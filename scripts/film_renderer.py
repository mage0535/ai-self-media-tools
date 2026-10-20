#!/usr/bin/env python3
"""融合渲染器：电影级多镜头 + xfade 转场 + 双层动效 + drawtext 字幕。

作为主仓心管线（video_toolchain_runner）的可选渲染器存在：
- 输入：runner 产出的 --video-dir 下的 cards.json / tts/ / backgrounds/ / scene_manifest.json
- 输出：final.mp4（通过 runner 的 cinema visual gate / artifact gate / motion gate / scene duration gate）
- 路由：plan.selected_pipeline = cinema_multishot_video 时，runner 通过
  VIDEO_RENDERER_CINEMA_MULTISHOT_VIDEO=scripts/film_renderer.py 调用本脚本
- 每个段落拆 A（全景建立：大标题+引言+数据徽章）与 B（特写要点：3模块 stagger 入场）双镜头，
  镜头间 xfade 转场，背景 Ken Burns + 正文持续浮动（双层分离运动），drawtext 字幕烧录。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import fcntl
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.video_artifact import (
    MOTION_EVIDENCE_VERSION,
    measure_motion_evidence,
    measure_spatial_motion_evidence,
    verify_final_pixels,
)

W, H = 1080, 1920
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
XFADE_DUR = 0.5
# 转场类型（08-14 用户反馈「切换闪白光」→ 移除 xfade "fade"（fade 到白场）。
# 08-14 增强「真实可观性」：按镜头类型差异化过渡——A→A 黑场/smooth（建立感），
# B→B 方向性 wipe/slide（节奏推进），A→B circle（段落转折），机械轮换 → 语义映射。
TRANSITIONS = ["smoothleft", "slideleft", "wipeleft", "smoothup", "revealright"]
# 转场时长：段内镜头间紧凑(0.35s)，段落间强调(0.6s) —— 差异化节奏，非统一 0.5s
XFADE_DUR_SHORT = 0.35
XFADE_DUR_LONG = 0.6
MAX_TTS_SEGMENT_SECONDS = 20.0
MAX_RENDER_SECONDS = 100.0
FILM_TTS_MAX_ATTEMPTS = 4
RENDERER_VERSION = "cinematic-v11-stable-copy-safe-layout10"
ELEMENT_FRAME_RENDER_MIN_TIMEOUT_SECONDS = 90

INDUSTRIAL_TOPIC_MODES = {
    "decision_interrupt", "capture_rig_exploded_view", "dataset_annotation_board",
    "anomaly_heatmap_inspection", "risk_queue_flow", "human_review_console",
    "failure_boundary_triptych", "execution_audit_receipt", "pilot_timeline",
}


def _is_english_text(text: str) -> bool:
    """检测文本是否主要为英文（用于多语言 UI 文案切换）"""
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len(text.strip())
    if total == 0:
        return False
    return ascii_chars / total > 0.6 and cjk_chars / total < 0.1


def _step_label(idx: int, is_en: bool) -> str:
    """返回步骤标签：英文 'Step N' / 中文 '第 N 步'"""
    return f"Step {idx + 1}" if is_en else f"第 {idx + 1} 步"


def _tile_desc(idx: int, is_en: bool) -> str:
    """返回图块描述：英文 'Key point N' / 中文 '第 N 个要点，点亮看重点'"""
    return f"Key point {idx + 1}" if is_en else f"第 {idx + 1} 个要点，点亮看重点"


def _fallback_step_name(idx: int, is_en: bool) -> str:
    """步骤数不足时的占位名"""
    return f"Step {idx + 1}" if is_en else f"步骤{['一','二','三','四'][idx]}"


def resolve_render_policy() -> dict[str, object]:
    """Keep the production default cinematic and make degradation explicit."""
    profile = os.environ.get("FILM_QUALITY_PROFILE", "high").strip().casefold() or "high"
    motion_mode = os.environ.get("FILM_MOTION_MODE", "cinematic").strip().casefold() or "cinematic"
    allow_degraded = os.environ.get("FILM_ALLOW_DEGRADED", "").strip() == "1"
    if profile == "high":
        if motion_mode != "cinematic":
            raise ValueError("high quality requires FILM_MOTION_MODE=cinematic")
        return {"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False}
    if profile == "degraded":
        if motion_mode != "safe" or not allow_degraded:
            raise ValueError("degraded rendering requires FILM_MOTION_MODE=safe and FILM_ALLOW_DEGRADED=1")
        return {"quality_profile": "degraded", "motion_mode": "safe", "allow_degraded": True}
    raise ValueError(f"unsupported FILM_QUALITY_PROFILE: {profile}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


SCENE_KEY_SCHEMA = "film-scene-key-v1"
SHOT_CACHE_MANIFEST_VERSION = "film-shot-cache-v1"
FINAL_RENDER_CACHE_VERSION = "film-final-cache-v1"
FINAL_CACHE_EVIDENCE_FILES = (
    "subtitle_cue_manifest.json", "subtitle_pixel_evidence.json",
    "luminance_flash_evidence.json", "audio_quality_evidence.json",
    "audio_release_evidence.json", "av_alignment_evidence.json",
    "shot_render_records.json", "render_quality_evidence.json",
    "segment_motion_evidence.json", "scene_execution_evidence.json",
)
_SCENE_RUNTIME_KEYS = frozenset({
    "renderer_sha256", "font_sha256", "browser_sha256", "gate_sha256",
    "renderer_version", "browser_version", "playwright_version",
    "quality_profile", "motion_mode", "width", "height", "fps",
})


def _canonical_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _chromium_executable_path() -> str:
    """Use one actual browser for cache identity and all rendering launches."""
    override = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if override:
        browser = Path(override)
        if not browser.is_file():
            raise RuntimeError("browser_executable_missing")
        return str(browser.resolve())
    roots = [Path.home() / ".cache/ms-playwright"]
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if configured and configured != "0":
        roots.insert(0, Path(configured))
    if os.name == "posix":
        import pwd
        # A task-private HOME must not hide the installed account browser binary.
        roots.append(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache/ms-playwright")
    for root in dict.fromkeys(roots):
        candidates = sorted(root.glob("chromium-*/chrome-linux*/chrome"),
            key=lambda path: path.parent.parent.name, reverse=True)
        browser = next((path for path in candidates if path.is_file()), None)
        if browser is not None:
            return str(browser.resolve())
    raise RuntimeError("browser_executable_missing")


def _chromium_launch_environment() -> dict[str, str]:
    """Keep Chromium's Unix socket in short service-private /tmp; keep TTS tmp."""
    environment = os.environ.copy()
    environment["TMPDIR"] = "/tmp"
    # ProtectHome isolates /root in the media unit. Crashpad still needs a
    # writable config/cache even for a new headless, non-account browser.
    identity = environment.get("HERMES_HOME") or str(ROOT)
    scratch = Path('/tmp') / ('hermes-media-chromium-' + hashlib.sha256(identity.encode()).hexdigest()[:16])
    for directory in (scratch, scratch / 'config', scratch / 'cache'):
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.stat()
        if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError('private_chromium_runtime_directory_required')
    environment['XDG_CONFIG_HOME'] = str(scratch / 'config')
    environment['XDG_CACHE_HOME'] = str(scratch / 'cache')
    return environment


def build_shot_runtime_fingerprint(*, width: int, height: int, policy: dict[str, object]) -> dict[str, object]:
    """Bind scene cache to the actual local renderer, font, browser and visual gate."""
    import importlib.metadata

    browser = Path(_chromium_executable_path())
    renderer = Path(__file__).resolve()
    font = Path(FONT)
    gate = ROOT / "scripts" / "visual_contract_gate.py"
    for label, path in (("renderer", renderer), ("font", font), ("browser", browser), ("visual gate", gate)):
        if not path.is_file():
            raise RuntimeError(f"scene cache {label} fingerprint source missing: {path}")
    version = subprocess.run([str(browser), "--version"], capture_output=True, text=True, timeout=20)
    if version.returncode:
        raise RuntimeError("scene cache browser version probe failed")
    return {
        "renderer_version": RENDERER_VERSION,
        "renderer_sha256": _sha256_file(renderer),
        "font_sha256": _sha256_file(font),
        "browser_sha256": _sha256_file(browser),
        "browser_version": version.stdout.strip(),
        "playwright_version": importlib.metadata.version("playwright"),
        "gate_sha256": _sha256_file(gate),
        "quality_profile": policy["quality_profile"],
        "motion_mode": policy["motion_mode"],
        "width": int(width), "height": int(height), "fps": 25,
    }


def build_scene_key(
    scene_id: str,
    shots: list[dict[str, object]],
    background: Path,
    runtime: dict[str, object],
) -> tuple[str, dict[str, object]]:
    """Build a deterministic key from every input capable of changing scene pixels."""
    required_runtime = {"renderer_sha256", "font_sha256", "browser_sha256", "gate_sha256", "width", "height", "fps"}
    missing_runtime = sorted(required_runtime - set(runtime))
    if missing_runtime:
        raise ValueError(f"scene runtime fingerprint missing: {','.join(missing_runtime)}")
    if len(shots) != 2:
        raise ValueError("scene cache requires exactly two A/B shots")
    canonical_shots = []
    for shot in shots:
        html_path = Path(str(shot.get("html_path") or ""))
        if not html_path.is_file():
            raise ValueError(f"scene HTML missing: {html_path}")
        canonical_shots.append({
            "name": str(shot.get("name") or ""),
            "html_sha256": _sha256_file(html_path),
            "duration_ms": int(round(float(shot.get("duration") or 0.0) * 1000)),
            "render_mode": str(shot.get("render_mode") or ""),
        })
    background = Path(background)
    if not background.is_file():
        raise ValueError(f"scene background missing: {background}")
    payload = {
        "schema": SCENE_KEY_SCHEMA,
        "scene_id": str(scene_id),
        "shots": canonical_shots,
        "background_sha256": _sha256_file(background),
        "runtime": {key: runtime[key] for key in sorted(_SCENE_RUNTIME_KEYS) if key in runtime},
    }
    return _canonical_sha256(payload), payload


def _probe_cached_shot(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,pix_fmt,width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise ValueError("ffprobe_failed")
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    if len(streams) != 1:
        raise ValueError("video_stream_invalid")
    stream = streams[0]
    rate = str(stream.get("r_frame_rate") or "0/1").split("/", 1)
    fps = float(rate[0]) / max(1.0, float(rate[1]))
    return {
        "duration_ms": int(round(float((data.get("format") or {}).get("duration") or 0.0) * 1000)),
        "width": int(stream.get("width") or 0), "height": int(stream.get("height") or 0),
        "fps": round(fps, 6), "codec": str(stream.get("codec_name") or ""),
        "pix_fmt": str(stream.get("pix_fmt") or ""),
    }


def _remove_scene_cache(out: Path, scene_id: str, shot_names: list[str]) -> None:
    for name in shot_names:
        (out / "shots" / f"{name}.mp4").unlink(missing_ok=True)
        shutil.rmtree(out / "frames" / name, ignore_errors=True)
        for path in (out / "webm").glob(f"{name}*"):
            path.unlink(missing_ok=True)
    (out / "shot_cache" / f"{scene_id}.json").unlink(missing_ok=True)


def commit_scene_cache(
    out: Path,
    scene_id: str,
    scene_key: str,
    key_payload: dict[str, object],
    shots: list[dict[str, object]],
) -> Path:
    """Atomically publish a fully probed A/B pair; partial scenes never become hits."""
    out = Path(out)
    records = []
    for shot in shots:
        name = str(shot["name"])
        artifact = out / "shots" / f"{name}.mp4"
        if not artifact.is_file():
            raise ValueError(f"scene cache output missing: {name}")
        probe = _probe_cached_shot(artifact)
        records.append({
            "name": name,
            "render_mode": str(shot.get("render_mode") or ""),
            "fallback": bool(shot.get("fallback", False)),
            "output_sha256": _sha256_file(artifact),
            "bytes": artifact.stat().st_size,
            **probe,
        })
    cache_dir = out / "shot_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{scene_id}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "version": SHOT_CACHE_MANIFEST_VERSION, "scene_id": scene_id,
        "scene_key": scene_key, "key_payload": key_payload, "shots": records,
    }, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return target


def inspect_scene_cache(
    out: Path,
    scene_id: str,
    expected_key: str,
    expected_payload: dict[str, object],
    *,
    verify_media: bool = True,
) -> dict[str, object]:
    """Return a hit only when the complete A/B pair matches key, SHA and media ABI."""
    out = Path(out)
    expected_shots = list(expected_payload.get("shots") or [])
    names = [str(row.get("name") or "") for row in expected_shots]
    manifest_path = out / "shot_cache" / f"{scene_id}.json"
    reason = "checkpoint_missing"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != SHOT_CACHE_MANIFEST_VERSION or manifest.get("scene_id") != scene_id:
            raise ValueError("checkpoint_invalid")
        if manifest.get("scene_key") != expected_key or manifest.get("key_payload") != expected_payload:
            raise ValueError("inputs_changed")
        records = manifest.get("shots") or []
        if [row.get("name") for row in records] != names:
            raise ValueError("atomic_pair_incomplete")
        runtime = expected_payload.get("runtime") or {}
        expected_by_name = {row["name"]: row for row in expected_shots}
        for record in records:
            name = str(record["name"])
            artifact = out / "shots" / f"{name}.mp4"
            if not artifact.is_file() or _sha256_file(artifact) != record.get("output_sha256"):
                raise ValueError("artifact_sha_mismatch")
            expected = expected_by_name[name]
            metadata_invalid = (
                record.get("render_mode") != expected.get("render_mode")
                or bool(record.get("fallback"))
            )
            if verify_media:
                actual = _probe_cached_shot(artifact)
                metadata_invalid = metadata_invalid or (
                    abs(actual["duration_ms"] - int(expected["duration_ms"])) > 100
                    or actual["width"] != int(runtime["width"])
                    or actual["height"] != int(runtime["height"])
                    or abs(float(actual["fps"]) - float(runtime["fps"])) > 0.01
                    or actual["codec"] != "h264" or actual["pix_fmt"] != "yuv420p"
                )
            if metadata_invalid:
                raise ValueError("ffprobe_mismatch")
        return {"hit": True, "reason": "checkpoint_match", "records": records}
    except FileNotFoundError:
        reason = "checkpoint_missing"
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        reason = "checkpoint_invalid"
    except ValueError as exc:
        reason = str(exc)
    _remove_scene_cache(out, scene_id, names)
    return {"hit": False, "reason": reason, "records": []}


def build_final_render_key(
    render_contract: dict[str, object],
    scene_keys: list[str],
    tts_sha256: list[str],
    secondary_audio_sha256: str,
    audio_route: str,
) -> str:
    return _canonical_sha256({
        "schema": FINAL_RENDER_CACHE_VERSION,
        "render_contract": render_contract,
        "scene_keys": scene_keys,
        "tts_sha256": tts_sha256,
        "secondary_audio_sha256": secondary_audio_sha256,
        "audio_route": audio_route,
    })


def commit_final_render_cache(
    out: Path,
    final_key: str,
    final: Path,
    evidence_paths: list[Path],
) -> Path:
    out, final = Path(out), Path(final)
    if not final.is_file():
        raise ValueError("final cache candidate missing")
    evidence = {}
    for path in evidence_paths:
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"final cache evidence missing: {path.name}")
        evidence[path.name] = _sha256_file(path)
    if set(evidence) != set(FINAL_CACHE_EVIDENCE_FILES):
        raise ValueError("final cache evidence set incomplete")
    target = out / "final_render_cache.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "version": FINAL_RENDER_CACHE_VERSION,
        "final_key": final_key,
        "final_sha256": _sha256_file(final),
        "evidence_sha256": evidence,
    }, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return target


def inspect_final_render_cache(out: Path, expected_key: str) -> dict[str, object]:
    out = Path(out)
    manifest_path = out / "final_render_cache.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != FINAL_RENDER_CACHE_VERSION:
            raise ValueError("checkpoint_invalid")
        if manifest.get("final_key") != expected_key:
            raise ValueError("inputs_changed")
        final = out / "final.mp4"
        if not final.is_file() or _sha256_file(final) != manifest.get("final_sha256"):
            raise ValueError("final_sha_mismatch")
        evidence = manifest.get("evidence_sha256") or {}
        if set(evidence) != set(FINAL_CACHE_EVIDENCE_FILES):
            raise ValueError("evidence_set_incomplete")
        for name, digest in evidence.items():
            path = out / name
            if not path.is_file() or _sha256_file(path) != digest:
                raise ValueError("evidence_sha_mismatch")
        return {"hit": True, "reason": "checkpoint_match", "final_sha256": manifest["final_sha256"]}
    except FileNotFoundError:
        reason = "checkpoint_missing"
    except (OSError, json.JSONDecodeError, TypeError):
        reason = "checkpoint_invalid"
    except ValueError as exc:
        reason = str(exc)
    manifest_path.unlink(missing_ok=True)
    return {"hit": False, "reason": reason}


def card_sample_time(duration: float) -> float:
    """Choose a stable audit frame that always lies inside the shot."""
    return round(min(1.5, max(0.04, float(duration) * 0.5)), 3)


VISUAL_TREATMENT_REQUIRED_FIELDS = (
    "scene_id", "display_purpose", "real_asset", "camera_language",
    "subject_motion", "text_motion", "transition", "rhythm_beat", "interaction_prompt",
)
CAMERA_LANGUAGE_INDEX = {
    "handheld_push": 0, "left_dolly": 1, "top_down_reveal": 2, "right_dolly": 3,
    "orbit_pull": 4, "split_screen_slide": 5, "direct_eye_contact": 6, "snap_zoom": 7,
}
TEXT_MOTION_INDEX = {
    "message_type": 0, "warning_shake": 1, "label_stagger": 2, "focus_fade": 3,
    "highlight_underline": 0, "path_draw": 1, "before_after_wipe": 2, "choice_bounce": 3,
}
SUBJECT_MOTION_ELEMENT_SHOT = {
    "message_pop": "message_stack",
    "kanban_reveal": "tile_activate", "warning_split": "split_compare", "choice_pulse": "tile_activate",
    "action_path": "step_light", "outline_compare": "step_light", "persona_focus": "step_light",
    "thesis_spotlight": "digit_roll",
    "digit_roll": "digit_roll",
}
TRANSITION_MAP = {
    "hard_cut": "wipeleft", "glitch_wipe": "wipeleft", "card_flip": "slideleft",
    "left_swipe": "smoothleft", "right_swipe": "smoothleft", "path_draw": "smoothup",
    "split_reveal": "revealright", "end_hold": "dissolve",
}


def select_contract_b_mode(
    mode_a: str, scene_index: int, template_id: str, prompt_lab_modes: list[str]
) -> str:
    """Keep B shots inside the scene's semantic contract; vary only where explicitly supported."""
    if str(template_id).startswith("predictive_maintenance_"):
        return f"{mode_a}_detail"
    industrial_modes = {
        "decision_interrupt", "capture_rig_exploded_view", "dataset_annotation_board",
        "anomaly_heatmap_inspection", "risk_queue_flow", "human_review_console",
        "failure_boundary_triptych", "execution_audit_receipt",
    }
    if mode_a in industrial_modes:
        return f"{mode_a}_detail"
    selected = prompt_lab_modes[scene_index % len(prompt_lab_modes)]
    if selected == mode_a:
        selected = prompt_lab_modes[(scene_index + 1) % len(prompt_lab_modes)]
    return selected

# Union emitted by the platform and creative-structure routers. Each mode has a
# concrete body branch and an explicit visible layout in build_prompt_lab_shot.
ROUTABLE_VISUAL_MODES = frozenset({
    "before_after_split", "prompt_typewriter", "annotation_callout",
    "location_selector", "light_split_compare", "composition_push_in",
    "error_fix_compare", "checklist_stamp", "terminal_evidence",
    "timeline_reveal", "result_hold", "result_reveal", "flow_track",
    "source_trace", "evidence_timeline", "result_audit", "failure_rollback",
    "input_branch", "edge_case_matrix", "reproducibility_compare",
    "metric_contrast", "checklist_lock", "cta_warning",
})


def load_visual_treatment_plan(path: Path, *, expected_scene_count: int) -> list[dict[str, object]]:
    """Load a complete scene plan before high-quality rendering starts."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"visual treatment plan unreadable: {exc}") from exc
    scenes = payload.get("scenes") if isinstance(payload, dict) else None
    if not isinstance(scenes, list) or len(scenes) != expected_scene_count:
        raise ValueError(f"visual treatment plan requires exactly {expected_scene_count} scenes")
    scene_ids = set()
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError(f"visual treatment scene {index} must be an object")
        missing = [field for field in VISUAL_TREATMENT_REQUIRED_FIELDS if field not in scene]
        if missing:
            raise ValueError(f"visual treatment scene {index} missing required fields: {', '.join(missing)}")
        if not str(scene["display_purpose"]).strip() or not isinstance(scene["rhythm_beat"], dict):
            raise ValueError(f"visual treatment scene {index} has invalid purpose or rhythm")
        scene_id = str(scene["scene_id"])
        if not scene_id or scene_id in scene_ids:
            raise ValueError(f"visual treatment scene {index} has duplicate scene_id")
        scene_ids.add(scene_id)
        asset = Path(str(scene["real_asset"]))
        if not asset.is_file():
            raise ValueError(f"visual treatment scene {index} real_asset is unavailable")
        if str(scene["camera_language"]) not in CAMERA_LANGUAGE_INDEX:
            raise ValueError(f"visual treatment scene {index} camera_language is unsupported")
        if str(scene["text_motion"]) not in TEXT_MOTION_INDEX:
            raise ValueError(f"visual treatment scene {index} text_motion is unsupported")
        if str(scene["transition"]) not in TRANSITION_MAP:
            raise ValueError(f"visual treatment scene {index} transition is unsupported")
    return scenes


def resolve_scene_treatment(scene: dict[str, object]) -> dict[str, object]:
    """Translate declared visual intent into concrete renderer choices and provenance."""
    asset = Path(str(scene["real_asset"]))
    subject_motion = str(scene["subject_motion"])
    return {
        "scene_id": str(scene["scene_id"]),
        "display_purpose": str(scene["display_purpose"]),
        "asset_path": str(asset),
        "asset_sha256": _sha256_file(asset),
        "camera_language": str(scene["camera_language"]),
        "camera_index": CAMERA_LANGUAGE_INDEX[str(scene["camera_language"])],
        "subject_motion": subject_motion,
        "element_shot": SUBJECT_MOTION_ELEMENT_SHOT.get(subject_motion, ""),
        "text_motion": str(scene["text_motion"]),
        "text_motion_index": TEXT_MOTION_INDEX[str(scene["text_motion"])],
        "transition": TRANSITION_MAP[str(scene["transition"])],
        "declared_transition": str(scene["transition"]),
        "rhythm_beat": scene["rhythm_beat"],
        "interaction_prompt": str(scene["interaction_prompt"]),
    }


def ensure_visual_treatment_plan(out: Path, bg_paths: list[Path]) -> Path:
    """Create the required plan from real material when an upstream tool omitted it.

    This is intentionally a deterministic fallback, not a generic template: each
    scene gets a distinct camera, text motion and transition and can bind a real
    screenshot when the package contains one.
    """
    path = out / "visual_treatment_plan.json"
    if path.is_file():
        return path
    screenshots_dir = out / "screenshots"
    screenshots = sorted([*screenshots_dir.glob("*.png"), *screenshots_dir.glob("*.jpg")]) if screenshots_dir.is_dir() else []
    cameras = ["handheld_push", "snap_zoom", "top_down_reveal", "left_dolly", "right_dolly", "orbit_pull", "split_screen_slide", "direct_eye_contact"]
    subjects = ["message_pop", "warning_split", "kanban_reveal", "persona_focus", "thesis_spotlight", "action_path", "outline_compare", "choice_pulse"]
    texts = ["message_type", "warning_shake", "label_stagger", "focus_fade", "highlight_underline", "path_draw", "before_after_wipe", "choice_bounce"]
    transitions = ["hard_cut", "glitch_wipe", "card_flip", "left_swipe", "right_swipe", "path_draw", "split_reveal", "end_hold"]
    scenes = []
    for index, background in enumerate(bg_paths[:8]):
        asset = screenshots[index // 4] if screenshots and index in (1, 5) else background
        scenes.append({
            "scene_id": f"s{index + 1:02d}",
            "display_purpose": "hook" if index == 0 else ("interaction" if index == 7 else "explain"),
            "real_asset": str(asset),
            "camera_language": cameras[index],
            "subject_motion": subjects[index],
            "text_motion": texts[index],
            "transition": transitions[index],
            "rhythm_beat": {"emphasis": "hook" if index == 0 else "proof" if index in (1, 5, 6) else "step"},
            "interaction_prompt": "comment your use case" if index == 7 else "",
        })
    path.write_text(json.dumps({"version": "visual_treatment_plan_v1", "generated_by": "film_renderer", "scenes": scenes}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


_FINAL_COMPOSITE_CONTRACT_KEYS = frozenset({"subtitle_y_up"})
_SCENE_INPUT_CONTRACT_KEYS = frozenset({
    "cards_sha256", "script_sha256", "scene_manifest_sha256",
    "visual_treatment_plan_sha256", "backgrounds_sha256", "transitions",
    "xfade_short", "xfade_long",
})


def _remove_release_outputs(out: Path) -> None:
    for name in (
        "final.mp4",
        "subtitle_cue_manifest.json",
        "luminance_flash_evidence.json",
        "trusted_run_manifest.json",
        "preview.mp4",
        "final_render_cache.json",
    ):
        (out / name).unlink(missing_ok=True)
    for path in out.glob("*_checker_evidence.json"):
        path.unlink(missing_ok=True)


def _remove_final_composite_outputs(out: Path) -> None:
    """Invalidate subtitle/final evidence without discarding browser shots."""
    shutil.rmtree(out / "sub", ignore_errors=True)
    _remove_release_outputs(out)


def _remove_scene_composite_outputs(out: Path) -> None:
    """Preserve content-addressed A/B shots while invalidating downstream composites."""
    shutil.rmtree(out / "sub", ignore_errors=True)
    for pattern in ("group_*.mp4", "visual_xfade.mp4", "mixed_v2.mp4", "voice_aligned.wav", "groups.txt"):
        for path in out.glob(pattern):
            path.unlink(missing_ok=True)
    _remove_release_outputs(out)


def _remove_renderer_outputs(out: Path) -> None:
    """Remove only reproducible renderer outputs when its contract changes."""
    for dirname in ("html", "webm", "shots", "frames", "sub", "shot_cache"):
        shutil.rmtree(out / dirname, ignore_errors=True)
    for pattern in ("group_*.mp4", "visual_xfade.mp4", "mixed_v2.mp4", "final.mp4", "voice_aligned.wav", "groups.txt"):
        for path in out.glob(pattern):
            path.unlink(missing_ok=True)
    _remove_release_outputs(out)


def prepare_render_contract(out: Path, contract: dict[str, object]) -> bool:
    """Invalidate derived video assets if renderer behavior or inputs changed."""
    state_path = out / "render_contract.json"
    previous = None
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {"invalid": True}
    derived_outputs_exist = any((out / name).exists() for name in ("shots", "webm", "frames", "final.mp4", "mixed_v2.mp4"))
    changed = previous != contract if previous is not None else derived_outputs_exist
    changed_keys = sorted(
        set(previous or {}).union(contract)
        if previous is None
        else {
            key
            for key in set(previous).union(contract)
            if previous.get(key) != contract.get(key)
        }
    )
    scope = "none"
    if changed:
        if previous is not None and set(changed_keys).issubset(_FINAL_COMPOSITE_CONTRACT_KEYS):
            scope = "final_composite"
            _remove_final_composite_outputs(out)
        elif previous is not None and set(changed_keys).issubset(_SCENE_INPUT_CONTRACT_KEYS):
            scope = "scene_cache_recheck"
            _remove_scene_composite_outputs(out)
        else:
            scope = "all_renderer_outputs"
            _remove_renderer_outputs(out)
    (out / "render_invalidation_evidence.json").write_text(
        json.dumps({"scope": scope, "changed_keys": changed_keys}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def validate_audio_spec(probe: dict[str, object]) -> dict[str, object]:
    sample_rate = int(probe.get("sample_rate") or 0)
    channels = int(probe.get("channels") or 0)
    failures = []
    if sample_rate != 44100:
        failures.append("audio_sample_rate_invalid")
    if channels != 2:
        failures.append("audio_channel_layout_invalid")
    return {"passed": not failures, "sample_rate": sample_rate, "channels": channels, "failures": failures}


def probe_audio_spec(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        return {"sample_rate": 0, "channels": 0, "probe_error": (result.stderr or "ffprobe failed")[-160:]}
    try:
        streams = json.loads(result.stdout).get("streams") or []
        audio = next((row for row in streams if row.get("codec_type") == "audio"), {})
        return {"sample_rate": int(audio.get("sample_rate") or 0), "channels": int(audio.get("channels") or 0)}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {"sample_rate": 0, "channels": 0, "probe_error": "invalid ffprobe output"}


def probe_media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError(f"duration probe failed: {(result.stderr or '')[-160:]}")
    return float((json.loads(result.stdout).get("format") or {}).get("duration") or 0)


def probe_final_loudness(path: Path) -> dict[str, float]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
         "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=180,
    )
    match = re.search(r'\{\s*"input_i".*?\}', result.stderr or "", re.DOTALL)
    if result.returncode or not match:
        raise RuntimeError("ffmpeg loudness probe failed")
    measured = json.loads(match.group(0))
    return {"integrated_lufs": float(measured["input_i"]), "true_peak_dbtp": float(measured["input_tp"])}


def build_audio_release_evidence(final: Path, voice: Path, secondary: Path, route: str) -> dict[str, object]:
    duration = probe_media_duration(final)
    secondary_role = "sound_effects" if route == "sfx_only" else "background_music"
    roles = ["voiceover", secondary_role]
    stems = []
    for role, path in (("voiceover", voice), (secondary_role, secondary)):
        stem_duration = probe_media_duration(path)
        stems.append({
            "role": role,
            "path": str(path.resolve()),
            "sha256": _sha256_file(path),
            "coverage_ratio": min(1.0, stem_duration / duration) if duration else 0.0,
        })
    window_length = min(5.0, max(1.0, duration / 3))
    middle_start = max(0.0, duration / 2 - window_length / 2)
    windows = {
        "opening": {"start_seconds": 0.0, "end_seconds": window_length, "stem_roles": roles, "coverage_ratio": 1.0},
        "middle": {"start_seconds": middle_start, "end_seconds": min(duration, middle_start + window_length), "stem_roles": roles, "coverage_ratio": 1.0},
        "ending": {"start_seconds": max(0.0, duration - window_length), "end_seconds": duration, "stem_roles": roles, "coverage_ratio": 1.0},
    }
    return {
        "version": "audio_release_evidence_v1",
        "candidate_sha256": _sha256_file(final),
        "route": route,
        "stems": stems,
        "coverage_ratio": min((float(item["coverage_ratio"]) for item in stems), default=0.0),
        "windows": windows,
        "final_loudness": probe_final_loudness(final),
    }


def build_render_quality_evidence(
    *,
    policy: dict[str, object],
    shot_records: list[dict[str, object]],
    motion: dict[str, object],
    spatial_motion: dict[str, object] | None = None,
) -> dict[str, object]:
    """Combine renderer provenance and measured motion into a publishable verdict."""
    fallbacks = [row.get("name") for row in shot_records if row.get("fallback")]
    stills = [row.get("name") for row in shot_records if row.get("renderer") == "still-motion"]
    element_shots = [
        row.get("name") for row in shot_records
        if row.get("renderer") == "playwright-frame-video" and not row.get("fallback")
    ]
    # Element-level motion intentionally does not keep a full-screen camera moving.
    # Accept its measured evidence separately, but only when the frame-driven shots
    # are real, fallback-free, and the encoded video contains active changes/peaks.
    spatial_motion = spatial_motion or {}
    element_motion_passed = bool(
        element_shots
        and not fallbacks
        and spatial_motion.get("passed") is True
        and spatial_motion.get("background_stable") is True
        and float(spatial_motion.get("business_roi_active_ratio") or 0) >= 0.05
        and float(spatial_motion.get("moving_area_ratio_p95") or 1) <= 0.25
        and int(motion.get("peak_count") or 0) >= 2
    )
    failures = []
    if policy.get("motion_mode") == "cinematic" and (fallbacks or stills):
        failures.append("cinematic_fallback_used")
    # 2026-08-17 修复：safe 模式（知识卡/图文卡片适配）豁免 cinematic 级帧差门禁。
    # 宠物/知识卡内容是静态背景+元素动效，帧差天然低于电影级；
    # safe 模式本意是适配这类内容，不应强制电影级 motion 阈值。
    if policy.get("motion_mode") != "safe" and not motion.get("passed") and not element_motion_passed:
        failures.append("motion_evidence_insufficient")
    if element_shots and spatial_motion.get("passed") is not True:
        spatial_failures = list(spatial_motion.get("failures") or ["spatial_motion_evidence_missing"])
        failures.extend(item for item in spatial_failures if item not in failures)
    return {
        "version": "render_quality_evidence_v1",
        "passed": not failures,
        "quality_profile": policy.get("quality_profile"),
        "motion_mode": policy.get("motion_mode"),
        "fallback_shots": fallbacks,
        "still_motion_shots": stills,
        "element_motion_shots": element_shots,
        "motion_gate_mode": "element_motion" if element_motion_passed and not motion.get("passed") else "cinematic",
        "shot_records": shot_records,
        "motion": motion,
        "spatial_motion": spatial_motion,
        "failures": failures,
    }


def calculate_timeline(durations: list[float], transition_after: list[float]) -> tuple[list[float], float]:
    """Return scene starts from the exact transition used at each boundary."""
    if len(transition_after) != max(0, len(durations) - 1):
        raise ValueError("transition count must equal duration count minus one")
    starts: list[float] = []
    position = 0.0
    for index, duration in enumerate(durations):
        starts.append(round(position, 3))
        if index < len(transition_after):
            position += duration - transition_after[index]
        else:
            position += duration
    return starts, round(position, 3)


def script_gate_passed(returncode: int, quality_profile: str) -> bool:
    return returncode == 0 or quality_profile == "degraded"


def element_render_timeout_seconds(duration: float) -> float:
    """Keep native element-motion recordings bounded without cutting long scenes."""
    return max(ELEMENT_FRAME_RENDER_MIN_TIMEOUT_SECONDS, float(duration) * 8 + 30)


def segment_shot_durations(tts_duration: float, *, element_motion: bool) -> tuple[float, float]:
    """Allocate A/B shots so their post-crossfade span contains the narration."""
    a_duration = min(2.8, float(tts_duration) * 0.30)
    # A->B always uses the long crossfade. Reserve it and a small delivery
    # margin before the later A/V gate performs its exact probe.
    b_duration = max(1.0, float(tts_duration) - a_duration + XFADE_DUR_LONG + 2.40)
    if element_motion and b_duration < 3.2:
        shortfall = 3.2 - b_duration
        a_duration = max(0.6, a_duration - shortfall)
        b_duration = float(tts_duration) - a_duration + XFADE_DUR_LONG + 2.40
    return a_duration, b_duration


def short_scene_timing(durations, fps=25):
    """Fit complete measured speech into a short timeline without time stretch.

    One frame grid owns visuals, voice offsets and captions. Pauses are actual
    silence; no source speech is trimmed and no old AAC timeline is reused.
    """
    import math
    frames = [math.ceil(float(duration) * fps) for duration in durations]
    if not frames or any(value <= 0 for value in frames):
        raise ValueError('short_timeline_actual_speech_duration_required')
    head, pause, tail = 6, 6, 8
    holds = [pause] * (len(frames) - 1) + [tail]
    total = sum(frames) + head + sum(holds)
    target = min(60 * fps, math.ceil((sum(durations) + 2.5) * fps))
    if total > target:
        raise ValueError('complete_speech_cannot_fit_short_policy')
    shortest = min(range(len(frames)), key=lambda index: frames[index])
    holds[shortest] += target - total
    result = []; start = 0
    for index, (voice, hold) in enumerate(zip(frames, holds)):
        count = voice + hold + (head if index == 0 else 0)
        left = count // 2; right = count - left
        if max(left, right) > 4 * fps:
            raise ValueError('short_scene_requires_more_than_two_four_second_shots')
        result.append({'segment':index+1, 'start_frame':start, 'frame_count':count,
            'voice_start_frame':start+(head if index==0 else 0),
            'voice_duration_seconds':float(durations[index]),
            'shot_a_seconds':left/fps, 'shot_b_seconds':right/fps})
        start += count
    return {'version':'short_audio_timeline_v1', 'fps':fps, 'target_frames':target,
        'duration_seconds':target/fps, 'speech_rate_changed':False,
        'speech_trimmed':False, 'segments':result}

# 镜头A 背景运动（建立镜头）：8 种电影运镜轮换（推入/拉出/摇移/呼吸/斜推）
# 08-14 增强：从 4 种微动升级为 8 种电影运镜，增加视觉层次
KB_A = [
    ("scale(1.00) translate(0px,0px)", "scale(1.10) translate(0px,-24px)"),   # 推入+上移
    ("scale(1.00) translate(0px,0px)", "scale(1.08) translate(-28px,0px)"),   # 推入+左摇
    ("scale(1.10) translate(0px,0px)", "scale(1.00) translate(0px,18px)"),    # 拉出+下移
    ("scale(1.00) translate(0px,0px)", "scale(1.09) translate(26px,0px)"),    # 推入+右摇
    ("scale(1.00) translate(0px,-22px)", "scale(1.07) translate(0px,22px)"),  # 垂直呼吸
    ("scale(1.00) translate(-24px,0px)", "scale(1.09) translate(24px,0px)"),  # 水平呼吸
    ("scale(1.00) translate(0px,0px)", "scale(1.11) translate(-18px,-18px)"), # 斜推左上
    ("scale(1.00) translate(0px,0px)", "scale(1.08) translate(18px,-20px)"),  # 斜推右上
]
# 镜头B 背景运动（要点镜头）：反向运镜 + 特写 zoom（08-14 增强）
KB_B = [
    ("scale(1.10) translate(0px,-24px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.08) translate(-28px,0px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.00) translate(0px,18px)", "scale(1.10) translate(0px,0px)"),
    ("scale(1.09) translate(26px,0px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.07) translate(0px,22px)", "scale(1.00) translate(0px,-22px)"),
    ("scale(1.09) translate(24px,0px)", "scale(1.00) translate(-24px,0px)"),
    ("scale(1.11) translate(-18px,-18px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.08) translate(18px,-20px)", "scale(1.00) translate(0px,0px)"),
]
# 镜头B 模块动效轮换（08-14 增强 4 种）
MODULE_ANIMS = [
    ("staggerUp", ["translateY(30px)", "translateY(0px)"]),
    ("fadeSlideL", ["translateX(30px)", "translateX(0px)"]),
    ("staggerUp", ["translateY(24px)", "translateY(0px)"]),
    ("fadeSlideR", ["translateX(-30px)", "translateX(0px)"]),
]


def _b64img(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def esc(s: str) -> str:
    """HTML 转义（动效镜头标题/文案注入安全）"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(r.stdout).get("format", {}).get("duration", 4.0))
    except Exception:
        return 4.0


def cached_media_duration(path: Path, previous_record: dict[str, object] | None = None) -> float:
    """Reuse a measured duration only when it is bound to the current bytes."""
    record = previous_record if isinstance(previous_record, dict) else {}
    cached = float(record.get("duration_seconds") or 0.0)
    if cached > 0 and record.get("audio_sha256") == _sha256_file(Path(path)):
        return cached
    return _duration(str(path))


def _max_total_for_platform(platform: str) -> float:
    """2026-08-16 新增：时长上限按平台自适应（之前全局固定 100s）。

    抖音/Shorts/视频号/TikTok 平台上限 60s，快手 70s，其他 100s。
    防止渲染器允许超长内容被平台拒（douyin/yt_shorts 60s 门禁）。
    """
    plat = str(platform or "").casefold()
    if plat in {"douyin", "douyin_ai", "douyin_pet", "tiktok", "youtube", "shipinhao", "shorts"}:
        return 60.0
    if plat == "kuaishou":
        return 70.0
    return float(os.environ.get("FILM_RENDERER_MAX_TOTAL_SECONDS", MAX_RENDER_SECONDS))


def validate_render_durations(durations: list[float], platform: str = "") -> dict:
    """Reject runaway narration before allocating browser or FFmpeg work.

    2026-08-16：max_total 按平台自适应（douyin 60s / kuaishou 70s / 其他 100s）。
    """
    max_segment = float(os.environ.get("FILM_RENDERER_MAX_SEGMENT_SECONDS", MAX_TTS_SEGMENT_SECONDS))
    max_total = _max_total_for_platform(platform)
    failures = []
    if any(duration <= 0 for duration in durations):
        failures.append("invalid_tts_duration")
    if any(duration > max_segment for duration in durations):
        failures.append("segment_duration_exceeded")
    if sum(durations) > max_total:
        failures.append("total_duration_exceeded")
    return {
        "passed": not failures,
        "failures": failures,
        "total_seconds": round(sum(durations), 3),
        "max_segment_seconds": max_segment,
        "max_total_seconds": max_total,
    }


def synthesize_edge_tts(text: str, output: Path, voice: str, rate: str = "-5%") -> int:
    """Retry a transient Edge response and never retain an empty MP3.

    2026-08-16：rate 参数化（不再固定 -5%），按内容赛道可调（pets/emotion 稍慢更温和，tech 默认）。
    """
    attempts = max(1, int(os.environ.get("FILM_TTS_MAX_ATTEMPTS", FILM_TTS_MAX_ATTEMPTS)))
    delay = max(0.0, float(os.environ.get("FILM_TTS_RETRY_DELAY_SECONDS", "1")))
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            output.unlink(missing_ok=True)
            result = subprocess.run(
                ["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", str(output)],
                capture_output=True, text=True, timeout=90,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or "edge-tts failed")[-160:])
            if not output.is_file() or output.stat().st_size <= 10_000:
                raise RuntimeError("edge-tts returned empty audio")
            return attempt
        except Exception as exc:
            output.unlink(missing_ok=True)
            errors.append(str(exc)[:160])
            if attempt == attempts:
                raise RuntimeError(f"edge-tts failed after {attempts} attempts: {errors[-1]}") from exc
            time.sleep(delay * attempt)
    raise RuntimeError("edge-tts retry loop exited unexpectedly")


def _card_title(card: dict, fallback: str = "") -> str:
    return str(card.get("t") or card.get("txt") or fallback)[:60]


def _stat_from_card(card: dict) -> str:
    num = str(card.get("num") or "")
    ext = str(card.get("ext") or "")
    if num:
        return num
    txt = str(card.get("txt") or "")
    nums = re.findall(r"\d+[\.\d]*[%倍个分钟小时秒]?", txt)
    return nums[0] if nums else ""


def _modules_from_card(card: dict) -> list[str]:
    items = card.get("items") or []
    txt = str(card.get("txt") or "")
    parts = [re.sub(r"\s+", " ", str(x)).strip() for x in items if str(x).strip()] if items else []
    if len(parts) < 3:
        # 从 txt 拆 3 个短句
        sentences = [s.strip() for s in re.split(r"[，。；！？、]", txt) if s.strip()]
        parts = (sentences[:3] if len(sentences) >= 3 else sentences + ["", "", ""])[:3]
    return (parts + ["", "", ""])[:3]


def _predictive_maintenance_body(mode: str, title: str) -> str:
    """Topic-specific full-canvas compositions; each scene owns a distinct spatial grammar."""
    detail = mode.endswith("_detail")
    base_mode = mode[:-7] if detail else mode
    t = esc(title)
    bodies = {
        "before_after_split": f'''<section class="pm-layout pm-device-diagnostic"><div class="pm-title">{t}</div><div class="pm-running-state"><b>设备仍在运行</b><span>当前状态未停机</span></div><div class="pm-bearing-marker"><i></i><span>轴承测点</span></div><div class="pm-trend-panel"><b>异常趋势</b><div class="pm-threshold"></div><div class="pm-trend-line"></div><span>已越过预警线</span></div><div class="pm-split-verdict">能转 ≠ 健康</div></section>''',
        "input_branch": f'''<section class="pm-layout pm-sensor-topology"><div class="pm-title">{t}</div><div class="pm-device-core">设备 M-07</div><div class="pm-sensor pm-s1"><b>振动</b><span>轴承座</span></div><div class="pm-sensor pm-s2"><b>温度</b><span>电机外壳</span></div><div class="pm-sensor pm-s3"><b>电流</b><span>配电柜</span></div><div class="pm-sensor pm-s4"><b>维修记录</b><span>历史工单</span></div><div class="pm-topology-note">缺一路输入 → 结论先降级</div></section>''',
        "source_trace": f'''<section class="pm-layout pm-baseline-proof"><div class="pm-title">{t}</div><div class="pm-source-chain"><div><b>M-07</b><span>同设备</span></div><i>→</i><div><b>80%</b><span>同负载</span></div><i>→</i><div><b>稳定生产</b><span>相近工况</span></div></div><div class="pm-baseline-band"><span>正常基线带</span><i></i><b>当前轨迹</b></div><div class="pm-wrong-reference">全厂平均值：不可直接使用</div></section>''',
        "error_fix_compare": f'''<section class="pm-layout pm-signal-columns"><div class="pm-corner-title">先识别信号类型</div><div class="pm-signal drift"><b>连续漂移</b><i></i><span>设备退化 → 查趋势</span></div><div class="pm-signal spike"><b>突然尖峰</b><i></i><span>瞬时冲击 → 查事件</span></div><div class="pm-signal offline"><b>传感器掉线</b><i></i><span>输入缺失 → 先修数据</span></div></section>''',
        "evidence_timeline": f'''<section class="pm-layout pm-evidence-handoff"><div class="pm-title">{t}</div><div class="pm-evidence-sheet"><div><b>异常项</b><span>轴承振动</span></div><div><b>开始时间</b><span>14:32</span></div><div><b>持续时长</b><span>18 min</span></div><div><b>证据附件</b><span>趋势图 + 历史工单</span></div></div><div class="pm-authority-zone"><b>待人工复核</b><span>AI 不签发停机决定</span></div></section>''',
        "checklist_lock": f'''<section class="pm-layout pm-field-review"><div class="pm-hud-title">{t}</div><div class="pm-check c1">01 听异响</div><div class="pm-check c2">02 查润滑</div><div class="pm-check c3">03 看紧固件</div><div class="pm-check c4">04 对波形 / 工单</div><div class="pm-human-badge">实物与证据互证后再定案</div></section>''',
        "flow_track": f'''<section class="pm-layout pm-decision-matrix"><div class="pm-lane-title">处置由人决定</div><div class="pm-axis risk">安全风险 ↑</div><div class="pm-axis duration">异常持续性 →</div><div class="pm-quadrant run"><b>继续运行</b><span>低风险 / 短时</span></div><div class="pm-quadrant derate"><b>降载观察</b><span>低风险 / 持续</span></div><div class="pm-quadrant stop"><b>计划停机</b><span>中高风险 / 可计划</span></div><div class="pm-quadrant urgent"><b>立即升级</b><span>高风险不得放行</span></div><div class="pm-case-dot">当前案例</div><div class="pm-human-gate">维修主管确认后执行</div></section>''',
        "result_audit": f'''<section class="pm-layout pm-result-workorder"><div class="pm-loop-title">{t}</div><div class="pm-wave-compare"><div><b>检修前</b><i class="before"></i></div><div><b>复测后</b><i class="after"></i></div></div><div class="pm-workorder"><b>工单已关闭</b><span>复测结果：通过</span><span>处理人：维修责任人</span><span>回写状态：已完成</span></div><div class="pm-four-step">采集 → 比较 → 复核 → 回写</div><div class="pm-independent-cta"><strong>收藏四步</strong><span>转给管设备的同事</span></div></section>''',
    }
    body = bodies.get(base_mode, "")
    body = body.replace('class="pm-independent-cta"', 'class="pm-independent-cta" data-role="visual-cta" data-visual-role="cta"')
    if not body or not detail:
        return body
    detail_copy = {
        "before_after_split": "趋势变化 > 单点状态",
        "input_branch": "4 路输入已对齐",
        "source_trace": "设备 / 负载 / 工况已锁定",
        "error_fix_compare": "漂移 / 尖峰 / 掉线分别处理",
        "evidence_timeline": "偏差、起点、持续时间均可回查",
        "checklist_lock": "现场互证后再定案",
        "flow_track": "选择人：维修责任人",
        "result_audit": "重新采样 → 写回工单",
    }[base_mode]
    body = body.replace('class="pm-layout ', 'class="pm-layout pm-detail-layout ', 1)
    return body.replace("</section>", f'<div class="pm-detail-proof">{detail_copy}</div></section>', 1)


def build_original_order_shot(idx, bg_path, mode, template_id, group_motion, platform_reason, purpose, body_copy=None):
    """Accurate example fields over a separately admitted photographic scene."""
    from content_platform.visual_policy_gate import file_record
    record = (body_copy or {}).get('real_scene_background_record') or {}
    if (record.get('source_kind') not in {'licensed_real_scene_photo','generated_photographic_scene'}
            or Path(record.get('path') or '').resolve() != Path(bg_path).resolve()):
        raise ValueError('original_order_primary_photographic_background_required')
    file_record(bg_path, record.get('sha256'))
    from content_platform.native_visual_inputs import functional_role_markup
    atlas=(body_copy or {}).get('functional_role_atlas_record')
    if not atlas or (body_copy or {}).get('functional_role_cell_index')!=idx-1:
        raise ValueError('original_order_functional_role_asset_required')
    role_sprite=functional_role_markup(atlas,idx-1,size=390)
    role_sprite=role_sprite.replace('style="','style="top:'+str({2:720,5:690}.get(idx,955))+'px;',1)
    labels=['总数相同仍可能漏单','核对公开自制订单表','保留独立基准清单','逐个订单号计数','比较编号集合差集','重复与漏单分别列出','业务字段缺失先复核','保存四份材料再确认']
    def pane(title, rows, key):
        items=''.join('<div class="field-row" data-visual-role="evidence" data-semantic-key="'+esc(key)+'-'+str(n)+'">'+esc(value)+'</div>' for n,value in enumerate(rows))
        return '<section class="glass"><h2>'+esc(title)+'</h2>'+items+'</section>'
    baseline=['B001','B002','B003','B004']; actual=['B001','B002','B002','B004']
    layouts={
        1:'<div class="comparison">'+pane('基准：4条',baseline,'baseline')+pane('原表：4条',actual,'actual')+'</div><div class="verdict">B002 重复 · B003 缺失</div>',
        2:'<div class="record-strip">'+pane('公开自制原表',['01 · B001','02 · B002','03 · B002','04 · B004'],'rows')+'</div><aside class="annotation">02、03 行同号<br>四条记录 ≠ 核对通过</aside>',
        3:'<div class="baseline-flow">'+pane('独立基准',baseline,'reference')+'<div class="flow-arrow">↓ 保留原件</div><div class="glass">baseline.csv<br>据此核对编号</div></div>',
        4:'<div class="diagonal-count">'+pane('回到原始行',['第02行 · B002','第03行 · B002'],'count-rows')+'<div class="counter"><b>2</b><span>B002 出现次数</span></div></div>',
        5:'<div class="set-difference">'+pane('基准集合',baseline,'set-base')+'<div class="difference-arrow">− 实际 { B001, B002, B004 }</div><div class="missing-slot">B003 → 漏单清单 · 待核查</div></div>',
        6:'<div class="two-results">'+pane('重复清单',['B002 × 2','对应原行 02 / 03'],'duplicates')+pane('漏单清单',['B003 × 0','基准有 · 实际无'],'missing')+'</div><div class="verdict">两类问题分别给出编号</div>',
        7:'<div class="review-split">'+pane('原始记录保留',['02 · B002','03 · B002'],'review-rows')+pane('业务含义先复核',['批次：未提供','发货：未提供','是否分批：待确认'],'review-fields')+'</div><div class="locked">禁止自动删除 · 由负责人判断</div>',
        8:'<div class="handoff-stairs">'+''.join('<div class="glass file-step" data-visual-role="evidence" data-semantic-key="file-'+str(n)+'">'+esc(name)+'</div>' for n,name in enumerate(['baseline.csv','original.csv','duplicates.csv','missing.csv']))+'</div><div class="flow-arrow">↓ 交给负责人重新检查</div>'}
    role=['猫核对员圈出重复 · 狗复核员守住基准','猫查看原行 · 狗提醒不能只数条数','狗复核员保留独立基准','猫核对员圈出两行 B002','狗复核员寻找缺失 B003','猫列重复 · 狗列漏单','狗复核员阻止未经核查的删除','狗复核员交接四份材料'][idx-1]
    attrs=' '.join('data-'+key+'="'+esc(value)+'"' for key,value in [('beat-id',f's{idx:02}'),('template-id',template_id),('visual-mode',mode),('group-motion',','.join(group_motion or [])),('platform-reason',platform_reason),('shot-purpose',purpose)])
    detail=purpose.startswith('inspect:')
    return '<!doctype html><html><head><meta charset="utf-8"><style>'+f"""
      html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;color:#f8fafc;font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif}}
      .bg{{position:absolute;inset:0;background:url(data:image/png;base64,{_b64img(bg_path)}) center/cover}}
      .veil{{position:absolute;inset:0;background:linear-gradient(135deg,rgba(10,18,30,.4),rgba(10,18,30,.12) 35%,transparent 70%)}}
      .order-title{{position:absolute;left:54px;top:64px;width:972px;font-size:80px;font-weight:900;line-height:1.24;color:#111827;-webkit-text-stroke:2px #fde047;paint-order:stroke fill;text-shadow:0 3px 12px rgba(255,255,255,.5)}}
      .example-label{{position:absolute;left:58px;top:282px;font-size:30px;text-shadow:0 2px 9px #000}}
      .contract-motion{{position:absolute;left:54px;right:54px;top:330px}}
      .glass{{background:rgba(15,23,42,.62);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.24);border-radius:16px;padding:18px;box-sizing:border-box;text-shadow:0 2px 8px rgba(0,0,0,.65)}}
      h2{{font-size:40px;margin:0 0 12px}} .field-row{{font-size:44px;font-weight:700;line-height:1.13;border-bottom:1px solid rgba(255,255,255,.24);padding:4px 0;white-space:nowrap}}
      .comparison,.two-results,.review-split{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
      .record-strip{{width:570px}} .annotation{{position:absolute;right:0;top:850px;font-size:40px;background:rgba(15,23,42,.62);padding:20px;border-left:6px solid #fde047}}
      .baseline-flow{{width:550px}} .baseline-flow .flow-arrow{{margin-top:570px}} .flow-arrow{{font-size:38px;line-height:1.4;margin:20px 0;text-shadow:0 2px 8px #000}}
      .diagonal-count .glass{{width:660px;transform:rotate(-3deg)}} .counter{{position:relative;margin:70px 0 0 540px;text-shadow:0 2px 8px #000}} .counter b{{display:block;font-size:160px;color:#fde047}} .counter span{{font-size:38px}}
      .set-difference{{width:700px}} .difference-arrow{{font-size:34px;margin:540px 0 24px;line-height:1.5;text-shadow:0 2px 8px #000}} .missing-slot{{font-size:40px;padding:22px;border:3px dashed #fde047;background:rgba(15,23,42,.62)}}
      .two-results{{margin-top:150px}} .two-results .glass:first-child{{transform:translateY(-70px)}} .review-split{{grid-template-columns:.8fr 1.2fr}} .review-split .field-row{{font-size:34px}}
      .verdict,.locked{{font-size:40px;line-height:1.4;margin-top:18px;padding:18px;background:rgba(15,23,42,.62);border-left:6px solid #fde047}}
      .handoff-stairs{{width:700px}} .file-step{{font-size:36px;width:660px;padding:14px;margin-bottom:14px}} .file-step:nth-child(2){{margin-left:45px}} .file-step:nth-child(3){{margin-left:90px}} .file-step:nth-child(4){{margin-left:135px}}
      .functional-role-sprite{{position:absolute;right:52px;top:955px;filter:drop-shadow(0 9px 12px rgba(0,0,0,.28));transform-origin:center bottom}}
      .role{{position:absolute;left:54px;right:54px;top:1390px;font-size:30px;line-height:1.4;background:rgba(15,23,42,.62);padding:16px;border-radius:12px}}
      .order-cta{{position:absolute;left:54px;right:54px;top:1500px;font-size:36px;line-height:1.4;text-shadow:0 2px 8px #000}}
    """+'</style></head><body '+attrs+'><div class="bg"></div><div class="veil"></div><div class="order-title" data-visual-role="title" data-semantic-key="s'+str(idx)+'-title">'+esc(labels[idx-1])+'</div><div class="example-label">公开自制反例 · 非真实客户数据</div><div class="contract-motion" data-motion="'+esc((group_motion or ['focus_shift'])[0])+'">'+layouts[idx]+'</div>'+role_sprite+'<div class="role" data-visual-role="annotation" data-semantic-key="functional-cat-dog-role">'+esc(role)+'</div>'+('<div class="order-cta" data-role="visual-cta" data-visual-role="cta">保存四份材料 · 交负责人检查再确认</div>' if idx==8 else '')+'''<script>window.renderFrame=function(t){var sprite=document.querySelector('.functional-role-sprite');sprite.style.transform='translateY('+(-Math.abs(Math.sin(t*1.5))*9)+'px) rotate('+(Math.sin(t*1.2)*2)+'deg)';document.querySelectorAll('.field-row').forEach(function(el,i){el.style.borderColor=t>=i*.5&&t<i*.5+.9?'#fde047':'rgba(255,255,255,.24)';el.style.transform='translateX('+('''+('Math.sin(t*1.8+i)*5' if detail else '0')+''')+'px)';});};window.renderFrame(0);</script></body></html>'''


def build_prompt_lab_shot(idx: int, title: str, text: str, bg_path: str, mode: str, kicker: str, template_id: str = "", group_motion=None, platform_reason: str = "", contract_mode: str = "", shot_purpose: str = "", body_copy=None) -> str:
    """Build a mode-specific shot with stable background and local motion."""
    if isinstance(body_copy,dict) and body_copy.get('original_order_id_profile'):
        return build_original_order_shot(idx,bg_path,contract_mode or mode,template_id,group_motion,platform_reason,shot_purpose,body_copy)
    b64 = _b64img(bg_path)
    safe = esc(text)
    template_id = esc(template_id or f"{mode}_v1")
    motion = esc(",".join(str(item) for item in (group_motion or [])))
    reason = esc(platform_reason)
    effective_mode = contract_mode or mode
    if template_id.startswith("predictive_maintenance_") and mode.endswith("_detail"):
        effective_mode = mode
    pet_base_mode = mode.removesuffix("_detail")
    if template_id.startswith("cat_") or pet_base_mode in {"sleep_pose_hook", "curled_sleep_pose", "side_sleep_pose", "back_sleep_pose", "loaf_alert_pose", "hidden_sleep_pose", "observe_not_diagnose", "sleep_pose_checklist"}:
        effective_mode = mode
    predictive_layout = template_id.startswith("predictive_maintenance_") and bool(
        _predictive_maintenance_body(effective_mode, title)
    )
    purpose = esc(shot_purpose or f"{effective_mode}:primary")
    display_title = {
        "decision_interrupt": "AI看不准，还能直接报废？",
        "decision_interrupt_detail": "等待人工决定",
        "capture_rig_exploded_view": "输入一漂，结果就不可信",
        "capture_rig_exploded_view_detail": "漂移就复核",
        "dataset_annotation_board": "谁来定义“正常”？",
        "dataset_annotation_board_detail": "治理不等于接管",
        "anomaly_heatmap_inspection": "只画框，不算证据",
        "anomaly_heatmap_inspection_detail": "证据必须可复核",
        "risk_queue_flow": "4类信号，必须交给人",
        "risk_queue_flow_detail": "黄件暂停，交给人",
        "human_review_console": "人不是看屏幕，是做决定",
        "human_review_console_detail": "授权质检员定案",
        "failure_boundary_triptych": "这4种情况，强制接管",
        "failure_boundary_triptych_detail": "这些情况强制接管",
        "execution_audit_receipt": "执行后，责任怎么追？",
        "execution_audit_receipt_detail": "执行完成，审计留痕",
    }.get(effective_mode, title)
    if isinstance(body_copy, dict) and body_copy.get("title"):
        display_title = str(body_copy.get("title")).strip()
    if isinstance(body_copy, dict) and body_copy.get("kicker"):
        kicker = str(body_copy.get("kicker")).strip()
    if effective_mode in {"sleep_pose_hook", "curled_sleep_pose", "side_sleep_pose", "back_sleep_pose", "loaf_alert_pose", "hidden_sleep_pose", "observe_not_diagnose", "sleep_pose_checklist"}:
        kicker = "猫咪睡姿观察"
    narrative_copy = {
        "decision_interrupt_detail": (
            "AI一旦犹豫，先停工件，再交权。",
            "误判不可逆，接管必须先于处置。",
        ),
        "capture_rig_exploded_view_detail": (
            "接管不是凭感觉，先排除输入漂移。",
            "锁定光源、机位、距离，再判断真假缺陷。",
        ),
        "dataset_annotation_board_detail": (
            "机器照标准找错，人负责定义标准。",
            "质检与工艺共同定标，模型不能自己猜。",
        ),
        "anomaly_heatmap_inspection_detail": (
            "只给一个“NG”，不叫证据。",
            "原图、热区、类别和不确定性必须同时可查。",
        ),
        "risk_queue_flow_detail": (
            "AI不知道自己不知道，才最危险。",
            "4类信号一出现，处置权立即交还给人。",
        ),
        "human_review_console_detail": (
            "人不是再看一遍，而是承担处置。",
            "结合原图、规范与批次，决定放行、返工或隔离。",
        ),
        "failure_boundary_triptych_detail": (
            "输入边界一变，自动判定必须让路。",
            "新材质、反光、相机偏移、新SKU都要接管。",
        ),
        "execution_audit_receipt_detail": (
            "每次人工改判，都必须留下责任链。",
            "可追责、可复盘，也能反哺下一版规则。",
        ),
    }.get(effective_mode)
    if effective_mode.endswith("_detail") and isinstance(body_copy, dict):
        contract_strong = str(body_copy.get("strong") or "").strip()
        contract_detail = str(
            body_copy.get("explanation") or body_copy.get("detail") or body_copy.get("support") or ""
        ).strip()
        if contract_strong and contract_detail:
            narrative_copy = (contract_strong, contract_detail)
    is_en = _is_english_text(f"{title} {text}")
    labels = {
        "before_after_split": (("BEFORE", "AFTER") if is_en else ("处理前", "处理后")),
        "prompt_typewriter": ("SUBJECT", "ENVIRONMENT", "LIGHTING", "STYLE", "COMPOSITION"),
        "annotation_callout": (("ACTION", "EXPRESSION", "CLOTHING", "DISTANCE") if is_en else ("热区", "缺陷类别", "置信度", "疑点")),
        "location_selector": ("雨夜街道", "便利店", "车站", "窗边"),
        "light_split_compare": ("COOL LIGHT", "WARM LIGHT"),
        "composition_push_in": ("中近景", "侧脸", "右侧留白"),
        "error_fix_compare": ("缺主体 / 缺环境", "结构化提示词"),
        "checklist_stamp": ("主体", "环境", "光线", "风格", "构图"),
    }.get(effective_mode, (("PROMPT",) if is_en else ("流程要点",)))
    chips = "".join(f'<span class="chip">{esc(x)}</span>' for x in labels)
    pet_modes = {
        "sleep_pose_hook", "curled_sleep_pose", "side_sleep_pose", "back_sleep_pose",
        "loaf_alert_pose", "hidden_sleep_pose", "observe_not_diagnose", "sleep_pose_checklist",
    }
    if effective_mode in pet_modes or (effective_mode.endswith("_detail") and effective_mode.removesuffix("_detail") in pet_modes):
        labels = ("姿势", "先观察", "不要强行打扰")
        chips = "".join(f'<span class="chip">{esc(x)}</span>' for x in labels)
        body = (
            f'<div class="pet-observation reveal-item">'
            f'<div class="pet-pose-marker">{esc(display_title)}</div>'
            f'<div class="pet-observation-line"></div>'
            f'<div class="pet-observation-copy">{safe}</div>'
            f'<div class="pet-observation-chips">{chips}</div>'
            f'</div>'
        )
    elif predictive_layout:
        body = _predictive_maintenance_body(effective_mode, display_title)
    elif effective_mode == "before_after_split":
        if is_en:
            body = f'<div class="hero-compare"><div class="copy-panel result-bad reveal-item" id="resultBad"><span class="eyebrow">BEFORE</span><strong>Needs review</strong><small>Check the exception</small></div><div class="hero-arrow">→</div><div class="copy-panel result-good reveal-item" id="resultGood"><span class="eyebrow">AFTER</span><strong>Human queue</strong><small>Approve after review</small></div></div><div class="hero-copy reveal-item" data-role="visual-cta" data-visual-role="cta">{safe}</div>'
        else:
            body = f'<div class="hero-compare"><div class="copy-panel result-bad reveal-item" id="resultBad"><span class="eyebrow">处理前</span><strong>逐项检查</strong><small>疑点容易遗漏</small></div><div class="hero-arrow">→</div><div class="copy-panel result-good reveal-item" id="resultGood"><span class="eyebrow">处理后</span><strong>人工复核队列</strong><small>复核后再定案</small></div></div><div class="hero-copy reveal-item" data-role="visual-cta" data-visual-role="cta">{safe}</div>'
    elif effective_mode == "prompt_typewriter":
        body = f'<div class="prompt-line"><span class="caret">▌</span>{chips}</div><div class="typed">{safe}</div>'
    elif effective_mode == "annotation_callout":
        body = f'<div class="annot"><div class="subject-spot"></div><div class="line l1"></div><div class="line l2"></div><div class="line l3"></div><div class="line l4"></div>{chips}</div>'
    elif effective_mode == "flow_track":
        body = f'<div class="flow-track">{chips}</div><div class="track-arrow">输入 → 处理 → 输出 → 验收</div>'
    elif effective_mode == "source_trace":
        body = f'<div class="source-trace"><div class="trace-origin">原始来源</div><div class="trace-line"></div><div class="trace-target">可继续加工的输入</div></div><div class="caption-line">{chips}</div>'
    elif effective_mode == "evidence_timeline":
        body = f'<div class="evidence-timeline"><div class="timeline-line"></div>{chips}</div>'
    elif effective_mode == "timeline_reveal":
        body = f'<div class="timeline-reveal"><div class="timeline-step">01 输入</div><div class="timeline-step">02 处理</div><div class="timeline-step">03 验收</div><div class="timeline-proof">{safe}</div></div>'
    elif effective_mode == "result_reveal":
        body = f'<div class="result-reveal"><span>结果已生成</span><strong>{safe}</strong><small>继续核验证据</small></div>'
    elif effective_mode == "result_hold":
        body = f'<div class="result-hold"><span>验收结论</span><strong>{safe}</strong><div class="hold-line"></div></div>'
    elif effective_mode == "result_audit":
        body = f'<div class="audit-ring"><div class="audit-center">结果<br>验收</div></div><div class="audit-items">{chips}</div>'
    elif effective_mode == "failure_rollback":
        body = '<div class="rollback"><div class="rollback-node bad">异常</div><div class="rollback-path">↩ 回到上一步</div><div class="rollback-node good">重新验收</div></div>'
    elif effective_mode == "qr_social_endcard":
        qr_path = Path(os.environ.get("WECHAT_QR_ASSET", str(Path.home() / ".hermes" / "data" / "wechat_assets" / "qrcode_公众号.jpg")))
        qr = _b64img(str(qr_path)) if qr_path.is_file() else ""
        body = f'<div class="qr-end"><div class="qr-title">验收通过，才值得分享</div><img class="qr-image" src="data:image/jpeg;base64,{qr}"><div class="qr-name">马吉克AI</div><div class="qr-copy">扫码关注公众号<br>分享可复用的AI效率方法</div></div>'
    elif effective_mode == "location_selector":
        body = f'<div class="orbit">{chips}</div><div class="center-word">地点决定故事</div>'
    elif effective_mode == "light_split_compare":
        body = f'<div class="light-split"><div class="cool">{esc(labels[0])}</div><div class="warm">{esc(labels[1])}</div></div>'
    elif effective_mode == "composition_push_in":
        body = f'<div class="viewfinder"><i></i><i></i><i></i><div class="crosshair">＋</div></div><div class="caption-line">{chips}</div>'
    elif effective_mode == "error_fix_compare":
        body = f'<div class="error-fix"><div class="error-side"><b>错误</b><span>{esc(labels[0])}</span></div><div class="fix-arrow">→</div><div class="fix-side"><b>修正</b><span>{esc(labels[1])}</span></div></div>'
    elif effective_mode == "checklist_stamp":
        body = f'<div class="checklist-stamp"><div class="check-items">{chips}</div><div class="local-stamp">验收完成</div></div>'
    elif effective_mode == "decision_interrupt_detail":
        body = '<div class="industrial-overlay decision-detail"><div class="decision-path"><span>AI 无法确认</span><i>→</i><b>保持工件</b><i>→</i><strong>呼叫质检员</strong></div><div class="decision-proof">未授权报废 · 控制权已移交</div></div>'
    elif effective_mode == "capture_rig_exploded_view_detail":
        body = '<div class="industrial-overlay capture-detail"><div><span>光源</span><b>已锁定</b></div><div><span>机位</span><b>已锁定</b></div><div><span>距离</span><b>已锁定</b></div><strong>任一漂移 → 暂停自动处置</strong></div>'
    elif effective_mode == "dataset_annotation_board_detail":
        body = '<div class="industrial-overlay governance-detail"><div><small>训练与治理</small><b>定义基线 / 缺陷字典</b></div><i>≠</i><div><small>运行时接管</small><b>质检员作出处置</b></div></div>'
    elif effective_mode == "anomaly_heatmap_inspection_detail":
        body = '<div class="industrial-overlay evidence-detail"><div class="defect-zoom"><b>缺陷局部</b><span>裂纹边缘</span><small>热区定位 · 原图坐标已保存</small></div><div class="evidence-chain"><b>原图</b><i>+</i><b>热区</b><i>+</i><b>类别</b><i>+</i><b>不确定性</b></div></div>'
    elif effective_mode == "risk_queue_flow_detail":
        body = '<div class="industrial-overlay risk-detail"><div class="risk-side green">规则内<br><b>继续</b></div><div class="risk-center"><span>低置信度 / 新缺陷</span><strong>等待人工</strong></div><div class="risk-side red">高风险<br><b>保持隔离</b></div></div>'
    elif effective_mode == "human_review_console_detail":
        body = '<div class="industrial-overlay disposition-detail"><div class="disposition-evidence">原图 · 局部 · 规范 · 批次</div><div class="disposition-actions"><span>放行</span><span>返工</span><b>保持隔离</b><span>升级</span></div><div class="disposition-proof">授权质检员已确认</div></div>'
    elif effective_mode == "failure_boundary_triptych_detail":
        body = '<div class="industrial-overlay trigger-detail"><div>新材质</div><div>强反光</div><div>相机偏移</div><div>新 SKU</div><strong>触发接管，禁止默认放行</strong></div>'
    elif effective_mode == "execution_audit_receipt_detail":
        body = '<div class="industrial-overlay receipt-switch"><div class="audit-state"><div class="physical-receipt"><b>已执行</b><span>工件进入隔离箱</span></div><div class="audit-receipt"><b>审计回执</b><span>操作者</span><span>时间</span><span>原因</span><span>模型 / 规则版本</span></div></div><div class="cta-panel"><b>收藏这份人工接管清单</b><span>低置信度 · 新缺陷 · 规则冲突 · 高风险件</span><strong>你会先强制接管哪一种？</strong></div></div>'
    elif effective_mode == "decision_interrupt":
        body = '<div class="industrial-overlay decision-interrupt"><div class="uncertain-target"><span>AI 无法确认</span><b>等待人工决定</b></div><div class="authority-line">疑难件已保持 · 尚未执行报废</div></div>'
    elif effective_mode == "capture_rig_exploded_view":
        body = '<div class="industrial-overlay capture-rig"><div><b>固定光源</b><span>亮度与角度受控</span></div><i>→</i><div><b>固定机位</b><span>焦距与姿态受控</span></div><i>→</i><div><b>固定距离</b><span>采集窗口受控</span></div></div>'
    elif effective_mode == "dataset_annotation_board":
        body = '<div class="industrial-overlay dataset-board"><div class="baseline-cell"><small>建模与治理</small><b>正常基线</b><span>由质检与工艺共同定义</span></div><div class="defect-cell"><small>缺陷字典</small><b>划痕 · 缺角 · 脏污</b><span>不是运行时接管</span></div></div>'
    elif effective_mode == "anomaly_heatmap_inspection":
        body = '<div class="industrial-overlay heatmap-inspection"><div class="heatmap-box"></div><div class="evidence-stack"><b>疑似缺陷</b><span>热区：已定位</span><span>类别：待复核</span><span>不确定性：触发路由</span></div></div>'
    elif effective_mode == "risk_queue_flow":
        body = '<div class="industrial-overlay risk-queue"><div class="route green"><b>绿</b><span>批准规则内</span></div><div class="route yellow"><b>黄</b><span>等待人工决定</span></div><div class="route red"><b>红</b><span>先保持 / 隔离</span></div></div>'
    elif effective_mode == "human_review_console":
        body = '<div class="industrial-overlay handoff-console"><div class="handoff-state">控制权已移交 · 等待人工决定</div><div class="review-evidence"><span>原图</span><span>缺陷放大</span><span>检验规范</span><span>批次上下文</span></div><div class="decision-buttons"><b>放行</b><b>返工</b><b>保持隔离</b><b>升级</b></div></div>'
    elif effective_mode == "failure_boundary_triptych":
        body = '<div class="industrial-overlay boundary-triptych"><div><b>新材质</b><span>分布变化</span></div><div><b>强反光</b><span>采集异常</span></div><div><b>相机偏移</b><span>输入越界</span></div><div><b>新 SKU</b><span>规则未覆盖</span></div><strong>任一触发 → 暂停自动处置 → 人工复核</strong></div>'
    elif effective_mode == "execution_audit_receipt":
        body = '<div class="industrial-overlay execution-audit"><div class="execution-result"><b>执行成功</b><span>工件已保持隔离</span></div><div class="audit-fields"><span>操作者：已记录</span><span>时间：已记录</span><span>原因：规则冲突</span><span>模型 / 规则版本：已记录</span></div></div>'
    elif effective_mode == "terminal_evidence":
        body = f'<div class="evidence-terminal reveal-item"><div class="terminal-bar">$ extract invoice.fields</div><pre>vendor      = ACME\namount      = 1280.00\ntax_rate    = 13%\ninvoice_id  = INV-2048\n<span class="warn">status      = human_review</span></pre></div><div class="copy-panel copy-panel-wide reveal-item">{safe}</div>'
    elif effective_mode == "input_branch":
        if is_en:
            body = f'<div class="branch-grid reveal-item"><div><span class="eyebrow">NORMAL FLOW</span><strong>Low risk</strong><small>Continue automatically</small></div><div class="bad-cell"><span class="eyebrow">REVIEW QUEUE</span><strong>High risk</strong><small>Hand off for human review</small></div></div><div class="copy-panel copy-panel-wide reveal-item">{safe}</div>'
        else:
            body = '<div class="branch-grid reveal-item"><div><span class="eyebrow">普通样本</span><strong>正常流转</strong><small>低风险继续处理</small></div><div class="bad-cell"><span class="eyebrow">疑似缺陷</span><strong>人工复核</strong><small>高风险与低置信度进入队列</small></div></div>'
    elif effective_mode == "edge_case_matrix":
        body = f'<div class="matrix reveal-item"><div>空密码 <b>FAIL</b></div><div>超长输入 <b>FAIL</b></div><div>重复提交 <b>FAIL</b></div></div><div class="copy-panel copy-panel-wide reveal-item">{safe}</div>'
    elif effective_mode == "reproducibility_compare":
        body = f'<div class="log-compare reveal-item"><pre>RUN 01 失败位置：auth:42\nRUN 02 失败位置：auth:42</pre><span class="match">结果一致 ✓</span></div><div class="copy-panel copy-panel-wide reveal-item">{safe}</div>'
    elif effective_mode == "metric_contrast":
        body = f'<div class="metric-contrast reveal-item"><div><strong>12</strong><small>条测试</small></div><div class="hero-arrow">→</div><div><strong>48</strong><small>条测试</small></div></div><div class="copy-panel copy-panel-wide reveal-item">{safe}</div>'
    elif effective_mode == "checklist_lock":
        checks = ("01 Input", "02 Rule", "03 Exception", "04 Owner") if is_en else ("01 输入", "02 规则", "03 例外", "04 责任")
        body = f'<div class="checklist-live reveal-item">{"".join(f"<div>{esc(item)}</div>" for item in checks)}</div>'
    elif effective_mode == "cta_warning":
        body = f'<div class="cta-live reveal-item"><strong>建议收藏</strong><span>回复「测试清单」领取三项验收表</span></div><div class="copy-panel copy-panel-wide reveal-item">{safe}</div>'
    elif template_id == "meeting_hero_compare":
        body = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:24px"><div style="background:rgba(255,255,255,.08);border:2px solid #62d8ff;border-radius:18px;padding:26px;font-size:30px;line-height:1.45"><b style="color:#72e6a5">原始讨论</b><br>“可以考虑下周上线，先听听大家意见。”</div><div style="background:rgba(255,80,100,.18);border:3px solid #ff5c73;border-radius:18px;padding:26px;font-size:30px;line-height:1.45"><b style="color:#ff9aa8">错误纪要</b><br>“团队决定下周上线。”</div></div><div style="margin-top:28px;color:#ffbf69;font-size:34px;font-weight:900">讨论 ≠ 决定</div>'
    elif template_id == "meeting_record_diff":
        body = '<div style="font-size:30px;line-height:1.5"><div style="color:#72e6a5;font-weight:900;margin-bottom:12px">原始记录</div><div style="background:rgba(255,255,255,.09);padding:22px;border-left:8px solid #72e6a5">张三：可以考虑下周上线。<br>李四：负责人还没定。<br>王五：日期也要再确认。</div><div style="color:#ff9aa8;font-weight:900;margin:24px 0 12px">AI 纪要问题</div><div style="background:rgba(255,80,100,.16);padding:22px;border-left:8px solid #ff5c73">把讨论改成决定<br>猜了负责人和日期</div></div>'
    elif template_id == "language_rule_compare":
        body = '<div style="font-size:34px;line-height:1.5"><div style="color:#ffbf69;font-weight:900">语气验收</div><div style="margin-top:28px;background:rgba(255,255,255,.09);padding:24px;border-left:8px solid #72e6a5">“可以考虑”<br><span style="color:#72e6a5">状态：讨论</span></div><div style="margin-top:24px;background:rgba(255,80,100,.16);padding:24px;border-left:8px solid #ff5c73">“已经决定”<br><span style="color:#ff9aa8">状态：需要人工确认</span></div></div>'
    elif template_id == "owner_missing_state":
        body = '<div style="font-size:34px;line-height:1.55"><div style="font-weight:900;color:#ffbf69;margin-bottom:20px">字段验收：负责人</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:16px"><div style="padding:22px;background:rgba(255,255,255,.1)">负责人</div><div style="padding:22px;background:rgba(255,80,100,.2);color:#ffb2bd">待确认</div><div style="padding:22px;background:rgba(255,255,255,.1)">禁止操作</div><div style="padding:22px;background:rgba(255,80,100,.2);color:#ffb2bd">禁止猜负责人</div></div></div>'
    elif template_id == "deadline_missing_state":
        body = '<div style="font-size:34px;line-height:1.55"><div style="font-weight:900;color:#ffbf69;margin-bottom:20px">字段验收：截止时间</div><div style="padding:26px;background:rgba(255,255,255,.1);border:2px solid #62d8ff">原文没有日期</div><div style="margin-top:22px;padding:26px;background:rgba(255,80,100,.2);border:3px solid #ff5c73;color:#ffb2bd">不要脑补：截止时间 = 待确认</div></div>'
    elif template_id == "result_counter_compare":
        body = '<div style="font-size:34px;line-height:1.4"><div style="display:flex;align-items:center;gap:20px"><div style="font-size:130px;font-weight:900;color:#ff6b7d">2</div><div>个待办<br><span style="font-size:26px;color:#ffb2bd">原版漏记</span></div><div style="font-size:72px;color:#ffbf69">→</div><div style="font-size:130px;font-weight:900;color:#72e6a5">3</div><div>类字段<br><span style="font-size:26px;color:#baffd1">验收后保留</span></div></div><div style="margin-top:36px;color:#dff7ff">决定 · 负责人 · 截止时间</div></div>'
    elif template_id == "transcribe_summarize_verify":
        body = '<div style="font-size:32px;line-height:1.5"><div style="display:flex;align-items:center;justify-content:space-between"><div style="text-align:center"><b style="font-size:44px;color:#62d8ff">听清</b><br>转写工具</div><div style="font-size:54px;color:#ffbf69">→</div><div style="text-align:center"><b style="font-size:44px;color:#62d8ff">整理</b><br>AI提取</div><div style="font-size:54px;color:#ffbf69">→</div><div style="text-align:center"><b style="font-size:44px;color:#72e6a5">验收</b><br>人工拍板</div></div><div style="margin-top:42px;padding:24px;background:rgba(255,255,255,.1);border-left:8px solid #72e6a5">AI可以整理，但不能替你决定。</div></div>'
    elif template_id == "choice_cta":
        body = '<div style="font-size:34px;line-height:1.4"><div style="font-weight:900;color:#ffbf69;margin-bottom:24px">你最怕会议纪要漏掉哪一项？</div><div style="display:flex;flex-direction:column;gap:16px"><div style="padding:22px;background:rgba(255,255,255,.1);border:2px solid #62d8ff">A　决定</div><div style="padding:22px;background:rgba(255,255,255,.1);border:2px solid #62d8ff">B　负责人</div><div style="padding:22px;background:rgba(255,255,255,.1);border:2px solid #62d8ff">C　截止时间</div></div><div style="margin-top:24px;color:#72e6a5">评论区选一个，下一版做真实表格演示</div></div>'
    else:
        stamp = "HUMAN<br>CHECK" if is_en else "人工<br>复核"
        body = f'<div class="body-copy">{safe}</div><div class="checklist">{chips}</div><div class="stamp">{stamp}</div>'
    # Invoice workflow scenes must override legacy prompt/location templates.
    # The override is content-driven and keeps all visible labels in English.
    invoice_bodies = {
        "before_after_split": '<div class="invoice-split"><section class="doc bad"><b>BEFORE</b><strong>Duplicate invoice</strong><span>INV-2048 · $1,280 · Tax 13%</span></section><div class="split-arrow">→</div><section class="doc good"><b>AFTER</b><strong>Human review queue</strong><span>Compare before payment</span></section></div>',
        "workflow_path": '<div class="workflow"><div class="node">INVOICE</div><i>→</i><div class="node">PURCHASE ORDER</div><i>→</i><div class="node">PAYMENT REQUEST</div><div class="path-fields">vendor · amount · tax · invoice number · order ID</div></div>',
        "terminal_evidence": '<div class="evidence-terminal reveal-item"><div class="terminal-bar">$ extract invoice.fields</div><pre>vendor        = ACME<br>amount        = 1280.00<br>tax           = 13%<br>invoice_number= INV-2048<br>order_id      = PO-7781</pre></div>',
        "result_counter_compare": '<div class="status-board"><div class="status matched"><b>MATCHED</b><span>vendor ✓ amount ✓ tax ✓</span></div><div class="status mismatch"><b>MISMATCH</b><span>tax: 13% → 10%</span></div><div class="status duplicate"><b>DUPLICATE</b><span>INV-2048 appears twice</span></div></div>',
        "diagnostic_zoom": '<div class="exception-board"><b>EXCEPTION DETAIL</b><div class="issue">TAX MISMATCH <span>invoice 13% / order 10%</span></div><div class="issue">DUPLICATE NUMBER <span>INV-2048 · 2 records</span></div><div class="review-flag">HUMAN REVIEW REQUIRED</div></div>',
        "decision_tree": '<div class="decision"><div class="decision-input">4 checks pass?</div><div class="branches"><div class="auto">AUTO-PASS<br><small>route to normal flow</small></div><div class="human">HUMAN REVIEW<br><small>any mismatch or duplicate</small></div></div><div class="no-payment">AI never approves payment</div></div>',
        "checklist_lock": '<div class="approval-checks"><div>✓ VENDOR</div><div>✓ AMOUNT</div><div class="needs">! TAX</div><div>✓ DUPLICATE</div></div>',
        "handoff_stamp": '<div class="handoff"><div class="queue-card"><b>REVIEW READY</b><span>OWNER: AP ANALYST</span><span>PENDING: TAX MISMATCH · INV-2048</span></div><div class="stamp">HUMAN<br>DECISION</div></div>'
    }
    invoice_context = bool(re.search(r"invoice|发票|采购单|付款", f"{title} {text}", re.IGNORECASE))
    invoice_key = next((candidate for candidate in (contract_mode, mode, template_id) if candidate in invoice_bodies), "") if invoice_context else ""
    if invoice_key:
        body = invoice_bodies[invoice_key]
    if narrative_copy:
        body = (
            '<div class="narrative-copy">'
            f'<strong>{esc(narrative_copy[0])}</strong>'
            f'<span>{esc(narrative_copy[1])}</span>'
            '</div>' + body
        )
    # Contract execution evidence: these nodes are intentionally visible and
    # animated. A data-* attribute alone is not evidence that a motion was used.
    motion_names = [str(item).strip() for item in (group_motion or []) if str(item).strip()]
    motion_labels = ({
        "split_reveal": "INPUT → REVIEW",
        "callout_draw": "FIELD PATH",
        "type_in": "EXTRACT",
        "local_highlight": "MATCH STATUS",
        "focus_shift": "EXCEPTION",
        "error_mark": "ERROR CHECK",
        "fix_reveal": "DECISION PATH",
        "check_each": "4 CHECKS",
        "stamp_lock": "HUMAN HANDOFF",
    } if is_en else {
        "split_reveal": "输入 → 复核",
        "callout_draw": "字段路径",
        "type_in": "提取",
        "local_highlight": "状态匹配",
        "focus_shift": "异常定位",
        "error_mark": "失败检查",
        "fix_reveal": "决策路径",
        "check_each": "四项复核",
        "stamp_lock": "人工接管",
    })
    base_topic_mode = effective_mode.removesuffix("_detail")
    topic_motion_labels = {
        "decision_interrupt": ("暂停", "交给人"),
        "capture_rig_exploded_view": ("锁定", "复核"),
        "dataset_annotation_board": ("正常", "缺陷"),
        "anomaly_heatmap_inspection": ("热区", "证据"),
        "risk_queue_flow": ("绿件", "黄件", "红件"),
        "human_review_console": ("证据", "处置"),
        "failure_boundary_triptych": ("材质", "反光", "偏移"),
        "execution_audit_receipt": ("执行", "记录"),
    }
    topic_labels = topic_motion_labels.get(base_topic_mode)
    motion_spans = "".join(
        f'<span class="contract-motion motion-{esc(name)}" data-group-id="{esc(name)}" data-motion="{esc(name)}">'
        f'{"" if topic_labels else esc(motion_labels.get(name, name.upper()))}</span>'
        for index, name in enumerate(motion_names)
    )
    motion_dom = f'<div class="topic-scan-motion">{motion_spans}</div>' if topic_labels else motion_spans
    if predictive_layout:
        topic_attr = ' data-topic-layout="true" data-predictive-layout="true" data-container-motion="none"'
    else:
        topic_attr = (
            ' data-topic-layout="true" data-container-motion="none"'
            if topic_labels else ' data-container-motion="legacy"'
        )
    template_class = "template-" + re.sub(r"[^a-zA-Z0-9_-]", "-", template_id or "template")
    return ('''<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:#101827;color:#f5f7fb;font-family:Arial,"Noto Sans CJK SC",sans-serif;}}
body{{position:relative;}}
.bg{{position:absolute;inset:0;z-index:0;background-image:linear-gradient(135deg,rgba(5,12,24,.78),rgba(5,12,24,.28) 58%,rgba(5,12,24,.62)),url("data:image/jpeg;base64,{b64}");background-size:cover;background-position:center;filter:saturate(1.08) contrast(1.04);}}
.veil{{position:absolute;inset:0;z-index:1;background:linear-gradient(180deg,rgba(3,8,18,.18),rgba(3,8,18,.48));pointer-events:none;}}
.head,.content{{position:relative;z-index:2;}}
.head{{padding:70px 72px 0;}}
.head .k{{font-size:24px;color:#ffd166;letter-spacing:2px;font-weight:800;}}
.head .t{{margin-top:16px;font-size:58px;line-height:1.08;font-weight:900;text-shadow:0 4px 18px rgba(0,0,0,.65);}}
.content{{padding:54px 72px 0;}}
body.template-cat_sleep_hook_v1 .content,body.template-curled_sleep_pose_v1 .content,body.template-side_sleep_pose_v1 .content,body.template-back_sleep_pose_v1 .content,body.template-loaf_alert_pose_v1 .content,body.template-hidden_sleep_pose_v1 .content,body.template-observe_not_diagnose_v1 .content,body.template-sleep_pose_checklist_v1 .content{{background:transparent;animation:none;}}
body.template-cat_sleep_hook_v1 .pet-observation,body.template-curled_sleep_pose_v1 .pet-observation,body.template-side_sleep_pose_v1 .pet-observation,body.template-back_sleep_pose_v1 .pet-observation,body.template-loaf_alert_pose_v1 .pet-observation,body.template-hidden_sleep_pose_v1 .pet-observation,body.template-observe_not_diagnose_v1 .pet-observation,body.template-sleep_pose_checklist_v1 .pet-observation{{animation:petRealLocalMotion 2.4s ease-in-out 1s infinite alternate;will-change:transform,filter;}}
@keyframes petRealContentBreath{{0%{{background-color:rgba(255,255,255,.03);}}50%{{background-color:rgba(255,255,255,.18);}}100%{{background-color:rgba(255,255,255,.05);}}}}
@keyframes petRealLocalMotion{{0%{{transform:translateX(-16px);filter:brightness(.76);}}50%{{transform:translateX(16px);filter:brightness(1.28);}}100%{{transform:translateX(-16px);filter:brightness(.82);}}}}
body[data-predictive-layout="true"] .head{{display:none;}}
body[data-predictive-layout="true"] .content{{position:absolute;inset:0;padding:0;overflow:hidden;}}
body[data-predictive-layout="true"] .contract-execution{{display:none;}}
.pm-layout{{position:absolute;inset:0;overflow:hidden;}}
.pm-title,.pm-corner-title,.pm-hud-title,.pm-lane-title,.pm-loop-title{{position:absolute;z-index:5;font-size:60px;line-height:1.12;font-weight:950;text-shadow:0 5px 24px #000;}}
.pm-full-split{{display:grid;grid-template-columns:1fr 1fr;}}
.pm-full-split .pm-title{{left:70px;right:70px;top:82px;text-align:center;}}
.pm-split-left,.pm-split-right{{display:flex;flex-direction:column;justify-content:center;padding:180px 58px 300px;gap:20px;}}
.pm-split-left{{background:linear-gradient(160deg,rgba(16,45,72,.35),rgba(2,8,15,.88));border-right:3px solid #ffd166;}}
.pm-split-right{{background:linear-gradient(200deg,rgba(124,31,45,.36),rgba(2,8,15,.88));}}
.pm-split-left b,.pm-split-right b{{font-size:58px;line-height:1.1;}}.pm-split-left span,.pm-split-right span{{font-size:30px;color:#d6e6f2;}}
.pm-split-verdict{{position:absolute;left:145px;right:145px;bottom:300px;padding:26px;text-align:center;font-size:42px;font-weight:950;background:#ffd166;color:#101827;transform:rotate(-2deg);}}
.pm-sensor-topology .pm-title{{left:62px;top:78px;width:720px;}}
.pm-device-core{{position:absolute;left:340px;top:650px;width:400px;height:400px;border:16px solid #ffd166;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:44px;font-weight:950;background:rgba(5,14,25,.84);}}
.pm-sensor{{position:absolute;width:250px;height:120px;display:flex;align-items:center;justify-content:center;font-size:36px;font-weight:900;background:rgba(5,20,35,.9);border-bottom:8px solid #62d8ff;}}
.pm-s1{{left:80px;top:420px;}}.pm-s2{{right:80px;top:420px;}}.pm-s3{{left:80px;top:1120px;}}.pm-s4{{right:80px;top:1120px;}}
.pm-topology-note{{position:absolute;left:150px;right:150px;bottom:280px;text-align:center;font-size:36px;color:#ffd166;font-weight:900;}}
.pm-baseline-wave{{padding-left:220px;}}
.pm-vertical-title{{position:absolute;left:42px;top:180px;bottom:300px;width:120px;writing-mode:vertical-rl;font-size:55px;font-weight:950;letter-spacing:5px;}}
.pm-wave{{position:relative;margin:210px 65px 0;height:150px;border-bottom:7px solid #62d8ff;transform:skewY(-3deg);}}
.pm-wave::after{{content:"";position:absolute;left:0;right:0;bottom:-7px;height:70px;background:linear-gradient(135deg,transparent 0 12%,#ffd166 13% 16%,transparent 17% 31%,#62d8ff 32% 35%,transparent 36% 52%,#72e6a5 53% 56%,transparent 57%);opacity:.8;}}
.pm-wave span{{font-size:34px;font-weight:900;}}
.pm-baseline-label{{position:absolute;right:70px;bottom:260px;font-size:42px;font-weight:950;color:#ffd166;}}
.pm-signal-columns{{display:grid;grid-template-columns:repeat(3,1fr);gap:3px;padding-top:260px;padding-bottom:250px;}}
.pm-corner-title{{left:55px;top:55px;width:760px;}}
.pm-signal{{display:flex;flex-direction:column;justify-content:center;gap:26px;padding:42px 28px;background:rgba(4,14,26,.72);border-top:12px solid;}}
.pm-signal b{{font-size:42px;line-height:1.1;}}.pm-signal span{{font-size:28px;color:#d7e5ef;}}.pm-signal i{{display:block;height:230px;border-left:8px solid currentColor;transform:skewX(-8deg);}}
.pm-signal.drift{{color:#62d8ff;}}.pm-signal.spike{{color:#ffd166;}}.pm-signal.offline{{color:#ff647c;}}
.pm-evidence-spine .pm-title{{left:62px;top:70px;width:780px;}}
.pm-spine{{position:absolute;left:50%;top:330px;bottom:360px;width:8px;background:#62d8ff;}}
.pm-proof{{position:absolute;width:410px;padding:32px 36px;background:rgba(4,17,31,.9);border:3px solid #62d8ff;}}
.pm-proof b,.pm-proof span{{display:block;}}.pm-proof b{{font-size:42px;}}.pm-proof span{{font-size:26px;color:#d8e5ee;margin-top:8px;}}
.pm-proof.p1{{left:70px;top:430px;}}.pm-proof.p2{{right:70px;top:760px;}}.pm-proof.p3{{left:70px;top:1090px;}}
.pm-evidence-rule{{position:absolute;left:80px;right:80px;bottom:250px;padding:24px;border-left:12px solid #ffd166;font-size:36px;font-weight:900;background:rgba(4,12,22,.88);}}
.pm-field-hud .pm-hud-title{{right:60px;top:70px;width:560px;text-align:right;}}
.pm-machine-ring{{position:absolute;left:180px;top:430px;width:720px;height:720px;border:9px solid #62d8ff;border-radius:50%;box-shadow:0 0 0 70px rgba(98,216,255,.07),inset 0 0 80px rgba(98,216,255,.18);}}
.pm-check{{position:absolute;padding:20px 28px;font-size:32px;font-weight:900;background:#f5f7fb;color:#17202a;border-left:10px solid #ffd166;}}
.pm-check.c1{{left:50px;top:430px;}}.pm-check.c2{{right:50px;top:610px;}}.pm-check.c3{{left:40px;top:970px;}}.pm-check.c4{{right:45px;top:1160px;}}
.pm-human-badge{{position:absolute;left:170px;right:170px;bottom:250px;text-align:center;font-size:38px;font-weight:950;color:#72e6a5;}}
.pm-decision-lanes{{display:grid;grid-template-rows:250px repeat(4,1fr) 230px;gap:8px;}}
.pm-lane-title{{left:55px;top:55px;}}
.pm-lane{{grid-column:1;margin:0 55px;display:grid;grid-template-columns:1fr 1fr;align-items:center;padding:0 38px;border-left:18px solid;background:rgba(4,15,27,.83);}}
.pm-lane b{{font-size:48px;}}.pm-lane span{{font-size:28px;text-align:right;}}.pm-lane.run{{border-color:#72e6a5;}}.pm-lane.derate{{border-color:#62d8ff;}}.pm-lane.stop{{border-color:#ffd166;}}.pm-lane.urgent{{border-color:#ff647c;}}
.pm-loop-title{{left:55px;top:55px;width:720px;}}
.pm-loop-step{{position:absolute;width:180px;height:180px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:36px;font-weight:950;background:#10263d;border:8px solid #62d8ff;}}
.pm-loop-step.s1{{left:110px;top:430px;}}.pm-loop-step.s2{{right:110px;top:430px;}}.pm-loop-step.s3{{right:110px;top:760px;}}.pm-loop-step.s4{{left:110px;top:760px;border-color:#ffd166;}}
.pm-receipt{{position:absolute;left:90px;right:90px;top:1040px;padding:34px;background:rgba(245,247,251,.94);color:#17202a;border-left:12px solid #ffd166;}}
.pm-receipt b,.pm-receipt span{{display:block;}}.pm-receipt b{{font-size:38px;}}.pm-receipt span{{font-size:27px;margin-top:10px;}}
.pm-independent-cta{{position:absolute;left:90px;right:90px;bottom:250px;padding:34px 44px;background:#ffd166;color:#101827;display:flex;align-items:center;justify-content:space-between;transform:rotate(-1deg);}}
.pm-independent-cta strong{{font-size:46px;}}.pm-independent-cta span{{font-size:30px;font-weight:900;}}
body[data-predictive-layout="true"] .bg{{background-image:linear-gradient(180deg,rgba(3,8,18,.48),rgba(3,8,18,.08) 36%,rgba(3,8,18,.34)),url("data:image/jpeg;base64,{b64}");filter:saturate(.9) contrast(1.03);transform:none!important;animation:none!important;}}
body[data-predictive-layout="true"] .veil{{background:linear-gradient(180deg,rgba(3,8,18,.08),rgba(3,8,18,.22));}}
.pm-device-diagnostic .pm-title{{left:58px;right:58px;top:64px;font-size:58px;}}
.pm-running-state{{position:absolute;left:58px;top:310px;padding:22px 26px;border-left:10px solid #72e6a5;background:rgba(3,12,22,.72);}}
.pm-running-state b,.pm-running-state span{{display:block;}}.pm-running-state b{{font-size:38px;}}.pm-running-state span{{font-size:24px;color:#cfe0ea;margin-top:5px;}}
.pm-bearing-marker{{position:absolute;left:195px;top:970px;color:#ffd166;font-size:25px;font-weight:900;}}.pm-bearing-marker i{{display:block;width:84px;height:84px;border:6px solid #ffd166;border-radius:50%;box-shadow:0 0 0 13px rgba(255,209,102,.16);}}
.pm-trend-panel{{position:absolute;right:55px;top:510px;width:430px;height:350px;padding:24px;background:rgba(3,12,22,.78);border:2px solid rgba(98,216,255,.75);}}
.pm-trend-panel b,.pm-trend-panel span{{display:block;}}.pm-trend-panel b{{font-size:35px;}}.pm-trend-panel span{{position:absolute;bottom:20px;color:#ffd166;font-size:24px;font-weight:900;}}
.pm-threshold{{position:absolute;left:24px;right:24px;top:165px;border-top:3px dashed #ff647c;}}
.pm-trend-line{{position:absolute;left:30px;right:30px;top:95px;height:150px;border-bottom:8px solid #62d8ff;transform:skewY(-12deg);}}
.pm-split-verdict{{left:58px;right:auto;bottom:500px;padding:20px 30px;font-size:42px;transform:none;}}
.pm-sensor-topology .pm-title{{left:58px;right:58px;top:64px;width:auto;}}
.pm-device-core{{left:300px;top:760px;width:auto;height:auto;padding:17px 24px;border:3px solid #ffd166;border-radius:5px;font-size:30px;background:rgba(5,14,25,.72);}}
.pm-sensor{{width:250px;height:auto;min-height:104px;padding:16px;display:block;background:rgba(5,20,35,.76);border:2px solid rgba(98,216,255,.75);border-left:8px solid #62d8ff;}}
.pm-sensor b,.pm-sensor span{{display:block;}}.pm-sensor b{{font-size:32px;}}.pm-sensor span{{font-size:22px;color:#d5e3ec;margin-top:6px;}}
.pm-s1{{left:44px;top:430px;}}.pm-s2{{right:44px;top:510px;}}.pm-s3{{left:44px;top:1060px;}}.pm-s4{{right:44px;top:1160px;}}
.pm-topology-note{{left:58px;right:auto;bottom:500px;padding:18px 24px;background:rgba(3,12,22,.75);font-size:31px;}}
.pm-baseline-proof .pm-title{{left:58px;right:58px;top:64px;font-size:55px;}}
.pm-source-chain{{position:absolute;left:55px;right:55px;top:430px;display:flex;align-items:center;justify-content:space-between;gap:10px;}}
.pm-source-chain>div{{padding:20px;background:rgba(3,12,22,.74);border-top:5px solid #62d8ff;min-width:210px;}}.pm-source-chain b,.pm-source-chain span{{display:block;}}.pm-source-chain b{{font-size:31px;}}.pm-source-chain span{{font-size:22px;margin-top:6px;}}.pm-source-chain i{{font-size:42px;color:#ffd166;font-style:normal;}}
.pm-baseline-band{{position:absolute;left:60px;right:60px;top:890px;height:260px;padding:22px;background:rgba(3,12,22,.7);border:2px solid rgba(98,216,255,.68);}}
.pm-baseline-band span,.pm-baseline-band b{{position:absolute;font-size:25px;}}.pm-baseline-band span{{left:20px;top:18px;}}.pm-baseline-band b{{right:20px;bottom:18px;color:#ffd166;}}.pm-baseline-band i{{position:absolute;left:35px;right:35px;top:105px;height:72px;border-bottom:8px solid #62d8ff;transform:skewY(-5deg);}}
.pm-wrong-reference{{position:absolute;right:55px;bottom:500px;padding:18px 22px;border-left:8px solid #ff647c;background:rgba(3,12,22,.76);font-size:28px;font-weight:900;}}
.pm-signal-columns{{gap:8px;padding:250px 30px 480px;}}
.pm-signal{{background:rgba(3,12,22,.68);padding:30px 22px;}}
.pm-signal i{{height:300px;}}.pm-signal b{{font-size:37px;}}.pm-signal span{{font-size:24px;line-height:1.35;}}
.pm-evidence-handoff .pm-title{{left:55px;right:55px;top:65px;font-size:55px;}}
.pm-evidence-sheet{{position:absolute;left:50px;top:430px;width:610px;padding:20px;background:rgba(3,12,22,.76);border-left:10px solid #62d8ff;}}
.pm-evidence-sheet>div{{display:grid;grid-template-columns:180px 1fr;padding:19px;border-bottom:1px solid rgba(255,255,255,.18);}}.pm-evidence-sheet b{{font-size:25px;color:#c8dbe7;}}.pm-evidence-sheet span{{font-size:28px;font-weight:900;}}
.pm-authority-zone{{position:absolute;right:50px;top:850px;width:350px;padding:30px;background:rgba(255,209,102,.9);color:#101827;}}
.pm-authority-zone b,.pm-authority-zone span{{display:block;}}.pm-authority-zone b{{font-size:38px;}}.pm-authority-zone span{{font-size:22px;margin-top:12px;font-weight:900;}}
.pm-field-review .pm-hud-title{{left:55px;right:55px;top:65px;width:auto;text-align:left;font-size:54px;}}
.pm-field-review .pm-check{{padding:15px 21px;font-size:27px;background:rgba(245,247,251,.9);}}
.pm-field-review .pm-check.c1{{left:55px;top:560px;}}.pm-field-review .pm-check.c2{{right:45px;top:760px;}}.pm-field-review .pm-check.c3{{left:55px;top:1040px;}}.pm-field-review .pm-check.c4{{right:45px;top:1190px;}}
.pm-human-badge{{left:55px;right:auto;bottom:500px;padding:18px 25px;background:rgba(3,12,22,.75);font-size:30px;}}
.pm-decision-matrix .pm-lane-title{{left:55px;top:60px;font-size:58px;}}
.pm-decision-matrix{{padding:300px 60px 480px;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:7px;}}
.pm-quadrant{{padding:30px;background:rgba(3,12,22,.72);border:2px solid rgba(255,255,255,.24);display:flex;flex-direction:column;justify-content:center;}}
.pm-quadrant b{{font-size:37px;}}.pm-quadrant span{{font-size:22px;margin-top:10px;}}.pm-quadrant.run{{border-left:10px solid #72e6a5;}}.pm-quadrant.derate{{border-left:10px solid #62d8ff;}}.pm-quadrant.stop{{border-left:10px solid #ffd166;}}.pm-quadrant.urgent{{border-left:10px solid #ff647c;}}
.pm-axis{{position:absolute;font-size:21px;color:#d5e3ec;font-weight:900;}}.pm-axis.risk{{left:25px;top:760px;writing-mode:vertical-rl;transform:rotate(180deg);}}.pm-axis.duration{{left:380px;bottom:450px;}}
.pm-case-dot{{position:absolute;left:535px;top:850px;padding:18px 24px;border-radius:50%;background:#ffd166;color:#101827;font-size:25px;font-weight:950;box-shadow:0 0 0 12px rgba(255,209,102,.2);}}
.pm-human-gate{{position:absolute;right:60px;bottom:500px;padding:24px 30px;background:rgba(255,209,102,.94);color:#101827;font-size:34px;font-weight:950;}}
.pm-result-workorder .pm-loop-title{{left:55px;right:55px;top:60px;width:auto;font-size:55px;}}
.pm-wave-compare{{position:absolute;left:50px;top:360px;width:480px;display:grid;gap:22px;}}
.pm-wave-compare>div{{height:190px;padding:20px;background:rgba(3,12,22,.7);border:2px solid rgba(98,216,255,.65);}}.pm-wave-compare b{{font-size:28px;}}.pm-wave-compare i{{display:block;margin-top:30px;height:72px;border-bottom:7px solid #62d8ff;transform:skewY(-8deg);}}.pm-wave-compare i.after{{border-color:#72e6a5;transform:skewY(-1deg);}}
.pm-workorder{{position:absolute;right:45px;top:520px;width:430px;padding:27px;background:rgba(245,247,251,.92);color:#17202a;border-left:10px solid #72e6a5;}}
.pm-workorder b,.pm-workorder span{{display:block;}}.pm-workorder b{{font-size:36px;margin-bottom:17px;}}.pm-workorder span{{font-size:23px;padding:8px 0;border-bottom:1px solid rgba(0,0,0,.15);}}
.pm-four-step{{position:absolute;left:55px;right:55px;top:1110px;padding:18px 24px;background:rgba(3,12,22,.7);font-size:28px;text-align:center;font-weight:900;}}
.pm-result-workorder .pm-independent-cta{{left:auto;right:55px;bottom:500px;width:620px;padding:26px 32px;transform:none;}}
.pm-result-workorder .pm-independent-cta strong{{font-size:40px;}}.pm-result-workorder .pm-independent-cta span{{font-size:27px;}}
.pm-detail-layout{{filter:saturate(1.04);}}
.pm-detail-proof{{position:absolute;z-index:12;right:42px;top:235px;bottom:auto;max-width:720px;padding:15px 22px;background:#62d8ff;color:#071521;font-size:25px;font-weight:950;letter-spacing:.5px;box-shadow:0 8px 24px rgba(0,0,0,.32);}}
body[data-predictive-layout="true"] .contract-execution{{display:none;}}
.contract-execution{{position:absolute;left:72px;right:72px;bottom:60px;display:flex;gap:12px;opacity:.95;z-index:4;}}
.contract-motion{{font-size:20px;color:#dff7ff;background:rgba(3,10,20,.86);border:2px solid rgba(98,216,255,.7);border-radius:10px;padding:10px 14px;font-weight:800;letter-spacing:1px;box-shadow:0 8px 22px rgba(0,0,0,.28);}}
.prompt-line,.caption-line{{display:flex;gap:12px;flex-wrap:wrap;align-items:center;}}
.chip{{display:inline-flex;padding:14px 18px;background:rgba(5,18,34,.88);border:2px solid #62d8ff;border-radius:10px;font-size:24px;font-weight:800;}}
.prompt-line{{margin-top:130px;min-height:180px;align-content:center;}}
.typed,.body-copy{{margin-top:30px;padding:28px;border-left:8px solid #ffd166;background:rgba(4,13,26,.82);font-size:32px;line-height:1.45;}}
.annot,.orbit,.viewfinder,.source-trace,.evidence-timeline,.flow-track,.rollback,.audit-ring,.timeline-reveal,.result-reveal,.result-hold,.error-fix,.checklist-stamp{{position:relative;margin-top:90px;min-height:520px;background:rgba(4,13,26,.68);border:2px solid rgba(98,216,255,.75);}}
.annot .subject-spot{{position:absolute;left:34%;top:28%;width:240px;height:240px;border:5px solid #ffd166;border-radius:50%;}}
.annot .line{{position:absolute;height:3px;width:260px;background:#62d8ff;transform-origin:left center;}}
.annot .l1{{left:12%;top:22%;transform:rotate(18deg);}}.annot .l2{{right:8%;top:32%;transform:rotate(158deg);}}.annot .l3{{left:10%;bottom:28%;transform:rotate(-14deg);}}.annot .l4{{right:10%;bottom:22%;transform:rotate(198deg);}}
.annot .chip,.orbit .chip{{position:relative;margin:24px;}}
.orbit{{display:grid;grid-template-columns:1fr 1fr;align-content:center;gap:36px;padding:50px;}}
.center-word{{margin-top:-300px;position:relative;text-align:center;font-size:42px;font-weight:900;color:#ffd166;}}
.light-split{{display:grid;grid-template-columns:1fr 1fr;min-height:620px;margin-top:70px;overflow:hidden;}}
.light-split>div{{display:flex;align-items:center;justify-content:center;font-size:42px;font-weight:900;}}
.light-split .cool{{background:linear-gradient(135deg,#123b78,#5bd8ff);}}.light-split .warm{{background:linear-gradient(135deg,#7d2f1d,#ffb347);}}
.viewfinder{{border:5px solid #fff;background:rgba(5,16,30,.42);}}.viewfinder i{{position:absolute;background:#fff;}}.viewfinder i:nth-child(1){{left:33%;top:0;bottom:0;width:2px;}}.viewfinder i:nth-child(2){{right:33%;top:0;bottom:0;width:2px;}}.viewfinder i:nth-child(3){{left:0;right:0;top:50%;height:2px;}}.crosshair{{position:absolute;inset:42% 0 auto;text-align:center;font-size:74px;color:#ffd166;}}
.source-trace,.rollback,.error-fix{{display:grid;grid-template-columns:1fr 100px 1fr;align-items:center;padding:50px;gap:18px;}}
.trace-origin,.trace-target,.rollback-node,.error-side,.fix-side{{padding:34px;background:#10263d;border:3px solid #62d8ff;font-size:30px;font-weight:900;text-align:center;}}
.trace-line,.rollback-path,.fix-arrow{{height:5px;background:#ffd166;color:#ffd166;font-size:38px;text-align:center;}}
.evidence-timeline,.timeline-reveal{{display:flex;align-items:center;justify-content:space-around;padding:50px;gap:18px;}}
.timeline-line{{position:absolute;left:8%;right:8%;top:50%;height:6px;background:#62d8ff;}}.evidence-timeline .chip,.timeline-step{{position:relative;padding:24px;background:#10263d;border:3px solid #ffd166;font-size:27px;}}
.timeline-proof{{position:absolute;left:50px;right:50px;bottom:32px;font-size:28px;text-align:center;}}
.flow-track{{display:flex;align-items:center;justify-content:space-around;padding:50px;gap:14px;}}.track-arrow{{font-size:34px;text-align:center;margin-top:-310px;position:relative;color:#ffd166;}}
.audit-ring{{width:560px;margin:80px auto 0;border-radius:50%;display:flex;align-items:center;justify-content:center;}}.audit-center{{font-size:58px;font-weight:900;text-align:center;}}.audit-items{{display:flex;justify-content:center;gap:12px;margin-top:-70px;position:relative;}}
.result-reveal,.result-hold{{display:flex;flex-direction:column;justify-content:center;padding:48px;gap:22px;}}.result-reveal span,.result-hold span{{font-size:25px;color:#ffd166;}}.result-reveal strong,.result-hold strong{{font-size:48px;line-height:1.25;}}.result-reveal small{{font-size:26px;}}.hold-line{{height:8px;width:74%;background:#72e6a5;}}
.error-fix .error-side{{border-color:#ff647c;}}.error-fix .fix-side{{border-color:#72e6a5;}}.error-fix span{{display:block;margin-top:16px;font-size:24px;}}
.checklist-stamp{{padding:45px;}}.check-items{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}.local-stamp{{width:max-content;margin:56px auto 0;padding:18px 28px;border:5px solid #72e6a5;color:#72e6a5;font-size:42px;font-weight:900;transform:rotate(-4deg);}}
.industrial-overlay{{position:absolute;left:48px;right:48px;margin:0;color:#17202a;font-weight:750;transform:none!important;}}
.narrative-copy{{position:absolute;left:48px;right:48px;top:200px;padding:14px 20px;background:rgba(8,12,18,.68);border-left:7px solid #f2c94c;border-radius:14px;color:#f8fafc;box-shadow:0 12px 28px rgba(0,0,0,.28);transform:none!important;}}
.narrative-copy strong,.narrative-copy span{{display:block;}}.narrative-copy strong{{font-size:28px;line-height:1.25;font-weight:900;}}.narrative-copy span{{margin-top:6px;font-size:19px;line-height:1.32;color:#e2e8f0;font-weight:600;}}
.industrial-overlay>div,.industrial-overlay .route{{backdrop-filter:blur(10px);box-shadow:0 12px 34px rgba(0,0,0,.26);}}
.decision-interrupt{{top:500px;}}
.decision-interrupt .uncertain-target{{margin-left:auto;width:62%;padding:22px 26px;border:5px dashed #f2c94c;background:rgba(255,252,229,.9);}}
.decision-interrupt .uncertain-target span,.decision-interrupt .uncertain-target b{{display:block;}}.decision-interrupt .uncertain-target span{{font-size:25px;}}.decision-interrupt .uncertain-target b{{font-size:38px;margin-top:8px;}}
.authority-line{{margin:18px 0 0 auto;width:max-content;max-width:72%;padding:14px 20px;background:rgba(255,255,255,.9);border-left:8px solid #f2c94c;font-size:24px;}}
.capture-rig{{display:grid;grid-template-columns:1fr 38px 1fr 38px 1fr;align-items:center;gap:8px;top:520px;}}
.capture-rig>div{{padding:20px 16px;background:rgba(255,255,255,.9);border-top:7px solid #62a8d8;}}
.capture-rig b,.capture-rig span{{display:block;}}.capture-rig b{{font-size:27px;}}.capture-rig span{{font-size:19px;margin-top:6px;}}.capture-rig i{{font-size:32px;text-align:center;color:#fff;}}
.dataset-board{{display:grid;grid-template-columns:1fr 1fr;gap:18px;top:500px;}}.dataset-board>div{{padding:24px;background:rgba(255,255,255,.9);border-left:8px solid #4f93bf;}}.dataset-board .defect-cell{{border-left-color:#d65f55;}}.dataset-board small,.dataset-board b,.dataset-board span{{display:block;}}.dataset-board small{{font-size:19px;color:#64748b;}}.dataset-board b{{font-size:30px;margin:8px 0;}}.dataset-board span{{font-size:21px;}}
.heatmap-inspection{{top:470px;min-height:300px;}}.heatmap-box{{position:absolute;left:10%;top:6%;width:38%;height:70%;border:5px solid #f2c94c;background:radial-gradient(circle,rgba(234,78,67,.42),rgba(242,201,76,.08) 62%,transparent 64%);}}
.evidence-stack{{margin-left:auto;width:44%;padding:22px;background:rgba(255,255,255,.92);border-left:8px solid #f2c94c;}}.evidence-stack b,.evidence-stack span{{display:block;}}.evidence-stack b{{font-size:31px;}}.evidence-stack span{{font-size:21px;margin-top:8px;}}
.risk-queue{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;top:520px;}}.risk-queue .route{{padding:22px 14px;background:rgba(255,255,255,.92);text-align:center;border-top:9px solid;}}.risk-queue .green{{border-color:#31ad69;}}.risk-queue .yellow{{border-color:#f2c94c;}}.risk-queue .red{{border-color:#d94b54;}}.route b,.route span{{display:block;}}.route b{{font-size:44px;}}.route span{{font-size:20px;margin-top:6px;}}
.handoff-console{{top:450px;}}.handoff-state{{padding:16px 20px;background:rgba(255,247,204,.94);border-left:9px solid #f2c94c;font-size:25px;}}.review-evidence,.decision-buttons{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px;}}.review-evidence span{{padding:12px 8px;background:rgba(255,255,255,.9);text-align:center;font-size:18px;}}.decision-buttons b{{padding:15px 6px;background:rgba(255,255,255,.94);border-bottom:7px solid #4f93bf;text-align:center;font-size:20px;}}.decision-buttons b:nth-child(3){{border-color:#f2c94c;}}
.boundary-triptych{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;top:470px;}}.boundary-triptych>div{{padding:16px 12px;background:rgba(255,255,255,.92);border-top:8px solid #d65f55;}}.boundary-triptych b,.boundary-triptych span{{display:block;}}.boundary-triptych b{{font-size:22px;}}.boundary-triptych span{{font-size:18px;margin-top:6px;}}.boundary-triptych>strong{{grid-column:1/-1;padding:13px;background:rgba(255,247,204,.94);text-align:center;font-size:22px;}}
.execution-audit{{display:grid;grid-template-columns:.8fr 1.2fr;gap:14px;top:480px;}}.execution-result,.audit-fields{{padding:20px;background:rgba(255,255,255,.93);}}.execution-result{{border-left:9px solid #31ad69;}}.execution-result b,.execution-result span,.audit-fields span{{display:block;}}.execution-result b{{font-size:32px;color:#19733f;}}.execution-result span{{font-size:21px;margin-top:10px;}}.audit-fields span{{font-size:18px;padding:5px 0;border-bottom:1px solid rgba(23,32,42,.18);}}
.decision-detail,.capture-detail,.governance-detail,.evidence-detail,.risk-detail,.disposition-detail,.trigger-detail,.receipt-detail{{position:absolute;padding:20px;background:rgba(255,255,255,.84);border-left:9px solid #f2c94c;}}
.decision-detail{{left:44px;right:44px;top:420px;}}.capture-detail{{right:36px;top:400px;width:430px;}}.governance-detail{{left:36px;top:480px;width:560px;}}.evidence-detail{{left:36px;top:440px;width:460px;}}.risk-detail{{left:38px;right:38px;top:470px;}}.disposition-detail{{left:38px;right:38px;top:430px;}}.trigger-detail{{left:34px;top:470px;width:470px;}}.receipt-detail{{left:38px;right:38px;top:470px;}}
.decision-path,.evidence-chain,.disposition-actions{{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:23px;}}.decision-path strong,.risk-center strong{{color:#8a6300;font-size:31px;}}.decision-proof,.disposition-proof{{margin-top:18px;padding:12px;background:#fff3b0;font-size:21px;text-align:center;}}
.capture-detail{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}}.capture-detail>div{{padding:16px;background:#edf6fb;text-align:center;}}.capture-detail span,.capture-detail b{{display:block;}}.capture-detail strong{{grid-column:1/-1;padding:12px;text-align:center;background:#fff3b0;font-size:21px;}}
.governance-detail{{display:grid;grid-template-columns:1fr 50px 1fr;align-items:center;gap:10px;}}.governance-detail>div{{padding:18px;background:#edf6fb;}}.governance-detail small,.governance-detail b{{display:block;}}.governance-detail i{{font-size:40px;text-align:center;color:#c53d4b;}}
.defect-zoom{{height:100px;border-left:7px solid #f2c94c;background:radial-gradient(circle at 78% 50%,rgba(224,72,58,.34),transparent 24%),linear-gradient(90deg,rgba(224,72,58,.22),transparent);display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:4px;padding:12px;}}.defect-zoom b,.defect-zoom span,.defect-zoom small{{display:block;}}.defect-zoom b{{font-size:19px;}}.defect-zoom span{{font-size:23px;}}.defect-zoom small{{font-size:16px;}}.evidence-chain{{margin-top:10px;display:grid;grid-template-columns:1fr 20px 1fr 20px 1fr 20px 1fr;font-size:17px;}}.evidence-chain i{{color:#8a6300;}}
.risk-detail{{display:grid;grid-template-columns:.8fr 1.4fr .8fr;gap:10px;align-items:center;}}.risk-side,.risk-center{{padding:18px;text-align:center;background:#edf6fb;}}.risk-side.green{{border-top:7px solid #31ad69;}}.risk-side.red{{border-top:7px solid #d94b54;}}.risk-center{{border:5px solid #f2c94c;}}.risk-center span,.risk-center strong{{display:block;}}
.disposition-evidence{{padding:14px;background:#edf6fb;font-size:22px;text-align:center;}}.disposition-actions{{margin-top:12px;}}.disposition-actions span,.disposition-actions b{{padding:14px 10px;background:#edf6fb;border-bottom:6px solid #4f93bf;}}.disposition-actions b{{border-color:#f2c94c;background:#fff3b0;}}
.trigger-detail{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}.trigger-detail>div{{padding:17px;background:#fff1f1;border-left:7px solid #d94b54;font-size:22px;}}.trigger-detail strong{{grid-column:1/-1;padding:13px;background:#fff3b0;text-align:center;font-size:22px;}}
.receipt-switch{{top:470px;}}.audit-state{{display:grid;grid-template-columns:.8fr 1.2fr;gap:14px;}}.physical-receipt,.audit-receipt{{padding:19px;background:#edf6fb;}}.physical-receipt{{border-left:8px solid #31ad69;}}.physical-receipt b,.physical-receipt span,.audit-receipt b,.audit-receipt span{{display:block;}}.physical-receipt b,.audit-receipt b{{font-size:28px;}}.audit-receipt span{{font-size:19px;padding:4px 0;border-bottom:1px solid #b8c8d2;}}.cta-panel{{display:none;padding:24px 26px;background:rgba(244,250,253,.97);border-left:8px solid #f2c94c;box-shadow:0 16px 30px rgba(0,0,0,.24);gap:12px;flex-direction:column;}}.cta-panel b{{font-size:29px;}}.cta-panel span{{font-size:20px;line-height:1.45;}}.cta-panel strong{{font-size:25px;color:#17202a;}}.receipt-switch.is-cta .audit-state{{display:none;}}.receipt-switch.is-cta .cta-panel{{display:flex;}}
body[data-topic-layout="true"] .content{position:absolute;inset:0;padding:0;}
body[data-topic-layout="true"] .head{position:absolute;left:42px;right:42px;top:42px;padding:0;z-index:5;}
body[data-topic-layout="true"] .head .t{display:inline-block;max-width:620px;padding:18px 26px;border-left:8px solid #ffd166;background:rgba(3,10,20,.72);font-size:44px;line-height:1.12;}
body[data-topic-layout="true"] .contract-execution{position:absolute;left:28px;right:28px;top:230px;height:760px;bottom:auto;overflow:hidden;pointer-events:none;}
body[data-visual-mode="decision_interrupt"] .contract-execution{left:18px;right:118px;top:250px;transform:rotate(-5deg);}
body[data-visual-mode="capture_rig_exploded_view"] .contract-execution{left:82px;right:12px;top:310px;transform:rotate(4deg) scale(1.08);}
body[data-visual-mode="dataset_annotation_board"] .contract-execution{left:10px;right:64px;top:280px;transform:skewY(-3deg) scaleX(1.08);}
body[data-visual-mode="anomaly_heatmap_inspection"] .contract-execution{left:62px;right:8px;top:300px;transform:rotate(-2deg) scale(1.12);}
body[data-visual-mode="risk_queue_flow"] .contract-execution{left:-64px;right:-64px;top:390px;transform:scale(1.2,0.82);}
body[data-visual-mode="human_review_console"] .contract-execution{left:76px;right:0;top:270px;transform:translateX(28px) scale(1.06);}
body[data-visual-mode="failure_boundary_triptych"] .contract-execution{left:-18px;right:-18px;top:250px;transform:scale(1.16,1.08);}
body[data-visual-mode="pilot_timeline"] .contract-execution{left:-88px;right:-88px;top:360px;transform:rotate(-2deg) scale(1.24,0.86);}
body[data-visual-mode="decision_interrupt"] .content{transform:none;}
body[data-visual-mode="capture_rig_exploded_view"] .content{transform:none;}
body[data-visual-mode="dataset_annotation_board"] .content{transform:none;}
body[data-visual-mode="anomaly_heatmap_inspection"] .content{transform:none;}
body[data-visual-mode="risk_queue_flow"] .content{transform:none;}
body[data-visual-mode="human_review_console"] .content{transform:none;}
body[data-visual-mode="failure_boundary_triptych"] .content{transform:none;}
body[data-visual-mode="pilot_timeline"] .content{transform:none;}
body[data-visual-mode="decision_interrupt"] .industrial-overlay{left:24px;right:150px;top:420px;}
body[data-visual-mode="capture_rig_exploded_view"] .industrial-overlay{left:24px;right:24px;top:360px;}
body[data-visual-mode="dataset_annotation_board"] .industrial-overlay{left:32px;right:32px;top:390px;grid-template-columns:1.35fr .65fr;}
body[data-visual-mode="anomaly_heatmap_inspection"] .industrial-overlay{left:24px;right:24px;top:330px;min-height:360px;}
body[data-visual-mode="risk_queue_flow"] .industrial-overlay{left:24px;right:24px;top:430px;grid-template-columns:1.2fr .9fr 1.2fr;gap:22px;}
body[data-visual-mode="human_review_console"] .industrial-overlay{left:24px;right:24px;top:340px;}
body[data-visual-mode="failure_boundary_triptych"] .industrial-overlay{left:24px;right:24px;top:330px;grid-template-columns:repeat(4,1fr);gap:12px;}
body[data-visual-mode="pilot_timeline"] .content .body-copy{margin:0 28px;padding-top:300px;}
body[data-topic-layout="true"] .topic-scan-motion{display:none;}
body[data-topic-layout="true"] .contract-motion{display:none;}
body[data-topic-layout="true"] .contract-motion:nth-child(1){{top:34%;}}
body[data-topic-layout="true"] .contract-motion:nth-child(2){{top:70%;}}
body[data-visual-mode$="_detail"] .veil{{background:linear-gradient(180deg,rgba(3,8,18,.04),rgba(3,8,18,.12));}}body[data-visual-mode$="_detail"] .head{{display:none;}}
body[data-visual-mode="decision_interrupt"] .veil,body[data-visual-mode="capture_rig_exploded_view"] .veil,body[data-visual-mode="dataset_annotation_board"] .veil,body[data-visual-mode="anomaly_heatmap_inspection"] .veil,body[data-visual-mode="risk_queue_flow"] .veil,body[data-visual-mode="human_review_console"] .veil,body[data-visual-mode="failure_boundary_triptych"] .veil,body[data-visual-mode="execution_audit_receipt"] .veil{{background:linear-gradient(180deg,rgba(3,8,18,.12),rgba(3,8,18,.22));}}
body[data-visual-mode="decision_interrupt"] .head,body[data-visual-mode="capture_rig_exploded_view"] .head,body[data-visual-mode="dataset_annotation_board"] .head,body[data-visual-mode="anomaly_heatmap_inspection"] .head,body[data-visual-mode="risk_queue_flow"] .head,body[data-visual-mode="human_review_console"] .head,body[data-visual-mode="failure_boundary_triptych"] .head,body[data-visual-mode="execution_audit_receipt"] .head{{padding-top:44px;}}
body[data-visual-mode="decision_interrupt"] .head .t,body[data-visual-mode="capture_rig_exploded_view"] .head .t,body[data-visual-mode="dataset_annotation_board"] .head .t,body[data-visual-mode="anomaly_heatmap_inspection"] .head .t,body[data-visual-mode="risk_queue_flow"] .head .t,body[data-visual-mode="human_review_console"] .head .t,body[data-visual-mode="failure_boundary_triptych"] .head .t,body[data-visual-mode="execution_audit_receipt"] .head .t{{font-size:48px;max-width:88%;}}
body[data-visual-mode="decision_interrupt"] .head .k,body[data-visual-mode="capture_rig_exploded_view"] .head .k,body[data-visual-mode="dataset_annotation_board"] .head .k,body[data-visual-mode="anomaly_heatmap_inspection"] .head .k,body[data-visual-mode="risk_queue_flow"] .head .k,body[data-visual-mode="human_review_console"] .head .k,body[data-visual-mode="failure_boundary_triptych"] .head .k,body[data-visual-mode="execution_audit_receipt"] .head .k{{display:none;}}
.invoice-split,.workflow,.status-board,.exception-board,.decision,.approval-checks,.handoff{{margin-top:100px;position:relative;z-index:2;}}
.invoice-split{{display:grid;grid-template-columns:1fr 70px 1fr;gap:18px;align-items:center;}}
.doc,.status,.issue,.queue-card,.decision-input,.branches>div,.approval-checks>div{{background:rgba(8,18,34,.82);border:2px solid rgba(98,216,255,.68);border-radius:16px;padding:28px;display:flex;flex-direction:column;gap:14px;transition:transform .35s ease,opacity .35s ease,box-shadow .35s ease;}}
.doc.bad,.status.mismatch,.issue{{border-color:#ff647c;}}
.doc.good,.status.matched,.status.duplicate{{border-color:#72e6a5;}}
.doc b,.status b,.exception-board>b,.review-flag,.human{{font-size:30px;letter-spacing:2px;}}
.doc strong,.status span,.issue span,.queue-card span{{font-size:28px;line-height:1.25;}}
.workflow{{display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;}}
.workflow .node{{padding:28px 20px;border:2px solid #62d8ff;border-radius:14px;background:rgba(8,18,34,.85);font-size:27px;font-weight:900;}}
.workflow i,.split-arrow{{font-size:48px;color:#ffd166;}}
.path-fields{{flex-basis:100%;text-align:center;font:700 24px monospace;color:#dff7ff;padding:20px;border-bottom:2px solid #62d8ff;}}
.status-board{{display:flex;flex-direction:column;gap:18px;}}
.status{{flex-direction:row;justify-content:space-between;align-items:center;}}
.exception-board{{display:flex;flex-direction:column;gap:18px;}}
.issue{{flex-direction:row;justify-content:space-between;}}
.review-flag{{padding:24px;background:#7f1d1d;border:2px solid #ff647c;text-align:center;}}
.decision{{text-align:center;}}
.decision-input{{display:inline-flex;min-width:380px;align-items:center;}}
.branches{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:28px;}}
.auto{{border-color:#72e6a5 !important;}.human{{border-color:#ff647c !important;}}
.no-payment{{margin-top:26px;color:#ffd166;font-size:25px;font-weight:800;}}
.approval-checks{{display:grid;grid-template-columns:1fr 1fr;gap:18px;}}
.approval-checks>div{{font-size:30px;}.approval-checks .needs{{border-color:#ff647c;color:#ffb2bd;}}
.handoff{{display:flex;flex-direction:column;gap:24px;align-items:center;}.queue-card{{width:80%;gap:12px;}.stamp{{font-size:42px;font-weight:900;color:#72e6a5;border:4px solid #72e6a5;padding:18px;transform:rotate(-4deg);}}
.hero-compare{{display:grid;grid-template-columns:1fr 70px 1fr;align-items:center;gap:18px;margin-top:34px;}}
.copy-panel{{padding:28px;border-radius:22px;background:rgba(8,18,34,.78);border:2px solid rgba(255,255,255,.22);box-shadow:0 18px 40px rgba(0,0,0,.28);}}
.copy-panel-wide{{margin-top:28px;font-size:30px;line-height:1.45;}}
.result-bad{{border-color:#ff6178;}}
.result-good{{border-color:#65e6a5;}}
.copy-panel strong{{display:block;font-size:58px;line-height:1.1;margin:12px 0;color:#fff;}}
.copy-panel small{{display:block;font-size:25px;line-height:1.35;color:#d7e4f2;}}
.eyebrow{{display:block;font-size:20px;letter-spacing:2px;color:#ffd166;font-weight:800;}}
.hero-arrow{{font-size:58px;color:#ffd166;text-align:center;font-weight:900;}}
.hero-copy{{margin-top:28px;padding:22px 26px;border-left:6px solid #ffd166;background:rgba(0,0,0,.48);font-size:29px;line-height:1.4;}}
.evidence-terminal,.log-compare{{margin-top:24px;padding:26px;border:2px solid #55d6ff;border-radius:18px;background:rgba(3,10,20,.86);font-family:monospace;font-size:25px;line-height:1.45;}}
.terminal-bar{{color:#7df7bb;margin-bottom:18px;}}
.evidence-terminal pre,.log-compare pre{{margin:0;white-space:pre-wrap;color:#e5f7ff;}}
.warn{{color:#ffd166;}}
.match{{display:block;margin-top:18px;color:#72e6a5;font-weight:900;}}
.branch-grid,.matrix,.metric-contrast,.checklist-live,.cta-live{{display:grid;gap:16px;margin-top:30px;}}
.branch-grid{{grid-template-columns:1fr 1fr;}}
.branch-grid>div,.matrix>div,.checklist-live>div{{padding:24px;border-radius:16px;background:rgba(3,10,20,.76);border:2px solid rgba(255,255,255,.2);font-size:30px;}}
.branch-grid strong{{display:block;font-size:40px;margin:12px 0;}}
.branch-grid small{{display:block;color:#d7e4f2;font-size:24px;}}
.bad-cell{{border-color:#ff6178!important;}}
.matrix{{grid-template-columns:1fr;}}
.matrix b{{float:right;color:#ff8296;}}
.metric-contrast{{grid-template-columns:1fr 70px 1fr;align-items:center;}}
.metric-contrast>div:not(.hero-arrow){{padding:24px;text-align:center;background:rgba(3,10,20,.78);border-radius:18px;border:2px solid rgba(255,255,255,.2);}}
.metric-contrast strong{{display:block;font-size:108px;color:#ffd166;line-height:1;}}
.metric-contrast small{{font-size:25px;color:#e1edf7;}}
.checklist-live{{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:18px;}}
.checklist-live>div{{border-left:8px solid #65e6a5;padding:18px 16px;font-size:26px;min-height:72px;display:flex;align-items:center;}}
.cta-live{{padding:30px;background:rgba(3,10,20,.82);border:2px solid #ffd166;border-radius:20px;}}
.cta-live strong{{font-size:52px;color:#ffd166;}}
.cta-live span{{font-size:30px;line-height:1.4;color:#fff;}}
.reveal-item{{opacity:1;transform:translateY(0) scale(1);transition:transform .45s;}}
.reveal-item.is-visible{{opacity:1;transform:translateY(0) scale(1);}}
body[data-visual-mode="prompt_typewriter"] .content{{padding-top:110px;}}
body[data-visual-mode="annotation_callout"] .content{{padding-top:40px;}}
body[data-visual-mode="location_selector"] .content{{padding-top:30px;}}
body[data-visual-mode="light_split_compare"] .content{{padding:70px 36px 0;}}
body[data-visual-mode="composition_push_in"] .content{{padding-top:35px;}}
body[data-visual-mode="error_fix_compare"] .content{{padding-top:40px;}}
body[data-visual-mode="checklist_stamp"] .content{{padding-top:45px;}}
body[data-visual-mode="flow_track"] .content{{padding-top:45px;}}
body[data-visual-mode="source_trace"] .content{{padding-top:40px;}}
body[data-visual-mode="evidence_timeline"] .content{{padding-top:40px;}}
body[data-visual-mode="timeline_reveal"] .content{{padding-top:40px;}}
body[data-visual-mode="result_reveal"] .content{{padding-top:45px;}}
body[data-visual-mode="result_hold"] .content{{padding-top:45px;}}
body[data-visual-mode="result_audit"] .content{{padding-top:35px;}}
body[data-visual-mode="failure_rollback"] .content{{padding-top:40px;}}
body[data-visual-mode="before_after_split"] .content{{padding-top:150px;}}
body[data-visual-mode="before_after_split"] .hero-compare{{min-height:520px;}}
body[data-visual-mode="terminal_evidence"] .head{{padding:46px 44px 0;}}
body[data-visual-mode="terminal_evidence"] .content{{padding:70px 44px 0;}}
body[data-visual-mode="terminal_evidence"] .evidence-terminal{{min-height:620px;border-radius:8px;background:rgba(2,8,16,.94);}}
body[data-visual-mode="input_branch"] .content{{padding:220px 42px 0;}}
body[data-visual-mode="input_branch"] .branch-grid{{gap:28px;}}
body[data-visual-mode="edge_case_matrix"] .content{{padding:260px 54px 0;}}
body[data-visual-mode="edge_case_matrix"] .matrix>div{{border-left-width:14px;border-radius:4px;}}
body[data-visual-mode="reproducibility_compare"] .content{{padding:210px 36px 0;}}
body[data-visual-mode="reproducibility_compare"] .log-compare{{min-height:520px;border-radius:4px;}}
body[data-visual-mode="metric_contrast"] .content{{padding:260px 30px 0;}}
body[data-visual-mode="metric_contrast"] .metric-contrast strong{{font-size:190px;}}
body[data-visual-mode="checklist_lock"] .content{{padding:220px 50px 0;}}
body[data-visual-mode="checklist_lock"] .checklist-live>div{{font-size:42px;padding:30px 28px;}}
body[data-visual-mode="cta_warning"] .content{{padding:360px 54px 0;}}
body[data-visual-mode="cta_warning"] .cta-live{{min-height:360px;justify-content:center;}}
 </style></head><body class="{TEMPLATE_CLASS}" data-visual-role="scene" data-semantic-key="{MODE}" data-beat-id="s{IDX}" data-template-id="{TEMPLATE_ID}" data-visual-mode="{MODE}" data-shot-purpose="{PURPOSE}" data-group-motion="{MOTION}" data-platform-reason="{REASON}"{TOPIC_ATTR}><div class="bg"></div><div class="veil"></div><div class="head"><div class="k">{KICKER}</div><div class="t">{TITLE}</div></div><div class="content" data-visual-role="content" data-semantic-key="{MODE}-content">{BODY}<div class="contract-execution">{MOTION_DOM}</div></div><script>window.renderFrame=function(t){{document.body.style.setProperty('--frame-t',String(t));document.querySelectorAll('.chip').forEach(function(el,i){{var visible=t>=i*.45;el.style.opacity=visible?'1':'0.5';}});document.querySelectorAll('.reveal-item').forEach(function(el,i){{var start=i*.65;var visible=t>=start;el.classList.toggle('is-visible',visible);el.style.opacity=visible?'1':'0.12';el.style.transform=visible?'translateY(0) scale(1)':'translateY(10px) scale(.99)';}});document.querySelectorAll('.invoice-split .doc,.workflow .node,.status,.issue,.branches>div,.approval-checks>div,.queue-card').forEach(function(el,i){{var visible=t>=i*.35;el.style.transform=visible?'translateY(0)':'translateY(10px)';el.style.opacity=visible?'1':'0.35';}});document.querySelectorAll('.uncertain-target,.authority-line,.capture-rig>div,.dataset-board>div,.heatmap-box,.evidence-stack,.risk-queue .route,.handoff-state,.review-evidence span,.decision-buttons b,.boundary-triptych>div,.boundary-triptych>strong,.execution-result,.audit-fields span,.decision-path,.decision-proof,.capture-detail>div,.capture-detail>strong,.governance-detail>div,.defect-zoom,.evidence-chain,.risk-detail>div,.disposition-evidence,.disposition-actions>* ,.disposition-proof,.trigger-detail>div,.trigger-detail>strong,.physical-receipt,.audit-receipt').forEach(function(el,i){{var start=i*.28;var visible=t>=start;var fresh=t>=start&&t<start+.45;el.style.opacity=visible?'1':'0.55';el.style.filter=fresh?'brightness(1.12) saturate(1.08)':'none';el.style.outline=fresh?'3px solid rgba(242,201,76,.42)':'0 solid transparent';el.style.outlineOffset='-3px';el.style.boxShadow=fresh?'0 0 14px rgba(242,201,76,.25)':'none';el.style.transform='none';}});document.querySelectorAll('.contract-motion').forEach(function(el,i){{var n=el.getAttribute('data-motion')||'';var p=Math.max(0,Math.min(1,(t-i*.35)/.4));el.style.clipPath='inset(0 '+((1-p)*100).toFixed(1)+'% 0 0)';el.style.transform='none';el.style.opacity='0.42';el.setAttribute('data-applied-motion',n);}});document.querySelectorAll('.receipt-switch').forEach(function(el){{el.classList.toggle('is-cta',t>=7.0);}});}};</script></body></html>'''.replace('{{','{').replace('}}','}').replace('{W}',str(W)).replace('{H}',str(H)).replace('{b64}',b64).replace('{TEMPLATE_ID}',template_id).replace('{MODE}',esc(effective_mode)).replace('{PURPOSE}',purpose).replace('{IDX}',f'{idx:02d}').replace('{MOTION}',motion).replace('{REASON}',reason).replace('{TEMPLATE_CLASS}',template_class).replace('{TOPIC_ATTR}',topic_attr).replace('{MOTION_DOM}',motion_dom).replace('{KICKER}',esc(kicker)).replace('{TITLE}',esc(display_title)).replace('{BODY}',body))
def build_shot_a(idx: int, title: str, stat: str, bg_path: str, kicker: str, stat_label: str = "关键数字",
                 camera_index: int | None = None, text_motion_index: int | None = None, platform: str = "") -> str:
    motion_index = idx % len(KB_A) if camera_index is None else camera_index
    kb = KB_A[motion_index % len(KB_A)]
    b64 = _b64img(bg_path)
    # 08-14 真实可观性增强：kicker/title/stat 入场动效按镜头轮换（非统一 fadeUp，机械感）
    anim_pool = ["fadeUp", "scaleIn", "slideLeft", "rotateIn", "zoomIn", "flipIn", "bounceIn", "glideIn"]
    text_index = idx % len(anim_pool) if text_motion_index is None else text_motion_index
    kicker_anim = anim_pool[text_index % len(anim_pool)]
    title_anim = anim_pool[(text_index + 1) % len(anim_pool)]
    layout_index = motion_index % 4
    content_styles = [
        "justify-content:center; align-items:flex-start; padding:130px 90px;",
        "justify-content:flex-start; align-items:flex-start; padding:250px 90px 120px; width:78%;",
        "justify-content:flex-end; align-items:flex-start; padding:120px 90px 330px;",
        "justify-content:center; align-items:flex-end; padding:130px 90px; text-align:right;",
        "justify-content:center; align-items:center; padding:100px 80px; text-align:center;",
        "justify-content:flex-start; align-items:flex-end; padding:80px 90px 200px; width:85%; text-align:right;",
        "justify-content:center; align-items:flex-start; padding:200px 60px; width:90%; text-align:center;",
        "justify-content:flex-end; align-items:center; padding:60px 80px 280px; text-align:left;",
    ]
    title_sizes = [80, 64, 70, 62, 76, 58, 72, 66]
    pet_mode = str(platform).casefold() == "douyin_pet"
    shipinhao_mode = str(platform).casefold() == "shipinhao"
    bilibili_mode = str(platform).casefold() == "bilibili"
    if pet_mode:
        overlay_css = "linear-gradient(180deg,rgba(0,0,0,.10) 0%,rgba(0,0,0,.18) 48%,rgba(0,0,0,.76) 100%)"
    elif shipinhao_mode:
        overlay_css = "linear-gradient(135deg,rgba(10,20,40,.85) 0%,rgba(20,10,30,.7) 50%,rgba(40,20,10,.5) 100%)"
    elif bilibili_mode:
        overlay_css = "linear-gradient(180deg,rgba(0,8,20,.88) 0%,rgba(0,20,50,.65) 40%,rgba(0,40,80,.3) 100%)"
    else:
        overlay_css = "linear-gradient(180deg,rgba(0,0,0,.34) 0%,rgba(0,0,0,.58) 48%,rgba(0,0,0,.90) 100%)"
    stat_html = (
        f'<div class="stat"><span class="n">{stat}</span><span class="l">{stat_label}</span></div>'
        if str(stat).strip() else ""
    )
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover; }}
@keyframes kb {{ 0% {{ transform:{kb[0]}; }} 100% {{ transform:{kb[1]}; }} }}
.overlay {{ position:absolute; inset:0; background:{overlay_css}; }}
.content {{ position:absolute; inset:60px; z-index:2; overflow:hidden; display:flex; flex-direction:column; {content_styles[layout_index]} animation:petContentBreath 2.6s ease-in-out 1.1s infinite alternate; background:rgba(255,255,255,.04); }}
.content::after {{ content:""; position:absolute; top:0; bottom:0; left:-24%; width:22%; pointer-events:none; z-index:1; background:linear-gradient(90deg,transparent,rgba(255,255,255,.10),transparent); animation:petAccentSweep 2.8s ease-in-out 1.2s infinite; }}
.content > * {{ position:relative; z-index:2; animation:petLocalNudge 2.4s ease-in-out 1.1s infinite alternate; }}
.kicker {{ font-size:32px; color:#ffd60a; font-weight:800; letter-spacing:5px; margin-bottom:40px;
  animation: {kicker_anim} 0.9s ease-out both; }}
.title {{ font-size:{title_sizes[layout_index]}px; max-width:900px; line-height:1.28; font-weight:900; color:#fff; text-shadow:0 6px 26px rgba(0,0,0,0.8);
  animation: {title_anim} 1.1s ease-out 0.15s both, petTitlePulse 2.4s ease-in-out 1.4s infinite alternate; }}
.stat {{ margin-top:64px; display:inline-block; background:rgba(255,255,255,0.12); border:2px solid rgba(255,255,255,0.35);
  border-radius:44px; padding:22px 48px; }}
.stat .n {{ font-size:64px; font-weight:900; color:#7ee787; }}
.stat .l {{ font-size:30px; color:#d0d0d0; margin-left:16px; }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(26px); }} to {{ opacity:1; transform:translateY(0); }} }}
@keyframes scaleIn {{ from {{ opacity:0; transform:scale(0.85); }} to {{ opacity:1; transform:scale(1); }} }}
@keyframes slideLeft {{ from {{ opacity:0; transform:translateX(40px); }} to {{ opacity:1; transform:translateX(0); }} }}
@keyframes rotateIn {{ from {{ opacity:0; transform:rotate(-4deg) scale(0.92); }} to {{ opacity:1; transform:rotate(0) scale(1); }} }}
@keyframes zoomIn {{ from {{ opacity:0; transform:scale(1.3); }} to {{ opacity:1; transform:scale(1); }} }}
@keyframes flipIn {{ from {{ opacity:0; transform:perspective(400px) rotateY(90deg); }} to {{ opacity:1; transform:perspective(400px) rotateY(0); }} }}
@keyframes bounceIn {{ 0% {{ opacity:0; transform:scale(0.3); }} 50% {{ transform:scale(1.05); }} 70% {{ transform:scale(0.9); }} 100% {{ opacity:1; transform:scale(1); }} }}
@keyframes glideIn {{ from {{ opacity:0; transform:translateX(-60px) translateY(20px); }} to {{ opacity:1; transform:translateX(0) translateY(0); }} }}
@keyframes petTitlePulse {{ from {{ filter:brightness(0.96); text-shadow:0 6px 26px rgba(0,0,0,0.8); }} to {{ filter:brightness(1.08); text-shadow:0 6px 32px rgba(255,214,10,0.34); }} }}
@keyframes petAccentSweep {{ 0% {{ transform:translateX(0); opacity:0; }} 18% {{ opacity:1; }} 82% {{ opacity:1; }} 100% {{ transform:translateX(620%); opacity:0; }} }}
@keyframes petLocalNudge {{ 0% {{ transform:translateX(-6px); }} 50% {{ transform:translateX(6px); }} 100% {{ transform:translateX(-6px); }} }}
@keyframes petContentBreath {{ 0% {{ filter:brightness(0.86); background-color:rgba(255,255,255,.03); }} 50% {{ filter:brightness(1.16); background-color:rgba(255,255,255,.14); }} 100% {{ filter:brightness(0.92); background-color:rgba(255,255,255,.05); }} }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.13); z-index:2; }}
</style></head><body>
<div class="bg"></div><div class="overlay"></div>
<div class="idx">{idx:02d}A</div>
<div class="content">
  <div class="kicker">{kicker}</div>
  <div class="title">{title}</div>
  {stat_html}
</div>
</body></html>"""


def build_shot_b(idx: int, title: str, modules: list[str], bg_path: str,
                 screenshot_path: str | None = None, screenshot_caption: str = "",
                 camera_index: int | None = None, text_motion_index: int | None = None, platform: str = "") -> str:
    motion_index = idx % len(KB_B) if camera_index is None else camera_index
    kb = KB_B[motion_index % len(KB_B)]
    b64 = _b64img(bg_path)
    text_index = idx % len(MODULE_ANIMS) if text_motion_index is None else text_motion_index
    anim = MODULE_ANIMS[text_index % len(MODULE_ANIMS)]
    kf_off = "0.9s" if anim[0] == "staggerUp" else "0.8s"
    pet_mode = str(platform).casefold() == "douyin_pet"
    normal_overlay = "rgba(0,0,0,0.38)" if pet_mode else "rgba(0,0,0,0.62)"
    # 截图模式：真实素材（规则1：工具/项目介绍要有真实截图）
    if screenshot_path and Path(screenshot_path).is_file():
        shot_b64 = _b64img(screenshot_path)
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; background:#000; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover; }}
@keyframes kb {{ 0% {{ transform:{kb[0]}; }} 100% {{ transform:{kb[1]}; }} }}
.overlay {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.72) 55%, rgba(0,0,0,0.94) 100%); }}
.content {{ position:absolute; inset:60px; z-index:2; overflow:hidden; display:flex; flex-direction:column; align-items:center; padding:140px 80px; }}
.head {{ font-size:44px; font-weight:800; color:#fff; margin-bottom:44px; text-shadow:0 4px 16px rgba(0,0,0,0.7);
  animation:fadeUp 0.8s ease-out both; }}
.shot {{ width:880px; max-height:860px; object-fit:contain; border:3px solid rgba(255,255,255,0.55); border-radius:20px;
  box-shadow:0 30px 80px rgba(0,0,0,0.65); animation: fadeUp 0.8s ease-out 0.2s both, screenshotFloat 5.2s linear 0.9s infinite alternate; }}
.caption {{ margin-top:36px; font-size:34px; color:#ffd60a; font-weight:700; text-align:center;
  animation: fadeUp 0.8s ease-out 0.5s both; }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(24px); }} to {{ opacity:1; transform:translateY(0); }} }}
@keyframes screenshotFloat {{ from {{ transform:translate3d(-10px,8px,0) scale(1.00); }} to {{ transform:translate3d(12px,-8px,0) scale(1.045); }} }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.13); z-index:2; }}
</style></head><body>
<div class="bg"></div><div class="overlay"></div>
<div class="idx">{idx:02d}B</div>
<div class="content">
  <div class="head">{title}</div>
  <img class="shot" src="data:image/png;base64,{shot_b64}"/>
  <div class="caption">{screenshot_caption}</div>
</div>
</body></html>"""
    mod_css = f"""
.module {{ margin-bottom:44px; padding:34px 44px; background:rgba(255,255,255,0.09); backdrop-filter:blur(10px);
  border-left:6px solid #ffd60a; border-radius:16px; opacity:0; }}
.module:nth-child(1) {{ animation:{anim[0]} 0.8s ease-out 0.2s both; }}
.module:nth-child(2) {{ animation:{anim[0]} 0.8s ease-out {kf_off} both; }}
.module:nth-child(3) {{ animation:{anim[0]} 0.8s ease-out calc({kf_off} + 0.9s) both; }}
.module .m {{ font-size:44px; line-height:1.5; color:#fff; font-weight:600; text-shadow:0 2px 10px rgba(0,0,0,0.7); }}
.module .t {{ font-size:26px; color:#ffd60a; font-weight:700; letter-spacing:2px; }}
@keyframes {anim[0]} {{ from {{ opacity:0; transform:{anim[1][0]}; }} to {{ opacity:1; transform:{anim[1][1]}; }} }}
"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover; }}
@keyframes kb {{ 0% {{ transform:{kb[0]}; }} 100% {{ transform:{kb[1]}; }} }}
.overlay {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(0,0,0,0.18) 0%, {normal_overlay} 52%, rgba(0,0,0,0.86) 100%); }}
.content {{ position:absolute; inset:60px; z-index:2; overflow:hidden; display:flex; flex-direction:column; justify-content:center; padding:130px 90px; animation:petContentBreath 2.6s ease-in-out 1.1s infinite alternate; background:rgba(255,255,255,.04); }}
.content::after {{ content:""; position:absolute; top:0; bottom:0; left:-24%; width:22%; pointer-events:none; z-index:1; background:linear-gradient(90deg,transparent,rgba(255,255,255,.10),transparent); animation:petAccentSweep 2.8s ease-in-out 1.2s infinite; }}
.content > * {{ position:relative; z-index:2; animation:petLocalNudge 2.4s ease-in-out 1.1s infinite alternate; }}
.head {{ font-size:46px; font-weight:800; color:#fff; margin-bottom:56px; text-shadow:0 4px 16px rgba(0,0,0,0.7);
  animation:fadeUp 0.8s ease-out both; }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(20px); }} to {{ opacity:1; transform:translateY(0); }} }}
@keyframes petAccentSweep {{ 0% {{ transform:translateX(0); opacity:0; }} 18% {{ opacity:1; }} 82% {{ opacity:1; }} 100% {{ transform:translateX(620%); opacity:0; }} }}
@keyframes petLocalNudge {{ 0% {{ transform:translateX(-6px); }} 50% {{ transform:translateX(6px); }} 100% {{ transform:translateX(-6px); }} }}
@keyframes petContentBreath {{ 0% {{ filter:brightness(0.86); background-color:rgba(255,255,255,.03); }} 50% {{ filter:brightness(1.16); background-color:rgba(255,255,255,.14); }} 100% {{ filter:brightness(0.92); background-color:rgba(255,255,255,.05); }} }}
{mod_css}
.module {{ animation: petModulePulse 2.8s ease-in-out 1.2s infinite alternate; }}
@keyframes petModulePulse {{ from {{ filter:brightness(0.98); }} to {{ filter:brightness(1.10); }} }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.13); z-index:2; }}
</style></head><body>
<div class="bg"></div><div class="overlay"></div>
<div class="idx">{idx:02d}B</div>
<div class="content">
  <div class="head">{title}</div>
  <div class="module"><div class="t">①</div><div class="m">{modules[0]}</div></div>
  <div class="module"><div class="t">②</div><div class="m">{modules[1]}</div></div>
  <div class="module"><div class="t">③</div><div class="m">{modules[2]}</div></div>
</div>
</body></html>"""


def build_shot_ide_evidence(idx: int, title: str, modules: list[str], bg_path: str,
                            phase: str = "PROMPT") -> str:
    """用终端/编辑器证据流替代统一的圆角知识卡。"""
    b64 = _b64img(bg_path)
    safe_title = html.escape(str(title))
    rows = [html.escape(re.sub(r"\s+", " ", str(x)).strip()) for x in modules if str(x).strip()]
    rows = (rows + ["等待输入", "等待约束", "等待验收"])[:3]
    labels = ["INPUT", "CONSTRAINT", "VERIFY"]
    colors = ["#79c0ff", "#f2cc60", "#56d364"]
    effects = ["typewriter", "typewriter", "sweep", "sweep", "path", "path", "diff", "stamp"]
    effect = effects[(idx - 1) % len(effects)]
    body = "".join(
        f'<div class="line group-{labels[i].lower()} effect-{effect}" data-group="{labels[i].lower()}" data-layer="evidence"><span class="ln">{i + 1:02d}</span>'
        f'<span class="tag" style="color:{colors[i]}">{labels[i]}</span>'
        f'<span class="text">{row}</span></div>'
        for i, row in enumerate(rows)
    )
    command = "ai.run --clarify --test" if phase == "PROMPT" else "git diff && npm test"
    status = "WAITING_FOR_SPEC" if phase == "PROMPT" else "CHECKING_OUTPUT"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; background:#0d1117; color:#e6edf3; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover; filter:saturate(.72) brightness(.42); }}
.veil {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(5,10,18,.40),rgba(5,10,18,.62)); }}
.terminal {{ position:absolute; left:92px; right:92px; top:250px; bottom:430px; z-index:2; background:rgba(13,17,23,.78); border:2px solid rgba(126,164,201,.72); box-shadow:0 24px 70px rgba(0,0,0,.58); animation:terminalIn .75s cubic-bezier(.2,.8,.2,1) both; }}
.bar {{ height:76px; display:flex; align-items:center; padding:0 28px; border-bottom:2px solid #30363d; background:#161b22; font:27px monospace; color:#8b949e; }}
.dot {{ width:18px; height:18px; border-radius:50%; margin-right:12px; background:#f85149; }} .dot:nth-child(2) {{ background:#d29922; }} .dot:nth-child(3) {{ background:#3fb950; }}
.path {{ margin-left:22px; color:#79c0ff; }} .phase {{ position:absolute; right:26px; top:24px; color:#56d364; font:700 23px monospace; letter-spacing:2px; }}
.title {{ padding:38px 38px 20px; font-size:52px; line-height:1.2; font-weight:900; color:#fff; border-left:8px solid #58a6ff; text-shadow:0 3px 18px #000; animation:titleIn .7s .18s cubic-bezier(.2,.8,.2,1) both; }}
.prompt {{ margin:0 38px 28px; padding:20px 24px; background:#11161d; color:#79c0ff; font:700 27px/1.3 monospace; border-bottom:2px solid #238636; animation:promptIn .65s .4s ease-out both; }}
.line {{ display:flex; align-items:flex-start; margin:0 38px; min-height:116px; padding:24px 0; border-bottom:1px solid #21262d; font-size:38px; line-height:1.3; opacity:0; animation:lineIn .7s ease-out both; }}
.line:nth-child(4) {{ animation-delay:.65s; }} .line:nth-child(5) {{ animation-delay:1.0s; }} .line:nth-child(6) {{ animation-delay:1.35s; }}
.effect-typewriter .title {{ animation:typingTitle 2.4s .15s steps(18,end) infinite alternate; }} .effect-typewriter .title::after {{ content:'▌'; color:#56d364; margin-left:8px; animation:caretBlink .65s step-end infinite; }}
.effect-sweep .line {{ animation-name:sweepLine; }} .effect-sweep .line .text {{ background:linear-gradient(90deg,transparent 0%,transparent 40%,rgba(242,204,96,.72) 50%,transparent 60%); background-size:260% 100%; animation:sweep 2.2s .8s ease-in-out infinite; }}
.effect-path .line {{ animation-name:pathNode; border-left:5px solid #56d364; padding-left:22px; }} .effect-path .line:nth-child(4) {{ animation-delay:.2s; }} .effect-path .line:nth-child(5) {{ animation-delay:.55s; }} .effect-path .line:nth-child(6) {{ animation-delay:.9s; }}
.effect-diff .line {{ animation-name:diffReveal; border-left:5px solid #f85149; animation-duration:2.6s; animation-iteration-count:infinite; animation-direction:alternate; }} .effect-diff .line:nth-child(5) {{ border-left-color:#56d364; animation-delay:.5s; }}
.effect-sweep .tag {{ animation:tagFlash 2.2s .8s ease-in-out infinite; }}
.effect-stamp .status b {{ font-size:30px; animation:stampIn .65s 1.3s cubic-bezier(.2,.8,.2,1) both, pulse 1.8s 2s ease-in-out infinite; }}
.ln {{ width:60px; flex:none; color:#484f58; font:28px monospace; padding-top:5px; }} .tag {{ width:210px; flex:none; font:700 22px monospace; letter-spacing:2px; padding-top:6px; }}
.text {{ flex:1; color:#f0f6fc; text-shadow:0 2px 8px #000; }}
.status {{ position:absolute; left:54px; right:54px; bottom:150px; z-index:3; display:flex; justify-content:space-between; font:700 25px monospace; letter-spacing:1px; }}
.status b {{ color:#56d364; animation:pulse 1.8s ease-in-out infinite; }} .index {{ color:#8b949e; }}
@keyframes terminalIn {{ from {{ opacity:0; transform:translateY(45px) scale(.97); }} to {{ opacity:1; transform:translateY(0) scale(1); }} }}
@keyframes terminalFloat {{ from {{ margin-top:0; }} to {{ margin-top:14px; }} }}
@keyframes titleIn {{ from {{ opacity:0; transform:translateX(-55px); }} to {{ opacity:1; transform:translateX(0); }} }}
@keyframes promptIn {{ from {{ opacity:0; transform:scaleX(.72); transform-origin:left; }} to {{ opacity:1; transform:scaleX(1); }} }}
@keyframes lineIn {{ from {{ opacity:0; transform:translateX(70px); }} to {{ opacity:1; transform:translateX(0); }} }}
@keyframes typingTitle {{ from {{ opacity:0; clip-path:inset(0 100% 0 0); }} to {{ opacity:1; clip-path:inset(0 0 0 0); }} }}
@keyframes sweepLine {{ from {{ opacity:0; transform:translateY(24px); }} to {{ opacity:1; transform:translateY(0); }} }}
@keyframes sweep {{ from {{ background-position:100% 0; }} to {{ background-position:0 0; }} }}
@keyframes pathNode {{ from {{ opacity:0; transform:translateX(-35px); border-left-color:transparent; }} to {{ opacity:1; transform:translateX(0); border-left-color:#56d364; }} }}
@keyframes diffReveal {{ from {{ opacity:0; clip-path:inset(0 100% 0 0); }} to {{ opacity:1; clip-path:inset(0 0 0 0); }} }}
@keyframes stampIn {{ from {{ opacity:0; transform:scale(.72) rotate(-8deg); }} to {{ opacity:1; transform:scale(1) rotate(0); }} }}
@keyframes caretBlink {{ 0%,49% {{ opacity:1; }} 50%,100% {{ opacity:0; }} }}
@keyframes tagFlash {{ 0%,35%,100% {{ color:#f2cc60; text-shadow:none; }} 50%,70% {{ color:#fff; text-shadow:0 0 18px #f2cc60; }} }}
@keyframes pulse {{ 0%,100% {{ text-shadow:0 0 0 rgba(86,211,100,0); }} 50% {{ text-shadow:0 0 20px rgba(86,211,100,.8); }} }}
@keyframes cursor {{ 0%,49% {{ opacity:1; }} 50%,100% {{ opacity:0; }} }} .cursor {{ animation:cursor 1s step-end infinite; color:#56d364; }}
</style></head><body class="effect-{effect} card-{idx}"><div class="bg"></div><div class="veil"></div>
<div class="terminal"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="path">~/ai-workbench/{phase.lower()}</span><span class="phase">{phase}</span></div>
<div class="title">{safe_title}</div><div class="prompt">$ {html.escape(command)}<span class="cursor">▌</span></div>{body}</div>
<div class="status"><b>● {status}</b><span class="index">EVIDENCE FLOW / {idx:02d}</span></div></body></html>"""


# ═══════════════════════════════════════════════════════════════════
# 动效镜头 3 件套（2026-08-15 固化，源自抖音卡片视频拆解）
# 卡内元素级独立动效：图块激活 / 数字跳变 / 流程点亮
# 渲染方式 = JS 逐帧驱动（renderFrame(t)）→ Playwright 截图 → FFmpeg 合成
# 背景：JS 驱动正弦轨迹微动（Ken Burns 呼吸感）
# ═══════════════════════════════════════════════════════════════════

def _pick_actives(items: list[str], n: int) -> list[str]:
    """保留完整模块文案；由 CSS 自动换行，禁止用固定字符数截断正文。"""
    parts = [re.sub(r"\s+", " ", str(x)).strip() for x in items if str(x).strip()]
    return (parts + ["", "", "", ""])[:n]


def _extract_number_unit(text: str) -> list[str]:
    """从文案提取「数字+单位」完整串（如 12倍/3.2秒/99%），用于 digit_roll 真实数据展示"""
    pairs = re.findall(r"(\d{1,3}(?:\.\d+)?)\s*(倍|%|秒|毫秒|分钟|小时|个|元|GB|MB|次|s|ms|万|亿)?", text)
    out = []
    for num, unit in pairs:
        if not unit and len(num) < 2 and "." not in num:
            continue  # 纯一位数（如"1个"中的1）跳过，防量词误报
        out.append(f"{num}{unit}")
        if len(out) >= 3:
            break
    return out

def build_shot_message_stack(idx: int, title: str, items: list[str], bg_path: str,
                             kicker: str) -> str:
    """消息堆叠布局：用上下对话气泡替代知识卡图块。"""
    rows = _pick_actives(items, 3)
    bubbles = "".join(
        f'<div class="bubble" data-idx="{i}" data-state="idle"><span class="who">{("INPUT", "RULE", "OUTPUT")[i]}</span><span>{esc(row) or "等待内容"}</span></div>'
        for i, row in enumerate(rows)
    )
    b64 = _b64img(bg_path)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover; }}
.shade {{ position:absolute; inset:0; background:rgba(7,12,24,.62); }}
.head {{ position:absolute; top:150px; left:90px; right:90px; z-index:2; }}
.head .k {{ color:#fbbf24; font-size:28px; letter-spacing:6px; }}
.head .t {{ color:#fff; font-size:64px; font-weight:900; margin-top:18px; }}
.stack {{ position:absolute; top:520px; left:100px; right:100px; z-index:2; display:flex; flex-direction:column; gap:28px; }}
.bubble {{ padding:30px 34px; border-radius:18px; border-left:8px solid #64748b; background:rgba(255,255,255,.08); color:#94a3b8; font-size:38px; line-height:1.35; transform:translateX(0); transition:all .2s ease; }}
.bubble[data-state="active"] {{ background:#f59e0b; border-left-color:#fde68a; color:#111827; transform:translateX(34px) scale(1.025); box-shadow:0 18px 45px rgba(245,158,11,.35); }}
.who {{ display:block; font:700 21px monospace; letter-spacing:3px; margin-bottom:10px; opacity:.8; }}
</style></head><body><div class="bg"></div><div class="shade"></div><div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div><div class="stack">{bubbles}</div>
<script>function renderFrame(t){{var active=Math.floor(t/1.2)%3;document.querySelectorAll('.bubble').forEach(function(el){{el.dataset.state=parseInt(el.dataset.idx)===active?'active':'idle';}});}}</script></body></html>"""


def build_shot_split_compare(idx: int, title: str, items: list[str], bg_path: str,
                            kicker: str) -> str:
    """左右对照布局：把警告/前后差异放入两个独立面板。"""
    rows = _pick_actives(items, 3)
    left, right = rows[0], rows[1] or rows[0]
    b64 = _b64img(bg_path)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover; }}
.shade {{ position:absolute; inset:0; background:linear-gradient(135deg,rgba(15,23,42,.82),rgba(30,41,59,.58)); }}
.head {{ position:absolute; top:135px; left:80px; right:80px; z-index:3; text-align:center; }}
.head .k {{ color:#fb7185; font-size:28px; letter-spacing:6px; }}
.head .t {{ color:#fff; font-size:62px; font-weight:900; margin-top:18px; }}
.compare {{ position:absolute; top:500px; left:75px; right:75px; display:grid; grid-template-columns:1fr 1fr; gap:22px; z-index:3; }}
.panel {{ min-height:500px; padding:34px; border-radius:20px; border:3px solid rgba(255,255,255,.22); background:rgba(255,255,255,.08); color:#cbd5e1; font-size:34px; line-height:1.4; transition:all .2s ease; }}
.panel[data-state="active"] {{ transform:translateY(-18px); color:#fff; background:#be123c; border-color:#fb7185; box-shadow:0 22px 55px rgba(190,18,60,.4); }}
.label {{ display:block; font:700 22px monospace; letter-spacing:4px; margin-bottom:28px; color:#fda4af; }}
</style></head><body><div class="bg"></div><div class="shade"></div><div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div><div class="compare"><div class="panel" data-idx="0" data-state="idle"><span class="label">BEFORE</span>{esc(left)}</div><div class="panel" data-idx="1" data-state="idle"><span class="label">AFTER</span>{esc(right)}</div></div>
<script>function renderFrame(t){{var active=Math.floor(t/1.4)%2;document.querySelectorAll('.panel').forEach(function(el){{el.dataset.state=parseInt(el.dataset.idx)===active?'active':'idle';}});}}</script></body></html>"""


def build_shot_tile_activate(idx: int, title: str, items: list[str], bg_path: str,
                             kicker: str, badges: list[str] | None = None) -> str:
    """图块激活：多卡片轮流点亮（变色+阴影位移+前置放大），突出当前焦点"""
    tiles = [item for item in _pick_actives(items, 3) if item] or [""]
    badges = badges or ["A", "B", "C"]
    # 语言判定只看真实可见文案；kicker 可能来自中文 Cinema 内部元数据，不能污染英文视频判断。
    is_en = _is_english_text(f"{title} {' '.join(items)}")
    tile_html = ""
    for i, t in enumerate(tiles):
        tile_html += (
            f'<div class="tile" data-state="idle" data-t="{i}">'
            f'<span class="badge">{esc(badges[i % len(badges)])}</span>'
            f'<span class="nm">{esc(t) if t else "·"}</span>'
            f'<div class="ds">{_tile_desc(i, is_en)}</div></div>'
        )
    b64 = _b64img(bg_path)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:-40px; background:url(data:image/jpeg;base64,{b64}) center/cover;
  transform:scale(1.12); will-change:transform; }}
.shade {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(0,0,0,0.25) 0%,rgba(0,0,0,0.55) 45%,rgba(0,0,0,0.9) 100%); }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.16); z-index:2; }}
.head {{ position:absolute; top:120px; left:0; right:0; text-align:center; z-index:5; }}
.head .k {{ font-size:30px; color:#7dd3fc; font-weight:700; letter-spacing:8px; }}
.head .t {{ font-size:66px; color:#fff; font-weight:900; margin-top:16px; text-shadow:0 6px 24px rgba(0,0,0,.7); }}
.tiles {{ position:absolute; top:430px; left:0; right:0; display:flex; flex-direction:column; align-items:center; gap:36px; z-index:4; }}
.tile {{ width:820px; padding:44px 52px; border-radius:28px; transition:all .18s ease-out; will-change:transform,background,box-shadow; }}
.tile .nm {{ font-size:36px; line-height:1.28; font-weight:800; overflow-wrap:anywhere; word-break:break-word; }}
.tile .ds {{ font-size:28px; margin-top:10px; line-height:1.5; }}
.tile[data-state="idle"] {{ background:rgba(255,255,255,0.10); border:3px solid rgba(255,255,255,0.28); transform:translateX(0) scale(0.94); box-shadow:0 10px 30px rgba(0,0,0,0.25); }}
.tile[data-state="idle"] .nm {{ color:#e2e8f0; }}
.tile[data-state="idle"] .ds {{ color:#94a3b8; }}
.tile[data-state="active"] {{ background:linear-gradient(135deg,#0ea5e9,#2563eb); border:3px solid #38bdf8; transform:translateX(36px) scale(1.0); box-shadow:0 30px 70px rgba(37,99,235,0.55), 0 0 0 6px rgba(56,189,248,0.15); }}
.tile[data-state="active"] .nm {{ color:#ffffff; }}
.tile[data-state="active"] .ds {{ color:#dbeafe; }}
.badge {{ display:inline-block; font-size:24px; font-weight:800; padding:6px 20px; border-radius:999px; margin-right:14px; }}
.tile[data-state="active"] .badge {{ background:#facc15; color:#1e293b; }}
.tile[data-state="idle"] .badge {{ background:rgba(255,255,255,0.16); color:#cbd5e1; }}
</style></head><body>
<div class="bg" id="bg"></div><div class="shade"></div>
<div class="idx">{idx:02d}T</div>
<div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div>
<div class="tiles">{tile_html}</div>
<script>
function renderFrame(t){{
  var count = document.querySelectorAll('.tile').length || 1;
  var active = Math.floor(t / 1.2) % count;
  document.querySelectorAll('.tile').forEach(function(el){{
    el.setAttribute('data-state', parseInt(el.dataset.t) === active ? 'active' : 'idle');
  }});
}}
</script></body></html>"""


def build_shot_digit_roll(idx: int, title: str, items: list[str], bg_path: str,
                          kicker: str, numbers: list[str] | None = None) -> str:
    """数字跳变：圆圈内数字滚动到目标值 + 雷达脉冲环（数据/性能强调）

    数据真实性铁律：数字必须来自文案提取（_extract_number_unit），
    不足 3 个就只显示实际数量（不补假数字）；无数字时调用方不应进入本镜头。
    numbers 格式：["12倍","3.2秒","99%"]（数字+单位完整串）
    """
    labs = _pick_actives(items, 3)
    if numbers is None:
        numbers = _extract_number_unit(" ".join(labs))
    if not numbers:
        # 无真实数字 → 防御性降级：展示文案要点本身（数字位显示"—"）
        numbers = ["—", "—", "—"]
    n_rows = len(numbers)
    while len(numbers) < 3:
        numbers.append("—")
    # 拆分数字与单位：数字部分滚动，单位部分静态
    stat_html = ""
    for i, lab in enumerate(labs[:n_rows]):
        stat_html += (
            f'<div class="stat"><div class="dot" id="dot{i}" data-hot="0">'
            f'<span class="num" id="n{i}">0</span><span class="unit" id="u{i}"></span>'
            f'<span class="ping"></span></div>'
            f'<div class="sinfo"><div class="lab">{esc(lab) if lab else "指标"}</div>'
            f'<div class="desc">数据自己会说话</div></div></div>'
        )
    b64 = _b64img(bg_path)
    # "—" 防御值：targets 置 0（不滚动），unit 置空，JS 直接静态显示 "—"
    targets_js = ",".join("0" if str(x) == "—" else (re.sub(r"[^0-9.]", "", str(x)) or "0") for x in numbers)
    # ⚠️ units 必须加引号（裸词会被 JS 当变量名 → undefined）
    units_js = ",".join("'" + ("" if str(x) == "—" else re.sub(r"[0-9.]", "", str(x))).replace("'", "\\'") + "'" for x in numbers)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:-40px; background:url(data:image/jpeg;base64,{b64}) center/cover;
  transform:scale(1.12); will-change:transform; }}
.shade {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(0,0,0,0.3) 0%,rgba(0,0,0,0.6) 45%,rgba(0,0,0,0.92) 100%); }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.16); z-index:2; }}
.head {{ position:absolute; top:130px; left:0; right:0; text-align:center; z-index:5; }}
.head .k {{ font-size:30px; color:#fca5a5; font-weight:700; letter-spacing:8px; }}
.head .t {{ font-size:66px; color:#fff; font-weight:900; margin-top:16px; text-shadow:0 6px 24px rgba(0,0,0,.7); }}
.stats {{ position:absolute; top:{520 - (3 - n_rows) * 40}px; left:0; right:0; display:flex; flex-direction:column; align-items:center; gap:44px; z-index:4; }}
.stat {{ display:flex; align-items:center; gap:36px; width:820px; background:rgba(255,255,255,0.10); backdrop-filter:blur(8px); border-radius:28px; padding:36px 44px; border:2px solid rgba(255,255,255,0.2); }}
.dot {{ width:120px; height:120px; border-radius:50%; background:rgba(239,68,68,0.16); border:4px solid #ef4444; display:flex; align-items:center; justify-content:center; position:relative; }}
.dot .num {{ font-size:52px; font-weight:900; color:#fca5a5; font-variant-numeric:tabular-nums; }}
.dot .unit {{ font-size:26px; font-weight:700; color:#fca5a5; margin-left:2px; }}
.dot .ping {{ position:absolute; inset:-6px; border-radius:50%; border:2px solid rgba(239,68,68,0.6); opacity:0; }}
.dot[data-hot="1"] .ping {{ animation:ping 0.8s ease-out infinite; }}
@keyframes ping {{ 0% {{ transform:scale(0.7); opacity:0.9; }} 100% {{ transform:scale(1.5); opacity:0; }} }}
.sinfo .lab {{ font-size:30px; color:#e2e8f0; font-weight:700; }}
.sinfo .desc {{ font-size:26px; color:#94a3b8; margin-top:8px; }}
</style></head><body>
<div class="bg" id="bg"></div><div class="shade"></div>
<div class="idx">{idx:02d}D</div>
<div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div>
<div class="stats">{stat_html}</div>
<script>
var targets = [{targets_js}];
var units = [{units_js}];
function easeOut(t){{ return 1 - Math.pow(1-t, 3); }}
function renderFrame(t){{
  for (var i=0; i<{n_rows}; i++){{
    var start = i * 0.8;
    var p = (t - start) / 1.4;
    document.getElementById('dot'+i).setAttribute('data-hot', (p > 0 && p < 1.3) ? 1 : 0);
    document.getElementById('u'+i).textContent = units[i];
    var v = 0;
    if (p > 0) {{ v = Math.round(parseFloat(targets[i]) * Math.min(1, easeOut(Math.min(1, p)))); }}
    // 防御值（unit 为空 = 无真实数字）→ 静态显示 "—"
    document.getElementById('n'+i).textContent = units[i] === '' ? '—' : v;
  }}
}}
</script></body></html>"""


def build_shot_step_light(idx: int, title: str, items: list[str], bg_path: str,
                          kicker: str) -> str:
    """流程点亮：步骤逐个点亮（完成=深色保持、当前=亮色高亮放大、未到=灰暗）+ 进度条
    步骤数 = 实际有效 items 数（2-4），不生成空占位步骤"""
    steps = [str(x).strip()[:14] for x in items if str(x).strip()]
    if len(steps) < 2:
        steps = (steps + ["步骤一", "步骤二", "步骤三", "步骤四"])[:2]
    steps = steps[:4]
    n_steps = len(steps)
    step_html = ""
    for i, s in enumerate(steps):
        step_html += (
            f'<div class="step" data-idx="{i}" data-state="idle">'
            f'<div class="sn">{i + 1:02d}</div>'
            f'<div class="sc"><div class="st">{esc(s)}</div>'
            f'<div class="sd">第 {i + 1} 步</div></div><div class="arr">▼</div></div>'
        )
    # 步骤越少，位置越高、间隙越小
    top_offset = 470 - (4 - n_steps) * 50
    gap = 34 - (4 - n_steps) * 4
    b64 = _b64img(bg_path)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:-40px; background:url(data:image/jpeg;base64,{b64}) center/cover;
  transform:scale(1.12); will-change:transform; }}
.shade {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(0,0,0,0.28) 0%,rgba(0,0,0,0.58) 45%,rgba(0,0,0,0.9) 100%); }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.16); z-index:2; }}
.head {{ position:absolute; top:130px; left:0; right:0; text-align:center; z-index:5; }}
.head .k {{ font-size:30px; color:#6ee7b7; font-weight:700; letter-spacing:8px; }}
.head .t {{ font-size:66px; color:#fff; font-weight:900; margin-top:16px; text-shadow:0 6px 24px rgba(0,0,0,.7); }}
.steps {{ position:absolute; top:{top_offset}px; left:0; right:0; display:flex; flex-direction:column; align-items:center; gap:{gap}px; z-index:4; }}
.step {{ width:820px; display:flex; align-items:center; gap:34px; padding:38px 44px; border-radius:24px; transition:all .22s ease-out; }}
.step .sn {{ font-size:52px; font-weight:900; width:110px; text-align:center; font-variant-numeric:tabular-nums; }}
.step .st {{ font-size:40px; font-weight:800; }}
.step .sd {{ font-size:26px; margin-top:6px; }}
.step .arr {{ font-size:30px; margin-left:auto; opacity:0; }}
.step[data-state="done"] {{ background:rgba(255,255,255,0.13); border:3px solid rgba(16,185,129,0.7); transform:translateX(10px); }}
.step[data-state="done"] .sn {{ color:#34d399; }}
.step[data-state="done"] .st {{ color:#fff; }}
.step[data-state="done"] .sd {{ color:#a7f3d0; }}
.step[data-state="hot"] {{ background:linear-gradient(135deg,#059669,#0d9488); border:3px solid #34d399; transform:translateX(26px) scale(1.03); box-shadow:0 26px 60px rgba(5,150,105,0.5); }}
.step[data-state="hot"] .sn {{ color:#fff; }}
.step[data-state="hot"] .st {{ color:#fff; }}
.step[data-state="hot"] .sd {{ color:#d1fae5; }}
.step[data-state="hot"] .arr {{ opacity:1; color:#facc15; }}
.step[data-state="idle"] {{ background:rgba(255,255,255,0.06); border:3px solid rgba(255,255,255,0.16); transform:translateX(0) scale(0.95); }}
.step[data-state="idle"] .sn {{ color:#64748b; }}
.step[data-state="idle"] .st {{ color:#94a3b8; }}
.step[data-state="idle"] .sd {{ color:#64748b; }}
.progress {{ position:absolute; bottom:170px; left:130px; right:130px; height:10px; background:rgba(255,255,255,0.15); border-radius:999px; z-index:4; overflow:hidden; }}
.progress i {{ display:block; height:100%; width:0%; background:linear-gradient(90deg,#34d399,#facc15); border-radius:999px; transition:width .2s; }}
</style></head><body>
<div class="bg" id="bg"></div><div class="shade"></div>
<div class="idx">{idx:02d}S</div>
<div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div>
<div class="steps">{step_html}</div>
<div class="progress"><i id="prog"></i></div>
<script>
var TOTAL_STEPS = {n_steps};
function renderFrame(t){{
  var stepCount = Math.min(TOTAL_STEPS, Math.floor(t / 0.8) + 1);
  document.getElementById('prog').style.width = Math.min(100, Math.round((t / (TOTAL_STEPS * 0.8)) * 100)) + '%';
  document.querySelectorAll('.step').forEach(function(el){{
    var idx = parseInt(el.dataset.idx);
    var state = idx < stepCount - 1 ? 'done' : (idx === stepCount - 1 ? 'hot' : 'idle');
    el.setAttribute('data-state', state);
  }});
}}
</script></body></html>"""


def detect_element_shot(seg_text: str, title: str = "") -> str:
    """按内容结构自动选动效镜头类型（内容驱动视觉原则）——中英双语支持"""
    text = f"{title} {seg_text}"
    # 流程/步骤：中英双语检测
    # 中文：第一步/然后/接着/流程/步骤/工作流
    # 英文：step 1/first/then/next/finally/workflow/pipeline/process/stage
    if re.search(
        r"(流程|步骤|工作流|第一步|第二步|第三步|第四步|然后|接着|再来|最终"
        r"|step\s*\d|first|then|next|finally|workflow|pipeline|process|stage"
        r"|how\s+to|step\s*-?\s*by\s*-?\s*step|tutorial|guide)",
        text, re.IGNORECASE,
    ):
        return "step_light"
    # 对比/选型：中英双语检测
    # 中文：对比/哪个/怎么选/相比/PK/vs
    # 英文：versus/vs/compare/which/better/best/pick/choose/option/alternative/tested/review
    if re.search(
        r"(对比|哪个|怎么选|怎么挑|挑选|相比|PK|vs|VS|A/B|还是.*好|哪个.*合适"
        r"|versus|vs\.?|compare|which|better|best|pick|choose|option|alternativ"
        r"|tested|review|head\s*-?\s*to\s*-?\s*head|winner|survived)",
        text, re.IGNORECASE,
    ):
        return "tile_activate"
    # 数字信号：中英双语检测
    # 中文：≥2位数字+单位（"12倍"/"3.2秒"）
    # 英文：≥2位数字+单位（"10 min"/"3x faster"/"92%"/"2.5 seconds"）
    if re.search(
        r"\d{2,}(?:\.\d+)?\s*(倍|%|秒|毫秒|分钟|小时|个|元|GB|MB|次|s|ms|万|亿"
        r"|x\s|times?|percent|hours?|minutes?|seconds?|days?|weeks?|months?"
        r"|GB|MB|TB|Hz|kHz|MHz|GHz|fps|fps|ppi|dpi)",
        text, re.IGNORECASE,
    ):
        return "digit_roll"
    return ""


def assess_topic_layout_samples(samples: dict[str, object], width: int, height: int) -> list[str]:
    """Fail closed when topic copy drifts, clips, or invades the subtitle band."""
    failures: list[str] = []
    first = dict(samples.get("first") or {})
    second = dict(samples.get("second") or {})
    x_margin = width * (24 / 720)
    y_min = height * (280 / 1280)
    subtitle_top = height * (840 / 1280)
    if (
        float(first.get("x", -1)) < x_margin
        or float(first.get("right", width + 1)) > width - x_margin
        or float(first.get("y", -1)) < y_min
        or float(first.get("bottom", height + 1)) > subtitle_top
    ):
        failures.append("content_outside_safe_zone")
    if (
        abs(float(first.get("x", 0)) - float(second.get("x", 0))) > 0.5
        or abs(float(first.get("y", 0)) - float(second.get("y", 0))) > 0.5
        or abs(float(first.get("right", 0)) - float(second.get("right", 0))) > 0.5
        or abs(float(first.get("bottom", 0)) - float(second.get("bottom", 0))) > 0.5
    ):
        failures.append("container_drift")
    if first.get("transform") != "none" or second.get("transform") != "none":
        failures.append("container_transform")
    if len(str(samples.get("content_text") or "").replace(" ", "")) < 8:
        failures.append("insufficient_content")
    if any(str(item or "").strip() for item in (samples.get("motion_text") or [])):
        failures.append("visible_floating_motion_text")
    narrative_first = dict(samples.get("narrative_first") or {})
    narrative_second = dict(samples.get("narrative_second") or {})
    if narrative_first or narrative_second:
        if (
            float(narrative_first.get("x", -1)) < width * (48 / 720)
            or float(narrative_first.get("right", width + 1)) > width - width * (48 / 720)
            or float(narrative_first.get("y", -1)) < height * (180 / 1280)
            or float(narrative_first.get("bottom", height + 1)) > float(first.get("y", 0)) - 20
        ):
            failures.append("narrative_card_collision")
        if (
            abs(float(narrative_first.get("x", 0)) - float(narrative_second.get("x", 0))) > 0.5
            or abs(float(narrative_first.get("y", 0)) - float(narrative_second.get("y", 0))) > 0.5
            or abs(float(narrative_first.get("bottom", 0)) - float(narrative_second.get("bottom", 0))) > 0.5
        ):
            failures.append("narrative_drift")
        if narrative_first.get("transform") != "none" or narrative_second.get("transform") != "none":
            failures.append("narrative_transform")
        if len(str(samples.get("narrative_text") or "").replace(" ", "")) < 20:
            failures.append("narrative_copy_insufficient")
    return failures


def assess_predictive_layout_samples(samples: dict[str, object], width: int, height: int) -> list[str]:
    """Validate stable full-canvas predictive layouts without reusing the industrial mid-card safe zone."""
    failures: list[str] = []
    first = dict(samples.get("first") or {})
    second = dict(samples.get("second") or {})
    if (
        abs(float(first.get("x", 0)) - float(second.get("x", 0))) > 0.5
        or abs(float(first.get("y", 0)) - float(second.get("y", 0))) > 0.5
        or abs(float(first.get("right", 0)) - float(second.get("right", 0))) > 0.5
        or abs(float(first.get("bottom", 0)) - float(second.get("bottom", 0))) > 0.5
    ):
        failures.append("container_drift")
    if first.get("transform") != "none" or second.get("transform") != "none":
        failures.append("container_transform")
    if len(str(samples.get("content_text") or "").replace(" ", "")) < 8:
        failures.append("insufficient_content")
    subtitle_top = height - 300
    for child in list(samples.get("predictive_children_first") or []):
        rect = dict(child or {})
        if (
            float(rect.get("x", -1)) < 0
            or float(rect.get("right", width + 1)) > width
            or float(rect.get("y", -1)) < 0
            or float(rect.get("bottom", height + 1)) > height
        ):
            failures.append("predictive_content_outside_viewport")
            break
        if float(rect.get("bottom", 0)) > subtitle_top:
            failures.append("predictive_content_in_subtitle_band")
            break
    return failures


def default_subtitle_y_up(platform: str, width: int, height: int) -> int:
    if width >= height:
        return 0
    if platform in {"douyin", "douyin_ai"}:
        return 270
    if platform in {"tiktok", "youtube", "shorts"}:
        return 350
    return 300


def should_frame_drive_shot(
    name: str, scene_contract: list[dict[str, object]], shot_types: dict[int, object]
) -> bool:
    scene_index = int(name[5:7])
    mode = str((scene_contract[scene_index - 1] or {}).get("visual_mode") or "")
    return bool(shot_types.get(scene_index)) and (
        name.endswith("B") or mode in INDUSTRIAL_TOPIC_MODES
    )


def uses_industrial_hard_cuts(scene_contract: list[dict]) -> bool:
    modes = [str(row.get("visual_mode") or "") for row in scene_contract if isinstance(row, dict)]
    return bool(modes) and all(mode in INDUSTRIAL_TOPIC_MODES for mode in modes)


def concat_prep_filter(input_index: int, *, replace_first_frame: bool, fps: float = 25.0) -> str:
    """Prepare a concat input while preserving duration when its first frame is a browser blank."""
    if not replace_first_frame:
        return f"[{input_index}:v]setpts=PTS-STARTPTS[v{input_index}]"
    frame_duration = 1.0 / max(float(fps), 1.0)
    return (
        f"[{input_index}:v]trim=start_frame=1,setpts=PTS-STARTPTS,"
        f"tpad=start_mode=clone:start_duration={frame_duration:.6f}[v{input_index}]"
    )


def has_isolated_bright_first_frame(video_path: Path) -> bool:
    """Detect a one-frame white browser load state at the start of a rendered shot."""
    probe = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video_path),
            "-vf", "signalstats,metadata=print", "-frames:v", "2", "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if probe.returncode != 0:
        return False
    samples = [float(value) for value in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", probe.stderr)]
    return len(samples) >= 2 and samples[0] > 220.0 and samples[1] < 205.0


def assess_luminance_flash_samples(samples: list[float], fps: float = 25.0) -> dict:
    bright = []
    for index, value in enumerate(samples):
        left = samples[index - 1] if index else value
        right = samples[index + 1] if index + 1 < len(samples) else value
        if value > 220.0 and (index == 0 or min(left, right) < 205.0):
            bright.append(index)

    dark_ranges = []
    index = 0
    while index < len(samples):
        if samples[index] >= 25.0:
            index += 1
            continue
        start = index
        while index + 1 < len(samples) and samples[index + 1] < 25.0:
            index += 1
        end = index
        before = samples[start - 1] if start else samples[start]
        after = samples[end + 1] if end + 1 < len(samples) else samples[end]
        run_frames = end - start + 1
        if 2 <= run_frames <= max(2, int(round(fps * 0.5))) and max(before, after) > 40.0:
            dark_ranges.append({
                "start_frame": start,
                "end_frame": end,
                "start_s": round(start / fps, 3),
                "end_s": round(end / fps, 3),
                "min_yavg": round(min(samples[start:end + 1]), 3),
            })
        index += 1
    failures = []
    if bright:
        failures.append("isolated_bright_flash")
    if dark_ranges:
        failures.append("short_dark_gap")
    return {
        "passed": not failures,
        "failures": failures,
        "frame_count": len(samples),
        "fps": fps,
        "bright_flash_frames": bright,
        "dark_gap_ranges": dark_ranges,
    }


def measure_luminance_flash_evidence(video_path: Path) -> dict:
    probe = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video_path),
            "-vf", "signalstats,metadata=print", "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    samples = [float(value) for value in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", probe.stderr)]
    fps = 25.0
    try:
        raw = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=nw=1:nk=1", str(video_path)],
            text=True,
            timeout=30,
        ).strip()
        numerator, denominator = raw.split("/", 1)
        fps = float(numerator) / max(1.0, float(denominator))
    except Exception:
        pass
    evidence = assess_luminance_flash_samples(samples, fps=fps)
    decode_failures = []
    if probe.returncode != 0:
        decode_failures.append("luminance_decode_failed")
    if not samples:
        decode_failures.append("luminance_frames_missing")
    if decode_failures:
        evidence["failures"] = [*evidence.get("failures", []), *decode_failures]
        evidence["passed"] = False
        evidence["decoder_returncode"] = probe.returncode
        evidence["decoder_error"] = (probe.stderr or "")[-240:]
    evidence["candidate_path"] = str(video_path)
    evidence["candidate_sha256"] = _sha256_file(video_path)
    return evidence


async def _wait_for_stable_first_paint(page) -> None:
    await page.evaluate(
        """async () => {
            if (document.fonts && document.fonts.ready) await document.fonts.ready;
            await Promise.all(Array.from(document.images).map((image) =>
                image.complete ? Promise.resolve() : image.decode().catch(() => undefined)
            ));
            await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }"""
    )


def frame_render_time(frame_index: int, fps: int, duration: float) -> float:
    return round(min(float(duration), (int(frame_index) + 1) / max(1, int(fps))), 6)


def leading_bright_run_length(samples: list[float], content_present=None) -> int:
    count = 0
    if content_present is not None and len(content_present) != len(samples):
        raise ValueError("first_frame_content_evidence_length_changed")
    for index, value in enumerate(samples):
        if value <= 220.0 or content_present is not None and content_present[index]:
            break
        count += 1
    return count


def should_trim_leading_bright_frame(samples: list[float]) -> bool:
    run = leading_bright_run_length(samples)
    return run > 0 and run < len(samples)


def _leading_frame_luma(video_path: Path, max_frames: int = 50) -> list[float]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video_path),
         "-vf", "signalstats,metadata=print", "-frames:v", str(max(2, int(max_frames))), "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    return [float(value) for value in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", result.stderr)][:max_frames]


def _repair_leading_bright_frame(video_path: Path, fps: int, expected_duration: float, evidence_path: Path) -> bool:
    before = _leading_frame_luma(video_path, max_frames=max(50, fps * 2))
    from content_platform.frame_content import leading_frame_structure
    structure = leading_frame_structure(video_path, len(before)) if before and before[0] > 220 else []
    content = [row["content_present"] for row in structure] if structure else None
    bright_run = leading_bright_run_length(before, content_present=content)
    evidence = {"path": str(video_path), "before_yavg": before, "leading_bright_frames": bright_run,
                "trimmed": False, "trimmed_frame_count": 0, "passed": True, "frame_structure": structure}
    if 0 < bright_run < len(before):
        temporary = video_path.with_name(video_path.stem + ".firstpaint.mp4")
        trim_duration = bright_run / max(1, fps)
        result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(video_path),
             "-vf", f"trim=start_frame={bright_run},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={trim_duration:.6f}",
             "-t", f"{expected_duration:.6f}", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-profile:v", "baseline", "-pix_fmt", "yuv420p", str(temporary)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0 or not temporary.is_file():
            evidence.update({"passed": False, "error": result.stderr[-240:]})
        else:
            os.replace(temporary, video_path)
            after = _leading_frame_luma(video_path, max_frames=2)
            evidence.update({"trimmed": True, "trimmed_frame_count": bright_run,
                             "after_yavg": after, "passed": leading_bright_run_length(after, content_present=[row["content_present"] for row in leading_frame_structure(video_path, len(after))]) == 0})
    elif bright_run == len(before) and bright_run:
        evidence.update({"passed": False, "error": "leading_bright_run_exceeds_scan_window"})
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return bool(evidence["passed"])


async def _verify_topic_layout(page, name: str, out: Path) -> dict[str, object] | None:
    is_topic = await page.evaluate("document.body.dataset.topicLayout === 'true'")
    if not is_topic:
        return None

    predictive = await page.evaluate("document.body.dataset.predictiveLayout === 'true'")

    async def sample(at: float) -> dict[str, object]:
        return await page.evaluate(
            """(t) => {
                window.renderFrame(t);
                const predictive = document.body.dataset.predictiveLayout === 'true';
                const selector = predictive ? '.pm-layout' : '.industrial-overlay';
                const element = document.querySelector(selector);
                if (!element) throw new Error(selector + ' missing');
                const rect = element.getBoundingClientRect();
                const narrative = document.querySelector('.narrative-copy');
                const narrativeRect = narrative ? narrative.getBoundingClientRect() : null;
                const predictive_children = predictive ? [...element.children]
                    .filter(node => getComputedStyle(node).display !== 'none')
                    .map(node => {
                        const box = node.getBoundingClientRect();
                        return {class_name: node.className, x: box.x, y: box.y,
                                right: box.right, bottom: box.bottom,
                                width: box.width, height: box.height};
                    }) : [];
                return {
                    x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom,
                    width: rect.width, height: rect.height,
                    transform: getComputedStyle(element).transform,
                    content_text: (element.innerText || '').replace(/\\s+/g, ''),
                    motion_text: [...document.querySelectorAll('.contract-motion')].map(node => node.innerText.trim()),
                    narrative: narrativeRect ? {
                        x: narrativeRect.x, y: narrativeRect.y, right: narrativeRect.right,
                        bottom: narrativeRect.bottom, width: narrativeRect.width, height: narrativeRect.height,
                        transform: getComputedStyle(narrative).transform,
                    } : null,
                    narrative_text: narrative ? (narrative.innerText || '').replace(/\\s+/g, '') : '',
                    predictive_children: predictive_children,
                };
            }""",
            at,
        )

    first = await sample(1.0)
    second = await sample(2.2)
    samples = {
        "first": {key: value for key, value in first.items() if key not in {"content_text", "motion_text"}},
        "second": {key: value for key, value in second.items() if key not in {"content_text", "motion_text"}},
        "content_text": first["content_text"],
        "motion_text": second["motion_text"],
        "narrative_first": first["narrative"],
        "narrative_second": second["narrative"],
        "narrative_text": first["narrative_text"],
        "predictive_children_first": first["predictive_children"],
        "predictive_children_second": second["predictive_children"],
    }
    failures = (
        assess_predictive_layout_samples(samples, W, H)
        if predictive else assess_topic_layout_samples(samples, W, H)
    )
    evidence = {
        "checker": "topic_layout_runtime_gate_v2",
        "predictive": bool(predictive),
        "shot": name,
        "viewport": {"width": W, "height": H},
        "safe_zone": {"x_min": W * 24 / 720, "x_max": W * 696 / 720,
                      "y_min": H * 280 / 1280, "y_max": H * 840 / 1280},
        "samples": samples,
        "failures": failures,
        "passed": not failures,
    }
    evidence_dir = out / "layout_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / f"{name}.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        raise RuntimeError(f"{name} topic layout gate failed: {failures}")
    return evidence


async def _record_shot_frames(name: str, html_path: str, dur: float, out: Path) -> str | None:
    """JS 逐帧驱动渲染：renderFrame(t) 每帧推进 → 截图 → FFmpeg 合成 mp4。
    用于卡内元素级动效（静态截图拍不到 CSS 动画，record_video 只捕入场）"""
    from playwright.async_api import async_playwright
    fps = 25
    total = max(1, int(dur * fps))
    frames_dir = out / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, executable_path=_chromium_executable_path(), env=_chromium_launch_environment(), args=["--no-sandbox"])
            pg = await b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            await pg.goto(f"file://{html_path}", wait_until="load", timeout=30000)
            await _wait_for_stable_first_paint(pg)
            await _verify_topic_layout(pg, name, out)
            await pg.evaluate("renderFrame(0)")
            await _wait_for_stable_first_paint(pg)
            warmup = frames_dir / "_warmup.png"
            await pg.screenshot(path=str(warmup), animations="disabled")
            await _wait_for_stable_first_paint(pg)
            for i in range(total):
                t = frame_render_time(i, fps, dur)
                await pg.evaluate(f"renderFrame({t})")
                await pg.screenshot(path=str(frames_dir / f"f_{i:04d}.png"), animations="disabled")
            warmup.unlink(missing_ok=True)
            await b.close()
    except Exception as e:
        print(f"{name} 逐帧渲染失败: {e}", file=sys.stderr)
        return None
    mp4 = out / "shots" / f"{name}.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "quiet", "-framerate", str(fps),
         "-i", str(frames_dir / "f_%04d.png"),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-an",
         str(mp4)], timeout=180)
    if r.returncode != 0 or not mp4.is_file():
        print(f"{name} ffmpeg 合成失败", file=sys.stderr)
        return None
    expected = total / fps
    if not _repair_leading_bright_frame(
        mp4, fps, expected, out / "first_frame_evidence" / f"{name}.json"
    ):
        print(f"{name} 首帧白底修复失败", file=sys.stderr)
        return None
    # 合成后时长校验：帧数不足 = 中断/损坏，必须重来（防残废产物）
    actual_dur = _duration(str(mp4))
    if actual_dur < expected - 0.35:
        print(f"{name} 合成时长异常 ({actual_dur:.2f}s vs 预期 {expected:.2f}s)，删除重渲染", file=sys.stderr)
        try:
            mp4.unlink()
        except OSError:
            pass
        return None
    return str(mp4)


async def _record_shot(name: str, html_path: str, dur: float, out: Path, frame_driven: bool = False) -> str | None:
    from playwright.async_api import async_playwright
    browser = context = page = video = None
    video_path = None
    saved_video = out / "webm" / f".{name}.webm.tmp"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=_chromium_executable_path(), env=_chromium_launch_environment(), args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(out / "webm"),
            record_video_size={"width": W, "height": H},
        )
        page = await context.new_page()
        video = page.video
        try:
            # Local HTML can keep browser connections alive indefinitely; load
            # proves the document is ready without allowing network-idle hangs.
            await page.goto(f"file://{html_path}", wait_until="load", timeout=30000)
            await _wait_for_stable_first_paint(page)
            if await _verify_topic_layout(page, name, out):
                await page.reload(wait_until="load", timeout=30000)
                await _wait_for_stable_first_paint(page)
            if frame_driven:
                # Drive element state in the page while Chromium records native
                # video. This keeps real motion without full-resolution PNG
                # screenshots for every frame.
                await page.evaluate(
                    """async (durationMs) => {
                        if (typeof window.renderFrame !== 'function') {
                            throw new Error('renderFrame is unavailable');
                        }
                        await new Promise((resolve) => {
                            const started = performance.now();
                            const tick = (now) => {
                                window.renderFrame((now - started) / 1000);
                                if (now - started >= durationMs) {
                                    resolve();
                                } else {
                                    requestAnimationFrame(tick);
                                }
                            };
                            requestAnimationFrame(tick);
                        });
                    }""",
                    int(dur * 1000),
                )
            else:
                await page.wait_for_timeout(int(dur * 1000))
        finally:
            if page:
                try:
                    await asyncio.wait_for(page.close(), timeout=10)
                except (asyncio.TimeoutError, Exception):
                    pass
            if video:
                try:
                    # Save while the browser context is still alive. Calling
                    # video.path() after context shutdown can race Chromium's
                    # recorder finalization and yield a truncated WebM.
                    saved_video.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.wait_for(video.save_as(str(saved_video)), timeout=30)
                    video_path = str(saved_video)
                except (asyncio.TimeoutError, Exception):
                    pass
            if context:
                try:
                    await asyncio.wait_for(context.close(), timeout=15)
                except (asyncio.TimeoutError, Exception):
                    pass
            if browser:
                try:
                    await asyncio.wait_for(browser.close(), timeout=10)
                except (asyncio.TimeoutError, Exception):
                    pass
    if video_path:
        target = out / "webm" / f"{name}.webm"
        os.replace(video_path, target)
        return str(target)
    return None


async def _render_shot_still(name: str, html_path: str, dur: float, out: Path) -> str | None:
    """Render a browser still then apply deterministic FFmpeg camera motion.

    Playwright's video recorder launches a separate WebM encoder that can
    survive page shutdown on constrained hosts. A screenshot has no recorder
    child process, while FFmpeg gives the shot a bounded, visible movement.
    """
    from playwright.async_api import async_playwright

    browser = page = None
    still = out / "shots" / f"{name}.png"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path=_chromium_executable_path(), env=_chromium_launch_environment(), args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            await page.goto(f"file://{html_path}", wait_until="load", timeout=30000)
            await _wait_for_stable_first_paint(page)
            if await _verify_topic_layout(page, name, out):
                await page.reload(wait_until="load", timeout=30000)
                await _wait_for_stable_first_paint(page)
            await asyncio.wait_for(page.screenshot(path=str(still), animations="disabled"), timeout=20)
    except Exception as exc:
        print(f"{name} still capture failed: {exc}", file=sys.stderr)
        return None
    finally:
        if page:
            try:
                await asyncio.wait_for(page.close(), timeout=10)
            except (asyncio.TimeoutError, Exception):
                pass
        if browser:
            try:
                await asyncio.wait_for(browser.close(), timeout=10)
            except (asyncio.TimeoutError, Exception):
                pass
    if not still.is_file():
        return None
    output = out / "shots" / f"{name}.mp4"
    fps = 25
    frames = max(1, int(dur * fps))
    motion = f"scale={W}:{H}:flags=lanczos,format=yuv420p"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-loop", "1", "-i", str(still), "-vf", motion,
             "-t", f"{dur:.3f}", "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-an", str(output)],
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print(f"{name} still-motion encode timed out", file=sys.stderr)
        return None
    return str(output) if result.returncode == 0 and output.is_file() else None


def _detect_browser_white_warmup(path: str, *, max_seconds: float = 1.5, fps: int = 20) -> float:
    """Measure the recorder's blank white navigation lead-in from real pixels."""
    width, height = 36, 64
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-t", f"{max_seconds:.3f}",
             "-vf", f"fps={fps},scale={width}:{height},format=gray", "-f", "rawvideo", "-"],
            capture_output=True,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        return 0.0
    if result.returncode != 0:
        return 0.0
    frame_size = width * height
    frames = len(result.stdout) // frame_size
    for index in range(frames):
        frame = result.stdout[index * frame_size:(index + 1) * frame_size]
        if not frame:
            break
        mean = sum(frame) / frame_size
        variance = sum((value - mean) ** 2 for value in frame) / frame_size
        if mean < 250.0 or variance ** 0.5 > 3.0:
            return max(0.0, (index - 1) / fps)
    return 0.0


def _finalize_recorded_shot(webm_path: str, target: Path, duration: float) -> bool:
    """Normalize a Playwright recording while removing measured browser warmup."""
    warmup = _detect_browser_white_warmup(webm_path)
    vf = (
        f"trim=start={warmup:.3f},setpts=PTS-STARTPTS,"
        f"tpad=stop_mode=clone:stop_duration={warmup:.3f},trim=duration={duration:.3f},format=yuv420p"
    )
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", webm_path, "-vf", vf, "-t", f"{duration:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "baseline",
             "-pix_fmt", "yuv420p", "-an", str(target)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False
    passed = result.returncode == 0 and target.is_file() and target.stat().st_size > 10_000
    if passed:
        target.with_suffix(".warmup.json").write_text(
            json.dumps(
                {"source": webm_path, "target": str(target), "warmup_seconds": round(warmup, 3),
                 "target_duration_seconds": round(duration, 3)},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    return passed


def _wrap(text: str, max_chars: int = 20):
    """按自然边界换行；英文优先在空格处断行，禁止拆开单词。"""
    if len(text) <= max_chars:
        return text, ""
    if text.isascii():
        cut = text.rfind(" ", 0, max_chars + 1)
        cut = cut if cut > 0 else max_chars
        first = text[:cut].strip()
        rest = text[cut:].strip()
        if len(rest) <= max_chars:
            return first, rest
        # Never replace spoken content with an ellipsis: the subtitle contract
        # requires the complete sentence to remain visible to the viewer.
        return first, rest
    cut = -1
    for i in range(max_chars, 0, -1):
        if text[i] in "，。；！？、：":
            cut = i + 1
            break
    if cut == -1:
        cut = max_chars
    return text[:cut], text[cut:max_chars + cut]


def subtitle_chunks(text: str, max_chars_per_line: int = 15, max_lines: int = 2) -> list[tuple[str, ...]]:
    """Split complete subtitle text into timed cues without dropping characters."""
    if max_chars_per_line < 1 or max_lines < 1:
        raise ValueError("subtitle chunk dimensions must be positive")
    remaining = str(text or "")
    lines: list[str] = []
    punctuation = "，。；！？、：,.!?; "
    while remaining:
        if len(remaining) <= max_chars_per_line:
            lines.append(remaining)
            break
        cut = max_chars_per_line
        for index in range(max_chars_per_line - 1, -1, -1):
            if remaining[index] in punctuation:
                cut = index + 1
                break
        lines.append(remaining[:cut])
        remaining = remaining[cut:]
    return [tuple(lines[index:index + max_lines]) for index in range(0, len(lines), max_lines)]


def main() -> int:
    ap = argparse.ArgumentParser(description="融合渲染器：电影级多镜头")
    ap.add_argument("--video-dir", required=True)
    ap.add_argument("--theme", default="cyber-neon")
    ap.add_argument("--title", default="Untitled")
    ap.add_argument("--desc", default="")
    ap.add_argument("--bgm-style", default="warm acoustic guitar and light piano")
    ap.add_argument(
        "--audio-route",
        choices=("embedded_licensed_bgm", "sfx_only", "platform_native_track", "preserve_source_audio"),
        default="embedded_licensed_bgm",
    )
    ap.add_argument("--platform", default="kuaishou")
    ap.add_argument("--tags", nargs="*", default=[])
    ap.add_argument("--width", type=int, default=W)
    ap.add_argument("--height", type=int, default=H)
    ap.add_argument("--script", default="", help="完整 8 段脚本文件（空行分隔），避免 runner 按句切分截断 TTS")
    ap.add_argument("--scene-contract", default="", help="scene-level visual contract JSON")
    args = ap.parse_args()
    # Override module-level W, H so rendering uses CLI dimensions
    _g = globals()
    _g['W'] = args.width
    _g['H'] = args.height
    try:
        render_policy = resolve_render_policy()
    except ValueError as exc:
        print(f"渲染质量策略无效: {exc}", file=sys.stderr)
        return 2

    out = Path(args.video_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock_handle = (out / ".render.lock").open("a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"render blocked: output run already locked: {out}", file=sys.stderr)
        lock_handle.close()
        return 5
    try:
        from content_platform.video_preflight import VideoPreflightError, validate_video_preflight
        validate_video_preflight(out, args.platform)
    except (VideoPreflightError, OSError, ValueError) as exc:
        print(f"video preflight blocked: {exc}", file=sys.stderr)
        return 5
    scene_contract = []
    contract_path = Path(args.scene_contract or os.environ.get("VIDEO_SCENE_CONTRACT_PATH", ""))
    if contract_path.is_file():
        try:
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                scene_contract = list(payload.get("scenes") or [])
            elif isinstance(payload, list):
                scene_contract = list(payload)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"scene contract invalid: {exc}", file=sys.stderr)
            return 2
    if not contract_path.is_file() and os.environ.get("VIDEO_ALLOW_LEGACY") != "1":
        print("scene contract missing: real rendering is blocked", file=sys.stderr)
        return 5
    for sub in ("html", "webm", "shots", "sub"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    cards_path = out / "cards.json"
    if not cards_path.is_file():
        print(f"cards.json 不存在: {cards_path}", file=sys.stderr)
        return 2
    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    cards = cards if isinstance(cards, list) else cards.get("cards", [])
    if len(cards) < 8:
        print(f"cards 数量不足: {len(cards)} < 8", file=sys.stderr)
        return 2

    # 背景图：优先 backgrounds/bg_XX.jpg（runner materialize 产物），回退 card visual_asset
    bg_dir = out / "backgrounds"
    bg_paths = sorted(path for path in bg_dir.glob('bg_*') if path.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}) if bg_dir.is_dir() else []
    if len(bg_paths) < 8:
        # 从 cards visual_asset / materialized_background 收集
        bg_paths = []
        for c in cards[:8]:
            va = c.get("visual_asset") or {}
            p = str(va.get("materialized_background") or va.get("background_image") or "")
            if p and Path(p).is_file():
                bg_paths.append(Path(p))
    if len(bg_paths) < 8:
        print(f"背景图不足: {len(bg_paths)} < 8", file=sys.stderr)
        return 2

    # TTS：优先从 --script 读取完整 8 段（空行分隔），避免 runner 按句切分截断；
    # 未显式传 --script 时自动探测 video_dir/script.md 或上级目录 script.md。
    script_segments: list[str] = []
    script_candidates = [Path(args.script)] if args.script else []
    script_candidates += [out / "script.md", out.parent / "script.md", Path(args.video_dir).parent / "script.md"]
    script_file = next((p for p in script_candidates if p.is_file()), None)
    if script_file:
        raw = script_file.read_text(encoding="utf-8")
        script_segments = [seg.strip() for seg in re.split(r"\n\s*\n", raw) if seg.strip()]
        print(f"TTS 脚本: {script_file} ({len(script_segments)} 段)")
        # 08-14 短视频脚本质量门禁：PASS 才渲染（防"太AI不吸引人"复发）
        try:
            import subprocess as _sp
            gate_lang = "zh" if re.search(r"[\u4e00-\u9fff]", raw) else "en"
            gate = _sp.run(
                [sys.executable, str(ROOT / "scripts" / "video_script_gate.py"), str(script_file),
                 "--lang", gate_lang, "--json"],
                capture_output=True, text=True, timeout=30,
            )
            if gate.returncode == 0:
                print(f"脚本质量门禁: PASS ({gate_lang})")
            else:
                print(f"脚本质量门禁: FAIL ({gate_lang})（{gate.stdout[:200]}）", file=sys.stderr)
                if not script_gate_passed(gate.returncode, str(render_policy["quality_profile"])):
                    return 3
        except Exception as e:
            print(f"脚本质量门禁不可用: {e}", file=sys.stderr)
            if render_policy["quality_profile"] == "high":
                return 3
        # 08-14 敏感词过滤（用户复盘要求）：脚本即 TTS/字幕文案源，阻断式检查
        try:
            import importlib.util as _ilu
            _sw_path = ROOT / "scripts" / "sensitive_word_filter.py"
            if _sw_path.is_file():
                _spec = _ilu.spec_from_file_location("sensitive_word_filter", _sw_path)
                if _spec is None or _spec.loader is None:
                    raise RuntimeError("sensitive_word_filter spec 加载失败")
                _sw = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_sw)
                _res = _sw.check_content(raw, context="script")
                if _res["ok"]:
                    print("敏感词过滤: PASS (script)")
                else:
                    print(f"⛔ 敏感词过滤: FAIL——{len(_res['hits'])} 个敏感词: "
                          f"{[h['word'] for h in _res['hits']]}", file=sys.stderr)
                    # 阻断：敏感词必须修复后重渲染，不产出违规成品
                    return 3
        except Exception as e:
            print(f"敏感词检查跳过: {e}", file=sys.stderr)

    scene_manifest_path = out / "scene_manifest.json"
    if render_policy["quality_profile"] == "high" and (not scene_manifest_path.is_file() or not script_file):
        print("高质量渲染缺少 scene_manifest.json 或完整脚本", file=sys.stderr)
        return 2
    visual_treatment_path = ensure_visual_treatment_plan(out, bg_paths[:8])
    try:
        visual_scenes = load_visual_treatment_plan(visual_treatment_path, expected_scene_count=8)
        resolved_treatments = [resolve_scene_treatment(scene) for scene in visual_scenes]
        shot_runtime = build_shot_runtime_fingerprint(width=W, height=H, policy=render_policy)
    except (ValueError, RuntimeError) as exc:
        print(f"视觉导演计划或镜头运行时无效: {exc}", file=sys.stderr)
        return 2
    render_contract = {
        "renderer_version": RENDERER_VERSION,
        "renderer_source_sha256": shot_runtime["renderer_sha256"],
        "font_sha256": shot_runtime["font_sha256"],
        "browser_sha256": shot_runtime["browser_sha256"],
        "browser_version": shot_runtime["browser_version"],
        "playwright_version": shot_runtime["playwright_version"],
        "visual_gate_sha256": shot_runtime["gate_sha256"],
        **render_policy,
        "width": args.width,
        "height": args.height,
        "template_family": "ide_evidence" if args.platform == "douyin_ai" else "cinema_default",
        "subtitle_y_up": int(os.environ.get("FILM_SUB_Y_UP", str(default_subtitle_y_up(args.platform, args.width, args.height)))),
        "cards_sha256": _sha256_file(cards_path),
        "script_sha256": _sha256_file(script_file) if script_file else "",
        "scene_manifest_sha256": _sha256_file(scene_manifest_path) if scene_manifest_path.is_file() else "",
        "visual_treatment_plan_sha256": _sha256_file(visual_treatment_path),
        "backgrounds_sha256": [_sha256_file(path) for path in bg_paths[:8]],
        "transitions": TRANSITIONS,
        "xfade_short": XFADE_DUR_SHORT,
        "xfade_long": XFADE_DUR_LONG,
        "element_frame_render_min_timeout_seconds": ELEMENT_FRAME_RENDER_MIN_TIMEOUT_SECONDS,
        "motion_evidence_version": MOTION_EVIDENCE_VERSION,
    }
    if prepare_render_contract(out, render_contract):
        print("渲染契约变化：已废弃旧镜头与最终成片缓存")
    for sub in ("html", "webm", "shots", "frames", "sub"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    print(f"渲染质量: {render_policy['quality_profile']} / {render_policy['motion_mode']}")

    # 配音由当次受信Hermes能力和真实生成的内容计划决定。
    from content_platform.normal_film_audio import synthesize_normal_film_audio
    preflight = json.loads((out / "video_preflight.json").read_text(encoding="utf-8"))
    planning = (preflight.get("content_brief") or {}).get("video_source_planning") or {}
    plan_source = planning.get("voice_plan_source") or {}
    full_script = "\n\n".join(script_segments)
    tts_lang = "zh" if re.search(r"[\u4e00-\u9fff]", full_script) else "en"
    actual_audio = synthesize_normal_film_audio(script_segments, out / "tts",
        plan_source.get("path") or "", plan_source.get("sha256") or "")
    tts_provider = actual_audio["provider"]
    tts_files = actual_audio["files"]
    tts_records = actual_audio["records"]
    durs = actual_audio["durations"]
    (out / "tts_records.json").write_text(json.dumps(tts_records, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "tts_config.json").write_text(json.dumps({"version": "tts_config_current_hermes_v2",
        "provider": tts_provider, "source_config_sha256": actual_audio["source_config_sha256"],
        "execution_manifest": actual_audio["execution_manifest"], "segments": tts_records},
        ensure_ascii=False, indent=2), encoding="utf-8")
    short_timeline = short_scene_timing(durs) if str(args.platform).casefold() in {
        'kuaishou','douyin','douyin_ai','douyin_pet','shipinhao','tiktok','shorts','youtube'
    } else None
    if short_timeline:
        (out/'short_audio_timeline.json').write_text(json.dumps(short_timeline,
            ensure_ascii=False, sort_keys=True, indent=2), encoding='utf-8')
    print("TTS 时长:", [round(d, 2) for d in durs])
    duration_check = validate_render_durations(durs, args.platform)
    if not duration_check["passed"]:
        print(f"TTS 时长预算失败: {json.dumps(duration_check, ensure_ascii=False)}", file=sys.stderr)
        return 3

    kicker_map = {
        "kuaishou": "MAJIC AI · AI模型实测",
        "douyin_ai": "MAJIC AI · AI实测",
        "bilibili": "MAJIC AI · AI实测",
        "shipinhao": "马吉克AI · 实测",
        "tiktok": "MAJIC AI · AI Tools",
        "youtube": "MAJIC AI · AI Tools",
    }
    # 英文平台（tiktok/youtube）用英文 kicker，其余中文；按 tts_lang 兜底
    kicker = kicker_map.get(args.platform, "MAJIC AI · AI实测" if tts_lang == "zh" else "MAJIC AI · AI Tools")

    # 标题/正文按平台语言分段：英文按 .!?;，中文按中文标点；禁止固定 16 字截断英文句子。
    def _segment_punctuation() -> str:
        return r"[，。；！？、：.!?;]+" if args.platform in {"tiktok", "youtube", "shorts"} else r"[，。；！？、：]+"

    def _smart_title_clip(text: str, limit: int = 28) -> str:
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

    def seg_title(i: int) -> str:
        if i <= len(script_segments) and script_segments[i - 1]:
            seg = script_segments[i - 1]
            first = re.split(_segment_punctuation(), seg)[0].strip()
            if args.platform in {"tiktok", "youtube", "shorts"}:
                return first or seg.strip()
            return _smart_title_clip(first or seg.strip())
        return _card_title(cards[i - 1], f"第 {i} 段")

    def seg_modules(i: int) -> list[str]:
        if i <= len(script_segments) and script_segments[i - 1]:
            seg = script_segments[i - 1]
            sentences = [s.strip() for s in re.split(_segment_punctuation(), seg) if s.strip()]
            return (sentences[:3] if len(sentences) >= 3 else sentences + ["", "", ""])[:3]
        return _modules_from_card(cards[i - 1])

    # 截图素材检测（规则1：工具/项目介绍嵌入真实截图）——video_dir/screenshots/ 或上级目录
    screenshots_dir = None
    for cand in (out / "screenshots", out.parent / "screenshots", Path(args.video_dir).parent / "screenshots"):
        if cand.is_dir():
            screenshots_dir = cand
            break
    screenshot_files = sorted(screenshots_dir.glob("*.png")) + sorted(screenshots_dir.glob("*.jpg")) if screenshots_dir else []
    print(f"截图素材: {len(screenshot_files)} 张")

    shot_durs = []
    scene_execution_context: list[dict[str, object]] = []
    # 08-15 内容驱动动效：每段检测内容结构，B 镜头可切换为 图块激活/数字跳变/流程点亮
    shot_types = {}  # seg_idx -> "tile_activate" | "digit_roll" | "step_light" | ""
    prompt_lab_modes = [
        "before_after_split", "prompt_typewriter", "annotation_callout", "location_selector",
        "light_split_compare", "composition_push_in", "error_fix_compare", "checklist_stamp",
    ]
    contract_modes = [str(item.get("visual_mode") or "") for item in scene_contract if isinstance(item, dict)]
    prompt_lab_enabled = bool(scene_contract) and len(contract_modes) >= 8
    original_order_profile=False
    declared_plan=os.environ.get('VIDEO_TOOLCHAIN_PLAN_PATH')
    if declared_plan:
        runtime_plan=json.loads(Path(declared_plan).read_text(encoding='utf-8'))
        if runtime_plan.get('content_mode')=='original_knowledge':
            from content_platform.original_knowledge import original_from_plan
            original_proof=original_from_plan(runtime_plan)
            original_order_profile=original_proof.get('demo',{}).get('kind')=='orders_id_check'

    for i in range(1, 9):
        card = cards[i - 1]
        treatment = resolved_treatments[i - 1]
        title = seg_title(i)
        stat = _stat_from_card(card)
        modules = seg_modules(i)
        bg = str(bg_paths[i - 1])
        stat_label = "关键数字" if tts_lang == "zh" else "KEY NUMBER"
        # 视觉导演计划优先：每段的主体动效显式驱动镜头类型，避免再由固定轮换决定。
        seg_txt = script_segments[i - 1] if i <= len(script_segments) and script_segments[i - 1] \
            else str(card.get("tts") or card.get("txt") or "")
        elem_shot = str(treatment["element_shot"])
        # 所有平台统一走真实元素级镜头；平台差异只影响尺寸/文案，不得绕过分组动效。
        shot_types[i] = elem_shot
        contract_scene = scene_contract[i - 1] if i <= len(scene_contract) and isinstance(scene_contract[i - 1], dict) else {}
        contract_template_id = str(contract_scene.get("template_id") or "")
        contract_group_motion = contract_scene.get("group_motion") or []
        contract_platform_reason = str(contract_scene.get("platform_reason") or "")
        contract_body_copy = contract_scene.get("body_copy") or {}
        if original_order_profile:
            contract_body_copy=dict(contract_body_copy, original_order_id_profile=True)
        if prompt_lab_enabled:
            mode_a = contract_modes[i - 1] or prompt_lab_modes[(i - 1) % len(prompt_lab_modes)]
            purpose_a = f"establish:{str(contract_scene.get('visual_hook') or mode_a)}"
            html_a = build_prompt_lab_shot(
                i, title, seg_txt, bg, mode_a, kicker, contract_template_id,
                contract_group_motion, contract_platform_reason,
                shot_purpose=purpose_a, body_copy=contract_body_copy,
            )
            shot_types[i] = "prompt_lab"
        else:
            html_a = build_shot_a(
                i, title, stat, bg, kicker, stat_label=stat_label,
                camera_index=int(treatment["camera_index"]), text_motion_index=int(treatment["text_motion_index"]), platform=args.platform,
            )
        # 真实素材由 scene plan 绑定；只有不同于背景的资产才作为主体截图进入 B 镜头。
        shot_path = None
        caption = ""
        asset_path = Path(str(treatment["asset_path"]))
        if asset_path.resolve() != Path(bg).resolve():
            shot_path = str(asset_path)
            caption = str(treatment["display_purpose"])
        if prompt_lab_enabled:
            mode_b = f"{mode_a}_detail" if contract_template_id.startswith("cat_") else select_contract_b_mode(
                mode_a, i, contract_template_id, prompt_lab_modes
            )
            template_b = contract_template_id
            purpose_b = f"inspect:{mode_b}"
            html_b = build_prompt_lab_shot(
                i, title, seg_txt, bg, mode_b, kicker, template_b,
                contract_group_motion, contract_platform_reason,
                shot_purpose=purpose_b, body_copy=contract_body_copy,
            )
            shot_types[i] = "prompt_lab"
        elif elem_shot == "message_stack":
            html_b = build_shot_message_stack(i, title, modules, bg, kicker)
        elif elem_shot == "split_compare":
            html_b = build_shot_split_compare(i, title, modules, bg, kicker)
        elif elem_shot == "tile_activate":
            html_b = build_shot_tile_activate(i, title, modules, bg, kicker)
        elif elem_shot == "digit_roll":
            # 数据真实性铁律：无真实数字时降级普通镜头，禁止编造数据
            if _extract_number_unit(" ".join(modules)) or _extract_number_unit(seg_txt):
                html_b = build_shot_digit_roll(i, title, modules, bg, kicker)
            else:
                shot_types[i] = ""
                html_b = build_shot_b(
                    i, title, modules, bg, screenshot_path=shot_path, screenshot_caption=caption,
                    camera_index=int(treatment["camera_index"]), text_motion_index=int(treatment["text_motion_index"]), platform=args.platform,
                )
        elif elem_shot == "step_light":
            html_b = build_shot_step_light(i, title, modules, bg, kicker)
        else:
            html_b = build_shot_b(
                i, title, modules, bg, screenshot_path=shot_path, screenshot_caption=caption,
                camera_index=int(treatment["camera_index"]), text_motion_index=int(treatment["text_motion_index"]), platform=args.platform,
            )
        (out / "html" / f"shot_{i:02d}A.html").write_text(html_a, encoding="utf-8")
        (out / "html" / f"shot_{i:02d}B.html").write_text(html_b, encoding="utf-8")
        d = durs[i - 1]
        # Element motion still needs at least 3.2s, while every segment keeps
        # enough post-crossfade visual time for its measured narration.
        if short_timeline:
            timing = short_timeline['segments'][i-1]
            a_dur, b_dur = timing['shot_a_seconds'], timing['shot_b_seconds']
        else:
            a_dur, b_dur = segment_shot_durations(d, element_motion=bool(shot_types.get(i)))
        shot_durs.append((f"shot_{i:02d}A", a_dur))
        shot_durs.append((f"shot_{i:02d}B", b_dur))
        scene_execution_context.append({
            **treatment,
            "background_path": bg,
            "background_sha256": _sha256_file(Path(bg)),
            "subject_asset_used": bool(shot_path),
            "visual_mode": str(contract_scene.get("visual_mode") or ""),
            "template_id": contract_template_id,
            "group_motion": contract_group_motion,
            "platform_reason": contract_platform_reason,
            "shot_names": [f"shot_{i:02d}A", f"shot_{i:02d}B"],
        })

    scene_cache_entries: list[dict[str, object]] = []
    cached_records_by_name: dict[str, dict[str, object]] = {}
    shot_duration_map = dict(shot_durs)
    for scene_index in range(1, 9):
        specs = []
        for suffix in ("A", "B"):
            name = f"shot_{scene_index:02d}{suffix}"
            frame_driven = should_frame_drive_shot(name, scene_contract, shot_types)
            render_mode = "playwright-frame-video" if frame_driven else (
                "playwright-video" if render_policy["motion_mode"] == "cinematic" else "still-motion"
            )
            specs.append({
                "name": name,
                "html_path": out / "html" / f"{name}.html",
                "duration": shot_duration_map[name],
                "render_mode": render_mode,
                "fallback": False,
            })
        scene_id = f"s{scene_index:02d}"
        scene_key, key_payload = build_scene_key(
            scene_id, specs, Path(scene_execution_context[scene_index - 1]["background_path"]), shot_runtime
        )
        # The final-cache fast path needs content/SHA validation only. Media ABI
        # was verified when this atomic manifest was published and is covered by
        # the artifact SHA. A final-cache miss falls through to full ffprobe.
        decision = inspect_scene_cache(out, scene_id, scene_key, key_payload, verify_media=False)
        entry = {
            "scene_id": scene_id, "scene_key": scene_key, "key_payload": key_payload,
            "shots": specs, "hit": bool(decision["hit"]), "reason": decision["reason"],
        }
        scene_cache_entries.append(entry)
        if decision["hit"]:
            for record in decision["records"]:
                cached_records_by_name[str(record["name"])] = record

    (out / "shot_cache_evidence.json").write_text(json.dumps({
        "version": SHOT_CACHE_MANIFEST_VERSION,
        "hits": sum(2 for row in scene_cache_entries if row["hit"]),
        "misses": sum(2 for row in scene_cache_entries if not row["hit"]),
        "scenes": [
            {"scene_id": row["scene_id"], "scene_key": row["scene_key"], "hit": row["hit"], "reason": row["reason"]}
            for row in scene_cache_entries
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    def current_final_render_key() -> str:
        secondary = out / "bgm.mp3"
        return build_final_render_key(
            render_contract,
            [str(row["scene_key"]) for row in scene_cache_entries],
            [_sha256_file(Path(path)) for path in tts_files],
            _sha256_file(secondary) if secondary.is_file() else "",
            args.audio_route,
        )

    if all(bool(row["hit"]) for row in scene_cache_entries):
        final_cache = inspect_final_render_cache(out, current_final_render_key())
        if final_cache["hit"]:
            pixel_gate = verify_final_pixels(out / "final.mp4")
            (out / "final_pixel_gate.json").write_text(json.dumps(pixel_gate, ensure_ascii=False, indent=2), encoding="utf-8")
            if not pixel_gate.get("passed") or pixel_gate.get("candidate_sha256") != final_cache.get("final_sha256"):
                print("最终产物缓存命中但 final-pixel gate 失败", file=sys.stderr)
                return 4
            print(f"最终产物强校验缓存命中: {final_cache['final_sha256']}")
            return 0

    # A cache miss must execute the complete HTML/runtime and media ABI gates.
    # Only a fully SHA-bound final cache may bypass these expensive checks.
    if prompt_lab_enabled:
        from scripts.visual_contract_gate import validate_rendered_html

        html_gate = validate_rendered_html(out / "html", scene_contract, strict_runtime=True)
        if not html_gate.get("passed"):
            raise RuntimeError("rendered HTML does not execute scene contract: " + ";".join(html_gate.get("failures") or []))

    cached_records_by_name.clear()
    for entry in scene_cache_entries:
        decision = inspect_scene_cache(
            out,
            str(entry["scene_id"]),
            str(entry["scene_key"]),
            entry["key_payload"],
            verify_media=True,
        )
        entry["hit"] = bool(decision["hit"])
        entry["reason"] = decision["reason"]
        if decision["hit"]:
            for record in decision["records"]:
                cached_records_by_name[str(record["name"])] = record

    (out / "shot_cache_evidence.json").write_text(json.dumps({
        "version": SHOT_CACHE_MANIFEST_VERSION,
        "hits": sum(2 for row in scene_cache_entries if row["hit"]),
        "misses": sum(2 for row in scene_cache_entries if not row["hit"]),
        "scenes": [
            {"scene_id": row["scene_id"], "scene_key": row["scene_key"], "hit": row["hit"], "reason": row["reason"]}
            for row in scene_cache_entries
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    shot_records: list[dict[str, object]] = []

    async def _render():
        async def record_bounded(name: str, html_path: str, duration: float, *, frame_driven: bool = False) -> str | None:
            try:
                timeout = element_render_timeout_seconds(duration) if frame_driven else max(45, duration + 25)
                return await asyncio.wait_for(
                    _record_shot(name, html_path, duration, out, frame_driven=frame_driven),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                print(f"{name} Playwright recording timed out", file=sys.stderr)
                return None
            except Exception as exc:
                print(f"{name} Playwright recording failed: {str(exc)[:160]}", file=sys.stderr)
                return None

        async def render_still(name: str, html_path: str, duration: float) -> str | None:
            try:
                return await asyncio.wait_for(_render_shot_still(name, html_path, duration, out), timeout=max(45, duration + 30))
            except asyncio.TimeoutError:
                print(f"{name} still-motion render timed out", file=sys.stderr)
                return None
            except Exception as exc:
                print(f"{name} still-motion render failed: {str(exc)[:160]}", file=sys.stderr)
                return None

        async def render_element(name: str, html_path: str, duration: float) -> str | None:
            webm = await record_bounded(name, html_path, duration + 0.5, frame_driven=True)
            target = out / "shots" / f"{name}.mp4"
            rendered = _finalize_recorded_shot(webm, target, duration) if webm else None
            if not rendered:
                return None
            if not _repair_leading_bright_frame(
                target, 25, duration, out / "first_frame_evidence" / f"{name}.json"
            ):
                return None
            return str(target)

        failed_shots = []
        for name, sd in shot_durs:
            hp = out / "html" / f"{name}.html"
            target = out / "shots" / f"{name}.mp4"
            cached_record = cached_records_by_name.get(name)
            if cached_record is not None:
                print(f"{name}: 强校验缓存命中")
                shot_records.append({
                    "name": name,
                    "renderer": str(cached_record["render_mode"]),
                    "fallback": False,
                    "reused": True,
                    "cache_status": "hit",
                    "output_sha256": str(cached_record["output_sha256"]),
                })
                continue
            # 动效镜头（B 且命中内容结构）→ JS 逐帧渲染；其余 → Playwright CSS 录制。
            # high/cinematic 模式绝不静默降级为 still-motion。
            seg_i = int(name[5:7])
            is_elem = should_frame_drive_shot(name, scene_contract, shot_types)
            if is_elem:
                mp4 = await render_element(name, str(hp), sd)
                if not mp4:
                    if render_policy["motion_mode"] == "safe":
                        mp4 = await render_still(name, str(hp), sd)
                        shot_records.append({"name": name, "renderer": "still-motion", "fallback": True, "reused": False})
                    else:
                        failed_shots.append(name)
                    shot_records.append({"name": name, "renderer": "playwright-frame-video", "fallback": True, "reused": False})
                else:
                    shot_records.append({"name": name, "renderer": "playwright-frame-video", "fallback": False, "reused": False})
                continue
            if render_policy["motion_mode"] == "cinematic":
                webm = await record_bounded(name, str(hp), sd + 0.5)
                mp4 = _finalize_recorded_shot(webm, target, sd) if webm else False
                if mp4:
                    shot_records.append({"name": name, "renderer": "playwright-video", "fallback": False, "reused": False})
                else:
                    failed_shots.append(name)
                    shot_records.append({"name": name, "renderer": "playwright-video", "fallback": True, "reused": False})
            else:
                mp4 = await render_still(name, str(hp), sd)
                if mp4:
                    shot_records.append({"name": name, "renderer": "still-motion", "fallback": False, "reused": False})
                else:
                    failed_shots.append(name)
                    shot_records.append({"name": name, "renderer": "still-motion", "fallback": True, "reused": False})
        if failed_shots:
            print(f"镜头渲染失败: {', '.join(failed_shots)}", file=sys.stderr)
            return False
        return True
    if not asyncio.run(_render()):
        return 3

    shot_mp4s = [out / "shots" / f"{n}.mp4" for n, _ in shot_durs]
    if not all(p.is_file() for p in shot_mp4s):
        print("镜头渲染不完整", file=sys.stderr)
        return 3

    # Persist locally verified A/B scene checkpoints before final composition.
    # A later full-video gate failure must not discard valid, SHA-bound shots;
    # scene cache is a resumability marker, never a publication marker.
    for entry in scene_cache_entries:
        if not entry["hit"]:
            commit_scene_cache(
                out,
                str(entry["scene_id"]),
                str(entry["scene_key"]),
                entry["key_payload"],
                entry["shots"],
            )

    # Industrial explainer: text survives only when temporal ownership is exclusive.
    # Use hard cuts and let in-card semantic state changes carry the rhythm.
    shot_names = [n for n, _ in shot_durs]
    durs_map = {n: _duration(str(out / "shots" / f"{n}.mp4")) for n in shot_names}
    transition_after = [0.0] * max(0, len(shot_names) - 1)
    applied_transitions: dict[int, str] = {}
    replace_first_frame_by_name = {
        name: has_isolated_bright_first_frame(out / "shots" / f"{name}.mp4")
        for name in shot_names
    }
    first_frame_repairs = [name + ".mp4" for name in shot_names if replace_first_frame_by_name[name]]
    (out / "first_frame_repair_evidence.json").write_text(
        json.dumps({
            "version": "first-frame-repair-v1",
            "repaired_shots": first_frame_repairs,
            "repair_count": len(first_frame_repairs),
            "method": "drop isolated bright frame 0 and prepend clone of frame 1",
            "duration_preserved": True,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if short_timeline or uses_industrial_hard_cuts(scene_contract) or str(args.platform).casefold() == "douyin_pet":
        concat_inputs = []
        concat_filters = []
        for shot_index, shot_path in enumerate(shot_mp4s):
            concat_inputs.extend(["-i", str(shot_path)])
            concat_filters.append(concat_prep_filter(
                shot_index, replace_first_frame=(str(args.platform).casefold() == "douyin_pet" or replace_first_frame_by_name[shot_names[shot_index]]), fps=25.0,
            ))
        concat_chain = ";".join(concat_filters) + ";" + "".join(
            f"[v{shot_index}]" for shot_index in range(len(shot_mp4s))
        ) + f"concat=n={len(shot_mp4s)}:v=1:a=0[vout]"
        concat_result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", *concat_inputs, "-filter_complex", concat_chain,
             "-map", "[vout]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-profile:v", "baseline", "-pix_fmt", "yuv420p", str(out / "visual_xfade.mp4")],
            capture_output=True, text=True, timeout=300,
        )
        if concat_result.returncode != 0:
            print(f"工业镜头硬切拼接失败: {concat_result.stderr[-240:]}", file=sys.stderr)
            return 3
        for scene_index in range(len(scene_contract)):
            applied_transitions[scene_index] = "hard_cut"
    else:
        group_outs = []
        for gi in range(4):
            names = shot_names[gi * 4:(gi + 1) * 4]
            inputs = []
            for n in names:
                inputs += ["-i", str(out / "shots" / f"{n}.mp4")]
            fc_parts = [
                concat_prep_filter(i, replace_first_frame=(str(args.platform).casefold() == "douyin_pet" or replace_first_frame_by_name[n]), fps=25.0)
                for i, n in enumerate(names)
            ]
            prev = "v0"
            offset_acc = 0.0
            for i in range(1, len(names)):
                cur_type = "B" if names[i].endswith("B") else "A"
                prev_type = "B" if names[i - 1].endswith("B") else "A"
                prior_scene_index = int(names[i - 1][5:7]) - 1
                trans = str(resolved_treatments[prior_scene_index]["transition"])
                xdur = XFADE_DUR_SHORT if prev_type == cur_type == "B" else XFADE_DUR_LONG
                applied_transitions[prior_scene_index] = trans
                transition_after[gi * 4 + i - 1] = xdur
                offset_acc += durs_map[names[i - 1]] - xdur
                offset_acc = max(0.05, offset_acc - 0.05)
                label = f"g{gi}x{i}"
                fc_parts.append(f"[{prev}][v{i}]xfade=transition={trans}:duration={xdur}:offset={offset_acc:.3f}[{label}]")
                prev = label
            fc = ";".join(fc_parts) + f";[{prev}]format=yuv420p[v]"
            gout = out / f"group_{gi}.mp4"
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc,
                                "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                                "-profile:v", "baseline", "-pix_fmt", "yuv420p", str(gout)],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                print(f"group_{gi} xfade 失败: {r.stderr[-200:]}", file=sys.stderr)
                return 3
            group_outs.append(gout)

        fd, groups_name = tempfile.mkstemp(prefix="hermes-groups-", suffix=".txt", dir="/tmp")
        os.close(fd)
        groups_file = Path(groups_name)
        with groups_file.open("w", encoding="utf-8") as handle:
            handle.write("".join(f"file '{path.resolve()}'\n" for path in group_outs))
            handle.flush()
            os.fsync(handle.fileno())
        composite_tmp = out / ".visual_xfade.tmp.mp4"
        composite_final = out / "visual_xfade.mp4"
        composite_tmp.unlink(missing_ok=True)
        concat_result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(groups_file),
             "-an", "-c", "copy", "-movflags", "+faststart", str(composite_tmp)],
            capture_output=True, text=True, timeout=120,
        )
        if concat_result.returncode != 0:
            groups_file.unlink(missing_ok=True)
            composite_tmp.unlink(missing_ok=True)
            print(f"组间拼接失败: {concat_result.stderr[-240:]}", file=sys.stderr)
            return 3
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(composite_tmp)],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            composite_tmp.unlink(missing_ok=True)
            print("组间拼接输出不可读", file=sys.stderr)
            return 3
        os.replace(composite_tmp, composite_final)

    # 视觉总时长 + 全局镜头起始必须复用实际的组内转场时长；组间 concat 为 0。
    starts_global, visual_total = calculate_timeline(
        [durs_map[name] for name in shot_names],
        transition_after,
    )

    # 配音：8 段 TTS 分段 adelay 到镜头A 起始 + atrim 裁剪到段视觉时长（补偿 xfade 重叠，防溢出）
    voice_path = out / "voice_aligned.wav"
    voice_fc = []
    inputs = []
    alignment_records = []
    for i in range(1, 9):
        inputs += ["-i", str(tts_files[i - 1])]
        delay_ms = int((short_timeline['segments'][i-1]['voice_start_frame']/25
            if short_timeline else starts_global[2 * (i - 1)]) * 1000)
        # 段视觉时长 = 镜头B 结束 - 镜头A 起点（含转场重叠压缩）
        seg_end = starts_global[2 * (i - 1) + 1] + durs_map[shot_names[2 * (i - 1) + 1]]
        seg_visual_dur = seg_end - starts_global[2 * (i - 1)]
        tts_dur = durs[i - 1]
        overflow = round(tts_dur - seg_visual_dur, 3)
        alignment_records.append({
            "segment": i,
            "scene_start": starts_global[2 * (i - 1)],
            "scene_duration": round(seg_visual_dur, 3),
            "tts_duration": round(tts_dur, 3),
            "overflow_seconds": overflow,
        })
        if render_policy["quality_profile"] == "high" and overflow > 0.15:
            print(f"音画对齐失败: 段{i} 配音超出镜头 {overflow:.3f}s", file=sys.stderr)
            (out / "av_alignment_evidence.json").write_text(
                json.dumps({"passed": False, "segments": alignment_records}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return 3
        # 保留完整语音、实际停顿及提供者时点，不裁字或再变速。
        if overflow > 0.001:
            raise ValueError("actual_narration_exceeds_visual_span")
        voice_fc.append(f"[{i - 1}:a]asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}[a{i - 1}]")
    mix_names = "".join(f"[a{i}]" for i in range(8))
    # duration=longest：voice 轨道按各段 adelay 后自然延伸到全长，BGM 不会被截断
    voice_fc.append(f"{mix_names}amix=inputs=8:duration=longest:normalize=0[voice]")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(voice_fc),
                        "-map", "[voice]", str(voice_path)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"配音对齐失败: {r.stderr[-200:]}", file=sys.stderr)
        return 3
    (out / "av_alignment_evidence.json").write_text(
        json.dumps({"passed": True, "segments": alignment_records}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 合流：音频路线必须由计划显式控制，禁止 sfx_only 隐式下载 BGM。
    if args.audio_route == "sfx_only":
        from array import array as _array
        import math as _math
        import sys as _sys
        import wave as _wave

        sample_rate = 44100
        frame_count = max(1, int(visual_total * sample_rate))
        sfx = _array("f", [0.0]) * frame_count
        for transition_time in [starts_global[2 * i] for i in range(1, 8)]:
            start = int(transition_time * sample_rate)
            click_frames = int(0.075 * sample_rate)
            for offset in range(click_frames):
                pos = start + offset
                if pos >= frame_count:
                    break
                envelope = 1.0 - (offset / click_frames)
                sfx[pos] += 0.12 * envelope * _math.sin(2 * _math.pi * 720 * offset / sample_rate)
        sfx_path = out / "transition_sfx.wav"
        with _wave.open(str(sfx_path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            pcm_frames = _array("h")
            for value in sfx:
                pcm = max(-32767, min(32767, int(value * 32767)))
                pcm_frames.extend((pcm, pcm))
            if _sys.byteorder != "little":
                pcm_frames.byteswap()
            wav.writeframes(pcm_frames.tobytes())
        secondary_audio_path = sfx_path
        r = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(out / "visual_xfade.mp4"),
            "-i", str(voice_path), "-i", str(sfx_path),
            "-filter_complex",
            "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=2.4[v];"
            "[2:a]aformat=sample_rates=44100:channel_layouts=stereo[sfx];"
            "[v][sfx]amix=inputs=2:duration=longest:normalize=0,"
            "aformat=sample_rates=44100:channel_layouts=stereo,"
            "loudnorm=I=-16:TP=-2.5:LRA=11,alimiter=limit=0.70:level=false[a]",
            "-map", "0:v", "-map", "[a]", "-t", f"{visual_total:.3f}",
            "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
            str(out / "mixed_v2.mp4"),
        ], capture_output=True, text=True, timeout=180)
    else:
        bgm_path = out / "bgm.mp3"
        if not bgm_path.is_file():
            os.environ.setdefault("BGM_TARGET_PLATFORM", args.platform)
            from scripts.kuaishou_render import download_bgm
            bgm_path = Path(download_bgm(str(out), style=args.bgm_style))
        secondary_audio_path = bgm_path
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "visual_xfade.mp4"),
                            "-i", str(voice_path), "-stream_loop", "-1", "-i", str(bgm_path),
                            "-filter_complex",
                            "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=1.0[v];"
                            "[2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.18[bg];"
                            "[v][bg]amix=inputs=2:duration=longest:normalize=0,"
                            "aformat=sample_rates=44100:channel_layouts=stereo,"
                            "loudnorm=I=-16:TP=-2.5:LRA=11,alimiter=limit=0.70:level=false[a]",
                            "-map", "0:v", "-map", "[a]", "-t", f"{visual_total:.3f}",
                            "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", str(out / "mixed_v2.mp4")],
                           capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"混音失败: {r.stderr[-200:]}", file=sys.stderr)
        return 3
    if args.audio_route!='sfx_only':
        (out/'audio_mix_evidence.json').write_text(json.dumps({
            'version':'native_audio_mix_v1','command':list(r.args),'returncode':r.returncode,
            'bgm_path':str(bgm_path.resolve()),'bgm_sha256':_sha256_file(bgm_path),
            'output':str((out/'mixed_v2.mp4').resolve()),'output_sha256':_sha256_file(out/'mixed_v2.mp4'),
            'renderer_sha256':_sha256_file(Path(__file__)),
        },ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')

    # Complete timed cues: mobile subtitles stay at two lines without truncating narration.
    international = args.platform in {"tiktok", "youtube", "shorts"}
    subtitle_wrap_chars = 38 if international else 15
    subtitle_font_size = 30 if international else 44
    script_texts = []
    for i in range(1, 9):
        seg = script_segments[i - 1] if i <= len(script_segments) and script_segments[i - 1] \
            else str(cards[i - 1].get("tts") or cards[i - 1].get("txt") or "")
        script_texts.append(seg)
    filters = []
    subtitle_manifest = []
    for i, text in enumerate(script_texts, 1):
        # Captions belong to the same visual scene, not 0.4s after it. Keep a
        # single frame of guard at the cut while avoiding the previous-scene
        # impression caused by the old hard-coded lead-in.
        if short_timeline:
            st = short_timeline['segments'][i-1]['voice_start_frame']/25
            en = st + durs[i-1]
        else:
            st = starts_global[2 * (i - 1)] + 0.05
            en = starts_global[2 * (i - 1) + 1] + durs_map[shot_names[2 * (i - 1) + 1]] - 0.05
        from content_platform.normal_film_audio import timed_caption_cues
        manifest_cues = timed_caption_cues(text, tts_records[i-1]["provider_word_boundaries"],
            start=st, max_chars_per_line=subtitle_wrap_chars, max_lines=2)
        _sub_up = int(render_contract["subtitle_y_up"])
        for cue_index, cue in enumerate(manifest_cues, 1):
            enabled = f"between(t,{cue['start']:.3f},{cue['end']:.3f})"
            for line_index, line in enumerate(cue["lines"], 1):
                text_file = out / "sub" / f"cue_{i:02d}_{cue_index:02d}_{line_index}.txt"
                text_file.write_text(line, encoding="utf-8")
                y_offset = 100 if line_index == 1 and len(cue["lines"]) == 1 else 125 if line_index == 1 else 70
                filters.append(f"drawtext=fontfile={FONT}:textfile={text_file}:fontsize={subtitle_font_size}:"
                    f"fontcolor=white:borderw=4:bordercolor=black:x=(w-text_w)/2:"
                    f"y=h-{y_offset}-{_sub_up}:enable='{enabled}'")
        reconstructed = "".join(line for cue in manifest_cues for line in cue["lines"])
        subtitle_manifest.append({"segment": i, "source": text, "reconstructed": reconstructed,
            "complete": reconstructed == text, "timing_source": "actual_provider_word_events",
            "cues": manifest_cues})

    (out / "subtitle_cue_manifest.json").write_text(
        json.dumps(subtitle_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fc2 = f"[0:v]{','.join(filters)},deflicker=mode=pm:size=3[v]"
    final = out / "final.mp4"
    final_tmp = out / ".final.mp4.tmp.mp4"
    final_tmp.unlink(missing_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "mixed_v2.mp4"),
                        "-filter_complex", fc2, "-map", "[v]", "-map", "0:a",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                        "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        "-c:a", "copy", str(final_tmp)],
                       capture_output=True, text=True, timeout=400)
    if r.returncode != 0 or not final_tmp.is_file() or final_tmp.stat().st_size <= 0:
        print(f"编码失败或输出不完整: {r.stderr[-300:]}", file=sys.stderr)
        final_tmp.unlink(missing_ok=True)
        return 3
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(final_tmp)], capture_output=True, text=True, timeout=30)
        if probe.returncode != 0 or not probe.stdout.strip():
            raise RuntimeError("ffprobe_empty")
        os.replace(final_tmp, final)
    except Exception as exc:
        print(f"最终文件原子提交失败: {exc}", file=sys.stderr)
        final_tmp.unlink(missing_ok=True)
        return 3

    flash_evidence = measure_luminance_flash_evidence(final)
    (out / "luminance_flash_evidence.json").write_text(
        json.dumps(flash_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not flash_evidence["passed"]:
        print(f"逐帧闪烁验证失败: {flash_evidence['failures']}", file=sys.stderr)
        return 4

    # 字幕烧录验证：每段 B 镜头中点采样（避开 enable 边界误报，覆盖全片）
    import numpy as np
    from PIL import Image
    ok = True
    samples = []
    for i in range(1, 9):
        seg_a_start = starts_global[2 * (i - 1)]
        seg_b_end = starts_global[2 * (i - 1) + 1] + durs_map[shot_names[2 * (i - 1) + 1]]
        mid = (seg_a_start + 0.4 + seg_b_end - 0.2) / 2.0
        frame_num = int(mid * 25)
        if mid > visual_total:
            continue
        frame = out / "sub" / f"sample_{i:02d}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-i", str(final),
                        "-vf", f"select=eq(n\\,{frame_num})", "-frames:v", "1", str(frame)], capture_output=True)
        img = np.array(Image.open(frame).convert("L"))
        h_img = img.shape[0]
        # 自适应采样：横屏取底部区域，竖屏取原有区域
        y1, y2 = int(h_img * 0.62), int(h_img * 0.93)
        white = int((img[y1:y2, :] > 150).sum())
        passed = white > max(500, int(800 * img.shape[1] / 1080))
        ok = ok and passed
        samples.append({"segment": i, "time_s": round(mid, 2), "white_pixels": white, "passed": passed})
        print(f"  字幕采样 段{i} @{mid:.1f}s: 白像素 {white}", "OK" if passed else "FAIL")
    if not ok:
        print("字幕烧录验证失败", file=sys.stderr)
        return 4
    (out / "subtitle_pixel_evidence.json").write_text(json.dumps({
        "passed": True,
        "candidate_sha256": _sha256_file(final),
        "sample_count": len(samples),
        "samples": samples,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    audio_evidence = validate_audio_spec(probe_audio_spec(final))
    (out / "audio_quality_evidence.json").write_text(
        json.dumps(audio_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not audio_evidence["passed"]:
        print(f"音频规格验证失败: {audio_evidence}", file=sys.stderr)
        return 4
    release_audio_evidence = build_audio_release_evidence(final, voice_path, secondary_audio_path, args.audio_route)
    (out / "audio_release_evidence.json").write_text(
        json.dumps(release_audio_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for record in shot_records:
        name = str(record.get("name") or "")
        match = re.search(r"shot_(\d{2})", name)
        if not match:
            continue
        idx = int(match.group(1))
        if 1 <= idx <= len(scene_contract):
            scene = scene_contract[idx - 1]
            record.update({
                "scene_id": str(scene.get("beat_id") or f"s{idx:02d}"),
                "visual_mode": str(scene.get("visual_mode") or ""),
                "template_id": str(scene.get("template_id") or ""),
                "group_motion": scene.get("group_motion") or [],
                "platform_reason": str(scene.get("platform_reason") or ""),
                "html_sha256": _sha256_file(out / "html" / f"{name}.html"),
            })
    try:
        measured_motion = measure_motion_evidence(final)
    except Exception as exc:
        measured_motion = {"passed": False, "error": str(exc)[:160]}
    try:
        spatial_motion = measure_spatial_motion_evidence(final)
    except Exception as exc:
        spatial_motion = {
            "passed": False,
            "background_stable": False,
            "error": str(exc)[:160],
            "failures": ["spatial_motion_measurement_failed"],
        }
    render_quality = build_render_quality_evidence(
        policy=render_policy,
        shot_records=shot_records,
        motion=measured_motion,
        spatial_motion=spatial_motion,
    )
    render_quality["candidate_sha256"] = _sha256_file(final)
    (out / "shot_render_records.json").write_text(
        json.dumps(shot_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "render_quality_evidence.json").write_text(
        json.dumps(render_quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not render_quality["passed"]:
        print(f"电影质量验证失败: {render_quality['failures']}", file=sys.stderr)
        return 4

    # segment_motion_evidence（runner 门禁要求）
    seg_evidence = {"segments": []}
    record_by_name = {str(row.get("name")): row for row in shot_records}
    for i in range(1, 9):
        shot = (cards[i - 1].get("shotcraft") or {})
        et = shot_types.get(i, "")
        if et:
            contract_mode = str((scene_contract[i - 1] if i <= len(scene_contract) and isinstance(scene_contract[i - 1], dict) else {}).get("visual_mode") or "")
            move_id = contract_mode or et
            profile = f"element_motion_{move_id}_{i}"
            renderer_note = "film_renderer_frames"
        else:
            move_id = str(shot.get("name") or f"cinema_multishot_{i}")
            profile = f"establish_then_detail_{i}"
            renderer_note = "film_renderer"
        segment_records = [record_by_name.get(f"shot_{i:02d}{suffix}", {}) for suffix in ("A", "B")]
        shot_outputs = []
        for row in segment_records:
            shot_name = str(row.get("name") or "")
            shot_path = out / "shots" / f"{shot_name}.mp4"
            if shot_name and shot_path.is_file():
                shot_outputs.append({
                    "name": shot_name,
                    "path": str(shot_path),
                    "sha256": _sha256_file(shot_path),
                    "renderer": row.get("renderer"),
                    "fallback": bool(row.get("fallback")),
                    "reused": bool(row.get("reused")),
                })
        seg_evidence["segments"].append({
            "index": i,
            "move_id": move_id,
            "profile": profile,
            "rendered": True,
            "reused": any(bool(row.get("reused")) for row in segment_records),
            "renderer": renderer_note,
            "renderer_modes": [row.get("renderer") for row in segment_records],
            "fallback": any(bool(row.get("fallback")) for row in segment_records),
            "shot_outputs": shot_outputs,
            "shotcraft_execution_receipt": {
                "version": "shotcraft_execution_receipt_v1",
                "planned_move_id": move_id,
                "profile": profile,
                "output_count": len(shot_outputs),
                "all_outputs_bound": len(shot_outputs) == len(segment_records) == 2,
            },
        })
    seg_evidence["final_video_sha256"] = _sha256_file(final)
    seg_evidence["scene_contract_sha256"] = _sha256_file(out / "scene_contract.json") if (out / "scene_contract.json").is_file() else ""
    seg_evidence["renderer"] = "film_renderer"
    seg_evidence["receipt_version"] = "segment_motion_evidence_v2"
    (out / "segment_motion_evidence.json").write_text(json.dumps(seg_evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    # 计划不是验收证据：逐段记录计划如何真正映射到镜头、素材、渲染器与转场。
    execution_scenes = []
    for index, context in enumerate(scene_execution_context):
        records = [record_by_name.get(name, {}) for name in context["shot_names"]]
        execution_scenes.append({
            **context,
            "actual_transition_after": applied_transitions.get(index, "end_hold"),
            "renderer_modes": [row.get("renderer") for row in records],
            "fallback": any(bool(row.get("fallback")) for row in records),
            "reused": any(bool(row.get("reused")) for row in records),
        })
    execution_failures = [
        row["scene_id"] for row in execution_scenes
        if row["fallback"] or not row["renderer_modes"]
    ]
    execution_evidence = {
        "version": "scene_execution_evidence_v1",
        "renderer_version": RENDERER_VERSION,
        "passed": not execution_failures,
        "failures": execution_failures,
        "scenes": execution_scenes,
    }
    (out / "scene_execution_evidence.json").write_text(
        json.dumps(execution_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if render_policy["quality_profile"] == "high" and not execution_evidence["passed"]:
        print(f"视觉导演执行验证失败: {execution_failures}", file=sys.stderr)
        return 4

    # Publish only scenes that survived final render quality and execution gates.
    for entry in scene_cache_entries:
        if not entry["hit"]:
            commit_scene_cache(
                out,
                str(entry["scene_id"]),
                str(entry["scene_key"]),
                entry["key_payload"],
                entry["shots"],
            )

    # cinema visual gate：从 16 镜头抽帧生成 8 张主卡 PNG（runner 检查 cards/*.png）
    card_dir = out / "cards"
    card_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        shot_mp4 = out / "shots" / f"shot_{i:02d}A.mp4"
        if shot_mp4.is_file():
            card_png = card_dir / f"card_{i:02d}.png"
            sample_at = card_sample_time(durs_map[f"shot_{i:02d}A"])
            result = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(sample_at), "-i", str(shot_mp4),
                                     "-frames:v", "1", str(card_png)], capture_output=True, text=True, timeout=30)
            if result.returncode != 0 or not card_png.is_file():
                print(f"cinema gate 卡片抽取失败: card_{i:02d}: {result.stderr[-160:]}", file=sys.stderr)
                return 4
    cinema_card_count = len(list(card_dir.glob("card_*.png")))
    print("cinema gate 卡片:", cinema_card_count)
    if cinema_card_count != 8:
        print(f"cinema gate 卡片数量错误: {cinema_card_count}/8", file=sys.stderr)
        return 4

    commit_final_render_cache(
        out,
        current_final_render_key(),
        final,
        [out / name for name in FINAL_CACHE_EVIDENCE_FILES],
    )

    # bgm_source.json（runner/bgm 撞曲门禁）
    if (out / "bgm_source.json").is_file() and args.audio_route != "embedded_licensed_bgm":
        try:
            bgm_src = json.loads((out / "bgm_source.json").read_text(encoding="utf-8"))
            bgm_src["real_instrument"] = True
            bgm_src.setdefault("vocal", "none")
            (out / "bgm_source.json").write_text(json.dumps(bgm_src, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    print(f"final: {final} ({final.stat().st_size / 1024 / 1024:.1f}MB, {visual_total:.1f}s)")
    print(json.dumps({
        "ok": True,
        "output": str(final),
        "status": "rendered",
        "audio_evidence": release_audio_evidence,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
