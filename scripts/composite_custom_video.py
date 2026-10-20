import json
import subprocess
from pathlib import Path

BASE_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1')
CUSTOM_DIR = BASE_DIR / 'custom_render'
SHOTS_DIR = CUSTOM_DIR / 'shots'
AUDIO_DIR = BASE_DIR / 'audio'
OUTPUT_DIR = BASE_DIR / 'render'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Build shots concat file
concat_txt = CUSTOM_DIR / 'shots_concat.txt'
shot_names = []
for idx in range(8):
    sid = f'shot_{idx+1:02d}'
    shot_names.append(f'{sid}A')
    shot_names.append(f'{sid}B')

with open(concat_txt, 'w', encoding='utf-8') as f:
    for name in shot_names:
        mp4_path = SHOTS_DIR / f'{name}.mp4'
        f.write(f"file '{mp4_path.resolve()}'\n")

video_concat_mp4 = CUSTOM_DIR / 'visual_concat.mp4'
print("Step 1: Concatenating 16 video shots...")
cmd_concat = [
    'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
    '-i', str(concat_txt),
    '-c:v', 'libx264', '-preset', 'fast', '-profile:v', 'baseline', '-level', '3.1',
    '-pix_fmt', 'yuv420p', '-r', '25',
    str(video_concat_mp4)
]
subprocess.run(cmd_concat, check=True)
print("Step 1: Done!")

# 2. Build aligned audio from the 8 TTS files
print("Step 2: Concatenating 8 TTS audio files...")
tts_files = [AUDIO_DIR / f's{i+1:02d}.mp3' for i in range(8)]
tts_concat_txt = CUSTOM_DIR / 'tts_concat.txt'
with open(tts_concat_txt, 'w', encoding='utf-8') as f:
    for tf in tts_files:
        f.write(f"file '{tf.resolve()}'\n")

voice_aligned_wav = CUSTOM_DIR / 'voice_aligned.wav'
cmd_voice = [
    'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
    '-i', str(tts_concat_txt),
    '-ar', '44100', '-ac', '2',
    str(voice_aligned_wav)
]
subprocess.run(cmd_voice, check=True)

p = subprocess.run([
    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
    '-of', 'default=noprint_wrappers=1:nokey=1', str(voice_aligned_wav)
], capture_output=True, text=True, check=True)
total_voice_dur = float(p.stdout.strip())
print(f"Total voice duration: {total_voice_dur:.2f}s")

# 3. Mix Voice and BGM (piano bgm at volume 0.12)
print("Step 3: Mixing Voice with BGM...")
bgm_file = AUDIO_DIR / 'bgm.mp3'
mixed_audio_wav = CUSTOM_DIR / 'mixed_audio.wav'
cmd_mix = [
    'ffmpeg', '-y',
    '-i', str(voice_aligned_wav),
    '-stream_loop', '-1', '-i', str(bgm_file),
    '-filter_complex', '[0:a]volume=1.0[v];[1:a]volume=0.12[b];[v][b]amix=inputs=2:duration=first:dropout_transition=2[out]',
    '-map', '[out]',
    '-t', str(total_voice_dur),
    '-ar', '44100', '-ac', '2',
    str(mixed_audio_wav)
]
subprocess.run(cmd_mix, check=True)
print("Step 3: Done!")

# 4. Generate Subtitles (srt) with fine-grained clause timing
print("Step 4: Building Subtitle file with safe boundaries...")
durations = json.loads((AUDIO_DIR / 'durations.json').read_text('utf-8'))
seg_durs = [durations[f's{i+1:02d}'] for i in range(8)]

# Precise 2-3 phrase splits per beat matching spoken rhythm
subtitle_splits = [
    # Beat 1: 9.408s
    [
        ("千万别直接让AI写方案！", 0.0, 3.2),
        ("张哥救命，我3分钟生成的5000字方案，", 3.2, 6.8),
        ("汇报时被领导追问数据出处，当场崩溃！", 6.8, 9.408),
    ],
    # Beat 2: 9.864s
    [
        ("你直接让它写，不出事才怪！", 0.0, 3.1),
        ("大模型本质是文字概率推测，它会生成话术级的自信，", 3.1, 7.2),
        ("但年份案例全凭编造。", 7.2, 9.864),
    ],
    # Beat 3: 5.904s
    [
        ("难怪查不到出处！那平时做方案，", 0.0, 3.0),
        ("到底怎么让AI干活才不会翻车？", 3.0, 5.904),
    ],
    # Beat 4: 8.136s
    [
        ("第1招锁死信源：指令开头必须加", 0.0, 3.2),
        ("“仅基于我给的材料总结”，不提供真实资料，", 3.2, 6.0),
        ("坚决不让AI乱猜。", 6.0, 8.136),
    ],
    # Beat 5: 8.472s
    [
        ("第2招强制标注出处：核心结论后面", 0.0, 3.4),
        ("必须打括号指明引用的原文段落，", 3.4, 6.2),
        ("查不到来源的数据直接剔除。", 6.2, 8.472),
    ],
    # Beat 6: 8.616s
    [
        ("第3招骨肉分离：让AI干排版整理、文字润色的体力活，", 0.0, 4.4),
        ("关键决策和核心数据必须人工复核。", 4.4, 8.616),
    ],
    # Beat 7: 8.160s
    [
        ("懂了！锁信源、标出处、人看两头！", 0.0, 3.6),
        ("这套防AI胡说清单太实用了，我得赶紧保存下来。", 3.6, 8.160),
    ],
    # Beat 8: 9.432s
    [
        ("你在用人工智能写方案时被虚假数据坑过吗？", 0.0, 4.2),
        ("建议收藏，评论区回复【防翻车】，发你这套避坑指令模板。", 4.2, 9.432),
    ],
]

def fmt_time(sec):
    hrs = int(sec // 3600)
    mins = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{s:02d},{ms:03d}"

srt_path = CUSTOM_DIR / 'subtitles.srt'
cur_base = 0.0
srt_idx = 1
with open(srt_path, 'w', encoding='utf-8') as f:
    for b_idx, phrases in enumerate(subtitle_splits):
        for text, rel_start, rel_end in phrases:
            start_t = cur_base + rel_start
            end_t = cur_base + rel_end
            f.write(f"{srt_idx}\n")
            f.write(f"{fmt_time(start_t)} --> {fmt_time(end_t)}\n")
            f.write(f"{text}\n\n")
            srt_idx += 1
        cur_base += seg_durs[b_idx]

print(f"Generated {srt_idx-1} subtitle cues in {srt_path.name}")

# 5. Final Composite: Burn-in subtitles at bottom safe zone with clear styling
print("Step 5: Burning subtitles and compositing final MP4...")
final_mp4 = OUTPUT_DIR / 'final.mp4'
backup_old = OUTPUT_DIR / 'final_old_failed.mp4'
if final_mp4.exists():
    final_mp4.replace(backup_old)

# MarginV=70 keeps subtitle at bottom Y ≈ 1190px, strictly outside the top 175px~660px card area!
sub_style = 'Fontname=Noto Sans CJK SC,Fontsize=22,PrimaryColour=&HFFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=2.5,Shadow=1,Alignment=2,MarginV=65'
cmd_final = [
    'ffmpeg', '-y',
    '-i', str(video_concat_mp4),
    '-i', str(mixed_audio_wav),
    '-vf', f"subtitles={srt_path}:force_style='{sub_style}'",
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-profile:v', 'baseline', '-level', '3.1',
    '-pix_fmt', 'yuv420p', '-r', '25',
    '-c:a', 'aac', '-b:a', '192k',
    '-movflags', '+faststart',
    '-t', str(total_voice_dur),
    str(final_mp4)
]
subprocess.run(cmd_final, check=True)
print(f"Successfully generated ultimate final video: {final_mp4.resolve()} ({final_mp4.stat().st_size / 1024 / 1024:.2f} MB)")
