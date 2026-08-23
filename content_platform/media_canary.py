"""Measured non-publishing media artifact acceptance probe."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def _ffprobe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe_failed")
    return json.loads(result.stdout or "{}")


def probe_media_artifact(artifact_dir: str | Path) -> dict[str, Any]:
    root = Path(artifact_dir)
    final = root / "final.mp4"
    failures: list[str] = []
    if not final.is_file() or final.stat().st_size <= 0:
        return {"status": "failed", "failures": ["final_mp4_missing"]}
    try:
        probe = _ffprobe(final)
    except Exception as exc:
        return {"status": "failed", "failures": [f"ffprobe:{type(exc).__name__}"]}
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    if not any(item.get("codec_type") == "video" for item in streams if isinstance(item, dict)):
        failures.append("video_stream_missing")
    audio = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"), None)
    if not audio:
        failures.append("audio_stream_missing")
    elif str(audio.get("sample_rate") or "") != "44100" or int(audio.get("channels") or 0) != 2:
        failures.append("audio_spec_not_44100_stereo")
    try:
        if float((probe.get("format") or {}).get("duration") or 0) <= 0:
            failures.append("duration_missing")
    except (TypeError, ValueError):
        failures.append("duration_invalid")
    for evidence_name in ("av_alignment_evidence.json", "audio_quality_evidence.json", "render_quality_evidence.json"):
        path = root / evidence_name
        if not path.is_file():
            failures.append(f"{evidence_name}_missing")
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("passed") is not True:
                failures.append(f"{evidence_name}_failed")
        except (OSError, ValueError):
            failures.append(f"{evidence_name}_invalid")
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    return {"status": "artifact_verified" if not failures else "failed", "failures": failures, "sha256": f"sha256:{digest}", "probe": probe}
