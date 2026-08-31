#!/usr/bin/env python3
"""Deterministic semantic validation backed by Cloudflare Workers AI vision."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence

try:
    from content_platform.image_provider import load_secret
except ModuleNotFoundError:  # Allow direct execution from outside the repository root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from content_platform.image_provider import load_secret


DEFAULT_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct"
DEFAULT_THRESHOLD = 0.6
ANALYZER_NAME = "cloudflare_workers_ai"


class AnalyzerError(RuntimeError):
    """Raised when the configured analyzer cannot return trustworthy output."""


_SYNONYM_GROUPS = (
    ("ai", "artificial intelligence", "人工智能", "智能助手"),
    ("cat", "cats", "feline", "kitten", "猫", "猫咪"),
    ("dog", "dogs", "canine", "puppy", "狗", "狗狗"),
    ("phone", "smartphone", "mobile", "cellphone", "手机", "智能手机"),
    ("computer", "laptop", "notebook", "电脑", "笔记本电脑"),
    ("dashboard", "control panel", "digital display", "digital displays", "digital interface", "digital interfaces", "display", "screen", "仪表盘", "控制面板"),
    ("workflow", "process", "connected devices", "connected device", "connect", "wires", "wire", "流程", "工作流"),
    ("person", "people", "human", "人物", "人", "用户"),
    ("text", "words", "typography", "文字", "文本"),
    ("agent", "software agent", "ai agent", "robot", "assistant", "机器人", "智能体"),
    ("search", "information retrieval", "retrieval", "magnifying glass", "searching", "检索", "搜索"),
    ("loop", "repetitive", "repeated", "daily", "cycle", "circular arrows", "循环", "重复"),
    ("archive", "memory archive", "bookshelf", "bookshelves", "library", "books", "documents", "document", "papers", "folders", "organized boxes", "档案", "归档", "文档", "书架"),
    ("identity", "profile card", "id card", "profile", "personal information", "avatar card", "身份", "个人资料"),
    ("time", "clock", "calendar", "deadline", "watch", "hourglass", "时间", "日历", "时钟", "沙漏"),
    ("office", "workspace", "办公室", "办公空间"),
)


def _normalized_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w\u3400-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _canonicalize(text: str) -> str:
    normalized = f" {_normalized_text(text)} "
    for group in _SYNONYM_GROUPS:
        canonical = group[0]
        for synonym in sorted(group, key=len, reverse=True):
            candidate = _normalized_text(synonym)
            if not candidate:
                continue
            if re.search(r"[\u3400-\u9fff]", candidate):
                normalized = normalized.replace(candidate, f" {canonical} ")
            else:
                normalized = re.sub(rf"(?<!\w){re.escape(candidate)}(?!\w)", f" {canonical} ", normalized)
    return " ".join(normalized.split())


def _tokens(text: str) -> set[str]:
    canonical = _canonicalize(text)
    latin = set(re.findall(r"[a-z0-9]+", canonical))
    cjk = set(re.findall(r"[\u3400-\u9fff]", canonical))
    return latin | cjk


def score_semantics(expected_concepts: Sequence[str], caption: str, labels: Sequence[str]) -> tuple[float, list[str]]:
    """Score grounded concept coverage without trusting a model score.

    Provider queries and editorial titles often describe the same subject at
    different levels of detail. Reward one strongly grounded concept while
    retaining a smaller penalty for ungrounded companion concepts.
    """
    expected = [str(item).strip() for item in expected_concepts if str(item).strip()]
    if not expected:
        return 1.0, []
    observed_tokens = _tokens(" ".join([caption, *labels]))
    coverages: list[float] = []
    matched_concepts: list[str] = []
    for concept in expected:
        concept_tokens = _tokens(concept)
        if not concept_tokens:
            continue
        overlap = concept_tokens & observed_tokens
        coverage = len(overlap) / len(concept_tokens)
        coverages.append(coverage)
        if coverage >= 0.25:
            matched_concepts.append(concept)
    if not coverages:
        return 0.0, []
    concept_match_rate = len(matched_concepts) / len(coverages)
    token_coverage = sum(coverages) / len(coverages)
    score = 0.7 * concept_match_rate + 0.3 * token_coverage
    return round(min(1.0, score), 6), matched_concepts


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def empty_result(
    image_path: str | Path,
    expected_concepts: Sequence[str],
    *,
    ok: bool = False,
    model: str = "",
    caption: str = "",
    labels: Sequence[str] = (),
    score: float = 0.0,
    threshold: float = DEFAULT_THRESHOLD,
    passed: bool = False,
) -> dict[str, Any]:
    path = Path(image_path)
    return {
        "version": "image_semantic_evidence_v1",
        "ok": bool(ok),
        "analyzer": ANALYZER_NAME,
        "model": model or os.environ.get("CLOUDFLARE_VISION_MODEL", DEFAULT_MODEL),
        "caption": str(caption),
        "labels": [str(item) for item in labels],
        "expected_concepts": [str(item) for item in expected_concepts],
        "matched_concepts": [],
        "semantic_match_score": float(score),
        "threshold": float(threshold),
        "passed": bool(passed),
        "output_sha256": _sha256(path),
        "image_sha256": _sha256(path),
        "score_source": "deterministic_caption_label_recall",
        "evidence_level": "artifact_verified" if ok else "unavailable",
    }


def _extract_model_output(payload: Any) -> tuple[str, list[str]]:
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise AnalyzerError("Cloudflare returned an unsuccessful response")
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("response"), dict):
        result = result["response"]
    if isinstance(result, dict) and isinstance(result.get("response"), str):
        raw = result["response"].strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            raw = fenced.group(1)
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            # Some multimodal deployments ignore JSON mode. The prose is still
            # observed-image evidence; derive labels locally and never accept a
            # model-supplied numeric score.
            labels = _labels_from_caption(raw)
            if len(raw) < 20 or len(labels) < 2:
                raise AnalyzerError("Cloudflare vision prose response was not descriptive enough")
            return raw, labels
    if not isinstance(result, dict):
        raise AnalyzerError("Cloudflare vision response had no result object")
    caption = result.get("caption")
    labels = result.get("labels")
    if not isinstance(caption, str) or not caption.strip():
        raise AnalyzerError("Cloudflare vision response had no caption")
    if not isinstance(labels, list) or any(not isinstance(item, str) for item in labels):
        raise AnalyzerError("Cloudflare vision response had invalid labels")
    return caption.strip(), [item.strip() for item in labels if item.strip()]


def _labels_from_caption(caption: str) -> list[str]:
    stop = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "in", "is",
        "it", "of", "on", "or", "that", "the", "this", "to", "with", "visible", "image", "shows",
    }
    labels: list[str] = []
    for token in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]{2,8}", _normalized_text(caption)):
        if token in stop or len(token) < 2 or token in labels:
            continue
        labels.append(token)
        if len(labels) >= 24:
            break
    return labels


def analyze_image(
    image_path: str | Path,
    expected_concepts: Sequence[str],
    *,
    role: str = "",
    platform: str = "",
    threshold: float | None = None,
) -> dict[str, Any]:
    path = Path(image_path)
    if not path.is_file():
        raise AnalyzerError(f"target image does not exist: {path}")
    account_id = load_secret("CLOUDFLARE_ACCOUNT_ID")
    api_token = load_secret("CLOUDFLARE_API_TOKEN") or load_secret("CF_WORKER_KEY")
    if not account_id or not api_token:
        raise AnalyzerError("Cloudflare Workers AI credentials are unavailable")
    model = os.environ.get("CLOUDFLARE_VISION_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    configured_threshold = threshold
    if configured_threshold is None:
        try:
            configured_threshold = float(os.environ.get("IMAGE_SEMANTIC_THRESHOLD", DEFAULT_THRESHOLD))
        except ValueError as exc:
            raise AnalyzerError("IMAGE_SEMANTIC_THRESHOLD must be numeric") from exc
    if not 0.0 <= configured_threshold <= 1.0:
        raise AnalyzerError("semantic threshold must be between 0 and 1")

    context = ", ".join(part for part in (f"role={role}" if role else "", f"platform={platform}" if platform else "") if part)
    prompt = (
        "Analyze this image. Return only a JSON object with a non-empty caption string and a labels array of "
        "concise visible concepts. Do not return confidence or match scores."
    )
    if context:
        prompt += f" Content context: {context}."
    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    body = json.dumps(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": 512,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "type": "object",
                    "properties": {
                        "caption": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["caption", "labels"],
                },
            },
        }
    ).encode("utf-8")
    quoted_model = urllib.parse.quote(model, safe="/@")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{quoted_model}"
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "User-Agent": "ai-self-media-tools/image-semantic-analyzer",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
        except OSError:
            detail = ""
        raise AnalyzerError(f"Cloudflare vision HTTP {exc.code}: {detail}") from exc
    except (OSError, urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalyzerError("Cloudflare vision request failed or returned invalid JSON") from exc
    caption, labels = _extract_model_output(payload)
    score, matched = score_semantics(expected_concepts, caption, labels)
    result = empty_result(
        path,
        expected_concepts,
        ok=True,
        model=model,
        caption=caption,
        labels=labels,
        score=score,
        threshold=configured_threshold,
        passed=score >= configured_threshold,
    )
    result["matched_concepts"] = matched
    return result


def _load_expected_json(value: str) -> list[str]:
    candidate = Path(value)
    try:
        raw = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalyzerError("--expected-json must be valid JSON or a readable JSON file") from exc
    if isinstance(payload, dict):
        payload = payload.get("expected_concepts", payload.get("concepts", payload.get("expected")))
    if isinstance(payload, str):
        payload = [payload]
    if not isinstance(payload, list) or any(not isinstance(item, str) for item in payload):
        raise AnalyzerError("--expected-json must contain a string list")
    return [item.strip() for item in payload if item.strip()]


def _expected_values(expected_json: str, expected_args: Sequence[str]) -> list[str]:
    values = _load_expected_json(expected_json) if expected_json else []
    for item in expected_args:
        values.extend(part.strip() for part in item.split(",") if part.strip())
    return list(dict.fromkeys(values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_image", help="Image file to analyze")
    parser.add_argument("--expected-json", default="", help="JSON text/file containing expected concepts")
    parser.add_argument("--expected", action="append", default=[], help="Expected concept; repeat or comma-separate")
    parser.add_argument("--role", default="", help="Image role context, such as cover or scene")
    parser.add_argument("--platform", default="", help="Destination platform context")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    expected: list[str] = []
    try:
        expected = _expected_values(args.expected_json, args.expected)
        result = analyze_image(args.target_image, expected, role=args.role, platform=args.platform)
    except (AnalyzerError, OSError) as exc:
        result = empty_result(args.target_image, expected)
        print(f"image semantic analyzer unavailable: {exc}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("passed") is True else 3


if __name__ == "__main__":
    raise SystemExit(main())
