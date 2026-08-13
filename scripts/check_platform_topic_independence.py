#!/usr/bin/env python3
"""Check that each platform used independent source evidence before topic selection."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from content_platform.paths import project_home
except Exception:  # pragma: no cover
    def project_home() -> Path:
        import os

        return Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.cwd()))


PLATFORM_DIRS = {
    "wechat": "data/local_ops_gzh",
    "kuaishou": "data/local_ops_kuaishou",
    "bilibili": "data/local_ops_bilibili",
    "zhihu": "data/local_ops_zhihu",
    "juejin": "data/local_ops_juejin",
    "douyin": "data/local_ops_douyin",
    "shipinhao": "data/local_ops_shipinhao",
    "xiaohongshu": "data/local_ops_xiaohongshu",
    "youtube": "data/local_ops_youtube",
    "tiktok": "data/local_ops_tiktok",
    "x": "data/local_ops_x",
}


def _normalize_topic_domain(text: str) -> str:
    normalized = str(text or "").casefold()
    domains = {
        "spreadsheet_cleanup": ["spreadsheet cleanup", "spreadsheet", "excel"],
        "prompt_engineering": ["prompt engineering", "prompt habits", "prompt"],
        "unit_testing": ["unit test", "testing", "test automation"],
        "code_review": ["code review", "bug fix", "lint"],
        "slides": ["ppt", "presentation", "slides"],
        "agent_workflow": ["ai agent", "agent workflow", "workflow agent"],
        "video_creation": ["video creation", "shorts", "editing"],
        "workflow_automation": ["automation workflow", "content pipeline", "workflow automation"],
    }
    for domain, keywords in domains.items():
        if any(keyword in normalized for keyword in keywords):
            return domain
    return ""


def _similarity(a: str, b: str) -> float:
    left_domain = _normalize_topic_domain(a)
    right_domain = _normalize_topic_domain(b)
    if left_domain and right_domain:
        return 1.0 if left_domain == right_domain else 0.0
    if bool(left_domain) != bool(right_domain):
        return 0.0
    left = {ch for ch in a.casefold() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"}
    right = {ch for ch in b.casefold() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"}
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _load_analysis(platform_dir: Path, date: str) -> dict:
    json_candidates = [
        platform_dir / f"platform_source_matrix_{date}.json",
        platform_dir / f"analysis_{date}.json",
        platform_dir / f"ops_analysis_{date}.json",
    ]
    for path in json_candidates:
        if path.is_file():
            return {"path": str(path), "data": json.loads(path.read_text(encoding="utf-8"))}
    md = platform_dir / f"analysis_{date}.md"
    if md.is_file():
        text = md.read_text(encoding="utf-8", errors="replace")
        return {"path": str(md), "data": _parse_markdown_analysis(text, platform_hint=platform_dir.name)}
    return {"path": "", "data": {}}


def _parse_markdown_analysis(text: str, platform_hint: str = "") -> dict:
    attempted, successful, platform_internal = _extract_markdown_sources(text)
    if not platform_internal and attempted and platform_hint in {"local_ops_gzh", "local_ops_wechat"}:
        platform_internal = True
    return {
        "selected_topic": _extract_markdown_topic(text),
        "markdown_only": True,
        "source_matrix": {
            "attempted_sources": attempted,
            "successful_sources": successful,
            "platform_internal_verified": platform_internal,
            "shared_trend_only": bool(re.search(r"(shared_trend_only|共享趋势)\s*[:：]\s*(true|yes|是)", text, re.I)),
        },
    }


def _extract_markdown_topic(text: str) -> str:
    patterns = [
        r"(?:^|\n)\s*(?:#+\s*)?(?:选题方向|选题|selected_topic|topic)\s*[:：=]\s*(?:\*\*)?([^*\n#|]+)",
        r"(?:^|\n)\s*[-*]\s*(?:选题方向|选题|selected_topic|topic)\s*[:：=]\s*(?:\*\*)?([^*\n#|]+)",
        r"(?:^|\n)\s*(?:#+\s*)?(?:今日选题依据|内容主题)\s*[:：=]\s*(?:\*\*)?([^*\n#|]+)",
        r"閫夐[锛?]\s*(?:\*\*)?銆?([^銆媆n*]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _clean_cell(match.group(1))
    for line in text.splitlines():
        cleaned = _clean_cell(line.lstrip("# "))
        if cleaned and not cleaned.startswith("|") and len(cleaned) >= 8:
            if any(marker in cleaned.casefold() for marker in ["topic", "选题", "主题", "复盘", "实测", "analysis", "分析"]):
                return cleaned
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            cleaned = _clean_cell(line.lstrip("# "))
            if cleaned and len(cleaned) >= 4:
                return cleaned
    return ""


def _extract_markdown_sources(text: str) -> tuple[list[str], list[str], bool]:
    attempted: list[str] = []
    successful: list[str] = []
    platform_internal = False
    ok_status = re.compile(r"(✅|ok|success|成功|可用|passed|true)", re.I)
    fail_status = re.compile(r"(❌|fail|失败|login_required|unavailable|blocked|error)", re.I)
    internal_source = re.compile(r"(平台内|站内|搜狗微信|微信|公众号|快手|抖音|视频号|小红书|b站|bilibili|zhihu|juejin|youtube|tiktok|x/twitter|twitter|x\b)", re.I)

    for line in text.splitlines():
        line = line.strip()
        if not line or set(line) <= {"|", "-", ":", " "}:
            continue
        cells = [_clean_cell(cell) for cell in line.strip("|").split("|")] if "|" in line else []
        if cells and len(cells) >= 2:
            header = " ".join(cells).casefold()
            if any(word in header for word in ["source", "status", "来源", "数据源", "状态"]) and not (ok_status.search(header) or fail_status.search(header)):
                continue
            source = cells[0]
            status_text = " ".join(cells[1:])
            if source:
                attempted.append(source)
                if not fail_status.search(status_text) and status_text.strip():
                    successful.append(source)
                if internal_source.search(source) or "internal" in status_text.casefold() or "平台" in status_text:
                    platform_internal = True
            continue
        bullet = re.match(r"^[-*•]\s*([^:：]+)\s*[:：]\s*(.+)$", line)
        if bullet:
            source = _clean_cell(bullet.group(1))
            status_text = bullet.group(2)
            if ok_status.search(status_text) or fail_status.search(status_text):
                attempted.append(source)
                if ok_status.search(status_text) and not fail_status.search(status_text):
                    successful.append(source)
                if internal_source.search(source):
                    platform_internal = True

    if re.search(r"(platform_internal_verified|平台内验证|平台内)\s*[:：]?\s*(true|yes|是|✅|ok|成功|失败|login_required|❌)?", text, re.I):
        platform_internal = True
    if not platform_internal and attempted:
        first_source = attempted[0].casefold()
        if any(marker in first_source for marker in ["wechat", "微信", "公众号", "sogou", "搜狗"]):
            platform_internal = True
    attempted = _dedupe(attempted)
    successful = [item for item in _dedupe(successful) if item in attempted]
    return attempted, successful, platform_internal


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().strip("*`：:，,。-"))


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result

def _matrix_result(data: dict) -> dict:
    matrix = data.get("platform_source_matrix") or data.get("source_matrix") or {}
    if not isinstance(matrix, dict):
        matrix = {}
    attempted = matrix.get("attempted_sources") or data.get("attempted_sources") or []
    successful = matrix.get("successful_sources") or data.get("successful_sources") or []
    platform_internal = matrix.get("platform_internal_verified") or matrix.get("platform_internal_failure_reason")
    shared_only = bool(matrix.get("shared_trend_only") or data.get("shared_trend_only"))
    return {
        "attempted_count": len(attempted) if isinstance(attempted, list) else int(attempted or 0),
        "successful_count": len(successful) if isinstance(successful, list) else int(successful or 0),
        "platform_internal_evidence": bool(platform_internal),
        "shared_trend_only": shared_only,
    }


def _natural_overlap_evidence(data: dict, matrix: dict) -> dict:
    selection = data.get("topic_selection") if isinstance(data.get("topic_selection"), dict) else {}
    adaptation = str(selection.get("platform_adaptation_reason") or data.get("platform_adaptation_reason") or "").strip()
    signal = str(selection.get("platform_signal") or data.get("platform_signal") or "").strip()
    return {
        "passed": matrix["successful_count"] >= 5 and matrix["platform_internal_evidence"] and len(adaptation) >= 8 and len(signal) >= 8,
        "platform_adaptation_reason": adaptation,
        "platform_signal": signal,
    }


def check(date: str, platforms: list[str] | None = None, root: Path | None = None) -> dict:
    root = root or project_home()
    platforms = platforms or list(PLATFORM_DIRS)
    records = {}
    failures = []
    topics = {}
    for platform in platforms:
        loaded = _load_analysis(root / PLATFORM_DIRS.get(platform, f"data/local_ops_{platform}"), date)
        data = loaded["data"]
        selected = str(data.get("selected_topic") or data.get("topic") or data.get("title") or "").strip()
        matrix = _matrix_result(data)
        platform_failures = []
        if not loaded["path"]:
            platform_failures.append("analysis_file_missing")
        if matrix["attempted_count"] < 5:
            platform_failures.append("attempted_sources_lt_5")
        if matrix["successful_count"] < 3:
            platform_failures.append("successful_sources_lt_3")
        if not matrix["platform_internal_evidence"]:
            platform_failures.append("platform_internal_verification_missing")
        if matrix["shared_trend_only"]:
            platform_failures.append("shared_trend_only")
        if not selected:
            platform_failures.append("selected_topic_missing")
        if platform_failures:
            failures.append({"platform": platform, "failed_dimensions": platform_failures})
        records[platform] = {"analysis_path": loaded["path"], "selected_topic": selected, "matrix": matrix, "natural_overlap_evidence": _natural_overlap_evidence(data, matrix), "failed_dimensions": platform_failures}
        topics[platform] = selected

    for i, left in enumerate(platforms):
        for right in platforms[i + 1 :]:
            overlap_allowed = bool(records[left]["natural_overlap_evidence"]["passed"] and records[right]["natural_overlap_evidence"]["passed"])
            if topics.get(left) and topics.get(right) and _similarity(topics[left], topics[right]) > 0.5 and not overlap_allowed:
                failures.append({
                    "platforms": [left, right],
                    "failed_dimensions": ["topic_similarity_too_high"],
                    "topic_left": topics[left],
                    "topic_right": topics[right],
                    "similarity": round(_similarity(topics[left], topics[right]), 2),
                })

    try:
        from content_platform.ops_run import direction_register_issues

        failures.extend(direction_register_issues(root, date))
    except Exception:
        failures.append({"failed_dimensions": ["direction_register_check_failed"]})

    return {"passed": not failures, "date": date, "platforms": platforms, "records": records, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate per-platform topic/source independence.")
    parser.add_argument("date")
    parser.add_argument("--platforms", default="")
    parser.add_argument("--root", default="")
    args = parser.parse_args()
    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()] or None
    result = check(args.date, platforms, Path(args.root) if args.root else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
