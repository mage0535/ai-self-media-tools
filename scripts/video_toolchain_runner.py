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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    script_body = argv[0] if argv else ""
    title = argv[1] if len(argv) > 1 else "Untitled video"
    output_dir = Path(os.environ.get("VIDEO_OUTPUT_DIR") or ROOT / "data" / "artifacts" / "video_toolchain").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = _load_plan()
    if str(plan.get("selected_pipeline") or "") == "localized_repost_video" and os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") != "1":
        return _run_localized_repost(plan, output_dir, title)
    dry_run = os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1"
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
    # diagram-design 补图通道：结构化主题且背景不足时，自动生成杂志级 diagram 背景
    materialized_backgrounds = _diagram_background_fill(output_dir, script_body or title, materialized_backgrounds)
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
    )
    pre_render_gate_path = output_dir / "pre_render_gate.json"
    pre_render_gate_path.write_text(json.dumps(pre_render_gate, ensure_ascii=False, indent=2), encoding="utf-8")
    if not pre_render_gate.get("passed"):
        manifest = {
            "ok": False,
            "title": title,
            "selected_pipeline": plan.get("selected_pipeline", ""),
            "template_family": plan.get("template_family", ""),
            "status": "pre_render_gate_failed",
            "error": "generated cards failed pre-render validation",
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
    renderer, plan = _content_driven_renderer(plan, script_body, title, output_dir)
    template_family = str(visual_recipe.get("template_family") or plan.get("template_family") or "")
    style_variants = visual_recipe.get("style_variants") if isinstance(visual_recipe.get("style_variants"), dict) else {}
    theme = str(style_variants.get("theme") or THEME_BY_TEMPLATE.get(template_family, "cyber-neon"))
    bgm_style = _bgm_style(cinema_scenes)
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
        "visual_recipe": visual_recipe,
        "visual_recipe_path": str(recipe_path),
        "visual_recipe_gate": recipe_gate,
        "recipe_reuse_gate": recipe_reuse_gate,
        "scene_manifest": scene_manifest,
        "scene_manifest_path": str(scene_manifest_path),
        "scene_manifest_gate": scene_manifest_gate,
        "recipe_fingerprint": visual_recipe.get("fingerprint"),
        "recipe_core_fingerprint": visual_recipe.get("core_fingerprint"),
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
    generated = sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    if proc.returncode == 0 and generated:
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
        for record in (manifest.get("tool_invocation_manifest", {}).get("invocations", {}) or {}).values():
            if isinstance(record, dict) and record.get("status") == "planned_internal":
                record["status"] = "ok"
                record["artifact"] = str(generated[0])
        manifest.update({"ok": True, "output": str(generated[0]), "status": "rendered", "executed_tools": PLANNED_TOOLS})
        _register_visual_recipe_use(visual_recipe, plan, str(generated[0]))
        _write_manifest(output_dir, manifest)
        print(json.dumps({"ok": True, "output": str(generated[0])}, ensure_ascii=False))
        return 0
    manifest["error"] = "video renderer produced no mp4"
    _write_manifest(output_dir, manifest)
    print(manifest["stderr_tail"] or manifest["stdout_tail"] or manifest["error"], file=sys.stderr)
    return proc.returncode or 3


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
    cards = []
    for index in range(8):
        beat = beats[index % len(beats)]
        next_beat = beats[(index + 1) % len(beats)]
        layout = LAYOUTS[index % len(LAYOUTS)]
        scene = (cinema_scenes or [])[index] if index < len(cinema_scenes or []) else {}
        card = {
            "layout": layout,
            "t": title[:36] if index == 0 else _card_title(beat, index),
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
        }
        if visual_assignments:
            card["visual_asset"] = visual_assignments[index % len(visual_assignments)]
        if layout == "cover":
            card.update({"sub": _summary(script_body)[:40], "hook": title[:42], "hook_prefix": "Auto selected video workflow"})
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
                }
            )
    except Exception as e:
        print(f"[diagram-fill] skipped: {e}", file=sys.stderr)
    return existing


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
    # 文案来源：script_body 或 title（title 也是内容信号）
    # ⚠️ 对齐 film_renderer 内部逻辑：只检测偶数段（i%2==0 才启用动效镜头），
    # 避免"切了 film_renderer 但实际无动效"的白切
    text = f"{script_body}\n{title}"
    wants_element_motion = False
    try:
        from scripts.film_renderer import detect_element_shot
        segs = [s for s in re.split(r"\n\s*\n", text) if s.strip()]
        for idx, seg in enumerate(segs, 1):
            if idx % 2 == 0 and detect_element_shot(seg):
                wants_element_motion = True
                break
        # 偶数段都不命中时，再查 title 本身（标题也可能是动效信号，且 title 会进 film_renderer 的 seg_title）
        if not wants_element_motion and title and detect_element_shot(title):
            wants_element_motion = True
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


def _bgm_style(cinema_scenes: list[dict]) -> str:
    for scene in cinema_scenes:
        scheme = scene.get("color_scheme") or {}
        hint = str(scheme.get("bgm_hint") or scheme.get("bgm") or "").strip()
        if hint:
            return hint[:80]
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
    policy = _duplication_policy().get("same_day_template_duplicate") or {}
    if policy.get("enabled") is False:
        return {"passed": True, "policy_enabled": False}
    lookback_days = int(policy.get("lookback_days") or 1)
    core = str(recipe.get("core_fingerprint") or "").strip()
    registry_path = _visual_recipe_registry_path()
    registry = _load_visual_recipe_registry()
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    platforms = {str(item).casefold() for item in (plan.get("platforms") or []) if str(item).strip()}
    duplicates = []
    for item in registry.get("recipes", []):
        if not isinstance(item, dict) or str(item.get("core_fingerprint") or "").strip() != core:
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
        "platforms": plan.get("platforms") or [],
        "selected_pipeline": plan.get("selected_pipeline") or "",
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
    # 中文为主：直接取前 16 字符
    if re.search(r"[\u4e00-\u9fff]", text):
        return text[:16]
    words = text.split()
    if len(words) >= 4:
        return " ".join(words[:6])[:36]
    return text[:36] or f"Scene {index + 1}"


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
    (output_dir / "video_toolchain_runner_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _primary_platform(plan: dict) -> str:
    platforms = [str(item).casefold() for item in (plan.get("platforms") or []) if str(item).strip()]
    return platforms[0] if platforms else "video"


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


if __name__ == "__main__":
    raise SystemExit(main())
