"""Run-scoped operational evidence and direction-level topic safeguards."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def _run_path(root: Path, date: str) -> Path:
    return root / "data" / "ops_runs" / str(date) / "run_manifest.json"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(str(value), "%Y%m%d")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def create_run(root: Path, date: str, lookback_days: int = 7) -> dict:
    """Create or return a date-scoped run manifest without replacing evidence."""
    path = _run_path(Path(root), date)
    if path.is_file():
        return _read(path)
    manifest = {
        "version": 1,
        "date": str(date),
        "lookback_days": int(lookback_days),
        "direction_register": [],
        "assets": [],
        "quality_gate_result": {},
        "exceptions": [],
    }
    _write(path, manifest)
    return manifest


def _normalized_direction(topic: str, direction: str) -> str:
    explicit = re.sub(r"[^a-z0-9_\-]+", "_", str(direction or "").casefold()).strip("_")
    if explicit:
        return explicit
    text = str(topic or "").casefold()
    domains = {
        "code_review": ("code review", "review bot", "代码审查", "代码评审"),
        "unit_testing": ("unit test", "testing", "测试", "单元测试"),
        "prompt_engineering": ("prompt", "提示词"),
        "agent_workflow": ("ai agent", "agent workflow", "智能体", "工作流"),
        "video_creation": ("video", "shorts", "剪辑", "视频"),
        "spreadsheet_cleanup": ("spreadsheet", "excel", "表格"),
    }
    for name, words in domains.items():
        if any(word in text for word in words):
            return name
    return re.sub(r"\s+", " ", text).strip()[:80]


def _recent_records(root: Path, date: str, lookback_days: int) -> list[dict]:
    cutoff = _parse_date(date).date().toordinal() - lookback_days
    records: list[dict] = []
    for path in (Path(root) / "data" / "ops_runs").glob("*/run_manifest.json"):
        try:
            manifest = _read(path)
            run_date = str(manifest.get("date") or path.parent.name)
            if _parse_date(run_date).date().toordinal() < cutoff:
                continue
            records.extend(item for item in manifest.get("direction_register", []) if isinstance(item, dict))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return records


def _independent_evidence(record: dict) -> bool:
    """Require a platform-specific evidence chain before allowing natural overlap."""
    evidence = record.get("source_evidence") if isinstance(record, dict) else {}
    if not isinstance(evidence, dict):
        return False
    successful = evidence.get("successful_sources") or 0
    if isinstance(successful, list):
        successful = len(successful)
    attempted = evidence.get("attempted_sources") or 0
    if isinstance(attempted, list):
        attempted = len(attempted)
    return (
        bool(str(evidence.get("source_matrix_id") or "").strip())
        and int(attempted) >= 8
        and int(successful) >= 5
        and evidence.get("platform_internal_verified") is True
        and len(str(evidence.get("platform_signal") or "").strip()) >= 8
        and len(str(evidence.get("platform_adaptation_reason") or "").strip()) >= 8
    )


def _independent_overlap(records: list[dict]) -> bool:
    source_ids = {
        str((record.get("source_evidence") or {}).get("source_matrix_id") or "").strip()
        for record in records
        if isinstance(record, dict)
    }
    return len(records) >= 2 and len(source_ids) == len(records) and all(_independent_evidence(record) for record in records)


def record_topic(
    root: Path,
    date: str,
    platform: str,
    topic: str,
    *,
    direction: str = "",
    follow_up_to: str = "",
    difference_angle: str = "",
    recap_reason: str = "",
    source_evidence: dict | None = None,
) -> dict:
    """Record a topic direction while allowing evidence-backed natural overlap."""
    root = Path(root)
    manifest = create_run(root, date)
    normalized = _normalized_direction(topic, direction)
    conflicts = [
        item
        for item in _recent_records(root, date, int(manifest["lookback_days"]))
        if str(item.get("direction") or "") == normalized
    ]
    documented_follow_up = bool(follow_up_to and difference_angle and recap_reason)
    record = {
        "platform": str(platform),
        "topic": str(topic),
        "direction": normalized,
        "follow_up_to": str(follow_up_to),
        "difference_angle": str(difference_angle),
        "recap_reason": str(recap_reason),
        "source_evidence": dict(source_evidence or {}),
    }
    independent_overlap = bool(conflicts) and _independent_overlap([*conflicts, record])
    failed_dimensions = [] if not conflicts or documented_follow_up or independent_overlap else ["direction_already_selected"]
    record["overlap_mode"] = "independent_evidence" if independent_overlap else ("documented_follow_up" if documented_follow_up else "distinct_direction")
    accepted = not failed_dimensions
    if accepted:
        manifest["direction_register"].append(record)
        _write(_run_path(root, date), manifest)
    return {
        "accepted": accepted,
        "date": str(date),
        "record": record,
        "conflicts": conflicts,
        "failed_dimensions": failed_dimensions,
        "manifest_path": str(_run_path(root, date)),
    }


def direction_register_issues(root: Path, date: str) -> list[dict]:
    """Report manually edited or legacy manifests that bypassed topic recording."""
    path = _run_path(Path(root), date)
    if not path.is_file():
        return []
    try:
        records = _read(path).get("direction_register") or []
    except (OSError, json.JSONDecodeError):
        return [{"failed_dimensions": ["direction_register_invalid"]}]
    grouped: dict[str, list[dict]] = {}
    for record in records:
        if isinstance(record, dict) and str(record.get("direction") or ""):
            grouped.setdefault(str(record["direction"]), []).append(record)
    issues = []
    for direction, entries in grouped.items():
        if _independent_overlap(entries):
            continue
        unresolved = [item for item in entries[1:] if not (item.get("follow_up_to") and item.get("difference_angle") and item.get("recap_reason"))]
        if unresolved:
            issues.append(
                {
                    "failed_dimensions": ["direction_register_duplicate"],
                    "direction": direction,
                    "platforms": [str(item.get("platform") or "") for item in entries],
                }
            )
    return issues
