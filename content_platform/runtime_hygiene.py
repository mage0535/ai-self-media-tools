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
        return {"archived": [], "reason": "disk_below_cleanup_threshold", "usage_percent": round(usage, 2)}
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, int(retention_days)) * 86400
    archive_dir = root / "runtime_archive" / datetime.now(timezone.utc).strftime("%Y%m%d")
    archived: list[str] = []
    for base in (root / "artifacts", root / "local_ops_kuaishou", root / "local_ops_douyin", root / "local_ops_tiktok"):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.name in PROTECTED_NAMES or path.suffix.casefold() not in REBUILDABLE_SUFFIXES:
                continue
            if path.stat().st_mtime > cutoff:
                continue
            archived.append(str(path))
            if not dry_run:
                target = archive_dir / path.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
    return {"archived": archived, "archive": str(archive_dir), "reason": "dry_run" if dry_run else "archived", "usage_percent": round(usage, 2)}
