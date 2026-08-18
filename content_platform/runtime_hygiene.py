"""Conservative cleanup for reproducible media intermediates."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REBUILDABLE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".ass", ".srt", ".tmp", ".log"}
PROTECTED_NAMES = {"final.mp4", "cover.png", "cover.jpg", "scene_manifest.json", "tts_config.json", "acceptance_summary.json", "publish_info.json", "quality_report.json"}


def cleanup_runtime(data_dir: str | Path, *, retention_days: int = 14, dry_run: bool = True, disk_usage_percent: float | None = None, threshold_percent: float = 80) -> dict[str, Any]:
    root = Path(data_dir)
    usage = float(disk_usage_percent) if disk_usage_percent is not None else shutil.disk_usage(root).used * 100 / shutil.disk_usage(root).total
    if usage < threshold_percent:
        return {"removed": [], "bytes_removed": 0, "reason": "disk_below_cleanup_threshold", "usage_percent": round(usage, 2)}
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, int(retention_days)) * 86400
    removed: list[str] = []
    bytes_removed = 0
    # Only generated intermediates are eligible. Local-ops and handoff roots
    # may contain the operator's only publishable copy and are never scanned.
    for base in (root / "artifacts", root / "tmp"):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.name in PROTECTED_NAMES or path.suffix.casefold() not in REBUILDABLE_SUFFIXES:
                continue
            if path.stat().st_mtime > cutoff:
                continue
            removed.append(str(path))
            if not dry_run:
                bytes_removed += path.stat().st_size
                path.unlink()
    return {"removed": removed, "bytes_removed": bytes_removed, "reason": "dry_run" if dry_run else "removed", "usage_percent": round(usage, 2)}
