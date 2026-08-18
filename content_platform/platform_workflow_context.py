"""Strict platform workflow context loading.

Every content workflow must materialize this context before generation.  The
context is evidence, not a prompt claim: files are resolved and hashed, the
platform rulebook is checked, and required skills are verified on disk.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK = ROOT / "config" / "channel_content_rulebook.json"
RULES_FILE = ROOT / "data" / "platform_rules_2026.md"
STRATEGY_DIR = ROOT / "data"

GENERIC_SKILLS = [
    "content/channel-operations-workflow",
    "content/visual-quality-standards",
]
PLATFORM_SKILLS = {
    "kuaishou": ["content/kuaishou-content-publishing", "content/kuaishou-publishing-workflow"],
    "tiktok": ["content/intl-short-video-pipeline"],
    "youtube": ["content/intl-short-video-pipeline"],
    "bilibili": ["content/channel-operations-workflow"],
    "shipinhao": ["content/kuaishou-content-publishing"],
    "xiaohongshu": ["content/xiaohongshu-content-enhancer"],
    "wechat": ["wechat-pipeline-v2"],
    "zhihu": ["content/zhihu-publishing-workflow"],
    "juejin": ["content/juejin-publishing-workflow"],
    "douyin": ["douyin-repost-workflow"],
    "douyin_ai": ["douyin-daily-analysis-workflow"],
    "douyin_pet": ["douyin-repost-workflow"],
    "x": ["social-media/x-twitter-autopublish"],
    "twitter": ["social-media/x-twitter-autopublish"],
}
PUBLISH_MODES = {
    "kuaishou": "automatic_scheduled",
    "x": "automatic",
    "twitter": "automatic",
    "wechat": "draft",
    "zhihu": "draft",
    "juejin": "draft",
}
for _platform in {"tiktok", "youtube", "bilibili", "shipinhao", "douyin", "douyin_ai", "douyin_pet", "xiaohongshu"}:
    PUBLISH_MODES.setdefault(_platform, "manual_handoff")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _skill_path(name: str) -> Path:
    candidates = [Path.home() / ".hermes" / "skills" / name / "SKILL.md"]
    if name.startswith("content/"):
        candidates.append(Path.home() / ".hermes" / "skills" / name.split("/", 1)[1] / "SKILL.md")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _latest_strategy(platform: str) -> Path | None:
    candidates = sorted(STRATEGY_DIR.glob("growth_strategy_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    platform = platform.casefold()
    # Exact platform strategy mapping; substring matching would map `x` to `xhs`.
    prefixes = {
        "xiaohongshu": ["growth_strategy_xhs_"],
        "xhs": ["growth_strategy_xhs_"],
        "douyin_ai": ["growth_strategy_douyin_ai_"],
        "douyin": ["growth_strategy_20260816"],
        "douyin_pet": ["growth_strategy_20260816"],
        "x": ["growth_strategy_20260816"],
        "twitter": ["growth_strategy_20260816"],
    }
    wanted = prefixes.get(platform, ["growth_strategy_20260816"])
    for prefix in wanted:
        exact = [p for p in candidates if p.name.startswith(prefix)]
        if exact:
            return exact[0]
    return candidates[0] if candidates else None


def _platform_rule_loaded(platform: str) -> tuple[bool, str]:
    aliases = {
        "kuaishou": ["快手"], "tiktok": ["tiktok"], "youtube": ["youtube"],
        "bilibili": ["b站", "bilibili"], "shipinhao": ["视频号"], "wechat": ["公众号"],
        "xiaohongshu": ["小红书"], "zhihu": ["知乎"], "juejin": ["掘金"],
        "douyin": ["抖音"], "douyin_ai": ["抖音"], "douyin_pet": ["抖音"],
        "x": ["twitter"], "twitter": ["twitter"],
    }
    names = aliases.get(platform, [platform])
    fallback = Path.home() / ".hermes" / "skills" / "content" / "platform-ops-rules-2026" / "SKILL.md"
    candidates = [RULES_FILE, fallback]
    matched = False
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        if any(name.casefold() in text for name in names):
            matched = True
            break
    return (RULES_FILE.is_file(), "" if RULES_FILE.is_file() else "platform_rules_2026.md missing")


def load_platform_workflow_context(platform: str, *, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load and validate runtime context; raise on missing mandatory inputs."""
    platform = str(platform or "").casefold().strip()
    if platform in {"file", "demo"}:
        return {
            "version": "platform_workflow_context_v1",
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "platform": platform,
            "rulebook": {"path": str(RULEBOOK), "entry_loaded": False, "adapter": "local_test_or_file"},
            "platform_rules_2026": {"path": str(RULES_FILE), "matched": False, "adapter": "local_test_or_file"},
            "strategy": {"path": "local_test_adapter", "sha256": ""},
            "skills": [], "publish_mode": "file", "selected_tools": ["file_publisher"],
            "plan": {}, "loaded": True, "adapter": "local_test_or_file",
        }
    if not platform:
        raise ValueError("platform workflow context requires a platform")
    plan = plan or {}
    if not RULEBOOK.is_file():
        raise FileNotFoundError(str(RULEBOOK))
    rulebook = json.loads(RULEBOOK.read_text(encoding="utf-8"))
    channel_rules = rulebook.get("channel_rules") or rulebook.get("channels") or rulebook.get("platforms") or rulebook
    rule_entry = channel_rules.get(platform) if isinstance(channel_rules, dict) else None
    if not isinstance(rule_entry, dict):
        # account variants (douyin_ai/douyin_pet) inherit the base channel rulebook
        if platform.startswith("douyin_"):
            rule_entry = channel_rules.get("douyin") if isinstance(channel_rules, dict) else None
    if not isinstance(rule_entry, dict):
        # aliases used by the rulebook
        aliases = {"x": "twitter", "twitter": "x", "gzh": "wechat", "weixin": "wechat"}
        rule_entry = channel_rules.get(aliases.get(platform, "")) if isinstance(channel_rules, dict) else None
    if not isinstance(rule_entry, dict):
        raise ValueError(f"platform rulebook entry missing: {platform}")
    rules_ok, rules_reason = _platform_rule_loaded(platform)
    if not rules_ok:
        raise ValueError(f"2026 platform rules missing for {platform}: {rules_reason}")

    strategy = _latest_strategy(platform)
    if strategy is None or not strategy.is_file():
        raise FileNotFoundError(f"growth strategy missing for {platform}")
    required_skills = list(dict.fromkeys(GENERIC_SKILLS + PLATFORM_SKILLS.get(platform, [])))
    skill_records = []
    missing = []
    for skill in required_skills:
        path = _skill_path(skill)
        record = {"name": skill, "path": str(path), "exists": path.is_file()}
        if path.is_file():
            record["sha256"] = _sha256(path)
        else:
            missing.append(skill)
        skill_records.append(record)
    if missing:
        raise FileNotFoundError(f"required platform skills missing: {', '.join(missing)}")

    selected_tools = plan.get("selected_tools") or plan.get("tools") or []
    if not selected_tools:
        selected_tools = [
            "platform_rules_loader", "growth_strategy_loader", "channel_operations_workflow",
            "content_strategy", "visual_quality_gate", "platform_renderer", "publish_mode_guard",
        ]
    context = {
        "version": "platform_workflow_context_v1",
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "rulebook": {"path": str(RULEBOOK), "entry_loaded": True},
        "platform_rules_2026": {"path": str(RULES_FILE), "matched": True},
        "strategy": {"path": str(strategy), "sha256": _sha256(strategy)},
        "skills": skill_records,
        "publish_mode": PUBLISH_MODES.get(platform, "manual_handoff"),
        "selected_tools": list(dict.fromkeys(map(str, selected_tools))),
        "plan": {"template_family": plan.get("template_family", ""), "selected_pipeline": plan.get("selected_pipeline", "")},
        "loaded": True,
    }
    return context


def write_platform_workflow_context(output_dir: str | Path, platform: str, *, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    context = load_platform_workflow_context(platform, plan=plan)
    path = Path(output_dir) / "platform_workflow_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    context["path"] = str(path)
    return context
