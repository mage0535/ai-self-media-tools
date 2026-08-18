#!/usr/bin/env python3
import asyncio, base64, json, urllib.parse, urllib.request
from pathlib import Path

ROOT=Path('/root/.ai-self-media-tools'); OUT=ROOT/'data/overnight/codex-recovery-20260818/xiaohongshu_mascot_v2'; OUT.mkdir(parents=True,exist_ok=True)
CARDS=[
 ('hero','小猫负责生成','小狗负责验收','AI输出四步双检法','cat dog working together'),
 ('split','角色一：生成猫','负责起草、整理、给候选','候选不等于事实','playful cat laptop'),
 ('timeline','第一关：看来源','链接｜原文｜截图｜时间','小狗先找证据','watchful dog computer'),
 ('checklist','第二关：核事实','数字有出处｜案例可复核｜不确定就标记','没有依据就退回','dog checklist office'),
 ('warning','第三关：补缺口','负责人？截止？权限？','让小猫别乱猜','curious cat notebook'),
 ('compare','第四关：看交付','技术成功 ≠ 业务成功','文件、状态、回执都要有','cat dog comparison'),
 ('receipt','一张交付回执','任务号｜内容哈希｜平台状态｜证据路径','小狗签字才放行','dog guarding document'),
 ('flow','完整双检流程','输入 → 生成猫 → 验收狗 → 交付','失败退回对应步骤','cat dog workflow'),
 ('action','今天就能用','把“帮我检查”改成四关清单','保存这套猫狗双检法','cute cat dog office'),
]
def api_key():
  for p in (ROOT/'secrets/channel_matrix.env',ROOT/'secrets/image.env'):
    if p.is_file():
      for line in p.read_text().splitlines():
        if line.startswith('PEXELS_API_KEY='): return line.split('=',1)[1].strip().strip('"\'')
  raise RuntimeError('PEXELS_API_KEY missing')
def fetch_images():
  records=[]
  for i,(_,_,_,_,query) in enumerate(CARDS,1):
    url='https://api.pexels.com/v1/search?'+urllib.parse.urlencode({'query':query,'per_page':12,'orientation':'portrait'})
    data=json.load(urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':api_key(),'User-Agent':'Mozilla/5.0'}),timeout=25))
    photo=data['photos'][(i*2)%len(data['photos'])]; link=photo['src']['large2x']; target=OUT/f'asset_{i:02d}.jpg'
    target.write_bytes(urllib.request.urlopen(urllib.request.Request(link,headers={'User-Agent':'Mozilla/5.0'}),timeout=30).read())
    records.append({'card':i,'query':query,'source_url':photo['url'],'photographer':photo['photographer'],'license':'Pexels','path':str(target)})
  (OUT/'asset_provenance.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
async def render():
  from playwright.async_api import async_playwright
  async with async_playwright() as pw:
    browser=await pw.chromium.launch(headless=True,args=['--no-sandbox'])
    for i,(layout,kicker,title,body,_) in enumerate(CARDS,1):
      img=base64.b64encode((OUT/f'asset_{i:02d}.jpg').read_bytes()).decode(); accent=['#FFD166','#7BDFF2','#B2F7EF','#FF8FAB'][i%4]
      extra={
       'hero':'<div class="roles"><b>🐱 生成</b><b>🐶 验收</b></div>',
       'split':'<div class="split"><span>候选</span><span>证据</span></div>',
       'timeline':'<div class="line">来源 ●──● 原文 ●──● 时间</div>',
       'checklist':'<ul><li>来源可打开</li><li>数字可追溯</li><li>缺口有标记</li></ul>',
       'warning':'<div class="warn">待确认 ≠ 自动补全</div>',
       'compare':'<div class="split"><span>技术成功</span><span>业务成功</span></div>',
       'receipt':'<div class="receipt">任务号 ✓<br>内容哈希 ✓<br>平台状态 ✓<br>证据路径 ✓</div>',
       'flow':'<div class="line">输入 → 🐱 → 🐶 → 交付</div>',
       'action':'<div class="save">先保存，再接进工作流</div>'}[layout]
      html=f'''<html><style>*{{box-sizing:border-box}}body{{margin:0;width:1080px;height:1440px;overflow:hidden;font-family:"Noto Sans CJK SC";color:white;background:#111}}.bg{{position:absolute;inset:0;background:url(data:image/jpeg;base64,{img}) center/cover;filter:saturate(1.12)}}.veil{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.12),rgba(0,0,0,.86) 68%)}}.card{{position:absolute;left:64px;right:64px;bottom:70px;padding:48px;background:rgba(10,18,30,.78);border:3px solid {accent};border-radius:34px;box-shadow:0 28px 80px #000}}.idx{{position:absolute;top:55px;right:55px;background:{accent};color:#111;border-radius:50%;padding:16px 22px;font-weight:900;font-size:32px}}.k{{color:{accent};font-size:34px;font-weight:800}}h1{{font-size:68px;line-height:1.14;margin:18px 0}}p{{font-size:38px;line-height:1.45;margin:14px 0}}.roles,.split{{display:flex;gap:18px}}.roles b,.split span{{flex:1;padding:24px;background:rgba(255,255,255,.14);border-radius:20px;font-size:34px}}.line,.warn,.save,.receipt{{margin-top:26px;padding:24px;border-radius:20px;background:rgba(255,209,102,.16);font-size:34px;line-height:1.5}}li{{font-size:32px;margin:14px}}</style><body><div class="bg"></div><div class="veil"></div><div class="idx">{i}/9</div><div class="card"><div class="k">{kicker}</div><h1>{title}</h1><p>{body}</p>{extra}</div></body></html>'''
      page=await browser.new_page(viewport={'width':1080,'height':1440}); await page.set_content(html); await page.screenshot(path=str(OUT/f'card_{i:02d}.png')); await page.close()
    await browser.close()
fetch_images(); asyncio.run(render())
print(OUT)
