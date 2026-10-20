from pathlib import Path
import os
import base64, json, shutil, subprocess
from playwright.sync_api import sync_playwright

ROOT=Path(os.environ.get('CONTENT_PLATFORM_HOME', str(Path(__file__).resolve().parents[1])))
OUT=ROOT/'data/artifacts/video_toolchain/shipinhao_20260911_custom'
WEBM=OUT/'webm'; HTML=OUT/'html'; SEG=OUT/'segments'
for d in [OUT,WEBM,HTML,SEG]: d.mkdir(parents=True,exist_ok=True)
BGROOT=ROOT/'data/artifacts/video_toolchain/shipinhao_20260911_v3/backgrounds'
TTSROOT=ROOT/'data/artifacts/video_toolchain/shipinhao_20260911_v4/tts'
QR=Path(os.environ.get('WECHAT_QR_ASSET', str(Path.home()/'.hermes/data/wechat_assets/qrcode_公众号.jpg')))
beats=[
 ('返工的真相','AI写完代码，你为什么还要重做？','最离谱的是：问题通常不在模型，而在你没有写验收标准。','split'),
 ('4个任务字段','输入 / 结果 / 限制 / 验收','少一个字段，AI就会自己补空白。','fields'),
 ('先计划，再执行','步骤 → 依赖 → 风险 → 回退','不要直接要答案，先让AI把路线摊开。','plan'),
 ('输出必须可验证','代码=测试  文章=来源  自动化=日志·超时·重试','看起来完成，不等于真的可交付。','evidence'),
 ('一个具体例子','“帮我做网站”  ✕','数据、筛选、加载提示、提交测试  ✓','beforeafter'),
 ('把跑通的流程存下来','输入格式 + 步骤模板 + 检查项','下次复用工作流，不要重新开一轮聊天。','template'),
 ('结果不稳先查哪里？','输入 → 步骤 → 输出 → 回滚','别先换模型，先定位是哪一层出了问题。','debug'),
 ('把AI变成执行者','收藏这条，下一次先补齐4个字段。','你最常返工代码、文案，还是自动化？评论区说说。','qr'),
]

def esc(s):
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def common_css():
    return '''*{box-sizing:border-box}html,body{margin:0;width:1080px;height:1920px;overflow:hidden}body{font-family:"Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",sans-serif;color:#fff}.bg{position:absolute;inset:-40px;background-position:center;background-size:cover;filter:saturate(1.18) contrast(1.08) brightness(0.95);animation:kenburns 14s ease-in-out infinite alternate}@keyframes kenburns{0%{transform:scale(1.02) translate(0,0)}100%{transform:scale(1.08) translate(-15px,-10px)}}.shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(8,16,36,.58) 0%,rgba(5,10,24,.48) 48%,rgba(8,16,36,.68) 100%)}.glow{position:absolute;inset:0;background:radial-gradient(circle at 75% 18%,rgba(251,191,36,.18),transparent 30%),radial-gradient(circle at 20% 80%,rgba(59,130,246,.22),transparent 35%)}.grid{position:absolute;inset:0;opacity:.11;background-image:linear-gradient(rgba(147,197,253,.5) 1px,transparent 1px),linear-gradient(90deg,rgba(147,197,253,.5) 1px,transparent 1px);background-size:54px 54px}.wrap{position:relative;z-index:2;width:100%;height:100%;padding:84px 72px 120px;display:flex;flex-direction:column}.eyebrow{font-size:23px;letter-spacing:4px;color:#fcd34d;font-weight:900;animation:fadeIn .6s both}.chapter{font-size:18px;color:#bfdbfe;letter-spacing:2px;margin-top:12px}.title{font-size:67px;line-height:1.12;font-weight:950;letter-spacing:-2px;text-shadow:0 4px 22px #000;margin:0}.title em{font-style:normal;color:#fbbf24}.body{font-size:31px;line-height:1.45;color:#e0f2fe;text-shadow:0 2px 12px #000}.panel{background:rgba(8,18,38,.8);border:2px solid rgba(147,197,253,.35);border-radius:24px;backdrop-filter:blur(12px);box-shadow:0 18px 45px rgba(0,0,0,.32)}.small{font-size:22px;color:#93c5fd}.tag{display:inline-block;padding:9px 16px;border-radius:999px;background:rgba(251,191,36,.16);border:1px solid rgba(251,191,36,.65);color:#fde68a;font-size:20px;font-weight:800}.footer{margin-top:auto;color:#bfdbfe;font-size:18px;letter-spacing:1px}.qr{width:330px;height:330px;background:#fff;padding:18px;border-radius:22px;box-shadow:0 0 42px rgba(251,191,36,.55)}@keyframes fadeIn{from{opacity:0;transform:translateY(24px)}to{opacity:1;transform:none}}@keyframes slideIn{from{opacity:0;transform:translateX(-80px)}to{opacity:1;transform:none}}@keyframes pop{from{opacity:0;transform:scale(.72)}to{opacity:1;transform:scale(1)}}@keyframes typeIn{from{clip-path:inset(0 100% 0 0);opacity:.2}to{clip-path:inset(0 0 0 0);opacity:1}}@keyframes pulse{0%,100%{box-shadow:0 0 0 rgba(251,191,36,0)}50%{box-shadow:0 0 35px rgba(251,191,36,.55)}}'''

def make_html(i, bg, data):
    title, body, extra, mode=data
    bgurl=bg.as_uri()
    css=common_css()
    if mode=='split':
        content=f'''<div class="wrap"><div class="eyebrow">01 / ROOT CAUSE</div><div class="chapter">开发者最常见的返工现场</div><div style="height:120px"></div><div class="panel" style="padding:35px;animation:slideIn .8s both"><div class="small">你以为问题在模型</div><div class="title" style="margin-top:18px">{esc(title)}</div><div class="body" style="margin-top:28px">{esc(body)}</div></div><div class="panel" style="margin-top:28px;padding:28px;display:flex;justify-content:space-between;align-items:center;animation:pop .8s .3s both"><div><div class="small">真正缺少的东西</div><div style="font-size:40px;font-weight:900;color:#fbbf24;margin-top:10px">验收标准</div></div><div style="font-size:72px;color:#60a5fa">→</div><div style="text-align:right"><div class="small">结果</div><div style="font-size:34px;font-weight:900">少返工</div></div></div><div class="footer">AI效率 · 任务链拆解</div></div>'''
    elif mode=='fields':
        fields=[('01','输入','我给了什么'),('02','结果','要交付什么'),('03','限制','不能违反什么'),('04','验收','怎样算完成')]
        boxes=''.join(f'<div class="panel" style="padding:24px;animation:pop .6s {j*.12}s both"><div style="font-size:26px;color:#fbbf24;font-weight:900">{a}</div><div style="font-size:34px;font-weight:900;margin-top:12px">{b}</div><div class="small" style="margin-top:8px">{c}</div></div>' for j,(a,b,c) in enumerate(fields))
        content=f'''<div class="wrap"><div class="eyebrow">02 / TASK BRIEF</div><div class="title" style="margin-top:42px">{esc(title)}</div><div class="body" style="margin-top:20px;animation:typeIn .8s both">{esc(body)}</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:65px">{boxes}</div><div class="panel" style="margin-top:25px;padding:24px;border-left:8px solid #fbbf24;animation:slideIn .8s .5s both"><div class="body" style="font-size:28px">{esc(extra)}</div></div><div class="footer">先写清楚，再让AI动手</div></div>'''
    elif mode=='plan':
        steps=['步骤','依赖','风险','回退']; rows=''.join(f'<div style="display:flex;align-items:center;gap:18px;margin:20px 0;animation:slideIn .65s {j*.16}s both"><div style="width:58px;height:58px;border-radius:50%;background:#fbbf24;color:#0b1326;display:flex;align-items:center;justify-content:center;font-size:27px;font-weight:900">{j+1}</div><div class="panel" style="flex:1;padding:20px 24px;font-size:33px;font-weight:900">{x}</div></div>' for j,x in enumerate(steps))
        content=f'''<div class="wrap"><div class="eyebrow">03 / PLAN FIRST</div><div class="title" style="margin-top:42px">{esc(title)}</div><div class="body" style="margin-top:20px">{esc(body)}</div><div style="margin-top:54px;position:relative">{rows}</div><div class="panel" style="margin-top:auto;padding:24px;animation:pulse 2s infinite"><div class="small">核心判断</div><div style="font-size:30px;font-weight:900;margin-top:8px">先检查路线，再开始执行</div></div></div>'''
    elif mode=='evidence':
        cards=[('CODE','测试用例'),('ARTICLE','原始来源'),('AUTOMATION','日志 / 超时 / 重试')]
        rows=''.join(f'<div class="panel" style="padding:25px;animation:typeIn .7s {j*.2}s both"><div class="tag">{a}</div><div style="font-size:31px;font-weight:900;margin-top:22px">{b}</div><div style="margin-top:18px;color:#86efac;font-size:27px">✓ 可核验</div></div>' for j,(a,b) in enumerate(cards))
        content=f'''<div class="wrap"><div class="eyebrow">04 / EVIDENCE CHECK</div><div class="title" style="margin-top:42px">{esc(title)}</div><div class="body" style="margin-top:22px">{esc(body)}</div><div style="display:flex;flex-direction:column;gap:20px;margin-top:58px">{rows}</div><div class="footer">完成 ≠ 可交付 · 证据才是验收入口</div></div>'''
    elif mode=='beforeafter':
        content=f'''<div class="wrap"><div class="eyebrow">05 / BEFORE → AFTER</div><div class="title" style="margin-top:42px">一个具体例子</div><div class="panel" style="margin-top:52px;padding:30px;border-color:#fb7185;animation:slideIn .8s both"><div class="tag" style="background:rgba(251,113,133,.2);border-color:#fb7185;color:#fecdd3">返工写法</div><div style="font-size:35px;font-weight:900;margin-top:22px">{esc(title)}</div></div><div style="font-size:68px;text-align:center;color:#fbbf24;margin:23px 0;animation:pop .8s .3s both">↓</div><div class="panel" style="padding:30px;border-color:#34d399;animation:slideIn .8s .5s both"><div class="tag" style="background:rgba(52,211,153,.2);border-color:#34d399;color:#bbf7d0">可执行写法</div><div style="font-size:31px;font-weight:900;line-height:1.4;margin-top:22px">{esc(body)}</div></div><div class="footer">把结果写成可检查的条件</div></div>'''
    elif mode=='template':
        content=f'''<div class="wrap"><div class="eyebrow">06 / SAVE THE WORKFLOW</div><div class="title" style="margin-top:42px">{esc(title)}</div><div class="body" style="margin-top:20px">{esc(body)}</div><div class="panel" style="margin-top:60px;padding:30px;transform:rotate(-2deg);animation:pop .8s both"><div style="font-size:27px;color:#fbbf24;font-weight:900">WORKFLOW_TEMPLATE.md</div><div style="margin-top:26px;font-family:monospace;font-size:25px;line-height:1.8;color:#bfdbfe">INPUT ✓<br>STEPS ✓<br>CHECKS ✓<br>ROLLBACK ✓</div></div><div class="panel" style="margin-top:24px;padding:23px;animation:slideIn .8s .5s both"><div class="body" style="font-size:28px">{esc(extra)}</div></div><div class="footer">跑通一次，保存下来</div></div>'''
    elif mode=='debug':
        checks=['输入完整吗？','步骤能执行吗？','输出能验证吗？','失败能回滚吗？']
        rows=''.join(f'<div class="panel" style="padding:22px 25px;display:flex;align-items:center;gap:18px;animation:slideIn .55s {j*.14}s both"><div style="width:38px;height:38px;border:3px solid #fbbf24;border-radius:8px"></div><div style="font-size:31px;font-weight:900">{x}</div></div>' for j,x in enumerate(checks))
        content=f'''<div class="wrap"><div class="eyebrow">07 / DEBUG THE PROCESS</div><div class="title" style="margin-top:42px">{esc(title)}</div><div class="body" style="margin-top:22px">{esc(body)}</div><div style="display:flex;flex-direction:column;gap:18px;margin-top:55px">{rows}</div><div class="footer">先定位层级，再决定是否换模型</div></div>'''
    else:
        qr=QR.as_uri(); content=f'''<div class="wrap" style="align-items:center;text-align:center"><div class="eyebrow">08 / TAKEAWAY</div><div class="title" style="margin-top:55px">{esc(title)}</div><div class="line" style="width:120px;height:5px;background:#fbbf24;margin:38px 0"></div><img class="qr" src="{qr}"><div style="font-size:40px;font-weight:900;color:#fef3c7;margin-top:30px">马吉克AI</div><div class="body" style="font-size:28px;margin-top:16px">扫码关注公众号<br>{esc(extra)}</div><div class="footer">收藏这条 · 下一次先写验收标准</div></div>'''
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body><div class="bg" style="background-image:url(\'{bgurl}\')"></div><div class="shade"></div><div class="glow"></div><div class="grid"></div>{content}</body></html>'

# Create one HTML scene per content beat and record real CSS motion as webm.
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    for idx,data in enumerate(beats,1):
        bg=BGROOT/f'bg_{idx:02d}.jpg'; h=HTML/f'scene_{idx:02d}.html'; h.write_text(make_html(idx,bg,data),encoding='utf-8')
        duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(TTSROOT/f'tts_{idx:02d}.mp3')],text=True).strip())
        ctx=browser.new_context(viewport={'width':1080,'height':1920},record_video_dir=str(WEBM),record_video_size={'width':1080,'height':1920})
        page=ctx.new_page(); page.goto(h.as_uri(),wait_until='networkidle'); page.wait_for_timeout(int((duration+0.25)*1000)); vp=page.video.path(); ctx.close(); dst=WEBM/f'scene_{idx:02d}.webm'; shutil.copy2(vp,dst)
        seg=SEG/f'seg_{idx:02d}.mp4'; subprocess.run(['ffmpeg','-y','-i',str(dst),'-i',str(TTSROOT/f'tts_{idx:02d}.mp3'),'-t',str(duration),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','medium','-crf','23','-profile:v','baseline','-level','4.0','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-shortest',str(seg)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    browser.close()
# concat video segments
concat=SEG/'concat.txt'; concat.write_text(''.join(f"file 'seg_{i:02d}.mp4'\n" for i in range(1,9)))
subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(OUT/'video_only.mp4')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
# mix BGM from audited v4 source
bgm=ROOT/'data/artifacts/video_toolchain/shipinhao_20260911_v4/bgm.mp3'
subprocess.run(['ffmpeg','-y','-i',str(OUT/'video_only.mp4'),'-stream_loop','-1','-i',str(bgm),'-filter_complex','[0:a]volume=1.0[v];[1:a]volume=0.16[bg];[v][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]','-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','128k',str(OUT/'final_custom.mp4')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('final=',OUT/'final_custom.mp4')
