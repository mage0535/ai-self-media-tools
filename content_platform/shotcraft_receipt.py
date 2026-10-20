"""Fail-closed validation for real Shotcraft/Cinema shot execution receipts."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,pix_fmt",
        "-of", "json", str(path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")
    payload = json.loads(proc.stdout)
    streams = payload.get("streams") or []
    video = next((row for row in streams if row.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("video stream missing")
    return {
        "returncode": 0,
        "duration_seconds": round(float((payload.get("format") or {}).get("duration") or 0), 3),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": str(video.get("codec_name") or ""),
        "pix_fmt": str(video.get("pix_fmt") or ""),
        "audio_stream_present": any(row.get("codec_type") == "audio" for row in streams),
    }


def build_shotcraft_execution_receipt(root: Path, evidence: dict[str, Any], *, identity: dict[str, Any] | None = None, plan_sha256: str = "") -> dict[str, Any]:
    root = Path(root).resolve()
    receipt: dict[str, Any] = {
        "receipt_version": "shotcraft_execution_receipt_v2",
        "identity": dict(identity or {}),
        "shotcraft_plan_sha256": plan_sha256,
        "segments": [],
    }
    failures: list[str] = []
    names: set[str] = set()
    for segment in evidence.get("segments") or []:
        row = dict(segment)
        outputs = []
        for output in segment.get("shot_outputs") or []:
            name = str(output.get("name") or "")
            raw = Path(str(output.get("path") or ""))
            path = raw if raw.is_absolute() else root / raw
            try:
                relative = path.resolve().relative_to(root).as_posix()
            except ValueError:
                failures.append(f"output_outside_root:{name}")
                continue
            item = dict(output)
            item["path"] = relative
            item["sha256"] = _sha256(path) if path.is_file() else ""
            try:
                item["ffprobe"] = _probe(path)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                item["ffprobe"] = {"returncode": 1}
                failures.append(f"shot_probe_failed:{name}")
            if name in names:
                failures.append(f"duplicate_shot_name:{name}")
            names.add(name)
            if not path.is_file():
                failures.append(f"shot_missing:{name}")
            if bool(item.get("fallback")) or str(item.get("renderer") or "") == "still-motion":
                failures.append(f"degraded_shot:{name}")
            outputs.append(item)
        row["shot_outputs"] = outputs
        row["shotcraft_execution_receipt"] = {
            "version": "shotcraft_execution_receipt_v2",
            "planned_move_id": row.get("move_id"),
            "profile": row.get("profile"),
            "output_count": len(outputs),
            "all_outputs_bound": bool(outputs) and not any(not item.get("sha256") for item in outputs),
        }
        if row["shotcraft_execution_receipt"]["planned_move_id"] != row.get("move_id"):
            failures.append(f"move_binding_failed:{row.get('index')}")
        receipt["segments"].append(row)
    final = root / "final.mp4"
    if final.is_file():
        receipt["final_video"] = {"path": "final.mp4", "sha256": _sha256(final), "ffprobe": _probe(final)}
    else:
        receipt["final_video"] = {"path": "final.mp4", "sha256": "", "ffprobe": {"returncode": 1}}
        failures.append("final_video_missing")
    receipt["passed"] = not failures and len(names) == sum(len(row.get("shot_outputs") or []) for row in receipt["segments"])
    receipt["failures"] = failures
    return receipt


def validate_shotcraft_execution_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    failures: list[str] = []
    names: set[str] = set()
    for segment in receipt.get("segments") or []:
        for output in segment.get("shot_outputs") or []:
            name = str(output.get("name") or "")
            path = root / str(output.get("path") or "")
            if name in names:
                failures.append(f"duplicate_shot_name:{name}")
            names.add(name)
            try:
                path.resolve().relative_to(root)
                actual_sha = _sha256(path)
                probe = _probe(path)
                if actual_sha != output.get("sha256"):
                    failures.append(f"shot_sha_mismatch:{name}")
                if float(probe.get("duration_seconds") or 0) <= 0:
                    failures.append(f"shot_duration_invalid:{name}")
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                failures.append(f"shot_invalid:{name}")
            if output.get("fallback") or output.get("renderer") == "still-motion":
                failures.append(f"degraded_shot:{name}")
    final = receipt.get("final_video") or {}
    final_path = root / str(final.get("path") or "final.mp4")
    try:
        if _sha256(final_path) != final.get("sha256"):
            failures.append("final_video_sha_mismatch")
        _probe(final_path)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
        failures.append("final_video_invalid")
    return {"passed": not failures and receipt.get("passed") is True, "failures": failures}
