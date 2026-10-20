import asyncio
import json
import subprocess
from pathlib import Path
import edge_tts

AUDIO_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_v2/audio')
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# 7 High-Tension, Natural Human Developer Beats (Compact & Punchy, total ~50s)
BEATS = [
    {
        'id': 's01',
        'eyebrow': '01 / 职场翻车现场',
        'title': '为什么AI写方案一问就穿帮？',
        'mode': 'split',
        'q_speaker': '工程师',
        'q_text': '老张，我用大模型写的方案，开会被抓到假数据，太尴尬了！',
        'a_speaker': '架构师',
        'a_text': '踩到幻觉的坑了！大模型没给依据，它就会一本正经地瞎编。',
        'q_voice': 'zh-CN-YunxiNeural',
        'q_rate': '+8%',
        'a_voice': 'zh-CN-YunyangNeural',
        'a_rate': '+5%',
        'card_data': {
            'tag': '认知纠偏',
            'headline': '直接要方案 = 默认允许模型脑补',
            'desc': '大模型是概率续写并非事实检索，没有边界约束必定随机胡说。'
        }
    },
    {
        'id': 's02',
        'eyebrow': '02 / 本质认知',
        'title': '转变思路：不做生成，只做提炼',
        'mode': 'mindset',
        'q_speaker': '工程师',
        'q_text': '我看它条理挺顺，怎么里面核心数字全是编的？',
        'a_speaker': '架构师',
        'a_text': '绝不能直接向它“要方案”，而是要喂入真实材料让它“做提炼”。',
        'q_voice': 'zh-CN-YunxiNeural',
        'q_rate': '+8%',
        'a_voice': 'zh-CN-YunyangNeural',
        'a_rate': '+5%',
        'card_data': {
            'wrong': '✕ 直接下令：“帮我写一份5000字行业分析方案”',
            'right': '✓ 约束执行：“基于我上传的3篇财报，做横向数据提炼”'
        }
    },
    {
        'id': 's03',
        'eyebrow': '03 / 避坑第1招',
        'title': '锁死信源：没给的数据坚决不准写',
        'mode': 'lock_source',
        'q_speaker': '工程师',
        'q_text': '那第一步具体该怎么做？怎么防它乱猜？',
        'a_speaker': '架构师',
        'a_text': '第一条叫锁死信源：把真实材料喂给它，明确命令没给的一律不准写。',
        'q_voice': 'zh-CN-YunxiNeural',
        'q_rate': '+8%',
        'a_voice': 'zh-CN-YunyangNeural',
        'a_rate': '+5%',
        'card_data': {
            'step': '01',
            'name': '锁死真实信源 (Grounding)',
            'rule': '严禁超出给定上下文！未出现的数据直接填“未提及”，杜绝脑补。'
        }
    },
    {
        'id': 's04',
        'eyebrow': '04 / 避坑第2招',
        'title': '强制标注出处：结论必须挂钩原文',
        'mode': 'cite_source',
        'q_speaker': '工程师',
        'q_text': '那它推导出来的结论，又该怎么快速核实？',
        'a_speaker': '架构师',
        'a_text': '第二条叫强制标注出处：每条结论后括号注明原文段落，查不到直接剔除。',
        'q_voice': 'zh-CN-YunxiNeural',
        'q_rate': '+8%',
        'a_voice': 'zh-CN-YunyangNeural',
        'a_rate': '+5%',
        'card_data': {
            'step': '02',
            'name': '结论引用溯源 (Citation)',
            'rule': '每一条论断末尾标注 [出处: 文件A 第3节]，随时可人工回溯核验。'
        }
    },
    {
        'id': 's05',
        'eyebrow': '05 / 避坑第3招',
        'title': '骨肉分离：AI负责排版，人工死守数据',
        'mode': 'separate',
        'q_speaker': '工程师',
        'q_text': '明白了！那整篇方案的核心架构该怎么把控？',
        'a_speaker': '架构师',
        'a_text': '第三条叫骨肉分离：让AI负责文字排版润色，核心数据你自己死守。',
        'q_voice': 'zh-CN-YunxiNeural',
        'q_rate': '+8%',
        'a_voice': 'zh-CN-YunyangNeural',
        'a_rate': '+5%',
        'card_data': {
            'step': '03',
            'name': '人机骨肉分离 (Separation)',
            'ai_role': '🤖 AI：框架搭建、遣词造句、逻辑润色、格式排版',
            'human_role': '🧑 人工：业务指标、关键数据、结论定夺、终审签署'
        }
    },
    {
        'id': 's06',
        'eyebrow': '06 / 实战清单',
        'title': '方案交付前 4 步防翻车核对清单',
        'mode': 'checklist',
        'q_speaker': '工程师',
        'q_text': '这3招太实用了！交付前怎么快速自检？',
        'a_speaker': '架构师',
        'a_text': '记住这4步：查信源、查出处、查边界、查数据，核对完再交差。',
        'q_voice': 'zh-CN-YunxiNeural',
        'q_rate': '+8%',
        'a_voice': 'zh-CN-YunyangNeural',
        'a_rate': '+5%',
        'card_data': {
            'items': [
                ('1. 查信源', '是否只用了真实可靠材料'),
                ('2. 查出处', '每个关键指标是否有据可查'),
                ('3. 查边界', '有无超出给定的业务范畴'),
                ('4. 查数据', '人工核对总计与环比准确性')
            ]
        }
    },
    {
        'id': 's07',
        'eyebrow': '07 / 互动行动',
        'title': '把AI真正变成靠谱的生产力',
        'mode': 'action',
        'q_speaker': '工程师',
        'q_text': '赶紧存下了！哪里还能学更多避坑实战？',
        'a_speaker': '架构师',
        'a_text': '快手关注我，带你掌握可落地的效率工程。你方案翻过车吗？评论区聊聊！',
        'q_voice': 'zh-CN-YunxiNeural',
        'q_rate': '+8%',
        'a_voice': 'zh-CN-YunyangNeural',
        'a_rate': '+5%',
        'card_data': {
            'cta_title': '快手关注「magic」',
            'cta_sub': '持续更新 AI 效率工程 · 真实避坑实战',
            'prompt_tip': '评论区回复【防翻车】，获取完整版大模型约束提示词模版'
        }
    }
]

async def generate_single(text: str, voice: str, rate: str, out_path: Path):
    comm = edge_tts.Communicate(text, voice, rate=rate)
    await comm.save(str(out_path))

def get_duration(p: Path) -> float:
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(p)]
    return float(subprocess.check_output(cmd, text=True).strip())

async def main():
    silence_path = AUDIO_DIR / 'silence_200ms.mp3'
    subprocess.run([
        'ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
        '-t', '0.20', '-q:a', '9', '-acodec', 'libmp3lame', str(silence_path)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    records = []
    total_time = 0.0
    
    print("=== Generating Natural Human Dialogue TTS (7 Beats) ===")
    for b in BEATS:
        bid = b['id']
        q_path = AUDIO_DIR / f'{bid}_q.mp3'
        a_path = AUDIO_DIR / f'{bid}_a.mp3'
        seg_tts = AUDIO_DIR / f'{bid}_dialogue.mp3'
        
        await generate_single(b['q_text'], b['q_voice'], b['q_rate'], q_path)
        await generate_single(b['a_text'], b['a_voice'], b['a_rate'], a_path)
        
        dur_q = get_duration(q_path)
        dur_a = get_duration(a_path)
        
        concat_list = AUDIO_DIR / f'{bid}_concat.txt'
        concat_list.write_text(f"file '{q_path.name}'\nfile '{silence_path.name}'\nfile '{a_path.name}'\n", encoding='utf-8')
        
        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(concat_list),
            '-c', 'copy',
            str(seg_tts)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        dur_total = get_duration(seg_tts)
        total_time += dur_total
        
        rec = {
            'id': bid,
            'eyebrow': b['eyebrow'],
            'title': b['title'],
            'mode': b['mode'],
            'q_speaker': b['q_speaker'],
            'q_text': b['q_text'],
            'q_dur': dur_q,
            'silence_dur': 0.20,
            'a_speaker': b['a_speaker'],
            'a_text': b['a_text'],
            'a_dur': dur_a,
            'total_dur': dur_total,
            'card_data': b['card_data'],
            'file': str(seg_tts)
        }
        records.append(rec)
        print(f"[{bid}] Q: {dur_q:.2f}s | Silence: 0.20s | A: {dur_a:.2f}s => Total: {dur_total:.2f}s")
    
    meta_path = AUDIO_DIR / 'dialogue_meta.json'
    meta_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nAll 7 dialogue segments generated! Total duration: {total_time:.2f}s")

if __name__ == '__main__':
    asyncio.run(main())
