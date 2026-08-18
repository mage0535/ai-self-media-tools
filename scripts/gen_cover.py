#!/usr/bin/env python3
"""gen_cover.py — 自动生成平台优化封面（HTML + Playwright，竖版/横版）。

取代 Hermes 手动生成封面：渲染完视频后自动产出 1080x1920 竖版 / 1920x1080 横版
优化封面（实景背景 + 深色渐变遮罩 + 超大标题 + 数字钩子 + CTA 徽章）。

用法:
  from scripts.gen_cover import generate_cover
  path = generate_cover(title, subtitle, hook, bg_image, output_path, orientation='vertical')

依赖: Playwright + 中文字体（Noto Sans CJK）
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"


def _bg_base64(bg_path: str) -> str:
    p = Path(bg_path)
    if not p.is_file():
        return ""
    return base64.b64encode(p.read_bytes()).decode()


def generate_cover(
    title: str,
    subtitle: str,
    hook: str,
    bg_image: str,
    output_path: str,
    orientation: str = "vertical",
    tag: str = "AI效率实测",
    cta: str = "关注 · 每日一个AI实测",
    badge: str = "先收藏",
    highlight: str = "",
    layout: str = "auto",
) -> str | None:
    """生成优化封面，返回输出路径或 None。

    2026-08-16：layout 按内容赛道适配（不再单一模板）——
    auto: 按 detect_genre 选（数字类=big_number / 教程类=checklist / 情感类=warm / 默认=hero）
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    b64 = _bg_base64(bg_image)
    if not b64:
        return None

    if orientation == "vertical":
        W, H = "1080", "1920"
        padding = "110px 80px"
    else:
        W, H = "1920", "1080"
        padding = "110px 120px"

    # 标题双行处理
    title_part = title
    h1 = highlight or title_part

    # 2026-08-16：布局按内容赛道适配（不再单一 hero 模板）
    if layout == "auto":
        try:
            from scripts.voice_engine import detect_genre
            genre = detect_genre(f"{title} {subtitle} {hook}")
            layout_map = {
                "pets": "warm", "emotion": "warm",
                "finance": "big_number", "science": "checklist",
                "tech": "big_number",
            }
            layout = layout_map.get(genre, "hero")
        except Exception:
            layout = "hero"

    if layout == "big_number":
        # 数字钩子式：大数字突出 + 结果承诺
        title_style = "font-size:96px; line-height:1.15; font-weight:900; color:#fff; text-shadow:0 6px 30px rgba(0,0,0,0.9); margin-bottom:30px;"
        sub_style = "font-size:44px; font-weight:700; color:#ffd54d; text-shadow:0 3px 16px rgba(0,0,0,0.9); margin-bottom:60px;"
        hook_style = "display:inline-block; align-self:flex-start; padding:28px 56px; background:linear-gradient(135deg,#e74c3c,#f39c12); border-radius:26px; color:#fff; font-size:44px; font-weight:900; box-shadow:0 10px 40px rgba(231,76,60,0.35);"
    elif layout == "checklist":
        # 清单式：标题 + 副标题 + 3 点钩子
        title_style = "font-size:80px; line-height:1.22; font-weight:900; color:#fff; text-shadow:0 6px 30px rgba(0,0,0,0.9); margin-bottom:34px;"
        sub_style = "font-size:40px; font-weight:700; color:#4fc3f7; text-shadow:0 3px 16px rgba(0,0,0,0.9); margin-bottom:50px;"
        hook_style = "display:inline-block; align-self:flex-start; padding:22px 44px; background:rgba(79,195,247,0.2); border:2px solid #4fc3f7; border-radius:20px; color:#fff; font-size:36px; font-weight:700;"
    elif layout == "warm":
        # 温暖式：柔和渐变 + 大标题
        title_style = "font-size:90px; line-height:1.22; font-weight:900; color:#fff; text-shadow:0 6px 30px rgba(0,0,0,0.85); margin-bottom:40px;"
        sub_style = "font-size:44px; font-weight:700; color:#ffb74d; text-shadow:0 3px 16px rgba(0,0,0,0.9); margin-bottom:70px;"
        hook_style = "display:inline-block; align-self:flex-start; padding:24px 48px; background:linear-gradient(135deg,#ff8a65,#ffb74d); border-radius:24px; color:#fff; font-size:40px; font-weight:800;"
    else:
        # hero 默认
        title_style = "font-size:88px; line-height:1.24; font-weight:900; color:#fff; text-shadow:0 6px 30px rgba(0,0,0,0.9), 0 3px 8px rgba(0,0,0,1); margin-bottom:38px;"
        sub_style = "font-size:42px; font-weight:700; color:#ffd54d; text-shadow:0 3px 16px rgba(0,0,0,0.9); margin-bottom:80px;"
        hook_style = "display:inline-block; align-self:flex-start; padding:24px 48px; background:linear-gradient(135deg,#e74c3c,#f39c12); border-radius:22px; color:#fff; font-size:38px; font-weight:800;"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover no-repeat; }}
.overlay {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.72) 40%, rgba(0,0,0,0.93) 100%); }}
.content {{ position:absolute; inset:0; z-index:2; display:flex; flex-direction:column; justify-content:center; padding:{padding}; }}
.tag {{ display:inline-block; align-self:flex-start; padding:16px 38px; background:rgba(255,255,255,0.14); border:1px solid rgba(255,255,255,0.35); border-radius:50px; color:#fff; font-size:30px; font-weight:600; margin-bottom:46px; }}
.title {{ {title_style} }}
.hl {{ color:#ffd54d; }}
.sub {{ {sub_style} }}
.hookbox {{ {hook_style} }}
.cta {{ position:absolute; bottom:100px; left:80px; right:80px; display:flex; justify-content:space-between; align-items:center; border-top:2px solid rgba(255,255,255,0.2); padding-top:30px; }}
.cta span {{ font-size:28px; color:rgba(255,255,255,0.85); }}
.badge {{ padding:14px 32px; background:rgba(255,255,255,0.14); border-radius:40px; font-size:28px; color:#fff; }}
</style></head><body>
<div class="bg"></div><div class="overlay"></div>
<div class="content">
  <div class="tag">{tag}</div>
  <div class="title">{h1}</div>
  <div class="sub">{subtitle}</div>
  <div class="hookbox">{hook}</div>
</div>
<div class="cta"><span>{cta}</span><span class="badge">{badge}</span></div>
</body></html>"""

    tmp = Path(tempfile.gettempdir()) / f"cover_{Path(output_path).stem}.html"
    tmp.write_text(html, encoding="utf-8")

    code = f"""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=['--no-sandbox'])
    pg = b.new_page(viewport={{"width": {W}, "height": {H}}}, device_scale_factor=1)
    pg.goto('file://{tmp}')
    pg.wait_for_timeout(500)
    pg.screenshot(path='{out}')
    b.close()
"""
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=90)
        if r.returncode != 0:
            return None
        if out.is_file() and out.stat().st_size > 5000:
            return str(out)
    except Exception:
        return None
    return None


if __name__ == "__main__":
    # CLI: 生成封面
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--hook", default="")
    ap.add_argument("--bg", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--orient", default="vertical")
    args = ap.parse_args()
    p = generate_cover(args.title, args.subtitle, args.hook, args.bg, args.out, args.orient)
    print(f"封面: {p or '失败'}")
