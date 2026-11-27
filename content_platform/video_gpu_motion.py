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


def inject_kinetic_runtime(html_doc: str) -> str:
    """Inject deterministic HyperFrames/Remotion-style JS runtime before </body>."""
    if "__hermesKineticReady" in html_doc:
        return html_doc
    tag = f"<script>{KINETIC_MOTION_RUNTIME_JS}</script>"
    if "</body>" in html_doc:
        return html_doc.replace("</body>", tag + "</body>", 1)
    return html_doc + tag


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
