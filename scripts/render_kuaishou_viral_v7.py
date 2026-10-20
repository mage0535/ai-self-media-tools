#!/usr/bin/env python3
from __future__ import annotations
import json, math, shutil, subprocess, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path('/root/.ai-self-media-tools')
OUT=ROOT/'data/artifacts/video_toolchain/20260914_kuaishou_v7'
BG=ROOT/'data/artifacts/video_toolchain/20260914_kuaishou/backgrounds'
TTS=ROOT/'data/artifacts/video_toolchain/20260914_kuaishou/tts'
BGM=ROOT/'data/artifacts/video_toolchain/20260914_kuaishou/bgm.mp3'
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
TITLE='AI 10分钟写完测试，不代表真的能用：我只看这3个结果'
SCENES=[
 ('result_split','生成通过≠真实可用','测试全绿','3个结果：运行 / 边界 / 复现'),
 ('terminal','终端证据','AI生成测试文件后，先看真实运行结果','全绿只是开始'),
 ('branch','输入分支','正常账号能过，错误账号也必须按预期失败','输入不同，结果才可信'),
 ('matrix','边界矩阵','空密码 / 超长输入 / 重复提交','少测一个，线上就可能返工'),
 ('logs','日志复现','同一份代码跑两次，失败位置要一致','RUN 01 = RUN 02'),
 ('numbers','数字反差','12条测试 → 48条测试','数量涨，不代表覆盖涨'),
 ('checklist','验收清单','01 运行  02 边界  03 复现','三项都过，再让AI扩展'),
 ('cta','评论CTA','回复“测试清单”','领取三项验收表'),
]

def sh(cmd):
    subprocess.run(cmd,check=True)

def probe_duration(p):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(p)]).decode().strip())

def esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')

def html(scene_type, headline, line, idx, bg):
    common=f'''<div class="bg"></div><div class="shade"></div><div class="top"><span>MAJIC AI · AI效率实测</span><b>{idx:02d}/08</b></div><h1>{esc(headline)}</h1>'''
    if scene_type=='result_split':
        body=f'''<main class="hero"><section class="result bad"><small>生成结果</small><strong>全绿</strong><p>测试文件生成了</p><em>但还没证明能用</em></section><div class="arrow">→</div><section class="result good"><small>验收结果</small><strong>3项</strong><p>运行 · 边界 · 复现</p><em>现在才值得相信</em></section></main><div class="promise">{esc(line)}</div>'''
    elif scene_type=='terminal':
        body=f'''<main class="terminal"><div class="termbar">● ● ●　ai-test / login.spec</div><pre>$ run tests\nPASS  file generated\nPASS  syntax checked\n<span>WAIT  real input not verified</span>\n<span>WAIT  edge cases not verified</span></pre></main><div class="caption">{esc(line)}</div>'''
    elif scene_type=='branch':
        body=f'''<main class="branch"><div class="branchnode start">输入账号</div><div class="branchline"></div><div class="branchnode pass">正常账号<br><b>PASS</b></div><div class="branchnode fail">错误账号<br><b>FAIL + 明确日志</b></div></main><div class="caption">{esc(line)}</div>'''
    elif scene_type=='matrix':
        body=f'''<main class="matrix"><div class="mhead">边界输入检查</div><div class="row"><b>空密码</b><span>必须失败</span><i>✕</i></div><div class="row"><b>超长输入</b><span>不能崩溃</span><i>✕</i></div><div class="row"><b>重复提交</b><span>必须有保护</span><i>✕</i></div></main><div class="caption">{esc(line)}</div>'''
    elif scene_type=='logs':
        body=f'''<main class="logs"><div class="logcol"><b>RUN 01</b><pre>auth:42\ninvalid_token\nexit 1</pre></div><div class="logcol active"><b>RUN 02</b><pre>auth:42\ninvalid_token\nexit 1</pre></div></main><div class="match">结果一致 ✓</div><div class="caption">{esc(line)}</div>'''
    elif scene_type=='numbers':
        body=f'''<main class="numbers"><div><strong>12</strong><span>条测试</span></div><b>→</b><div class="highlight"><strong>48</strong><span>条测试</span></div></main><div class="warning">真正覆盖的场景：还是 3 个</div><div class="caption">{esc(line)}</div>'''
    elif scene_type=='checklist':
        body=f'''<main class="checklist"><div class="check active"><b>01</b><span>运行</span><small>正常与错误输入都跑</small></div><div class="check"><b>02</b><span>边界</span><small>空值、超长、重复提交</small></div><div class="check"><b>03</b><span>复现</span><small>两次运行结果一致</small></div></main><div class="caption">{esc(line)}</div>'''
    else:
        body=f'''<main class="cta"><div class="ctaMark">SAVE</div><strong>测试清单</strong><p>运行 · 边界 · 复现</p><span>评论区回复关键词，领取三项验收表</span></main><div class="caption">{esc(line)}</div>'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1920px;overflow:hidden;background:#07111f;color:#f4f8ff;font-family:Arial,"Noto Sans CJK SC",sans-serif}}body{{position:relative}}.bg{{position:absolute;inset:0;background:url("file://{bg}") center/cover;filter:saturate(1.15) contrast(1.08)}}.shade{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(2,9,19,.35),rgba(2,9,19,.82) 78%)}}.top{{position:relative;z-index:3;display:flex;justify-content:space-between;padding:54px 54px 0;color:#ffd166;font-size:22px;letter-spacing:2px;font-weight:800}}h1{{position:relative;z-index:3;margin:34px 54px 0;font-size:54px;line-height:1.12;text-shadow:0 5px 22px #000}}main{{position:relative;z-index:3;margin:80px 54px 0}}.caption,.promise{{position:relative;z-index:3;margin:42px 54px 0;padding:24px 28px;background:rgba(2,10,22,.8);border-left:7px solid #ffd166;font-size:31px;line-height:1.35}}.hero{{display:grid;grid-template-columns:1fr 70px 1fr;gap:20px;align-items:center;margin-top:190px}}.result{{padding:34px 24px;border-radius:22px;background:rgba(4,14,28,.9);border:3px solid}}.result.bad{{border-color:#ff5570}}.result.good{{border-color:#58e29a}}.result small,.result em{{display:block;color:#c9d8e8;font-size:22px;font-style:normal}}.result strong{{display:block;font-size:88px;margin:22px 0;color:#fff}}.result p{{font-size:28px;margin:0 0 18px}}.arrow{{font-size:68px;color:#ffd166;text-align:center}}.terminal{{margin-top:120px;border:3px solid #5de1ff;background:rgba(1,8,16,.94);border-radius:10px;box-shadow:0 0 40px rgba(65,210,255,.22)}}.termbar{{padding:20px;border-bottom:2px solid #244156;color:#7df7bb;font:700 22px monospace}}pre{{margin:0;padding:32px;font:26px/1.75 monospace;white-space:pre-wrap}}pre span{{color:#ffd166}}.branch{{margin-top:180px;display:grid;grid-template-columns:1fr 1fr;gap:30px;align-items:center;text-align:center}}.branchnode{{padding:32px 18px;border-radius:18px;border:3px solid;font-size:32px;background:rgba(2,10,20,.85)}}.branchnode.start{{grid-column:1/3;border-color:#5de1ff}}.branchnode.pass{{border-color:#58e29a}}.branchnode.fail{{border-color:#ff5570}}.branchnode b{{display:block;margin-top:18px;font-size:23px}}.matrix{{margin-top:150px;padding:22px;border:3px solid #ffd166;background:rgba(3,12,25,.9)}}.mhead{{font-size:34px;font-weight:900;padding:20px;border-bottom:2px solid #705b27}}.row{{display:grid;grid-template-columns:1fr 1.4fr 80px;gap:10px;padding:25px 15px;border-bottom:1px solid #314255;font-size:28px;align-items:center}}.row i{{font-style:normal;color:#ff5570;font-size:45px;text-align:center}}.logs{{margin-top:140px;display:grid;grid-template-columns:1fr 1fr;gap:22px}}.logcol{{background:#07101b;border:2px solid #607589;border-radius:8px;overflow:hidden}}.logcol b{{display:block;padding:18px;color:#d9e6f4;background:#152536;font-size:26px}}.logcol.active{{border-color:#58e29a}}.logcol pre{{font-size:22px}}.match{{position:relative;z-index:3;margin:22px 54px;color:#58e29a;font-size:36px;font-weight:900}}.numbers{{margin-top:220px;display:grid;grid-template-columns:1fr 70px 1fr;gap:18px;align-items:center;text-align:center}}.numbers div{{padding:30px;background:rgba(2,10,20,.88);border:2px solid #7890a8;border-radius:20px}}.numbers strong{{display:block;font-size:170px;color:#ffd166;line-height:1}}.numbers span{{font-size:28px}}.numbers>b{{font-size:58px;color:#ffd166}}.numbers .highlight{{border-color:#58e29a}}.warning{{position:relative;z-index:3;margin:40px 54px 0;text-align:center;color:#ff8296;font-size:34px;font-weight:900}}.checklist{{margin-top:140px;display:grid;gap:22px}}.check{{display:grid;grid-template-columns:95px 1fr;column-gap:18px;align-items:center;padding:22px 25px;background:rgba(3,12,24,.9);border-left:10px solid #73869a;border-radius:5px}}.check.active{{border-color:#58e29a}}.check b{{grid-row:1/3;font-size:58px;color:#ffd166}}.check span{{font-size:42px;font-weight:900}}.check small{{font-size:23px;color:#c4d2e0;margin-top:8px}}.cta{{margin-top:240px;text-align:center;padding:70px 35px;border:4px solid #ffd166;background:rgba(3,12,24,.92);border-radius:24px}}.ctaMark{{color:#58e29a;letter-spacing:6px;font-size:28px;font-weight:900}}.cta strong{{display:block;font-size:98px;margin:28px 0;color:#ffd166}}.cta p{{font-size:38px;margin:0 0 28px}}.cta span{{font-size:28px;color:#e6eef7}}body:after{{content:"";position:absolute;inset:0;z-index:4;pointer-events:none;border:1px solid rgba(255,255,255,.1)}}
</style></head><body><div class="bg"></div><div class="shade"></div>{common}{body}<script>function renderFrame(t){{document.body.style.setProperty('--t',t);document.querySelectorAll('main,.caption,.promise,.warning,.match').forEach((el,i)=>{{el.style.transform='translateY('+Math.max(0,34-t*28+i*1.2)+'px)';el.style.opacity=Math.min(1,Math.max(.15,(t-.2-i*.08)*2));}});document.querySelectorAll('.result,.row,.check,.logcol').forEach((el,i)=>{{el.style.transform='translateX('+Math.sin(t*2+i)*4+'px)';}});}}</script></body></html>'''

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    html_dir=OUT/'html_v7'; shots=OUT/'shots_v7'; frames=OUT/'frames_v7'; clips=OUT/'clips_v7'
    for d in [html_dir,shots,frames,clips]:
        if d.exists(): shutil.rmtree(d)
        d.mkdir(parents=True)
    durations=[]
    for i,(typ,head,line,_) in enumerate(SCENES,1):
        tts=TTS/f'tts_{i:02d}.mp3'; d=probe_duration(tts); durations.append(d)
        bg=BG/f'bg_{i:02d}.jpg'
        h=html(typ,head,line,i,bg); hp=html_dir/f'scene_{i:02d}.html'; hp.write_text(h,encoding='utf-8')
        fd=frames/f'scene_{i:02d}'; fd.mkdir()
        with sync_playwright() as pw:
            b=pw.chromium.launch(headless=True,args=['--no-sandbox']); page=b.new_page(viewport={'width':1080,'height':1920})
            page.goto('file://'+str(hp)); total=max(1,math.ceil(d*12))
            for n in range(total): page.evaluate(f'renderFrame({n/12})'); page.screenshot(path=str(fd/f'f_{n:04d}.png'))
            b.close()
        raw=clips/f'v_{i:02d}.mp4'; audio=clips/f'a_{i:02d}.mp4'; clip=clips/f'c_{i:02d}.mp4'
        sh(['ffmpeg','-y','-v','error','-framerate','12','-i',str(fd/'f_%04d.png'),'-c:v','libx264','-preset','fast','-crf','22','-profile:v','baseline','-pix_fmt','yuv420p','-t',f'{d:.3f}',str(raw)])
        sh(['ffmpeg','-y','-v','error','-i',str(raw),'-i',str(tts),'-c:v','copy','-c:a','aac','-ar','44100','-ac','2','-shortest',str(audio)])
        # add audio clip as the clip source; video and audio are already muxed
        shutil.copy2(audio,clip)
    concat=clips/'concat.txt'; concat.write_text('\n'.join(f"file '{clips/f'c_{i:02d}.mp4'}'" for i in range(1,9)))
    joined=OUT/'v7_joined.mp4'; mixed=OUT/'v7_mixed.mp4'; final=OUT/'final_v7.mp4'
    sh(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(joined)])
    total=sum(durations)
    sh(['ffmpeg','-y','-v','error','-i',str(joined),'-stream_loop','-1','-i',str(BGM),'-filter_complex','[0:a]volume=2.0[v];[1:a]volume=0.18[b];[v][b]amix=inputs=2:duration=first:normalize=0[a]','-map','0:v','-map','[a]','-t',f'{total:.3f}','-c:v','copy','-c:a','aac','-ar','44100','-ac','2','-b:a','128k',str(mixed)])
    # Keep the new renderer's text inside the frames; add only a small lower-third timestamp-safe caption layer from existing subtitle files.
    sh(['ffmpeg','-y','-v','error','-i',str(mixed),'-c:v','copy','-c:a','copy','-movflags','+faststart',str(final)])
    print(json.dumps({'ok':True,'output':str(final),'duration':total,'scenes':8,'renderer':'independent_scene_html_v7'},ensure_ascii=False))
if __name__=='__main__': main()
