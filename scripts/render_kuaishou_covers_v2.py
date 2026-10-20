import asyncio
import base64
from pathlib import Path
from playwright.async_api import async_playwright

OUT_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1/covers')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Read downloaded real photo assets
meeting_img = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1/covers/unsplash_meeting.jpg')
work_img = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1/covers/unsplash_frustrated_work.jpg')

b64_meeting = base64.b64encode(meeting_img.read_bytes()).decode('utf-8')
b64_work = base64.b64encode(work_img.read_bytes()).decode('utf-8')

# Option 1: 真实会议室现场 + 超大字强冲突（背景清晰可见会议手势、电脑与笔记本）
html_v2_opt1 = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{
    margin: 0; padding: 0;
    width: 1080px; height: 1920px;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    overflow: hidden;
    position: relative;
}}
/* 真实实景背景：保持明亮自然，绝无大面积死黑压制 */
.real-bg {{
    position: absolute; inset: 0;
    background-image: url('data:image/jpeg;base64,{b64_meeting}');
    background-size: cover;
    background-position: center 20%;
    filter: brightness(0.92) contrast(1.08);
}}

/* 仅在文字需要阅读的顶部与底部添加轻量渐变遮罩，中间与背景实物完全露出 */
.vignette-overlay {{
    position: absolute; inset: 0;
    background: linear-gradient(
        to bottom,
        rgba(0, 0, 0, 0.82) 0%,
        rgba(0, 0, 0, 0.55) 30%,
        rgba(0, 0, 0, 0.15) 55%,
        rgba(0, 0, 0, 0.70) 85%,
        rgba(0, 0, 0, 0.90) 100%
    );
}}

.content-container {{
    position: absolute; inset: 60px 50px;
    display: flex; flex-direction: column; justify-content: space-between;
    z-index: 10;
}}

/* 顶部标签栏 */
.top-bar {{
    display: flex; justify-content: space-between; align-items: center;
}}
.tag-pill {{
    background: #ef4444; color: #ffffff;
    font-size: 32px; font-weight: 900;
    padding: 12px 30px; border-radius: 999px;
    box-shadow: 0 8px 24px rgba(239, 68, 68, 0.5);
    display: flex; align-items: center; gap: 12px;
}}
.tag-sub {{
    background: rgba(0,0,0,0.65); border: 2px solid rgba(255,255,255,0.4);
    color: #f1f5f9; font-size: 28px; font-weight: 800;
    padding: 10px 24px; border-radius: 999px;
    backdrop-filter: blur(8px);
}}

/* 主标题区：字号极大，多重文字阴影，无论什么实景底图都极为清晰 */
.hook-block {{
    display: flex; flex-direction: column; gap: 16px;
    margin-top: 20px;
}}
.sub-warning {{
    display: inline-flex; align-items: center;
    background: #ffd166; color: #000;
    font-size: 36px; font-weight: 950;
    padding: 8px 24px; border-radius: 8px;
    width: fit-content;
    box-shadow: 0 6px 20px rgba(0,0,0,0.5);
}}
.title-line-1 {{
    font-size: 104px; font-weight: 1000; line-height: 1.15;
    color: #ffffff;
    text-shadow: 0 6px 12px rgba(0,0,0,0.9), 0 12px 36px rgba(0,0,0,0.8), 0 0 20px rgba(0,0,0,0.8);
    letter-spacing: -1px;
}}
.title-line-2 {{
    font-size: 112px; font-weight: 1000; line-height: 1.15;
    color: #ffd166;
    text-shadow: 0 6px 12px rgba(0,0,0,0.9), 0 12px 36px rgba(255, 209, 102, 0.4), 0 0 24px rgba(0,0,0,0.9);
    letter-spacing: -1px;
}}

/* 留出中间大面积透视区，让真实的电脑、开会手势、笔记本清楚可见 */
.real-scene-window {{
    flex: 1;
    display: flex; align-items: center; justify-content: center;
    pointer-events: none;
}}
.scene-indicator {{
    background: rgba(0, 0, 0, 0.6);
    border: 1.5px solid rgba(255, 255, 255, 0.35);
    border-radius: 999px;
    padding: 10px 28px;
    color: #e2e8f0; font-size: 26px; font-weight: 700;
    backdrop-filter: blur(8px);
    box-shadow: 0 6px 18px rgba(0,0,0,0.4);
}}

/* 下方悬浮轻量半透明实操卡 */
.bottom-glass-card {{
    background: rgba(15, 23, 42, 0.72);
    border: 2.5px solid rgba(255, 255, 255, 0.25);
    border-radius: 28px;
    padding: 30px 36px;
    backdrop-filter: blur(16px);
    box-shadow: 0 24px 50px rgba(0,0,0,0.6);
    display: flex; flex-direction: column; gap: 16px;
}}
.card-header-row {{
    display: flex; justify-content: space-between; align-items: center;
}}
.card-speaker {{
    display: flex; align-items: center; gap: 16px;
}}
.avatar-lin {{
    width: 64px; height: 64px; border-radius: 50%;
    background: #f43f5e; color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-size: 32px; font-weight: 900;
    box-shadow: 0 4px 14px rgba(244,63,94,0.6);
}}
.speaker-name {{
    font-size: 32px; font-weight: 900; color: #fff;
}}
.card-accent-badge {{
    color: #fca5a5; font-size: 26px; font-weight: 700;
}}
.card-quote {{
    font-size: 32px; line-height: 1.4; color: #f1f5f9; font-weight: 700;
    background: rgba(239,68,68,0.25); border-left: 6px solid #ef4444;
    padding: 14px 20px; border-radius: 12px;
}}
.tips-row {{
    display: flex; justify-content: space-around;
    padding-top: 6px;
    border-top: 1px solid rgba(255,255,255,0.15);
}}
.tips-item {{
    font-size: 26px; font-weight: 800; color: #6ee7b7;
    display: flex; align-items: center; gap: 8px;
}}

/* 底部 CTA 按钮 */
.cta-button {{
    margin-top: 16px;
    background: linear-gradient(90deg, #ef4444, #dc2626);
    color: #ffffff;
    font-size: 38px; font-weight: 950;
    padding: 24px; text-align: center; border-radius: 20px;
    box-shadow: 0 10px 30px rgba(239, 68, 68, 0.6);
    letter-spacing: 1px;
}}
</style>
</head>
<body>
    <div class="real-bg"></div>
    <div class="vignette-overlay"></div>
    
    <div class="content-container">
        <!-- 顶部标签 -->
        <div class="top-bar">
            <div class="tag-pill">🔥 职场避坑第一期</div>
            <div class="tag-sub">真实翻车实录</div>
        </div>
        
        <!-- 巨幅主标题（强痛点冲突） -->
        <div class="hook-block">
            <div class="sub-warning">汇报当场穿帮？</div>
            <div class="title-line-1">千万别直接让</div>
            <div class="title-line-2">AI替你写方案！</div>
        </div>
        
        <!-- 中部大面积实景透出视窗 -->
        <div class="real-scene-window">
            <div class="scene-indicator">📍 真实办公会议场景 · 开会现场</div>
        </div>
        
        <!-- 底部半透明卡片与CTA -->
        <div>
            <div class="bottom-glass-card">
                <div class="card-header-row">
                    <div class="card-speaker">
                        <div class="avatar-lin">林</div>
                        <div class="speaker-name">小林 · 方案翻车事故</div>
                    </div>
                    <div class="card-accent-badge">大模型幻觉编数据</div>
                </div>
                <div class="card-quote">
                    “5000字方案看似完美，被领导追问数据出处，发现全是编的！”
                </div>
                <div class="tips-row">
                    <div class="tips-item">✔ 锁死信源</div>
                    <div class="tips-item">✔ 强制出处</div>
                    <div class="tips-item">✔ 骨肉分离</div>
                </div>
            </div>
            
            <div class="cta-button">
                3招彻底锁死准确率 ⚡ 赶紧存下
            </div>
        </div>
    </div>
</body>
</html>
"""

# Option 2: 真实工位写代码/方案实拍 + 极客架构师SOP（背景清晰可见码农敲电脑与工位）
html_v2_opt2 = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{
    margin: 0; padding: 0;
    width: 1080px; height: 1920px;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    overflow: hidden;
    position: relative;
}}
/* 真实工位背景：真实人物、笔记本、代码界面通透自然 */
.real-bg {{
    position: absolute; inset: 0;
    background-image: url('data:image/jpeg;base64,{b64_work}');
    background-size: cover;
    background-position: center 25%;
    filter: brightness(0.90) contrast(1.06);
}}

/* 局部半透明渐变，保证顶部标题和底部卡片清晰，中间工位人物清晰透出 */
.vignette-overlay {{
    position: absolute; inset: 0;
    background: linear-gradient(
        to bottom,
        rgba(3, 7, 18, 0.88) 0%,
        rgba(3, 7, 18, 0.60) 28%,
        rgba(3, 7, 18, 0.15) 52%,
        rgba(3, 7, 18, 0.70) 80%,
        rgba(3, 7, 18, 0.94) 100%
    );
}}

.content-container {{
    position: absolute; inset: 60px 50px;
    display: flex; flex-direction: column; justify-content: space-between;
    z-index: 10;
}}

/* 顶部标签栏 */
.top-bar {{
    display: flex; justify-content: space-between; align-items: center;
}}
.tag-pill {{
    background: #0284c7; color: #ffffff;
    font-size: 32px; font-weight: 900;
    padding: 12px 30px; border-radius: 999px;
    box-shadow: 0 8px 24px rgba(2, 132, 199, 0.5);
    display: flex; align-items: center; gap: 12px;
}}
.tag-sub {{
    background: rgba(16, 185, 129, 0.25); border: 2px solid #10b981;
    color: #6ee7b7; font-size: 28px; font-weight: 800;
    padding: 10px 24px; border-radius: 999px;
    backdrop-filter: blur(8px);
}}

/* 主标题区 */
.hook-block {{
    display: flex; flex-direction: column; gap: 14px;
    margin-top: 20px;
}}
.sub-warning {{
    color: #38bdf8; font-size: 36px; font-weight: 900;
    letter-spacing: 2px; text-shadow: 0 4px 10px rgba(0,0,0,0.8);
}}
.title-line-1 {{
    font-size: 102px; font-weight: 1000; line-height: 1.15;
    color: #ffffff;
    text-shadow: 0 6px 14px rgba(0,0,0,0.95), 0 12px 36px rgba(0,0,0,0.8), 0 0 20px rgba(0,0,0,0.9);
}}
.title-line-2 {{
    font-size: 108px; font-weight: 1000; line-height: 1.15;
    color: #38bdf8;
    text-shadow: 0 6px 14px rgba(0,0,0,0.95), 0 12px 36px rgba(56, 189, 248, 0.5), 0 0 25px rgba(0,0,0,0.9);
}}

/* 中间工位实景视窗 */
.real-scene-window {{
    flex: 1;
    display: flex; align-items: center; justify-content: center;
    pointer-events: none;
}}
.scene-indicator {{
    background: rgba(3, 7, 18, 0.65);
    border: 1.5px solid rgba(56, 189, 248, 0.4);
    border-radius: 999px;
    padding: 10px 28px;
    color: #bae6fd; font-size: 26px; font-weight: 700;
    backdrop-filter: blur(8px);
    box-shadow: 0 6px 18px rgba(0,0,0,0.5);
}}

/* 底部3条SOP精炼卡片（磨砂半透明，不挡住桌面） */
.sop-container {{
    display: flex; flex-direction: column; gap: 14px;
}}
.sop-card {{
    background: rgba(15, 23, 42, 0.76);
    border: 2px solid rgba(56, 189, 248, 0.28);
    border-radius: 20px;
    padding: 18px 24px;
    backdrop-filter: blur(14px);
    display: flex; align-items: center; gap: 20px;
    box-shadow: 0 12px 30px rgba(0,0,0,0.5);
}}
.sop-num {{
    width: 54px; height: 54px; border-radius: 12px;
    background: #0284c7; font-size: 30px; font-weight: 950;
    display: flex; align-items: center; justify-content: center;
    color: #fff; flex-shrink: 0;
}}
.sop-text b {{ font-size: 32px; color: #fff; display: block; }}
.sop-text span {{ font-size: 24px; color: #94a3b8; }}

/* 底部 CTA 按钮 */
.cta-button {{
    margin-top: 14px;
    background: linear-gradient(90deg, #0284c7, #0ea5e9);
    color: #ffffff;
    font-size: 38px; font-weight: 950;
    padding: 24px; text-align: center; border-radius: 20px;
    box-shadow: 0 10px 30px rgba(14, 165, 233, 0.5);
    letter-spacing: 1px;
}}
</style>
</head>
<body>
    <div class="real-bg"></div>
    <div class="vignette-overlay"></div>
    
    <div class="content-container">
        <!-- 顶部标签 -->
        <div class="top-bar">
            <div class="tag-pill">💻 架构师避坑指南</div>
            <div class="tag-sub">SOP 实战</div>
        </div>
        
        <!-- 核心大字 -->
        <div class="hook-block">
            <div class="sub-warning">拒绝大模型一本正经胡说</div>
            <div class="title-line-1">防AI方案翻车</div>
            <div class="title-line-2">我只看这3条铁律</div>
        </div>
        
        <!-- 中部实景视窗 -->
        <div class="real-scene-window">
            <div class="scene-indicator">📍 真实写方案/代码工位现场</div>
        </div>
        
        <!-- 底部3条SOP与CTA -->
        <div>
            <div class="sop-container">
                <div class="sop-card">
                    <div class="sop-num">1</div>
                    <div class="sop-text">
                        <b>锁死真实信源</b>
                        <span>不给材料坚决不让AI发散盲猜</span>
                    </div>
                </div>
                <div class="sop-card">
                    <div class="sop-num">2</div>
                    <div class="sop-text">
                        <b>强制标注出处</b>
                        <span>结论后括号标明来源，无来源直接剔除</span>
                    </div>
                </div>
                <div class="sop-card">
                    <div class="sop-num">3</div>
                    <div class="sop-text">
                        <b>核心骨肉分离</b>
                        <span>AI负责排版润色，人工死守核心数据</span>
                    </div>
                </div>
            </div>
            
            <div class="cta-button">
                评论区回复【防翻车】领完整词库 📥
            </div>
        </div>
    </div>
</body>
</html>
"""

async def run_renders():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        
        # Render Cover 1
        page1 = await browser.new_page(viewport={'width': 1080, 'height': 1920})
        await page1.set_content(html_v2_opt1)
        p1 = OUT_DIR / 'cover_real_meeting_conflict.jpg'
        await page1.screenshot(path=str(p1), type='jpeg', quality=95)
        await page1.close()
        print(f"Rendered {p1.name}")
        
        # Render Cover 2
        page2 = await browser.new_page(viewport={'width': 1080, 'height': 1920})
        await page2.set_content(html_v2_opt2)
        p2 = OUT_DIR / 'cover_real_work_sop.jpg'
        await page2.screenshot(path=str(p2), type='jpeg', quality=95)
        await page2.close()
        print(f"Rendered {p2.name}")
        
        await browser.close()

asyncio.run(run_renders())
print("V2 covers with CLEAR REAL-WORLD BACKGROUND generated successfully!")
