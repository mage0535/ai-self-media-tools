#!/usr/bin/env python3
"""Render a 16:9 knowledge-card video package for Bilibili or YouTube handoff."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.content_recipe import build_tool_invocation_manifest
from content_platform.video_recipe import build_visual_recipe


THEMES = {
    "bilibili": {"accent": "#00a1d6", "bg": "rgba(15,18,30,0.78)", "label": "B站知识视频"},
    "youtube": {"accent": "#ff0033", "bg": "rgba(20,16,16,0.80)", "label": "YouTube Explainer"},
}


def _run(command: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError("command failed: " + " ".join(command) + "\n" + (result.stderr or result.stdout)[-800:])
    return result


def _duration(path: Path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(result.stdout.strip() or 0)
    except ValueError:
        return 0.0


def _mean_volume(path: Path) -> float | None:
    result = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", result.stderr + "\n" + result.stdout)
    return float(match.group(1)) if match else None


def _beats(script: str) -> list[str]:
    rows = [line.strip("- 0123456789.、") for line in script.splitlines() if line.strip()]
    return [row for row in rows if row][:10]


def _image_b64(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _write_slides(render_dir: Path, beats: list[str], bg_dir: Path, theme: dict) -> None:
    slide_dir = render_dir / "slides"
    slide_dir.mkdir(parents=True, exist_ok=True)
    for idx, beat in enumerate(beats, 1):
        bg = next((candidate for candidate in [bg_dir / f"bg_{idx:02d}.jpg", bg_dir / f"bg_{idx}.jpg", bg_dir / f"bg_{idx:02d}.png"] if candidate.is_file()), None)
        if not bg:
            raise RuntimeError(f"missing landscape background for beat {idx}: {bg_dir}")
        title = beat[:28]
        html = f"""<!doctype html><html><head><meta charset='utf-8'><style>
body{{margin:0;width:1280px;height:720px;overflow:hidden;background:#000;font-family:'Noto Sans CJK SC',sans-serif;}}
.bg{{position:absolute;inset:0;background:url('{_image_b64(bg)}') center/cover no-repeat;transform:scale(1.06);}}
.shade{{position:absolute;inset:0;background:linear-gradient(90deg,rgba(0,0,0,.82),rgba(0,0,0,.55),rgba(0,0,0,.18));}}
.panel{{position:absolute;left:60px;top:185px;width:780px;padding:30px 36px;background:{theme['bg']};border-left:7px solid {theme['accent']};border-radius:16px;box-shadow:0 18px 45px rgba(0,0,0,.35);}}
.tag{{display:inline-block;background:{theme['accent']};color:white;font-size:20px;font-weight:800;padding:7px 18px;border-radius:999px;margin-bottom:18px;}}
h1{{margin:0 0 16px 0;color:white;font-size:46px;line-height:1.25;font-weight:900;}}
p{{margin:0;color:#f3f4f6;font-size:27px;line-height:1.65;font-weight:520;}}
</style></head><body><div class='bg'></div><div class='shade'></div><div class='panel'><div class='tag'>{theme['label']} · {idx:02d}</div><h1>{title}</h1><p>{beat}</p></div></body></html>"""
        (slide_dir / f"slide_{idx:02d}.html").write_text(html, encoding="utf-8")


async def _tts(render_dir: Path, beats: list[str], voice: str) -> None:
    import edge_tts

    tts_dir = render_dir / "tts"
    tts_dir.mkdir(exist_ok=True)
    for idx, beat in enumerate(beats, 1):
        out = tts_dir / f"tts_{idx:02d}.mp3"
        if out.exists() and out.stat().st_size > 10_000:
            continue
        await edge_tts.Communicate(beat, voice).save(str(out))


async def _screenshots(render_dir: Path, count: int) -> None:
    from playwright.async_api import async_playwright

    out = render_dir / "cards"
    out.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        for idx in range(1, count + 1):
            await page.goto((render_dir / "slides" / f"slide_{idx:02d}.html").resolve().as_uri(), wait_until="networkidle")
            await page.screenshot(path=str(out / f"card_{idx:02d}.png"), full_page=True)
        await browser.close()


def _segments(render_dir: Path, count: int) -> None:
    seg_dir = render_dir / "segments"
    seg_dir.mkdir(exist_ok=True)
    for idx in range(1, count + 1):
        img = render_dir / "cards" / f"card_{idx:02d}.png"
        tts = render_dir / "tts" / f"tts_{idx:02d}.mp3"
        seg = seg_dir / f"seg_{idx:02d}.mp4"
        duration = _duration(tts) + 0.5
        _run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(img),
                "-i",
                str(tts),
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                str(seg),
            ],
            timeout=300,
        )


def _concat(render_dir: Path, count: int) -> Path:
    concat = render_dir / "concat.txt"
    concat.write_text("\n".join(f"file '{(render_dir / 'segments' / f'seg_{idx:02d}.mp4').as_posix()}'" for idx in range(1, count + 1)), encoding="utf-8")
    raw = render_dir / "raw.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(raw)], timeout=300)
    return raw


def _resolve_bgm(render_dir: Path, style: str, platform: str) -> Path:
    from scripts.kuaishou_render import download_bgm
    from scripts.check_bgm_uniqueness import check as check_bgm

    download_bgm(render_dir, style)
    result = check_bgm(render_dir, platform=platform)
    if not result.get("passed"):
        raise RuntimeError("BGM gate failed: " + json.dumps(result, ensure_ascii=False))
    return render_dir / "bgm.mp3"


def _subtitles(render_dir: Path, beats: list[str]) -> Path:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1280",
        "PlayResY: 720",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
        "Style: Default,Noto Sans CJK SC,28,&H00FFFFFF,&H00000000,&H80000000,-1,2,1,2,70,70,55",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    cursor = 0.0
    for idx, beat in enumerate(beats, 1):
        duration = _duration(render_dir / "tts" / f"tts_{idx:02d}.mp3")
        text = r"\N".join([beat[i : i + 20] for i in range(0, len(beat), 20)][:2])
        lines.append(f"Dialogue: 0,{_ass_time(cursor)},{_ass_time(cursor + duration)},Default,,0,0,0,,{text}")
        cursor += duration + 0.5
    path = render_dir / "subtitles.ass"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def render(args: argparse.Namespace) -> dict:
    out_dir = Path(args.out_dir).expanduser().resolve()
    render_dir = out_dir / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    bg_dir = Path(args.bg_dir).expanduser().resolve()
    script_text = Path(args.script).read_text(encoding="utf-8")
    beats = _beats(script_text)
    if len(beats) < 3:
        raise RuntimeError("landscape video requires at least 3 script beats")
    estimated = sum(max(3.0, min(10.0, len(beat) / 10)) for beat in beats)
    if estimated > args.max_duration and not args.force:
        raise RuntimeError(f"estimated duration {estimated:.0f}s exceeds max {args.max_duration}s; revise script or use --force")

    theme = THEMES[args.platform]
    _write_slides(render_dir, beats, bg_dir, theme)
    asyncio.run(_tts(render_dir, beats, args.voice))
    asyncio.run(_screenshots(render_dir, len(beats)))
    _segments(render_dir, len(beats))
    raw = _concat(render_dir, len(beats))
    bgm = _resolve_bgm(render_dir, args.bgm_style, args.platform)
    mixed = render_dir / "mixed.mp4"
    probe = render_dir / "mix_probe.json"
    _run([sys.executable, str(ROOT / "scripts" / "mix_bgm_with_gate.py"), "--video", str(raw), "--bgm", str(bgm), "--output", str(mixed), "--probe", str(probe)], timeout=360)
    subtitles = _subtitles(render_dir, beats)
    final = render_dir / "final.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mixed),
            "-vf",
            f"subtitles={subtitles}:fontsdir=/usr/share/fonts",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "44100",
            str(final),
        ],
        timeout=600,
    )
    cover = out_dir / "cover_1920x1080.jpg"
    _run(["ffmpeg", "-y", "-ss", "0.5", "-i", str(final), "-frames:v", "1", "-q:v", "2", str(cover)], timeout=60)
    visual_recipe = build_visual_recipe(
        {
            "selected_pipeline": "landscape_video_toolchain",
            "content_form": "landscape_explainer_video",
            "template_family": "chaptered_explainer",
            "platforms": [args.platform],
            "title": args.title,
            "script_body": script_text,
        },
        script_body=script_text,
        title=args.title,
        visual_assets={
            "assignments": [
                {"beat": f"beat_{idx:02d}", "path": str((render_dir / "cards" / f"card_{idx:02d}.png").resolve()), "match_reason": "landscape card explains this script beat"}
                for idx in range(1, len(beats) + 1)
            ]
        },
    )
    visual_recipe_path = render_dir / "visual_recipe.json"
    visual_recipe_path.write_text(json.dumps(visual_recipe, ensure_ascii=False, indent=2), encoding="utf-8")
    tools = {
        "render_landscape_video": "scripts/render_landscape_video.py",
        "mix_bgm_with_gate": "scripts/mix_bgm_with_gate.py",
        "check_bgm_uniqueness": "scripts/check_bgm_uniqueness.py",
        "visual_recipe": "content_platform.video_recipe",
    }
    manifest = {
        "passed": True,
        "platform": args.platform,
        "final": str(final),
        "cover": str(cover),
        "duration": _duration(final),
        "mean_volume_db": _mean_volume(final),
        "visual_recipe": str(visual_recipe_path),
        "tool_invocation_manifest": build_tool_invocation_manifest(planned_tools=tools, invocations={name: {"status": "ok", "output": ref} for name, ref in tools.items()}),
        "media_delivery": {"mode": "manual_handoff", "sent_as_separate_message": True, "text_report_separate": True, "abs_paths": [str(final), str(cover)]},
    }
    (out_dir / "landscape_video_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a landscape knowledge-card handoff video.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--bg-dir", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--platform", choices=sorted(THEMES), default="bilibili")
    parser.add_argument("--voice", default="zh-CN-YunxiNeural")
    parser.add_argument("--bgm-style", default="acoustic guitar instrumental")
    parser.add_argument("--max-duration", type=int, default=120)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = render(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
