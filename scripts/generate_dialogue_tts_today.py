#!/usr/bin/env python3
import asyncio
import json
import subprocess
from pathlib import Path
import edge_tts

AUDIO_DIR = Path("/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

DIALOGUE_BEATS = [
    {
        "beat_id": "s01",
        "speaker": "小林",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+15%",
        "text": "千万别直接让AI写方案！张哥救命，我3分钟生成的5000字方案，汇报时被领导追问数据出处，当场崩溃！"
    },
    {
        "beat_id": "s02",
        "speaker": "老张",
        "voice": "zh-CN-YunjianNeural",
        "rate": "+10%",
        "text": "你直接让它写，不出事才怪！大模型本质是文字概率推测，它会生成话术级的自信，但年份案例全凭编造。"
    },
    {
        "beat_id": "s03",
        "speaker": "小林",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+15%",
        "text": "难怪查不到出处！那平时做方案，到底怎么让AI干活才不会翻车？"
    },
    {
        "beat_id": "s04",
        "speaker": "老张",
        "voice": "zh-CN-YunjianNeural",
        "rate": "+10%",
        "text": "第1招锁死信源：指令开头必须加“仅基于我给的材料总结”，不提供真实资料，坚决不让AI乱猜。"
    },
    {
        "beat_id": "s05",
        "speaker": "老张",
        "voice": "zh-CN-YunjianNeural",
        "rate": "+10%",
        "text": "第2招强制标注出处：核心结论后面必须打括号指明引用的原文段落，查不到来源的数据直接剔除。"
    },
    {
        "beat_id": "s06",
        "speaker": "老张",
        "voice": "zh-CN-YunjianNeural",
        "rate": "+10%",
        "text": "第3招骨肉分离：让AI干排版整理、文字润色的体力活，关键决策和核心数据必须人工复核。"
    },
    {
        "beat_id": "s07",
        "speaker": "小林",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+15%",
        "text": "懂了！锁信源、标出处、人看两头！这套防AI胡说清单太实用了，我得赶紧保存下来。"
    },
    {
        "beat_id": "s08",
        "speaker": "老张",
        "voice": "zh-CN-YunjianNeural",
        "rate": "+10%",
        "text": "你在用人工智能写方案时被虚假数据坑过吗？建议收藏，评论区回复【防翻车】，发你这套避坑指令模板。"
    }
]

def get_duration(audio_file: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_file)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())

async def main():
    durations = {}
    total_dur = 0.0
    for beat in DIALOGUE_BEATS:
        beat_id = beat["beat_id"]
        out_mp3 = AUDIO_DIR / f"{beat_id}.mp3"
        print(f"Generating TTS for {beat_id} [{beat['speaker']} / {beat['voice']}]...")
        communicate = edge_tts.Communicate(beat["text"], beat["voice"], rate=beat["rate"])
        await communicate.save(str(out_mp3))
        dur = get_duration(out_mp3)
        durations[beat_id] = round(dur, 3)
        total_dur += dur
        print(f"  -> {beat_id}.mp3: {dur:.2f}s ({beat['text'][:20]}...)")

    (AUDIO_DIR / "durations.json").write_text(json.dumps(durations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nAll 8 beats synthesized successfully! Total duration: {total_dur:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
