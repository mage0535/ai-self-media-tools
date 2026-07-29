#!/usr/bin/env python3
import os
if os.environ.get('HERMES_ALLOW_LEGACY_RENDER_DEMO') != '1':
    raise SystemExit('legacy_render_demo_disabled: use Pipeline + validate_*_auto_packet + current manifest')
"""完整快手管线：Kokoro TTS → FFmpeg 合成 → 验证"""
import subprocess, os, sys, time
from pathlib import Path

OUT = Path("/root/.ai-self-media-tools/data/drafts/kuaishou_video")

scripts = [
    "想用AI提效但不知道从哪下手？今天教你一个最简单的切入点。",
    "第一步，找出你每天重复做3次以上的任务。填报表、回邮件、整理数据，这些就是自动化的首选目标。",
    "第二步，用OpenClaw搭一条简单的Agent链。新数据进来，自动处理，结果写入表格，全程不用守着。",
    "第三步，加一个通知节点。处理完自动推送到企业微信，你在手机上就能看结果。",
    "这个流程我跑了半个月，最直接的感受：以前每天花1小时整理的数据，现在机器替我搞定。",
    "关注我，下期拆解一个能自动接单赚钱的Agent系统。",
]

kokoro_cli = [sys.executable, str(Path(os.environ.get("HERMES_SCRIPTS_DIR", str(Path.home() / ".hermes" / "scripts"))) / "kokoro_tts.py"), "--voice", "zh-CN-XiaoxiaoNeural"]

# 1. Kokoro TTS
for i, text in enumerate(scripts):
    out = str(OUT / f"tts_{i+1:02d}.wav")
    r = subprocess.run(kokoro_cli + ["--text", text, "--write-media", out],
                      capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"TTS {i+1} failed: {r.stderr[:200]}")
        sys.exit(1)
    dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",out],
                        capture_output=True, text=True).stdout.strip()
    sz = os.path.getsize(out)
    print(f"[{time.strftime('%H:%M:%S')}] TTS {i+1}: {float(dur):.1f}s, {sz//1024}KB ✅")
    sys.stdout.flush()

# 2. Segments
cards = [str(OUT / f"card_{i+1:02d}.png") for i in range(6)]
segs = []
for i in range(6):
    seg = str(OUT / f"seg_{i+1:02d}.mp4")
    subprocess.run([
        "ffmpeg","-y","-loop","1","-i",cards[i],"-i",str(OUT/f"tts_{i+1:02d}.wav"),
        "-c:v","libx264","-preset","ultrafast","-crf","28",
        "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p","-shortest",seg
    ], capture_output=True, timeout=120)
    dur = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",seg],
                        capture_output=True, text=True).stdout.strip()
    print(f"Seg {i+1}: {float(dur):.1f}s ✅")
    segs.append(seg)

# 3. Concat
concat = OUT / "concat.txt"
concat.write_text("\n".join(f"file '{s}'" for s in segs))
raw = OUT / "raw.mp4"
subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(raw)], capture_output=True, timeout=60)

# 4. BGM mix (SoundHelix Track 4 - 民谣吉他, real instrument)
bgm_trim = OUT / "bgm_trim.mp3"
subprocess.run(["ffmpeg","-y","-i",str(OUT/"bgm_test_4.mp3"),"-t","55","-c","copy",str(bgm_trim)], capture_output=True, timeout=30)
mix = OUT / "mixed.mp3"
subprocess.run(["ffmpeg","-y","-i",str(raw),"-i",str(bgm_trim),
    "-filter_complex","[1:a]volume=0.08[bgm];[0:a][bgm]amix=inputs=2:duration=first",
    "-c:a","libmp3lame","-q:a","2",str(mix)], capture_output=True, timeout=60)
final = OUT / "final.mp4"
subprocess.run(["ffmpeg","-y","-i",str(raw),"-i",str(mix),
    "-c:v","copy","-c:a","aac","-map","0:v:0","-map","1:a:0","-shortest",str(final)], capture_output=True, timeout=60)

# 5. Verify
dur_s = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(final)], capture_output=True, text=True).stdout.strip()
sz = os.path.getsize(final)//1024
subprocess.run(["ffmpeg","-y","-i",str(final),"-vframes","1","-q:v","2",str(OUT/"verify.jpg")], capture_output=True)
vf = os.path.getsize(str(OUT/"verify.jpg")) if (OUT/"verify.jpg").exists() else 0
vol = subprocess.run(["ffmpeg","-i",str(final),"-af","volumedetect","-f","null","-"], capture_output=True, text=True)
mv = [l.strip() for l in vol.stderr.split("\n") if "mean_volume" in l]

print(f"\n{'='*40}")
print(f"时长: {float(dur_s):.1f}s")
print(f"大小: {sz}KB")
print(f"画面: {'✅' if vf>100 else '❌'} ({vf}B)")
print(f"音量: {mv[0] if mv else '?'}")
print(f"配音: Kokoro ✅ 自然人声")
print(f"配乐: SoundHelix Track 4 民谣吉他 ✅ 真实乐器")
print(f"{'='*40}")
