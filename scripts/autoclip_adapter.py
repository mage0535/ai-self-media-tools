#!/usr/bin/env python3
"""
AutoClip Hermes adapter - wraps AI video highlight extraction into a callable module.
Integrates into content_generator.py video pipeline.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = Path(os.environ.get("HERMES_DATA_DIR", os.path.expanduser("~/.hermes/data"))) / "video_output"


def log(msg):
    ts = datetime.now(CST).strftime("%H:%M:%S")
    print(f"[AutoClip] {ts} {msg}")


def check_deps():
    missing = []
    for cmd in ["yt-dlp", "ffmpeg"]:
        if not shutil.which(cmd):
            missing.append(cmd)
    try:
        import whisper
    except ImportError:
        missing.append("whisper")
    return missing


def download_video(url, output_dir):
    out = os.path.join(output_dir, "%(title)s.%(ext)s")
    r = subprocess.run(
        [
            "yt-dlp", "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "--write-subs", "--write-auto-subs", "--sub-langs", "en,zh-Hans,zh",
            "--convert-subs", "srt",
            "-o", out, url,
        ],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError("Download failed: " + r.stderr[:200])
    mp4s = sorted(Path(output_dir).glob("*.mp4"))
    return str(mp4s[0]) if mp4s else None


def transcribe_video(video_path):
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(video_path)
    return result["text"], result.get("segments", [])


def extract_highlights(transcript_text):
    return {"segments_summary": transcript_text[:2000], "llm_ready": True}


def clip_segments(video_path, segments, output_dir):
    clips = []
    for i, seg in enumerate(segments[:5]):
        start = seg.get("start", 0)
        end = seg.get("end", min(start + 60, 300))
        title = seg.get("title", f"clip_{i:02d}")
        out = os.path.join(output_dir, f"highlight_{i:02d}_{title[:30]}.mp4")
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-ss", str(start), "-to", str(end), "-c", "copy", "-y", out],
            check=True, capture_output=True, timeout=120,
        )
        clips.append({"file": out, "title": title, "start": start, "end": end})
    return clips


def create_compilation(clips, output_path):
    if not clips:
        return None
    if len(clips) == 1:
        shutil.copy(clips[0]["file"], output_path)
        return output_path
    list_file = output_path + ".txt"
    with open(list_file, "w") as f:
        for c in clips:
            f.write(f"file '{c['file']}'\n")
    subprocess.run(
        ["ffmpeg", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", "-y", output_path],
        check=True, capture_output=True, timeout=120,
    )
    os.unlink(list_file)
    return output_path


def get_clip_duration(filepath):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", filepath],
        capture_output=True, text=True, timeout=10,
    )
    try:
        return float(r.stdout.strip() or 0)
    except ValueError:
        return 0


def quality_check(clips, min_duration=10, max_duration=300):
    if not clips:
        return {"pass": False, "reason": "No clips generated"}
    issues = []
    for c in clips:
        dur = get_clip_duration(c["file"])
        if dur < min_duration:
            issues.append("Clip too short: " + c["title"] + " (" + str(int(dur)) + "s)")
        if dur > max_duration:
            issues.append("Clip too long: " + c["title"] + " (" + str(int(dur)) + "s)")
        if not os.path.exists(c["file"]):
            issues.append("Missing file: " + c["file"])
    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "clip_count": len(clips),
    }


def run_autoclip_pipeline(url, task_id=None):
    import time as _time
    task_id = task_id or f"ac_{int(_time.time())}"
    workdir = OUTPUT_DIR / task_id
    workdir.mkdir(parents=True, exist_ok=True)

    log("Starting AutoClip: " + url[:80])

    video = download_video(url, workdir)
    if not video:
        raise RuntimeError("Download returned no video file")
    log("Downloaded: " + os.path.basename(video))

    text, segments = transcribe_video(video)
    log("Transcribed: " + str(len(text)) + " chars, " + str(len(segments)) + " segments")

    highlights = extract_highlights(text)
    log("Highlights extracted")

    clips = clip_segments(video, segments, workdir)
    log("Clipped: " + str(len(clips)) + " segments")

    compilation = str(OUTPUT_DIR / f"{task_id}_compilation.mp4")
    create_compilation(clips, compilation)

    result = {
        "task_id": task_id,
        "source_url": url,
        "clips": [{"file": c["file"], "title": c["title"], "start": c["start"], "end": c["end"]} for c in clips],
        "compilation": compilation,
        "transcript_preview": text[:500],
    }
    log("Done: " + str(len(clips)) + " clips + compilation")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AutoClip - AI video highlight extraction")
    parser.add_argument("url", help="Video URL to process")
    parser.add_argument("--check", action="store_true", help="Check dependencies only")
    args = parser.parse_args()

    if args.check:
        missing = check_deps()
        print(json.dumps({"deps_ok": len(missing) == 0, "missing": missing}, indent=2))
        sys.exit(0 if not missing else 1)

    result = run_autoclip_pipeline(args.url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
