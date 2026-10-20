import asyncio
import base64
from pathlib import Path
from playwright.async_api import async_playwright

OUT_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1/covers')
OUT_DIR.mkdir(parents=True, exist_ok=True)

BG_PATH = Path('/root/.ai-self-media-tools/data/runs/douyin_ai/20260921_wechat_voice_dialogue_r1/backgrounds/bg_01.jpg')
BG_B64 = base64.b64encode(BG_PATH.read_bytes()).decode('utf-8')

# Option 1: 极度冲突警示风（职场翻车+醒目黄黑红大字对比，适合快手双列信息流点击率）
html_opt1 = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{
    margin: 0; padding: 0;
    width: 1080px; height: 1920px;
    background: #090d16;
    color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    overflow: hidden;
    position: relative;
}}
.bg {{
    position: absolute; inset: 0;
    background-image: url('data:image/jpeg;base64,{BG_B64}');
    background-size: cover; background-position: center;
    filter: brightness(0.28) contrast(1.2) saturate(1.1);
}}
.vignette {{
    position: absolute; inset: 0;
    background: radial-gradient(circle at center, rgba(10,15,30,0.4) 20%, rgba(5,8,16,0.92) 100%);
}}
.grid {{
    position: absolute; inset: 0;
    background-image: linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
    background-size: 50px 50px;
}}
.container {{
    position: absolute; inset: 80px 60px;
    display: flex; flex-direction: column; justify-content: space-between;
    z-index: 10;
}}
.badge-row {{
    display: flex; justify-content: space-between; align-items: center;
}}
.tag-badge {{
    background: #ffd166; color: #0f172a;
    font-size: 32px; font-weight: 950;
    padding: 10px 26px; border-radius: 999px;
    box-shadow: 0 8px 24px rgba(255,209,102,0.4);
    letter-spacing: 1px;
}}
.alert-badge {{
    background: rgba(239, 68, 68, 0.25); border: 2px solid #ef4444;
    color: #fca5a5; font-size: 28px; font-weight: 900;
    padding: 8px 24px; border-radius: 999px;
}}
.main-hook {{
    display: flex; flex-direction: column; gap: 24px; margin-top: 40px;
}}
.sub-tag {{
    font-size: 42px; font-weight: 900; color: #ef4444;
    display: flex; align-items: center; gap: 14px;
    letter-spacing: 2px;
}}
.sub-tag::before {{
    content: ""; display: inline-block; width: 14px; height: 42px; background: #ef4444; border-radius: 4px;
}}
.big-title-1 {{
    font-size: 92px; font-weight: 1000; line-height: 1.15;
    color: #ffffff;
    text-shadow: 0 10px 30px rgba(0,0,0,0.9);
}}
.big-title-2 {{
    font-size: 96px; font-weight: 1000; line-height: 1.15;
    color: #ffd166;
    text-shadow: 0 10px 30px rgba(255, 209, 102, 0.3);
}}
.card-preview {{
    background: rgba(15, 23, 42, 0.88);
    border: 3px solid rgba(255,255,255,0.18);
    border-radius: 32px;
    padding: 36px 40px;
    box-shadow: 0 30px 70px rgba(0,0,0,0.8);
    backdrop-filter: blur(24px);
    display: flex; flex-direction: column; gap: 24px;
}}
.speaker-header {{
    display: flex; align-items: center; gap: 20px;
}}
.avatar-box {{
    width: 80px; height: 80px; border-radius: 50%;
    background: linear-gradient(135deg, #f43f5e, #fb7185);
    display: flex; align-items: center; justify-content: center;
    font-size: 38px; font-weight: 900; color: #fff;
    box-shadow: 0 6px 20px rgba(244, 63, 94, 0.5);
}}
.speaker-title {{
    font-size: 38px; font-weight: 900; color: #fff;
}}
.speaker-sub {{
    font-size: 26px; color: #94a3b8; font-weight: 600;
}}
.quote-box {{
    background: rgba(239, 68, 68, 0.16); border-left: 8px solid #ef4444;
    border-radius: 16px; padding: 24px 28px;
    font-size: 34px; line-height: 1.45; color: #fecaca; font-weight: 700;
}}
.bottom-checklist {{
    background: rgba(16, 185, 129, 0.18); border-left: 8px solid #10b981;
    border-radius: 16px; padding: 22px 28px;
    display: flex; justify-content: space-between; align-items: center;
}}
.bottom-checklist b {{ font-size: 36px; color: #6ee7b7; }}
.bottom-checklist span {{ font-size: 28px; color: #cbd5e1; }}
.cta-footer {{
    background: linear-gradient(90deg, #f43f5e, #ef4444);
    border-radius: 24px; padding: 28px; text-align: center;
    font-size: 42px; font-weight: 950; color: #fff;
    box-shadow: 0 12px 36px rgba(239, 68, 68, 0.4);
    letter-spacing: 2px;
}}
</style>
</head>
<body>
    <div class="bg"></div>
    <div class="vignette"></div>
    <div class="grid"></div>
    <div class="container">
        <div class="badge-row">
            <div class="tag-badge">AI 职场避坑 · 实战</div>
            <div class="alert-badge">● 翻车事故实录</div>
        </div>
        
        <div class="main-hook">
            <div class="sub-tag">汇报当场穿帮？</div>
            <div class="big-title-1">千万别直接让</div>
            <div class="big-title-2">AI替你写方案！</div>
        </div>
        
        <div class="card-preview">
            <div class="speaker-header">
                <div class="avatar-box">林</div>
                <div>
                    <div class="speaker-title">小林 · 职场新人求助</div>
                    <div class="speaker-sub">领导一追问数据出处，发现全是编的！</div>
                </div>
            </div>
            <div class="quote-box">
                “3分钟出了5000字方案，结果行业预测全是大模型幻觉编造的！”
            </div>
            <div class="bottom-checklist">
                <b>老张支招</b>
                <span>锁信源 · 标出处 · 骨肉分离</span>
            </div>
        </div>
        
        <div class="cta-footer">
            3招彻底锁死方案真实性 ⚡ 赶紧存下
        </div>
    </div>
</body>
</html>
"""

# Option 2: 沉稳干货SOP对照风（老张架构师视角，专业感极强，适合收藏党）
html_opt2 = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{
    margin: 0; padding: 0;
    width: 1080px; height: 1920px;
    background: #070c18;
    color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    overflow: hidden;
    position: relative;
}}
.bg {{
    position: absolute; inset: 0;
    background-image: url('data:image/jpeg;base64,{BG_B64}');
    background-size: cover; background-position: center;
    filter: brightness(0.24) contrast(1.25) saturate(1.1);
}}
.vignette {{
    position: absolute; inset: 0;
    background: radial-gradient(circle at center, rgba(14,165,233,0.12) 0%, rgba(4,7,15,0.95) 100%);
}}
.grid {{
    position: absolute; inset: 0;
    background-image: linear-gradient(rgba(56,189,248,0.06) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(56,189,248,0.06) 1px, transparent 1px);
    background-size: 60px 60px;
}}
.container {{
    position: absolute; inset: 80px 60px;
    display: flex; flex-direction: column; justify-content: space-between;
    z-index: 10;
}}
.badge-row {{
    display: flex; justify-content: space-between; align-items: center;
}}
.tag-badge {{
    background: #0284c7; color: #fff;
    font-size: 32px; font-weight: 950;
    padding: 10px 28px; border-radius: 999px;
    box-shadow: 0 8px 24px rgba(2,132,199,0.4);
}}
.alert-badge {{
    background: rgba(16, 185, 129, 0.2); border: 2px solid #10b981;
    color: #6ee7b7; font-size: 28px; font-weight: 900;
    padding: 8px 24px; border-radius: 999px;
}}
.main-hook {{
    display: flex; flex-direction: column; gap: 20px; margin-top: 30px;
}}
.sub-tag {{
    font-size: 38px; font-weight: 900; color: #38bdf8;
    letter-spacing: 2px;
}}
.big-title-1 {{
    font-size: 88px; font-weight: 1000; line-height: 1.2;
    color: #ffffff;
}}
.big-title-2 {{
    font-size: 92px; font-weight: 1000; line-height: 1.2;
    color: #38bdf8;
}}
.sop-matrix {{
    display: flex; flex-direction: column; gap: 20px;
}}
.sop-card {{
    background: rgba(15, 23, 42, 0.90);
    border: 2px solid rgba(56, 189, 248, 0.3);
    border-radius: 24px; padding: 28px 32px;
    backdrop-filter: blur(20px);
    display: flex; align-items: center; gap: 24px;
}}
.sop-num {{
    width: 68px; height: 68px; border-radius: 16px;
    background: #0284c7; font-size: 36px; font-weight: 950;
    display: flex; align-items: center; justify-content: center;
    color: #fff; flex-shrink: 0;
}}
.sop-info b {{ display: block; font-size: 36px; color: #fff; margin-bottom: 6px; }}
.sop-info span {{ font-size: 26px; color: #94a3b8; }}

.cta-footer {{
    background: linear-gradient(90deg, #0284c7, #0ea5e9);
    border-radius: 24px; padding: 28px; text-align: center;
    font-size: 42px; font-weight: 950; color: #fff;
    box-shadow: 0 12px 36px rgba(14, 165, 233, 0.4);
}}
</style>
</head>
<body>
    <div class="bg"></div>
    <div class="vignette"></div>
    <div class="grid"></div>
    <div class="container">
        <div class="badge-row">
            <div class="tag-badge">老张架构师拆解</div>
            <div class="alert-badge">SOP 指南</div>
        </div>
        
        <div class="main-hook">
            <div class="sub-tag">拒绝大模型一本正经胡说</div>
            <div class="big-title-1">防AI方案翻车</div>
            <div class="big-title-2">我只看这3条铁律</div>
        </div>
        
        <div class="sop-matrix">
            <div class="sop-card">
                <div class="sop-num">1</div>
                <div class="sop-info">
                    <b>锁死真实信源</b>
                    <span>不给真实材料，坚决不让AI发散盲猜</span>
                </div>
            </div>
            <div class="sop-card">
                <div class="sop-num">2</div>
                <div class="sop-info">
                    <b>强制标注出处</b>
                    <span>结论后打括号指明来源，查不到直接剔除</span>
                </div>
            </div>
            <div class="sop-card">
                <div class="sop-num">3</div>
                <div class="sop-info">
                    <b>核心骨肉分离</b>
                    <span>AI负责文字排版润色，人工死守数据复核</span>
                </div>
            </div>
        </div>
        
        <div class="cta-footer">
            评论区回复【防翻车】领完整约束词库 📥
        </div>
    </div>
</body>
</html>
"""

async def render_covers():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        
        # Render Cover 1
        page1 = await browser.new_page(viewport={'width': 1080, 'height': 1920})
        await page1.set_content(html_opt1)
        c1_path = OUT_DIR / 'cover_option1_conflict.jpg'
        await page1.screenshot(path=str(c1_path), type='jpeg', quality=95)
        await page1.close()
        print(f"Rendered {c1_path.name}")
        
        # Render Cover 2
        page2 = await browser.new_page(viewport={'width': 1080, 'height': 1920})
        await page2.set_content(html_opt2)
        c2_path = OUT_DIR / 'cover_option2_sop.jpg'
        await page2.screenshot(path=str(c2_path), type='jpeg', quality=95)
        await page2.close()
        print(f"Rendered {c2_path.name}")
        
        await browser.close()

asyncio.run(render_covers())
print("Both high-CTR 1080x1920 covers generated successfully!")
