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

from .content_policy import delivery_mode
from .strategy_compiler import compile_strategy, validate_compiled_strategy
from .content_quality_reference import load_content_quality_reference_pack, validate_content_quality_reference_pack
from .runtime_capabilities import build_runtime_capability_snapshot
from .tool_selection import build_tool_selection_evidence
from .overnight_batch import load_hot_work_parameter_pack_compact
from .preflight_manifest import REQUIRED_SKILLS_BY_CHANNEL, required_workflow_skills

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK = ROOT / "config" / "channel_content_rulebook.json"
RULES_FILE = ROOT / "data" / "platform_rules_2026.md"
PUBLIC_RULES_FILE = ROOT / "config" / "platform_rules_2026.md"
STRATEGY_DIR = ROOT / "data"
PUBLIC_STRATEGY_DIR = ROOT / "config"

GENERIC_SKILLS = sorted(set.intersection(*(set(required_workflow_skills(name)) for name in REQUIRED_SKILLS_BY_CHANNEL)))
PLATFORM_SKILLS = {
    name: [skill for skill in required_workflow_skills(name) if skill not in GENERIC_SKILLS]
    for name in REQUIRED_SKILLS_BY_CHANNEL
}
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _skill_path(name: str) -> Path:
    repo_skills = ROOT / "skills"
    candidates = [Path.home() / ".hermes" / "skills" / name / "SKILL.md"]
    if name.startswith("content/"):
        candidates.append(Path.home() / ".hermes" / "skills" / name.split("/", 1)[1] / "SKILL.md")
        candidates.append(repo_skills / name / "SKILL.md")
        candidates.append(repo_skills / "content" / name.split("/", 1)[1] / "SKILL.md")
    else:
        candidates.append(repo_skills / name / "SKILL.md")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _latest_strategy(platform: str) -> Path | None:
    candidates = sorted(STRATEGY_DIR.glob("growth_strategy_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        candidates = sorted(PUBLIC_STRATEGY_DIR.glob("growth_strategy_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
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
    candidates = [RULES_FILE, PUBLIC_RULES_FILE, fallback]
    matched = False
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        if any(name.casefold() in text for name in names):
            matched = True
            break
    return (matched, "" if matched else "2026 platform rule section missing")


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
    if platform in {"kuaishou", "tiktok", "youtube", "bilibili", "shipinhao", "wechat", "xiaohongshu", "zhihu", "juejin", "douyin", "douyin_ai", "douyin_pet", "x", "twitter"} and not rules_ok:
        raise ValueError(f"2026 platform rules missing for {platform}: {rules_reason}")

    strategy = _latest_strategy(platform)
    strict_runtime = bool(plan.get("run_contract"))
    if strategy is None and not strict_runtime:
        strategy = ROOT / "config" / "default_growth_strategy.md"
    compiled_strategy = None
    if strategy is None or not strategy.is_file():
        if strict_runtime:
            raise FileNotFoundError(f"growth strategy missing for {platform}")
        strategy_gate = {"passed": False, "failures": ["growth_strategy_missing_legacy_adapter"]}
    else:
        compiled_strategy = compile_strategy(strategy, platform)
        strategy_gate = validate_compiled_strategy(compiled_strategy)
        if not strategy_gate["passed"]:
            raise ValueError("compiled growth strategy invalid: " + ", ".join(strategy_gate["failures"]))
    required_skills = required_workflow_skills(platform)
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
    if missing and strict_runtime:
        raise FileNotFoundError(f"required platform skills missing: {', '.join(missing)}")

    runtime_capabilities = build_runtime_capability_snapshot()
    tool_evidence = build_tool_selection_evidence(
        platform=platform,
        content_type=str(plan.get("content_form") or plan.get("stage") or "article"),
        content_goal="select an executable, platform-matched tool stack before generation",
        capability_status={"tools": runtime_capabilities.get("tools") or {}},
        video_effect_registry=runtime_capabilities.get("video_effect_modules") or {},
        planned_manifest=plan.get("tool_invocation_manifest") or {},
    )
    plan.update(tool_evidence)
    selected_tools = list(dict.fromkeys(tool_evidence["tool_selection_plan"].get("selected_tools") or []))
    if not selected_tools:
        raise RuntimeError(f"no executable tools available for platform={platform}")
    selected_tools.append("content_quality_reference_pack")
    quality_reference_pack = load_content_quality_reference_pack(
        platform,
        content_form=str(plan.get("content_form") or plan.get("stage") or ""),
    )
    quality_reference_gate = validate_content_quality_reference_pack(quality_reference_pack)
    context = {
        "version": "platform_workflow_context_v1",
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "rulebook": {"path": str(RULEBOOK), "entry_loaded": True},
        "platform_rules_2026": {"path": str(RULES_FILE if RULES_FILE.is_file() else PUBLIC_RULES_FILE), "matched": True},
        "strategy": {
            "path": str(strategy) if strategy else "",
            "sha256": _sha256(strategy) if strategy else "",
            "compiled": compiled_strategy,
            "compiled_gate": strategy_gate,
        },
        "skills": skill_records,
        "content_quality_reference_pack": quality_reference_pack,
        "content_quality_reference_gate": quality_reference_gate,
        "runtime_capabilities": runtime_capabilities,
        "hot_work_parameter_pack": load_hot_work_parameter_pack_compact(platform),
        "publish_mode": delivery_mode(platform),
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
