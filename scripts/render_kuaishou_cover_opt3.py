import asyncio
import base64
from pathlib import Path
from playwright.async_api import async_playwright

OUT_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1/covers')
meeting_img = OUT_DIR / 'unsplash_meeting.jpg'
b64_meeting = base64.b64encode(meeting_img.read_bytes()).decode('utf-8')

# Option 3: 100% 原生明亮实景，不加任何全屏暗角蒙版，采用“红黄警示贴纸 + 纯白大字 + 强投影”
html_v2_opt3 = f"""<!DOCTYPE html>
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
/* 100% 原生真实照片光彩，不压暗，不改变对比度，纯实景呈现 */
.raw-bg {{
    position: absolute; inset: 0;
    background-image: url('data:image/jpeg;base64,{b64_meeting}');
    background-size: cover;
    background-position: center 20%;
}}

.content-container {{
    position: absolute; inset: 60px 50px;
    display: flex; flex-direction: column; justify-content: space-between;
    z-index: 10;
}}

/* 顶部浮动警示胶囊 */
.top-row {{
    display: flex; gap: 16px;
}}
.tag-red {{
    background: #dc2626; color: #fff;
    font-size: 34px; font-weight: 950;
    padding: 12px 32px; border-radius: 999px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}}
.tag-black {{
    background: rgba(0,0,0,0.8); color: #fef08a;
    font-size: 30px; font-weight: 900;
    padding: 12px 28px; border-radius: 999px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}}

/* 核心标题贴条块（直接在明亮实景上悬浮，高反差） */
.sticker-container {{
    margin-top: 30px;
    display: flex; flex-direction: column; gap: 16px;
    align-items: flex-start;
}}
.sticker-warn {{
    background: #e11d48; color: #fff;
    font-size: 40px; font-weight: 950;
    padding: 10px 24px; border-radius: 12px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    transform: rotate(-1.5deg);
}}
.sticker-main-1 {{
    background: #0f172a; color: #ffffff;
    font-size: 96px; font-weight: 1000;
    padding: 12px 32px; border-radius: 16px;
    box-shadow: 0 16px 36px rgba(0,0,0,0.6);
    letter-spacing: -1px;
}}
.sticker-main-2 {{
    background: #facc15; color: #0f172a;
    font-size: 106px; font-weight: 1000;
    padding: 12px 32px; border-radius: 16px;
    box-shadow: 0 16px 36px rgba(0,0,0,0.6);
    letter-spacing: -1px;
}}

/* 中间留出巨幅空白，让手势、开会、笔记本电脑完全裸露 */
.scene-spacer {{
    flex: 1;
}}

/* 底部极简高亮白底黑字卡片 */
.bottom-banner {{
    background: rgba(15, 23, 42, 0.9);
    border-radius: 28px;
    padding: 28px 36px;
    box-shadow: 0 20px 50px rgba(0,0,0,0.5);
    display: flex; flex-direction: column; gap: 16px;
}}
.bottom-title {{
    font-size: 36px; font-weight: 900; color: #38bdf8;
    display: flex; align-items: center; justify-content: space-between;
}}
.bottom-rules {{
    display: flex; justify-content: space-between;
    font-size: 30px; font-weight: 800; color: #f8fafc;
}}
.bottom-cta {{
    background: #facc15; color: #000;
    font-size: 38px; font-weight: 950;
    padding: 20px; border-radius: 16px; text-align: center;
    box-shadow: 0 8px 20px rgba(250,204,21,0.4);
}}
</style>
</head>
<body>
    <div class="raw-bg"></div>
    <div class="content-container">
        <div class="top-row">
            <div class="tag-red">🚨 职场翻车预警</div>
            <div class="tag-black">大模型幻觉实录</div>
        </div>
        
        <div class="sticker-container">
            <div class="sticker-warn">汇报当场穿帮被抓现行！</div>
            <div class="sticker-main-1">千万别直接让</div>
            <div class="sticker-main-2">AI替你写方案！</div>
        </div>
        
        <div class="scene-spacer"></div>
        
        <div class="bottom-banner">
            <div class="bottom-title">
                <span>防一本正经胡说 · 3条硬核实操</span>
                <span style="font-size: 24px; color: #94a3b8;">老张支招</span>
            </div>
            <div class="bottom-rules">
                <span>① 锁死真实信源</span>
                <span>② 强制标明出处</span>
                <span>③ 核心骨肉分离</span>
            </div>
            <div class="bottom-cta">
                评论区回复【防翻车】领避坑约束词 📥
            </div>
        </div>
    </div>
</body>
</html>
"""

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport={'width': 1080, 'height': 1920})
        await page.set_content(html_v2_opt3)
        p3 = OUT_DIR / 'cover_real_bright_sticker.jpg'
        await page.screenshot(path=str(p3), type='jpeg', quality=95)
        await page.close()
        await browser.close()
        print(f"Rendered {p3.name}")

asyncio.run(run())
