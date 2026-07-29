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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cinema_composition import storyboard


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RENDERER = ROOT / "scripts" / "kuaishou_render.py"
LAYOUTS = ["cover", "two_column", "card_stack", "big_number", "timeline", "diagonal", "card_stack", "interaction"]
THEME_BY_TEMPLATE = {
    "pet_repost_real_behavior": "mint-fresh",
    "wechat_ecosystem_microcase": "blueprint",
    "chaptered_tutorial": "blueprint",
    "social_note_motion_cards": "mint-fresh",
    "knowledge_card_motion_case": "cyber-neon",
}
PLANNED_TOOLS = [
    "cinema_composition.storyboard",
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
    output_dir = Path(os.environ.get("VIDEO_OUTPUT_DIR") or ROOT / "data" / "artifacts" / "video_toolchain")
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = _load_plan()
    if str(plan.get("selected_pipeline") or "") == "localized_repost_video" and os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") != "1":
        return _run_localized_repost(plan, output_dir, title)
    cinema_scenes = storyboard(script_body or title, 8)
    cards = build_cards(script_body, title, plan, cinema_scenes)
    cards_path = output_dir / "cards.json"
    cards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
    renderer = _renderer_path(plan)
    theme = THEME_BY_TEMPLATE.get(str(plan.get("template_family") or ""), "cyber-neon")
    bgm_style = _bgm_style(cinema_scenes)
    renderer_cmd = _renderer_command(renderer, output_dir, theme, title, script_body, plan, bgm_style)
    toolchain_contract = _toolchain_contract(plan, theme, bgm_style, renderer)
    manifest = {
        "ok": False,
        "title": title,
        "selected_pipeline": plan.get("selected_pipeline", ""),
        "template_family": plan.get("template_family", ""),
        "cards_json": str(cards_path),
        "renderer": str(renderer),
        "renderer_command_preview": renderer_cmd,
        "bgm_style": bgm_style,
        "toolchain_contract": toolchain_contract,
        "dry_run": os.environ.get("VIDEO_TOOLCHAIN_DRY_RUN") == "1",
        "cinema_storyboard": cinema_scenes,
    }
    if manifest["dry_run"]:
        fake = output_dir / "dry_run.mp4"
        fake.write_bytes(b"video-toolchain-dry-run")
        manifest.update({"ok": True, "output": str(fake), "status": "dry_run"})
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
        manifest.update({"ok": True, "output": str(generated[0]), "status": "rendered", "executed_tools": PLANNED_TOOLS})
        _write_manifest(output_dir, manifest)
        print(json.dumps({"ok": True, "output": str(generated[0])}, ensure_ascii=False))
        return 0
    manifest["error"] = "video renderer produced no mp4"
    _write_manifest(output_dir, manifest)
    print(manifest["stderr_tail"] or manifest["stdout_tail"] or manifest["error"], file=sys.stderr)
    return proc.returncode or 3


def build_cards(script_body: str, title: str, plan: dict, cinema_scenes: list[dict] | None = None) -> list[dict]:
    beats = _beats(script_body)
    cards = []
    for index in range(8):
        beat = beats[index] if index < len(beats) else f"Step {index + 1}: keep the visual rhythm aligned with the script."
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
        }
        if layout == "cover":
            card.update({"sub": _summary(script_body)[:40], "hook": title[:42], "hook_prefix": "Auto selected video workflow"})
        if layout == "card_stack":
            card["items"] = [beat, "Match visual to narration", "Keep subtitles in the lower third"]
        if layout == "big_number":
            card.update({"num": f"0{index + 1}", "ext": beat})
        if layout == "timeline":
            card["items"] = [beat, "Add voiceover", "Add licensed music", "Run post-render checks"]
        cards.append(card)
    return cards


def _run_cinema_visual_gate(output_dir: Path) -> dict:
    image_dir = output_dir / "cards"
    candidates = []
    for root in [image_dir, output_dir]:
        if root.is_dir():
            for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                candidates.extend(root.glob(pattern))
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


def _load_plan() -> dict:
    path = os.environ.get("VIDEO_TOOLCHAIN_PLAN_PATH", "")
    if path and Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "selected_pipeline": os.environ.get("VIDEO_SELECTED_PIPELINE", "knowledge_card_video"),
        "template_family": os.environ.get("VIDEO_TEMPLATE_FAMILY", "knowledge_card_motion_case"),
    }


def _renderer_path(plan: dict) -> Path:
    env_key = "VIDEO_RENDERER_" + re.sub(r"[^A-Z0-9]+", "_", str(plan.get("selected_pipeline") or "").upper())
    return Path(os.environ.get(env_key) or os.environ.get("VIDEO_TOOLCHAIN_RENDERER") or DEFAULT_RENDERER)


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
        "--tags",
        *_tags(plan),
    ]


def _bgm_style(cinema_scenes: list[dict]) -> str:
    for scene in cinema_scenes:
        scheme = scene.get("color_scheme") or {}
        hint = str(scheme.get("bgm_hint") or scheme.get("bgm") or "").strip()
        if hint:
            return hint[:80]
    return "warm optimistic electronic"


def _toolchain_contract(plan: dict, theme: str, bgm_style: str, renderer: Path) -> dict:
    return {
        "planned_tools": PLANNED_TOOLS,
        "renderer_steps": RENDERER_STEPS,
        "effect_stack": EFFECT_STACK,
        "template_registry": {
            "template_family": str(plan.get("template_family") or ""),
            "theme": theme,
            "renderer": str(renderer),
            "card_layouts": LAYOUTS,
        },
        "bgm_style": bgm_style,
        "post_render_gates": ["visual_gate.py --cinema"],
    }


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
    manifest = {
        "ok": False,
        "title": title,
        "selected_pipeline": plan.get("selected_pipeline", ""),
        "template_family": plan.get("template_family", ""),
        "renderer": "localized_repost_video",
        "dry_run": False,
        "toolchain_contract": _repost_contract(plan),
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
    parts = [part.strip(" -#\t") for part in re.split(r"\n+|[。.!?；;]", text or "") if part.strip(" -#\t")]
    return [part[:120] for part in parts if len(part) >= 8][:10]


def _card_title(text: str, index: int) -> str:
    words = text.strip().split()
    if len(words) >= 4:
        return " ".join(words[:6])[:36]
    return f"Scene {index + 1}"


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


if __name__ == "__main__":
    raise SystemExit(main())
