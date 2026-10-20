#!/usr/bin/env python3
"""Direct vertical video renderer for YouTube Shorts.
Renders HTML knowledge cards via Playwright, composites with narration + subtitles.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VIDEO_DIR = ROOT / "data" / "local_ops_youtube" / "20260828" / "render"

CARD_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: 1080px; height: 1920px; display: flex; align-items: center; justify-content: center;
       background: {bg_gradient}; font-family: 'Noto Sans', sans-serif; color: white; overflow: hidden; }}
.card {{ padding: 80px 60px; text-align: center; }}
.title {{ font-size: {title_size}px; font-weight: 900; line-height: 1.2;
          margin-bottom: 40px; color: {accent_color};
          text-shadow: 2px 2px 20px rgba(0,0,0,0.5); }}
.body {{ font-size: {body_size}px; line-height: 1.5; color: rgba(255,255,255,0.9);
         max-width: 900px; margin: 0 auto; }}
.tag {{ display: inline-block; background: {accent_color}; color: #000;
        padding: 12px 24px; border-radius: 8px; font-size: 28px;
        font-weight: 700; margin-top: 40px; }}
</style></head><body>
<div class="card">
  <div class="title">{title}</div>
  <div class="body">{body}</div>
  {tag_html}
</div></body></html>"""

THEMES = {
    "cover": {"bg_gradient": "linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #16213e 100%)",
              "accent_color": "#00ff88", "title_size": 72, "body_size": 40},
    "big_number": {"bg_gradient": "linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%)",
                   "accent_color": "#ff6b6b", "title_size": 120, "body_size": 38},
    "tool": {"bg_gradient": "linear-gradient(135deg, #141e30 0%, #243b55 100%)",
             "accent_color": "#00b4d8", "title_size": 80, "body_size": 40},
    "savings": {"bg_gradient": "linear-gradient(135deg, #0d1117 0%, #161b22 50%, #21262d 100%)",
                "accent_color": "#3fb950", "title_size": 100, "body_size": 40},
    "shift": {"bg_gradient": "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
              "accent_color": "#e94560", "title_size": 72, "body_size": 40},
    "cta": {"bg_gradient": "linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #0d7377 100%)",
            "accent_color": "#14ffec", "title_size": 80, "body_size": 40},
}

CARDS = [
    {"layout": "cover", "title": "3 AI Writing Tools\nThat Replace Your\nContent Team", "body": "Stop paying writers.\nThree AI tools do it better and cheaper.", "tag": "AI效率实测"},
    {"layout": "big_number", "title": "$4,000/mo", "body": "Hiring writers costs four grand a month\nand six weeks to onboard.", "tag": ""},
    {"layout": "tool", "title": "Claude", "body": "Writes 2000-word blog posts in 3 minutes.\nThe quality is scary good.", "tag": "Long-form"},
    {"layout": "tool", "title": "ChatGPT", "body": "Cranks out 50 social captions\nbefore your coffee gets cold.", "tag": "Speed"},
    {"layout": "tool", "title": "Grammarly", "body": "Fixes the grammar both miss.\nFinal polish, zero effort.", "tag": "Quality"},
    {"layout": "savings", "title": "95%\nSAVINGS", "body": "Two hundred bucks a month\nbeats four thousand.", "tag": ""},
    {"layout": "shift", "title": "You = Editor\nNot Writer", "body": "Better use of your time, honestly.", "tag": ""},
    {"layout": "cta", "title": "Save This", "body": "Which tool do you want to try first?\nComment below.", "tag": "Follow for more"},
]


async def render_cards():
    """Render all cards to PNG screenshots."""
    frames_dir = VIDEO_DIR / "frames"
    frames_dir.mkdir(exist_ok=True)
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed", file=sys.stderr)
        return False
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1080, "height": 1920})
        
        for i, card in enumerate(CARDS):
            theme = THEMES.get(card["layout"], THEMES["cover"])
            tag_html = f'<div class="tag">{card["tag"]}</div>' if card["tag"] else ""
            
            html = CARD_HTML_TEMPLATE.format(
                bg_gradient=theme["bg_gradient"],
                title_size=theme["title_size"],
                body_size=theme["body_size"],
                accent_color=theme["accent_color"],
                title=card["title"].replace("\n", "<br>"),
                body=card["body"].replace("\n", "<br>"),
                tag_html=tag_html,
            )
            
            await page.set_content(html)
            await page.wait_for_timeout(100)
            out_path = frames_dir / f"card_{i:02d}.png"
            await page.screenshot(path=str(out_path))
            print(f"  Card {i}: {out_path.name}")
        
        await browser.close()
    return True


def build_ass_subtitles():
    """Build ASS subtitle file for YouTube Shorts (MarginV=350)."""
    srt_path = VIDEO_DIR / "narration.srt"
    ass_path = VIDEO_DIR / "sub" / "subtitles.ass"
    ass_path.parent.mkdir(exist_ok=True)
    
    # Parse SRT and group into sentence-level segments
    import re
    srt_text = srt_path.read_text()
    
    # Group word-level segments into sentence-level
    sentences = []
    current_start = None
    current_end = None
    current_words = []
    
    for m in re.finditer(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)(?:\n\n|\Z)', srt_text, re.DOTALL):
        ts_start = m.group(2)
        ts_end = m.group(3)
        text = m.group(4).strip()
        
        if current_start is None:
            current_start = ts_start
        current_end = ts_end
        current_words.append(text)
        
        # Split on sentence boundaries
        if text.endswith(('.', '!', '?')):
            full = ' '.join(current_words)
            # Fix common TTS artifacts
            full = full.replace('人工智能', 'AI')
            sentences.append((current_start, current_end, full))
            current_start = None
            current_words = []
    
    # ASS header
    ass_content = """[Script Info]
Title: YouTube Shorts Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans,44,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,0,2,30,30,350,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    def srt_to_ass_time(srt_ts):
        # "00:00:01,234" -> "0:00:01.23"
        h, m, rest = srt_ts.split(':')
        s, ms = rest.split(',')
        return f"{int(h)}:{m}:{s}.{ms[:2]}"
    
    for start, end, text in sentences:
        ass_start = srt_to_ass_time(start)
        ass_end = srt_to_ass_time(end)
        # Escape ASS special chars
        text = text.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
        ass_content += f"Dialogue: 0,{ass_start},{ass_end},Default,,0,0,0,,{text}\n"
    
    ass_path.write_text(ass_content)
    print(f"  ASS subtitles: {ass_path}")
    return ass_path


def render_video():
    """Compose final video with FFmpeg."""
    frames_dir = VIDEO_DIR / "frames"
    narration = VIDEO_DIR / "narration.mp3"
    ass_file = VIDEO_DIR / "sub" / "subtitles.ass"
    output = VIDEO_DIR / "final.mp4"
    
    # Get audio duration
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(narration)],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())
    print(f"  Audio duration: {duration:.1f}s")
    
    # Calculate per-card duration (8 cards, ~6.4s each)
    n_cards = len(CARDS)
    card_duration = duration / n_cards
    
    # Build FFmpeg filter: show each card for its duration
    filter_parts = []
    inputs = []
    
    for i in range(n_cards):
        inputs.extend(["-loop", "1", "-t", f"{card_duration:.3f}",
                       "-i", str(frames_dir / f"card_{i:02d}.png")])
    
    # Build concat filter
    filter_str = ""
    for i in range(n_cards):
        filter_str += f"[{i}:v]scale=1080:1920,setsar=1,fps=30[v{i}]; "
    
    concat_inputs = "".join(f"[v{i}]" for i in range(n_cards))
    filter_str += f"{concat_inputs}concat=n={n_cards}:v=1:a=0[vout]"
    
    # All inputs: N image inputs + 1 audio input
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-i", str(narration),
        "-filter_complex", filter_str,
        "-map", "[vout]",
        "-map", f"{n_cards}:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        str(output)
    ]
    
    print(f"  Running FFmpeg compose...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  FFmpeg error: {result.stderr[-500:]}", file=sys.stderr)
        return False
    
    # Burn subtitles
    if ass_file.exists():
        sub_output = VIDEO_DIR / "final_sub.mp4"
        cmd_sub = [
            "ffmpeg", "-y",
            "-i", str(output),
            "-vf", f"ass={ass_file}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            str(sub_output)
        ]
        print(f"  Burning subtitles...")
        result = subprocess.run(cmd_sub, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            sub_output.rename(output)
        else:
            print(f"  Subtitle burn failed, keeping video without subs: {result.stderr[-300:]}")
    
    # Verify
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration,size",
         "-of", "csv=p=0", str(output)],
        capture_output=True, text=True
    )
    print(f"  Output: {output}")
    print(f"  Info: {result.stdout.strip()}")
    return True


def main():
    from scripts.visual_contract_gate import enforce_entry
    contract_gate = enforce_entry(VIDEO_DIR, "youtube", require_native=True)
    if not contract_gate.get("passed"):
        raise RuntimeError("visual contract failed: " + ", ".join(contract_gate.get("failures", [])))
    print("=== YouTube Shorts Vertical Renderer ===")
    print(f"Working dir: {VIDEO_DIR}")
    
    print("\n[1/4] Rendering card frames...")
    asyncio.run(render_cards())
    
    print("\n[2/4] Building ASS subtitles...")
    build_ass_subtitles()
    
    print("\n[3/4] Composing video...")
    render_video()
    from content_platform.standalone_render_state import write_rendered_unverified
    write_rendered_unverified(VIDEO_DIR, platform="youtube_shorts", renderer="yt_shorts_render.py")
    
    print("\n[4/4] Done!")


if __name__ == "__main__":
    main()
