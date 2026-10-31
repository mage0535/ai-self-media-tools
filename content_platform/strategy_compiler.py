"""Compile human-readable growth strategy into bounded generation policy."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


STRUCTURE_POOL = [
    "pain_reversal_tutorial",
    "real_demo_before_after",
    "failure_postmortem",
    "controversial_viewpoint",
    "saveable_checklist",
    "story_microcase",
]
CTA_POOL = ["specific_open_question", "identity_question", "choice_question", "save_reason"]


def compile_strategy(path: str | Path, platform: str) -> dict[str, Any]:
    source = Path(path)
    text = source.read_text(encoding="utf-8", errors="replace")
    normalized = str(platform or "").casefold()
    if "�" in text:
        raise ValueError("growth strategy contains mojibake")
    content_pillars = _extract_pillars(text)
    hook_templates = _extract_quoted(text, limit=8)
    kpis = _extract_kpis(text)
    strategy = {
        "version": "compiled_strategy_v1",
        "platform": normalized,
        "source_path": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "content_pillars": content_pillars or ["practical problem solving", "evidence-backed workflow", "saveable checklist"],
        "structure_pool": STRUCTURE_POOL,
        "hook_templates": hook_templates,
        "cta_pool": CTA_POOL,
        "kpi_hypotheses": kpis,
        "evidence_policy": {
            "numeric_claim_requires_source": True,
            "first_person_operation_requires_evidence": True,
            "strategy_claims_are_hypotheses_until_metrics_eligible": True,
        },
        "selection_policy": {
            "same_core_topic_same_day": "block",
            "cross_platform_resonance": "allow_only_with_different_angle_form_evidence",
            "shadow_can_report": True,
            "shadow_can_create_jobs": False,
        },
    }
    return strategy


def _extract_pillars(text: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [re.sub(r"[*#`]+", "", item).strip() for item in line.split("|")]
        if len(cells) >= 3 and any(token in " ".join(cells).casefold() for token in ("解决", "避坑", "对比", "教程", "效率", "痛点")):
            candidate = cells[1] or cells[0]
            if candidate and candidate not in values and not set(candidate) <= {"-", ":"}:
                values.append(candidate)
    return values[:8]


def _extract_quoted(text: str, limit: int) -> list[str]:
    values = re.findall(r"[「『“\"]([^」』”\"]{6,80})[」』”\"]", text)
    return list(dict.fromkeys(item.strip() for item in values))[:limit]


def _extract_kpis(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("5s完播率", "2s跳出率", "评论率", "点赞率", "收藏率", "完播率"):
        match = re.search(re.escape(key) + r"[^\n|]{0,40}?([<>≥≤]?\s*\d+(?:\.\d+)?%)", text, re.I)
        if match:
            result[key] = match.group(1).replace(" ", "")
    return result


def validate_compiled_strategy(strategy: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(strategy, dict):
        return {"passed": False, "failures": ["compiled_strategy_missing"]}
    for field in ("version", "platform", "source_sha256", "content_pillars", "structure_pool", "cta_pool", "evidence_policy"):
        if not strategy.get(field):
            failures.append(f"compiled_strategy_{field}_missing")
    if len(strategy.get("structure_pool") or []) < 5:
        failures.append("compiled_strategy_structure_pool_too_small")
    if strategy.get("selection_policy", {}).get("shadow_can_create_jobs") is not False:
        failures.append("compiled_strategy_shadow_publish_boundary_invalid")
    return {"passed": not failures, "failures": failures}


def build_strategy_evidence_contract(
    *,
    platform: str,
    lane: str,
    viral_collection: dict[str, Any] | None,
    viral_breakdown: dict[str, Any] | None,
    keyword_tool: dict[str, Any] | None,
    prompt_bundle: dict[str, Any] | None,
    reference_platform: str | None = None,
) -> dict[str, Any]:
    """Bind observed research outputs to the generation strategy.

    The compiler does not collect network data itself.  It records the
    outputs of the real collectors and makes their provenance a runtime
    input, so a caller cannot claim that a strategy used research it never
    supplied.
    """
    contract = {
        "version": "strategy_evidence_contract_v1",
        "platform": str(platform or "").casefold().strip(),
        "lane": str(lane or "").strip(),
        "viral_collection": dict(viral_collection or {}),
        "viral_breakdown": dict(viral_breakdown or {}),
        "keyword_tool": dict(keyword_tool or {}),
        "prompt_bundle": dict(prompt_bundle or {}),
    }
    reference = str(reference_platform or "").casefold().strip()
    if reference and reference != contract["platform"]:
        # A lane without its own public collector names the sibling platform it observed.
        contract["reference_platform"] = reference
    return contract


def validate_strategy_evidence_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Fail closed unless collection, analysis, keywords, and prompts exist."""
    failures: list[str] = []
    if not isinstance(contract, dict):
        return {"passed": False, "failures": ["strategy_evidence_contract_missing"]}
    platform = str(contract.get("platform") or "").casefold().strip()
    lane = str(contract.get("lane") or "").strip()
    if not platform:
        failures.append("strategy_evidence_platform_missing")
    if not lane:
        failures.append("strategy_evidence_lane_missing")

    collection = contract.get("viral_collection") or {}
    if not isinstance(collection, dict) or not collection.get("tool") or not collection.get("collected_at") or int(collection.get("sample_count") or 0) < 1:
        failures.append("viral_collection_missing_or_not_executed")

    breakdown = contract.get("viral_breakdown") or {}
    summary = breakdown.get("summary") if isinstance(breakdown, dict) else {}
    accepted = int((summary or {}).get("accepted_samples") or breakdown.get("accepted_samples", 0)) if isinstance(breakdown, dict) else 0
    samples = breakdown.get("samples") if isinstance(breakdown, dict) else []
    if not isinstance(breakdown, dict) or breakdown.get("status") != "ready" or accepted < 1 or not isinstance(samples, list) or not samples:
        failures.append("viral_breakdown_not_ready")
    native_roots = {
        "douyin": ("douyin.com", "iesdouyin.com"),
        "douyin_ai": ("douyin.com", "iesdouyin.com"),
        "douyin_pet": ("douyin.com", "iesdouyin.com"),
        "tiktok": ("tiktok.com",),
        "youtube": ("youtube.com", "youtu.be"),
        "bilibili": ("bilibili.com", "b23.tv"),
        "kuaishou": ("kuaishou.com", "gifshow.com", "kwai.com"),
        "zhihu": ("zhihu.com",),
        "juejin": ("juejin.cn",),
        "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
        "wechat": ("mp.weixin.qq.com", "weixin.qq.com"),
        "shipinhao": ("weixin.qq.com", "channels.weixin.qq.com"),
        "x": ("x.com", "twitter.com"),
        "twitter": ("x.com", "twitter.com"),
    }
    # Samples must be native to the lane, or to the sibling platform the contract declares.
    roots = native_roots.get(str(contract.get("reference_platform") or platform).casefold())
    if roots and isinstance(samples, list):
        non_native = []
        metadata_incomplete = False
        for sample in samples:
            url = str(sample.get("canonical_url") or sample.get("url") or "") if isinstance(sample, dict) else ""
            host = (urlparse(url).hostname or "").casefold()
            if not any(host == root or host.endswith("." + root) for root in roots):
                non_native.append(url or "missing_url")
            if isinstance(sample, dict):
                required = ("native_id", "canonical_url", "author", "published_at", "captured_at")
                missing = any(not str(sample.get(field) or "").strip() or str(sample.get(field)).casefold().startswith("unavailable") for field in required)
                has_metric = any(sample.get(field) not in (None, "") for field in ("views", "likes", "comments", "shares", "points", "metrics"))
                has_content_evidence = any(sample.get(field) not in (None, "", [], {}) for field in ("visual_evidence", "media_ref", "media_path", "raw_snapshot_ref"))
                if missing or not has_metric or not has_content_evidence:
                    metadata_incomplete = True
        if non_native:
            failures.append("viral_breakdown_cross_platform_samples")
        if metadata_incomplete:
            failures.append("viral_breakdown_sample_metadata_incomplete")

    keyword_tool = contract.get("keyword_tool") or {}
    queries = keyword_tool.get("queries") if isinstance(keyword_tool, dict) else []
    keyword_platform = str(keyword_tool.get("platform") or "").casefold() if isinstance(keyword_tool, dict) else ""
    keyword_lane = str(keyword_tool.get("lane") or "").strip() if isinstance(keyword_tool, dict) else ""
    if (
        not isinstance(keyword_tool, dict)
        or not keyword_tool.get("tool")
        or not isinstance(queries, list)
        or not [item for item in queries if str(item).strip()]
        or keyword_platform != platform
        or keyword_lane != lane
    ):
        failures.append("keyword_tool_missing_or_not_executed")

    prompt = contract.get("prompt_bundle") or {}
    prompt_validation = prompt.get("validation") if isinstance(prompt, dict) else {}
    if (
        not isinstance(prompt, dict)
        or not isinstance(prompt_validation, dict)
        or prompt_validation.get("passed") is not True
        or not prompt.get("fingerprint")
        or not prompt.get("evidence")
    ):
        failures.append("prompt_bundle_missing_or_invalid")
    return {"passed": not failures, "failures": list(dict.fromkeys(failures))}


def compact_compiled_strategy(compiled: dict | None) -> dict:
    """Return a bounded, JSON-safe excerpt of the compiled strategy for bounded_model_input."""
    if not isinstance(compiled, dict):
        return {}
    # Keep only essential wire-safe fields, drop large blobs
    keep = {"platform", "version", "pillars", "kpis", "phases", "constraints", "compiled_at", "source_path", "source_sha256"}
    out = {k: v for k, v in compiled.items() if k in keep}
    # Also keep any small list/dict fields under 1k chars when serialized
    import json
    for k, v in compiled.items():
        if k not in out:
            try:
                if len(json.dumps(v, ensure_ascii=False)) < 1024:
                    out[k] = v
            except Exception:
                pass
    return out
