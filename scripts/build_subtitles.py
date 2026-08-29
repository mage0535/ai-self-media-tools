#!/usr/bin/env python3
"""Shared ASS subtitle builder for mobile-first video renderers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


_PLATFORM_SPECS = {
    "default": {"width": 720, "height": 1280, "font_size": 48, "margin_v": 200, "max_chars": 16, "max_lines": 2},
    "kuaishou": {"width": 720, "height": 1280, "font_size": 48, "margin_v": 200, "max_chars": 16, "max_lines": 2},
    "douyin": {"width": 720, "height": 1280, "font_size": 48, "margin_v": 200, "max_chars": 16, "max_lines": 2},
    "shipinhao": {"width": 720, "height": 1280, "font_size": 46, "margin_v": 190, "max_chars": 16, "max_lines": 2},
    "tiktok": {"width": 720, "height": 1280, "font_size": 48, "margin_v": 200, "max_chars": 16, "max_lines": 2},
    "youtube": {"width": 720, "height": 1280, "font_size": 48, "margin_v": 200, "max_chars": 16, "max_lines": 2},
    "bilibili": {"width": 1920, "height": 1080, "font_size": 52, "margin_v": 92, "max_chars": 28, "max_lines": 2},
}


def subtitle_spec(platform: str) -> dict[str, int]:
    return dict(_PLATFORM_SPECS.get(str(platform or "").casefold(), _PLATFORM_SPECS["default"]))


def ass_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"


def wrap_text(text: str, *, max_chars: int, max_lines: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip().replace("{", "").replace("}", "")
    if not text:
        return ""
    lines: list[str] = []
    current = ""
    current_width = 0
    limit = max_chars * 2
    for char in text:
        width = 1 if ord(char) < 128 else 2
        if current and current_width + width > limit:
            lines.append(current)
            current = char
            current_width = width
            if len(lines) >= max_lines:
                break
        else:
            current += char
            current_width += width
    if len(lines) < max_lines and current:
        lines.append(current)
    shown = "".join(lines)
    if len(shown) < len(text) and lines:
        lines[-1] = lines[-1].rstrip("，。,. ") + "..."
    return r"\N".join(lines[:max_lines])


def build_ass(cues: list[tuple[float, float, str]], *, platform: str = "default") -> str:
    spec = subtitle_spec(platform)
    events = []
    expanded = []
    for start, end, text in cues:
        expanded.extend(split_timed_cue(start, end, text, max_chars=spec["max_chars"], max_lines=spec["max_lines"]))
    for start, end, text in expanded:
        if float(end) <= float(start):
            continue
        wrapped = wrap_text(text, max_chars=spec["max_chars"], max_lines=spec["max_lines"])
        if wrapped:
            events.append(f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},Default,,0,0,0,,{wrapped}")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {spec['width']}
PlayResY: {spec['height']}
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,{spec['font_size']},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,3,2,0,2,20,20,{spec['margin_v']},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{chr(10).join(events)}"""


def split_timed_cue(start: float, end: float, text: str, *, max_chars: int, max_lines: int) -> list[tuple[float, float, str]]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    capacity = max(8, int(max_chars) * int(max_lines))
    if not clean:
        return []
    chunks = []
    remaining = clean
    while remaining:
        if len(remaining) <= capacity:
            chunks.append(remaining)
            break
        window = remaining[: capacity + 1]
        boundary = max(window.rfind(mark) for mark in "，。！？；,.!?;")
        cut = boundary + 1 if boundary >= max(6, capacity // 2) else capacity
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    total_weight = sum(max(1, len(chunk)) for chunk in chunks)
    cursor = float(start)
    duration = max(0.01, float(end) - float(start))
    result = []
    for index, chunk in enumerate(chunks):
        next_cursor = float(end) if index == len(chunks) - 1 else cursor + duration * max(1, len(chunk)) / total_weight
        result.append((cursor, next_cursor, chunk))
        cursor = next_cursor
    return result


def _audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return float(result.stdout.strip() or 0)
    except ValueError:
        return 0.0


def write_ass_from_cards(video_dir: Path, cards: list[dict[str, Any]], *, platform: str = "kuaishou", output: Path | None = None) -> Path:
    video_dir = Path(video_dir)
    offset = 0.0
    cues: list[tuple[float, float, str]] = []
    for index, card in enumerate(cards, start=1):
        duration = _audio_duration(video_dir / "tts" / f"tts_{index:02d}.mp3") or 6.0
        text = str(card.get("tts") or card.get("txt") or card.get("sub") or card.get("f") or "")
        cues.append((offset, offset + duration, text))
        offset += duration
    destination = output or video_dir / "subtitles.ass"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_ass(cues, platform=platform), encoding="utf-8")
    return destination


def load_cards(cards_path: Path) -> list[dict[str, Any]]:
    """Read cards authored on Windows as well as Linux without BOM failures."""
    payload = json.loads(cards_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("cards JSON must be a list")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build lower-third ASS subtitles from cards and TTS durations.")
    parser.add_argument("--video-dir", required=True)
    parser.add_argument("--cards", default="")
    parser.add_argument("--platform", default="kuaishou")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    video_dir = Path(args.video_dir)
    cards_path = Path(args.cards) if args.cards else video_dir / "cards.json"
    cards = load_cards(cards_path)
    output = write_ass_from_cards(video_dir, cards, platform=args.platform, output=Path(args.output) if args.output else None)
    print(json.dumps({"ok": True, "output": str(output), "platform": args.platform}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
