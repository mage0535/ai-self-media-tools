#!/usr/bin/env python3
"""
fast_dialogue_pipeline.py - 极速短视频职场双人对谈流水线 (V2 Architecture)
实现：
1. 异步并发 TTS (Yunxi + Yunyang + 200ms 气口)
2. 单实例 Playwright WebM 录屏 (CSS 组件分层动效)
3. 单管道 FFmpeg 流式压合与 Loudnorm 混音
4. 真实通透背景封面自动生成
5. 编译期快速失败拦截与全链路耗时审计
目标：<= 3分钟全自动端到端高质量交付。
"""

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

BASE_DIR = Path('/root/.ai-self-media-tools')
ASSET_POOL = BASE_DIR / 'data/assets/dialogue_pool'
BG_POOL = ASSET_POOL / 'backgrounds'
BGM_POOL = ASSET_POOL / 'bgm'
AUDIO_POOL = ASSET_POOL / 'audio'
FONT_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'

VOICE_Q = 'zh-CN-YunxiNeural'
RATE_Q = '+8%'
VOICE_A = 'zh-CN-YunyangNeural'
RATE_A = '+5%'

CSS_TEMPLATE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
    width: 1080px; height: 1920px;
    overflow: hidden;
    background: #060b19;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    color: #ffffff;
}

/* 优雅平滑慢镜头：Ken Burns 16s，拒绝机械抖动 */
.bg {
    position: absolute; inset: -40px;
    background-position: center; background-size: cover;
    filter: saturate(1.15) contrast(1.08) brightness(0.92);
    animation: kenburns 16s ease-in-out infinite alternate;
}
@keyframes kenburns {
    0% { transform: scale(1.02) translate(0, 0); }
    100% { transform: scale(1.07) translate(-10px, -8px); }
}

.shade {
    position: absolute; inset: 0;
    background: linear-gradient(180deg, rgba(6,11,25,0.60) 0%, rgba(4,8,18,0.45) 45%, rgba(6,11,25,0.72) 100%);
}
.glow {
    position: absolute; inset: 0;
    background: radial-gradient(circle at 80% 20%, rgba(250,204,21,0.18), transparent 45%),
                radial-gradient(circle at 20% 70%, rgba(56,189,248,0.22), transparent 45%);
}
.grid {
    position: absolute; inset: 0; opacity: 0.10;
    background-image: linear-gradient(rgba(147,197,253,0.3) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(147,197,253,0.3) 1px, transparent 1px);
    background-size: 56px 56px;
}

.wrap {
    position: relative; z-index: 2;
    width: 100%; height: 100%;
    padding: 80px 64px 320px;
    display: flex; flex-direction: column;
}

.eyebrow-row {
    display: flex; justify-content: space-between; align-items: center;
    animation: fadeIn .4s ease-out both;
}
.eyebrow {
    font-size: 26px; letter-spacing: 3px; color: #facc15; font-weight: 950;
}
.series-tag {
    font-size: 22px; color: #bae6fd;
    background: rgba(2,132,199,0.25); border: 1.5px solid rgba(56,189,248,0.4);
    padding: 6px 18px; border-radius: 999px; font-weight: 800;
}
.main-title {
    font-size: 52px; line-height: 1.22; font-weight: 1000;
    letter-spacing: -1px; text-shadow: 0 4px 18px rgba(0,0,0,0.9);
    margin-top: 18px;
    animation: fadeIn .5s .1s ease-out both;
}

.dialogue-box {
    margin-top: 36px;
    display: flex; flex-direction: column; gap: 24px;
}

/* 工程师提问气泡：平滑左滑入 */
.bubble-q {
    background: rgba(239, 68, 68, 0.18);
    border: 2px solid #ef4444;
    border-radius: 24px; padding: 24px 30px;
    backdrop-filter: blur(14px);
    box-shadow: 0 10px 30px rgba(239, 68, 68, 0.25);
    animation: slideInLeft .5s .15s both;
}
.bubble-q .speaker-row {
    display: flex; align-items: center; gap: 12px; margin-bottom: 10px;
}
.avatar-q {
    width: 44px; height: 44px; border-radius: 50%;
    background: #ef4444; color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-size: 24px; font-weight: 900;
}
.speaker-title-q {
    font-size: 24px; font-weight: 900; color: #fca5a5;
}
.bubble-q .text {
    font-size: 32px; font-weight: 900; color: #ffffff; line-height: 1.38;
}

/* 架构师回答气泡：平滑右滑入 */
.bubble-a {
    background: rgba(16, 185, 129, 0.18);
    border: 2px solid #10b981;
    border-radius: 24px; padding: 24px 30px;
    backdrop-filter: blur(14px);
    box-shadow: 0 10px 30px rgba(16, 185, 129, 0.25);
    animation: slideInRight .5s .35s both;
}
.bubble-a .speaker-row {
    display: flex; align-items: center; gap: 12px; margin-bottom: 10px;
}
.avatar-a {
    width: 44px; height: 44px; border-radius: 50%;
    background: #10b981; color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-size: 24px; font-weight: 900;
}
.speaker-title-a {
    font-size: 24px; font-weight: 900; color: #6ee7b7;
}
.bubble-a .text {
    font-size: 32px; font-weight: 900; color: #ffffff; line-height: 1.38;
}

/* 核心知识面板：微弹性升起 */
.panel {
    background: rgba(15, 23, 42, 0.85);
    border: 2px solid rgba(56, 189, 248, 0.35);
    border-radius: 24px;
    backdrop-filter: blur(16px);
    box-shadow: 0 20px 50px rgba(0,0,0,0.6);
    animation: popUp .6s .50s both;
}

.footer {
    margin-top: auto;
    color: #94a3b8; font-size: 22px; font-weight: 700;
    display: flex; justify-content: space-between; align-items: center;
    text-shadow: 0 2px 8px rgba(0,0,0,0.9);
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes slideInLeft {
    from { opacity: 0; transform: translateX(-35px); }
    to { opacity: 1; transform: translateX(0); }
}
@keyframes slideInRight {
    from { opacity: 0; transform: translateX(35px); }
    to { opacity: 1; transform: translateX(0); }
}
@keyframes popUp {
    0% { opacity: 0; transform: translateY(25px) scale(0.96); }
    70% { transform: translateY(-3px) scale(1.01); }
    100% { opacity: 1; transform: translateY(0) scale(1); }
}
"""

def esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def b64_img(p: Path) -> str:
    if not p.is_file():
        return ''
    mime = 'image/png' if p.suffix.lower() == '.png' else 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(p.read_bytes()).decode('utf-8')

def generate_panel_html(b: dict) -> str:
    mode = b.get('mode', 'split')
    cdata = b.get('card_data', {})
    
    if mode == 'split':
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 32px; border-left: 8px solid #facc15;">
            <div style="display: inline-block; background: rgba(250,204,21,0.25); border: 1.5px solid #facc15; color: #fef08a; padding: 6px 16px; border-radius: 999px; font-size: 20px; font-weight: 900;">{esc(cdata.get('tag', '认知纠偏'))}</div>
            <div style="font-size: 34px; font-weight: 950; color: #fef08a; margin-top: 14px;">{esc(cdata.get('headline', ''))}</div>
            <div style="font-size: 24px; color: #e2e8f0; margin-top: 10px; line-height: 1.5;">{esc(cdata.get('desc', ''))}</div>
        </div>
        """
    elif mode == 'mindset':
        return f"""
        <div style="display: flex; flex-direction: column; gap: 16px; margin-top: 24px;">
            <div class="panel" style="padding: 22px 28px; border-left: 6px solid #ef4444; background: rgba(30,15,25,0.85);">
                <div style="color: #fca5a5; font-size: 20px; font-weight: 900;">错误做法</div>
                <div style="color: #ffffff; font-size: 26px; font-weight: 800; margin-top: 6px;">{esc(cdata.get('wrong', ''))}</div>
            </div>
            <div class="panel" style="padding: 22px 28px; border-left: 6px solid #10b981; background: rgba(10,30,25,0.85); animation-delay: .65s;">
                <div style="color: #6ee7b7; font-size: 20px; font-weight: 900;">正确做法</div>
                <div style="color: #ffffff; font-size: 26px; font-weight: 800; margin-top: 6px;">{esc(cdata.get('right', ''))}</div>
            </div>
        </div>
        """
    elif mode in ['lock_source', 'cite_source']:
        color = '#38bdf8' if mode == 'lock_source' else '#fb923c'
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 30px 32px; border-top: 5px solid {color};">
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <span style="font-size: 22px; font-weight: 900; color: {color};">军规 {esc(str(cdata.get('step', '01')))}</span>
                <span style="font-size: 20px; color: #94a3b8; font-family: monospace;">FAIL-CLOSED RULE</span>
            </div>
            <div style="font-size: 34px; font-weight: 950; color: #ffffff; margin-top: 10px;">{esc(cdata.get('name', ''))}</div>
            <div style="font-size: 24px; color: #cbd5e1; margin-top: 12px; line-height: 1.5; background: rgba(0,0,0,0.3); padding: 14px 18px; border-radius: 12px;">
                {esc(cdata.get('rule', ''))}
            </div>
        </div>
        """
    elif mode == 'separate':
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 28px 30px; border-top: 5px solid #a855f7;">
            <div style="font-size: 32px; font-weight: 950; color: #c084fc; margin-bottom: 16px;">{esc(cdata.get('name', ''))}</div>
            <div style="display: flex; flex-direction: column; gap: 12px;">
                <div style="background: rgba(168,85,247,0.18); border-left: 5px solid #a855f7; padding: 14px 20px; border-radius: 12px; font-size: 24px; font-weight: 800;">
                    {esc(cdata.get('ai_role', ''))}
                </div>
                <div style="background: rgba(16,185,129,0.18); border-left: 5px solid #10b981; padding: 14px 20px; border-radius: 12px; font-size: 24px; font-weight: 800;">
                    {esc(cdata.get('human_role', ''))}
                </div>
            </div>
        </div>
        """
    elif mode == 'checklist':
        items_html = "".join(f"""
        <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 18px; background: rgba(0,0,0,0.3); border-radius: 12px; border-left: 4px solid #10b981;">
            <span style="font-size: 25px; font-weight: 900; color: #6ee7b7;">{esc(title)}</span>
            <span style="font-size: 22px; color: #cbd5e1;">{esc(desc)}</span>
        </div>
        """ for title, desc in cdata.get('items', []))
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 26px 30px;">
            <div style="font-size: 30px; font-weight: 950; color: #6ee7b7; margin-bottom: 14px;">4步自检SOP · 逐条过关</div>
            <div style="display: flex; flex-direction: column; gap: 10px;">
                {items_html}
            </div>
        </div>
        """
    else:  # action
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 32px; text-align: center; border: 2px solid #facc15; box-shadow: 0 0 35px rgba(250,204,21,0.3);">
            <div style="font-size: 38px; font-weight: 1000; color: #fef08a;">{esc(cdata.get('cta_title', '行动指南'))}</div>
            <div style="font-size: 24px; color: #cbd5e1; margin-top: 8px;">{esc(cdata.get('cta_sub', ''))}</div>
            <div style="margin-top: 20px; background: rgba(250,204,21,0.2); padding: 14px 20px; border-radius: 14px; color: #fde047; font-size: 24px; font-weight: 900;">
                💬 {esc(cdata.get('prompt_tip', ''))}
            </div>
        </div>
        """

def build_scene_html(b: dict, bg_uri: str, platform: str = "douyin_ai") -> str:
    panel_html = generate_panel_html(b)
    if platform == "douyin_ai":
        speaker_q_avatar = "林"
        speaker_q_title = "小林 · 运营新人"
        speaker_a_avatar = "张"
        speaker_a_title = "老张 · 资深架构师"
        footer_left = "AI实战避坑 · 表格自动化清洗"
        footer_right = "点赞收藏 · 评论区领SOP"
    else:
        speaker_q_avatar = "工"
        speaker_q_title = "工程师 · 困惑求助"
        speaker_a_avatar = "张"
        speaker_a_title = "老张 · 架构师拆解"
        footer_left = "AI效率工程 · 防幻觉避坑指南"
        footer_right = "点赞收藏 · 评论交流"
    return f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <style>{CSS_TEMPLATE}</style>
</head>
<body>
    <div class="bg" style="background-image: url('{bg_uri}');"></div>
    <div class="shade"></div>
    <div class="glow"></div>
    <div class="grid"></div>
    
    <div class="wrap">
        <div class="eyebrow-row">
            <div class="eyebrow">{esc(b['eyebrow'])}</div>
            <div class="series-tag">实战对谈</div>
        </div>
        
        <div class="main-title">{esc(b['title'])}</div>
        
        <div class="dialogue-box">
            <div class="bubble-q">
                <div class="speaker-row">
                    <div class="avatar-q">{speaker_q_avatar}</div>
                    <div class="speaker-title-q">{speaker_q_title}</div>
                </div>
                <div class="text">“{esc(b['q_text'])}”</div>
            </div>
            
            <div class="bubble-a">
                <div class="speaker-row">
                    <div class="avatar-a">{speaker_a_avatar}</div>
                    <div class="speaker-title-a">{speaker_a_title}</div>
                </div>
                <div class="text">“{esc(b['a_text'])}”</div>
            </div>
            
            {panel_html}
        </div>
        
        <div class="footer">
            <span>{footer_left}</span>
            <span>{footer_right}</span>
        </div>
    </div>
</body>
</html>
"""

async def generate_single_tts(text: str, voice: str, rate: str, out_path: Path):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out_path))

def get_audio_duration(p: Path) -> float:
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(p)]
    return float(subprocess.check_output(cmd, text=True).strip())

def select_visual_style_for_topic(title: str, beats: list | None = None) -> str:
    """Evaluate topic & viral hook to pick the most effective design language."""
    content = str(title or "")
    if beats:
        for b in beats:
            content += " " + b.get("q_text", "") + " " + b.get("a_text", "") + " " + b.get("title", "")

    if any(k in content for k in ["代码", "终端", "脚本", "API", "报错", "Git", "Bug", "Python", "Docker", "Prompt", "提示词"]):
        return "terminal_code"
    if any(k in content for k in ["表格", "Excel", "数据", "公式", "清洗", "大模型", "对比", "避坑", "算法", "穿帮", "口算"]):
        return "evidence_card"
    if any(k in content for k in ["流程", "架构", "系统", "全景", "SOP", "工作流", "Agent", "闭环", "底层原理"]):
        return "minimal_blueprint"
    if any(k in content for k in ["面试", "离职", "老板", "领导", "吐槽", "升职", "摸鱼", "偷懒", "薪资", "同事"]):
        return "vibrant_sticker"

    return "evidence_card"


def build_cover_html(style: str, title: str, subtitle: str, bg_uri: str, beats: list | None = None) -> str:
    clean_sub = subtitle.replace('<span>', '<span style="color: #38bdf8; font-weight: 950;">').replace('</span>', '</span>')
    title_escaped = esc(title)

    if style == "evidence_card":
        title_with_cyan = title_escaped.replace("用AI做的", "<span>用AI做的</span>").replace("AI", "<span>AI</span>")
        return f"""<!doctype html>
<head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{
            width: 1080px; height: 1920px;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
            background: #090d16;
            color: #ffffff;
        }}
        .bg {{
            position: absolute; inset: 0;
            background: url('{bg_uri}') center center / cover no-repeat;
            filter: saturate(1.1) contrast(1.08) brightness(0.85);
        }}
        .vignette {{
            position: absolute; inset: 0;
            background: linear-gradient(180deg, rgba(9,13,22,0.80) 0%, rgba(9,13,22,0.35) 40%, rgba(9,13,22,0.85) 100%);
        }}
        .wrap {{
            position: relative; z-index: 2;
            width: 100%; height: 100%;
            padding: 96px 64px;
            display: flex; flex-direction: column; justify-content: space-between;
        }}
        .header {{
            display: flex; flex-direction: column; gap: 24px;
        }}
        .tag-row {{
            display: flex; gap: 16px; align-items: center;
        }}
        .category-badge {{
            background: linear-gradient(135deg, #0284c7, #0369a1);
            color: #ffffff;
            padding: 12px 28px; border-radius: 999px;
            font-size: 26px; font-weight: 900; letter-spacing: 2px;
            box-shadow: 0 4px 20px rgba(2, 132, 199, 0.4);
        }}
        .tech-badge {{
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border: 1.5px solid #10b981;
            padding: 10px 24px; border-radius: 999px;
            font-size: 24px; font-weight: 900; letter-spacing: 1px;
        }}
        .title-card {{
            background: rgba(15, 23, 42, 0.88);
            border: 2.5px solid #38bdf8;
            border-radius: 28px;
            padding: 36px 40px;
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.85);
            backdrop-filter: blur(24px);
        }}
        .title-text {{
            color: #ffffff;
            font-size: 56px; font-weight: 1000; line-height: 1.30;
            letter-spacing: -0.5px;
        }}
        .title-text span {{
            color: #38bdf8;
            text-shadow: 0 0 25px rgba(56, 189, 248, 0.4);
        }}
        .middle-evidence {{
            display: flex; flex-direction: column; gap: 16px;
        }}
        .evidence-row {{
            background: rgba(15, 23, 42, 0.85);
            border-radius: 20px;
            padding: 24px 30px;
            display: flex; align-items: center; gap: 20px;
            border-left: 6px solid #ef4444;
            box-shadow: 0 10px 30px rgba(0,0,0,0.6);
            backdrop-filter: blur(16px);
        }}
        .evidence-row.correct {{
            border-left: 6px solid #10b981;
            background: rgba(6, 78, 59, 0.35);
        }}
        .evidence-icon {{
            font-size: 32px; font-weight: 900;
        }}
        .evidence-text {{
            font-size: 28px; font-weight: 850; color: #f1f5f9;
        }}
        .evidence-sub {{
            font-size: 22px; color: #94a3b8; margin-top: 4px;
        }}
        .footer-banner {{
            background: linear-gradient(135deg, #059669, #10b981);
            color: #ffffff; border-radius: 20px;
            padding: 24px 32px; font-size: 30px; font-weight: 950;
            display: flex; justify-content: space-between; align-items: center;
            box-shadow: 0 10px 30px rgba(16, 185, 129, 0.4);
        }}
    </style>
</head>
<body data-template="evidence_card">
    <div class="bg"></div>
    <div class="vignette"></div>
    <div class="wrap">
        <div class="header">
            <div class="tag-row">
                <div class="category-badge">AI实战避坑 · 证据拆解</div>
                <div class="tech-badge">SOP硬核指南</div>
            </div>
            <div class="title-card">
                <div class="title-text">{title_with_cyan}</div>
            </div>
        </div>

        <div class="middle-evidence">
            <div class="evidence-row">
                <div class="evidence-icon">❌</div>
                <div>
                    <div class="evidence-text">直投乱序全表让AI口算汇总</div>
                    <div class="evidence-sub">大模型缺乏计算沙箱，100%编造假数字假行</div>
                </div>
            </div>
            <div class="evidence-row correct">
                <div class="evidence-icon">✅</div>
                <div>
                    <div class="evidence-text">前3行样例定框 + 借脑出码</div>
                    <div class="evidence-sub">AI输出Excel公式与脚本，把计算交给电脑沙箱</div>
                </div>
            </div>
        </div>

        <div class="footer-banner">
            <span>实操3条铁律 · 彻底锁死准确率</span>
            <span>点赞收藏 📥</span>
        </div>
    </div>
</body>
</html>"""

    elif style == "terminal_code":
        return f"""<!doctype html>
<head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{
            width: 1080px; height: 1920px;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, "JetBrains Mono", "Fira Code", "PingFang SC", "Noto Sans CJK SC", monospace;
            background: #090d16;
            color: #ffffff;
        }}
        .bg {{
            position: absolute; inset: 0;
            background: url('{bg_uri}') center center / cover no-repeat;
            filter: saturate(0.9) contrast(1.15) brightness(0.65);
        }}
        .vignette {{
            position: absolute; inset: 0;
            background: linear-gradient(180deg, rgba(9,13,22,0.90) 0%, rgba(9,13,22,0.50) 45%, rgba(9,13,22,0.92) 100%);
        }}
        .wrap {{
            position: relative; z-index: 2;
            width: 100%; height: 100%;
            padding: 96px 64px;
            display: flex; flex-direction: column; justify-content: space-between;
        }}
        .terminal-header {{
            background: #1e293b;
            border-top-left-radius: 24px; border-top-right-radius: 24px;
            padding: 20px 28px;
            display: flex; align-items: center; gap: 14px;
            border: 2px solid #334155; border-bottom: none;
        }}
        .dot {{ width: 20px; height: 20px; border-radius: 50%; }}
        .dot.red {{ background: #ef4444; }}
        .dot.yellow {{ background: #f59e0b; }}
        .dot.green {{ background: #10b981; }}
        .terminal-title {{
            color: #94a3b8; font-size: 22px; font-weight: 700; margin-left: 12px;
        }}
        .terminal-box {{
            background: rgba(15, 23, 42, 0.94);
            border: 2px solid #334155;
            border-bottom-left-radius: 24px; border-bottom-right-radius: 24px;
            padding: 36px 40px;
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.90);
        }}
        .prompt-line {{
            color: #10b981; font-size: 28px; font-weight: 800; margin-bottom: 18px;
        }}
        .main-headline {{
            color: #f8fafc; font-size: 54px; font-weight: 1000; line-height: 1.30;
        }}
        .middle-console {{
            display: flex; flex-direction: column; gap: 18px;
        }}
        .console-row {{
            background: rgba(15, 23, 42, 0.90);
            border-radius: 20px; padding: 26px 32px;
            border: 1.5px solid #334155;
        }}
        .console-status-fail {{
            color: #f87171; font-size: 26px; font-weight: 900; margin-bottom: 8px;
        }}
        .console-status-ok {{
            color: #34d399; font-size: 26px; font-weight: 900; margin-bottom: 8px;
        }}
        .console-desc {{
            color: #e2e8f0; font-size: 26px; font-weight: 700;
        }}
        .footer-banner {{
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff; border-radius: 20px;
            padding: 24px 32px; font-size: 30px; font-weight: 950;
            display: flex; justify-content: space-between; align-items: center;
        }}
    </style>
</head>
<body data-template="terminal_code">
    <div class="bg"></div>
    <div class="vignette"></div>
    <div class="wrap">
        <div>
            <div class="terminal-header">
                <div class="dot red"></div>
                <div class="dot yellow"></div>
                <div class="dot green"></div>
                <span class="terminal-title">bash — AI Engine Inspector</span>
            </div>
            <div class="terminal-box">
                <div class="prompt-line">$ python execute.py --check-integrity</div>
                <div class="main-headline">{title_escaped}</div>
            </div>
        </div>

        <div class="middle-console">
            <div class="console-row" style="border-left: 6px solid #ef4444;">
                <div class="console-status-fail">[-] 500 EXEC_REJECTED: 乱序文本口算</div>
                <div class="console-desc">模型缺乏沙箱算力，100%产生统计幻觉与假行</div>
            </div>
            <div class="console-row" style="border-left: 6px solid #10b981;">
                <div class="console-status-ok">[+] 200 VERIFIED: 样例定框 + 出码执行</div>
                <div class="console-desc">大模型写公式脚本，把计算交由本地Python引擎沙箱</div>
            </div>
        </div>

        <div class="footer-banner">
            <span>[STATUS: 3 RULES VERIFIED]</span>
            <span>点赞收藏 📥</span>
        </div>
    </div>
</body>
</html>"""

    elif style == "minimal_blueprint":
        return f"""<!doctype html>
<head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{
            width: 1080px; height: 1920px;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
            background: #0a1128;
            color: #ffffff;
        }}
        .bg {{
            position: absolute; inset: 0;
            background: url('{bg_uri}') center center / cover no-repeat;
            filter: saturate(0.8) contrast(1.1) brightness(0.7);
        }}
        .vignette {{
            position: absolute; inset: 0;
            background: linear-gradient(180deg, rgba(10,17,40,0.85) 0%, rgba(10,17,40,0.40) 45%, rgba(10,17,40,0.90) 100%);
        }}
        .wrap {{
            position: relative; z-index: 2;
            width: 100%; height: 100%;
            padding: 96px 64px;
            display: flex; flex-direction: column; justify-content: space-between;
        }}
        .blueprint-tag {{
            color: #60a5fa; font-size: 26px; font-weight: 900; letter-spacing: 4px; margin-bottom: 16px;
        }}
        .title-card {{
            background: rgba(15, 23, 42, 0.90);
            border-left: 8px solid #3b82f6;
            border-radius: 20px; padding: 36px 40px;
            box-shadow: 0 25px 60px rgba(0,0,0,0.85);
        }}
        .title-text {{
            color: #ffffff; font-size: 56px; font-weight: 1000; line-height: 1.30;
        }}
        .middle-steps {{
            display: flex; flex-direction: column; gap: 18px;
        }}
        .step-row {{
            background: rgba(15, 23, 42, 0.88);
            border-radius: 20px; padding: 24px 30px;
            display: flex; align-items: center; gap: 24px;
            border: 1.5px solid #1e3a8a;
        }}
        .step-idx {{
            color: #38bdf8; font-size: 38px; font-weight: 1000; font-family: monospace;
        }}
        .step-name {{
            color: #f8fafc; font-size: 28px; font-weight: 900;
        }}
        .step-desc {{
            color: #94a3b8; font-size: 22px; margin-top: 4px;
        }}
        .footer-banner {{
            background: linear-gradient(135deg, #1d4ed8, #2563eb);
            color: #ffffff; border-radius: 20px;
            padding: 24px 32px; font-size: 30px; font-weight: 950;
            display: flex; justify-content: space-between; align-items: center;
        }}
    </style>
</head>
<body data-template="minimal_blueprint">
    <div class="bg"></div>
    <div class="vignette"></div>
    <div class="wrap">
        <div>
            <div class="blueprint-tag">SYSTEM ARCHITECTURE · 01</div>
            <div class="title-card">
                <div class="title-text">{title_escaped}</div>
            </div>
        </div>

        <div class="middle-steps">
            <div class="step-row">
                <div class="step-idx">01</div>
                <div>
                    <div class="step-name">样例定框 (Few-Shot Framing)</div>
                    <div class="step-desc">只投前3行脏数据与目标字段，锁死契约</div>
                </div>
            </div>
            <div class="step-row">
                <div class="step-idx">02</div>
                <div>
                    <div class="step-name">借脑出码 (Code Engine)</div>
                    <div class="step-desc">生成公式与处理脚本，把计算交给沙箱执行</div>
                </div>
            </div>
            <div class="step-row">
                <div class="step-idx">03</div>
                <div>
                    <div class="step-name">极值采样 (Validation Gate)</div>
                    <div class="step-desc">抽查首尾空值与总额对齐，2分钟彻底验真</div>
                </div>
            </div>
        </div>

        <div class="footer-banner">
            <span>SOP闭环标准 · 准确率100%锁死</span>
            <span>点赞收藏 📥</span>
        </div>
    </div>
</body>
</html>"""

    else:  # vibrant_sticker
        return f"""<!doctype html>
<head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{
            width: 1080px; height: 1920px;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
            background: #000;
        }}
        .bg {{
            position: absolute; inset: 0;
            background: url('{bg_uri}') center center / cover no-repeat;
        }}
        .vignette {{
            position: absolute; inset: 0;
            background: linear-gradient(180deg, rgba(0,0,0,0.65) 0%, rgba(0,0,0,0.20) 40%, rgba(0,0,0,0.75) 100%);
        }}
        .wrap {{
            position: relative; z-index: 2;
            width: 100%; height: 100%;
            padding: 90px 60px;
            display: flex; flex-direction: column; justify-content: space-between;
        }}
        .header {{
            display: flex; flex-direction: column; gap: 16px;
        }}
        .tag-row {{
            display: flex; gap: 16px;
        }}
        .pill {{
            background: #e11d48; color: #fff;
            padding: 10px 24px; border-radius: 999px;
            font-size: 26px; font-weight: 900; letter-spacing: 2px;
            box-shadow: 0 4px 20px rgba(225, 29, 72, 0.5);
        }}
        .sticker-title {{
            display: inline-block;
            background: #facc15; color: #000000;
            font-size: 58px; font-weight: 1000; line-height: 1.25;
            padding: 20px 32px; border-radius: 20px;
            box-shadow: 0 10px 35px rgba(0,0,0,0.8);
            letter-spacing: -1px;
        }}
        .sub-bar {{
            background: rgba(15, 23, 42, 0.90);
            border: 2px solid #38bdf8;
            border-radius: 20px; padding: 24px 30px;
            font-size: 30px; font-weight: 850; color: #ffffff;
            box-shadow: 0 15px 40px rgba(0,0,0,0.8);
            backdrop-filter: blur(16px);
        }}
        .sub-bar span {{
            color: #38bdf8; font-weight: 950;
        }}
        .footer-banner {{
            background: rgba(16, 185, 129, 0.92);
            color: #ffffff; border-radius: 20px;
            padding: 24px 32px; font-size: 32px; font-weight: 950;
            display: flex; justify-content: space-between; align-items: center;
            box-shadow: 0 10px 30px rgba(16, 185, 129, 0.4);
        }}
    </style>
</head>
<body data-template="vibrant_sticker">
    <div class="bg"></div>
    <div class="vignette"></div>
    <div class="wrap">
        <div class="header">
            <div class="tag-row">
                <div class="pill">🔥 职场避坑</div>
                <div class="pill" style="background: #2563eb;">老张架构师拆解</div>
            </div>
            <div style="margin-top: 10px;">
                <div class="sticker-title">{title_escaped}</div>
            </div>
        </div>

        <div style="margin-bottom: 20px;">
            <div class="sub-bar">
                {clean_sub}
            </div>
            <div class="footer-banner" style="margin-top: 20px;">
                <span>架构师 3 招彻底锁死准确率</span>
                <span>点赞收藏 📥</span>
            </div>
        </div>
    </div>
</body>
</html>"""


class FastDialoguePipeline:
    def __init__(self, run_dir: Path, bg_dir: Path | None = None, platform: str = "douyin_ai", visual_style: str = "auto"):
        self.visual_style = visual_style
        self.run_dir = run_dir
        self.bg_dir = Path(bg_dir) if bg_dir and Path(bg_dir).is_dir() else (run_dir / 'backgrounds')
        self.platform = platform
        self.audio_dir = run_dir / 'audio'
        self.html_dir = run_dir / 'html'
        self.webm_dir = run_dir / 'webm'
        self.seg_dir = run_dir / 'segments'
        self.render_dir = run_dir / 'render'
        self.covers_dir = run_dir / 'covers'
        
        for d in [self.audio_dir, self.html_dir, self.webm_dir, self.seg_dir, self.render_dir, self.covers_dir]:
            d.mkdir(parents=True, exist_ok=True)
            
        self.silence_200ms = AUDIO_POOL / 'silence_200ms.mp3'
        self.bgm_path = BGM_POOL / 'piano_calm.mp3'
        
        self.timings = {}
        
    def validate_preflight(self, beats: list):
        t0 = time.time()
        print(">>> [Preflight] Validating Inlined Contracts & Assertions...")
        assert len(beats) >= 3, "Beats count must be >= 3"
        assert self.silence_200ms.exists(), f"Missing silence asset: {self.silence_200ms}"
        assert self.bgm_path.exists(), f"Missing BGM asset: {self.bgm_path}"
        assert Path(FONT_PATH).exists(), f"Missing font: {FONT_PATH}"
        
        # Check backgrounds in run's bg_dir
        bg_files = sorted(list(self.bg_dir.glob('*.jpg')) + list(self.bg_dir.glob('*.png')))
        assert len(bg_files) >= len(beats), f"Need at least {len(beats)} backgrounds in {self.bg_dir}, found {len(bg_files)}"
        
        for idx, b in enumerate(beats, 1):
            assert 'q_text' in b and len(b['q_text']) > 4, f"Beat {idx} missing valid q_text"
            assert 'a_text' in b and len(b['a_text']) > 4, f"Beat {idx} missing valid a_text"
            assert 'title' in b, f"Beat {idx} missing title"
            
        self.timings['preflight'] = round(time.time() - t0, 2)
        print(f"✓ Preflight PASSED in {self.timings['preflight']}s")

    async def stage_tts(self, beats: list) -> list:
        t0 = time.time()
        print(f">>> [Stage 1/5] Concurrent Async TTS Generation for {len(beats)} beats...")
        tasks = []
        meta = []
        for idx, b in enumerate(beats, 1):
            bid = b.get('id', f's{idx:02d}')
            q_file = self.audio_dir / f"{bid}_q.mp3"
            a_file = self.audio_dir / f"{bid}_a.mp3"
            tasks.append(generate_single_tts(b['q_text'], VOICE_Q, RATE_Q, q_file))
            tasks.append(generate_single_tts(b['a_text'], VOICE_A, RATE_A, a_file))
            meta.append({'id': bid, 'q_file': q_file, 'a_file': a_file, 'beat': b})
            
        await asyncio.gather(*tasks)
        
        # Stitch with 200ms silence
        stitched_meta = []
        for item in meta:
            bid = item['id']
            q_file = item['q_file']
            a_file = item['a_file']
            dialogue_file = self.audio_dir / f"{bid}_dialogue.mp3"
            
            subprocess.run([
                'ffmpeg', '-y',
                '-i', str(q_file),
                '-i', str(self.silence_200ms),
                '-i', str(a_file),
                '-filter_complex', '[0:a][1:a][2:a]concat=n=3:v=0:a=1[aout]',
                '-map', '[aout]',
                '-c:a', 'libmp3lame', '-b:a', '128k',
                str(dialogue_file)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            q_dur = get_audio_duration(q_file)
            a_dur = get_audio_duration(a_file)
            tot_dur = get_audio_duration(dialogue_file)
            
            stitched_meta.append({
                **item['beat'],
                'id': bid,
                'q_dur': q_dur,
                'silence_dur': 0.20,
                'a_dur': a_dur,
                'total_dur': tot_dur,
                'audio_file': dialogue_file
            })
            
        self.timings['tts'] = round(time.time() - t0, 2)
        total_audio_len = sum(m['total_dur'] for m in stitched_meta)
        print(f"✓ Async TTS completed in {self.timings['tts']}s (Total Audio: {total_audio_len:.2f}s)")
        return stitched_meta

    def stage_html(self, stitched_meta: list) -> list:
        t0 = time.time()
        print(f">>> [Stage 2/5] Compiling HTMLs with Real Scene Backgrounds from {self.bg_dir}...")
        bg_files = sorted(list(self.bg_dir.glob('*.jpg')) + list(self.bg_dir.glob('*.png')))
        html_items = []
        for idx, b in enumerate(stitched_meta):
            bg_file = bg_files[idx % len(bg_files)]
            bg_uri = b64_img(bg_file)
            html_content = build_scene_html(b, bg_uri, platform=self.platform)
            h_path = self.html_dir / f"scene_{idx+1:02d}.html"
            h_path.write_text(html_content, encoding='utf-8')
            html_items.append((h_path, b))
        self.timings['html'] = round(time.time() - t0, 2)
        print(f"✓ Generated {len(html_items)} HTML scenes in {self.timings['html']}s")
        return html_items

    def stage_record_webm(self, html_items: list):
        t0 = time.time()
        print(f">>> [Stage 3/5] Single-Session Playwright WebM Recording ({len(html_items)} scenes)...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            for idx, (h_path, b) in enumerate(html_items, 1):
                dur = b['total_dur']
                ctx = browser.new_context(
                    viewport={'width': 1080, 'height': 1920},
                    record_video_dir=str(self.webm_dir),
                    record_video_size={'width': 1080, 'height': 1920}
                )
                page = ctx.new_page()
                page.goto(h_path.as_uri(), wait_until='networkidle')
                page.wait_for_timeout(int((dur + 0.25) * 1000))
                video = page.video
                page.close()
                ctx.close()
                
                dst_webm = self.webm_dir / f"scene_{idx:02d}.webm"
                if video is not None:
                    shutil.copy2(video.path(), dst_webm)
            browser.close()
        self.timings['record_webm'] = round(time.time() - t0, 2)
        print(f"✓ Playwright Recording completed in {self.timings['record_webm']}s")

    def stage_single_pass_mux(self, stitched_meta: list) -> Path:
        t0 = time.time()
        print(f">>> [Stage 4/5] Single-Pass Subtitle Burning & Stream Direct Mux...")
        seg_mp4s = []
        for idx, b in enumerate(stitched_meta, 1):
            bid = b['id']
            webm_file = self.webm_dir / f"scene_{idx:02d}.webm"
            tts_file = b['audio_file']
            seg_mp4 = self.seg_dir / f"seg_{idx:02d}.mp4"
            total_dur = b['total_dur']
            q_dur = b['q_dur']
            silence_dur = b['silence_dur']
            
            # Subtitle timing: Q during [0, q_dur], A during [q_dur+silence, total_dur]
            q_text = b['q_text'].replace("'", "’").replace(":", "：").replace("\n", "")
            a_text = b['a_text'].replace("'", "’").replace(":", "：").replace("\n", "")
            
            # Smart Clause Splitting (strictly <= 14 chars per chunk)
            def smart_split_dialogue(text: str, max_chars: int = 14) -> list[str]:
                text = text.replace('‘', '').replace('’', '').replace('“', '').replace('”', '').strip()
                raw_clauses = re.split(r'([，！。？：；…\n]+)', text)
                tokens = []
                i = 0
                while i < len(raw_clauses):
                    c = raw_clauses[i].strip()
                    p = raw_clauses[i+1].strip() if i+1 < len(raw_clauses) else ''
                    if c:
                        tokens.append(c + p)
                    elif p:
                        if tokens:
                            tokens[-1] += p
                    i += 2
                    
                chunks = []
                curr = ''
                for t in tokens:
                    if not curr:
                        curr = t
                    elif len(curr) + len(t) <= max_chars:
                        curr += t
                    else:
                        chunks.append(curr)
                        curr = t
                if curr:
                    chunks.append(curr)
                    
                final_subs = []
                for c in chunks:
                    if len(c) <= max_chars:
                        final_subs.append(c)
                    else:
                        for k in range(0, len(c), max_chars):
                            final_subs.append(c[k:k+max_chars])
                return final_subs

            def get_sub_filters(text: str, t_start: float, t_end: float, color: str):
                chunks = smart_split_dialogue(text, max_chars=14)
                tot_chars = sum(max(1, len(c)) for c in chunks)
                dur = t_end - t_start
                filters = []
                curr_t = t_start
                for c in chunks:
                    # Compilation Assertion (FAIL-CLOSED)
                    assert len(c) <= 16, f"FATAL SUBTITLE OVERFLOW: '{c}' has {len(c)} chars > 16!"
                    assert len(c) * 38 <= 650, f"FATAL SUBTITLE PIXEL OVERFLOW: '{c}' width {len(c)*38}px > 650px!"
                    
                    c_dur = dur * (len(c) / tot_chars)
                    c_start = curr_t
                    c_end = curr_t + c_dur
                    curr_t = c_end
                    
                    safe_c = c.replace("'", "’").replace(":", "：")
                    f_str = (
                        f"drawtext=fontfile='{FONT_PATH}':text='{safe_c}':fontsize=38:fontcolor={color}:"
                        f"borderw=3.5:bordercolor=black@0.90:x=(w-text_w)/2:y=1680:"
                        f"enable='between(t,{c_start:.2f},{c_end:.2f})'"
                    )
                    filters.append(f_str)
                return filters

            vf_filters = []
            vf_filters.extend(get_sub_filters(q_text, 0.0, q_dur, "white"))
            vf_filters.extend(get_sub_filters(a_text, q_dur + silence_dur, total_dur, "#6ee7b7"))
            vf_arg = ",".join(vf_filters)
            
            cmd = [
                'ffmpeg', '-y',
                '-i', str(webm_file),
                '-i', str(tts_file),
                '-t', str(total_dur),
                '-vf', vf_arg,
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
                '-profile:v', 'baseline', '-level', '4.0', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '128k',
                '-shortest',
                str(seg_mp4)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            seg_mp4s.append(seg_mp4)
            
        concat_txt = self.seg_dir / 'concat.txt'
        concat_txt.write_text("".join(f"file '{p.name}'\n" for p in seg_mp4s), encoding='utf-8')
        
        video_concat = self.render_dir / 'video_concat.mp4'
        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(concat_txt),
            '-c', 'copy',
            str(video_concat)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        final_mp4 = self.render_dir / 'final_delivery.mp4'
        filter_complex = (
            "[0:a]volume=1.0[v];"
            "[1:a]volume=0.10[bg];"
            "[v][bg]amix=inputs=2:duration=first:normalize=0[mixed];"
            "[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
        )
        subprocess.run([
            'ffmpeg', '-y',
            '-i', str(video_concat),
            '-stream_loop', '-1',
            '-i', str(self.bgm_path),
            '-filter_complex', filter_complex,
            '-map', '0:v:0',
            '-map', '[aout]',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart',
            str(final_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self.timings['mux_encode'] = round(time.time() - t0, 2)
        print(f"✓ Single-Pass Mux & Loudnorm completed in {self.timings['mux_encode']}s")
        return final_mp4

    def stage_generate_cover(self, title: str, subtitle: str, beats: list | None = None) -> Path:
        t0 = time.time()
        style = self.visual_style
        if not style or style == "auto":
            style = select_visual_style_for_topic(title, beats)
        print(f">>> [Stage 5/5] Generating High-CTR Cover using style: '{style}' for {self.platform}...")
        
        bg_files = sorted(list(self.bg_dir.glob('*.jpg')) + list(self.bg_dir.glob('*.png')))
        if bg_files:
            bg_candidate = bg_files[0]
        else:
            bg_candidate = BG_POOL / 'unsplash_meeting.jpg'
        bg_uri = b64_img(bg_candidate)

        cover_html = build_cover_html(style, title, subtitle, bg_uri, beats)
        cover_html_path = self.covers_dir / 'cover.html'
        cover_html_path.write_text(cover_html, encoding='utf-8')
        cover_jpg = self.covers_dir / 'cover_1080x1920.jpg'

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1080, 'height': 1920})
            page.goto(cover_html_path.as_uri(), wait_until='networkidle')
            page.screenshot(path=str(cover_jpg), quality=95, type='jpeg')
            browser.close()

        self.timings['cover'] = round(time.time() - t0, 2)
        print(f"✓ Cover generated in {self.timings['cover']}s: {cover_jpg} [Template: {style}]")
        return cover_jpg

    def audit_final_delivery(self, final_mp4: Path, cover_jpg: Path):
        print("\n" + "="*50)
        print("🎉 END-TO-END PIPELINE AUDIT REPORT")
        print("="*50)
        dur = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(final_mp4)], text=True).strip()
        size_mb = final_mp4.stat().st_size / (1024 * 1024)
        
        total_pipeline_time = sum(self.timings.values())
        print(f"Final Video : {final_mp4}")
        print(f"Final Cover : {cover_jpg}")
        print(f"Duration    : {float(dur):.2f} s")
        print(f"File Size   : {size_mb:.2f} MB")
        print(f"\n--- Wall-Clock Elapsed Breakdown ---")
        for k, v in self.timings.items():
            print(f"  * {k.ljust(15)}: {v}s")
        print(f"------------------------------------")
        print(f"🔥 TOTAL TIME : {total_pipeline_time:.2f}s (~{total_pipeline_time/60:.2f} min)")
        if total_pipeline_time <= 180:
            print("🚀 STATUS: UNDER 3-MINUTE PERFORMANCE BENCHMARK! (PASSED)")
        else:
            print(f"⚠️ STATUS: Exceeded 180s benchmark by {total_pipeline_time - 180:.1f}s")
        print("="*50 + "\n")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Run Fast Dialogue Video Pipeline.")
    parser.add_argument("--scenario-json", default="", help="Path to scenario beats JSON file")
    parser.add_argument("--out-dir", default="/root/.ai-self-media-tools/data/runs/benchmark_v2_fast", help="Output directory")
    parser.add_argument("--bg-dir", default="", help="Directory with background images")
    parser.add_argument("--platform", default="douyin_ai", help="Platform name (douyin_ai or kuaishou)")
    parser.add_argument("--visual-style", default="auto", choices=["auto", "evidence_card", "vibrant_sticker", "terminal_code", "minimal_blueprint"], help="Visual design style")
    parser.add_argument("--cover-title", default="为什么领导总能一眼看出你的表格是用AI做的？", help="Cover main title")
    parser.add_argument("--cover-subtitle", default="开会被抓到假数据当场穿帮？<span>架构师3条铁律彻底锁死准确率</span>", help="Cover subtitle")
    args = parser.parse_args()

    if args.scenario_json and Path(args.scenario_json).is_file():
        beats = json.loads(Path(args.scenario_json).read_text(encoding='utf-8'))
    else:
        # Test execution with realistic workplace topic
        beats = [
        {
            "id": "s01",
            "eyebrow": "01 / 职场翻车现场",
            "title": "为什么AI写方案一问就穿帮？",
            "q_text": "老张，我用大模型写的方案，开会被抓到假数据，太尴尬了！",
            "a_text": "踩到大模型幻觉的坑了！没给依据，它就会一本正经地瞎编。",
            "mode": "split",
            "card_data": {
                "tag": "认知纠偏",
                "headline": "直接要方案 = 默认允许模型脑补",
                "desc": "大模型是概率语言补全机，绝非事实检索库。"
            }
        },
        {
            "id": "s02",
            "eyebrow": "02 / 本质认知转变",
            "title": "从‘直接要’到‘做提炼’",
            "q_text": "我看它条理挺顺，怎么里面核心数字全是编的？",
            "a_text": "绝不能直接向它‘要方案’，而是要喂入真实材料让它‘做提炼’。",
            "mode": "mindset",
            "card_data": {
                "wrong": "“帮我写一份2026年AI效率落地商业方案”",
                "right": "“基于这份附件财报第3节数据，提炼核心结论”"
            }
        },
        {
            "id": "s03",
            "eyebrow": "03 / 避坑第1招",
            "title": "锁死真实信源：严禁超出材料",
            "q_text": "那第一步具体该怎么做？怎么防它乱猜？",
            "a_text": "第一条叫锁死信源：把真实材料喂给它，明确命令没给的一律不准写。",
            "mode": "lock_source",
            "card_data": {
                "step": "01",
                "name": "真实信源接地 (Grounding)",
                "rule": "Prompt明文约束：‘所有数据只能引用给定附件，未提及的一律回答未包含’。"
            }
        },
        {
            "id": "s04",
            "eyebrow": "04 / 避坑第2招",
            "title": "强制标注出处：结论必须挂钩原文",
            "q_text": "那它推导出来的结论，又该怎么快速核实？",
            "a_text": "第二条叫强制标注出处：每条结论后括号注明原文段落，查不到直接剔除。",
            "mode": "cite_source",
            "card_data": {
                "step": "02",
                "name": "结论引用溯源 (Citation)",
                "rule": "要求模型每输出一个数字或结论，必须在末尾附带 [文档名-章节] 以供人工核验。"
            }
        },
        {
            "id": "s05",
            "eyebrow": "05 / 避坑第3招",
            "title": "人机骨肉分离：AI润色，人工死守数据",
            "q_text": "明白了！整篇方案的核心架构该怎么把控？",
            "a_text": "第三条叫骨肉分离：让 AI 负责排版润色，核心数据你自己死守。",
            "mode": "separate",
            "card_data": {
                "name": "职责绝对隔离",
                "ai_role": "AI 职责：文字润色、结构排版、排版扩写",
                "human_role": "人类职责：核心业务逻辑、边界把控、真实数据复核"
            }
        },
        {
            "id": "s06",
            "eyebrow": "06 / 实战清单自检",
            "title": "4步自检SOP：逐条过关再交差",
            "q_text": "这3招太实用了！方案交付前怎么快速自检？",
            "a_text": "记住这4步：查信源、查出处、查边界、查数据，逐条核对完再交差。",
            "mode": "checklist",
            "card_data": {
                "items": [
                    ("1. 查信源", "数据是否全部来自附件，无脑补"),
                    ("2. 查出处", "关键结论是否均附带原文段落标注"),
                    ("3. 查边界", "超出上下文的问题模型是否明确拒答"),
                    ("4. 查数据", "核心商业指标是否经人工核算确认")
                ]
            }
        },
        {
            "id": "s07",
            "eyebrow": "07 / 行动互动闭环",
            "title": "高效不踩坑，架构师带你落地",
            "q_text": "赶紧存下了！哪里还能学更多避坑实战？",
            "a_text": "快手关注我，带你掌握可落地的效率工程。你方案翻过车吗？评论区聊聊！",
            "mode": "action",
            "card_data": {
                "cta_title": "领取《防AI幻觉约束词库》",
                "cta_sub": "已沉淀至团队内部 SOP 规范，直接套用",
                "prompt_tip": "评论区回复【防翻车】即刻获取"
            }
        }
    ]
    
    out_dir = Path(args.out_dir)
    pipeline = FastDialoguePipeline(out_dir, bg_dir=Path(args.bg_dir) if args.bg_dir else None, platform=args.platform, visual_style=args.visual_style)
    
    pipeline.validate_preflight(beats)
    meta = asyncio.run(pipeline.stage_tts(beats))
    html_items = pipeline.stage_html(meta)
    pipeline.stage_record_webm(html_items)
    final_mp4 = pipeline.stage_single_pass_mux(meta)
    cover_jpg = pipeline.stage_generate_cover(
        title=args.cover_title,
        subtitle=args.cover_subtitle
    )
    pipeline.audit_final_delivery(final_mp4, cover_jpg)
