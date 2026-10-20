import json, re
from pathlib import Path

run_dir = Path('/root/.ai-self-media-tools/data/runs/douyin_ai/20260921_wechat_voice_dialogue_r1')
html_dir = run_dir / 'html'

dialogue_cards_data = [
    # Scene 1: 小林 抓狂
    {
        'speaker': '小林', 'badge': '职场新人 · 紧急求助', 'tag': '抓狂',
        'title': '连甩5条60秒语音，AI把客套当紧急任务？',
        'kicker': '【小林 · 抓狂求助】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card lin-speaker">
            <div class="speaker-bar"><span class="avatar lin-avatar">林</span><b>小林 (新员工)</b><span class="status-pill panic">崩溃抓狂中</span></div>
            <div class="wechat-bubble incoming-bubble">
                <div class="voice-badge-group">
                    <div class="voice-bubble"><i></i> 60″ 🔴 <b>老板语音 1/5</b></div>
                    <div class="voice-bubble"><i></i> 60″ 🔴 <b>老板语音 2/5</b></div>
                    <div class="voice-bubble"><i></i> 60″ 🔴 <b>老板语音 3/5</b></div>
                </div>
                <div class="bubble-caption">直接转文字扔给AI，居然把随口客套列成了P0级死线待办！</div>
            </div>
            <div class="error-banner">❌ AI把“周五有空看下竞品”当成了紧急需求！</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card lin-speaker">
            <div class="speaker-bar"><span class="avatar lin-avatar">林</span><b>小林 (新员工)</b><span class="status-pill panic">实测翻车</span></div>
            <div class="narrative-copy-custom">
                <strong>微信长语音直接丢给AI？分分钟背大锅！</strong>
                <span>老板随口一句“下周有空把竞品过一下”，AI直接标红加粗排进核心日程。</span>
            </div>
            <div class="comparison-row">
                <div class="box red-box"><b>AI生成结论</b><span>P0紧急待办：周五交付竞品</span></div>
                <div class="box green-box"><b>真实老板意图</b><span>闲聊客套，优先级极低</span></div>
            </div>
        </div>
        """
    },
    # Scene 2: 老张 盲区
    {
        'speaker': '老张', 'badge': '资深架构 · 盲区拆解', 'tag': '沉稳',
        'title': '口水话整段甩过去，不出问题才怪',
        'kicker': '【老张 · 盲区拆解】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill calm">思考分析</span></div>
            <div class="wechat-bubble reply-bubble">
                <div class="quote-box">“你是不是把几百字口水话粘进去，直接敲了一句帮我总结？”</div>
                <div class="bubble-caption">实战复盘这纯属操作盲区：语音转写里满屏“那个、懂吧”，AI连上下文都没有！</div>
            </div>
            <div class="insight-banner">⚠️ 语音识别噪音 + 缺失任务边界 = 大模型无底线幻觉</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill calm">盲区直击</span></div>
            <div class="narrative-copy-custom">
                <strong>口水话直接甩过去，不出问题才怪。</strong>
                <span>大模型只能根据词频概率去猜，输入全是噪音，输出必然是幻觉。</span>
            </div>
            <div class="comparison-row">
                <div class="box red-box"><b>错误姿势</b><span>全选复制 → 帮我整理待办</span></div>
                <div class="box green-box"><b>关键缺失</b><span>时间坐标、责任人、过滤规则</span></div>
            </div>
        </div>
        """
    },
    # Scene 3: 老张 原理
    {
        'speaker': '老张', 'badge': '资深架构 · 原理揭秘', 'tag': '原理',
        'title': '大模型没有物理时间概念',
        'kicker': '【老张 · 原理揭秘】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill tech">核心原理</span></div>
            <div class="calendar-visual">
                <div class="cal-badge">📅 丢失时间锚点</div>
                <div class="cal-diff">
                    <div class="cal-item wrong"><b>老板说的“下周三”</b><span>AI眼中：语料里的任意周三</span></div>
                    <div class="cal-item correct"><b>今天实际日期</b><span>2026年9月21日 星期一</span></div>
                </div>
            </div>
            <div class="insight-banner">💡 大模型没有挂钟，必须显式在提示词注入当前物理时间！</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill tech">物理时间盲区</span></div>
            <div class="narrative-copy-custom">
                <strong>老板说“下周三”，AI上哪知道是哪个周三？</strong>
                <span>未显式传递系统基准日期，AI在推算相对时间时只能瞎蒙。</span>
            </div>
            <div class="comparison-row">
                <div class="box red-box"><b>相对时间</b><span>“大后天”、“下周前”</span></div>
                <div class="box green-box"><b>绝对物理映射</b><span>2026-09-21 ➔ 2026-09-30</span></div>
            </div>
        </div>
        """
    },
    # Scene 4: 小林 核心发难
    {
        'speaker': '小林', 'badge': '职场新人 · 核心发难', 'tag': '痛点',
        'title': '逐字硬听5分钟，到底怎么破？',
        'kicker': '【小林 · 核心发难】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card lin-speaker">
            <div class="speaker-bar"><span class="avatar lin-avatar">林</span><b>小林 (新员工)</b><span class="status-pill panic">灵魂发问</span></div>
            <div class="time-cost-grid">
                <div class="cost-item bad"><b>逐字人工硬听</b><span>耗时 5:00 分钟</span><small>头昏脑涨、效率极低</small></div>
                <div class="cost-item vs">VS</div>
                <div class="cost-item good"><b>结构化AI防漏SOP</b><span>耗时 0:30 秒</span><small>精准提取、稳妥复核</small></div>
            </div>
            <div class="error-banner">到底怎么搞，才能既彻底省时间、又一条都不漏？</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card lin-speaker">
            <div class="speaker-bar"><span class="avatar lin-avatar">林</span><b>小林 (新员工)</b><span class="status-pill panic">痛点碰撞</span></div>
            <div class="narrative-copy-custom">
                <strong>逐字听要听整整5分钟，到底怎么搞？</strong>
                <span>既不能把时间全耗在硬听上，又绝对不敢承担漏事的背锅风险。</span>
            </div>
            <div class="comparison-row">
                <div class="box red-box"><b>痛点 1</b><span>语音信息密度极低</span></div>
                <div class="box green-box"><b>诉求 2</b><span>30秒精准锁定真任务</span></div>
            </div>
        </div>
        """
    },
    # Scene 5: 老张 实操1
    {
        'speaker': '老张', 'badge': '资深架构 · 3步SOP', 'tag': '实操1',
        'title': '第1步：Prompt首行锁死时间锚点',
        'kicker': '【老张 · 实操解法】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill step">保命第 1 步</span></div>
            <div class="code-terminal-box">
                <div class="code-header">Prompt 模板首行 · 强制注入物理坐标</div>
                <pre class="code-body">【系统基准】当前时间：2026年9月21日 星期一
【执行指令】基于此时间锚点，推导语音内所有相对死线
【转化要求】如“下周三”严格换算为“2026-09-30”</pre>
            </div>
            <div class="insight-banner">✅ 锁死基准坐标，时间推理准确率直接提升到 100%！</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill step">时间锚点实操</span></div>
            <div class="narrative-copy-custom">
                <strong>首行写入当前日期：2026年9月21日。</strong>
                <span>给大模型一个物理世界坐标系，所有“后天、下周”自动精准映射。</span>
            </div>
            <div class="comparison-row">
                <div class="box green-box"><b>规则生效</b><span>相对时间一律转绝对年月日</span></div>
                <div class="box green-box"><b>避免歧义</b><span>消除跨周跨月时间错位</span></div>
            </div>
        </div>
        """
    },
    # Scene 6: 老张 实操2
    {
        'speaker': '老张', 'badge': '资深架构 · 3步SOP', 'tag': '实操2',
        'title': '第2步：强制三要素过滤噪音',
        'kicker': '【老张 · 结构提取】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill step">保命第 2 步</span></div>
            <div class="three-elements-table">
                <div class="table-row head"><span>责任人 (Who)</span><span>死线 (When)</span><span>交付标准 (What)</span></div>
                <div class="table-row valid"><span>小林</span><span>09-23 18:00</span><span>客户方案终版PPT</span></div>
                <div class="table-row pending"><span>待定 (客套话)</span><span>无明确死线</span><span>“有空看下竞品”(过滤)</span></div>
            </div>
            <div class="insight-banner">🎯 凡是“再看看、放一放”，强制打上待定，降低误差！</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill step">结构化清洗</span></div>
            <div class="narrative-copy-custom">
                <strong>只抓责任人、截止时间、交付标准。</strong>
                <span>三要素缺一不可，客套话与摸棱两可讨论强制打标“待定”。</span>
            </div>
            <div class="comparison-row">
                <div class="box green-box"><b>真需求</b><span>三要素齐全 ➔ 进正式清单</span></div>
                <div class="box red-box"><b>假需求</b><span>要素缺失 ➔ 自动隔离过滤</span></div>
            </div>
        </div>
        """
    },
    # Scene 7: 老张 实操3
    {
        'speaker': '老张', 'badge': '资深架构 · 3步SOP', 'tag': '实操3',
        'title': '第3步：1.5倍速原声30秒倒查复核',
        'kicker': '【老张 · 人工防线】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill audit">保命第 3 步</span></div>
            <div class="waveform-box">
                <div class="wave-header">微信语音条 · 1.5X 倒查复核</div>
                <div class="wave-body">
                    <div class="wave-track"><span></span><span></span><span></span><span></span><span></span><span></span></div>
                    <div class="wave-speed">1.5X 倍速</div>
                </div>
                <div class="audit-stamp">人工终审 · APPROVED</div>
            </div>
            <div class="insight-banner">🛡️ 别全信AI！花30秒人工倒查关键数字与死线，再发工作群！</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card zhang-speaker">
            <div class="speaker-bar"><span class="avatar zhang-avatar">张</span><b>老张 (资深架构)</b><span class="status-pill audit">人工底线防线</span></div>
            <div class="narrative-copy-custom">
                <strong>严禁盲目甩给工作群，双人核对核心事实。</strong>
                <span>用1.5倍速倒查原语音的核心事实，核对无误再行分发。</span>
            </div>
            <div class="comparison-row">
                <div class="box green-box"><b>30秒人工抽检</b><span>责任人、截止日期、关键数字</span></div>
                <div class="box green-box"><b>免责闭环</b><span>可信留痕，万无一失</span></div>
            </div>
        </div>
        """
    },
    # Scene 8: 双人 互动
    {
        'speaker': '双人', 'badge': '职场效率 · 互动闭环', 'tag': '互动',
        'title': '微信长语音防漏待办SOP清单',
        'kicker': '【双人 · 避坑互动】',
        'html_A': """
        <div class="industrial-overlay wechat-dialogue-card both-speaker">
            <div class="speaker-bar"><span class="avatar lin-avatar">林</span><span class="avatar zhang-avatar" style="margin-left:-8px;">张</span><b>小林 &amp; 老张</b><span class="status-pill cta">总结收藏</span></div>
            <div class="sop-summary-card">
                <div class="sop-item"><b>1. 锁定时间锚点</b><span>首行注入今天物理日期</span></div>
                <div class="sop-item"><b>2. 强制三要素表</b><span>责任人+死线+交付指标</span></div>
                <div class="sop-item"><b>3. 30秒1.5X复核</b><span>原声倒查关键事实再发群</span></div>
            </div>
            <div class="cta-discuss-banner">💬 你收到过最长的一条微信语音是多少秒？在评论区聊聊！</div>
        </div>
        """,
        'html_B': """
        <div class="industrial-overlay wechat-dialogue-card both-speaker">
            <div class="speaker-bar"><span class="avatar lin-avatar">林</span><span class="avatar zhang-avatar" style="margin-left:-8px;">张</span><b>小林 &amp; 老张</b><span class="status-pill cta">促发收藏</span></div>
            <div class="narrative-copy-custom">
                <strong>先收藏这份长语音防漏SOP清单！</strong>
                <span>下次收到老板连环60秒语音，照着这3步做，绝不背锅！</span>
            </div>
            <div class="comparison-row">
                <div class="box green-box"><b>点击收藏</b><span>随用随取防漏模板</span></div>
                <div class="box green-box"><b>评论区互动</b><span>分享你的窒息语音瞬间</span></div>
            </div>
        </div>
        """
    }
]

custom_css = """
/* WeChat Dialogue Custom Styling */
.wechat-dialogue-card {
    position: absolute;
    left: 36px;
    right: 36px;
    top: 420px;
    background: rgba(14, 23, 38, 0.92);
    border: 2px solid rgba(255, 209, 102, 0.45);
    border-radius: 20px;
    box-shadow: 0 16px 40px rgba(0,0,0,0.6);
    padding: 24px 22px;
    backdrop-filter: blur(12px);
    box-sizing: border-box;
}
.speaker-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    border-bottom: 1px solid rgba(255,255,255,0.15);
    padding-bottom: 12px;
}
.speaker-bar .avatar {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    font-weight: 900;
    color: #fff;
}
.lin-avatar { background: #ff5e62; border: 2px solid #ff9966; }
.zhang-avatar { background: #00b09b; border: 2px solid #96c93d; }
.speaker-bar b { font-size: 26px; color: #fff; font-weight: 800; }
.status-pill {
    margin-left: auto;
    font-size: 18px;
    font-weight: 700;
    padding: 4px 12px;
    border-radius: 12px;
}
.status-pill.panic { background: rgba(255, 94, 98, 0.25); color: #ff8585; border: 1px solid #ff5e62; }
.status-pill.calm { background: rgba(0, 176, 155, 0.25); color: #52e5d5; border: 1px solid #00b09b; }
.status-pill.tech { background: rgba(98, 216, 255, 0.25); color: #62d8ff; border: 1px solid #62d8ff; }
.status-pill.step { background: rgba(255, 209, 102, 0.25); color: #ffd166; border: 1px solid #ffd166; }
.status-pill.audit { background: rgba(114, 230, 165, 0.25); color: #72e6a5; border: 1px solid #72e6a5; }
.status-pill.cta { background: rgba(255, 209, 102, 0.3); color: #ffd166; border: 1px solid #ffd166; }

.voice-badge-group {
    display: flex;
    gap: 10px;
    margin-bottom: 14px;
}
.voice-bubble {
    background: #07c160;
    color: #fff;
    padding: 8px 14px;
    border-radius: 16px;
    font-size: 20px;
    font-weight: 800;
    display: flex;
    align-items: center;
    gap: 6px;
}
.bubble-caption {
    font-size: 22px;
    line-height: 1.4;
    color: #e2e8f0;
    margin-bottom: 12px;
}
.error-banner {
    background: rgba(224, 72, 58, 0.25);
    border-left: 6px solid #e0483a;
    padding: 10px 14px;
    font-size: 20px;
    color: #ff9999;
    font-weight: 700;
    border-radius: 4px;
}
.insight-banner {
    background: rgba(255, 209, 102, 0.18);
    border-left: 6px solid #ffd166;
    padding: 10px 14px;
    font-size: 20px;
    color: #ffe699;
    font-weight: 700;
    border-radius: 4px;
}
.quote-box {
    background: rgba(255, 255, 255, 0.08);
    border-left: 4px solid #62d8ff;
    padding: 10px 14px;
    font-size: 22px;
    color: #62d8ff;
    font-style: italic;
    margin-bottom: 10px;
    border-radius: 4px;
}
.calendar-visual {
    background: rgba(0, 0, 0, 0.3);
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 12px;
}
.cal-badge { font-size: 20px; color: #ffd166; font-weight: 800; margin-bottom: 8px; }
.cal-diff { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.cal-item { padding: 10px; border-radius: 8px; font-size: 19px; }
.cal-item.wrong { background: rgba(224, 72, 58, 0.2); border-left: 4px solid #e0483a; }
.cal-item.correct { background: rgba(49, 173, 105, 0.2); border-left: 4px solid #31ad69; }
.cal-item b { display: block; font-size: 19px; margin-bottom: 4px; }
.cal-item span { font-size: 17px; color: #cbd5e1; }

.time-cost-grid {
    display: grid;
    grid-template-columns: 1fr 40px 1fr;
    align-items: center;
    gap: 8px;
    margin-bottom: 14px;
}
.cost-item { padding: 12px 10px; border-radius: 8px; text-align: center; }
.cost-item.bad { background: rgba(224, 72, 58, 0.2); border: 2px solid #e0483a; }
.cost-item.good { background: rgba(49, 173, 105, 0.2); border: 2px solid #31ad69; }
.cost-item.vs { font-size: 24px; font-weight: 900; color: #ffd166; }
.cost-item b { display: block; font-size: 20px; margin-bottom: 4px; }
.cost-item span { display: block; font-size: 24px; font-weight: 900; color: #ffd166; }
.cost-item small { font-size: 16px; color: #cbd5e1; }

.code-terminal-box {
    background: #020810;
    border: 1px solid #62d8ff;
    border-radius: 10px;
    padding: 12px;
    margin-bottom: 12px;
}
.code-header { font-size: 18px; color: #62d8ff; font-weight: 800; margin-bottom: 6px; }
.code-body { margin: 0; font-family: monospace; font-size: 18px; line-height: 1.35; color: #72e6a5; white-space: pre-wrap; }

.three-elements-table {
    display: grid;
    grid-template-rows: auto auto auto;
    gap: 6px;
    margin-bottom: 12px;
}
.table-row {
    display: grid;
    grid-template-columns: 1.1fr 1.1fr 1.3fr;
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 18px;
    align-items: center;
}
.table-row.head { background: rgba(255, 255, 255, 0.12); font-weight: 800; color: #ffd166; }
.table-row.valid { background: rgba(49, 173, 105, 0.25); border-left: 4px solid #31ad69; color: #fff; }
.table-row.pending { background: rgba(255, 209, 102, 0.18); border-left: 4px solid #ffd166; color: #cbd5e1; }

.waveform-box {
    background: rgba(0, 0, 0, 0.35);
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 12px;
}
.wave-header { font-size: 19px; color: #ffd166; font-weight: 800; margin-bottom: 8px; }
.wave-body { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.wave-track { display: flex; gap: 4px; align-items: flex-end; height: 36px; }
.wave-track span { width: 6px; background: #07c160; border-radius: 3px; }
.wave-track span:nth-child(1) { height: 16px; }
.wave-track span:nth-child(2) { height: 32px; }
.wave-track span:nth-child(3) { height: 24px; }
.wave-track span:nth-child(4) { height: 36px; }
.wave-track span:nth-child(5) { height: 28px; }
.wave-track span:nth-child(6) { height: 20px; }
.wave-speed { font-size: 26px; font-weight: 900; color: #72e6a5; background: rgba(114, 230, 165, 0.2); padding: 4px 12px; border-radius: 8px; }
.audit-stamp {
    font-size: 22px;
    font-weight: 900;
    color: #72e6a5;
    border: 2px dashed #72e6a5;
    padding: 6px 12px;
    display: inline-block;
    border-radius: 6px;
    transform: rotate(-2deg);
}

.sop-summary-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 12px;
}
.sop-item {
    background: rgba(255, 255, 255, 0.08);
    border-left: 5px solid #ffd166;
    padding: 8px 12px;
    border-radius: 4px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 19px;
}
.sop-item b { color: #ffd166; }
.sop-item span { color: #cbd5e1; font-size: 17px; }
.cta-discuss-banner {
    background: linear-gradient(90deg, rgba(255, 209, 102, 0.3), rgba(255, 94, 98, 0.3));
    border: 1px solid #ffd166;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 20px;
    color: #fff;
    font-weight: 800;
    text-align: center;
}

.narrative-copy-custom {
    background: rgba(8, 12, 18, 0.75);
    border-left: 7px solid #ffd166;
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 14px;
}
.narrative-copy-custom strong { display: block; font-size: 25px; color: #ffd166; margin-bottom: 6px; }
.narrative-copy-custom span { display: block; font-size: 20px; color: #e2e8f0; line-height: 1.35; }
.comparison-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.comparison-row .box { padding: 12px; border-radius: 8px; font-size: 18px; }
.comparison-row .red-box { background: rgba(224, 72, 58, 0.2); border-left: 4px solid #e0483a; }
.comparison-row .green-box { background: rgba(49, 173, 105, 0.2); border-left: 4px solid #31ad69; }
.comparison-row b { display: block; font-size: 19px; margin-bottom: 4px; color: #fff; }
.comparison-row span { font-size: 17px; color: #cbd5e1; }
"""

for idx, data in enumerate(dialogue_cards_data):
    s_id = f'shot_0{idx+1}'
    for suffix, html_frag in [('A', data['html_A']), ('B', data['html_B'])]:
        file_path = html_dir / f'{s_id}{suffix}.html'
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding='utf-8')
        
        # Replace whatever is inside <div class="content" ...> with html_frag
        content = re.sub(
            r'(<div class="content"[^>]*>).*?(<div class="contract-execution">|<script>)',
            r'\1' + html_frag + r'\2',
            content,
            flags=re.DOTALL
        )
        
        if '/* WeChat Dialogue Custom Styling */' not in content:
            content = content.replace('</style>', f'{custom_css}\n</style>')
            
        file_path.write_text(content, encoding='utf-8')
        print(f'Successfully updated {file_path.name}!')
