import asyncio
import json
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1')
CUSTOM_DIR = BASE_DIR / 'custom_render'
HTML_DIR = CUSTOM_DIR / 'html'
CARD_DIR = CUSTOM_DIR / 'card_images'
SHOTS_DIR = CUSTOM_DIR / 'shots'
AUDIO_DIR = BASE_DIR / 'audio'
CARD_DIR.mkdir(parents=True, exist_ok=True)
SHOTS_DIR.mkdir(parents=True, exist_ok=True)

# 8 segments TTS durations
durations = json.loads((AUDIO_DIR / 'durations.json').read_text('utf-8'))
durs = [
    durations['s01'], # 9.408
    durations['s02'], # 9.864
    durations['s03'], # 5.904
    durations['s04'], # 8.136
    durations['s05'], # 8.472
    durations['s06'], # 8.616
    durations['s07'], # 8.160
    durations['s08'], # 9.432
]

async def render_all_shots():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        for idx in range(8):
            sid = f'shot_{idx+1:02d}'
            dur = durs[idx]
            # Split into A (45%) and B (55%)
            dur_a = round(dur * 0.45, 2)
            dur_b = round(dur - dur_a, 2)
            
            for suffix, d in [('A', dur_a), ('B', dur_b)]:
                name = f'{sid}{suffix}'
                html_file = HTML_DIR / f'{name}.html'
                png_path = CARD_DIR / f'{name}.png'
                mp4_path = SHOTS_DIR / f'{name}.mp4'
                
                # Snapshot via Playwright
                pg = await browser.new_page(viewport={'width': 720, 'height': 1280})
                await pg.goto(f'file://{html_file}')
                await pg.screenshot(path=str(png_path), type='png')
                await pg.close()
                
                # Encode to 25fps H.264 Baseline MP4
                cmd = [
                    'ffmpeg', '-y', '-loop', '1',
                    '-i', str(png_path),
                    '-c:v', 'libx264', '-profile:v', 'baseline', '-level', '3.1',
                    '-pix_fmt', 'yuv420p', '-r', '25',
                    '-t', str(d),
                    str(mp4_path)
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                print(f"Rendered {name}.mp4 ({d:.2f}s)")
                
        await browser.close()

asyncio.run(render_all_shots())
print("All 16 dialogue shots rendered with photographic backgrounds successfully!")
