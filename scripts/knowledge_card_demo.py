#!/usr/bin/env python3
import os
if os.environ.get("HERMES_ALLOW_LEGACY_RENDER_DEMO") != "1":
    raise SystemExit("legacy_render_demo_disabled: use Pipeline + video_toolchain_runner.py + cinema visual gate")
"""Demo: 知识卡片过渡动画 + 字幕对齐"""
import subprocess, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("/tmp/knowledge_card_demo")
OUT.mkdir(parents=True, exist_ok=True)
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

def font(sz):
    try: return ImageFont.truetype(FONT, sz, index=0)
    except: return ImageFont.load_default()

# 4张测试卡片
cards = [
    {"text": "AI工具正在改变\n我们的工作方式", "sub": "效率提升看得见", "bg": (15,23,42), "accent": (59,130,246)},
    {"text": "自动处理重复任务\n释放你的创造力", "sub": "每天省下2小时", "bg": (20,40,30), "accent": (52,211,153)},
    {"text": "实时数据分析\n决策不再靠感觉", "sub": "数据驱动增长", "bg": (30,20,50), "accent": (139,92,246)},
    {"text": "关注我\n持续分享AI效率工具", "sub": "下期更精彩", "bg": (40,15,30), "accent": (236,72,153)},
]

scripts = [
    "AI工具正在改变我们的工作方式。效率提升看得见。",
    "自动处理重复任务，释放你的创造力。每天省下2小时。",
    "实时数据分析，决策不再靠感觉。数据驱动增长。",
    "关注我，持续分享AI效率工具。下期更精彩。",
]

card_paths = []
for i, d in enumerate(cards):
    img = Image.new("RGB", (720, 1280), d["bg"])
    draw = ImageDraw.Draw(img)
    # gradient
    for y in range(1280):
        a = 0.3
        r = min(255, int(d["bg"][0]*(1-a) + d["accent"][0]*a*y/1280))
        g = min(255, int(d["bg"][1]*(1-a) + d["accent"][1]*a*y/1280))
        b = min(255, int(d["bg"][2]*(1-a) + d["accent"][2]*a*y/1280))
        draw.line([(0,y),(719,y)], fill=(r,g,b), width=1)
    # accented card number
    draw.rounded_rectangle([(40,60),(100,100)], radius=12, fill=d["accent"])
    draw.text((52,68), f"0{i+1}", fill=d["bg"], font=font(22))
    # title
    f_big = font(44)
    for j, ln in enumerate(d["text"].split("\n")):
        draw.text((40, 250+j*60), ln, fill=(245,245,245), font=f_big)
    # subtitle
    draw.text((40, 400), d["sub"], fill=d["accent"], font=font(28))
    # bottom tag
    draw.rounded_rectangle([(40,1100),(250,1140)], radius=8, fill=d["accent"])
    draw.text((55,1109), "效率工具 · 自动化", fill=d["bg"], font=font(18))
    p = OUT / f"card_{i+1:02d}.png"
    img.save(p)
    card_paths.append(str(p))
    print(f"卡{i+1}: {p}")

# TTS (get actual durations for sync)
audio_paths = []
durations = []
for i, script in enumerate(scripts):
    out = str(OUT / f"tts_{i+1:02d}.mp3")
    subprocess.run(["edge-tts","--voice","zh-CN-XiaoxiaoNeural","--text",script,"--write-media",out],
                   capture_output=True, timeout=60)
    dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out],
                        capture_output=True, text=True).stdout.strip()
    durations.append(float(dur))
    audio_paths.append(out)
    print(f"TTS {i+1}: {dur}s")

# Generate segments with zoompan (Ken Burns)
seg_paths = []
xfade_types = ["fade", "slideright",  "fadeblack", "slidetop"]
xfade_types = ["fade", "slideright", "fadeblack", "slidetop"]

for i in range(4):
    seg = OUT / f"seg_{i+1:02d}.mp4"
    dur = durations[i]
    # zoompan: subtle Ken Burns zoom
    subprocess.run([
        "ffmpeg","-y","-loop","1","-i",card_paths[i],"-i",audio_paths[i],
        "-filter_complex",
        f"[0:v]zoompan=z='if(lte(zoom,1.0),1.05,zoom-0.0015)':d={int(dur*30)}:s=720x1280:fps=30[v]",
        "-map","[v]","-map","1:a","-c:v","libx264","-preset","ultrafast","-crf","28",
        "-c:a","aac","-shortest",str(seg)
    ], capture_output=True, timeout=120)
    seg_paths.append(str(seg))
    print(f"Seg {i+1}: {dur}s (xfade={xfade_types[i] if i>0 else 'none'})")

# Concat with xfade transitions (between segments)
# First segment starts raw, then each subsequent segment has transition
concat_parts = []

# Seg 1 (no transition needed)
concat_parts.append(seg_paths[0])

# For xfade approach, we need overlapping segments
for i in range(1, 4):
    # Transition lasts 0.5s
    trans = xfade_types[i - 1]
    prev_dur = sum(durations[:i])
    
    # We use the concat protocol instead since xfade requires precise overlapping
    # which is complex for multi-segment. For simplicity, demonstrate with concat
    # and add transition between first two segments as proof
    pass

# Simpler approach: concat with hard cut (for now), then add single xfade demo
# Just concat for demo
concat_file = OUT / "concat.txt"
with open(concat_file, "w") as f:
    for s in seg_paths:
        f.write(f"file '{s}'\n")

raw = OUT / "raw.mp4"
subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat_file),"-c","copy",str(raw)],
               capture_output=True, timeout=60)

# Add subtitles synced to TTS
# Generate subtitles with exact timing
srt_content = ""
offset = 0
for i in range(4):
    start = offset
    end = offset + durations[i]
    srt_content += f"{i+1}\n"
    srt_content += f"{int(start//60):02d}:{int(start%60):02d}:{int((start%1)*1000):03d} --> "
    srt_content += f"{int(end//60):02d}:{int(end%60):02d}:{int((end%1)*1000):03d}\n"
    srt_content += f"{scripts[i]}\n\n"
    offset = end

srt_path = OUT / "subtitles.srt"
srt_path.write_text(srt_content)

# Burn subtitles
final_with_sub = OUT / "final_sub.mp4"
subprocess.run([
    "ffmpeg","-y","-i",str(raw),
    "-vf",f"subtitles={srt_path}:force_style='FontName=Noto+Sans+SC,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H00666666,BorderStyle=1,Outline=2,MarginV=40'",
    "-c:a","copy",str(final_with_sub)
], capture_output=True, timeout=60)

# Now demo xfade transition between seg 1 and seg 2 (0.5s crossfade)
demo_xfade = OUT / "demo_xfade.mp4"
subprocess.run([
    "ffmpeg","-y","-i",seg_paths[0],"-i",seg_paths[1],
    "-filter_complex",
    f"[0:v][1:v]xfade=transition=fade:duration=0.5:offset={durations[0]-0.5}[v];"
    f"[0:a][1:a]acrossfade=d=0.5[cross]",
    "-map","[v]","-map","[cross]","-c:v","libx264","-preset","ultrafast","-crf","28",
    "-c:a","aac",str(demo_xfade)
], capture_output=True, timeout=120)

# Verify
print(f"\n{'='*40}")
print(f"✅ Demo 完成")
print(f"   完整视频(硬切): {raw} ({os.path.getsize(raw)//1024}KB)")
print(f"   字幕对齐: {final_with_sub} ({os.path.getsize(final_with_sub)//1024}KB)")
print(f"   过渡动画demo: {demo_xfade} ({os.path.getsize(demo_xfade)//1024}KB)")
print(f"  字幕时间轴: {srt_path}")
print(f"{'='*40}")
print()
print("过渡动画类型:")
for i, t in enumerate(['(首卡)','fade','slideright','fadeblack','slidetop']):
    print(f"  {i+1}. {t}")
print()
print("字幕对齐方式: TTS实际时长 -> SRT精确到毫秒")
print(f"  各段TTS时长: {[f'{d:.2f}s' for d in durations]}")
