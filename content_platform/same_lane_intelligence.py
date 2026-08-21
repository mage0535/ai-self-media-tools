from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


NATIVE_DOMAINS: dict[str, tuple[str, ...]] = {
    "wechat": ("mp.weixin.qq.com",),
    "zhihu": ("zhihu.com", "zhuanlan.zhihu.com"),
    "juejin": ("juejin.cn",),
    "bilibili": ("bilibili.com", "b23.tv"),
    "kuaishou": ("kuaishou.com", "kwai.com"),
    "shipinhao": ("channels.weixin.qq.com", "weixin.qq.com"),
    "douyin": ("douyin.com", "iesdouyin.com"),
    "douyin_ai": ("douyin.com", "iesdouyin.com"),
    "douyin_pet": ("douyin.com", "iesdouyin.com"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
    "youtube": ("youtube.com", "youtu.be"),
    "tiktok": ("tiktok.com",),
    "x": ("x.com", "twitter.com"),
    "twitter": ("x.com", "twitter.com"),
}

GENERIC_OR_WRONG_LANE_DOMAINS = {
    "openai.com",
    "chatgpt.com",
    "gemini.google.com",
    "google.com",
    "baidu.com",
    "zhidao.baidu.com",
    "wikipedia.org",
    "github.com",
}

AI_LANE_TERMS = (
    "ai",
    "agent",
    "workflow",
    "automation",
    "automate",
    "chatbot",
    "n8n",
    "claude",
    "gpt",
    "qwen",
    "kimi",
    "ollama",
    "groq",
    "智能体",
    "自动化",
    "工作流",
    "效率",
    "教程",
    "工具",
    "提示词",
    "大模型",
    "办公",
    "提效",
)

PET_LANE_TERMS = ("猫", "狗", "宠物", "治愈", "喵", "汪", "pet", "cat", "dog")


def _host(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return parsed.netloc.casefold().removeprefix("www.")


def _domain_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _is_native_platform_url(platform: str, url: str) -> bool:
    domains = NATIVE_DOMAINS.get(str(platform).casefold())
    if not domains:
        return True
    return _domain_matches(_host(url), domains)


def _lane_terms(platform: str) -> tuple[str, ...]:
    if str(platform).casefold() == "douyin_pet":
        return PET_LANE_TERMS
    return AI_LANE_TERMS


def _lane_score(platform: str, text: str) -> int:
    haystack = str(text or "").casefold()
    return sum(1 for term in _lane_terms(platform) if term.casefold() in haystack)


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _sample_account(sample: dict[str, Any]) -> str:
    return str(
        sample.get("account")
        or sample.get("author")
        or sample.get("uploader")
        or sample.get("channel")
        or sample.get("source")
        or "unknown"
    )


def _sample_views(sample: dict[str, Any]) -> int:
    for key in ("views", "view_count", "play", "plays", "points", "likes"):
        value = _as_int(sample.get(key))
        if value:
            return value
    return 0


def filter_rankable_samples(platform: str, samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep platform-native, lane-relevant samples and record explicit rejection reasons."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in samples:
        sample = dict(raw)
        title = str(sample.get("title") or sample.get("desc") or sample.get("text") or "").strip()
        url = str(sample.get("url") or sample.get("source_url") or sample.get("webpage_url") or "").strip()
        host = _host(url)
        if not title:
            sample["reject_reason"] = "missing_title"
            rejected.append(sample)
            continue
        if not url:
            sample["reject_reason"] = "missing_url"
            rejected.append(sample)
            continue
        if not _is_native_platform_url(platform, url):
            sample["reject_reason"] = "non_native_domain"
            rejected.append(sample)
            continue
        if host in GENERIC_OR_WRONG_LANE_DOMAINS or any(host.endswith(f".{domain}") for domain in GENERIC_OR_WRONG_LANE_DOMAINS):
            sample["reject_reason"] = "generic_or_wrong_lane_domain"
            rejected.append(sample)
            continue
        if _lane_score(platform, f"{title} {sample.get('summary', '')} {sample.get('description', '')}") <= 0:
            sample["reject_reason"] = "lane_mismatch"
            rejected.append(sample)
            continue
        sample["title"] = title
        sample["url"] = url
        sample["account"] = _sample_account(sample)
        sample["views"] = _sample_views(sample)
        sample["evidence_quality"] = "platform_native_work"
        accepted.append(sample)
    accepted.sort(key=lambda row: (_sample_views(row), str(row.get("title") or "")), reverse=True)
    return accepted, rejected


def _detect_topic_patterns(samples: list[dict[str, Any]]) -> list[str]:
    patterns: Counter[str] = Counter()
    for sample in samples:
        title = str(sample.get("title") or "").casefold()
        if any(term in title for term in ("workflow", "automation", "n8n", "自动化", "工作流")):
            patterns["tool_workflow_tutorial"] += 1
        if any(term in title for term in ("tutorial", "guide", "how to", "教程", "保姆级", "从0")):
            patterns["step_by_step_tutorial"] += 1
        if any(term in title for term in ("vs", "compare", "对比", "横评")):
            patterns["comparison_review"] += 1
        if any(term in title for term in ("fail", "mistake", "wrong", "坑", "失败", "复盘")):
            patterns["failure_case_review"] += 1
        if any(term in title for term in ("build", "made", "demo", "实测", "案例", "生成")):
            patterns["result_first_demo"] += 1
    if not patterns:
        patterns["platform_native_case"] = len(samples)
    return [name for name, _count in patterns.most_common(8)]


def _proof_requirements(patterns: list[str]) -> list[str]:
    requirements = ["platform_native_work", "real_work_or_account_url"]
    if any(pattern in patterns for pattern in ("tool_workflow_tutorial", "step_by_step_tutorial", "result_first_demo")):
        requirements.extend(["screen_or_tool_stack_demo", "before_after_or_process_evidence"])
    if "comparison_review" in patterns:
        requirements.append("side_by_side_comparison_evidence")
    if "failure_case_review" in patterns:
        requirements.append("failure_symptom_and_fix_evidence")
    return list(dict.fromkeys(requirements))


def _recommended_moves(platform: str, patterns: list[str], own_data_status: str) -> list[str]:
    moves = [
        "start from one concrete pain point, not a generic AI news headline",
        "show a concrete tool stack or visible workflow proof before making claims",
        "bind every scene or paragraph to evidence, demo, case, or actionable step",
    ]
    if "tool_workflow_tutorial" in patterns:
        moves.append("package the topic as a concrete tool stack tutorial with a result-first hook")
    if "result_first_demo" in patterns:
        moves.append("open with the finished result, then explain the minimum reproducible path")
    if own_data_status == "insufficient":
        moves.append("treat this as competitor-inspired guidance only; do not auto-tune strategy from own metrics yet")
    if platform in {"youtube", "bilibili"}:
        moves.append("use screen recordings, section chapters, and proof captions instead of static knowledge cards")
    return moves


def _top_accounts(samples: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"account": "", "work_count": 0, "total_views": 0, "sample_titles": []})
    for sample in samples:
        account = _sample_account(sample)
        row = grouped[account]
        row["account"] = account
        row["work_count"] += 1
        row["total_views"] += _sample_views(sample)
        if len(row["sample_titles"]) < 3:
            row["sample_titles"].append(str(sample.get("title") or ""))
    return sorted(grouped.values(), key=lambda row: (row["total_views"], row["work_count"]), reverse=True)[:limit]


def _top_works(samples: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    works = []
    for sample in samples[:limit]:
        works.append(
            {
                "title": sample.get("title", ""),
                "url": sample.get("url", ""),
                "account": _sample_account(sample),
                "views": _sample_views(sample),
            }
        )
    return works


def _own_data_status(own_metrics_readiness: dict[str, Any] | None) -> str:
    if not own_metrics_readiness:
        return "unknown"
    return "usable" if _as_int(own_metrics_readiness.get("strategy_eligible_count")) > 0 else "insufficient"


def distill_same_lane_samples(
    platform: str,
    samples: list[dict[str, Any]],
    own_metrics_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    accepted, rejected = filter_rankable_samples(platform, samples)
    own_status = _own_data_status(own_metrics_readiness)
    patterns = _detect_topic_patterns(accepted)
    proof = _proof_requirements(patterns)
    return {
        "version": "same_lane_playbook_v1",
        "platform": platform,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample_count": len(samples),
        "accepted_sample_count": len(accepted),
        "rejected_sample_count": len(rejected),
        "own_data_status": own_status,
        "strategy_claim_boundary": "own_metrics_data_driven" if own_status == "usable" else "competitor_inspired_not_auto_tuned",
        "evidence_quality": sorted({row.get("evidence_quality", "") for row in accepted if row.get("evidence_quality")}),
        "top_accounts": _top_accounts(accepted),
        "top_works": _top_works(accepted),
        "topic_patterns": patterns,
        "hook_patterns": ["result-first hook", "specific tool plus outcome", "pain point before method"],
        "structure_patterns": ["result -> pain -> stack -> steps -> boundary -> CTA"],
        "visual_patterns": ["screen demo", "before/after", "chapter cards only as support"],
        "proof_requirements": proof,
        "recommended_content_moves": _recommended_moves(platform, patterns, own_status),
        "rejected_examples": [
            {"title": row.get("title", ""), "url": row.get("url", ""), "reject_reason": row.get("reject_reason", "")}
            for row in rejected[:8]
        ],
        "generation_rules": [
            "do not use generic AI news as a platform-native trend",
            "do not generate if every accepted same-lane sample is missing visible proof",
            "if own metrics are insufficient, label output as competitor-inspired guidance",
            "if samples are rejected for duplicate or wrong-lane assets, re-search before blocking the platform",
        ],
    }


def _flatten_platform_samples(platform: str, payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get(platform), list):
        return [dict(row) for row in payload[platform] if isinstance(row, dict)]
    if isinstance(payload.get("samples"), list):
        return [dict(row) for row in payload["samples"] if isinstance(row, dict)]
    if isinstance(payload.get("recent_works"), list):
        return [dict(row) for row in payload["recent_works"] if isinstance(row, dict)]
    if isinstance(payload.get("accounts"), list):
        rows: list[dict[str, Any]] = []
        for account in payload["accounts"]:
            if not isinstance(account, dict):
                continue
            account_name = str(account.get("account") or account.get("name") or account.get("channel") or "")
            for work in account.get("recent_works") or account.get("works") or []:
                if isinstance(work, dict):
                    rows.append({**work, "account": work.get("account") or account_name})
        return rows
    if isinstance(payload.get("keywords"), list):
        rows = []
        for entry in payload["keywords"]:
            if isinstance(entry, dict):
                for row in entry.get("samples") or entry.get("items") or []:
                    if isinstance(row, dict):
                        rows.append(row)
        return rows
    if isinstance(payload.get("platforms"), dict) and isinstance(payload["platforms"].get(platform), dict):
        return _flatten_platform_samples(platform, payload["platforms"][platform])
    return []


def load_samples_file(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    platforms = set(NATIVE_DOMAINS)
    if isinstance(payload, dict):
        platforms.update(str(key) for key in payload)
    return {platform: _flatten_platform_samples(platform, payload) for platform in sorted(platforms)}


def build_same_lane_report(
    samples_by_platform: dict[str, list[dict[str, Any]]],
    platforms: list[str] | None = None,
    own_metrics_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = platforms or sorted(samples_by_platform)
    reports = {}
    for platform in selected:
        readiness = (own_metrics_readiness or {}).get(platform) if isinstance((own_metrics_readiness or {}).get(platform), dict) else own_metrics_readiness
        reports[platform] = distill_same_lane_samples(platform, samples_by_platform.get(platform, []), readiness)
    return {
        "ok": True,
        "version": "same_lane_intelligence_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platforms": selected,
        "reports": reports,
    }
