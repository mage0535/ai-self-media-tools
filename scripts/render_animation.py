#!/usr/bin/env python3
import os
if os.environ.get('HERMES_ALLOW_LEGACY_RENDER_DEMO') != '1':
    raise SystemExit('legacy_render_demo_disabled: use Pipeline + validate_*_auto_packet + current manifest')
"""渲染知识卡片HTML为视频"""
import asyncio, subprocess, os
from pathlib import Path
from playwright.async_api import async_playwright

OUT = "/tmp/animated_card_demo"
FRAMES = f"{OUT}/frames"
os.makedirs(FRAMES, exist_ok=True)
HTML = str(Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools"))) / "scripts" / "knowledge_card_animation.html")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 720, "height": 1280})
        await page.goto(f"file://{HTML}", wait_until="networkidle")
        await page.wait_for_timeout(1500)

        for i in range(180):  # 36s * 5fps
            await page.screenshot(path=f"{FRAMES}/frame_{i:04d}.png")
            await page.wait_for_timeout(200)

        await browser.close()
        print(f"截图: {len(os.listdir(FRAMES))}张")

asyncio.run(main())

# 合成视频
subprocess.run(["ffmpeg","-y","-framerate","5","-i",f"{FRAMES}/frame_%04d.png",
    "-c:v","libx264","-preset","ultrafast","-crf","28","-pix_fmt","yuv420p",
    f"{OUT}/html_raw.mp4"], capture_output=True, timeout=120)

# 配乐（用现有TTS）
for i in range(6):
    out = f"{OUT}/tts_{i+1:02d}.wav"
    if not os.path.exists(out):
        subprocess.run(["edge-tts","--voice","zh-CN-XiaoxiaoNeural","--text",f"卡{i+1}的配音内容",
            "--write-media",out], capture_output=True, timeout=60)

# 简单BGM
subprocess.run(["ffmpeg","-y","-i",f"{OUT}/html_raw.mp4",
    "-i",f"{OUT}/tts_01.wav","-c:v","copy","-c:a","aac",
    "-map","0:v:0","-map","1:a:0","-shortest",f"{OUT}/final_html.mp4"],
    capture_output=True, timeout=60)

sz = os.path.getsize(f"{OUT}/final_html.mp4")//1024
print(f"视频: {OUT}/final_html.mp4 ({sz}KB)")
