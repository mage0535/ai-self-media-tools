import base64
import json
import os
import re
import subprocess
from pathlib import Path

# Paths
BASE_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1')
CUSTOM_DIR = BASE_DIR / 'custom_render'
HTML_DIR = CUSTOM_DIR / 'html'
HTML_DIR.mkdir(parents=True, exist_ok=True)

# 8 Background images from 20260921
BG_DIR = Path('/root/.ai-self-media-tools/data/runs/douyin_ai/20260921_wechat_voice_dialogue_r1/backgrounds')

def get_b64(path):
    return base64.b64encode(path.read_bytes()).decode('utf-8')

# Custom CSS for Workplace Live Dialogue
custom_css = """
* { box-sizing: border-box; }
html, body {
    margin: 0; padding: 0;
    width: 720px; height: 1280px;
    overflow: hidden;
    background: #0b0f19;
    color: #f8fafc;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
}
body { position: relative; }

.bg-layer {
    position: absolute; inset: 0; z-index: 0;
    background-size: cover; background-position: center;
    filter: brightness(0.40) saturate(1.15) contrast(1.1);
}
.grid-overlay {
    position: absolute; inset: 0; z-index: 1;
    background-image: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
    background-size: 36px 36px;
    pointer-events: none;
}
.vignette {
    position: absolute; inset: 0; z-index: 2;
    background: radial-gradient(circle at center, transparent 35%, rgba(4, 8, 16, 0.85) 100%);
    pointer-events: none;
}

/* Header Hook */
.header-bar {
    position: absolute; top: 40px; left: 36px; right: 36px; z-index: 10;
}
.kicker-row {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 8px;
}
.kicker-tag {
    font-size: 19px; font-weight: 900; letter-spacing: 1.5px;
    color: #ffd166; text-transform: uppercase;
    display: flex; align-items: center; gap: 6px;
}
.rec-badge {
    background: rgba(239, 68, 68, 0.25); border: 1px solid #ef4444;
    color: #fca5a5; font-size: 16px; font-weight: 800;
    padding: 3px 10px; border-radius: 999px;
}
.main-title {
    font-size: 38px; line-height: 1.25; font-weight: 950;
    color: #ffffff; text-shadow: 0 4px 16px rgba(0,0,0,0.9);
    border-left: 6px solid #ffd166; padding-left: 14px;
}

/* Main Center Card */
.card-container {
    position: absolute; top: 175px; left: 32px; right: 32px; z-index: 10;
    background: rgba(13, 18, 30, 0.88);
    backdrop-filter: blur(20px);
    border: 2px solid rgba(255, 255, 255, 0.14);
    border-radius: 20px;
    padding: 20px 22px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7);
}

/* Speaker Bar */
.speaker-bar {
    display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
}
.avatar {
    width: 48px; height: 48px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px; font-weight: 900; color: #fff;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
.lin-avatar { background: linear-gradient(135deg, #f43f5e, #fb7185); }
.zhang-avatar { background: linear-gradient(135deg, #0ea5e9, #38bdf8); }
.speaker-meta { flex: 1; }
.speaker-name { font-size: 22px; font-weight: 900; color: #fff; line-height: 1.2; }
.speaker-role { font-size: 15px; color: #94a3b8; font-weight: 600; }
.status-pill {
    padding: 5px 14px; border-radius: 999px; font-size: 16px; font-weight: 800;
}
.status-pill.panic { background: rgba(244, 63, 94, 0.2); color: #fda4af; border: 1px solid #f43f5e; }
.status-pill.solve { background: rgba(14, 165, 233, 0.2); color: #7dd3fc; border: 1px solid #0ea5e9; }
.status-pill.pass { background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid #10b981; }

/* Custom Content Blocks */
.content-box {
    display: flex; flex-direction: column; gap: 12px;
}

.wechat-voice-group {
    display: flex; gap: 8px; justify-content: space-between;
}
.voice-capsule {
    flex: 1; background: rgba(34, 197, 94, 0.22);
    border: 1.5px solid #22c55e; border-radius: 12px;
    padding: 10px 8px; text-align: center;
    font-size: 16px; font-weight: 800; color: #86efac;
    display: flex; align-items: center; justify-content: center; gap: 6px;
}
.voice-capsule .dot { width: 8px; height: 8px; background: #ef4444; border-radius: 50%; }

.narrative-block {
    background: rgba(255, 255, 255, 0.06);
    border-left: 5px solid #ffd166; border-radius: 10px;
    padding: 12px 14px;
}
.narrative-block strong { display: block; font-size: 22px; color: #ffd166; margin-bottom: 4px; }
.narrative-block span { display: block; font-size: 17px; color: #cbd5e1; line-height: 1.35; }

.compare-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
}
.compare-cell {
    padding: 12px; border-radius: 10px;
}
.compare-cell.bad { background: rgba(239, 68, 68, 0.18); border-left: 4px solid #ef4444; }
.compare-cell.good { background: rgba(16, 185, 129, 0.18); border-left: 4px solid #10b981; }
.compare-cell b { display: block; font-size: 18px; margin-bottom: 4px; color: #fff; }
.compare-cell span { font-size: 15px; color: #cbd5e1; line-height: 1.3; }

.code-prompt-box {
    background: #040812; border: 1.5px solid #38bdf8;
    border-radius: 12px; padding: 12px 14px;
    font-family: monospace; font-size: 16px; color: #38bdf8; line-height: 1.5;
}
.code-prompt-box .highlight { color: #fde047; font-weight: bold; }

.sop-checklist {
    display: flex; flex-direction: column; gap: 8px;
}
.sop-row {
    background: rgba(255, 255, 255, 0.07); border-left: 5px solid #10b981;
    border-radius: 8px; padding: 10px 14px;
    display: flex; justify-content: space-between; align-items: center;
}
.sop-row b { font-size: 18px; color: #6ee7b7; }
.sop-row span { font-size: 15px; color: #cbd5e1; }

.cta-banner {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.3), rgba(245, 158, 11, 0.3));
    border: 1.5px solid #f59e0b; border-radius: 12px;
    padding: 14px; text-align: center;
}
.cta-banner b { display: block; font-size: 22px; color: #ffd166; margin-bottom: 4px; }
.cta-banner span { font-size: 16px; color: #fef08a; }

/* Subtitle Safe Bottom Region (top 175px + card height ~480px = 655px; bottom is free from 680px to 1280px) */
"""

# 8 Scenes Data
scenes_data = [
    # Scene 1: 小林 抓狂
    {
        'bg': 'bg_01.jpg',
        'kicker': '【小林 · 紧急求助】',
        'title': '千万别直接让AI写方案！汇报当场翻车',
        'speaker': '小林', 'avatar_cls': 'lin-avatar', 'avatar_txt': '林',
        'role': '职场新人', 'status_cls': 'panic', 'status_txt': '崩溃求助',
        'content_A': """
            <div class="wechat-voice-group">
                <div class="voice-capsule"><span class="dot"></span> 5000字方案</div>
                <div class="voice-capsule"><span class="dot"></span> 耗时3分钟</div>
                <div class="voice-capsule"><span class="dot"></span> 汇报当场翻车</div>
            </div>
            <div class="narrative-block">
                <strong>张哥救命！汇报被追问数据出处，当场崩溃！</strong>
                <span>兴冲冲交了AI生成的方案，领导一问行业预测出处，发现全是模型编的！</span>
            </div>
            <div class="compare-cell bad">
                <b>❌ 致命盲区</b><span>把AI生成的假数据直接当结论汇报，当场穿帮！</span>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>3分钟出的5000字方案，全是虚假繁荣！</strong>
                <span>看似框架完整、辞藻华丽，关键数据经不起哪怕一次推敲追问。</span>
            </div>
            <div class="compare-grid">
                <div class="compare-cell bad"><b>AI直出方案</b><span>文字自信，数据全凭虚构</span></div>
                <div class="compare-cell good"><b>真实业务底线</b><span>每条数据必须有据可查</span></div>
            </div>
        """
    },
    # Scene 2: 老张 原理
    {
        'bg': 'bg_02.jpg',
        'kicker': '【老张 · 盲区拆解】',
        'title': '直接让它写不出事才怪！大模型本质是概率推测',
        'speaker': '老张', 'avatar_cls': 'zhang-avatar', 'avatar_txt': '张',
        'role': '资深架构师', 'status_cls': 'solve', 'status_txt': '深度拆解',
        'content_A': """
            <div class="narrative-block">
                <strong>你直接让它写，不出事才怪！</strong>
                <span>大模型本质是文字概率推测工具，它为了讨好你，会生成话术级的自信。</span>
            </div>
            <div class="compare-cell bad">
                <b>⚠️ 核心真相</b><span>大模型不是数据库，没有外部信源时，年份与案例全凭文字接龙编造！</span>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>话术级自信 vs 真实事实索引</strong>
                <span>没有事实锚点，大模型生成的内容越长，混入的虚假幻觉数据就越多。</span>
            </div>
            <div class="compare-grid">
                <div class="compare-cell bad"><b>致命误区</b><span>把大模型当做事实搜索引擎</span></div>
                <div class="compare-cell good"><b>正确认知</b><span>大模型是语言组织与排版引擎</span></div>
            </div>
        """
    },
    # Scene 3: 小林 启发
    {
        'bg': 'bg_03.jpg',
        'kicker': '【小林 · 方案请教】',
        'title': '难怪查不到出处！到底怎么让AI干活才不翻车？',
        'speaker': '小林', 'avatar_cls': 'lin-avatar', 'avatar_txt': '林',
        'role': '职场新人', 'status_cls': 'panic', 'status_txt': '认真求招',
        'content_A': """
            <div class="narrative-block">
                <strong>难怪领导一查查不到出处！</strong>
                <span>那平时写商业方案、做行业分析，到底该怎么给指令才不会翻车？</span>
            </div>
            <div class="compare-cell good">
                <b>💡 核心诉求</b><span>不要虚假幻觉，只要可查证、可交付的严谨内容！</span>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>求老张传授3套真正可落地的防翻车实操！</strong>
                <span>如何在保证AI高效产出的同时，彻底锁死事实准确率？</span>
            </div>
            <div class="sop-checklist">
                <div class="sop-row"><b>第1招</b><span>锁死真实信源材料</span></div>
                <div class="sop-row"><b>第2招</b><span>强制核心结论标注出处</span></div>
            </div>
        """
    },
    # Scene 4: 老张 第1招
    {
        'bg': 'bg_04.jpg',
        'kicker': '【老张 · 第1招】',
        'title': '第1招：锁死信源！不给材料绝不让AI乱猜',
        'speaker': '老张', 'avatar_cls': 'zhang-avatar', 'avatar_txt': '张',
        'role': '资深架构师', 'status_cls': 'solve', 'status_txt': '指令锁死',
        'content_A': """
            <div class="narrative-block">
                <strong>第1招锁死信源：指令开头必须加硬性约束！</strong>
                <span>“仅基于我给的材料总结，材料未提及的直接回答不知道”。</span>
            </div>
            <div class="code-prompt-box">
                <div>PROMPT约束模板：</div>
                <div class="highlight">【仅基于下述业务材料分析，严禁发散推断，未提及内容严禁编造】</div>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>从源头切断AI的胡说概率！</strong>
                <span>不给真实资料，坚决不让AI开工。输入真实，输出才可能严谨。</span>
            </div>
            <div class="compare-grid">
                <div class="compare-cell bad"><b>错误指令</b><span>帮我写一份2026行业方案</span></div>
                <div class="compare-cell good"><b>满分指令</b><span>基于附件这篇白皮书提炼结论</span></div>
            </div>
        """
    },
    # Scene 5: 老张 第2招
    {
        'bg': 'bg_05.jpg',
        'kicker': '【老张 · 第2招】',
        'title': '第2招：强制标注出处！查不到来源直接剔除',
        'speaker': '老张', 'avatar_cls': 'zhang-avatar', 'avatar_txt': '张',
        'role': '资深架构师', 'status_cls': 'solve', 'status_txt': '出处核对',
        'content_A': """
            <div class="narrative-block">
                <strong>第2招强制标注出处：每句结论必须带证据！</strong>
                <span>核心结论后面必须打括号指明引用的原文段落或具体数据行。</span>
            </div>
            <div class="code-prompt-box">
                <div>输出规范规则：</div>
                <div class="highlight">[核心结论] + (引用段落编号/原始报表单元格)</div>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>建立严格的事实回溯机制！</strong>
                <span>自己先看一遍括号里的来源，查不到明确出处的数据，直接一键剔除！</span>
            </div>
            <div class="compare-grid">
                <div class="compare-cell bad"><b>无源幻觉</b><span>行业增长率预计达45%（虚构）</span></div>
                <div class="compare-cell good"><b>带出处核验</b><span>增长率12.5%（见财报第18页）</span></div>
            </div>
        """
    },
    # Scene 6: 老张 第3招
    {
        'bg': 'bg_06.jpg',
        'kicker': '【老张 · 第3招】',
        'title': '第3招：骨肉分离！AI排版润色，人审核心数据',
        'speaker': '老张', 'avatar_cls': 'zhang-avatar', 'avatar_txt': '张',
        'role': '资深架构师', 'status_cls': 'solve', 'status_txt': '分工防线',
        'content_A': """
            <div class="narrative-block">
                <strong>第3招骨肉分离：人机分工绝不越界！</strong>
                <span>让AI干排版整理、文字润色的体力活，关键决策和核心数据必须人工复核。</span>
            </div>
            <div class="compare-grid">
                <div class="compare-cell good"><b>AI管“肉”</b><span>润色行文、调整格式、提炼要点</span></div>
                <div class="compare-cell bad"><b>人把“骨”</b><span>把控核心逻辑、核对关键金额与死线</span></div>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>永远不要让人工终审缺位！</strong>
                <span>工具只负责放大生产力，最终在方案上签名的永远是活生生的人。</span>
            </div>
            <div class="sop-checklist">
                <div class="sop-row"><b>人工复核</b><span>用时3分钟，核实全部数字真实性</span></div>
                <div class="sop-row"><b>交付安全</b><span>彻底杜绝向领导汇报时的穿帮风险</span></div>
            </div>
        """
    },
    # Scene 7: 小林 总结
    {
        'bg': 'bg_07.jpg',
        'kicker': '【小林 · 价值沉淀】',
        'title': '懂了！锁信源、标出处、人看两头，赶紧存下！',
        'speaker': '小林', 'avatar_cls': 'lin-avatar', 'avatar_txt': '林',
        'role': '职场新人', 'status_cls': 'pass', 'status_txt': '清单已存',
        'content_A': """
            <div class="narrative-block">
                <strong>懂了！锁信源、标出处、人看两头！</strong>
                <span>这套防AI胡说清单太实用了，以后做方案汇报再也不怕被领导问住了！</span>
            </div>
            <div class="sop-checklist">
                <div class="sop-row"><b>原则一</b><span>仅基于真实材料，无依据不发散</span></div>
                <div class="sop-row"><b>原则二</b><span>每处数据带出处，查无来源直接剔除</span></div>
                <div class="sop-row"><b>原则三</b><span>AI排版整理，人工核验两头关键数据</span></div>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>避坑SOP直接封神！</strong>
                <span>一套组合拳把AI从“造假惯犯”改造成“高效率生产力神器”！</span>
            </div>
            <div class="compare-cell good">
                <b>✅ 验收结果</b><span>方案事实准确率100%，职场汇报底气十足！</span>
            </div>
        """
    },
    # Scene 8: 老张 互动
    {
        'bg': 'bg_08.jpg',
        'kicker': '【老张 · 互动福利】',
        'title': '你被AI虚假数据坑过吗？评论区领避坑模板',
        'speaker': '老张', 'avatar_cls': 'zhang-avatar', 'avatar_txt': '张',
        'role': '资深架构师', 'status_cls': 'solve', 'status_txt': '评论互动',
        'content_A': """
            <div class="narrative-block">
                <strong>你在用人工智能写方案时，被编造的数据坑过吗？</strong>
                <span>建议点赞收藏备用，避免下次汇报关键时刻掉链子！</span>
            </div>
            <div class="cta-banner">
                <b>🎁 粉丝专属福利</b>
                <span>评论区回复【防翻车】，免费发你这套万能避坑指令模板！</span>
            </div>
        """,
        'content_B': """
            <div class="narrative-block">
                <strong>欢迎在评论区聊聊你的AI翻车名场面！</strong>
                <span>老张在线为你答疑支招，带你把AI真正变成职场开挂利器！</span>
            </div>
            <div class="cta-banner">
                <b>👇 立即互动领取</b>
                <span>评论区回复【防翻车】，获取完整版防AI幻觉约束词库！</span>
            </div>
        """
    },
]

# Generate HTML for all 16 shots
for idx, scene in enumerate(scenes_data):
    sid = f'shot_{idx+1:02d}'
    bg_path = BG_DIR / scene['bg']
    bg_b64 = get_b64(bg_path)
    
    for suffix, content_frag in [('A', scene['content_A']), ('B', scene['content_B'])]:
        name = f'{sid}{suffix}'
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{custom_css}
</style>
</head>
<body>
    <div class="bg-layer" style="background-image: url('data:image/jpeg;base64,{bg_b64}');"></div>
    <div class="grid-overlay"></div>
    <div class="vignette"></div>
    
    <div class="header-bar">
        <div class="kicker-row">
            <div class="kicker-tag">{scene['kicker']} · AI效率实战</div>
            <div class="rec-badge">● LIVE 00:42</div>
        </div>
        <div class="main-title">{scene['title']}</div>
    </div>
    
    <div class="card-container">
        <div class="speaker-bar">
            <div class="avatar {scene['avatar_cls']}">{scene['avatar_txt']}</div>
            <div class="speaker-meta">
                <div class="speaker-name">{scene['speaker']}</div>
                <div class="speaker-role">{scene['role']}</div>
            </div>
            <div class="status-pill {scene['status_cls']}">{scene['status_txt']}</div>
        </div>
        <div class="content-box">
            {content_frag}
        </div>
    </div>
</body>
</html>
"""
        out_file = HTML_DIR / f'{name}.html'
        out_file.write_text(html_content, encoding='utf-8')
        print(f"Generated {out_file.name}")

print("All 16 custom HTML files generated successfully!")
