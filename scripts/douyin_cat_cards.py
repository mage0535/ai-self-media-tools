#!/usr/bin/env python3
import os
if os.environ.get("HERMES_ALLOW_LEGACY_RENDER_DEMO") != "1":
    raise SystemExit("legacy_douyin_original_cards_disabled: douyin must use repost/handoff workflow, not original card generation")
"""抖音猫咪治愈视频生成"""
import subprocess, json, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("/root/.ai-self-media-tools/data/drafts/douyin_video")
OUT.mkdir(parents=True, exist_ok=True)
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

def font(sz):
    try: return ImageFont.truetype(FONT, sz, index=0)
    except: return ImageFont.load_default()

# 猫咪内容 6卡
cards_data = [
    {"text": "猫咪蹭你的时候\n不只是在撒娇", "sub": "它在用气味标记\n你是它的", "bg": (50, 30, 25), "accent": (255, 200, 150), "layout": "warm"},
    {"text": "猫咪咕噜咕噜\n不只是舒服", "sub": "4-6Hz 的频率\n能帮助骨骼修复", "bg": (40, 45, 35), "accent": (180, 220, 160), "layout": "fact"},
    {"text": "猫咪每天睡\n12-16 小时", "sub": "不是懒\n这是猫科动物的生存本能", "bg": (30, 35, 50), "accent": (150, 190, 255), "layout": "stat"},
    {"text": "猫咪对你\n慢慢眨眼", "sub": "这是猫的吻\n它在说\"我信任你\"", "bg": (45, 30, 40), "accent": (255, 180, 200), "layout": "love"},
    {"text": "养猫的人\n血压更低", "sub": "研究证实\n猫能降低心脏病风险", "bg": (35, 45, 40), "accent": (160, 220, 180), "layout": "health"},
    {"text": "关注我\n每天一个猫咪小知识", "sub": "治愈你的每一天", "bg": (50, 35, 30), "accent": (255, 200, 100), "layout": "cta"},
]

for i, d in enumerate(cards_data):
    img = Image.new("RGB", (720, 1280), d["bg"])
    draw = ImageDraw.Draw(img)
    # 渐变
    for y in range(1280):
        a = 0.3
        r2 = int(d["bg"][0]*(1-a) + d["accent"][0]*a*y/1280)
        g2 = int(d["bg"][1]*(1-a) + d["accent"][1]*a*y/1280)
        b2 = int(d["bg"][2]*(1-a) + d["accent"][2]*a*y/1280)
        draw.line([(0, y), (719, y)], fill=(min(255,r2), min(255,g2), min(255,b2)), width=1)
    # 标题大字
    f_big = font(48)
    lines = d["text"].split("\n")
    y = 300
    for ln in lines:
        draw.text((40, y), ln, fill=(245, 245, 245), font=f_big)
        y += 65
    # 副标题
    f_sub = font(28)
    draw.text((40, y+30), d["sub"], fill=d["accent"], font=f_sub)
    # 装饰元素
    draw.rounded_rectangle([(40, 80), (120, 115)], radius=20, fill=d["accent"])
    draw.text((55, 88), f"0{i+1}", fill=d["bg"], font=font(20))
    path = OUT / f"card_{i+1:02d}.png"
    img.save(path)
    print(f"卡{i+1} [{d['layout']}]")

print("\n卡片生成完成 ✅")
