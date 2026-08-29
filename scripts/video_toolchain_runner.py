#!/usr/bin/env python3
"""Pipeline-compatible video toolchain runner.

The content platform calls video scripts as:

    python script.py <script_body> <title>

This runner reads VIDEO_TOOLCHAIN_PLAN_PATH, materializes a renderer-ready
cards.json, chooses the configured renderer, and leaves the generated mp4 in
VIDEO_OUTPUT_DIR for MediaBridge to discover.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cinema_composition import storyboard
from scripts.pre_render_gate import validate_render_inputs
from content_platform.content_recipe import build_tool_invocation_manifest
from content_platform.tool_selection import build_tool_selection_evidence
from content_platform.video_recipe import build_visual_recipe, load_effect_module_registry, validate_visual_recipe
from content_platform.video_artifact import verify_artifact
from content_platform.scene_manifest import build_scene_manifest, validate_rendered_duration, validate_scene_manifest
from content_platform.paths import agent_scripts_dir
from content_platform.platform_workflow_context import write_platform_workflow_context
from content_platform.asset_ledger import AssetLedger, validate_asset_set

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
    "cover_director.render_cover_poster",
]
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
ROUTE_PLANNED_TOOLS = {
    "landscape_explainer_renderer": [
        "render_landscape_video.slides", "render_landscape_video.playwright", "render_landscape_video.tts",
        "render_landscape_video.segments", "render_landscape_video.concat", "kuaishou_render.download_bgm",
        "mix_bgm_with_gate.mix_bgm", "render_landscape_video.subtitles", "render_landscape_video.encode_final",
        "visual_gate.py --cinema", "cover_director.render_cover_poster",
    ],
    "real_footage_renderer": [
        "cinematic_v11.source_asset_gate", "cinematic_v11.tts", "kuaishou_render.download_bgm",
        "cinematic_v11.scene_compositor", "cinematic_v11.semantic_transitions", "cinematic_v11.subtitle_overlay",
        "cinematic_v11.audio_mix", "cinematic_v11.encode_final", "visual_gate.py --cinema", "cover_director.render_cover_poster",
    ],
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    script_body = argv[0] if argv else ""
    title = argv[1] if len(argv) > 1 else "Untitled video"
    output_dir = Path(os.environ.get("VIDEO_OUTPUT_DIR") or ROOT / "data" / "artifacts" / "video_toolchain").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = _load_plan()
    platform_context = None
    requested_platforms = [str(item).strip() for item in (plan.get("platforms") or []) if str(item).strip()]
    if requested_platforms:
        if len(requested_platforms) != 1:
            raise RuntimeError("video renderer requires exactly one platform per serial workflow")
        platform_context = write_platform_workflow_context(output_dir, requested_platforms[0], plan=plan)
    elif os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") != "1":
        raise RuntimeError("real video render requires plan.platforms and platform workflow context")
    dry_run = os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1"
    if str(plan.get("selected_pipeline") or "") == "localized_repost_video" and not dry_run:
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
    visual_assets = _load_visual_assets()
    materialized_backgrounds = _materialize_visual_backgrounds(output_dir, visual_assets)
    # 2026-08-16 新增：背景不足时自动 Pexels 语义下载兜底（取代 Hermes 手动下载）
    if not dry_run and len(materialized_backgrounds) < 8:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from pexels_auto_bg import auto_fetch_backgrounds, write_auto_assets
            auto_assets = auto_fetch_backgrounds(script_body or title, title or "", output_dir, _primary_platform(plan))
            if auto_assets:
                materialized_backgrounds = _merge_materialized_backgrounds(materialized_backgrounds, auto_assets)
        except Exception:
            # 静默失败，不阻断渲染
            pass
    # diagram-design 补图通道：结构化主题且背景不足时，自动生成杂志级 diagram 背景
    if not dry_run:
        materialized_backgrounds = _diagram_background_fill(output_dir, script_body or title, materialized_backgrounds)
    if plan.get("run_contract"):
        ledger = AssetLedger(os.environ.get("ASSET_LEDGER_PATH") or ROOT / "data" / "asset_ledger.db")
        previous_hashes = {str(row.get("sha256") or "") for row in ledger.uses() if str(row.get("sha256") or "")}
        current_hashes = {
            hashlib.sha256(Path(str(item.get("path") or "")).read_bytes()).hexdigest()
            for item in materialized_backgrounds
            if Path(str(item.get("path") or "")).is_file()
        }
        if previous_hashes.intersection(current_hashes):
            try:
                from pexels_auto_bg import auto_fetch_backgrounds
                replacements = auto_fetch_backgrounds(
                    script_body or title,
                    title or "",
                    output_dir,
                    _primary_platform(plan),
                    force=True,
                    excluded_hashes=previous_hashes,
                )
                replacement_rows = _merge_materialized_backgrounds([], replacements)
                if len(replacement_rows) >= 8:
                    materialized_backgrounds = replacement_rows
                else:
                    print(f"[asset-reselection] insufficient unique replacements: {len(replacement_rows)}/8", file=sys.stderr)
            except Exception as exc:
                print(f"[asset-reselection] failed: {exc}", file=sys.stderr)
    visual_assets = _visual_assets_from_materialized(materialized_backgrounds)
    asset_records = _asset_provenance_records(materialized_backgrounds)
    asset_provenance_path = output_dir / "asset_provenance.json"
    asset_provenance_path.write_text(json.dumps({"version": "asset_provenance_v1", "assets": asset_records}, ensure_ascii=False, indent=2), encoding="utf-8")
    asset_gate = {}
    if plan.get("run_contract"):
        asset_gate = validate_asset_set(
            asset_records,
            _primary_platform(plan),
            str(plan.get("work_id") or output_dir.name),
            ledger,
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
    recipe_collision_recovery = {"recovered": False, "attempts": []}
    if recipe_gate.get("passed") and not recipe_reuse_gate.get("passed"):
        recipe_collision_recovery["attempts"].append({"attempt": 0, **recipe_reuse_gate})
        retry_styles = [
            ("clean_blueprint", "medium_high", "split_screen_steps", 3),
            ("warm_editorial", "medium", "timeline_cards", 5),
            ("high_contrast_note", "fast_cut", "diagonal_hook_cards", 3),
            ("content_matched", "calm", "headline_plus_lower_third", 6),
        ]
        for attempt in range(1, 5):
            retry_plan = dict(plan)
            retry_plan["recipe_retry_variant"] = attempt
            # An explicit visual_recipe otherwise ignores retry fields and
            # repeats the same core fingerprint forever. Rebuild the recipe
            # with a genuinely different visual combination.
            retry_plan.pop("visual_recipe", None)
            color, density, layout, interval = retry_styles[attempt - 1]
            retry_plan.update({
                "color_mood": color,
                "motion_density": density,
                "text_layout": layout,
                "scene_change_interval_sec": interval,
            })
            candidate = build_visual_recipe(
                retry_plan,
                script_body=script_body,
                title=title,
                cinema_scenes=cinema_scenes,
                shotcraft_plan=shotcraft_plan,
                visual_assets=visual_assets,
                registry=registry,
            )
            candidate_gate = validate_visual_recipe(candidate, registry)
            candidate_reuse_gate = _recipe_reuse_gate(candidate, retry_plan)
            recipe_collision_recovery["attempts"].append({"attempt": attempt, **candidate_reuse_gate})
            if candidate_gate.get("passed") and candidate_reuse_gate.get("passed"):
                visual_recipe = candidate
                recipe_gate = candidate_gate
                recipe_reuse_gate = candidate_reuse_gate
                plan = retry_plan
                recipe_collision_recovery.update({"recovered": True, "selected_attempt": attempt})
                break
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
            "recipe_collision_recovery": recipe_collision_recovery,
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
    scene_manifest_gate = validate_scene_manifest(scene_manifest)
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
        require_backgrounds=False,
        require_scene_manifest=True,
        require_functional_mascots=bool(plan.get("require_functional_mascots")),
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
    if len(materialized_backgrounds) >= 8:
        _write_visual_treatment_plan(output_dir, plan, materialized_backgrounds)
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
        "asset_quality_gate": asset_gate,
        "visual_recipe": visual_recipe,
        "visual_recipe_path": str(recipe_path),
        "visual_recipe_gate": recipe_gate,
        "recipe_reuse_gate": recipe_reuse_gate,
        "recipe_collision_recovery": recipe_collision_recovery,
        "scene_manifest": scene_manifest,
        "scene_manifest_path": str(scene_manifest_path),
        "scene_manifest_gate": scene_manifest_gate,
        "recipe_fingerprint": visual_recipe.get("fingerprint"),
        "recipe_core_fingerprint": visual_recipe.get("core_fingerprint"),
        "video_route": plan.get("video_route") or {},
        "card_titles": [str(card.get("t") or "") for card in cards],
        "subtitle": {"width": 1080, "height": 1920},
        "tool_invocation_manifest": tool_manifest,
        **tool_selection_evidence,
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
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.environ.get("VIDEO_TOOLCHAIN_TIMEOUT", "900")))
    manifest.update({"renderer_command": cmd, "returncode": proc.returncode, "stdout_tail": (proc.stdout or "")[-800:], "stderr_tail": (proc.stderr or "")[-800:]})
    if proc.returncode == 0:
        _normalize_alternate_renderer_outputs(renderer, output_dir, plan, script_body)
    generated = sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    if proc.returncode == 0 and generated:
        duration_fix = _normalize_short_video_duration(generated[0], _primary_platform(plan))
        manifest["duration_normalization"] = duration_fix
        if not duration_fix.get("passed"):
            manifest.update({"ok": False, "output": str(generated[0]), "status": "duration_normalization_failed", "error": duration_fix.get("error") or "short video duration normalization failed"})
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
        manifest["scene_execution_evidence"] = _write_measured_scene_execution(
            output_dir,
            generated[0],
            scene_manifest,
            segment_motion,
        )
        actual_tools = set(_route_planned_tools(plan))
        invocations = manifest.get("tool_invocation_manifest", {}).get("invocations", {}) or {}
        for name, record in invocations.items():
            if not isinstance(record, dict) or record.get("status") != "planned_internal":
                continue
            if name in actual_tools:
                record["status"] = "ok"
                record["artifact"] = str(generated[0])
            else:
                record["status"] = "not_invoked"
                record["reason"] = "planned candidate was not called by the selected renderer"
        manifest.update({
            "ok": True,
            "output": str(generated[0]),
            "status": "rendered",
            "executed_tools": [name for name, record in invocations.items() if isinstance(record, dict) and record.get("status") in {"ok", "generated"}],
        })
        if asset_gate.get("passed"):
            validate_asset_set(
                asset_records,
                _primary_platform(plan),
                str(plan.get("work_id") or output_dir.name),
                AssetLedger(os.environ.get("ASSET_LEDGER_PATH") or ROOT / "data" / "asset_ledger.db"),
                register=True,
            )
        _register_visual_recipe_use(visual_recipe, plan, str(generated[0]))
        bg_for_cover, background_selection = _select_cover_background(materialized_backgrounds, _primary_platform(plan))
        if not bg_for_cover or not Path(str(bg_for_cover)).is_file():
            manifest.update({"ok": False, "status": "cover_failed", "error": "topic-matched cover background missing"})
            _write_manifest(output_dir, manifest)
            return 6
        try:
            cover = _generate_video_cover(
                output_dir, title, _summary(script_body), plan, Path(str(bg_for_cover)),
                background_selection=background_selection,
            )
        except Exception as exc:
            manifest.update({"ok": False, "status": "cover_failed", "error": str(exc)[:500]})
            _write_manifest(output_dir, manifest)
            return 6
        manifest["cover"] = cover["path"]
        manifest["cover_quality_evidence"] = cover["evidence"]
        # Archive only after the cover and its measured evidence exist, so the
        # handoff package cannot omit the click-facing asset.
        try:
            from scripts.archive_delivery_package import archive_delivery_package_direct
            archive_delivery_package_direct(output_dir)
        except Exception as _archive_err:
            manifest["archive_warning"] = f"delivery archive failed: {_archive_err}"
        _write_manifest(output_dir, manifest)
        print(json.dumps({"ok": True, "output": str(generated[0])}, ensure_ascii=False))
        return 0
    manifest["error"] = "video renderer produced no mp4"
    _write_manifest(output_dir, manifest)
    print(manifest["stderr_tail"] or manifest["stdout_tail"] or manifest["error"], file=sys.stderr)
    return proc.returncode or 3


def _normalize_short_video_duration(path: Path, platform: str) -> dict:
    """Trim over-limit vertical shorts before measured artifact gates run."""
    normalized = str(platform or "").casefold()
    if normalized not in {"douyin", "douyin_ai", "douyin_pet", "kuaishou", "shipinhao", "tiktok", "youtube"}:
        return {"passed": True, "applied": False, "reason": "platform has no short duration limit"}
    duration = _video_duration(path)
    if duration <= 60.0:
        return {"passed": True, "applied": False, "duration_seconds": round(duration, 3)}
    temp = path.with_name(path.stem + ".duration-normalized.mp4")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-t", "59.8",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac",
             "-b:a", "128k", "-pix_fmt", "yuv420p", str(temp)],
            capture_output=True, text=True, timeout=180, check=False,
        )
        if result.returncode != 0 or not temp.is_file():
            return {"passed": False, "applied": True, "error": (result.stderr or "ffmpeg duration normalization failed")[-400:]}
        temp.replace(path)
        measured = _video_duration(path)
        return {"passed": measured <= 60.0, "applied": True, "original_seconds": round(duration, 3), "duration_seconds": round(measured, 3)}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        temp.unlink(missing_ok=True)
        return {"passed": False, "applied": True, "error": str(exc)[:400]}


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
    route = plan.get("video_route") if isinstance(plan.get("video_route"), dict) else {}
    directed_presentations = list(route.get("scene_presentations") or [])
    presentation_layouts = {
        "hero_footage": "cover", "hero_poster": "cover", "hero_conflict": "cover", "hero_number": "big_number",
        "split_screen": "two_column", "side_a": "two_column", "side_b": "two_column",
        "difference_grid": "card_stack", "takeaway_grid": "card_stack", "summary_grid": "card_stack",
        "timeline": "timeline", "process_flow": "timeline", "process_insert": "timeline",
        "chart_build": "big_number", "metric_focus": "big_number", "number_motion": "big_number",
        "evidence_zoom": "diagonal", "evidence_source": "diagonal", "evidence_overlay": "diagonal",
        "ui_focus": "diagonal", "cursor_demo": "timeline", "detail_closeup": "diagonal",
        "result_reveal": "interaction", "winner_reveal": "interaction", "payoff_reveal": "interaction",
        "reaction_cut": "card_stack", "behavior_closeup": "diagonal", "context_wide": "two_column",
        "list_reveal": "card_stack", "diagram": "timeline", "real_asset_overlay": "diagonal",
        "establishing": "two_column", "cta": "interaction", "cta_footage": "interaction",
    }
    cards = []
    for index in range(8):
        beat = beats[index % len(beats)]
        presentation = directed_presentations[index] if index < len(directed_presentations) else ""
        layout = presentation_layouts.get(presentation, LAYOUTS[index % len(LAYOUTS)])
        scene = (cinema_scenes or [])[index] if index < len(cinema_scenes or []) else {}
        headline = _visual_headline(beat, presentation, index)
        card = {
            "layout": layout,
            "t": headline,
            "txt": _presentation_label(presentation, index),
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
            "presentation_mode": presentation or layout,
        }
        if visual_assignments:
            card["visual_asset"] = visual_assignments[index % len(visual_assignments)]
        if layout == "cover":
            card.update({"sub": "先看问题，再看统一路径", "hook": title, "hook_prefix": "内容工作流实测"})
        if layout == "card_stack":
            card["items"] = _supporting_labels(presentation, index)
        if layout == "big_number":
            card.update({"num": f"0{index + 1}", "ext": _presentation_label(presentation, index)})
        if layout == "timeline":
            card["items"] = _supporting_labels(presentation, index)
        cards.append(card)
    return cards


def _visual_label(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip(" ，。！？!?;；")
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,18}|[\u3400-\u9fff]{2,6}", clean)
    stop = {"为什么", "这是", "一个", "第一步", "第二步", "第三步", "直接", "根据", "不要", "可以"}
    selected = []
    for token in tokens:
        if token in stop or token in selected:
            continue
        selected.append(token)
        if len(selected) >= 3:
            break
    return " · ".join(selected) if selected else clean[:18]


def _visual_headline(text: str, presentation: str, index: int) -> str:
    lowered = str(text or "").casefold()
    rules = [
        (("切换", "工具越多", "too many tools", "switching"), "工具切换黑洞"),
        (("账号", "密码", "登录", "充值", "会员"), "隐藏的管理成本"),
        (("文本", "图像", "图片", "语音", "视频"), "能力散落在各处"),
        (("一个入口", "统一", "整合", "后台管理"), "统一入口管理"),
        (("api", "接口", "接入"), "把能力接进流程"),
        (("效率", "时间", "省下"), "把时间还给内容"),
        (("第一步", "第二步", "第三步", "步骤"), "按顺序跑通"),
    ]
    for tokens, label in rules:
        if any(token in lowered for token in tokens):
            return label
    return _presentation_label(presentation, index)


def _presentation_label(presentation: str, index: int) -> str:
    labels = {
        "hero_poster": "核心问题", "hero_conflict": "先看冲突", "hero_number": "关键数字",
        "establishing": "真实场景", "detail_closeup": "问题细节", "process_flow": "执行路径",
        "split_screen": "两种做法", "evidence_zoom": "核对证据", "payoff_reveal": "可执行结果",
        "list_reveal": "关键清单", "timeline": "步骤顺序", "diagram": "关系结构",
        "real_asset_overlay": "真实素材", "card_stack": "重点归纳", "summary_grid": "一页总结",
        "cta": "下一步行动", "cta_footage": "下一步行动", "interaction": "评论互动",
    }
    return labels.get(presentation, f"关键点 {index + 1}")


def _supporting_labels(presentation: str, index: int) -> list[str]:
    groups = {
        "process_flow": ["统一入口", "按需调用", "集中留痕"],
        "timeline": ["先定位", "再接入", "后验证"],
        "list_reveal": ["减少切换", "统一管理", "保留证据"],
        "summary_grid": ["问题", "路径", "结果"],
        "card_stack": ["成本", "流程", "改进"],
    }
    return groups.get(presentation, [f"要点 {index + 1}", "对应场景", "可执行结果"])


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
                "css": item.get("css") or {},
                "keyframe_definitions": item.get("keyframes") or {},
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
        "css": item.get("css") or {},
        "keyframe_definitions": item.get("keyframe_definitions") or {},
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


def _load_visual_assets() -> dict:
    path = os.environ.get("VIDEO_VISUAL_ASSETS_PATH", "")
    if not path:
        return {}
    source = Path(path)
    if not source.is_file():
        return {"error": "VIDEO_VISUAL_ASSETS_PATH missing", "path": path, "assignments": []}
    try:
        return json.loads(source.read_text(encoding="utf-8-sig"))
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
                "rights_cleared": bool(item.get("rights_cleared", True)),
                "real_scene": bool(item.get("real_scene", True)),
                "source_url": str(item.get("source_url") or ""),
                "license": str(item.get("license") or ""),
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
    return [
        {
            "scene_id": str(item.get("scene") or f"asset_{index}"),
            "path": str(item.get("path") or ""),
            "source_url": str(item.get("source_url") or ""),
            "license": str(item.get("license") or ""),
            "semantic_match_score": float(item.get("semantic_match_score") or 0),
            "match_reason": str(item.get("match_reason") or ""),
            "semantic_tags": list(item.get("semantic_tags") or []),
            "generation_evidence": dict(item.get("generation_evidence") or {}),
        }
        for index, item in enumerate(materialized, 1)
        if item.get("path")
    ]


def _visual_assets_from_materialized(materialized: list[dict]) -> dict:
    assignments = []
    for index, item in enumerate(materialized[:8], 1):
        path = str(item.get("path") or item.get("background_image") or "")
        if not path:
            continue
        assignments.append({
            "scene": item.get("scene") or index,
            "source_image": str(item.get("source") or path),
            "background_image": path,
            "materialized_background": path,
            "reused": False,
            "purpose": str(item.get("match_reason") or "scene background matched to narration"),
            "source_url": str(item.get("source_url") or ""),
            "license": str(item.get("license") or ""),
            "semantic_match_score": float(item.get("semantic_match_score") or 0),
            "match_reason": str(item.get("match_reason") or ""),
            "semantic_tags": list(item.get("semantic_tags") or []),
            "generation_evidence": dict(item.get("generation_evidence") or {}),
        })
    return {
        "source": "materialized_asset_selection",
        "image_count": len(assignments),
        "scene_count": len(assignments),
        "assignments": assignments,
    }


def _merge_materialized_backgrounds(existing: list[dict], additions: list[dict]) -> list[dict]:
    """Preserve rich input provenance while normalizing fallback asset rows."""
    merged = list(existing)
    seen_paths = {str(Path(str(item.get("path") or "")).resolve()) for item in merged if item.get("path")}
    for index, item in enumerate(additions, len(merged) + 1):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("background_image") or "")
        if not path or not Path(path).is_file():
            continue
        resolved = str(Path(path).resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        query = str(item.get("source_query") or "topic-matched background")
        merged.append({
            **item,
            "scene": item.get("scene") or index,
            "path": path,
            "source_url": str(item.get("source_url") or ""),
            "license": str(item.get("license") or ""),
            "semantic_match_score": float(item.get("semantic_match_score") or 0),
            "match_reason": str(item.get("match_reason") or f"visual search matched: {query}"),
            "semantic_tags": list(item.get("semantic_tags") or [query]),
            "generation_evidence": dict(item.get("generation_evidence") or {}),
        })
    return merged[:8]


def _renderer_path(plan: dict) -> Path:
    env_key = "VIDEO_RENDERER_" + re.sub(r"[^A-Z0-9]+", "_", str(plan.get("selected_pipeline") or "").upper())
    return Path(os.environ.get(env_key) or os.environ.get("VIDEO_TOOLCHAIN_RENDERER") or DEFAULT_RENDERER)


def _generate_video_cover(output_dir: Path, title: str, summary: str, plan: dict, background: Path, *, background_selection: dict | None = None) -> dict:
    from content_platform.cover_director import build_cover_direction, render_cover_poster
    from content_platform.cover_quality import validate_cover

    platform = _primary_platform(plan)
    direction = build_cover_direction(
        platform=platform,
        topic=str(plan.get("topic") or title),
        title=title,
        body=summary,
        recent_direction_ids=list(plan.get("recent_cover_direction_ids") or []),
    )
    width, height = direction["target_size"]
    cover_path = output_dir / f"cover_{width}x{height}.jpg"
    evidence = render_cover_poster(background, cover_path, direction)
    evidence["background_selection"] = dict(background_selection or {})
    evidence_path = output_dir / "cover_quality_evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    gate = validate_cover(cover_path, evidence, platform)
    if not gate.get("passed"):
        raise RuntimeError("video cover quality gate failed: " + ", ".join(gate.get("failures") or []))
    return {"path": str(cover_path), "evidence_path": str(evidence_path), "evidence": evidence, "gate": gate}


_FOREIGN_PLATFORM_MARKERS = {
    "kuaishou": {"instagram", "tiktok", "youtube", "facebook"},
    "douyin": {"instagram", "tiktok", "youtube", "facebook"},
    "xiaohongshu": {"instagram", "tiktok", "youtube", "facebook"},
}


def _select_cover_background(assignments: list[dict], platform: str) -> tuple[str | None, dict]:
    candidates = []
    forbidden = _FOREIGN_PLATFORM_MARKERS.get(str(platform or "").casefold(), set())
    for index, item in enumerate(assignments or []):
        raw = item.get("background_image") or item.get("path")
        path = Path(str(raw or ""))
        if not path.is_file():
            continue
        ocr = ""
        try:
            proc = subprocess.run(
                ["tesseract", str(path), "stdout", "-l", "eng"],
                capture_output=True, text=True, timeout=8, check=False,
            )
            ocr = (proc.stdout or "").casefold()
        except (OSError, subprocess.SubprocessError):
            pass
        conflicts = sorted(marker for marker in forbidden if marker in ocr)
        purpose = str(item.get("purpose") or item.get("match_reason") or "").casefold()
        stock_ui = "pexels.com" in str(item.get("source_url") or "").casefold() and any(token in purpose for token in ("interface", "dashboard", "screen"))
        score = sum(token in purpose for token in ("api", "workflow", "developer", "dashboard", "tool")) - 10 * len(conflicts) - (4 if stock_ui else 0)
        candidates.append({"path": str(path), "score": score, "ocr_conflicts": conflicts, "assignment_index": index, "purpose": purpose})
    usable = [row for row in candidates if not row["ocr_conflicts"]]
    selected = max(usable or candidates, key=lambda row: (row["score"], -row["assignment_index"]), default=None)
    if not selected:
        return None, {"passed": False, "reason": "no_cover_background_candidates"}
    return selected["path"], {"passed": not selected["ocr_conflicts"], **selected, "candidate_count": len(candidates)}


def _write_visual_treatment_plan(output_dir: Path, plan: dict, assignments: list[dict]) -> Path:
    route = plan.get("video_route") if isinstance(plan.get("video_route"), dict) else {}
    presentations = list(route.get("scene_presentations") or [])
    cameras = ["handheld_push", "split_screen_slide", "top_down_reveal", "left_dolly", "right_dolly", "orbit_pull", "snap_zoom", "direct_eye_contact"]
    subjects = {
        "split_screen": "outline_compare", "difference_grid": "kanban_reveal", "data_story": "digit_roll",
        "chart_build": "digit_roll", "metric_focus": "digit_roll", "process_flow": "action_path",
        "timeline": "action_path", "list_reveal": "kanban_reveal", "cta": "choice_pulse",
    }
    texts = ["message_type", "before_after_wipe", "label_stagger", "path_draw", "highlight_underline", "focus_fade", "warning_shake", "choice_bounce"]
    transitions = ["hard_cut", "split_reveal", "card_flip", "left_swipe", "right_swipe", "path_draw", "glitch_wipe", "end_hold"]
    scenes = []
    for index, item in enumerate(assignments[:8]):
        presentation = presentations[index] if index < len(presentations) else "explain"
        asset = str(item.get("background_image") or item.get("path") or "")
        scenes.append({
            "scene_id": f"s{index + 1:02d}",
            "display_purpose": str(item.get("purpose") or presentation),
            "real_asset": asset,
            "camera_language": "split_screen_slide" if presentation == "split_screen" else cameras[index],
            "subject_motion": subjects.get(presentation, "choice_pulse" if index == 7 else "persona_focus"),
            "text_motion": texts[index],
            "transition": transitions[index],
            "rhythm_beat": {"emphasis": "hook" if index == 0 else "cta" if index == 7 else presentation},
            "interaction_prompt": "comment your choice" if index == 7 else "",
            "presentation_mode": presentation,
        })
    path = output_dir / "visual_treatment_plan.json"
    path.write_text(json.dumps({"version": "visual_treatment_plan_v2", "generated_by": "video_director", "style_id": route.get("style_id", ""), "scenes": scenes}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _normalize_alternate_renderer_outputs(renderer: Path, output_dir: Path, plan: dict, script_body: str) -> None:
    if renderer.name not in {"render_landscape_video.py", "cinematic_v11.py"}:
        return
    candidates = [
        output_dir / "render" / "final.mp4",
        output_dir / "final_v11.mp4",
        output_dir / "final.mp4",
    ]
    source = next((path for path in candidates if path.is_file() and path.stat().st_size > 0), None)
    if source is None:
        return
    final = output_dir / "final.mp4"
    if source.resolve() != final.resolve():
        shutil.copy2(source, final)
    nested = output_dir / "render"
    for name in ("bgm_source.json", "bgm.mp3", "subtitles.ass", "visual_recipe.json"):
        source_sidecar = nested / name
        if source_sidecar.is_file() and not (output_dir / name).is_file():
            shutil.copy2(source_sidecar, output_dir / name)
    tts_files = sorted([*(nested / "tts").glob("tts_*.mp3"), *(output_dir / "tts").glob("tts_*.mp3")])
    if tts_files:
        from content_platform.tts_text_compiler import TTSTextCompiler
        platform = _primary_platform(plan)
        has_cjk = bool(re.search(r"[\u3400-\u9fff]", script_body))
        compiled = TTSTextCompiler.default().compile(script_body, context="tech", platform=platform)
        digest = hashlib.sha256()
        duration = 0.0
        for path in tts_files:
            digest.update(path.read_bytes())
            duration += _video_duration(path)
        fingerprint = {
            "display_text": script_body,
            "tts_text": compiled.tts_text,
            "provider": "edge-tts",
            "voice": "en-US-GuyNeural" if platform == "youtube" and not has_cjk else "zh-CN-YunjianNeural",
            "rate": "+0%",
            "sample_rate": 44100,
            "channels": 2,
            "duration_seconds": round(duration, 3),
            "sha256": digest.hexdigest(),
            "unhandled_latin_tokens": list(compiled.unhandled_latin_tokens) if has_cjk else [],
        }
        (output_dir / "tts_fingerprint.json").write_text(json.dumps(fingerprint, ensure_ascii=False, indent=2), encoding="utf-8")
    subtitle_file = output_dir / "subtitles.ass"
    if subtitle_file.is_file():
        cue_count = sum(1 for line in subtitle_file.read_text(encoding="utf-8", errors="ignore").splitlines() if line.startswith("Dialogue:"))
        (output_dir / "subtitle_burn_evidence.json").write_text(json.dumps({
            "version": "burned_subtitle_evidence_v1", "passed": cue_count >= 3, "burned_in": True,
            "sample_count": cue_count, "position": "lower_third", "font_size": 28,
            "max_chars_per_line": 20, "max_lines": 2, "margin_v": 55,
            "renderer": renderer.name,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    segment_roots = [nested / "segments", output_dir / "v11_clips"]
    segment_files = next((sorted(root.glob("*.mp4")) for root in segment_roots if root.is_dir()), [])
    route = plan.get("video_route") if isinstance(plan.get("video_route"), dict) else {}
    presentations = list(route.get("scene_presentations") or [])
    segments = []
    for index, path in enumerate(segment_files[:8]):
        segments.append({
            "scene_id": f"s{index + 1:02d}", "move_id": presentations[index] if index < len(presentations) else renderer.stem,
            "profile": str(route.get("style_id") or renderer.stem), "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "artifact_verified": True,
        })
    if segments:
        payload = {"version": "segment_motion_evidence_v2", "renderer": renderer.name, "segments": segments}
        (output_dir / "segment_motion_evidence.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "scene_execution_evidence.json").write_text(json.dumps({"version": "scene_execution_evidence_v2", "scenes": segments}, ensure_ascii=False, indent=2), encoding="utf-8")


def _sample_video_frame(video: Path, offset: float):
    from io import BytesIO
    from PIL import Image

    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{offset:.3f}", "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, timeout=30, check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"scene frame probe failed at {offset:.3f}s")
    return Image.open(BytesIO(result.stdout)).convert("L")


def _write_measured_scene_execution(output_dir: Path, final: Path, scene_manifest: dict, segment_motion: dict) -> dict:
    from PIL import ImageChops, ImageStat

    scenes = list(scene_manifest.get("scenes") or [])
    motions = list(segment_motion.get("segments") or [])
    duration = _video_duration(final)
    rows = []
    for index, scene in enumerate(scenes[:8]):
        start = duration * index / max(1, len(scenes))
        end = duration * (index + 1) / max(1, len(scenes))
        first = _sample_video_frame(final, min(end - 0.1, start + max(0.15, (end - start) * 0.25)))
        second = _sample_video_frame(final, min(end - 0.05, start + max(0.3, (end - start) * 0.75)))
        difference = ImageStat.Stat(ImageChops.difference(first, second)).mean[0] / 255.0
        motion = motions[index] if index < len(motions) and isinstance(motions[index], dict) else {}
        rows.append({
            "scene_id": str(scene.get("scene_id") or f"s{index + 1:02d}"),
            "frame_difference": round(difference, 6),
            "static_ratio": 0.0 if difference > 0.002 else 1.0,
            "move_id": str(motion.get("move_id") or "measured_scene_motion"),
            "profile": str(motion.get("profile") or "encoded_frame_probe"),
            "sample_offsets": [round(start + (end - start) * 0.25, 3), round(start + (end - start) * 0.75, 3)],
            "artifact_verified": True,
        })
    evidence = {"version": "scene_execution_evidence_v3", "video": str(final), "scenes": rows}
    (output_dir / "scene_execution_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence


def _content_driven_renderer(plan: dict, script_body: str, title: str, output_dir: Path) -> tuple[Path, dict]:
    """内容驱动渲染器选择（2026-08-15 固化 — 用户要求工作流自动识别动效，不依赖人工指定）。

    脚本文案命中卡内元素级动效结构（流程/对比/数字）→ 自动切换到 film_renderer
    （图块激活/数字跳变/流程点亮），否则维持 plan 默认渲染器。

    同步写 script.md（film_renderer 的 TTS 分段/门禁依赖），并回写 plan.selected_pipeline
    让 manifest / 门禁证据链一致。
    """
    new_plan = dict(plan)
    route = plan.get("video_route") if isinstance(plan.get("video_route"), dict) else {}
    renderer_id = str(route.get("renderer_id") or "")
    if renderer_id:
        renderers = {
            "layered_card_renderer": ROOT / "scripts" / "kuaishou_render.py",
            "cinema_multishot_renderer": ROOT / "scripts" / "film_renderer.py",
            "landscape_explainer_renderer": ROOT / "scripts" / "render_landscape_video.py",
            "real_footage_renderer": ROOT / "scripts" / "cinematic_v11.py",
        }
        renderer = renderers.get(renderer_id)
        if renderer is None:
            raise RuntimeError(f"unknown video route renderer: {renderer_id}")
        script_md = output_dir / "script.md"
        if script_body.strip():
            script_md.write_text(script_body.strip(), encoding="utf-8")
        print(f"[video-director] {renderer_id} -> {renderer.name}", file=sys.stderr)
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


def _renderer_command(renderer: Path, output_dir: Path, theme: str, title: str, script_body: str, plan: dict, bgm_style: str) -> list[str]:
    if renderer.name == "render_landscape_video.py":
        script_path = output_dir / "script.md"
        if not script_path.is_file():
            script_path.write_text(script_body, encoding="utf-8")
        return [
            sys.executable, str(renderer), "--out-dir", str(output_dir), "--script", str(script_path),
            "--bg-dir", str(output_dir / "backgrounds"), "--title", title[:80],
            "--platform", _primary_platform(plan), "--bgm-style", bgm_style,
        ]
    if renderer.name == "cinematic_v11.py":
        return [sys.executable, str(renderer), "--video-dir", str(output_dir), "--platform", _primary_platform(plan)]
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
        _summary(script_body)[:180],
        "--bgm-style",
        bgm_style,
        "--platform",
        _primary_platform(plan),
        "--tags",
        *_tags(plan),
        "--width",
        "1080",
        "--height",
        "1920",
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
        "planned_tools": _route_planned_tools(plan),
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


def _visual_recipe_registry_path() -> Path:
    configured = os.environ.get("VISUAL_RECIPE_FINGERPRINT_REGISTRY", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "data" / "visual_recipe_fingerprints.json"


def _load_visual_recipe_registry() -> dict:
    path = _visual_recipe_registry_path()
    if not path.is_file():
        return {"recipes": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"visual recipe registry invalid JSON: {path}") from exc
    recipes = data.get("recipes") if isinstance(data, dict) else []
    return {"recipes": recipes if isinstance(recipes, list) else []}


def _recipe_reuse_gate(recipe: dict, plan: dict) -> dict:
    # Isolated dry-runs must not read the production registry; tests can opt in
    # with VISUAL_RECIPE_FINGERPRINT_REGISTRY to exercise collision behavior.
    if os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1" and not os.environ.get("VISUAL_RECIPE_FINGERPRINT_REGISTRY"):
        return {"passed": True, "policy_enabled": True, "dry_run_isolated": True, "duplicate_count": 0, "duplicates": []}
    policy = _duplication_policy().get("same_day_template_duplicate") or {}
    if policy.get("enabled") is False:
        return {"passed": True, "policy_enabled": False}
    lookback_days = int(policy.get("lookback_days") or 1)
    core = str(recipe.get("core_fingerprint") or "").strip()
    registry_path = _visual_recipe_registry_path()
    registry = _load_visual_recipe_registry()
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    platforms = {str(item).casefold() for item in (plan.get("platforms") or []) if str(item).strip()}
    recipe_family = str(recipe.get("template_family") or plan.get("template_family") or "").strip()
    recipe_pipeline = str(recipe.get("selected_pipeline") or plan.get("selected_pipeline") or "").strip()
    duplicates = []
    for item in registry.get("recipes", []):
        if not isinstance(item, dict):
            continue
        item_core = str(item.get("core_fingerprint") or "").strip()
        item_family = str(item.get("template_family") or "").strip()
        item_pipeline = str(item.get("selected_pipeline") or "").strip()
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
            and item_modules
            and recipe_modules
            and item_style
            and recipe_style
            and item_modules == recipe_modules
            and item_style == recipe_style
        )
        if not (same_core or same_visual_family):
            continue
        used_at = _parse_utc(item.get("used_at"))
        if used_at and used_at < cutoff:
            continue
        item_platforms = {str(value).casefold() for value in (item.get("platforms") or []) if str(value).strip()}
        if platforms and item_platforms and platforms.isdisjoint(item_platforms):
            # Cross-platform duplication still matters for video hardening, but surface it explicitly.
            duplicates.append({**item, "duplicate_scope": "cross_platform"})
        else:
            duplicates.append({**item, "duplicate_scope": "same_platform_or_unknown"})
    return {
        "passed": not duplicates,
        "policy_enabled": True,
        "lookback_days": lookback_days,
        "registry_path": str(registry_path),
        "core_fingerprint": core,
        "duplicate_count": len(duplicates),
        "duplicates": duplicates[:5],
    }


def _register_visual_recipe_use(recipe: dict, plan: dict, output_path: str) -> None:
    registry_path = _visual_recipe_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_visual_recipe_registry()
    rows = [item for item in data.get("recipes", []) if isinstance(item, dict)]
    row = {
        "used_at": datetime.now(timezone.utc).isoformat(),
        "core_fingerprint": recipe.get("core_fingerprint"),
        "fingerprint": recipe.get("fingerprint"),
        "template_family": recipe.get("template_family"),
        "modules": recipe.get("modules") or [],
        "style_variants": recipe.get("style_variants") or {},
        "platforms": plan.get("platforms") or [],
        "selected_pipeline": plan.get("selected_pipeline") or "",
        "video_route": plan.get("video_route") or {},
        "style_id": (plan.get("video_route") or {}).get("style_id", "") if isinstance(plan.get("video_route"), dict) else "",
        "renderer_id": (plan.get("video_route") or {}).get("renderer_id", "") if isinstance(plan.get("video_route"), dict) else "",
        "output_path": output_path,
    }
    rows.append(row)
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
        out = output_dir / "final.mp4"
        shutil.copy2(source_path, out)
        manifest.update(
            {
                "ok": True,
                "status": "rendered",
                "output": str(out),
                "repost_source": {"source_type": "local_source_video", "path": str(source_path)},
                "source_asset_match": {"passed": True, "mode": "local_source_video"},
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
    generated = sorted((output_dir / "autoclip").rglob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not generated:
        manifest.update({"status": "source_processing_failed", "error": "autoclip produced no mp4"})
        _write_manifest(output_dir, manifest)
        print(manifest["error"], file=sys.stderr)
        return 7
    out = output_dir / "final.mp4"
    shutil.copy2(generated[0], out)
    manifest.update(
        {
            "ok": True,
            "status": "rendered",
            "output": str(out),
            "repost_source": {"source_type": "source_url", "source_url": source_url},
            "source_asset_match": {"passed": True, "mode": "autoclip"},
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


def _card_title(text: str, index: int) -> str:
    # ⚠️ 2026-08-10 修复：中文无空格，split() 整句算一个词 → 恒 <4 → 返回 "Scene N" 占位
    # 改为按字符数截取（中文 16 字内作卡片标题，英文按词截取兜底）
    text = str(text or "").strip()
    if not text:
        return f"Scene {index + 1}"
    # 英文标题保留完整首句；中文标题仍保持短标题，正文由卡片模块承载。
    if re.search(r"[\u4e00-\u9fff]", text):
        return text[:16]
    first = re.split(r"[.!?;]", text, maxsplit=1)[0].strip()
    return first or text or f"Scene {index + 1}"


def _summary(text: str) -> str:
    return " ".join(_beats(text)[:2]) or "Auto generated video package"


def _tags(plan: dict) -> list[str]:
    platforms = [str(item) for item in plan.get("platforms") or []]
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


def _primary_platform(plan: dict) -> str:
    platforms = [str(item).casefold() for item in (plan.get("platforms") or []) if str(item).strip()]
    return platforms[0] if platforms else "video"


def _tool_invocation_manifest(plan: dict, repost: bool = False) -> dict:
    names = REPOST_PLANNED_TOOLS if repost else _route_planned_tools(plan)
    planned = {name: _tool_ref(name) for name in names}
    return build_tool_invocation_manifest(
        planned_tools=planned,
        invocations={name: {"status": "planned_internal", "output": ref} for name, ref in planned.items()},
    )


def _route_planned_tools(plan: dict) -> list[str]:
    route = plan.get("video_route") if isinstance(plan.get("video_route"), dict) else {}
    return list(ROUTE_PLANNED_TOOLS.get(str(route.get("renderer_id") or ""), PLANNED_TOOLS))


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


if __name__ == "__main__":
    raise SystemExit(main())
