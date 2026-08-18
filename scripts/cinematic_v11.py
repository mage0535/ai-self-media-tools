#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

TRANSITIONS_BY_PLATFORM = {
    "youtube": ["fadeblack", "smoothleft", "circleopen", "dissolve", "smoothright", "smoothup", "fadeblack"],
    "tiktok": ["wipeleft", "slideup", "revealright", "wiperight", "slideleft", "revealup", "wipeup"],
    "douyin_ai": ["circleopen", "wipeleft", "slideup", "fadeblack", "revealright", "smoothup", "slideleft"],
    "bilibili": ["fadeblack", "smoothleft", "dissolve", "circleopen", "smoothright", "revealright", "fadeblack"],
}
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def synthesize_tts(text: str, voice: str, target: Path) -> None:
    errors=[]
    for attempt in range(1,5):
        target.unlink(missing_ok=True)
        result=subprocess.run(["edge-tts","--voice",voice,"--rate=-4%","--text",text,"--write-media",str(target)],capture_output=True,text=True,timeout=90)
        if result.returncode==0 and target.is_file() and target.stat().st_size>=10000:
            return
        errors.append((result.stderr or "no audio")[-160:])
        time.sleep(attempt)
    raise RuntimeError(f"edge-tts failed after 4 attempts: {errors[-1]}")

def duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], text=True)
    return float(out.strip())

def wrap(text: str, limit: int = 20) -> tuple[str, str]:
    if " " in text:
        words=text.split(); first=[]; second=[]
        for word in words:
            target=first if len(" ".join(first+[word]))<=limit else second
            target.append(word)
        return " ".join(first), " ".join(second)
    if len(text) <= limit: return text, ""
    return text[:limit], text[limit:limit * 2]

def wrap_lines(text: str, limit: int, max_lines: int = 4) -> list[str]:
    if " " not in text:
        return [text[i:i+limit] for i in range(0, len(text), limit)][:max_lines]
    lines=[]; current=""
    for word in text.split():
        candidate=(current+" "+word).strip()
        if current and len(candidate)>limit:
            lines.append(current); current=word
        else: current=candidate
    if current: lines.append(current)
    if len(lines)>max_lines:
        raise ValueError(f"subtitle exceeds {max_lines} lines: {text}")
    return lines

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-dir", required=True)
    ap.add_argument("--platform", required=True)
    args = ap.parse_args()
    out = Path(args.video_dir).resolve()
    landscape = args.platform == "bilibili"
    width, height = (1920, 1080) if landscape else (1080, 1920)
    transitions = TRANSITIONS_BY_PLATFORM.get(args.platform, TRANSITIONS_BY_PLATFORM["youtube"])
    footage = sorted((out / "footage").glob("scene_*.mp4"))
    manifest = json.loads((out / "scene_manifest.json").read_text(encoding="utf-8"))
    scenes = manifest["scenes"]
    from scripts.visual_asset_gate import validate_assets

    asset_gate = validate_assets(out, args.platform)
    if not asset_gate.get("passed"):
        raise SystemExit(f"visual asset gate failed: {asset_gate.get('failures')}")
    tts_dir = out / "tts"
    tts_dir.mkdir(exist_ok=True)
    has_cjk = any("\u4e00" <= char <= "\u9fff" for scene in scenes for char in str(scene.get("narration") or ""))
    voice = "zh-CN-YunxiNeural" if has_cjk else "en-US-JennyNeural"
    for index, scene in enumerate(scenes, 1):
        target = tts_dir / f"tts_{index:02d}.mp3"
        if not target.is_file() or target.stat().st_size < 10000:
            synthesize_tts(str(scene["narration"]), voice, target)
    tts = sorted(tts_dir.glob("tts_*.mp3"))
    if not (out / "bgm.mp3").is_file():
        from scripts.kuaishou_render import download_bgm
        download_bgm(str(out), style="gentle piano")
    if len(footage) != 8 or len(tts) != 8 or len(scenes) != 8:
        raise SystemExit("v11 requires eight footage clips, TTS clips, and scenes")
    clips = out / "v11_clips"
    clips.mkdir(exist_ok=True)
    clip_paths, clip_durations = [], []
    for index, (video, audio, scene) in enumerate(zip(footage, tts, scenes), 1):
        d = duration(audio) + 0.55
        line1, line2 = wrap(str(scene.get("visual_claim") or scene.get("subtitle") or ""), 18 if args.platform != "youtube" else 30)
        text1 = clips / f"text_{index:02d}_1.txt"
        text2 = clips / f"text_{index:02d}_2.txt"
        text1.write_text(line1, encoding="utf-8")
        text2.write_text(line2, encoding="utf-8")
        subtitle_lines = wrap_lines(str(scene.get("narration") or ""), 48 if landscape else 32, 4)
        subtitle_files=[]
        for line_index,line in enumerate(subtitle_lines,1):
            path=clips/f"sub_{index:02d}_{line_index}.txt"; path.write_text(line,encoding="utf-8"); subtitle_files.append(path)
        y_positions = [140, 690, 380] if landscape else [270, 1320, 780]
        y = y_positions[(index - 1) % 3]
        grades = {
            "youtube": ["contrast=1.08:saturation=1.04", "contrast=1.10:saturation=.94", "contrast=1.05:saturation=1.08"],
            "tiktok": ["contrast=1.12:saturation=1.28", "contrast=1.08:saturation=1.18", "contrast=1.16:saturation=1.22"],
            "douyin_ai": ["contrast=1.10:saturation=1.18", "contrast=1.14:saturation=1.08", "contrast=1.08:saturation=1.24"],
            "bilibili": ["contrast=1.08:saturation=.98", "contrast=1.12:saturation=.90", "contrast=1.06:saturation=1.05"],
        }
        grade = grades.get(args.platform, grades["youtube"])[index % 3]
        camera_x = ["sin(t*.65)*22", "cos(t*.58)*28", "sin(t*.42)*34"][index % 3]
        camera_y = ["cos(t*.50)*30", "sin(t*.46)*24", "cos(t*.35)*36"][index % 3]
        scale_width, scale_height = int(width * 1.12), int(height * 1.12)
        vf = (
            f"scale={scale_width}:{scale_height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='(in_w-out_w)/2+{camera_x}':y='(in_h-out_h)/2+{camera_y}',"
            f"eq={grade},vignette=PI/5,"
            f"drawbox=x=42:y=70:w={width-84}:h=8:color=#ffd166@0.30:t=fill,"
            f"drawbox=x=42:y=70:w={(width-84)*index/8:.1f}:h=8:color=#ffd166@0.95:t=fill,"
            f"drawtext=fontfile={FONT}:text='{index:02d}/08':fontsize={28 if landscape else 34}:fontcolor=#ffd166:x=50:y=92,"
            f"drawtext=fontfile={FONT}:textfile={text1}:fontsize={54 if landscape else 62}:fontcolor=white:borderw=4:bordercolor=black:x=(w-text_w)/2:y={y}:alpha='min(1,t/0.45)',"
            f"drawtext=fontfile={FONT}:textfile={text2}:fontsize={44 if landscape else 52}:fontcolor=#ffd166:borderw=4:bordercolor=black:x=(w-text_w)/2:y={y+80}:alpha='min(1,t/0.65)',"
            f"drawbox=x=40:y={height-450}:w={width-80}:h=360:color=black@0.58:t=fill"
        )
        subtitle_size=30 if landscape else 32
        for line_index,path in enumerate(subtitle_files):
            vf += f",drawtext=fontfile={FONT}:textfile={path}:fontsize={subtitle_size}:fontcolor=white:borderw=3:bordercolor=black:x=(w-text_w)/2:y={height-410+line_index*68}"
        target = clips / f"scene_{index:02d}.mp4"
        if not target.is_file() or duration(target) < d - 0.2:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(video), "-t", f"{d:.3f}", "-vf", vf, "-an", "-r", "25", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", str(target)], check=True, timeout=240)
        clip_paths.append(target)
        clip_durations.append(duration(target))
    inputs = sum((["-i", str(path)] for path in clip_paths), [])
    parts, previous, offset = [], "0:v", 0.0
    for index in range(1, 8):
        offset += clip_durations[index - 1] - 0.45
        label = f"x{index}"
        parts.append(f"[{previous}][{index}:v]xfade=transition={transitions[index-1]}:duration=0.45:offset={offset:.3f}[{label}]")
        previous = label
    parts.append(f"[{previous}]format=yuv420p[v]")
    visual = out / "v11_visual.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(parts), "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", str(visual)], check=True, timeout=500)
    audio_list = out / "v11_audio.txt"
    audio_list.write_text("\n".join(f"file '{path}'" for path in tts), encoding="utf-8")
    narration = out / "v11_narration.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c:a", "aac", "-ar", "44100", "-ac", "2", str(narration)], check=True)
    final = out / "final_v11.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(visual), "-i", str(narration), "-stream_loop", "-1", "-i", str(out / "bgm.mp3"), "-filter_complex", "[1:a]volume=1.8[v];[2:a]volume=.10[b];[v][b]amix=inputs=2:duration=first[a]", "-map", "0:v", "-map", "[a]", "-shortest", "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(final)], check=True, timeout=240)
    evidence = {"version": "cinematic-v11.3", "passed": True, "platform": args.platform, "source_footage": [str(p) for p in footage], "scene_count": 8, "transitions": transitions, "duration": duration(final), "visual_asset_gate": asset_gate, "cinematic_layers": ["source_motion", "camera_drift", "scene_progress", "visual_claim", "full_narration_subtitles", "semantic_transition"]}
    (out / "cinematic_v11_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(final)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
