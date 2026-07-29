#!/usr/bin/env python3
"""快手卡片生成 — 每卡不同layout + 强钩子"""

import json, os, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools"))) / "data" / "drafts" / "kuaishou_video"
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

def load_font(size):
    try:
        return ImageFont.truetype(FONT, size, index=0)
    except:
        return ImageFont.load_default()

# 6卡各有不同内容 + layout配置
# 用6种不同布局、配色、文字排列
cards_data = [
    # 卡1：钩子 — 大字冲击 + 对比色
    {"text": "你还在手动复制粘贴？\n别人已经用AI自动干活了", "layout": "big_text_contrast", "bg": (59, 13, 13), "accent": (245, 158, 11), "step": "🔥 差距"},
    # 卡2：问题+场景 — 左右分栏
    {"text": "每天重复的3件事：\n填表、回邮件、整理数据\n——这些全是自动化的菜", "layout": "split_left_right", "bg": (15, 23, 42), "accent": (59, 130, 246), "step": "STEP 1"},
    # 卡3：方案 — 时间线
    {"text": "OpenClaw 一条链搞定：\n接收 → 处理 → 写入", "layout": "timeline", "bg": (20, 40, 30), "accent": (52, 211, 153), "step": "STEP 2"},
    # 卡4：效果 — 卡片堆叠
    {"text": "加个通知节点\n手机上看结果\n不用守在电脑前", "layout": "card_stack", "bg": (30, 20, 50), "accent": (139, 92, 246), "step": "STEP 3"},
    # 卡5：成果 — 数据大字报
    {"text": "每天省1小时\n\n以前手动整理\n现在机器搞定", "layout": "big_number", "bg": (15, 35, 50), "accent": (251, 191, 36), "step": "📊 成果"},
    # 卡6：CTA — 对角切割
    {"text": "关注我\n\n下期拆解：\n能自动接单赚钱的Agent系统", "layout": "diagonal", "bg": (40, 15, 30), "accent": (236, 72, 153), "step": "👉 关注"},
]

def make_card(data, idx, w=720, h=1280):
    img = Image.new("RGB", (w, h), data["bg"])
    draw = ImageDraw.Draw(img)

    # 渐变叠加（让背景有层次）
    for i in range(h):
        r = max(0, data["bg"][0] - int(20 * i / h))
        g = max(0, data["bg"][1] - int(15 * i / h))
        b = max(0, data["bg"][2] - int(25 * i / h))
        draw.line([(0, i), (w-1, i)], fill=(r, g, b), width=1)

    # STEP/标签
    f_step = load_font(28)
    draw.text((40, 40), data["step"], fill=data["accent"], font=f_step)

    # 用于文字排列的装饰线
    draw.rectangle([(40, 85), (w-40, 87)], fill=data["accent"])

    # 正文（不同layout排版）
    lines = data["text"].split("\n")

    if data["layout"] == "big_text_contrast":
        # 大字对比 — 首行超大
        f_big = load_font(48)
        f_small = load_font(36)
        draw.text((40, 200), lines[0], fill=(245, 245, 245), font=f_big)
        if len(lines) > 1:
            draw.text((40, 320), lines[1], fill=data["accent"], font=f_small)
        # 高亮框
        draw.rounded_rectangle([(40, 450), (w-40, 520)], radius=12, fill=data["accent"], outline=None)
        draw.text((60, 460), "看完这条视频你就知道差距在哪", fill=(0,0,0), font=load_font(24))

    elif data["layout"] == "split_left_right":
        # 左右分栏 — 左标题右列表
        f_t = load_font(40)
        f_l = load_font(30)
        draw.text((40, 250), "你的日常:", fill=(160, 160, 160), font=load_font(26))
        for j, ln in enumerate(lines):
            if "：" in ln:
                parts = ln.split("：")
                draw.text((40, 300 + j*80), f"◉ {parts[0]}", fill=data["accent"], font=f_t)
                if len(parts) > 1:
                    draw.text((40, 340 + j*80), parts[1], fill=(200,200,200), font=f_l)
            else:
                draw.text((40, 300 + j*80), f"◉ {ln}", fill=(200,200,200), font=f_l)

    elif data["layout"] == "timeline":
        # 时间线 — 水平箭头
        f_b = load_font(32)
        steps = lines[0].split("→") if "→" in lines[0] else [l.strip() for l in lines if l.strip()]
        start_x = 40
        for j, step in enumerate(steps):
            x = start_x + j * 220
            draw.rounded_rectangle([(x, 350), (x+180, 420)], radius=16, fill=data["accent"], outline=None)
            draw.text((x+15, 365), step.strip(), fill=(0,0,0), font=f_b)
            if j < len(steps) - 1:
                draw.text((x+185, 370), "→", fill=(200,200,200), font=load_font(36))
        # 说明文字
        draw.text((40, 500), "一条链串联，全程自动化", fill=(180,180,180), font=load_font(28))

    elif data["layout"] == "card_stack":
        # 卡片堆叠
        f_c = load_font(30)
        items = [l.strip() for l in lines if l.strip()]
        for j, item in enumerate(items):
            colors = [(60, 60, 80), (50, 50, 70), (40, 40, 60)]
            offset = 40 + j * 15
            draw.rounded_rectangle([(40+offset, 250+j*150), (w-40+offset, 390+j*150)],
                                  radius=12, fill=colors[j % 3], outline=data["accent"])
            draw.text((70+offset, 290+j*150), f"  {item}", fill=(240,240,240), font=f_c)
            # 编号
            draw.text((70+offset, 260+j*150), f"0{j+1}", fill=data["accent"], font=load_font(22))

    elif data["layout"] == "big_number":
        # 大字报 — 数字特大
        f_num = load_font(80)
        f_d = load_font(30)
        draw.text((40, 250), "每天", fill=(180,180,180), font=load_font(38))
        draw.text((40, 310), "1", fill=data["accent"], font=f_num)
        draw.text((100, 370), "小时", fill=(180,180,180), font=load_font(38))
        # 对比
        draw.text((40, 520), "以前：手动整理", fill=(160,160,160), font=load_font(28))
        draw.text((40, 560), "现在：机器搞定", fill=data["accent"], font=load_font(32))
        # 进度条
        draw.rounded_rectangle([(40, 650), (w-40, 680)], radius=8, fill=(60,60,80), outline=None)
        draw.rounded_rectangle([(40, 650), (600, 680)], radius=8, fill=data["accent"], outline=None)
        draw.text((310, 650), "省时 80%", fill=(0,0,0), font=load_font(24))

    elif data["layout"] == "diagonal":
        # 对角切割 — 上色块下白底
        draw.polygon([(0, 0), (w, 0), (0, h)], fill=(data["bg"][0]+20, data["bg"][1]+15, data["bg"][2]+20))
        f_big = load_font(52)
        f_sm = load_font(30)
        draw.text((40, 250), lines[0], fill=(255,255,255), font=f_big)
        for j, ln in enumerate(lines[2:]):
            draw.text((60, 400 + j*70), f"• {ln}", fill=(220,220,220), font=f_sm)
        # 底部按钮
        draw.rounded_rectangle([(200, 1000), (w-200, 1080)], radius=24, fill=data["accent"], outline=None)
        draw.text((260, 1020), "点关注，不错过", fill=(0,0,0), font=load_font(28))

    path = OUT_DIR / f"card_{idx+1:02d}.png"
    img.save(path)
    print(f"卡{idx+1} [{data['layout']}]: {path}")
    return str(path), data["layout"]

results = [make_card(d, i) for i, d in enumerate(cards_data)]
print(f"\n✅ 6张卡片完成，使用layouts: {[r[1] for r in results]}")

# 保存manifest
meta = {
    "cards": len(results),
    "layouts": [r[1] for r in results],
    "color_schemes": [d["bg"] for d in cards_data],
    "has_hook": True,
    "hook_card": 1,
    "violations_remaining": ["FFmpeg合成", "字幕层"]
}
Path(OUT_DIR / "cards_manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
