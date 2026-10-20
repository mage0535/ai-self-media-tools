import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_v2')
BG_DIR = BASE / 'backgrounds'
AUDIO_DIR = BASE / 'audio'
HTML_DIR = BASE / 'html'
WEBM_DIR = BASE / 'webm'
SEG_DIR = BASE / 'segments'
RENDER_DIR = BASE / 'render'

for d in [HTML_DIR, WEBM_DIR, SEG_DIR, RENDER_DIR]:
    d.mkdir(parents=True, exist_ok=True)

BGM_PATH = AUDIO_DIR / 'bgm.mp3'
FONT_PATH = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'

def b64_img(p: Path) -> str:
    if not p.is_file():
        return ''
    mime = 'image/png' if p.suffix.lower() == '.png' else 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(p.read_bytes()).decode('utf-8')

def esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
    width: 1080px; height: 1920px;
    overflow: hidden;
    background: #060b19;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    color: #ffffff;
}

/* 优雅平滑慢镜头，绝无任何全屏机械晃动 */
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
    background: linear-gradient(180deg, rgba(6,11,25,0.65) 0%, rgba(4,8,18,0.50) 45%, rgba(6,11,25,0.75) 100%);
}
.glow {
    position: absolute; inset: 0;
    background: radial-gradient(circle at 80% 20%, rgba(250,204,21,0.18), transparent 45%),
                radial-gradient(circle at 20% 70%, rgba(56,189,248,0.22), transparent 45%);
}
.grid {
    position: absolute; inset: 0; opacity: 0.12;
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

/* 顶部信息栏 */
.eyebrow-row {
    display: flex; justify-content: space-between; align-items: center;
    animation: fadeIn .5s ease-out both;
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
    animation: fadeIn .6s .1s ease-out both;
}

/* 对话气泡容器 */
.dialogue-box {
    margin-top: 36px;
    display: flex; flex-direction: column; gap: 24px;
}

/* 工程师提问气泡：左侧平滑滑入 */
.bubble-q {
    background: rgba(239, 68, 68, 0.18);
    border: 2px solid #ef4444;
    border-radius: 24px; padding: 24px 30px;
    backdrop-filter: blur(14px);
    box-shadow: 0 10px 30px rgba(239, 68, 68, 0.25);
    animation: slideInLeft .6s .15s both;
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

/* 架构师回答气泡：右侧平滑滑入 */
.bubble-a {
    background: rgba(16, 185, 129, 0.18);
    border: 2px solid #10b981;
    border-radius: 24px; padding: 24px 30px;
    backdrop-filter: blur(14px);
    box-shadow: 0 10px 30px rgba(16, 185, 129, 0.25);
    animation: slideInRight .6s .35s both;
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
    animation: popUp .7s .55s both;
}

/* 底部常驻标识 */
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

def generate_panel_html(b: dict) -> str:
    mode = b['mode']
    cdata = b['card_data']
    
    if mode == 'split':
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 32px; border-left: 8px solid #facc15;">
            <div style="display: inline-block; background: rgba(250,204,21,0.25); border: 1.5px solid #facc15; color: #fef08a; padding: 6px 16px; border-radius: 999px; font-size: 20px; font-weight: 900;">{esc(cdata['tag'])}</div>
            <div style="font-size: 34px; font-weight: 950; color: #fef08a; margin-top: 14px;">{esc(cdata['headline'])}</div>
            <div style="font-size: 24px; color: #e2e8f0; margin-top: 10px; line-height: 1.5;">{esc(cdata['desc'])}</div>
        </div>
        """
    elif mode == 'mindset':
        return f"""
        <div style="display: flex; flex-direction: column; gap: 16px; margin-top: 24px;">
            <div class="panel" style="padding: 22px 28px; border-left: 6px solid #ef4444; background: rgba(30,15,25,0.85);">
                <div style="color: #fca5a5; font-size: 20px; font-weight: 900;">错误做法</div>
                <div style="color: #ffffff; font-size: 26px; font-weight: 800; margin-top: 6px;">{esc(cdata['wrong'])}</div>
            </div>
            <div class="panel" style="padding: 22px 28px; border-left: 6px solid #10b981; background: rgba(10,30,25,0.85); animation-delay: .7s;">
                <div style="color: #6ee7b7; font-size: 20px; font-weight: 900;">正确做法</div>
                <div style="color: #ffffff; font-size: 26px; font-weight: 800; margin-top: 6px;">{esc(cdata['right'])}</div>
            </div>
        </div>
        """
    elif mode in ['lock_source', 'cite_source']:
        color = '#38bdf8' if mode == 'lock_source' else '#fb923c'
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 30px 32px; border-top: 5px solid {color};">
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <span style="font-size: 22px; font-weight: 900; color: {color};">军规 {esc(cdata['step'])}</span>
                <span style="font-size: 20px; color: #94a3b8; font-family: monospace;">FAIL-CLOSED RULE</span>
            </div>
            <div style="font-size: 34px; font-weight: 950; color: #ffffff; margin-top: 10px;">{esc(cdata['name'])}</div>
            <div style="font-size: 24px; color: #cbd5e1; margin-top: 12px; line-height: 1.5; background: rgba(0,0,0,0.3); padding: 14px 18px; border-radius: 12px;">
                {esc(cdata['rule'])}
            </div>
        </div>
        """
    elif mode == 'separate':
        return f"""
        <div class="panel" style="margin-top: 24px; padding: 28px 30px; border-top: 5px solid #a855f7;">
            <div style="font-size: 32px; font-weight: 950; color: #c084fc; margin-bottom: 16px;">{esc(cdata['name'])}</div>
            <div style="display: flex; flex-direction: column; gap: 12px;">
                <div style="background: rgba(168,85,247,0.18); border-left: 5px solid #a855f7; padding: 14px 20px; border-radius: 12px; font-size: 24px; font-weight: 800;">
                    {esc(cdata['ai_role'])}
                </div>
                <div style="background: rgba(16,185,129,0.18); border-left: 5px solid #10b981; padding: 14px 20px; border-radius: 12px; font-size: 24px; font-weight: 800;">
                    {esc(cdata['human_role'])}
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
        """ for title, desc in cdata['items'])
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
            <div style="font-size: 38px; font-weight: 1000; color: #fef08a;">{esc(cdata['cta_title'])}</div>
            <div style="font-size: 24px; color: #cbd5e1; margin-top: 8px;">{esc(cdata['cta_sub'])}</div>
            <div style="margin-top: 20px; background: rgba(250,204,21,0.2); padding: 14px 20px; border-radius: 14px; color: #fde047; font-size: 24px; font-weight: 900;">
                💬 {esc(cdata['prompt_tip'])}
            </div>
        </div>
        """

def build_scene_html(b: dict, bg_uri: str) -> str:
    panel_html = generate_panel_html(b)
    
    return f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <style>{CSS}</style>
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
            <!-- 工程师提问 -->
            <div class="bubble-q">
                <div class="speaker-row">
                    <div class="avatar-q">工</div>
                    <div class="speaker-title-q">工程师 · 困惑求助</div>
                </div>
                <div class="text">“{esc(b['q_text'])}”</div>
            </div>
            
            <!-- 架构师解答 -->
            <div class="bubble-a">
                <div class="speaker-row">
                    <div class="avatar-a">张</div>
                    <div class="speaker-title-a">老张 · 架构师拆解</div>
                </div>
                <div class="text">“{esc(b['a_text'])}”</div>
            </div>
            
            <!-- 知识卡片 -->
            {panel_html}
        </div>
        
        <div class="footer">
            <span>AI效率工程 · 防幻觉避坑指南</span>
            <span>点赞收藏 · 评论交流</span>
        </div>
    </div>
</body>
</html>
"""

# Precise clause timing for short, crisp subtitles without line-break artifacts
TIMED_SUBTITLES = {
    's01': [
        ('工程师：老张，我用大模型写的方案', 0.0, 2.6, 'white'),
        ('开会被抓到假数据，太尴尬了！', 2.6, 5.59, 'white'),
        ('老张：踩到大模型幻觉的坑了！', 5.79, 8.4, '#6ee7b7'),
        ('没给依据，它就会一本正经地瞎编。', 8.4, 11.47, '#6ee7b7')
    ],
    's02': [
        ('工程师：我看它条理挺顺', 0.0, 2.0, 'white'),
        ('怎么里面核心数字全是编的？', 2.0, 4.20, 'white'),
        ('老张：绝不能直接向它“要方案”', 4.40, 6.8, '#6ee7b7'),
        ('而是要喂入真实材料让它“做提炼”。', 6.8, 9.58, '#6ee7b7')
    ],
    's03': [
        ('工程师：那第一步具体该怎么做？', 0.0, 1.9, 'white'),
        ('怎么防止大模型瞎猜？', 1.9, 3.79, 'white'),
        ('老张：第一条叫锁死真实信源：', 3.99, 6.8, '#6ee7b7'),
        ('没给的数据，明确要求一律不准写。', 6.8, 10.15, '#6ee7b7')
    ],
    's04': [
        ('工程师：那它推导出来的结论', 0.0, 2.0, 'white'),
        ('又该怎么快速核实？', 2.0, 3.91, 'white'),
        ('老张：第二条叫强制标注出处：', 4.11, 7.0, '#6ee7b7'),
        ('每条结论后括号注明原文段落。', 7.0, 10.54, '#6ee7b7')
    ],
    's05': [
        ('工程师：明白了！', 0.0, 1.4, 'white'),
        ('整篇方案的核心架构怎么把控？', 1.4, 4.49, 'white'),
        ('老张：第三条叫骨肉分离：', 4.69, 7.1, '#6ee7b7'),
        ('AI负责排版润色，核心数据你自己死守。', 7.1, 11.16, '#6ee7b7')
    ],
    's06': [
        ('工程师：这3招太实用了！', 0.0, 1.8, 'white'),
        ('方案交付前怎么快速自检？', 1.8, 4.58, 'white'),
        ('老张：记住这4步自检SOP：', 4.78, 7.4, '#6ee7b7'),
        ('查信源、查出处、查边界、查数据。', 7.4, 10.87, '#6ee7b7')
    ],
    's07': [
        ('工程师：赶紧存下了！', 0.0, 1.8, 'white'),
        ('哪里还能学更多避坑实战？', 1.8, 4.18, 'white'),
        ('老张：快手关注我，带你掌握可落地的效率工程。', 4.38, 8.0, '#6ee7b7'),
        ('你方案翻过车吗？评论区聊聊！', 8.0, 11.09, '#6ee7b7')
    ]
}

def main():
    meta = json.loads((AUDIO_DIR / 'dialogue_meta.json').read_text('utf-8'))
    
    print("=== [Stage 1/4] Generating HTMLs with Real Scene Backgrounds ===")
    html_files = []
    for idx, b in enumerate(meta, 1):
        bg_file = BG_DIR / f"bg_{idx:02d}.jpg"
        bg_uri = b64_img(bg_file)
        h_content = build_scene_html(b, bg_uri)
        h_path = HTML_DIR / f"scene_{idx:02d}.html"
        h_path.write_text(h_content, encoding='utf-8')
        html_files.append((h_path, b))
        print(f"[{idx}/7] Generated {h_path.name}")
        
    print("\n=== [Stage 2/4] Recording Playwright WebM Animations (CSS Driven) ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        for idx, (h_path, b) in enumerate(html_files, 1):
            dur = b['total_dur']
            ctx = browser.new_context(
                viewport={'width': 1080, 'height': 1920},
                record_video_dir=str(WEBM_DIR),
                record_video_size={'width': 1080, 'height': 1920}
            )
            page = ctx.new_page()
            page.goto(h_path.as_uri(), wait_until='networkidle')
            page.wait_for_timeout(int((dur + 0.25) * 1000))
            
            video = page.video
            page.close()
            ctx.close()
            
            dst_webm = WEBM_DIR / f"scene_{idx:02d}.webm"
            if video is not None:
                vpath = video.path()
                shutil.copy2(vpath, dst_webm)
            print(f"[{idx}/7] Recorded {dst_webm.name} ({dur:.2f}s)")
        browser.close()

    print("\n=== [Stage 3/4] Burning Synced Subtitles in Safe Zone (y=1680) ===")
    seg_mp4s = []
    for idx, (h_path, b) in enumerate(html_files, 1):
        bid = b['id']
        webm_file = WEBM_DIR / f"scene_{idx:02d}.webm"
        tts_file = AUDIO_DIR / f"{bid}_dialogue.mp3"
        seg_mp4 = SEG_DIR / f"seg_{idx:02d}.mp4"
        total_dur = b['total_dur']
        
        subs = TIMED_SUBTITLES.get(bid, [])
        vf_filters = []
        for text, t_start, t_end, color in subs:
            safe_text = text.replace("'", "’").replace(":", "：")
            f_str = (
                f"drawtext=fontfile='{FONT_PATH}':text='{safe_text}':"
                f"fontsize=38:fontcolor={color}:borderw=3.5:bordercolor=black@0.90:"
                f"x=(w-text_w)/2:y=1680:enable='between(t,{t_start:.2f},{t_end:.2f})'"
            )
            vf_filters.append(f_str)
        
        vf_arg = ",".join(vf_filters)
        
        cmd = [
            'ffmpeg', '-y',
            '-i', str(webm_file),
            '-i', str(tts_file),
            '-t', str(total_dur),
            '-vf', vf_arg,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
            '-profile:v', 'baseline', '-level', '4.0', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k',
            '-shortest',
            str(seg_mp4)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        seg_mp4s.append(seg_mp4)
        print(f"[{idx}/7] Subtitled & Encoded {seg_mp4.name} ({total_dur:.2f}s)")
        
    print("\n=== [Stage 4/4] Concatenating & Mixing Acoustic Bed (Final Delivery) ===")
    concat_txt = SEG_DIR / 'concat.txt'
    concat_txt.write_text("".join(f"file '{p.name}'\n" for p in seg_mp4s), encoding='utf-8')
    
    video_concat = RENDER_DIR / 'video_concat.mp4'
    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', str(concat_txt),
        '-c', 'copy',
        str(video_concat)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    final_output = RENDER_DIR / 'final_dialogue_v2.mp4'
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
        '-i', str(BGM_PATH),
        '-filter_complex', filter_complex,
        '-map', '0:v:0',
        '-map', '[aout]',
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '192k',
        '-movflags', '+faststart',
        str(final_output)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    dur = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(final_output)], text=True).strip()
    size_mb = final_output.stat().st_size / (1024 * 1024)
    print(f"\n==========================================")
    print(f"🎉 FINAL VIDEO GENERATED SUCCESSFULLY!")
    print(f"Path: {final_output}")
    print(f"Duration: {float(dur):.2f}s")
    print(f"Size: {size_mb:.2f} MB")
    print(f"==========================================")

if __name__ == '__main__':
    main()
