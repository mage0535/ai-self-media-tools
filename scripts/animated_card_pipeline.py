#!/usr/bin/env python3
import os
if os.environ.get('HERMES_ALLOW_LEGACY_RENDER_DEMO') != '1':
    raise SystemExit('legacy_render_demo_disabled: use Pipeline + validate_*_auto_packet + current manifest')
"""知识卡片动画视频管线 v1 — HTML+CSS动效 + Playwright录制 + FFmpeg合成
每张卡背景不变，正文文字以多种动画依次出现
"""
import subprocess, os, sys, json, time
from pathlib import Path
from string import Template

OUT = Path("/tmp/animated_card_demo")
OUT.mkdir(parents=True, exist_ok=True)

# ── 4张卡片的内容数据 ──
cards = [
    {
        "id": "01", "accent": "#3b82f6", "accent_bg": "rgba(59,130,246,0.15)",
        "gradient": "135deg, #0f172a 0%, #1e293b 100%",
        "title": "AI工具正在改变<span class='hl'>工作方式</span>",
        "subtitle": "效率提升看得见",
        "body1": "自动处理重复性任务，释放你的创造力。",
        "body2": "每天省下<span class='hl'>2小时</span>，专注真正重要的事。",
        "tag": "效率工具 · 自动化",
    },
    {
        "id": "02", "accent": "#34d399", "accent_bg": "rgba(52,211,153,0.15)",
        "gradient": "135deg, #0f2b1e 0%, #1a3a2a 100%",
        "title": "自动处理<span class='hl'>重复任务</span>",
        "subtitle": "每天省下2小时",
        "body1": "数据录入、报表生成、邮件回复都能自动化。",
        "body2": "让AI做<span class='hl'>重复的事</span>，你做真正创造价值的事。",
        "tag": "效率工具 · 自动化",
    },
    {
        "id": "03", "accent": "#8b5cf6", "accent_bg": "rgba(139,92,246,0.15)",
        "gradient": "135deg, #1a0a2e 0%, #2d1b4e 100%",
        "title": "<span class='hl'>实时数据</span>分析",
        "subtitle": "决策不再靠感觉",
        "body1": "AI自动采集、清洗、可视化，分钟级出报告。",
        "body2": "用<span class='hl'>数据说话</span>，而不是凭经验拍脑袋。",
        "tag": "效率工具 · 自动化",
    },
    {
        "id": "04", "accent": "#ec4899", "accent_bg": "rgba(236,72,153,0.15)",
        "gradient": "135deg, #2d0a1a 0%, #4a1530 100%",
        "title": "<span class='hl'>关注我</span>",
        "subtitle": "持续分享AI效率工具",
        "body1": "每周实测一款AI工具，帮你找到最适合的方案。",
        "body2": "下一期教你用<span class='hl'>OpenClaw</span>搭建自动化工作流。",
        "tag": "关注不迷路",
    },
]

# TTS脚本
scripts = [
    "AI工具正在改变我们的工作方式。效率提升看得见。自动处理重复任务，释放你的创造力。每天省下2小时。",
    "自动处理重复任务，释放你的创造力。每天省下2小时。让AI做重复的事，你做真正创造价值的事。",
    "实时数据分析，决策不再靠感觉。AI自动采集、清洗、可视化，分钟级出报告。用数据说话。",
    "关注我，持续分享AI效率工具。每周实测一款AI工具，帮你找到最适合的效率方案。",
]

# ── 1. 生成 HTML ⚠️ HTML 模板太复杂，用 Python 字符串拼接 ──
html_parts = ['<!DOCTYPE html><html><head><meta charset="utf-8"><style>']
html_parts.append("""
*{margin:0;padding:0;box-sizing:border-box;}
body{width:720px;height:1280px;overflow:hidden;font-family:'PingFang SC','Microsoft YaHei',sans-serif;}
.card{width:100%;height:100%;position:absolute;top:0;left:0;padding:60px;opacity:0;pointer-events:none;transition:opacity 0.3s;}
.card.active{opacity:1;pointer-events:auto;}
.tag{position:absolute;top:60px;left:60px;border-radius:12px;padding:8px 20px;font-size:22px;font-weight:bold;color:#fff;opacity:0;}
.tag.show{animation:fadeIn 0.3s ease 0.1s forwards;}
.title{position:absolute;top:280px;left:60px;right:60px;font-size:48px;font-weight:bold;color:#f1f5f9;line-height:1.3;opacity:0;transform:translateY(-20px);}
.title.show{animation:titleIn 0.5s ease-out 0.3s forwards;}
.sub{position:absolute;top:420px;left:60px;right:60px;font-size:28px;font-weight:500;opacity:0;display:flex;}
.sub.show{animation:subIn 0.4s ease-out 0.7s forwards;}
.sub .cursor{display:inline-block;width:2px;height:28px;margin-left:2px;background:transparent;animation:blink 0.6s step-end 5;}
.sub.show .cursor{background:currentColor;}
.b1{position:absolute;top:520px;left:60px;right:60px;font-size:26px;color:#cbd5e1;line-height:1.6;opacity:0;transform:translateX(-30px);}
.b1.show{animation:slideIn 0.4s ease-out 1.1s forwards;}
.b2{position:absolute;top:600px;left:60px;right:60px;font-size:26px;color:#94a3b8;line-height:1.6;opacity:0;transform:translateX(30px);}
.b2.show{animation:slideIn 0.4s ease-out 1.5s forwards;}
.ft{position:absolute;bottom:100px;left:60px;padding:10px 24px;border-radius:20px;font-size:20px;opacity:0;}
.ft.show{animation:fadeInUp 0.5s ease 2.0s forwards;}
.hl{display:inline-block;animation:pop 0.4s cubic-bezier(0.68,-0.55,0.27,1.55) 0.1s both;}
@keyframes fadeIn{to{opacity:1;}}
@keyframes fadeInUp{to{opacity:1;transform:translateY(0);}from{opacity:0;transform:translateY(20px);}}
@keyframes titleIn{to{opacity:1;transform:translateY(0);}}
@keyframes subIn{to{opacity:1;}}
@keyframes slideIn{to{opacity:1;transform:translateX(0);}}
@keyframes pop{0%{transform:scale(0);opacity:0;}70%{transform:scale(1.15);}100%{transform:scale(1);opacity:1;}}
@keyframes blink{50%{background:transparent;}}
""")

# Per-card CSS
for idx, c in enumerate(cards):
    html_parts.append(f"""
.card{idx} {{background:linear-gradient({c['gradient']});}}
.card{idx} .tag {{background:{c['accent']};}}
.card{idx} .sub {{color:{c['accent']};}}
.card{idx} .sub .cursor {{background:{c['accent']};}}
.card{idx} .hl {{color:{c['accent']};}}
.card{idx} .ft {{background:{c['accent_bg']};color:{c['accent']};}}
""")

html_parts.append('</style></head><body>')

# Card HTML
for i, c in enumerate(cards):
    active = "active" if i == 0 else ""
    html_parts.append(f"""
<div class="card card{i} {active}">
  <div class="tag show">{c['id']}</div>
  <div class="title show">{c['title']}</div>
  <div class="sub show">{c['subtitle']}<span class="cursor"></span></div>
  <div class="b1 show">{c['body1']}</div>
  <div class="b2 show">{c['body2']}</div>
  <div class="ft show">{c['tag']}</div>
</div>""")

html_parts.append("""
<script>
const cards = document.querySelectorAll('.card');
let idx = 0;
setInterval(() => {
  cards[idx].classList.remove('active');
  idx = (idx + 1) % cards.length;
  cards[idx].classList.add('active');
  // Re-trigger animations by re-adding classes
  cards[idx].querySelectorAll('.tag, .title, .sub, .b1, .b2, .ft').forEach(el => {
    el.classList.remove('show');
    void el.offsetWidth;
    el.classList.add('show');
  });
}, 6000);
</script>
</body></html>""")

html_content = "\n".join(html_parts)
html_path = OUT / "animated.html"
html_path.write_text(html_content, encoding="utf-8")
print("1️⃣ HTML生成 ✅")

# ── 2. TTS配音 ──
for i, text in enumerate(scripts):
    out = str(OUT / f"tts_{i+1:02d}.mp3")
    subprocess.run(["edge-tts","--voice","zh-CN-XiaoxiaoNeural","--text",text,"--write-media",out],
                   check=True, capture_output=True, timeout=60)
dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(OUT/"tts_01.mp3")],
                     capture_output=True, text=True).stdout.strip()
print(f"2️⃣ TTS完成 (首段{dur}s) ✅")

# ── 3. 字幕SRT ──
scripts_short = [s[:30] for s in scripts]  # 简短字幕
srt_lines = []
offset = 0.0
tts_files = [str(OUT / f"tts_{i+1:02d}.mp3") for i in range(4)]
for i, f in enumerate(tts_files):
    d = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f],
                            capture_output=True, text=True).stdout.strip())
    start_s = int(offset)
    start_ms = int((offset - start_s) * 1000)
    end = offset + d
    end_s = int(end)
    end_ms = int((end - end_s) * 1000)
    srt_lines.append(f"{i+1}\n{start_s:02d}:{int((offset-start_s)*60):02d}:{start_s:02d},{start_ms:03d} --> {end_s:02d}:{int((end-end_s)*60):02d}:{end_s:02d},{end_ms:03d}\n{scripts_short[i]}\n")
    offset = end
srt_path = OUT / "subs.srt"
srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
print("3️⃣ 字幕SRT ✅")

# ── 4. Playwright 截图录制 ──
# Use Playwright to capture screenshots every 0.2s for ~24s
frames_dir = OUT / "frames"
frames_dir.mkdir(exist_ok=True)

print("4️⃣ 录制动画中...")
sys.stdout.flush()

import asyncio
from playwright.async_api import async_playwright

async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 720, "height": 1280})
        await page.goto(f"file://{html_path}", wait_until="networkidle")
        await page.wait_for_timeout(1500)
        
        for i in range(120):  # 24s * 5fps
            await page.screenshot(path=str(frames_dir / f"frame_{i:04d}.png"), full_page=False)
            await page.wait_for_timeout(200)
        
        await browser.close()
        print(f"   截图完成: {len(list(frames_dir.glob('*.png')))}张")

asyncio.run(capture())

# ── 5. FFmpeg合成视频 ──
raw_video = OUT / "raw_video.mp4"
subprocess.run([
    "ffmpeg","-y","-framerate","5","-i",str(frames_dir / "frame_%04d.png"),
    "-c:v","libx264","-preset","ultrafast","-crf","28","-pix_fmt","yuv420p",str(raw_video)
], capture_output=True, timeout=120)

# Mix audio (first TTS extended with BGM)
audio1 = str(OUT / "tts_01.mp3")
final = OUT / "final.mp4"
subprocess.run([
    "ffmpeg","-y","-i",str(raw_video),"-i",audio1,
    "-c:v","copy","-c:a","aac","-map","0:v:0","-map","1:a:0","-shortest",str(final)
], capture_output=True, timeout=60)

# Burn subtitles
final_sub = OUT / "final_with_subs.mp4"
subprocess.run([
    "ffmpeg","-y","-i",str(final),
    "-vf",f"subtitles={srt_path}:force_style='FontName=Noto+Sans+SC,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00666666,BorderStyle=1,Outline=1,Shadow=0,MarginV=60,Alignment=2'",
    "-c:a","copy",str(final_sub)
], capture_output=True, timeout=120)

sz = os.path.getsize(final_sub)//1024 if final_sub.exists() else 0
print(f"\n5️⃣ 最终视频: {final_sub} ({sz}KB) ✅")
print(f"   字幕: {srt_path}")
print(f"   HTML源: {html_path}")
