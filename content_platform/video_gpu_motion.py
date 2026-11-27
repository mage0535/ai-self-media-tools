"""GPU-accelerated video encoding (NVENC), Vulkan Chromium flags, deterministic spring motion
runtime (HyperFrames declarative timeline + Remotion spring physics), and word-level kinetic ASS captions."""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=8)
def _probe_nvenc_profile(profile: str) -> bool:
    """Verify real hardware h264_nvenc availability with a 2-frame FFmpeg probe."""
    try:
        res = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=black:s=256x256:r=25:d=0.08",
                "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "20", "-b:v", "0",
                "-profile:v", profile, "-pix_fmt", "yuv420p", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def clear_hwaccel_cache() -> None:
    """Reset cached GPU probe results (used by unit tests)."""
    _probe_nvenc_profile.cache_clear()


def video_encoder_args(
    *,
    crf: int = 20,
    preset: str = "medium",
    profile: str = "baseline",
    mode: str | None = None,
) -> list[str]:
    """Return FFmpeg video encoder args using RTX NVENC when available, else libx264."""
    selected = str(mode if mode is not None else os.environ.get("FILM_HWACCEL", "auto")).strip().casefold()
    if selected not in {"cpu", "libx264", "off", "0", "false"}:
        # Probe requested profile first; if baseline is rejected by a driver, try main.
        for prof in (profile, "main") if profile != "main" else ("main",):
            if _probe_nvenc_profile(prof):
                nv_preset = "p4" if preset in {"medium", "slow"} else "p2"
                return [
                    "-c:v", "h264_nvenc",
                    "-preset", nv_preset,
                    "-rc", "vbr",
                    "-cq", str(int(crf)),
                    "-b:v", "0",
                    "-profile:v", prof,
                    "-pix_fmt", "yuv420p",
                ]
        if selected == "nvenc":
            raise RuntimeError("FILM_HWACCEL=nvenc requested but h264_nvenc probe failed")
    return [
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(int(crf)),
        "-profile:v", profile,
        "-pix_fmt", "yuv420p",
    ]


def video_bitrate_encoder_args(
    *,
    video_kbps: int,
    preset: str = "veryfast",
    mode: str | None = None,
) -> list[str]:
    """Return bitrate-capped FFmpeg video encoder args (e.g., B05 reference transport) using NVENC when available."""
    kbps = max(80, int(video_kbps))
    selected = str(mode if mode is not None else os.environ.get("FILM_HWACCEL", "auto")).strip().casefold()
    if selected not in {"cpu", "libx264", "off", "0", "false"}:
        if _probe_nvenc_profile("main"):
            return [
                "-c:v", "h264_nvenc",
                "-preset", "p2",
                "-rc", "vbr",
                "-b:v", f"{kbps}k",
                "-maxrate", f"{kbps * 2}k",
                "-bufsize", f"{kbps * 4}k",
                "-profile:v", "main",
                "-pix_fmt", "yuv420p",
            ]
        if selected == "nvenc":
            raise RuntimeError("FILM_HWACCEL=nvenc requested but h264_nvenc probe failed")
    return [
        "-c:v", "libx264",
        "-preset", preset,
        "-b:v", f"{kbps}k",
        "-maxrate", f"{kbps * 2}k",
        "-bufsize", f"{kbps * 4}k",
    ]


# Curated per-platform mobile/landscape subtitle safe zones absorbed from scripts/build_subtitles.py
_PLATFORM_SUBTITLE_SPECS: dict[str, dict[str, int]] = {
    "default": {"ref_w": 720, "ref_h": 1280, "font_size": 48, "margin_v": 200, "max_chars": 15, "max_lines": 2},
    "kuaishou": {"ref_w": 720, "ref_h": 1280, "font_size": 48, "margin_v": 200, "max_chars": 15, "max_lines": 2},
    "douyin": {"ref_w": 720, "ref_h": 1280, "font_size": 48, "margin_v": 200, "max_chars": 15, "max_lines": 2},
    "douyin_ai": {"ref_w": 720, "ref_h": 1280, "font_size": 48, "margin_v": 200, "max_chars": 15, "max_lines": 2},
    "douyin_pet": {"ref_w": 720, "ref_h": 1280, "font_size": 48, "margin_v": 200, "max_chars": 15, "max_lines": 2},
    "shipinhao": {"ref_w": 720, "ref_h": 1280, "font_size": 46, "margin_v": 190, "max_chars": 15, "max_lines": 2},
    "tiktok": {"ref_w": 720, "ref_h": 1280, "font_size": 42, "margin_v": 200, "max_chars": 38, "max_lines": 2},
    "youtube": {"ref_w": 720, "ref_h": 1280, "font_size": 42, "margin_v": 200, "max_chars": 38, "max_lines": 2},
    "shorts": {"ref_w": 720, "ref_h": 1280, "font_size": 42, "margin_v": 200, "max_chars": 38, "max_lines": 2},
    "bilibili": {"ref_w": 1920, "ref_h": 1080, "font_size": 52, "margin_v": 92, "max_chars": 28, "max_lines": 2},
}


def platform_subtitle_spec(platform: str, width: int = 1080, height: int = 1920) -> dict[str, int]:
    """Scale curated platform subtitle margins/font sizes proportionally to target video dimensions."""
    key = str(platform or "default").strip().casefold()
    base = _PLATFORM_SUBTITLE_SPECS.get(key, _PLATFORM_SUBTITLE_SPECS["default"])
    scale_h = max(0.4, float(height) / float(base["ref_h"]))
    # Landscape fallback when width > height on a vertical-default platform key
    if width > height and base["ref_w"] < base["ref_h"]:
        base = _PLATFORM_SUBTITLE_SPECS["bilibili"]
        scale_h = max(0.4, float(height) / float(base["ref_h"]))
    return {
        "width": int(width),
        "height": int(height),
        "font_size": max(24, int(round(base["font_size"] * scale_h * 0.65))) if width < height else max(28, int(round(base["font_size"] * scale_h))),
        "margin_v": max(48, int(round(base["margin_v"] * scale_h))),
        "max_chars": int(base["max_chars"]),
        "max_lines": int(base["max_lines"]),
    }


def render_broll_shot(
    video_path: Path | str,
    target: Path | str,
    *,
    duration: float,
    width: int = 1080,
    height: int = 1920,
    fps: int = 25,
) -> bool:
    """Loop, center-crop, gently darken, and GPU-encode a real stock MP4 B-roll shot."""
    src = Path(video_path)
    dst = Path(target)
    if not src.is_file() or duration <= 0:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=increase,"
        f"crop={int(width)}:{int(height)},"
        f"eq=brightness=-0.06:contrast=1.05:saturation=1.06,"
        f"fps={int(fps)},format=yuv420p"
    )
    res = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-stream_loop", "-1", "-i", str(src),
            "-t", f"{float(duration):.3f}",
            "-vf", vf,
            "-an",
            *video_encoder_args(crf=20, preset="medium", profile="baseline"),
            str(dst),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return res.returncode == 0 and dst.is_file() and dst.stat().st_size > 10_000


def encoder_summary(*, profile: str = "baseline", mode: str | None = None) -> dict[str, Any]:
    args = video_encoder_args(profile=profile, mode=mode)
    codec = args[args.index("-c:v") + 1] if "-c:v" in args else "libx264"
    actual_profile = args[args.index("-profile:v") + 1] if "-profile:v" in args else profile
    return {
        "codec": codec,
        "hwaccel": codec == "h264_nvenc",
        "profile": actual_profile,
        "mode": str(mode if mode is not None else os.environ.get("FILM_HWACCEL", "auto")).strip().casefold(),
    }


def chromium_launch_args(*, mode: str | None = None) -> list[str]:
    """Return headless Chromium args enabling NVIDIA Vulkan GPU compositing when present."""
    selected = str(mode if mode is not None else os.environ.get("FILM_CHROMIUM_GPU", "auto")).strip().casefold()
    base = ["--no-sandbox"]
    if selected in {"off", "cpu", "0", "false"}:
        return base
    has_gpu = Path("/dev/nvidia0").exists() and Path("/dev/dri/renderD128").exists()
    if selected == "vulkan" or (selected in {"auto", "gpu", "on", "1", "true"} and has_gpu):
        return [
            "--no-sandbox",
            "--use-gl=angle",
            "--use-angle=vulkan",
            "--enable-features=Vulkan",
            "--enable-webgl",
            "--ignore-gpu-blocklist",
        ]
    return base


# Deterministic JS motion runtime absorbing:
# 1) HyperFrames (Apache-2.0): integer-frame playhead __seekFrame(frame, fps) + declarative
#    data-start / data-duration / data-stagger attributes (zero wall-clock Date.now / setTimeout).
# 2) Remotion Skills (remotion-best-practices): damped spring(frame, fps, {damping, stiffness, mass}),
#    clamped interpolate(), and GPU-composited transform/opacity only (zero font-size/layout reflow).
KINETIC_MOTION_RUNTIME_JS = r"""
(function () {
  if (window.__hermesKineticReady) return;
  window.__hermesKineticReady = true;

  function spring(frame, fps, cfg) {
    fps = Math.max(1, Number(fps) || 25);
    if (frame <= 0) return 0;
    cfg = cfg || {};
    var damping = Math.max(8, Number(cfg.damping || 14));
    var stiffness = Math.max(40, Number(cfg.stiffness || 180));
    var mass = Math.max(0.2, Number(cfg.mass || 1));
    var t = frame / fps;
    var w0 = Math.sqrt(stiffness / mass);
    var zeta = damping / (2 * Math.sqrt(stiffness * mass));
    var val;
    if (zeta < 1) {
      var wd = w0 * Math.sqrt(1 - zeta * zeta);
      val = 1 - Math.exp(-zeta * w0 * t) * (Math.cos(wd * t) + (zeta * w0 / wd) * Math.sin(wd * t));
    } else {
      val = 1 - Math.exp(-w0 * t) * (1 + w0 * t);
    }
    return Math.max(0, Math.min(1.06, val));
  }

  function interpolate(value, inRange, outRange, clamp) {
    if (clamp === undefined) clamp = true;
    var inMin = inRange[0], inMax = inRange[1];
    var outMin = outRange[0], outMax = outRange[1];
    var ratio = inMax === inMin ? 1 : (value - inMin) / (inMax - inMin);
    if (clamp) ratio = Math.max(0, Math.min(1, ratio));
    return outMin + ratio * (outMax - outMin);
  }

  function applyDeclarativeTimeline(frame, fps) {
    var t = Math.max(0, Number(frame) || 0) / Math.max(1, Number(fps) || 25);
    document.body.style.setProperty('--kinetic-frame', String(frame));
    document.body.style.setProperty('--kinetic-t', t.toFixed(4));
    // Respect strict static-container topic/industrial layout gates.
    if (document.body.dataset.topicLayout === 'true') return;

    var nodes = document.querySelectorAll('[data-start]');
    nodes.forEach(function (el, idx) {
      var startSec = parseFloat(el.getAttribute('data-start') || '0') || 0;
      var staggerSec = parseFloat(el.getAttribute('data-stagger') || '0') || 0;
      var durSec = parseFloat(el.getAttribute('data-duration') || '0') || 0;
      var effectiveStart = startSec + idx * staggerSec;
      var enterFrame = (t - effectiveStart) * fps;
      var s = spring(Math.max(effectiveStart <= 0.1 ? 3 : 0, enterFrame), fps, { damping: 15, stiffness: 190, mass: 1 });
      var minOpacity = effectiveStart <= 0.1 ? 0.85 : 0;
      var opacity = interpolate(enterFrame, [0, 6], [minOpacity, 1], true);
      if (durSec > 0 && t > startSec + durSec) {
        opacity = interpolate(t - (startSec + durSec), [0, 0.2], [1, 0], true);
      }
      var dy = (1 - Math.min(1, s)) * 22;
      var scale = 0.95 + 0.05 * s;
      el.style.opacity = opacity.toFixed(3);
      el.style.transform = 'translate3d(0,' + dy.toFixed(2) + 'px,0) scale(' + scale.toFixed(4) + ')';
    });
    var bar = document.getElementById('hermes-global-progress-fill');
    if (bar) {
      var pStart = parseFloat(bar.getAttribute('data-progress-start') || '0') || 0;
      var pEnd = parseFloat(bar.getAttribute('data-progress-end') || '1') || 1;
      var shotDur = Math.max(0.2, parseFloat(bar.getAttribute('data-shot-duration') || '3') || 3);
      var frac = Math.max(0, Math.min(1, t / shotDur));
      var pct = Math.max(0, Math.min(100, (pStart + (pEnd - pStart) * frac) * 100));
      bar.style.transform = 'scaleX(' + (pct / 100).toFixed(4) + ')';
    }
  }

  window.__spring = spring;
  window.__interpolate = interpolate;
  window.__seekFrame = function (frame, fps) {
    fps = Math.max(1, Number(fps) || 25);
    var t = Math.max(0, Number(frame) || 0) / fps;
    applyDeclarativeTimeline(frame, fps);
    if (typeof window.renderFrame === 'function') {
      window.renderFrame(t);
    }
    return t;
  };
  applyDeclarativeTimeline(0, 25);
})();
""".strip()


def inject_kinetic_runtime(
    html_doc: str,
    *,
    progress_start: float | None = None,
    progress_end: float | None = None,
    shot_duration: float | None = None,
    include_progress_bar: bool = False,
) -> str:
    """Inject deterministic HyperFrames/Remotion-style JS runtime (and optional GPU progress bar) before </body>."""
    out = html_doc
    if (
        include_progress_bar
        and "hermes-global-progress-fill" not in out
        and 'data-topic-layout="true"' not in out
        and "data-topic-layout='true'" not in out
        and progress_start is not None
        and progress_end is not None
    ):
        dur_val = max(0.2, float(shot_duration or 3.0))
        bar_html = (
            '<div id="hermes-global-progress" style="position:fixed;top:0;left:0;right:0;height:5px;'
            'background:rgba(255,255,255,0.16);z-index:9999;pointer-events:none;">'
            f'<div id="hermes-global-progress-fill" data-progress-start="{max(0.0, min(1.0, float(progress_start))):.4f}" '
            f'data-progress-end="{max(0.0, min(1.0, float(progress_end))):.4f}" '
            f'data-shot-duration="{dur_val:.3f}" '
            'style="width:100%;height:100%;transform-origin:left center;transform:scaleX(0);'
            'background:linear-gradient(90deg,#FFD54F,#34D399);"></div></div>'
        )
        out = out.replace("</body>", bar_html + "</body>", 1) if "</body>" in out else out + bar_html
    if "__hermesKineticReady" in out:
        return out
    tag = f"<script>{KINETIC_MOTION_RUNTIME_JS}</script>"
    if "</body>" in out:
        return out.replace("</body>", tag + "</body>", 1)
    return out + tag


def _ass_time(seconds: float) -> str:
    """ASS timestamp H:MM:SS.cs (centiseconds)."""
    cs = max(0, int(round(float(seconds) * 100)))
    hours, rem = divmod(cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r", "")
        .replace("\n", r"\N")
    )


def build_kinetic_ass_subtitles(
    subtitle_manifest: list[dict[str, Any]],
    *,
    width: int = 1080,
    height: int = 1920,
    font_size: int = 46,
    margin_v: int = 120,
    active_bgr: str = "&H004FD5FF",   # #FFD54F warm gold (ASS BGR)
    inactive_bgr: str = "&H00FFFFFF", # crisp white
    back_abgr: str = "&H66000000",    # 60%-opacity dark backdrop box (libass BorderStyle=3 uses OutlineColour)
    outline_bgr: str = "&H80000000",
) -> str:
    """Generate mobile-safe word-level kinetic ASS subtitles from actual provider word boundaries.

    Every word highlights in warm gold with a damped spring pop (106% -> 100%) on its exact spoken
    window while keeping the full 1-2 line cue legible over a high-contrast dark backdrop.
    """
    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # BorderStyle=3 uses OutlineColour as the box fill in libass (semi-transparent dark pill backdrop).
        f"Style: Kinetic,Noto Sans CJK SC,{int(font_size)},{inactive_bgr},{active_bgr},{back_abgr},{outline_bgr},"
        f"-1,0,0,0,100,100,1,0,3,12,0,2,48,48,{int(margin_v)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])

    events: list[str] = []
    for seg in subtitle_manifest or []:
        for cue in seg.get("cues") or []:
            cue_start = float(cue.get("start") or 0.0)
            cue_end = float(cue.get("end") or 0.0)
            lines = [str(ln) for ln in (cue.get("lines") or []) if str(ln)]
            if cue_end <= cue_start or not lines:
                continue
            words = [w for w in (cue.get("words") or []) if isinstance(w, dict) and str(w.get("text") or "")]
            if not words:
                text = r"\N".join(_ass_escape(ln) for ln in lines)
                events.append(f"Dialogue: 0,{_ass_time(cue_start)},{_ass_time(cue_end)},Kinetic,,0,0,0,,{text}")
                continue

            # Partition the cue timeline into contiguous word slices so there are zero blank gaps
            # (guarantees stable white pixels for subtitle_pixel_evidence and zero flash spikes).
            n_words = len(words)
            for active_idx, active_word in enumerate(words):
                w_start = cue_start if active_idx == 0 else max(cue_start, float(active_word["start"]))
                if active_idx + 1 < n_words:
                    next_start = float(words[active_idx + 1]["start"])
                    w_end = max(w_start + 0.04, min(cue_end, next_start))
                else:
                    w_end = cue_end
                if w_end <= w_start:
                    continue
                # Rebuild lines with exact active-word gold highlight + subtle damped pop.
                by_line: dict[int, list[str]] = {}
                for idx, w in enumerate(words):
                    li = int(w.get("line_index") or 0)
                    esc_tok = _ass_escape(w["text"])
                    if idx == active_idx:
                        styled = (
                            f"{{\\c{active_bgr}\\fscx106\\fscy106"
                            f"\\t(0,110,\\fscx100\\fscy100)}}{esc_tok}"
                            f"{{\\c{inactive_bgr}\\fscx100\\fscy100}}"
                        )
                    else:
                        styled = esc_tok
                    by_line.setdefault(li, []).append(styled)
                rendered_lines = ["".join(by_line[k]) for k in sorted(by_line)]
                payload = r"\N".join(rendered_lines)
                events.append(f"Dialogue: 0,{_ass_time(w_start)},{_ass_time(w_end)},Kinetic,,0,0,0,,{payload}")

    return header + "\n" + "\n".join(events) + "\n"
