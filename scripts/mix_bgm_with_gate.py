#!/usr/bin/env python3
"""Mix video voiceover with licensed BGM and verify the rendered audio.

This is the shared helper for short-video renderers. It fixes the common ffmpeg
``amix`` mono-input trap by converting both inputs to stereo before mixing, then
writes a machine-readable probe that upload gates can inspect.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _duration(path: Path) -> float:
    result = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], timeout=30)
    try:
        return float(result.stdout.strip() or 0)
    except ValueError:
        return 0.0


def _audio_channels(path: Path) -> int:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=channels",
            "-of",
            "csv=p=0",
            str(path),
        ],
        timeout=30,
    )
    try:
        return int(result.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        return 0


def _mean_volume(path: Path) -> float | None:
    result = _run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], timeout=60)
    text = result.stderr + "\n" + result.stdout
    match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", text)
    return float(match.group(1)) if match else None


def _segment_mean_volume(path: Path, start: float, duration: float = 5.0) -> float | None:
    result = _run(
        ["ffmpeg", "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        timeout=60,
    )
    text = result.stderr + "\n" + result.stdout
    match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", text)
    return float(match.group(1)) if match else None


def mix_bgm(
    video: Path,
    bgm: Path,
    output: Path,
    bgm_weight: float = 0.45,
    voice_gain: float = 2.2,
    target_lufs: float = -16.0,
) -> dict:
    duration = _duration(video)
    if duration <= 0:
        return {"ok": False, "error": "input_duration_unreadable", "input": str(video)}
    if not bgm.is_file() or bgm.stat().st_size < 50_000:
        return {"ok": False, "error": "bgm_missing_or_too_small", "bgm": str(bgm)}
    output.parent.mkdir(parents=True, exist_ok=True)
    bgm_weight = max(0.3, min(float(bgm_weight), 1.0))
    voice_gain = max(1.0, min(float(voice_gain), 4.0))
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-stream_loop",
        "-1",
        "-i",
        str(bgm),
        "-filter_complex",
        (
            f"[0:a]aformat=channel_layouts=stereo,volume={voice_gain}[voice];"
            f"[1:a]atrim=0:{duration:.3f},aformat=channel_layouts=stereo,volume={bgm_weight}[bgm];"
            "[voice][bgm]amix=inputs=2:duration=first:normalize=0,"
            "alimiter=limit=0.95[aout]"
        ),
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-shortest",
        str(output),
    ]
    result = _run(command)
    if result.returncode != 0:
        return {"ok": False, "error": "ffmpeg_mix_failed", "stderr_tail": result.stderr[-500:]}
    channels = _audio_channels(output)
    mean_volume = _mean_volume(output)
    head_volume = _segment_mean_volume(output, 0.0)
    tail_volume = _segment_mean_volume(output, max(0.0, duration - 6.0))
    bgm_volume = _mean_volume(bgm)
    tail_gap = None if head_volume is None or tail_volume is None else abs(head_volume - tail_volume)
    ok = (
        channels >= 2
        and mean_volume is not None
        and -24 <= mean_volume <= -6
        and bgm_volume is not None
        and bgm_volume > -40
        and (tail_gap is None or tail_gap <= 10)
        and output.stat().st_size > 100_000
    )
    return {
        "ok": ok,
        "output": str(output),
        "duration_seconds": round(duration, 3),
        "audio_channels": channels,
        "mean_volume_db": mean_volume,
        "head_mean_volume_db": head_volume,
        "tail_mean_volume_db": tail_volume,
        "head_tail_gap_db": tail_gap,
        "bgm_mean_volume_db": bgm_volume,
        "bgm_weight": bgm_weight,
        "voice_gain": voice_gain,
        "target_lufs": target_lufs,
        "mix_rule": "voice_gain + looped real BGM + amix normalize=0 + limiter; no synthetic or silent BGM fallback",
        "size": output.stat().st_size if output.exists() else 0,
        "error": "" if ok else "audio_probe_failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Mix short-video voiceover with BGM and write an audio gate probe.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--bgm", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--probe", default="")
    parser.add_argument("--bgm-weight", type=float, default=0.45)
    parser.add_argument("--voice-gain", type=float, default=2.2)
    args = parser.parse_args()
    result = mix_bgm(Path(args.video), Path(args.bgm), Path(args.output), args.bgm_weight, args.voice_gain)
    if args.probe:
        Path(args.probe).parent.mkdir(parents=True, exist_ok=True)
        Path(args.probe).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
