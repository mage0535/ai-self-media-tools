"""Strict platform workflow context loading.

Every content workflow must materialize this context before generation.  The
context is evidence, not a prompt claim: files are resolved and hashed, the
platform rulebook is checked, and required skills are verified on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .strategy_compiler import compile_strategy, validate_compiled_strategy
from .content_quality_reference import load_content_quality_reference_pack, validate_content_quality_reference_pack
from .runtime_capabilities import build_runtime_capability_snapshot
from .tool_selection import build_tool_selection_evidence
from .overnight_batch import load_hot_work_parameter_pack_compact
from .wechat_blowup_intelligence import load_wechat_blowup_compact
from .real_world_ai_policy import load_real_world_ai_positioning
from .platform_intelligence_status import load_platform_intelligence_runtime_constraints

try:
    from .distilled_loader import load_distilled_per_account_compact  # first-load distilled per-account
except Exception:
    load_distilled_per_account_compact = None  # fallback if not yet deployed

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK = ROOT / "config" / "channel_content_rulebook.json"
RULES_FILE = ROOT / "data" / "platform_rules_2026.md"
PUBLIC_RULES_FILE = ROOT / "config" / "platform_rules_2026.md"
STRATEGY_DIR = ROOT / "data"
PUBLIC_STRATEGY_DIR = ROOT / "config"


def _wechat_blowup_latest_path() -> Path:
    """Resolve the shared runtime data directory at call time, not import time."""
    data_dir = Path(os.environ.get("CONTENT_PLATFORM_DATA_DIR") or ROOT / "data")
    return data_dir / "intel" / "wechat_blowup_intelligence_latest.json"


def _cross_platform_discovery_compact(platform: str) -> dict[str, Any]:
    """Load only discovery metadata; it never upgrades to native work evidence."""
    data_dir = Path(os.environ.get("CONTENT_PLATFORM_DATA_DIR") or ROOT / "data")
    path = data_dir / "intel" / "cross_platform_real_world_ai_discovery_latest.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "cross_platform_real_world_ai_discovery_v1", "status": "missing", "candidates": [], "generation_only": True}
    candidates = [
        {key: row.get(key) for key in ("content_id", "canonical_url", "title", "pillar")}
        for row in raw.get("candidates") or []
        if isinstance(row, dict) and str(row.get("platform") or "").casefold() == platform
    ]
    return {
        "version": raw.get("version") or "cross_platform_real_world_ai_discovery_v1",
        "status": (raw.get("platform_status") or {}).get(platform, "not_available"),
        "observed_at": raw.get("observed_at"),
        "source_class": raw.get("source_class"),
        "generation_only": True,
        "auto_selection_eligible": False,
        "viral_claim_eligible": False,
        "candidates": candidates,
    }


def _compact_dual_lane_work_plan(value: Any, platform: str) -> dict[str, Any]:
    """Project a plan's decision metadata, never raw observations or credentials."""
    if not isinstance(value, dict) or value.get("version") != "dual_lane_work_plan_v1":
        return {"status": "missing"}
    if str(value.get("platform") or "").casefold() != platform:
        return {"status": "platform_mismatch"}
    permissions = value.get("permissions") if isinstance(value.get("permissions"), dict) else {}
    if permissions.get("allow_viral_claims") is not False or permissions.get("allow_automated_learning") is not False:
        return {"status": "rejected", "reason_codes": ["dual_lane_permissions_must_remain_fail_closed"]}
    scenario = value.get("scenario_contract") if isinstance(value.get("scenario_contract"), dict) else {}
    required_scenario = ("actor", "inputs", "process", "outcome", "boundaries", "human_handoff")
    if value.get("decision") not in {"review_required", "planned"} or any(not str(scenario.get(key) or "").strip() for key in required_scenario):
        return {"status": "rejected", "reason_codes": ["dual_lane_plan_incomplete"]}
    refs = value.get("evidence_refs") if isinstance(value.get("evidence_refs"), dict) else {}
    return {
        "status": "available", "version": value["version"], "planning_mode": value.get("planning_mode"),
        "generation_only": True, "permissions": {"allow_viral_claims": False, "allow_automated_learning": False},
        "topic": value.get("topic"), "content_form": value.get("content_form"),
        "hook_hypothesis": value.get("hook_hypothesis"), "narrative_structure": list(value.get("narrative_structure") or []),
        "success_metric": value.get("success_metric"), "scenario_contract": scenario,
        "evidence_refs": {key: list(refs.get(key) or []) for key in ("public_web_observation", "authorized_owned_analytics")},
    }

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
    if not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("invalid_skill_name")
    repo_skills = ROOT / "skills"
    hermes_home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    roots = [hermes_home / "skills", repo_skills]
    candidates = []
    for root in roots:
        candidates.append(root / name / "SKILL.md")
        if name.startswith("content/"):
            candidates.append(root / name.split("/", 1)[1] / "SKILL.md")
    for candidate in candidates:
        # Materialized role homes may link the current shared skill catalogue.
        # Resolve to its stable source so later release checks see the same pin.
        if candidate.is_file():
            return candidate.resolve(strict=True)
    return candidates[0]


def _latest_distilled_strategy() -> Path | None:
    for cand in [ROOT / "config" / "growth_strategy_distilled_per_account.md", ROOT / "data" / "intel" / "distilled_per_account_20260822.md"]:
        if cand.is_file():
            return cand
    return None


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


def _validate_ai_rulebook_reference(platform: str, rule_entry: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve AI policy from its canonical file and reject stale rulebook refs."""
    policy = load_real_world_ai_positioning()
    policy_platform = "twitter" if platform == "x" else platform
    ai_platforms = set(policy.get("platforms") or [])
    rule_positioning = rule_entry.get("real_world_ai_positioning")
    if policy_platform not in ai_platforms:
        if rule_positioning is not None:
            raise ValueError(f"non-AI platform must not declare canonical AI positioning: {platform}")
        return None
    if not isinstance(rule_positioning, dict):
        raise ValueError(f"canonical AI rulebook reference missing: {platform}")
    expected_ref = {
        "source": "config/real_world_ai_implementation_v1.json",
        "policy_profile": policy.get("policy_profile"),
        "policy_revision": policy.get("policy_revision"),
    }
    if rule_positioning.get("canonical_contract") != expected_ref:
        raise ValueError(f"canonical AI rulebook reference mismatch: {platform}")
    expected_adaptation = (policy.get("platform_adaptation") or {}).get(policy_platform)
    if not expected_adaptation or rule_positioning.get("platform_adaptation") != expected_adaptation:
        raise ValueError(f"canonical AI platform adaptation mismatch: {platform}")
    if set(rule_positioning) != {"canonical_contract", "platform_adaptation"}:
        raise ValueError(f"AI rulebook entry duplicates canonical contract: {platform}")
    return policy


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
    canonical_ai_policy = _validate_ai_rulebook_reference(platform, rule_entry)
    rules_ok, rules_reason = _platform_rule_loaded(platform)
    if platform in {"kuaishou", "tiktok", "youtube", "bilibili", "shipinhao", "wechat", "xiaohongshu", "zhihu", "juejin", "douyin", "douyin_ai", "douyin_pet", "x", "twitter"} and not rules_ok:
        raise ValueError(f"2026 platform rules missing for {platform}: {rules_reason}")

    strategy = _latest_distilled_strategy() or _latest_strategy(platform)
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
        "rulebook": {"path": str(RULEBOOK), "entry_loaded": True, "entry": rule_entry},
        "positioning": canonical_ai_policy or {},
        "platform_adaptation": (
            (canonical_ai_policy.get("platform_adaptation") or {}).get("twitter" if platform == "x" else platform)
            if canonical_ai_policy else ""
        ),
        "platform_intelligence_constraints": load_platform_intelligence_runtime_constraints(platform),
        "external_discovery_candidates": _cross_platform_discovery_compact(platform),
        "dual_lane_work_plan": _compact_dual_lane_work_plan(plan.get("dual_lane_work_plan"), platform),
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
        "distilled_per_account": load_distilled_per_account_compact(platform) if load_distilled_per_account_compact else {"version": "distilled_per_account_compact_v1", "status": "missing", "note": "loader not deployed"},
        "hot_work_parameter_pack": load_hot_work_parameter_pack_compact(platform),
        "wechat_blowup_intelligence": load_wechat_blowup_compact(_wechat_blowup_latest_path()) if platform == "wechat" else {"version": "wechat_blowup_intelligence_v1", "status": "not_applicable", "samples": [], "failures": []},
        # Preserve the platform-scoped evidence report for the generate stage.
        # Readiness gates may inspect only its status, but generation needs the
        # bounded execution policy derived from its accepted samples.
        "viral_breakdown": plan.get("viral_breakdown") or plan.get("viral_breakdown_report") or {},
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
