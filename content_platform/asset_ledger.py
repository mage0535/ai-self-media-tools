"""Persistent source, license, semantic-fit, and reuse evidence for media assets."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


MIN_SEMANTIC_SCORE = 0.72
MAX_PERCEPTUAL_DISTANCE = 6


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_for_asset(path: Path) -> Image.Image:
    if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        return Image.open(path).convert("RGB")
    with tempfile.TemporaryDirectory() as temp_dir:
        frame = Path(temp_dir) / "frame.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(path), "-frames:v", "1", str(frame)],
            check=True,
            timeout=45,
        )
        return Image.open(frame).convert("RGB").copy()


def _perceptual_hash(path: Path) -> str:
    image = _image_for_asset(path).resize((9, 8))
    gray = image.convert("L")
    pixels = list(gray.get_flattened_data())
    bits = []
    for row in range(8):
        offset = row * 9
        bits.extend(pixels[offset + col] > pixels[offset + col + 1] for col in range(8))
    dhash = sum(1 << index for index, bit in enumerate(bits) if bit)
    colors = list(image.get_flattened_data())
    mean = tuple(round(sum(pixel[channel] for pixel in colors) / len(colors)) for channel in range(3))
    return f"{dhash:016x}{mean[0]:02x}{mean[1]:02x}{mean[2]:02x}"


def _distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


class AssetLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS asset_uses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                perceptual_hash TEXT NOT NULL,
                platform TEXT NOT NULL,
                work_id TEXT NOT NULL,
                scene_id TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL,
                license TEXT NOT NULL,
                semantic_tags_json TEXT NOT NULL DEFAULT '[]',
                used_at TEXT NOT NULL,
                UNIQUE(sha256, platform, work_id, scene_id)
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_sha ON asset_uses(sha256)")

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def uses(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM asset_uses ORDER BY id")]

    def register(self, rows: list[dict[str, Any]], platform: str, work_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO asset_uses(
                sha256,perceptual_hash,platform,work_id,scene_id,source_url,license,semantic_tags_json,used_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        row["sha256"], row["perceptual_hash"], platform, work_id,
                        str(row.get("scene_id") or ""), str(row.get("source_url") or ""),
                        str(row.get("license") or ""), json.dumps(row.get("semantic_tags") or [], ensure_ascii=False), now,
                    )
                    for row in rows
                ],
            )


def validate_asset_set(
    records: list[dict[str, Any]],
    platform: str,
    work_id: str,
    ledger: AssetLedger,
    *,
    register: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    normalized: list[dict[str, Any]] = []
    if not records:
        return {
            "passed": False,
            "platform": str(platform),
            "work_id": str(work_id),
            "assets": [],
            "failures": ["assets_missing"],
        }
    for index, record in enumerate(records, 1):
        path = Path(str(record.get("path") or "")).expanduser().resolve()
        prefix = str(record.get("scene_id") or f"asset_{index}")
        if not path.is_file():
            failures.append(f"{prefix}:asset_missing")
            continue
        source_url = str(record.get("source_url") or "")
        generated_source = source_url.startswith("generated:") and isinstance(record.get("generation_evidence"), dict) and bool(record.get("generation_evidence"))
        if not (source_url.startswith(("https://", "http://")) or generated_source):
            failures.append("asset_source_url_missing")
        if not str(record.get("license") or "").strip():
            failures.append("asset_license_missing")
        if float(record.get("semantic_match_score") or 0) < MIN_SEMANTIC_SCORE:
            failures.append("semantic_match_below_threshold")
        if not str(record.get("match_reason") or "").strip() or not record.get("semantic_tags"):
            failures.append("semantic_match_evidence_missing")
        try:
            normalized.append({
                **record,
                "path": str(path),
                "sha256": _sha256(path),
                "perceptual_hash": _perceptual_hash(path),
            })
        except (OSError, subprocess.SubprocessError, ValueError):
            failures.append(f"{prefix}:asset_probe_failed")

    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            if left["sha256"] == right["sha256"]:
                failures.append("within_work_exact_duplicate")
            elif _distance(left["perceptual_hash"], right["perceptual_hash"]) <= MAX_PERCEPTUAL_DISTANCE:
                failures.append("within_work_visual_duplicate")

    for current in normalized:
        for previous in ledger.uses():
            same = current["sha256"] == previous["sha256"]
            near = _distance(current["perceptual_hash"], previous["perceptual_hash"]) <= MAX_PERCEPTUAL_DISTANCE
            if not (same or near):
                continue
            if previous["platform"] != str(platform):
                failures.append("cross_platform_exact_duplicate" if same else "cross_platform_visual_duplicate")
            elif previous["work_id"] != str(work_id):
                failures.append("previous_work_asset_duplicate")

    result = {
        "passed": not failures,
        "platform": str(platform),
        "work_id": str(work_id),
        "assets": normalized,
        "failures": sorted(set(failures)),
    }
    if result["passed"] and register:
        ledger.register(normalized, str(platform), str(work_id))
    return result
