"""Hard gates in front of the Kuaishou scheduled auto-post (owner 11-10 CST).

Kuaishou is the only platform that posts without a person. ``schedule_kuaishou`` calls
``evaluate_publish_gates`` right before it builds a packet; any failure means no packet,
no upload, and one ``publish_log.json`` report. The gates repeat checks the pipeline already
ran, on purpose: the publish function must hold even if it is reached some other way.

1. Kill switch: ``/etc/hermes/kuaishou-autopublish.enabled`` must exist (fail closed).
2. Body visual: the five body_visual codes on the final mp4, plus any kf_freeze/motion
   exemption in the result record.
3. Independent cover: a registered cover image that is not a frame of the body video
   (pHash distance to sampled body frames) with ``cover_evidence.json``.
4. Kuaishou ops: heat, strategy and checklist generated for this Kuaishou task only;
   ``OPS_PASS`` is computed here, never copied from input.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_FLAG = "/etc/hermes/kuaishou-autopublish.enabled"
# 64-bit pHash; a cover that is a body frame (or a frame with a small overlay) lands within this distance.
COVER_FRAME_MAX_DISTANCE = 10
COVER_FRAME_SAMPLES = 12
COVER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def flag_path() -> Path:
    """Overridable only for tests and isolated replays; production uses the default path."""
    return Path(os.environ.get("KUAISHOU_AUTOPUBLISH_FLAG") or DEFAULT_FLAG)


def kill_switch_gate() -> dict[str, Any]:
    path = flag_path()
    return {"passed": path.is_file(), "flag": str(path),
            **({} if path.is_file() else {"code": "KUAISHOU_AUTOPUBLISH_DISABLED"})}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def body_visual_publish_gate(video: Path, result: dict[str, Any]) -> dict[str, Any]:
    from .body_visual_gate import MOTION_FALLBACK_BLOCKS_QUALIFIED, evaluate_body_visual, motion_blocks_delivery

    visual = evaluate_body_visual(video, platform="kuaishou")
    codes = [str(code) for code in visual.get("failed_codes") or []]
    if visual.get("passed") is not True and not codes:
        codes.append("BODY_VISUAL_EVIDENCE_MISSING")
    records = [result] + [item for item in (result.get("artifacts") or []) if isinstance(item, dict)]
    if any(motion_blocks_delivery(record) for record in records) and MOTION_FALLBACK_BLOCKS_QUALIFIED not in codes:
        codes.append(MOTION_FALLBACK_BLOCKS_QUALIFIED)
    return {"passed": not codes, "failed_codes": codes, "frames_sampled": visual.get("frames_sampled", 0),
            "video": str(video)}


def find_cover(result: dict[str, Any], render_dir: Path) -> Path | None:
    """The registered cover artifact first, then a cover* image next to final.mp4. Never a video frame."""
    rows = [item for item in (result.get("artifacts") or []) if isinstance(item, dict)]
    candidates = [Path(str(item.get("path") or "")) for item in rows if str(item.get("kind") or "").casefold() == "cover"]
    candidates += [Path(str(item.get("path") or "")) for item in rows
                   if Path(str(item.get("path") or "")).stem.casefold().startswith("cover")]
    candidates += sorted(path for path in render_dir.glob("cover*") if path.suffix.casefold() in COVER_SUFFIXES)
    return next((path for path in candidates if path.suffix.casefold() in COVER_SUFFIXES and path.is_file()), None)


def _frame_phashes(video: Path, samples: int) -> list[str]:
    from .repost_dedup import _image_phash, _video_duration

    duration = _video_duration(video)
    hashes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ks-cover-guard-") as directory:
        for index in range(samples):
            frame = Path(directory) / f"f{index:02d}.png"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{duration * (index + 0.5) / samples:.3f}",
                            "-i", str(video), "-frames:v", "1", "-vf", "scale=64:64", "-y", str(frame)],
                           capture_output=True, timeout=60, check=False)
            if frame.is_file():
                hashes.append(_image_phash(frame))
    return hashes


def _distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def cover_gate(result: dict[str, Any], video: Path, render_dir: Path, evidence_dir: Path) -> dict[str, Any]:
    from PIL import Image

    from .repost_dedup import _image_phash

    cover = find_cover(result, render_dir)
    if cover is None:
        return {"passed": False, "code": "COVER_MISSING"}
    try:
        with Image.open(cover) as image:
            width, height = image.size
        cover_hash = _image_phash(cover)
        frame_hashes = _frame_phashes(video, COVER_FRAME_SAMPLES)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"passed": False, "code": "COVER_EVIDENCE_MISSING", "cover_path": str(cover), "error": str(exc)[:200]}
    if not frame_hashes:
        return {"passed": False, "code": "COVER_EVIDENCE_MISSING", "cover_path": str(cover), "error": "no body frames sampled"}
    min_distance = min(_distance(cover_hash, value) for value in frame_hashes)
    quality = render_dir / "cover_quality_evidence.json"
    evidence = {
        "cover_path": str(cover.resolve()),
        "cover_sha256": sha256_file(cover),
        "width": width,
        "height": height,
        "cover_phash": cover_hash,
        "body_frames_sampled": len(frame_hashes),
        "min_phash_distance_to_body": min_distance,
        "max_distance_counted_as_frame": COVER_FRAME_MAX_DISTANCE,
        "is_body_frame": min_distance <= COVER_FRAME_MAX_DISTANCE,
        "validate_cover_evidence": str(quality) if quality.is_file() else "",
        "algorithm": "phash_dct_32x32_64bit",
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "cover_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = not evidence["is_body_frame"]
    return {"passed": passed, **({} if passed else {"code": "COVER_SCREENSHOT_FORBIDDEN"}),
            "cover_path": evidence["cover_path"], "cover_sha256": evidence["cover_sha256"],
            "min_phash_distance_to_body": min_distance, "evidence": str(evidence_dir / "cover_evidence.json")}


def build_kuaishou_ops(task: dict[str, Any], formatted: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Kuaishou-only ops from this task's own evidence. Missing evidence stays missing; nothing is filled in."""
    brief = task.get("brief") if isinstance(task.get("brief"), dict) else {}
    selection_mode = str(task.get("selection_mode") or brief.get("selection_mode") or "")
    heat: dict[str, Any] = {}
    trend = task.get("trend_candidate") or brief.get("trend_candidate")
    if selection_mode == "editorial_calendar" and (task.get("editorial_evidence") or brief.get("editorial_evidence")):
        heat = {"mode": "editorial_calendar", "evidence": task.get("editorial_evidence") or brief.get("editorial_evidence")}
    elif isinstance(trend, dict) and trend and (task.get("trend_candidate_gate") or {}).get("passed") is True:
        heat = {"mode": selection_mode or "trend", "trend_candidate": trend,
                "score": (brief.get("topic_decision") or {}).get("score")}
    strategy: dict[str, Any] = {}
    blueprint = brief.get("content_blueprint")
    topic = str(brief.get("topic") or task.get("topic") or formatted.get("title") or "").strip()
    if topic and (blueprint or brief.get("scenario")):
        strategy = {"topic": topic, "lane": brief.get("lane") or "", "content_blueprint": blueprint or {},
                    "scenario": brief.get("scenario") or {}}
    title = str(formatted.get("title") or "").strip()
    caption = str(formatted.get("caption") or "").strip()
    tags = [str(tag).lstrip("#") for tag in (formatted.get("hashtags") or []) if str(tag).strip("# ")]
    checklist = [
        {"item": "platform_is_kuaishou", "passed": str(task.get("platform") or "").casefold() == "kuaishou"},
        {"item": "title_present_le_30", "passed": 0 < len(title) <= 30},
        {"item": "caption_present", "passed": bool(caption)},
        {"item": "tags_1_to_3", "passed": 1 <= len(tags[:3]) <= 3},
    ]
    return {"platform": "kuaishou", "job_id": str(task.get("job_id") or ""),
            "date_cst": f"{now.astimezone(ZoneInfo('Asia/Shanghai')):%Y-%m-%d}",
            "heat": heat, "strategy": strategy, "checklist": checklist}


def ops_gate(ops: dict[str, Any]) -> dict[str, Any]:
    missing = [name for name in ("heat", "strategy", "checklist") if not ops.get(name)]
    if str(ops.get("platform") or "") != "kuaishou":
        missing.append("platform")
    failed_items = [row.get("item") for row in ops.get("checklist") or [] if row.get("passed") is not True]
    passed = not missing and not failed_items
    return {"passed": passed, "OPS_PASS": passed, "missing": missing, "failed_checklist": failed_items,
            **({} if passed else {"code": "KUAISHOU_OPS_INCOMPLETE"})}


def write_publish_log(out_dir: Path, record: dict[str, Any], ledger: Path | None = None) -> Path:
    """One report per call (blocked or scheduled) plus one ledger line beside the job directories."""
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {"time_cst": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"), **record}
    path = out_dir / "publish_log.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger = ledger or out_dir.parent / "autopublish_ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({key: record.get(key) for key in (
            "time_cst", "job_id", "decision", "reason", "schedule_time", "title", "video_sha256", "cover_sha256")},
            ensure_ascii=False) + "\n")
    return path
