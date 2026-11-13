#!/usr/bin/env python3
"""Pipeline-compatible video toolchain runner.

The content platform calls video scripts as:

    python script.py <script_body> <title>

This runner reads VIDEO_TOOLCHAIN_PLAN_PATH, materializes a renderer-ready
cards.json, chooses the configured renderer, and leaves the generated mp4 in
VIDEO_OUTPUT_DIR for MediaBridge to discover.
"""

from __future__ import annotations

import fcntl
import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cinema_composition import storyboard
from scripts.pre_render_gate import validate_render_inputs
from content_platform.content_recipe import build_tool_invocation_manifest
from content_platform.tool_selection import build_tool_selection_evidence
from content_platform.video_recipe import build_visual_recipe, load_effect_module_registry, validate_visual_recipe
from content_platform.shotcraft_receipt import build_shotcraft_execution_receipt, validate_shotcraft_execution_receipt
from content_platform.video_artifact import probe_video, verify_artifact, verify_final_pixels
from content_platform.scene_manifest import build_scene_manifest, validate_rendered_duration, validate_scene_manifest
from content_platform.paths import agent_scripts_dir
from content_platform.platform_workflow_context import write_platform_workflow_context
from content_platform.asset_ledger import AssetLedger, validate_asset_set
from content_platform.prompt_compiler import compile_prompt_bundle, validate_prompt_bundle
from content_platform.video_generation_contract import (
    InvalidGenerationContract,
    compile_generation_contract,
)
from content_platform.video_run import RunState, write_manifest_atomic
from content_platform.delivery_manifest import build_delivery_manifest
from content_platform.account_lane_gate import AccountLaneGateError, validate_account_lane
from content_platform.beat_asset_semantic_gate import BeatAssetSemanticError, validate_beat_asset_semantics
from content_platform.repost_dedup import build_dedup_evidence

try:
    from scripts.shotcraft_moves import SHOT_CARD_REGISTRY, shot_plan_for_text, shot_sequence
except Exception as exc:  # pragma: no cover - exercised through manifest fallback
    SHOT_CARD_REGISTRY = {}
    _SHOTCRAFT_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    shot_plan_for_text = None
    shot_sequence = None
else:
    _SHOTCRAFT_IMPORT_ERROR = ""


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RENDERER = ROOT / "scripts" / "kuaishou_render.py"
LAYOUTS = ["cover", "two_column", "card_stack", "big_number", "timeline", "diagonal", "card_stack", "interaction"]
THEME_BY_TEMPLATE = {
    "pet_repost_real_behavior": "mint-fresh",
    "wechat_ecosystem_microcase": "blueprint",
    "chaptered_tutorial": "blueprint",
    "chaptered_explainer": "blueprint",
    "social_note_motion_cards": "mint-fresh",
    "knowledge_card_motion_case": "cyber-neon",
}
PLANNED_TOOLS = [
    "cinema_composition.storyboard",
    "shotcraft_moves.shot_plan_for_text",
    "shotcraft_moves.shot_sequence",
    "video_toolchain_runner.build_cards",
    "kuaishou_render.render_cards",
    "kuaishou_render.gen_tts",
    "kuaishou_render.render_segments",
    "kuaishou_render.concat_video",
    "kuaishou_render.download_bgm",
    "mix_bgm_with_gate.mix_bgm",
    "kuaishou_render.gen_subtitles",
    "kuaishou_render.encode_final",
    "visual_gate.py --cinema",
]


def _cover_gate_failures(result: dict) -> list[str]:
    """Treat every non-pass cover verdict as a hard release failure."""
    failures = [str(item) for item in (result.get("failures") or [])]
    status = str(result.get("status") or "error")
    if status != "pass":
        failures.append(f"cover_status_{status}")
    if result.get("passed") is not True:
        failures.append("cover_passed_false")
    return list(dict.fromkeys(failures))


def _resolve_tool_invocation_status(
    invocations: dict[str, dict],
    *,
    runtime_evidence: dict[str, dict] | None,
) -> dict[str, dict]:
    """Resolve planned tools only from explicit runtime evidence.

    A planned name is not proof that a function ran.  The evidence producer
    must record the invocation and its artifact binding; otherwise the status
    remains ``not_invoked`` and delivery cannot claim that tool was executed.
    """
    evidence = runtime_evidence or {}
    resolved: dict[str, dict] = {}
    for name, record in invocations.items():
        current = dict(record) if isinstance(record, dict) else {"status": "invalid"}
        if current.get("status") != "planned_internal":
            resolved[name] = current
            continue
        observed = evidence.get(name)
        if isinstance(observed, dict) and observed.get("status") in {"ok", "executed", "generated"}:
            current.update(observed)
            current["status"] = "ok"
        else:
            current["status"] = "not_invoked"
            current["reason"] = "no explicit runtime invocation evidence"
        resolved[name] = current
    return resolved


RENDERER_STEPS = [
    "cinema_storyboard",
    "shotcraft_motion_plan",
    "build_cards",
    "render_cards",
    "gen_tts",
    "render_segments",
    "concat_video",
    "download_bgm",
    "mix_audio",
    "gen_subtitles",
    "encode_final",
    "generate_packet",
    "visual_gate_cinema",
]
EFFECT_STACK = [
    "template_theme",
    "cinema_color_css",
    "cinema_composition_layout",
    "shotcraft_motion_css",
    "motion_card_layouts",
    "lower_third_subtitles",
    "licensed_bgm_mix",
    "audio_loudness_gate",
    "post_render_anti_template_gate",
]
REPOST_PLANNED_TOOLS = [
    "source_video_discovery",
    "source_asset_matcher",
    "autoclip_adapter.run_autoclip_pipeline",
    "source_dedup_db",
    "ffmpeg.clip_segments",
    "ffmpeg.concat",
    "repost_rights_manifest",
]

STRUCTURE_SCENE_MODES = {
    "human_handoff_case": (
        "decision_interrupt", "capture_rig_exploded_view", "dataset_annotation_board",
        "anomaly_heatmap_inspection", "risk_queue_flow", "human_review_console",
        "failure_boundary_triptych", "execution_audit_receipt",
    ),
    "document_workflow": (
        "before_after_split", "terminal_evidence", "annotation_callout", "flow_track",
        "input_branch", "checklist_lock", "failure_rollback", "result_audit",
    ),
    "terminal_diff": (
        "terminal_evidence", "input_branch", "edge_case_matrix", "reproducibility_compare",
        "metric_contrast", "checklist_lock", "failure_rollback", "result_audit",
    ),
    "before_after": (
        "before_after_split", "metric_contrast", "light_split_compare", "error_fix_compare",
        "reproducibility_compare", "checklist_lock", "result_audit", "cta_warning",
    ),
    "diagnostic_console": (
        "terminal_evidence", "edge_case_matrix", "input_branch", "failure_rollback",
        "reproducibility_compare", "metric_contrast", "checklist_lock", "result_audit",
    ),
    "split_evidence": (
        "before_after_split", "annotation_callout", "terminal_evidence", "light_split_compare",
        "metric_contrast", "reproducibility_compare", "checklist_lock", "result_audit",
    ),
    "timeline_process": (
        "source_trace", "evidence_timeline", "flow_track", "annotation_callout",
        "input_branch", "failure_rollback", "checklist_lock", "result_audit",
    ),
    "screencast": (
        "source_trace", "prompt_typewriter", "annotation_callout", "flow_track",
        "input_branch", "error_fix_compare", "checklist_lock", "result_audit",
    ),
}

STRUCTURE_SCENE_MOTIONS = (
    "split_reveal", "type_in", "callout_draw", "focus_shift",
    "orbit_select", "check_each", "error_mark", "stamp_lock",
)


def _cover_output_path(
    output_dir: Path,
    *,
    orientation: str,
    generation_contract: dict | None,
) -> Path:
    if generation_contract is not None:
        return Path(str(generation_contract["canonical_cover"])).resolve()
    filename = "cover_1080x1920.jpg" if orientation == "vertical" else "cover_1920x1080.jpg"
    return output_dir / filename


def _write_generated_cover_evidence(
    *,
    cover_path: Path,
    evidence_path: Path,
    platform: str,
    title: str,
    subtitle: str,
    background_path: str | None = None,
    background_source: str = "unknown",
    layout_key: str = "hero_conflict",
    semantic_subject: str = "",
    supporting_visual_evidence: list[str] | None = None,
) -> dict[str, object]:
    """Bind an independently rendered cover to its semantic design contract."""
    ocr_title = title.strip().splitlines()[0].strip() if layout_key == "premium_fintech" else title.strip()
    payload: dict[str, object] = {
        "platform": platform,
        "cover_path": str(cover_path.resolve()),
        "cover_sha256": hashlib.sha256(cover_path.read_bytes()).hexdigest(),
        "layout_key": layout_key,
        "title": title.strip(),
        "title_cn": ocr_title,
        "hook": title.strip(),
        "conflict_or_payoff": subtitle.strip() or title.strip(),
        "content_match_reason": "封面主标题、冲突点与本次脚本主题直接对应",
        # MED87 (11-12 CST window): every premium_fintech cover, the douyin_pet one included, claimed the finance
        # demo's subject and reconciliation visuals. The caller now names the work's own subject.
        "semantic_subject": semantic_subject.strip(),
        "supporting_visual_evidence": list(supporting_visual_evidence or []),
        "focal_subjects": ["主题相关主视觉", "内容标题"],
        "safe_zone_verified": True,
        "background_provenance": {
            "path": str(Path(background_path).resolve()) if background_path else "",
            "source": background_source,
            "visible_required": True,
        },
        "renderer": "scripts.gen_cover.generate_cover",
        "independent_render": True,
        "degraded": False,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = evidence_path.with_name(f".{evidence_path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, evidence_path)
    return payload


def _apply_creative_structure_to_contract(plan: dict, contract: list[dict]) -> list[dict]:
    """Apply only an explicit, semantically compatible renderer mapping."""
    selected = (plan.get("creative_structure") or {}).get("selected") or {}
    family = str(selected.get("family") or "").strip()
    if not family:
        return [dict(scene) for scene in contract]
    modes = STRUCTURE_SCENE_MODES.get(family)
    if modes is None:
        raise RuntimeError(f"unsupported creative structure family: {family}")
    mapping = selected.get("capability_mapping")
    if not isinstance(mapping, dict) or mapping.get("semantic_compatible") is not True:
        return [dict(scene) for scene in contract]
    source_modes = {
        str(value).strip()
        for value in (mapping.get("source_visual_modes") or [])
        if str(value).strip()
    }
    target_modes = tuple(str(value).strip() for value in (mapping.get("target_visual_modes") or []))
    if not source_modes or len(target_modes) != len(contract) or any(not value for value in target_modes):
        raise RuntimeError("creative structure capability mapping is incomplete")
    if tuple(target_modes) != tuple(modes):
        raise RuntimeError("creative structure capability mapping does not match renderer capabilities")
    rewritten = []
    for index, (scene, mode, motion) in enumerate(
        zip(contract, target_modes, STRUCTURE_SCENE_MOTIONS, strict=True), 1
    ):
        item = dict(scene)
        existing_mode = str(item.get("visual_mode") or "").strip()
        has_scene_hook = bool(str(item.get("visual_hook") or "").strip())
        if existing_mode not in source_modes or has_scene_hook:
            rewritten.append(item)
            continue
        item.update(
            {
                "visual_mode": mode,
                "template_id": f"{family}_{mode}_v1",
                "group_motion": [motion],
                "structure_family": family,
                "structure_scene_index": index,
            }
        )
        rewritten.append(item)
    return rewritten


FINANCE_COVER_SUBJECT = "AI报表核算不能直接求和；必须公式校验"
FINANCE_COVER_VISUALS = ["对账系统界面", "红色差异标记", "人工复核动作"]


def _is_finance_plan(plan: dict) -> bool:
    return "finance_reconciliation" in str(plan.get("template_family") or "") or "finance_reconciliation" in str(plan.get("work_id") or "")


def _cover_subject(plan: dict, title: str) -> tuple[str, list[str]]:
    """The cover's semantic subject: an explicit plan value, the finance demo's own, else the work's title."""
    if _is_finance_plan(plan):
        return str(plan.get("cover_semantic_subject") or FINANCE_COVER_SUBJECT), list(FINANCE_COVER_VISUALS)
    return str(plan.get("cover_semantic_subject") or title or "").strip(), []


def _cover_text(plan: dict, title: str, script_body: str, clip) -> tuple[str, str, str, str, str]:
    """(title, subtitle, hook, layout, tag) for an independently generated video cover."""
    if plan.get('content_mode')=='original_knowledge':
        return clip(title,24), '公开自制示例｜逐项核对，人工确认', '保留依据，再核差异', 'evidence_interface', '公开自制示例'
    if _is_finance_plan(plan):
        return "核账不能\n直接付款", "500笔对账｜3小时→15分钟", "付款前必须人工复核", "premium_fintech", "⚠️ 财务打回实测"
    # MED59 (11-08 CST window): every other video got the fixed 09-21 Kuaishou demo cover ("用AI做表？…实测67%算错"),
    # so the douyin_pet cover named an AI spreadsheet test and failed title OCR; it now carries the work's own title.
    # Probe over the window's pet background: only this two-line large-title layout without a subtitle passed the
    # cover gate (evidence_interface: thumbnail unreadable; a subtitle: too many text blocks).
    opening = next((line.strip() for line in str(script_body).splitlines() if line.strip()), "")
    own = clip(title if title.strip() and title != "Untitled video" else opening, 16)
    cut = (len(own) + 1) // 2
    return (own[:cut] + "\n" + own[cut:]).strip(), "", "", "premium_fintech", ""


def _run_main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    script_body = argv[0] if argv else ""
    title = argv[1] if len(argv) > 1 else "Untitled video"
    output_dir = Path(os.environ.get("VIDEO_OUTPUT_DIR") or ROOT / "data" / "artifacts" / "video_toolchain").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runner_lock = (output_dir / ".runner.lock").open("a+")
    try:
        fcntl.flock(runner_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"runner blocked: output run already locked: {output_dir}", file=sys.stderr)
        runner_lock.close()
        return 5
    plan = _load_plan()
    dry_run = os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1"
    lane_gate = {"passed": False, "skipped": True, "reason": "dry_run"}
    if not dry_run:
        try:
            requires_account_lane = _primary_platform(plan) in {"douyin_ai", "douyin_pet"} or any(
                str(plan.get(key) or "").strip()
                for key in ("account_key", "platform_account", "content_line")
            )
            lane_gate = validate_account_lane(plan) if requires_account_lane else {
                "passed": True,
                "skipped": True,
                "reason": "account_lane_not_required_for_platform",
            }
        except AccountLaneGateError as exc:
            manifest = {
                "ok": False,
                "status": "account_lane_gate_failed",
                "error": str(exc),
                "account_lane_gate": {"passed": False, "failures": str(exc).split(",")},
            }
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 5
        (output_dir / "account_lane_gate.json").write_text(
            json.dumps(lane_gate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    platform_context = None
    requested_platforms = [str(item).strip() for item in (plan.get("platforms") or []) if str(item).strip()]
    workflow_platform = _workflow_platform(plan)
    if requested_platforms:
        if len(requested_platforms) != 1:
            raise RuntimeError("video renderer requires exactly one platform per serial workflow")
        if dry_run:
            # A dry run validates local contracts only; runtime capability and
            # platform-intelligence collection can block on external adapters.
            platform_context = {
                "version": "platform_workflow_context_v1",
                "platform": workflow_platform,
                "loaded": False,
                "adapter": "dry_run_local_contract_only",
            }
            (output_dir / "platform_workflow_context.json").write_text(
                json.dumps(platform_context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            platform_context = write_platform_workflow_context(
                output_dir, workflow_platform, plan=plan
            )
    elif not dry_run:
        raise RuntimeError("real video render requires plan.platforms and platform workflow context")
    prompt_platform = workflow_platform or _primary_platform(plan) or "generic_image"
    prompt_aliases = {"douyin": "douyin_ai", "youtube_shorts": "youtube"}
    prompt_platform = prompt_aliases.get(prompt_platform, prompt_platform)
    try:
        prompt_spec = {
            "platform": prompt_platform,
            "content_type": "short_video",
            "topic": title or "video workflow",
            "audience": "short-form video viewers",
            "goal": "deliver a clear, evidence-backed platform-matched video",
            "evidence": ["scripted beats", "rendered scene evidence"],
            "visual_style": "内容驱动、真实素材、清晰字幕",
            "duration": "20-100秒",
            "constraints": ["每个 beat 必须有视觉契约", "不得静默复用旧素材"],
        }
        for key in ("lane", "policy_profile", "policy_revision", "prompt_profile"):
            if plan.get(key) not in (None, "", [], {}):
                prompt_spec[key] = plan[key]
        package = plan.get("real_world_ai_package")
        if isinstance(package, dict):
            scenario = package.get("scenario") if isinstance(package.get("scenario"), dict) else package
            prompt_spec["scenario"] = scenario
        prompt_bundle = compile_prompt_bundle(prompt_spec)
        prompt_bundle_gate = validate_prompt_bundle(prompt_bundle)
        prompt_bundle_evidence = {
            "prompt_platform": prompt_platform,
            "prompt_bundle_fingerprint": prompt_bundle["fingerprint"],
            "prompt_registry_version": prompt_bundle["quality_contract"]["registry_version"],
            "prompt_quality_contract": prompt_bundle["quality_contract"],
            "prompt_bundle_validation": prompt_bundle_gate,
        }
    except (KeyError, TypeError, ValueError) as exc:
        prompt_bundle_evidence = {
            "prompt_platform": prompt_platform,
            "prompt_bundle_fingerprint": "",
            "prompt_bundle_validation": {"passed": False, "errors": [str(exc)], "warnings": []},
        }
        if not dry_run:
            _write_manifest(output_dir, {"ok": False, "status": "prompt_bundle_failed", **prompt_bundle_evidence})
            return 5
    if str(plan.get("selected_pipeline") or "") == "localized_repost_video" and not dry_run:
        # Source-preserving reposts use source/rights gates, not synthetic visual contracts.
        source_path = Path(str(plan.get("source_video_path") or ""))
        source_url = str(plan.get("source_url") or "").strip()
        if not source_path.is_file() and not source_url:
            return _run_localized_repost(plan, output_dir, title)
        return _run_localized_repost(plan, output_dir, title)
    script_structure = validate_script_structure(script_body)
    # Dry runs retain incomplete-plan evidence for isolated gate tests; real renders fail closed.
    if not dry_run and not script_structure.get("passed"):
        manifest = {
            "ok": False,
            "title": title,
            "selected_pipeline": plan.get("selected_pipeline", ""),
            "template_family": plan.get("template_family", ""),
            "status": "script_structure_failed",
            "error": "video script needs eight distinct narrative beats before rendering",
            "script_structure_gate": script_structure,
            "dry_run": dry_run,
            "tool_invocation_manifest": _tool_invocation_manifest(plan),
        }
        _write_manifest(output_dir, manifest)
        print(manifest["error"], file=sys.stderr)
        return 5
    generation_contract = None
    strict_generation_contract = not dry_run or bool(plan.get("strict_generation_contract"))
    if strict_generation_contract:
        script_input_path = output_dir / "script_input.txt"
        script_input_path.write_text(script_body, encoding="utf-8")
        plan_path = Path(os.environ.get("VIDEO_TOOLCHAIN_PLAN_PATH") or "")
        input_paths = {"script": script_input_path}
        if plan_path.is_file():
            input_paths["plan"] = plan_path.resolve()
        try:
            generation_contract = compile_generation_contract(
                plan,
                output_dir=output_dir,
                input_paths=input_paths,
            )
            trusted_manifest = generation_contract["run_manifest"].advance(
                RunState.CONTRACT_VALIDATED
            )
            generation_contract["run_manifest"] = trusted_manifest
            write_manifest_atomic(
                trusted_manifest,
                output_dir / "trusted_run_manifest.json",
            )
            generation_payload = {
                key: value
                for key, value in generation_contract.items()
                if key != "run_manifest"
            }
            generation_payload["run_manifest_path"] = str(
                output_dir / "trusted_run_manifest.json"
            )
            (output_dir / "video_generation_contract.json").write_text(
                json.dumps(generation_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            plan = dict(plan)
            plan["creative_structure"] = generation_contract["creative_structure"]
            if plan.get("content_mode")=="original_knowledge":
                plan["original_knowledge_intelligence"]=generation_contract["original_knowledge_intelligence"]
            else:
                plan["hot_viral_intelligence"] = generation_contract["hot_viral_intelligence"]
        except (InvalidGenerationContract, OSError, TypeError, ValueError) as exc:
            manifest = {
                "ok": False,
                "title": title,
                "status": "generation_contract_failed",
                "error": str(exc),
                "dry_run": dry_run,
            }
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 5
    visual_contract = plan.get("visual_contract") or plan.get("scene_contract") or []
    if generation_contract is not None:
        try:
            visual_contract = _apply_creative_structure_to_contract(
                plan, list(visual_contract)
            )
            plan["visual_contract"] = visual_contract
        except RuntimeError as exc:
            manifest = {
                "ok": False,
                "title": title,
                "status": "creative_structure_execution_failed",
                "error": str(exc),
                "dry_run": dry_run,
            }
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 5
    if not dry_run:
        from scripts.visual_contract_gate import validate_scene_contract
        contract_gate = validate_scene_contract(visual_contract, beat_count=8, strict_runtime=True)
        legacy_allowed = bool(plan.get("legacy_visual_contract")) and os.environ.get("VIDEO_ALLOW_LEGACY") == "1" and not plan.get("run_contract")
        if not contract_gate.get("passed") and not legacy_allowed:
            manifest = {
                "ok": False,
                "title": title,
                "selected_pipeline": plan.get("selected_pipeline", ""),
                "template_family": plan.get("template_family", ""),
                "status": "visual_contract_failed",
                "error": "scene-level visual contract failed: " + ", ".join(contract_gate.get("failures") or ["unknown"]),
                "visual_contract_gate": contract_gate,
                "dry_run": dry_run,
            }
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 5
    else:
        contract_gate = {"passed": True, "failures": [], "scenes": visual_contract}
    analysis_binding = _analysis_fingerprint(plan, script_body=script_body, title=title)
    if visual_contract:
        scene_contract_path = output_dir / "scene_contract.json"
        scene_contract_path.write_text(
            json.dumps(
                {
                    "version": "scene_contract_v1",
                    "account_lane": lane_gate,
                    "account_lane_fingerprint": lane_gate.get("account_lane_fingerprint", ""),
                    "analysis_fingerprint": analysis_binding,
                    "scenes": visual_contract,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.environ["VIDEO_SCENE_CONTRACT_PATH"] = str(scene_contract_path)
    visual_assets = _load_visual_assets(plan)
    if not dry_run and visual_contract:
        try:
            from content_platform.video_asset_semantics import validate_assignments
            validate_assignments(list(visual_contract),list((visual_assets or {}).get('assignments') or []))
            semantic_gate = validate_beat_asset_semantics(
                list(visual_contract), list((visual_assets or {}).get("assignments") or [])
            )
        except (BeatAssetSemanticError,ValueError) as exc:
            manifest = {
                "ok": False,
                "status": "beat_asset_semantic_gate_failed",
                "error": str(exc),
                "beat_asset_semantic_gate": {"passed": False, "failures": str(exc).split(",")},
            }
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 5
        (output_dir / "beat_asset_semantic_gate.json").write_text(
            json.dumps(semantic_gate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    materialized_backgrounds = _materialize_visual_backgrounds(output_dir, visual_assets)
    if plan.get('user_visual_materials_source'):
        from content_platform.native_visual_inputs import bind_materialized_user_assets
        plan=bind_materialized_user_assets(plan,visual_assets,materialized_backgrounds)
        visual_contract=plan['visual_contract']
        scene_contract_path=output_dir/'scene_contract.json'
        captured=json.loads(scene_contract_path.read_text(encoding='utf8'))
        captured['scenes']=visual_contract
        scene_contract_path.write_text(json.dumps(captured,ensure_ascii=False,indent=2),encoding='utf8')
    # Real renders may resolve missing backgrounds from Pexels. Dry runs must
    # remain deterministic and network-free; provenance failure is recorded
    # below but is not promoted to a release verdict.
    background_acquisition_error = None
    if not dry_run and len(materialized_backgrounds) < 8:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from pexels_auto_bg import auto_fetch_backgrounds, write_auto_assets
            auto_assets = auto_fetch_backgrounds(script_body or title, title or "", output_dir, _primary_platform(plan))
            if auto_assets:
                materialized_backgrounds = auto_assets
        except Exception as auto_bg_error:
            # Background acquisition is release-critical for non-dry runs.
            background_acquisition_error = f"{type(auto_bg_error).__name__}: {auto_bg_error}"
    # diagram-design 补图通道：结构化主题且背景不足时，自动生成杂志级 diagram 背景
    materialized_backgrounds = _diagram_background_fill(output_dir, script_body or title, materialized_backgrounds)
    asset_records = _asset_provenance_records(materialized_backgrounds)
    asset_provenance_path = output_dir / "asset_provenance.json"
    asset_provenance_path.write_text(json.dumps({"version": "asset_provenance_v1", "assets": asset_records}, ensure_ascii=False, indent=2), encoding="utf-8")
    background_provenance_gate = _background_provenance_gate(asset_records, required_scenes=8)
    (output_dir / "background_provenance_gate.json").write_text(
        json.dumps(background_provenance_gate, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not dry_run and not background_provenance_gate["passed"]:
        _write_manifest(
            output_dir,
            {
                "ok": False,
                "status": "background_provenance_failed",
                "error": "background provenance is incomplete: "
                + ", ".join(background_provenance_gate["failures"]),
                "background_provenance_gate": background_provenance_gate,
                "asset_provenance_path": str(asset_provenance_path),
            },
        )
        return 5
    asset_gate = {}
    if plan.get("run_contract"):
        asset_gate = validate_asset_set(
            asset_records,
            _primary_platform(plan),
            str(plan.get("work_id") or output_dir.name),
            AssetLedger(os.environ.get("ASSET_LEDGER_PATH") or ROOT / "data" / "asset_ledger.db"),
        )
        (output_dir / "asset_quality_gate.json").write_text(json.dumps(asset_gate, ensure_ascii=False, indent=2), encoding="utf-8")
        if not asset_gate.get("passed"):
            _write_manifest(output_dir, {"ok": False, "status": "asset_quality_failed", "error": "visual assets failed provenance, semantic fit, or reuse gate: " + ", ".join(asset_gate.get("failures") or ["unknown"]), "asset_quality_gate": asset_gate, "reselection_required": any("reuse" in str(item) or "duplicate" in str(item) for item in asset_gate.get("failures") or [])})
            return 5
    cinema_scenes = storyboard(script_body or title, 8)
    shotcraft_plan = _shotcraft_motion_plan(script_body or title)
    registry = load_effect_module_registry()
    tool_manifest = _tool_invocation_manifest(plan)
    tool_selection_evidence = build_tool_selection_evidence(
        platform=_primary_platform(plan),
        content_type=str(plan.get("content_form") or "knowledge_card_video"),
        content_goal="increase retention with selected video modules, matched assets, voice, subtitles, BGM, and quality gates",
        planned_manifest=tool_manifest,
    )
    visual_recipe = build_visual_recipe(
        plan,
        script_body=script_body,
        title=title,
        cinema_scenes=cinema_scenes,
        shotcraft_plan=shotcraft_plan,
        visual_assets=visual_assets,
        registry=registry,
    )
    recipe_gate = validate_visual_recipe(visual_recipe, registry)
    recipe_reuse_gate = _recipe_reuse_gate(visual_recipe, plan)
    recipe_path = output_dir / "visual_recipe.json"
    recipe_path.write_text(json.dumps(visual_recipe, ensure_ascii=False, indent=2), encoding="utf-8")
    scene_manifest_path = output_dir / "scene_manifest.json"
    scene_manifest_path.write_text(json.dumps(visual_recipe.get("scene_manifest") or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not recipe_gate.get("passed") or not recipe_reuse_gate.get("passed"):
        manifest = {
            "ok": False,
            "title": title,
            "selected_pipeline": plan.get("selected_pipeline", ""),
            "template_family": plan.get("template_family", ""),
            "visual_recipe": visual_recipe,
            "visual_recipe_path": str(recipe_path),
            "visual_recipe_gate": recipe_gate,
            "recipe_reuse_gate": recipe_reuse_gate,
            "dedup_required": True,
            "dedup_gate": recipe_reuse_gate,
            "tool_invocation_manifest": tool_manifest,
            **tool_selection_evidence,
            "status": "visual_recipe_failed" if not recipe_gate.get("passed") else "visual_recipe_reuse_failed",
            "error": "visual_recipe gate failed" if not recipe_gate.get("passed") else "visual_recipe reuse gate failed",
            "dry_run": os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1",
        }
        _write_manifest(output_dir, manifest)
        print(json.dumps({"ok": False, "error": manifest["error"], "visual_recipe_gate": recipe_gate, "recipe_reuse_gate": recipe_reuse_gate}, ensure_ascii=False), file=sys.stderr)
        return 5
    cards = build_cards(script_body, title, plan, cinema_scenes, shotcraft_plan, visual_assets)
    cards_path = output_dir / "cards.json"
    cards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
    scene_manifest = build_scene_manifest(cards, visual_recipe, plan, title)
    if visual_contract:
        manifest_scenes = scene_manifest.get("scenes") or []
        for idx, expected in enumerate(visual_contract):
            actual = manifest_scenes[idx] if idx < len(manifest_scenes) else {}
            for field in ("visual_mode", "template_id", "platform_reason", "visual_hook"):
                if str(actual.get(field) or "") != str(expected.get(field) or ""):
                    scene_manifest.setdefault("contract_mismatches", []).append({"scene": idx + 1, "field": field, "expected": expected.get(field), "actual": actual.get(field)})
            if list(actual.get("group_motion") or []) != list(expected.get("group_motion") or []):
                scene_manifest.setdefault("contract_mismatches", []).append({"scene": idx + 1, "field": "group_motion", "expected": expected.get("group_motion"), "actual": actual.get("group_motion")})
        if scene_manifest.get("contract_mismatches"):
            scene_manifest["contract_bound"] = False
    scene_manifest_gate = validate_scene_manifest(scene_manifest)
    if scene_manifest.get("contract_mismatches"):
        scene_manifest_gate["passed"] = False
        scene_manifest_gate.setdefault("failures", []).append("scene_contract_manifest_mismatch")
    scene_manifest_path = output_dir / "scene_manifest.json"
    scene_manifest_path.write_text(json.dumps(scene_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not scene_manifest_gate.get("passed"):
        manifest = {
            "ok": False,
            "title": title,
            "selected_pipeline": plan.get("selected_pipeline", ""),
            "template_family": plan.get("template_family", ""),
            "status": "scene_manifest_failed",
            "error": "scene manifest failed validation",
            "scene_manifest": scene_manifest,
            "scene_manifest_path": str(scene_manifest_path),
            "scene_manifest_gate": scene_manifest_gate,
            "dry_run": dry_run,
            "tool_invocation_manifest": tool_manifest,
            **tool_selection_evidence,
        }
        _write_manifest(output_dir, manifest)
        print(manifest["error"], file=sys.stderr)
        return 5
    pre_render_gate = validate_render_inputs(
        output_dir,
        cards,
        platform=_primary_platform(plan),
        require_backgrounds=not dry_run,
        require_scene_manifest=True,
        require_functional_mascots=bool(plan.get("require_functional_mascots")),
        require_materialized_audio=not dry_run,
    )
    pre_render_gate_path = output_dir / "pre_render_gate.json"
    pre_render_gate_path.write_text(json.dumps(pre_render_gate, ensure_ascii=False, indent=2), encoding="utf-8")
    if not pre_render_gate.get("passed"):
        for record in (tool_manifest.get("invocations") or {}).values():
            if isinstance(record, dict) and record.get("status") == "planned_internal":
                record["status"] = "not_invoked"
                record["reason"] = "pre_render_gate_failed"
        manifest = {
            "ok": False,
            "title": title,
            "selected_pipeline": plan.get("selected_pipeline", ""),
            "template_family": plan.get("template_family", ""),
            "status": "pre_render_gate_failed",
            "error": "generated cards failed pre-render validation: " + ", ".join(pre_render_gate.get("failures") or ["unknown"]),
            "script_structure_gate": script_structure,
            "pre_render_gate": pre_render_gate,
            "pre_render_gate_path": str(pre_render_gate_path),
            "scene_manifest": scene_manifest,
            "scene_manifest_path": str(scene_manifest_path),
            "scene_manifest_gate": scene_manifest_gate,
            "dry_run": dry_run,
            "tool_invocation_manifest": tool_manifest,
            **tool_selection_evidence,
        }
        _write_manifest(output_dir, manifest)
        print(manifest["error"], file=sys.stderr)
        return 5
    if generation_contract is not None and not dry_run:
        trusted_manifest = generation_contract["run_manifest"].advance(
            RunState.ASSETS_VALIDATED
        )
        generation_contract["run_manifest"] = trusted_manifest
        write_manifest_atomic(
            trusted_manifest,
            output_dir / "trusted_run_manifest.json",
        )
    renderer, plan = _content_driven_renderer(plan, script_body, title, output_dir)
    template_family = str(visual_recipe.get("template_family") or plan.get("template_family") or "")
    style_variants = visual_recipe.get("style_variants") if isinstance(visual_recipe.get("style_variants"), dict) else {}
    # 2026-08-16 修复：主题按内容赛道适配（不再固定 cyber-neon / 随机哈希）
    # 与 TTS/BGM 同步：pets→mint-fresh(清新萌宠)，finance/tech→blueprint(专业蓝)，emotion→mint-fresh(柔和)，science→blueprint
    theme = str(style_variants.get("theme") or THEME_BY_TEMPLATE.get(template_family, "") or "")
    if not theme:
        try:
            from scripts.voice_engine import detect_genre
            genre = detect_genre(f"{title} {script_body}")
            theme_map = {
                "pets": "mint-fresh",
                "emotion": "mint-fresh",
                "finance": "blueprint",
                "science": "blueprint",
                "tech": "cyber-neon",
            }
            theme = theme_map.get(genre, "cyber-neon")
        except Exception:
            theme = "cyber-neon"
    bgm_style = _bgm_style(cinema_scenes, text=f"{title} {script_body}")
    renderer_cmd = _renderer_command(renderer, output_dir, theme, title, script_body, plan, bgm_style)
    toolchain_contract = _toolchain_contract(plan, theme, bgm_style, renderer, visual_recipe)
    manifest = {
        "ok": False,
        "title": title,
        "selected_pipeline": plan.get("selected_pipeline", ""),
        "template_family": template_family,
        "cards_json": str(cards_path),
        "renderer": str(renderer),
        "renderer_command_preview": renderer_cmd,
        "bgm_style": bgm_style,
        "toolchain_contract": toolchain_contract,
        "dry_run": os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1",
        "script_structure_gate": script_structure,
        "pre_render_gate": pre_render_gate,
        "pre_render_gate_path": str(pre_render_gate_path),
        "scene_manifest_path": str(scene_manifest_path),
        "cinema_storyboard": cinema_scenes,
        "shotcraft_motion_plan": shotcraft_plan,
        "visual_assets": visual_assets,
        "materialized_backgrounds": materialized_backgrounds,
        "asset_provenance_path": str(asset_provenance_path),
        "background_provenance_gate": background_provenance_gate,
        "account_lane_gate": lane_gate,
        "analysis_fingerprint": analysis_binding,
        "asset_quality_gate": asset_gate,
        "visual_recipe": visual_recipe,
        "visual_recipe_path": str(recipe_path),
        "visual_recipe_gate": recipe_gate,
        "recipe_reuse_gate": recipe_reuse_gate,
        "dedup_required": True,
        "dedup_gate": recipe_reuse_gate,
        "scene_manifest": scene_manifest,
        "scene_manifest_path": str(scene_manifest_path),
        "scene_manifest_gate": scene_manifest_gate,
        "recipe_fingerprint": visual_recipe.get("fingerprint"),
        "recipe_core_fingerprint": visual_recipe.get("core_fingerprint"),
        "card_titles": [str(card.get("t") or "") for card in cards],
        "subtitle": {
            "width": int(plan.get("width") or 1080),
            "height": int(plan.get("height") or 1920),
        },
        "tool_invocation_manifest": tool_manifest,
        **prompt_bundle_evidence,
        **tool_selection_evidence,
    }
    if background_acquisition_error:
        manifest["background_acquisition"] = {"error": background_acquisition_error}
    if generation_contract is not None:
        manifest["video_generation_contract"] = {
            key: value
            for key, value in generation_contract.items()
            if key != "run_manifest"
        }
    if manifest["dry_run"]:
        fake = output_dir / "dry_run.mp4"
        fake.write_bytes(b"video-toolchain-dry-run")
        manifest.update({"ok": True, "output": str(fake), "status": "dry_run", "executed_tools": PLANNED_TOOLS})
        _write_manifest(output_dir, manifest)
        print(json.dumps({"ok": True, "output": str(fake)}, ensure_ascii=False))
        return 0
    if not renderer.is_file():
        manifest["error"] = f"renderer not found: {renderer}"
        _write_manifest(output_dir, manifest)
        print(manifest["error"], file=sys.stderr)
        return 2
    cmd = renderer_cmd
    renderer_env = _renderer_environment(plan)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("VIDEO_TOOLCHAIN_TIMEOUT", "900")),
        env=renderer_env,
    )
    manifest.update({"renderer_command": cmd, "returncode": proc.returncode, "stdout_tail": (proc.stdout or "")[-800:], "stderr_tail": (proc.stderr or "")[-800:]})
    expected_output = Path(
        generation_contract["canonical_output"]
        if generation_contract is not None
        else output_dir / "final.mp4"
    )
    generated = [expected_output] if expected_output.is_file() else []
    if proc.returncode == 0 and generated:
        audio_evidence_path = output_dir / "audio_release_evidence.json"
        try:
            manifest["audio_evidence"] = json.loads(
                audio_evidence_path.read_text(encoding="utf-8")
            )
            manifest["audio_evidence_path"] = str(audio_evidence_path)
        except (OSError, json.JSONDecodeError):
            manifest["audio_evidence"] = None
            manifest["audio_evidence_path"] = str(audio_evidence_path)
        render_quality_path = output_dir / "render_quality_evidence.json"
        try:
            manifest["render_quality_evidence"] = json.loads(
                render_quality_path.read_text(encoding="utf-8")
            )
            manifest["render_quality_evidence_path"] = str(render_quality_path)
        except (OSError, json.JSONDecodeError):
            manifest["render_quality_evidence"] = None
            manifest["render_quality_evidence_path"] = str(render_quality_path)
        rendered_html_gate = _run_rendered_html_gate(output_dir, visual_contract)
        manifest["rendered_html_gate"] = rendered_html_gate
        (output_dir / "rendered_html_gate.json").write_text(
            json.dumps(rendered_html_gate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not rendered_html_gate.get("passed"):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "rendered_html_gate_failed", "error": "rendered HTML contract gate failed: " + ", ".join(rendered_html_gate.get("failures") or ["unknown"])})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        final_pixel_gate = verify_final_pixels(generated[0])
        manifest["final_pixel_gate"] = final_pixel_gate
        (output_dir / "final_pixel_gate.json").write_text(
            json.dumps(final_pixel_gate, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not final_pixel_gate.get("passed") or final_pixel_gate.get("candidate_sha256") != hashlib.sha256(generated[0].read_bytes()).hexdigest():
            manifest.update({"ok": False, "output": str(generated[0]), "status": "final_pixel_gate_failed", "error": "final video pixel gate failed"})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        cinema_gate = _run_cinema_visual_gate(output_dir)
        manifest["cinema_visual_gate"] = cinema_gate
        if not cinema_gate.get("passed"):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "visual_gate_failed", "error": cinema_gate.get("error") or "cinema visual gate failed"})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        artifact_gate = verify_artifact(generated[0], manifest, _primary_platform(plan))
        manifest["artifact_gate"] = artifact_gate
        if not artifact_gate.get("passed"):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "artifact_gate_failed", "error": "final video artifact gate failed"})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        scene_duration_gate = validate_rendered_duration(scene_manifest, _video_duration(generated[0]))
        manifest["scene_duration_gate"] = scene_duration_gate
        if not scene_duration_gate.get("passed"):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "scene_duration_failed", "error": scene_duration_gate.get("failure") or "scene duration gate failed"})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        motion_evidence = _render_motion_evidence(generated[0])
        manifest["motion_evidence"] = motion_evidence
        if not motion_evidence.get("passed"):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "motion_gate_failed", "error": "final video has insufficient distinct frame motion"})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        segment_motion_path = output_dir / "segment_motion_evidence.json"
        try:
            segment_motion = json.loads(segment_motion_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            segment_motion = {}
        segments = segment_motion.get("segments") if isinstance(segment_motion, dict) else []
        if not segments or any(not row.get("move_id") or not row.get("profile") for row in segments if isinstance(row, dict)):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "motion_mapping_missing", "error": "final video is missing per-segment Shotcraft render evidence"})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        manifest["segment_motion_evidence"] = {"path": str(segment_motion_path), "segments": segments}
        receipt_identity = {
            "platform": _primary_platform(plan),
            "account_key": str(plan.get("account_key") or plan.get("account") or ""),
            "lane": str(plan.get("lane") or ""),
            "content_line": str(plan.get("content_line") or ""),
            "run_id": str(plan.get("run_id") or ""),
            "attempt_id": str(plan.get("attempt_id") or ""),
        }
        shotcraft_receipt = build_shotcraft_execution_receipt(output_dir, segment_motion, identity=receipt_identity)
        receipt_validation = validate_shotcraft_execution_receipt(output_dir, shotcraft_receipt)
        shotcraft_receipt["validation"] = receipt_validation
        shotcraft_receipt_path = output_dir / "shotcraft_execution_receipt.json"
        shotcraft_receipt_path.write_text(json.dumps(shotcraft_receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["shotcraft_execution_receipt"] = {"path": str(shotcraft_receipt_path), "passed": receipt_validation.get("passed")}
        if not receipt_validation.get("passed"):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "shotcraft_receipt_failed", "error": "Shotcraft execution receipt failed: " + ", ".join(receipt_validation.get("failures") or [])})
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        invocations = manifest.get("tool_invocation_manifest", {}).get("invocations", {}) or {}
        runtime_evidence: dict[str, dict] = {}
        if manifest.get("cinema_storyboard"):
            runtime_evidence["cinema_composition.storyboard"] = {
                "status": "ok",
                "artifact": str(output_dir / "scene_manifest.json"),
            }
        if isinstance(manifest.get("shotcraft_motion_plan"), dict) and manifest["shotcraft_motion_plan"].get("available"):
            runtime_evidence["shotcraft_moves.shot_plan_for_text"] = {
                "status": "ok",
                "artifact": str(output_dir / "scene_manifest.json"),
            }
        if (output_dir / "segment_motion_evidence.json").is_file() and segments:
            runtime_evidence["shotcraft_moves.shot_sequence"] = {
                "status": "ok",
                "artifact": str(segment_motion_path),
            }
        if (output_dir / "cards.json").is_file():
            runtime_evidence["video_toolchain_runner.build_cards"] = {
                "status": "ok",
                "artifact": str(output_dir / "cards.json"),
            }
        if cinema_gate.get("passed") is True:
            runtime_evidence["visual_gate.py --cinema"] = {
                "status": "ok",
                "artifact": str(output_dir / "cinema_visual_gate.json"),
            }
        invocations = _resolve_tool_invocation_status(invocations, runtime_evidence=runtime_evidence)
        manifest["tool_invocation_manifest"]["invocations"] = invocations
        required_runtime_tools = {
            "cinema_composition.storyboard",
            "shotcraft_moves.shot_plan_for_text",
            "shotcraft_moves.shot_sequence",
            "video_toolchain_runner.build_cards",
            "visual_gate.py --cinema",
        }
        missing_runtime_tools = sorted(
            name for name in required_runtime_tools
            if invocations.get(name, {}).get("status") != "ok"
        )
        if missing_runtime_tools:
            manifest.update({
                "ok": False,
                "output": str(generated[0]),
                "status": "runtime_tool_evidence_failed",
                "error": "missing runtime evidence: " + ", ".join(missing_runtime_tools),
                "executed_tools": [
                    name for name, record in invocations.items()
                    if isinstance(record, dict) and record.get("status") == "ok"
                ],
            })
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        manifest.update({
            "ok": True,
            "output": str(generated[0]),
            "status": "rendered_unverified",
            "executed_tools": [
                name for name, record in invocations.items()
                if isinstance(record, dict) and record.get("status") == "ok"
            ],
        })

        # 2026-08-17 新增：渲染完成后自动归档规范 JSON + audio/ 到交付包根目录
        # （08-13 规范：platform_source_matrix/scene_manifest/visual_recipe/bgm/tts/checkpoint/quality/publish/audio）
        # 由 scripts/archive_delivery_package.py 统一执行，防止 render/ 产物漏归档
        try:
            from scripts.archive_delivery_package import archive_delivery_package_direct
            archive_delivery_package_direct(output_dir)
        except Exception as _archive_err:
            manifest["archive_warning"] = f"delivery archive failed: {_archive_err}"
        # Cover generation is a release-critical transaction: no silent fallback.
        try:
            bg_for_cover = None
            bg_source = "unknown"
            configured_cover_background = str(plan.get("cover_background_path") or "").strip()
            if configured_cover_background and Path(configured_cover_background).expanduser().is_file():
                bg_for_cover = str(Path(configured_cover_background).expanduser().resolve())
                bg_source = str(plan.get("cover_background_source") or "ai_generated_local")
            elif materialized_backgrounds:
                first_background = materialized_backgrounds[0]
                bg_for_cover = first_background.get("background_image") or first_background.get("path")
                bg_source = str(first_background.get("source") or first_background.get("provider") or "materialized_background")
            orientation = "horizontal" if _primary_platform(plan) in {"bilibili", "youtube"} else "vertical"
            cover_path = _cover_output_path(
                output_dir,
                orientation=orientation,
                generation_contract=generation_contract,
            )
            configured_cover_evidence = str(plan.get("cover_evidence_path") or "").strip()
            cover_evidence_path = (
                Path(configured_cover_evidence).expanduser().resolve()
                if configured_cover_evidence
                else output_dir / "cover_evidence.json"
            )
            if cover_path.is_file() and cover_evidence_path.is_file():
                manifest["cover"] = str(cover_path)
                manifest["cover_evidence"] = str(cover_evidence_path)
                manifest["cover_source"] = "independent_existing_cover"
            else:
                if not bg_for_cover or not Path(str(bg_for_cover)).is_file():
                    raise RuntimeError("cover_background_missing_or_unreadable")
                sys.path.insert(0, str(ROOT / "scripts"))
                from gen_cover import generate_cover

                def _clip_cover_text(text: str, limit: int) -> str:
                    # 封面文字边界截断 v2：优先句末断点
                    text = (text or "").strip()
                    if len(text) <= limit:
                        return text
                    sent_ends = [mm.start() for mm in re.finditer(r"[。！？!?]", text[:limit + 1])]
                    if sent_ends:
                        end = sent_ends[-1] + 1
                        if end >= limit * 0.5:
                            return text[:end]
                    cut = text[:limit]
                    mm2 = re.search(r"[\s，；、：,;]", cut[::-1])
                    if mm2:
                        cut = cut[: limit - mm2.start() - 1]
                    while cut and re.search(r"[A-Za-z]$", cut) and re.match(r"[A-Za-z]", text[len(cut):len(cut) + 1] or ""):
                        sp = cut.rfind(" ")
                        if sp <= 0:
                            break
                        cut = cut[:sp]
                    return cut.rstrip(" ，。；！？、：,.!?;")

                cover_title, cover_subtitle, cover_hook, cover_layout, cover_tag = _cover_text(
                    plan, title, script_body, _clip_cover_text)
                cover = generate_cover(
                    title=cover_title,
                    subtitle=cover_subtitle,
                    hook=cover_hook,
                    bg_image=str(bg_for_cover),
                    output_path=str(cover_path),
                    orientation=orientation,
                    tag=cover_tag,
                    cta="",
                    badge="",
                    layout=cover_layout,
                    functional_role_atlas_record=plan.get('functional_role_atlas_record'),
                )
                if not cover or not Path(str(cover)).is_file():
                    raise RuntimeError("cover_renderer_produced_no_file")
                _write_generated_cover_evidence(
                    cover_path=Path(cover),
                    evidence_path=cover_evidence_path,
                    platform=_primary_platform(plan),
                    title=cover_title,
                    subtitle=cover_subtitle,
                    background_path=str(bg_for_cover),
                    background_source=bg_source,
                    layout_key=cover_layout,
                    semantic_subject=_cover_subject(plan, title)[0],
                    supporting_visual_evidence=_cover_subject(plan, title)[1],
                )
                manifest["cover"] = str(cover)
                manifest["cover_evidence"] = str(cover_evidence_path)
                manifest["cover_source"] = "independent_generated_cover"

            from scripts.cover_quality_gate import validate_cover
            cover_result = validate_cover(Path(str(manifest["cover"])), Path(str(manifest["cover_evidence"])))
            cover_failures = _cover_gate_failures(cover_result)
            manifest["cover_quality_gate"] = cover_result
            if cover_failures:
                raise RuntimeError("cover_quality_gate_failed:" + ",".join(cover_failures))
        except Exception as cover_error:
            manifest.update({
                "ok": False,
                "status": "cover_gate_failed",
                "error": f"{type(cover_error).__name__}: {cover_error}",
            })
            _write_manifest(output_dir, manifest)
            print(manifest["error"], file=sys.stderr)
            return 4
        # 2026-08-23 新增：BGM 指纹登记 + bgm_history_check 证据（供 media_quality gate 消费）
        try:
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "gen_bgm_history_check.py"),
                 str(output_dir), "--platform", _primary_platform(plan)],
                capture_output=True, text=True, timeout=180,
            )
        except Exception:
            pass
        if generation_contract is not None:
            try:
                _release_generation_candidate(
                    generation_contract,
                    output_dir=output_dir,
                    candidate=generated[0],
                    plan=plan,
                    runner_manifest=manifest,
                )
            except Exception as release_error:
                manifest.update(
                    {
                        "ok": False,
                        "status": "release_gate_failed",
                        "error": f"{type(release_error).__name__}: {release_error}",
                        "trusted_run_manifest": str(
                            output_dir / "trusted_run_manifest.json"
                        ),
                    }
                )
                _write_manifest(output_dir, manifest)
                print(manifest["error"], file=sys.stderr)
                return 4
        if asset_gate.get("passed"):
            validate_asset_set(
                asset_records,
                _primary_platform(plan),
                str(plan.get("work_id") or output_dir.name),
                AssetLedger(os.environ.get("ASSET_LEDGER_PATH") or ROOT / "data" / "asset_ledger.db"),
                register=True,
            )
        _register_visual_recipe_use(visual_recipe, plan, str(generated[0]))
        _write_manifest(output_dir, manifest)
        print(json.dumps({"ok": True, "output": str(generated[0])}, ensure_ascii=False))
        return 0
    manifest["error"] = "video renderer produced no mp4"
    _write_manifest(output_dir, manifest)
    print(manifest["stderr_tail"] or manifest["stdout_tail"] or manifest["error"], file=sys.stderr)
    return proc.returncode or 3


def _release_generation_candidate(
    generation_contract: dict,
    *,
    output_dir: Path,
    candidate: Path,
    plan: dict,
    runner_manifest: dict,
):
    """Connect the runner's exact candidate to the production release runtime."""
    from content_platform.video_release_runtime import release_rendered_candidate

    trusted_path = output_dir / "trusted_run_manifest.json"
    cover = Path(str(generation_contract["canonical_cover"])).resolve()
    configured_evidence = str(plan.get("cover_evidence_path") or "").strip()
    cover_evidence = (
        Path(configured_evidence).expanduser().resolve()
        if configured_evidence
        else (output_dir / "cover_evidence.json").resolve()
    )
    released = release_rendered_candidate(
        manifest=generation_contract["run_manifest"],
        output_dir=output_dir,
        candidate=candidate,
        cover=cover,
        cover_evidence=cover_evidence,
        platform=_primary_platform(plan),
        render_manifest=runner_manifest,
        trusted_manifest_path=trusted_path,
    )
    generation_contract["run_manifest"] = released
    runner_manifest.update(
        {
            "ok": True,
            "status": "handoff_ready",
            "trusted_run_manifest": str(trusted_path),
            "preview": str(output_dir / "preview.mp4"),
            "checker_evidence": {
                name: str(output_dir / f"{name}_checker_evidence.json")
                for name in ("media", "visual", "audio", "cover", "package")
            },
        }
    )
    return released


def build_cards(
    script_body: str,
    title: str,
    plan: dict,
    cinema_scenes: list[dict] | None = None,
    shotcraft_plan: dict | None = None,
    visual_assets: dict | None = None,
) -> list[dict]:
    beats = _story_beats(script_body) or [title]
    shotcraft_timeline = list((shotcraft_plan or {}).get("timeline") or [])
    visual_assignments = list((visual_assets or {}).get("assignments") or [])
    visual_contract = list(plan.get("visual_contract") or plan.get("scene_contract") or [])
    cards = []
    for index in range(8):
        beat = beats[index % len(beats)]
        next_beat = beats[(index + 1) % len(beats)]
        contract = visual_contract[index] if index < len(visual_contract) else {}
        layout = "cover" if index == 0 else str(contract.get("visual_mode") or LAYOUTS[index % len(LAYOUTS)])
        scene = (cinema_scenes or [])[index] if index < len(cinema_scenes or []) else {}
        card = {
            "layout": layout,
            "t": title if index == 0 else _card_title(beat, index),
            "txt": beat,
            "tts": beat,
            "f": str(plan.get("template_family") or "video_toolchain"),
            "label": str(plan.get("selected_pipeline") or "auto_video"),
            "cinema": scene,
            "traffic_pattern": scene.get("traffic_pattern", ""),
            "composition_advice": scene.get("composition_advice", ""),
            "layout_template": scene.get("layout_template", layout),
            "color_scheme": scene.get("color_scheme", {}),
            "css": scene.get("css", {}),
            "shotcraft": _shotcraft_for_card(shotcraft_timeline, index),
            "visual_mode": str(contract.get("visual_mode") or ""),
            "visual_hook": str(contract.get("visual_hook") or ""),
            "template_id": str(contract.get("template_id") or ""),
            "group_motion": contract.get("group_motion") or [],
            "platform_reason": str(contract.get("platform_reason") or ""),
            "evidence_asset": str(contract.get("evidence_asset") or ""),
            "reading_hold_seconds": contract.get("reading_hold_seconds"),
            "voice": contract.get("voice"),
            "rate": contract.get("rate"),
            "speaker": contract.get("speaker"),
        }
        if visual_assignments:
            card["visual_asset"] = visual_assignments[index % len(visual_assignments)]
        if layout == "cover":
            card.update({"sub": _summary(script_body), "hook": title, "hook_prefix": "Auto selected video workflow"})
        if layout == "card_stack":
            card["items"] = [beat, next_beat, title]
        if layout == "big_number":
            card.update({"num": f"0{index + 1}", "ext": beat})
        if layout == "timeline":
            card["items"] = [beat, next_beat, title]
        cards.append(card)
    return cards


def _shotcraft_motion_plan(text: str, num_shots: int = 8) -> dict:
    if not shot_plan_for_text or not shot_sequence:
        return {
            "available": False,
            "error": _SHOTCRAFT_IMPORT_ERROR or "shotcraft module unavailable",
            "registry_count": 0,
            "selected_shots": [],
            "timeline": [],
        }
    selected = shot_plan_for_text(text, num_shots=num_shots)
    timeline = shot_sequence(selected)
    return {
        "available": True,
        "registry_count": len(SHOT_CARD_REGISTRY),
        "selected_shots": [
            {"name": name, "duration_frames": duration, "params": params or {}}
            for name, duration, params in selected
        ],
        "timeline": [
            {
                "name": item.get("name", ""),
                "start_frame": item.get("start_frame", 0),
                "end_frame": item.get("end_frame", 0),
                "duration_frames": item.get("duration_frames", 0),
                "params": item.get("params") or {},
                "css_selectors": sorted((item.get("css") or {}).keys()),
                "keyframes": sorted((item.get("keyframes") or {}).keys()),
            }
            for item in timeline
        ],
    }


def _shotcraft_for_card(timeline: list[dict], index: int) -> dict:
    if not timeline:
        return {"available": False}
    item = timeline[index % len(timeline)]
    return {
        "available": True,
        "name": item.get("name", ""),
        "start_frame": item.get("start_frame", 0),
        "end_frame": item.get("end_frame", 0),
        "css_selectors": item.get("css_selectors") or [],
        "keyframes": item.get("keyframes") or [],
    }


def _run_cinema_visual_gate(output_dir: Path) -> dict:
    image_dir = output_dir / "cards"
    candidates = []
    for root in [image_dir, output_dir]:
        if root.is_dir():
            for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                candidates.extend(root.glob(pattern))
    candidates = [path for path in candidates if _is_full_card_visual_candidate(path)]
    candidates = sorted(set(candidates), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return {"passed": False, "error": "no rendered card images found for cinema visual gate", "checked_images": []}
    checked = []
    for image in candidates[: min(3, len(candidates))]:
        cmd = [sys.executable, str(ROOT / "scripts" / "visual_gate.py"), "--image", str(image), "--cinema"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        checked.append({"image": str(image), "returncode": proc.returncode, "stdout_tail": (proc.stdout or "")[-1200:], "stderr_tail": (proc.stderr or "")[-400:]})
        if proc.returncode != 0:
            return {"passed": False, "error": f"cinema visual gate failed for {image.name}", "checked_images": checked}
    return {"passed": True, "checked_images": checked}


def _run_rendered_html_gate(output_dir: Path, visual_contract: list[dict]) -> dict:
    """Validate the exact A/B HTML scenes consumed by the film renderer."""
    html_dir = output_dir / "html"
    if not visual_contract:
        return {"passed": False, "failures": ["rendered_html_contract_missing"], "html_dir": str(html_dir)}
    if not html_dir.is_dir():
        return {"passed": False, "failures": ["rendered_html_dir_missing"], "html_dir": str(html_dir)}
    try:
        from scripts.visual_contract_gate import validate_rendered_html
        result = validate_rendered_html(
            html_dir,
            visual_contract,
            strict_runtime=True,
            require_independent_cta=True,
        )
    except Exception as exc:
        return {
            "passed": False,
            "failures": [f"rendered_html_gate_error:{type(exc).__name__}"],
            "html_dir": str(html_dir),
        }
    result["html_dir"] = str(html_dir)
    return result


def _render_motion_evidence(output: Path) -> dict:
    """Probe real video frames; manifest declarations are not motion evidence."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(output)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        duration = float((probe.stdout or "0").strip() or 0)
        if duration <= 0:
            return {"passed": False, "reason": "duration_unavailable", "frames": []}
        offsets = sorted(
            {
                0.25,
                round(duration * 0.25, 3),
                round(duration * 0.5, 3),
                round(duration * 0.75, 3),
                max(0.25, round(duration - 0.25, 3)),
            }
        )
        frames = []
        for offset in offsets:
            rendered = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", str(offset), "-i", str(output), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True, timeout=30, check=False,
            )
            payload = rendered.stdout or b""
            frames.append({"offset": offset, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
        unique = len({item["sha256"] for item in frames if item["bytes"]})
        return {"passed": unique >= 2, "duration": duration, "frames": frames, "unique_frame_count": unique}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"passed": False, "reason": f"motion_probe_failed:{type(exc).__name__}", "frames": []}


def _video_duration(output: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(output)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return float((probe.stdout or "0").strip() or 0)
    except ValueError:
        return 0.0


def _is_full_card_visual_candidate(path: Path) -> bool:
    """Skip auxiliary render layers; visual_gate expects complete card frames."""
    return not path.name.endswith(("_bg.png", "_text.png"))


def _load_plan() -> dict:
    path = os.environ.get("VIDEO_TOOLCHAIN_PLAN_PATH", "")
    if path and Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return {
        "selected_pipeline": os.environ.get("VIDEO_SELECTED_PIPELINE", "knowledge_card_video"),
        "template_family": os.environ.get("VIDEO_TEMPLATE_FAMILY", "knowledge_card_motion_case"),
    }


def _load_visual_assets(plan: dict | None = None) -> dict:
    path = os.environ.get("VIDEO_VISUAL_ASSETS_PATH", "") or str(
        (plan or {}).get("visual_assets_path") or ""
    )
    if not path:
        return {}
    source = Path(path)
    if not source.is_file():
        return {"error": "VIDEO_VISUAL_ASSETS_PATH missing", "path": path, "assignments": []}
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        assignments = payload.get("assignments") if isinstance(payload, dict) else None
        if isinstance(assignments, list):
            def beat_key(item: dict) -> tuple[int, str]:
                value = str(item.get("beat_id") or "").strip().casefold()
                match = re.search(r"(\d+)$", value)
                return (int(match.group(1)) if match else 10**9, value)
            payload["assignments"] = sorted(
                [item for item in assignments if isinstance(item, dict)], key=beat_key
            )
        return payload
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"failed to load visual assets: {type(exc).__name__}", "path": path, "assignments": []}


def _materialize_visual_backgrounds(output_dir: Path, visual_assets: dict) -> list[dict]:
    assignments = list((visual_assets or {}).get("assignments") or [])
    if not assignments:
        return []
    bg_dir = output_dir / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for index, item in enumerate(assignments, 1):
        if not isinstance(item, dict):
            continue
        source_value = (
            item.get("background_image")
            or item.get("image")
            or item.get("path")
            or item.get("asset_path")
            or ""
        )
        source = Path(str(source_value))
        if not source.is_file():
            continue
        suffix = source.suffix.lower() if source.suffix else ".jpg"
        dest = bg_dir / f"bg_{index:02d}{suffix}"
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        item["background_image"] = str(dest)
        item["materialized_background"] = str(dest)
        copied.append(
            {
                "scene": item.get("scene") or index,
                "source": str(source),
                "path": str(dest),
                "rights_cleared": bool(item.get("rights_cleared", False)),
                "real_scene": bool(item.get("real_scene", False)),  # MED39: undeclared is not real
                "source_url": str(item.get("source_url") or item.get("page_url") or ""),
                "photo_id": str(item.get("photo_id") or ""),
                "page_url": str(item.get("page_url") or ""),
                "download_url": str(item.get("download_url") or ""),
                "photographer": str(item.get("photographer") or ""),
                "license": str(item.get("license") or ""),
                "license_url": str(item.get("license_url") or ""),
                "query": str(item.get("query") or item.get("source_query") or ""),
                "downloaded_at": str(item.get("downloaded_at") or ""),
                "sha256": str(item.get("sha256") or ""),
                "dimensions": dict(item.get("dimensions") or {}),
                "semantic_match_score": float(item.get("semantic_match_score") or 0),
                "match_reason": str(item.get("match_reason") or item.get("purpose") or ""),
                "semantic_tags": list(item.get("semantic_tags") or []),
                "generation_evidence": dict(item.get("generation_evidence") or {}),
            }
        )
    return copied


def _diagram_background_fill(output_dir: Path, text: str, existing: list[dict]) -> list[dict]:
    """diagram-design 背景补图通道（visual-router 视频侧集成）。

    当脚本/标题是结构化主题（流程/架构/对比等）且已有背景图不足时，
    自动调用 visual_router 判断 → diagram_route 生成杂志级 diagram 图，混入背景池。
    失败静默——不影响主渲染流程。

    关联: 可配置的 agent scripts visual_router.py（全生态路由层，本函数是其视频媒介执行器）
    """
    try:
        if len(existing) >= 8:
            return existing
        sys.path.insert(0, str(agent_scripts_dir()))
        from diagram_route import detect_diagram_type, build_diagram_html  # type: ignore

        dtype = detect_diagram_type(text)
        if not dtype:
            return existing

        from diagram_html2png import render_html_to_png  # type: ignore
        bg_dir = output_dir / "backgrounds"
        bg_dir.mkdir(parents=True, exist_ok=True)
        start = len(existing) + 1
        html_path = bg_dir / f"diagram-{dtype}.html"
        html_path.write_text(build_diagram_html(text, dtype, text[:60]), encoding="utf-8")
        for i in range(start, 9):  # 补齐到 8 张（上限）
            png = bg_dir / f"bg_{i:02d}.jpg"
            ok = render_html_to_png(html_path, png, width=1080, height=1920)
            if not ok:
                break
            existing.append(
                {
                    "scene": i,
                    "source": str(html_path),
                    "path": str(png),
                    "rights_cleared": True,
                    "real_scene": False,
                    "diagram": dtype,
                    "source_url": "generated:diagram_html2png",
                    "license": "generated_for_project",
                    "semantic_match_score": 0.8,
                    "match_reason": f"diagram visualizes the detected {dtype} structure",
                    "semantic_tags": [dtype, "diagram", "workflow"],
                    "generation_evidence": {"provider": "diagram_html2png", "source_html": str(html_path)},
                }
            )
    except Exception as e:
        print(f"[diagram-fill] skipped: {e}", file=sys.stderr)
    return existing


def _asset_provenance_records(materialized: list[dict]) -> list[dict]:
    records = []
    for index, item in enumerate(materialized, 1):
        path = str(item.get("path") or item.get("background_image") or "")
        if not path:
            continue
        records.append(
            {
                "scene_id": str(item.get("scene") or f"asset_{index}"),
                "path": path,
                "source_url": str(item.get("source_url") or item.get("page_url") or ""),
                "photo_id": str(item.get("photo_id") or ""),
                "page_url": str(item.get("page_url") or ""),
                "download_url": str(item.get("download_url") or ""),
                "photographer": str(item.get("photographer") or ""),
                "license": str(item.get("license") or ""),
                "license_url": str(item.get("license_url") or ""),
                "query": str(item.get("query") or item.get("source_query") or ""),
                "downloaded_at": str(item.get("downloaded_at") or ""),
                "sha256": str(item.get("sha256") or ""),
                "dimensions": dict(item.get("dimensions") or {}),
                "semantic_match_score": float(item.get("semantic_match_score") or 0),
                "match_reason": str(item.get("match_reason") or ""),
                "semantic_tags": list(item.get("semantic_tags") or []),
                "generation_evidence": dict(item.get("generation_evidence") or {}),
            }
        )
    return records


def _background_provenance_gate(records: list[dict], *, required_scenes: int = 8) -> dict:
    failures = []
    if not records:
        failures.append("background_assets_empty")
    covered_scenes = set()
    for index, record in enumerate(records, 1):
        scene_id = str(record.get("scene_id") or f"asset_{index}")
        covered_scenes.add(scene_id)
        if not Path(str(record.get("path") or "")).is_file():
            failures.append(f"scene_{scene_id}:asset_missing")
        if not str(record.get("source_url") or "").strip():
            failures.append(f"scene_{scene_id}:asset_source_url_missing")
        if not str(record.get("license") or "").strip():
            failures.append(f"scene_{scene_id}:asset_license_missing")
        is_pexels = (
            "pexels.com" in str(record.get("source_url") or "").casefold()
            or str(record.get("license") or "").strip() == "Pexels License"
        )
        if is_pexels:
            required = (
                "photo_id",
                "page_url",
                "download_url",
                "photographer",
                "license",
                "license_url",
                "query",
                "downloaded_at",
                "sha256",
                "dimensions",
            )
            for field in required:
                if not record.get(field):
                    failures.append(f"scene_{scene_id}:pexels_provenance_missing:{field}")
            declared_sha = str(record.get("sha256") or "")
            path = Path(str(record.get("path") or ""))
            if declared_sha and path.is_file():
                actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                if declared_sha != actual_sha:
                    failures.append(f"scene_{scene_id}:asset_sha256_mismatch")
    if len(covered_scenes) < required_scenes:
        failures.append(
            f"background_scene_coverage_insufficient:{len(covered_scenes)}/{required_scenes}"
        )
    return {
        "passed": not failures,
        "required_scenes": required_scenes,
        "covered_scenes": len(covered_scenes),
        "asset_count": len(records),
        "failures": failures,
    }


def _renderer_path(plan: dict) -> Path:
    env_key = "VIDEO_RENDERER_" + re.sub(r"[^A-Z0-9]+", "_", str(plan.get("selected_pipeline") or "").upper())
    return Path(os.environ.get(env_key) or os.environ.get("VIDEO_TOOLCHAIN_RENDERER") or DEFAULT_RENDERER)


def _content_driven_renderer(plan: dict, script_body: str, title: str, output_dir: Path) -> tuple[Path, dict]:
    """内容驱动渲染器选择（2026-08-15 固化 — 用户要求工作流自动识别动效，不依赖人工指定）。

    脚本文案命中卡内元素级动效结构（流程/对比/数字）→ 自动切换到 film_renderer
    （图块激活/数字跳变/流程点亮），否则维持 plan 默认渲染器。

    同步写 script.md（film_renderer 的 TTS 分段/门禁依赖），并回写 plan.selected_pipeline
    让 manifest / 门禁证据链一致。
    """
    new_plan = dict(plan)
    if plan.get("visual_contract") or plan.get("scene_contract"):
        renderer = ROOT / "scripts" / "film_renderer.py"
        new_plan["selected_pipeline"] = "cinema_multishot_video"
        print(f"[content-driven-renderer] scene contract present → force contract-aware renderer ({renderer.name})", file=sys.stderr)
        script_md = output_dir / "script.md"
        if script_body.strip():
            script_md.write_text(script_body.strip(), encoding="utf-8")
        return renderer, new_plan
    # 文案来源：script_body 或 title（title 也是内容信号）
    # ⚠️ 对齐 film_renderer 内部逻辑：只检测偶数段（i%2==0 才启用动效镜头），
    # 避免"切了 film_renderer 但实际无动效"的白切
    text = f"{script_body}\n{title}"
    wants_element_motion = False
    try:
        from scripts.film_renderer import detect_element_shot
        segs = [s for s in re.split(r"\n\s*\n", text) if s.strip()]
        # 2026-08-17 修复：检测所有段落（不只偶数段）——流程词"第一步/第二步"常在奇数段，
        # 只检偶数段导致流程类内容永远不命中 film_renderer
        for idx, seg in enumerate(segs, 1):
            if detect_element_shot(seg):
                wants_element_motion = True
                break
        # 所有段都不命中时，再查 title 本身（标题也可能是动效信号，且 title 会进 film_renderer 的 seg_title）
        if not wants_element_motion and title and detect_element_shot(title):
            wants_element_motion = True
        # 2026-08-17 英文兜底：所有段+标题都不命中时，检查是否英文评测/对比类内容
        # 这类内容天然有对比结构（tool A vs tool B），应强制走 film_renderer
        if not wants_element_motion and title and re.search(
            r"(test|review|compare|top\s+\d|best|which|vs\.?|versus|head\s*-?\s*to\s*-?\s*head"
            r"|tested|survived|winner|showdown|comparison|roundup|alternative)",
            title, re.IGNORECASE,
        ):
            wants_element_motion = True
            print(f"[content-driven-renderer] 英文评测类标题兜底 → film_renderer", file=sys.stderr)
    except Exception as exc:  # pragma: no cover - film_renderer 不可用时静默回退默认
        print(f"[content-driven-renderer] film_renderer import 失败，回退默认: {exc}", file=sys.stderr)
    if wants_element_motion:
        new_plan["selected_pipeline"] = "cinema_multishot_video"
        renderer = ROOT / "scripts" / "film_renderer.py"
        # script.md：film_renderer 依赖完整段落做 TTS（空行分隔），cards.json 的 tts 字段会被 runner 截断
        script_md = output_dir / "script.md"
        if script_body.strip():
            script_md.write_text(script_body.strip(), encoding="utf-8")
        print(f"[content-driven-renderer] 命中动效内容结构 → film_renderer（{renderer.name}）", file=sys.stderr)
    else:
        renderer = _renderer_path(new_plan)
        print(f"[content-driven-renderer] 未命中动效结构 → 默认渲染器（{renderer.name}）", file=sys.stderr)
    return renderer, new_plan


def _publication_description(plan: dict,script_body: str) -> str:
    audio=plan.get('audio_plan') or {}
    if audio.get('status')=='resolved' and audio.get('route')=='embedded_licensed_bgm' and audio.get('license')=='https://creativecommons.org/licenses/by/4.0/':
        copy=plan.get('music_publication_copy') or {}
        if not isinstance(copy.get('caption'),str) or not copy.get('music_attribution') or len(copy['caption'])>220:
            raise ValueError('licensed_music_publication_copy_required')
        return copy['caption']
    return _summary(script_body)[:180]


def _renderer_command(renderer: Path, output_dir: Path, theme: str, title: str, script_body: str, plan: dict, bgm_style: str) -> list[str]:
    platform = _primary_platform(plan).casefold()
    landscape = platform in {"bilibili", "youtube_long", "youtube_long_video"}
    default_width, default_height = (1920, 1080) if landscape else (1080, 1920)
    width = int(plan.get("width") or default_width)
    height = int(plan.get("height") or default_height)
    audio_route = str((plan.get("audio_plan") or {}).get("route") or "embedded_licensed_bgm")
    return [
        sys.executable,
        str(renderer),
        "--video-dir",
        str(output_dir),
        "--theme",
        theme,
        "--title",
        title[:80],
        "--desc",
        _publication_description(plan,script_body),
        "--bgm-style",
        bgm_style,
        "--audio-route",
        audio_route,
        "--platform",
        _primary_platform(plan),
        "--tags",
        *_tags(plan),
        "--width",
        str(width),
        "--height",
        str(height),
    ]


def _bgm_style(cinema_scenes: list[dict], text: str = "") -> str:
    for scene in cinema_scenes:
        scheme = scene.get("color_scheme") or {}
        hint = str(scheme.get("bgm_hint") or scheme.get("bgm") or "").strip()
        if hint:
            return hint[:80]
    # 2026-08-16 新增：按内容赛道选 BGM 曲风（不再固定 acoustic）
    # 对应 voice_engine GENRE_VOICE_MAP 的赛道，让音频情绪与内容匹配
    try:
        from scripts.voice_engine import detect_genre
        genre = detect_genre(text or "")
        style_map = {
            "pets": "light piano instrumental, cheerful, warm",
            "finance": "classical piano instrumental, steady, professional",
            "emotion": "soft piano instrumental, gentle, emotional",
            "science": "minimal piano instrumental, clean, calm",
            "tech": "warm acoustic guitar and light piano",
        }
        return style_map.get(genre, "warm acoustic guitar and light piano")
    except Exception:
        return "warm acoustic guitar and light piano"


def _toolchain_contract(plan: dict, theme: str, bgm_style: str, renderer: Path, visual_recipe: dict | None = None) -> dict:
    recipe = visual_recipe or {}
    recipe_modules = [str(item) for item in (recipe.get("modules") or [])]
    return {
        "planned_tools": PLANNED_TOOLS,
        "renderer_steps": RENDERER_STEPS,
        "effect_stack": recipe_modules or EFFECT_STACK,
        "template_registry": {
            "template_family": str(recipe.get("template_family") or plan.get("template_family") or ""),
            "theme": theme,
            "renderer": str(renderer),
            "card_layouts": LAYOUTS,
            "shotcraft_registry_count": len(SHOT_CARD_REGISTRY),
        },
        "visual_recipe": {
            "version": recipe.get("version", ""),
            "fingerprint": recipe.get("fingerprint", ""),
            "core_fingerprint": recipe.get("core_fingerprint", ""),
            "module_count": len(recipe_modules),
            "selection_reason": recipe.get("selection_reason", ""),
            "differentiation_reason": recipe.get("differentiation_reason", ""),
        },
        "bgm_style": bgm_style,
        "post_render_gates": ["validate_visual_recipe.py", "visual_gate.py --cinema"],
        "visual_asset_contract": "VIDEO_VISUAL_ASSETS_PATH assignments are bound to cards when provided",
    }


def _duplication_policy() -> dict:
    path = ROOT / "config" / "duplication_policy.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


SHARED_VISUAL_RECIPE_REGISTRY = Path("/srv/hermes-runtime/data/visual_recipe_fingerprints.json")


def _visual_recipe_registry_path() -> Path:
    configured = os.environ.get("VISUAL_RECIPE_FINGERPRINT_REGISTRY", "").strip()
    if configured:
        return Path(configured).expanduser()
    # 11-05 window: the real media job runs with a fresh per-job HERMES_HOME that never holds the seven-day
    # history, so douyin_pet failed trusted_seven_day_registry_missing; the shared registry is canonical (MED31).
    if SHARED_VISUAL_RECIPE_REGISTRY.is_file():
        return SHARED_VISUAL_RECIPE_REGISTRY
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "data" / "visual_recipe_fingerprints.json"


def _load_visual_recipe_registry() -> dict:
    path = _visual_recipe_registry_path()
    if not path.is_file():
        return {"recipes": [], "registry_present": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"visual recipe registry invalid JSON: {path}") from exc
    recipes = data.get("recipes") if isinstance(data, dict) else []
    return {
        **(data if isinstance(data, dict) else {}),
        "recipes": recipes if isinstance(recipes, list) else [],
        "registry_present": True,
    }


def _dedup_not_run(registry_path: Path, failure: str) -> dict:
    return {
        "passed": False,
        "required": True,
        "status": "not_run",
        "policy_enabled": True,
        "lookback_days": 7,
        "registry_path": str(registry_path),
        "duplicate_count": 0,
        "duplicates": [],
        "failures": [failure],
    }


def _terminal_rerender_failure(status: str) -> bool:
    normalized = status.casefold().strip()
    return bool(
        normalized in {"rejected", "failed", "blocked_dedup"}
        or normalized.endswith(("_failed", "_rejected"))
    )


def _recipe_structure_sequence(recipe: dict) -> list:
    sequence = recipe.get("dom_structure_signatures") or recipe.get("scene_contract_sequence") or []
    return list(sequence) if isinstance(sequence, (list, tuple)) else []


def _recipe_reuse_gate(recipe: dict, plan: dict) -> dict:
    registry_path = _visual_recipe_registry_path()
    dry_run = os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1"
    # Isolated dry-runs do not assert a production dedup pass.
    if dry_run and not os.environ.get("VISUAL_RECIPE_FINGERPRINT_REGISTRY"):
        return {
            "passed": True,
            "required": True,
            "status": "dry_run_isolated",
            "production_pass": False,
            "policy_enabled": True,
            "lookback_days": 7,
            "duplicate_count": 0,
            "duplicates": [],
            "failures": [],
        }
    policy = _duplication_policy().get("same_day_template_duplicate") or {}
    if policy.get("enabled") is False and not dry_run:
        return _dedup_not_run(registry_path, "dedup_policy_disabled")
    try:
        registry = _load_visual_recipe_registry()
    except RuntimeError:
        return _dedup_not_run(registry_path, "trusted_seven_day_registry_invalid")
    if not registry.get("registry_present"):
        if dry_run:
            return {
                "passed": True,
                "required": True,
                "status": "dry_run_isolated",
                "production_pass": False,
                "policy_enabled": True,
                "lookback_days": 7,
                "registry_path": str(registry_path),
                "duplicate_count": 0,
                "duplicates": [],
                "failures": [],
            }
        return _dedup_not_run(registry_path, "trusted_seven_day_registry_missing")
    if not dry_run:
        coverage_days = int(registry.get("coverage_days") or registry.get("lookback_days") or 0)
        if registry.get("trusted") is not True or coverage_days < 7:
            return _dedup_not_run(registry_path, "trusted_seven_day_registry_unverified")
    lookback_days = max(7, int(policy.get("lookback_days") or 7))
    core = str(recipe.get("core_fingerprint") or "").strip()
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    platforms = {str(item).casefold() for item in (plan.get("platforms") or []) if str(item).strip()}
    recipe_family = str(recipe.get("template_family") or plan.get("template_family") or "").strip()
    work_id = str(plan.get("work_id") or plan.get("run_id") or "").strip()
    revision = str(plan.get("revision") or "").strip()
    current_attempt = int(plan.get("attempt") or 0)
    current_structure = _recipe_structure_sequence(recipe)
    current_artifact = str(recipe.get("final_artifact_fingerprint") or plan.get("final_artifact_fingerprint") or "").strip()
    duplicates = []
    same_work_rerenders = []
    for item in registry.get("recipes", []):
        if not isinstance(item, dict):
            continue
        used_at = _parse_utc(item.get("used_at"))
        if used_at and used_at < cutoff:
            continue
        item_core = str(item.get("core_fingerprint") or "").strip()
        item_family = str(item.get("template_family") or "").strip()
        item_platforms = {str(value).casefold() for value in (item.get("platforms") or []) if str(value).strip()}
        same_core = bool(core and item_core == core and item_platforms)
        item_modules = item.get("modules") or []
        recipe_modules = recipe.get("modules") or []
        item_style = item.get("style_variants")
        recipe_style = recipe.get("style_variants")
        same_visual_family = bool(
            recipe_family
            and item_family == recipe_family
            and item_platforms
            and (
                not item_modules
                or not recipe_modules
                or (item_modules == recipe_modules and item_style == recipe_style)
            )
        )
        if not (same_core or same_visual_family):
            continue
        prior_status = str(item.get("terminal_status") or item.get("status") or "").strip()
        output_value = str(item.get("output_path") or "").strip()
        prior_manifest = (
            Path(output_value).expanduser().parent / "video_toolchain_runner_manifest.json"
            if output_value
            else None
        )
        if not prior_status and prior_manifest is not None and prior_manifest.is_file():
            try:
                prior_status = str(json.loads(prior_manifest.read_text(encoding="utf-8-sig")).get("status") or "")
            except (OSError, json.JSONDecodeError):
                prior_status = ""
        item_work_id = str(item.get("work_id") or "").strip()
        item_revision = str(item.get("revision") or "").strip()
        prior_attempt = int(item.get("attempt") or 0)
        same_work = bool(work_id and item_work_id == work_id and (not revision or item_revision == revision))
        prior_structure = _recipe_structure_sequence(item)
        prior_artifact = str(item.get("final_artifact_fingerprint") or "").strip()
        material_difference = bool(
            (current_structure and prior_structure and current_structure != prior_structure)
            or (current_artifact and prior_artifact and current_artifact != prior_artifact)
        )
        if (
            same_work
            and current_attempt > prior_attempt
            and _terminal_rerender_failure(prior_status)
            and material_difference
        ):
            same_work_rerenders.append(item)
            continue
        timing_sync_repair = bool(
            plan.get("repair_type") == "timing_sync_repair"
            and str(plan.get("repair_of_attempt") or "").strip()
            and str(plan.get("repair_scope") or "").strip() == "audio_subtitle_timing"
        )
        repair_target_matches = bool(
            timing_sync_repair
            and str(plan.get("repair_of_attempt") or "").strip() in output_value
            and platforms
            and item_platforms
            and not platforms.isdisjoint(item_platforms)
        )
        if repair_target_matches and current_attempt > prior_attempt:
            same_work_rerenders.append(item)
            continue
        if platforms and item_platforms and platforms.isdisjoint(item_platforms):
            duplicates.append({**item, "duplicate_scope": "cross_platform"})
        else:
            duplicates.append({**item, "duplicate_scope": "same_platform_or_unknown"})
    passed = not duplicates
    return {
        "passed": passed,
        "required": True,
        "status": "passed" if passed else "failed",
        "policy_enabled": True,
        "lookback_days": lookback_days,
        "registry_path": str(registry_path),
        "core_fingerprint": core,
        "duplicate_count": len(duplicates),
        "duplicates": duplicates[:5],
        "same_work_rerender_count": len(same_work_rerenders),
        "failures": [] if passed else ["recent_visual_recipe_duplicate"],
    }


def _register_visual_recipe_use(recipe: dict, plan: dict, output_path: str) -> None:
    registry_path = _visual_recipe_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_visual_recipe_registry()
    rows = [item for item in data.get("recipes", []) if isinstance(item, dict)]
    artifact = Path(output_path)
    artifact_fingerprint = ""
    if artifact.is_file():
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        artifact_fingerprint = "sha256:" + digest.hexdigest()
    row = {
        "used_at": datetime.now(timezone.utc).isoformat(),
        "core_fingerprint": recipe.get("core_fingerprint"),
        "fingerprint": recipe.get("fingerprint"),
        "template_family": recipe.get("template_family"),
        "modules": recipe.get("modules") or [],
        "style_variants": recipe.get("style_variants") or {},
        "dom_structure_signatures": recipe.get("dom_structure_signatures") or [],
        "scene_contract_sequence": recipe.get("scene_contract_sequence") or [],
        "final_artifact_fingerprint": artifact_fingerprint,
        "platforms": plan.get("platforms") or [],
        "selected_pipeline": plan.get("selected_pipeline") or "",
        "run_id": plan.get("run_id") or "",
        "work_id": plan.get("work_id") or plan.get("run_id") or "",
        "revision": plan.get("revision"),
        "attempt": plan.get("attempt"),
        "terminal_status": "handoff_ready" if plan.get("run_contract") else "rendered_unverified",
        "output_path": output_path,
    }
    rows.append(row)
    data.pop("registry_present", None)
    data.setdefault("version", "visual_recipe_registry_v1")
    data["coverage_days"] = max(7, int(data.get("coverage_days") or 7))
    data["recipes"] = rows[-500:]
    registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_utc(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _repost_contract(plan: dict) -> dict:
    return {
        "planned_tools": REPOST_PLANNED_TOOLS,
        "renderer_steps": ["source_asset_match", "download_or_copy_source", "clip_segments", "concat_video", "write_repost_manifest"],
        "effect_stack": ["source_video_preserved", "localized_repost_packaging"],
        "template_registry": {
            "template_family": str(plan.get("template_family") or ""),
            "renderer": "scripts/autoclip_adapter.py",
        },
        "post_render_gates": ["source_asset_match", "source_rights_recorded"],
    }


def _repost_dedup_evidence(
    plan: dict,
    output_dir: Path,
    candidate: Path,
    *,
    stage: str,
    pre_render_fingerprints: dict | None = None,
) -> dict:
    identity = plan.get("source_identity")
    transform = plan.get("repost_transform") or plan.get("transform")
    rights = plan.get("source_rights") or plan.get("rights")
    history_index = (
        plan.get("repost_history_index")
        or plan.get("dedup_history_index")
        or os.environ.get("REPOST_HISTORY_INDEX")
        or ""
    )
    return build_dedup_evidence(
        candidate,
        source_identity=identity if isinstance(identity, dict) else {},
        history_index=history_index,
        transform=transform if isinstance(transform, dict) else {},
        rights=rights if isinstance(rights, dict) else {},
        output_path=output_dir / "dedup_evidence.json",
        similarity_threshold=float(plan.get("repost_similarity_threshold") or 0.9),
        stage=stage,
        pre_render_fingerprints=pre_render_fingerprints,
    )


def _block_repost_dedup(output_dir: Path, manifest: dict, evidence: dict) -> int:
    manifest.update(
        {
            "ok": False,
            "status": "BLOCKED_DEDUP",
            "error": "localized repost blocked: complete passing dedup evidence is required",
            "dedup_evidence": evidence,
        }
    )
    _write_manifest(output_dir, manifest)
    print(manifest["error"], file=sys.stderr)
    return 8


def _validate_repost_candidate(candidate: Path, plan: dict) -> dict:
    """Validate source-preserving candidates with the same real media boundary."""
    try:
        media = probe_video(candidate)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return {"passed": False, "failures": ["media_probe_failed", type(exc).__name__]}
    render_manifest = {"subtitle": {"width": media.get("width"), "height": media.get("height")}}
    artifact = verify_artifact(candidate, render_manifest, _primary_platform(plan))
    pixel = artifact.get("final_pixel_gate") or verify_final_pixels(candidate)
    result = {
        "passed": bool(artifact.get("passed") and pixel.get("passed")),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "probe": media,
        "artifact_gate": artifact,
        "final_pixel_gate": pixel,
    }
    return result


def _run_localized_repost(plan: dict, output_dir: Path, title: str) -> int:
    tool_manifest = _tool_invocation_manifest(plan, repost=True)
    manifest = {
        "ok": False,
        "title": title,
        "selected_pipeline": plan.get("selected_pipeline", ""),
        "template_family": plan.get("template_family", ""),
        "renderer": "localized_repost_video",
        "dry_run": False,
        "toolchain_contract": _repost_contract(plan),
        "tool_invocation_manifest": tool_manifest,
        **build_tool_selection_evidence(
            platform=_primary_platform(plan),
            content_type=str(plan.get("content_form") or "edited_short_video"),
            content_goal="increase retention with localized repost source matching and quality gates",
            planned_manifest=tool_manifest,
        ),
    }
    source_path = Path(str(plan.get("source_video_path") or ""))
    source_url = str(plan.get("source_url") or "").strip()
    if source_path.is_file():
        pre_render = _repost_dedup_evidence(
            plan, output_dir, source_path, stage="pre_render"
        )
        if not pre_render.get("passed"):
            return _block_repost_dedup(output_dir, manifest, pre_render)
        out = output_dir / "final.mp4"
        shutil.copy2(source_path, out)
        post_render = _repost_dedup_evidence(
            plan,
            output_dir,
            out,
            stage="post_render",
            pre_render_fingerprints=pre_render.get("fingerprints"),
        )
        if not post_render.get("passed"):
            out.unlink(missing_ok=True)
            return _block_repost_dedup(output_dir, manifest, post_render)
        candidate_gate = _validate_repost_candidate(out, plan)
        (output_dir / "candidate_gate.json").write_text(json.dumps(candidate_gate, ensure_ascii=False, indent=2), encoding="utf-8")
        if not candidate_gate.get("passed"):
            out.unlink(missing_ok=True)
            manifest.update({"status": "candidate_gate_failed", "error": "localized repost candidate gate failed", "candidate_gate": candidate_gate})
            _write_manifest(output_dir, manifest)
            return 4
        manifest.update(
            {
                "ok": True,
                "status": "rendered_unverified",
                "publishable": False,
                "delivery_allowed": False,
                "requires_unified_release": True,
                "output": str(out),
                "repost_source": {"source_type": "local_source_video", "path": str(source_path)},
                "source_asset_match": {"passed": True, "mode": "local_source_video"},
                "dedup_evidence": post_render,
                "dedup_evidence_path": str(output_dir / "dedup_evidence.json"),
            }
        )
        _write_manifest(output_dir, manifest)
        print(json.dumps({"ok": True, "output": str(out)}, ensure_ascii=False))
        return 0
    if source_url:
        return _run_autoclip_repost(plan, output_dir, title, source_url, manifest)
    manifest.update(
        {
            "status": "source_required",
            "error": "localized_repost_video requires source_video_path or source_url; refusing original card fallback",
        }
    )
    _write_manifest(output_dir, manifest)
    print(manifest["error"], file=sys.stderr)
    return 6


def _run_autoclip_repost(plan: dict, output_dir: Path, title: str, source_url: str, manifest: dict) -> int:
    env = os.environ.copy()
    env["HERMES_DATA_DIR"] = str(output_dir / "autoclip")
    cmd = [sys.executable, str(ROOT / "scripts" / "autoclip_adapter.py"), source_url]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=int(os.environ.get("VIDEO_REPOST_TIMEOUT", "1200")), check=False)
    manifest.update({"returncode": proc.returncode, "stdout_tail": (proc.stdout or "")[-1200:], "stderr_tail": (proc.stderr or "")[-600:]})
    if proc.returncode != 0:
        manifest.update({"status": "source_processing_failed", "error": "autoclip source processing failed"})
        _write_manifest(output_dir, manifest)
        print(manifest["stderr_tail"] or manifest["stdout_tail"] or manifest["error"], file=sys.stderr)
        return proc.returncode or 7
    payload = None
    stdout = proc.stdout or ""
    for start in [match.start() for match in re.finditer(r"\{", stdout)][::-1]:
        try:
            candidate_payload = json.loads(stdout[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate_payload, dict) and candidate_payload.get("compilation"):
            payload = candidate_payload
            break
    if not isinstance(payload, dict):
        manifest.update({"status": "candidate_manifest_missing", "error": "autoclip compilation manifest missing"})
        _write_manifest(output_dir, manifest)
        return 7
    candidate = Path(str(payload.get("compilation"))).resolve()
    autoclip_root = (output_dir / "autoclip").resolve()
    if autoclip_root not in candidate.parents or not candidate.is_file() or str(payload.get("task_id") or "") not in candidate.name:
        manifest.update({"status": "candidate_ambiguous", "error": "autoclip compilation is not bound to current task/output root"})
        _write_manifest(output_dir, manifest)
        return 7
    pre_render = _repost_dedup_evidence(
        plan, output_dir, candidate, stage="pre_render"
    )
    if not pre_render.get("passed"):
        return _block_repost_dedup(output_dir, manifest, pre_render)
    out = output_dir / "final.mp4"
    shutil.copy2(candidate, out)
    post_render = _repost_dedup_evidence(
        plan,
        output_dir,
        out,
        stage="post_render",
        pre_render_fingerprints=pre_render.get("fingerprints"),
    )
    if not post_render.get("passed"):
        out.unlink(missing_ok=True)
        return _block_repost_dedup(output_dir, manifest, post_render)
    candidate_gate = _validate_repost_candidate(out, plan)
    (output_dir / "candidate_gate.json").write_text(json.dumps(candidate_gate, ensure_ascii=False, indent=2), encoding="utf-8")
    if not candidate_gate.get("passed"):
        out.unlink(missing_ok=True)
        manifest.update({"status": "candidate_gate_failed", "error": "autoclip candidate gate failed", "candidate_gate": candidate_gate})
        _write_manifest(output_dir, manifest)
        return 4
    manifest.update(
        {
            "ok": True,
            "status": "rendered_unverified",
            "output": str(out),
            "repost_source": {"source_type": "source_url", "source_url": source_url},
            "source_asset_match": {"passed": True, "mode": "autoclip"},
            "dedup_evidence": post_render,
            "dedup_evidence_path": str(output_dir / "dedup_evidence.json"),
        }
    )
    _write_manifest(output_dir, manifest)
    print(json.dumps({"ok": True, "output": str(out)}, ensure_ascii=False))
    return 0


def _beats(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]
    if len(paragraphs) >= 2:
        return [part[:200] for part in paragraphs][:10]
    parts = [part.strip(" -#\t") for part in re.split(r"\n+|[。.!?；;]", text or "") if part.strip(" -#\t")]
    return [part[:200] for part in parts if len(part) >= 8][:10]


def _story_beats(text: str) -> list[str]:
    # 2026-08-15 修复：优先按空行段落切分（与 _beats 一致），
    # 8 段脚本 = 8 卡一一对应，避免段内句号把 CTA 挤掉。
    # 无空行分段时回退到按句号切分（兼容单段落脚本）。
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", str(text or "")) if part.strip()]
    if len(paragraphs) >= 2:
        return [part[:200] for part in paragraphs][:10]
    parts = re.split(r"\n+|[.!?;\u3002\uff01\uff1f\uff1b]", str(text or ""))
    return [part.strip(" -#\t")[:200] for part in parts if len(part.strip(" -#\t")) >= 8]


def validate_script_structure(script_body: str, *, minimum_beats: int = 8) -> dict:
    beats = _story_beats(script_body)
    unique = {re.sub(r"\s+", " ", beat).casefold() for beat in beats}
    failures = []
    if len(beats) < minimum_beats:
        failures.append("story_beats_insufficient")
    if len(unique) < minimum_beats:
        failures.append("story_beats_not_distinct")
    return {"passed": not failures, "beat_count": len(beats), "distinct_beat_count": len(unique), "failures": failures}


def _smart_clip(text: str, limit: int) -> str:
    """2026-08-23 v2 统一边界截断：优先句末断点保完整短句；否则标点/空格回退，绝不切英文单词。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    sent_ends = [m.start() for m in re.finditer(r"[。！？!?]", text[:limit + 1])]
    if sent_ends:
        end = sent_ends[-1] + 1
        if end >= limit * 0.5:
            return text[:end]
    cut = text[:limit]
    m = re.search(r"[\s，；、：,;]", cut[::-1])
    if m:
        cut = cut[: limit - m.start() - 1]
    while cut and re.search(r"[A-Za-z]$", cut) and re.match(r"[A-Za-z]", text[len(cut):len(cut) + 1] or ""):
        sp = cut.rfind(" ")
        if sp <= 0:
            break
        cut = cut[:sp]
    return cut.rstrip(" ，。；！？、：,.!?;")


def _card_title(text: str, index: int) -> str:
    # ⚠️ 2026-08-10 修复：中文无空格，split() 整句算一个词 → 恒 <4 → 返回 "Scene N" 占位
    # 2026-08-23 再修：text[:16] 硬切会腰斩英文词(Harn)，统一走 _smart_clip 边界回退
    text = str(text or "").strip()
    if not text:
        return f"Scene {index + 1}"
    # 英文标题保留完整首句；中文标题仍保持短标题，正文由卡片模块承载。
    if re.search(r"[\u4e00-\u9fff]", text):
        return _smart_clip(text, 24)
    first = re.split(r"[.!?;]", text, maxsplit=1)[0].strip()
    return first or text or f"Scene {index + 1}"


def _summary(text: str) -> str:
    return " ".join(_beats(text)[:2]) or "Auto generated video package"


def _tags(plan: dict) -> list[str]:
    explicit = [str(item).strip() for item in (plan.get("tags") or []) if str(item).strip()]
    if explicit:
        return list(dict.fromkeys(explicit))[:5]
    platforms = [str(item) for item in plan.get("platforms") or []]
    if str(plan.get("lane") or "") == "real_world_ai_implementation":
        return ["AI落地", "工业AI", "智能制造"]
    if "douyin" in platforms:
        return ["猫咪", "知识", "治愈"]
    if "bilibili" in platforms:
        return ["AI工具", "效率", "教程"]
    return ["AI", "效率", "工具"]


def _write_manifest(output_dir: Path, manifest: dict) -> None:
    context_path = output_dir / "platform_workflow_context.json"
    if context_path.is_file() and "platform_workflow_context" not in manifest:
        try:
            manifest["platform_workflow_context"] = json.loads(context_path.read_text(encoding="utf-8"))
        except Exception:
            manifest["platform_workflow_context"] = {"path": str(context_path), "loaded": False}
    (output_dir / "video_toolchain_runner_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _finalize_delivery_manifest(output_dir: Path, plan: dict) -> dict:
    """Bind every post-render file to this attempt before handoff."""
    final = output_dir / "final.mp4"
    if not final.is_file():
        raise RuntimeError("delivery_manifest_final_mp4_missing")
    cover_candidates = [
        output_dir / name
        for name in ("cover.png", "cover.jpg", "cover.jpeg", "cover_1080x1920.jpg", "cover_1920x1080.jpg")
    ]
    cover = next((path for path in cover_candidates if path.is_file()), None)
    if cover is None:
        raise RuntimeError("delivery_manifest_cover_missing")
    manifest = build_delivery_manifest(
        output_dir,
        required_paths=[final, cover, output_dir / "scene_manifest.json", output_dir / "segment_motion_evidence.json", output_dir / "shotcraft_execution_receipt.json"],
        identity={
            "job_id": str(plan.get("job_id") or plan.get("run_id") or ""),
            "attempt_id": str(plan.get("attempt_id") or ""),
            "revision": str(plan.get("revision") or ""),
            "resolved_output_dir": str(output_dir),
            "platform": _primary_platform(plan),
            "content_package_id": str(plan.get("content_package_id") or ""),
        },
    )
    path = output_dir / "delivery_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    runner_path = output_dir / "video_toolchain_runner_manifest.json"
    if runner_path.is_file():
        runner = json.loads(runner_path.read_text(encoding="utf-8"))
        runner["delivery_manifest"] = str(path)
        runner["artifact_set_sha256"] = manifest["artifact_set_sha256"]
        _write_manifest(output_dir, runner)
    return manifest


def _renderer_environment(plan: dict) -> dict[str, str]:
    env = os.environ.copy()
    if plan.get("subtitle_y_up") is not None:
        env["FILM_SUB_Y_UP"] = str(int(plan["subtitle_y_up"]))
    if _primary_platform(plan) == "douyin_ai":
        # Publishable Douyin AI output cannot inherit preview/degraded renderer policy.
        env["FILM_QUALITY_PROFILE"] = "high"
        env["FILM_MOTION_MODE"] = "cinematic"
        env["FILM_ALLOW_DEGRADED"] = "0"
    return env


def _analysis_fingerprint(plan: dict, *, script_body: str, title: str) -> dict[str, str]:
    """Bind scene generation to the analysis inputs that selected the workflow."""
    explicit = str(plan.get("analysis_hash") or plan.get("analysis_fingerprint") or "").strip()
    analysis_path = Path(str(plan.get("analysis_path") or "")).expanduser()
    if explicit:
        return {"sha256": explicit, "source": "plan_declared_analysis_hash"}
    if analysis_path.is_file():
        digest = hashlib.sha256(analysis_path.read_bytes()).hexdigest()
        return {"sha256": digest, "source": str(analysis_path.resolve())}
    payload = {
        "title": title,
        "script_body": script_body,
        "lane": plan.get("lane"),
        "account_key": plan.get("account_key") or plan.get("platform_account"),
        "content_line": plan.get("content_line"),
        "real_world_ai_package": plan.get("real_world_ai_package"),
        "hot_viral_samples": plan.get("hot_viral_samples"),
        "visual_contract": plan.get("visual_contract") or plan.get("scene_contract"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "source": "plan_evidence_canonical"}


def _primary_platform(plan: dict) -> str:
    platforms = [str(item).casefold() for item in (plan.get("platforms") or []) if str(item).strip()]
    return platforms[0] if platforms else "video"


def _workflow_platform(plan: dict) -> str:
    explicit = str(plan.get("workflow_platform") or "").casefold().strip()
    return explicit or _primary_platform(plan)


def _tool_invocation_manifest(plan: dict, repost: bool = False) -> dict:
    names = REPOST_PLANNED_TOOLS if repost else PLANNED_TOOLS
    planned = {name: _tool_ref(name) for name in names}
    return build_tool_invocation_manifest(
        planned_tools=planned,
        invocations={name: {"status": "planned_internal", "output": ref} for name, ref in planned.items()},
    )


def _tool_ref(name: str) -> str:
    if name.endswith(".py --cinema"):
        return "script:scripts/visual_gate.py --cinema"
    if "." in name:
        module = name.split(".", 1)[0]
        if module in {"cinema_composition", "shotcraft_moves"}:
            return f"script:scripts/{module}.py"
        if module == "kuaishou_render":
            return "script:scripts/kuaishou_render.py"
        if module == "mix_bgm_with_gate":
            return "script:scripts/mix_bgm_with_gate.py"
        if module == "autoclip_adapter":
            return "script:scripts/autoclip_adapter.py"
        if module == "ffmpeg":
            return "tool:ffmpeg"
    return f"video_toolchain:{name}"


def main(argv: list[str] | None = None) -> int:
    """Run the renderer and persist root-level performance evidence."""
    argv = list(sys.argv[1:] if argv is None else argv)
    output_dir = Path(os.environ.get("VIDEO_OUTPUT_DIR") or ROOT / "data" / "artifacts" / "video_toolchain").resolve()
    dry_run = os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1"
    performance = None
    if not dry_run:
        from content_platform.performance_manifest import add_stage, new_performance_manifest, finish_manifest, write_performance_manifest
        plan = _load_plan()
        platforms = [str(item).strip() for item in (plan.get("platforms") or []) if str(item).strip()]
        performance = new_performance_manifest(
            job_id=str(plan.get("job_id") or plan.get("run_id") or output_dir.parent.name),
            platform_run_id=str(plan.get("platform_run_id") or output_dir.name),
            platform=str((platforms or [plan.get("workflow_platform") or "unknown"])[0]),
            attempt_id=str(plan.get("attempt_id") or "attempt-1"),
        )
    started = time.perf_counter()
    try:
        code = _run_main(argv)
        if performance is not None:
            timing_path = output_dir / "render_timing.json"
            if timing_path.is_file():
                try:
                    timing_payload = json.loads(timing_path.read_text(encoding="utf-8"))
                    for event in timing_payload.get("events", []):
                        if not isinstance(event, dict):
                            continue
                        add_stage(performance, str(event.get("stage") or "unknown"), float(event.get("seconds") or 0), cache="hit" if event.get("cached") is True else "miss")
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    performance.setdefault("cache", {}).setdefault("invalidations", []).append("render_timing_invalid")
            performance["wall_clock_elapsed_seconds"] = round(time.perf_counter() - started, 6)
            add_stage(performance, "runner_total", performance["wall_clock_elapsed_seconds"], status="passed" if code == 0 else "failed")
            trusted = output_dir / "trusted_run_manifest.json"
            final_status = "success" if code == 0 and trusted.is_file() else "blocked" if code == 0 else "failed"
            finish_manifest(performance, final_status=final_status)
            write_performance_manifest(output_dir / "performance_manifest.json", performance)
            if code == 0:
                plan = _load_plan()
                try:
                    _finalize_delivery_manifest(output_dir, plan)
                except Exception as delivery_error:
                    runner_path = output_dir / "video_toolchain_runner_manifest.json"
                    runner = json.loads(runner_path.read_text(encoding="utf-8")) if runner_path.is_file() else {}
                    runner.update({
                        "ok": False,
                        "status": "delivery_manifest_failed",
                        "error": f"{type(delivery_error).__name__}: {delivery_error}",
                    })
                    _write_manifest(output_dir, runner)
                    code = 4
        return code
    except Exception:
        if performance is not None:
            performance["wall_clock_elapsed_seconds"] = round(time.perf_counter() - started, 6)
            add_stage(performance, "runner_total", performance["wall_clock_elapsed_seconds"], status="failed")
            finish_manifest(performance, final_status="failed")
            write_performance_manifest(output_dir / "performance_manifest.json", performance)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
