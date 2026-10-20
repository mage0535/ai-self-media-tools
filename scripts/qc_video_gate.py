#!/usr/bin/env python3
"""
qc_video_gate.py — 视频发布前置自动质量门禁 (Fail-Closed)
核查维度：
1. 时长：短视频在 15~45 秒区间
2. 码率：必须 >= 600 kbps (杜绝 200kbps 极低画质 PPT)
3. 画面多样性：禁止纯色/纯黑底（检测画面方差）
4. 自动抽帧：输出 4 帧供 visual review
"""

import sys
import json
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

def run_qc(video_path: str) -> dict:
    vp = Path(video_path)
    if not vp.exists():
        return {"passed": False, "error": f"File not found: {video_path}"}

    # 1. ffprobe
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=width,height,codec_name,codec_type",
        "-of", "json", str(vp)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return {"passed": False, "error": "ffprobe failed: " + res.stderr}

    meta = json.loads(res.stdout)
    fmt = meta.get("format", {})
    streams = meta.get("streams", [])
    
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not v_stream or not a_stream:
        return {"passed": False, "error": "Missing video or audio stream"}

    duration = float(fmt.get("duration", 0))
    bitrate = int(fmt.get("bit_rate", 0))
    width = int(v_stream.get("width", 0))
    height = int(v_stream.get("height", 0))

    failures = []
    
    # Check dimensions
    if width != 1080 or height != 1920:
        failures.append(f"Invalid dimensions: {width}x{height}, expected 1080x1920")

    # Check duration
    if not (15.0 <= duration <= 45.0):
        failures.append(f"Duration out of bounds: {duration:.2f}s (must be 15~45s)")

    # Check bitrate (must be >= 600 kbps)
    if bitrate < 600000:
        failures.append(f"Bitrate too low: {bitrate/1000:.1f} kbps (must be >= 600 kbps)")

    # 2. Extract 4 frames and check non-solid background
    qa_dir = vp.parent / "qc_frames"
    qa_dir.mkdir(parents=True, exist_ok=True)
    
    frame_cmd = [
        "ffmpeg", "-y", "-i", str(vp),
        "-vf", r"select='not(mod(n\,80))',scale=270:480",
        "-vframes", "4",
        "-vsync", "vfr",
        str(qa_dir / "frame_%02d.png")
    ]
    subprocess.run(frame_cmd, capture_output=True)

    extracted_frames = list(qa_dir.glob("frame_*.png"))
    if not extracted_frames:
        failures.append("Failed to extract QA frames")
    else:
        for f in extracted_frames:
            im = Image.open(f).convert("RGB")
            arr = np.array(im)
            std_dev = float(np.std(arr))
            # Solid/pure flat color has std dev < 15
            if std_dev < 15.0:
                failures.append(f"Frame {f.name} appears to be solid/flat color (std_dev={std_dev:.1f} < 15.0)")

    return {
        "passed": len(failures) == 0,
        "video_path": str(vp),
        "duration": duration,
        "bitrate_kbps": round(bitrate / 1000, 1),
        "resolution": f"{width}x{height}",
        "qc_frames": [str(x) for x in extracted_frames],
        "failures": failures
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 qc_video_gate.py <path_to_video>")
        sys.exit(1)
    result = run_qc(sys.argv[1])
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 2)
