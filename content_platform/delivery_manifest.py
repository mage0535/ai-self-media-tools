"""Immutable delivery-directory evidence for rendered media attempts.

The delivery set is intentionally stricter than a loose manifest: it binds the
exact relative file names and their bytes for one render attempt.  The manifest
file itself is excluded to avoid a self-referential hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

_MANIFEST_NAME = "delivery_manifest.json"
_IGNORED_NAMES = frozenset({
    _MANIFEST_NAME,
    "video_toolchain_runner_manifest.json",
    "trusted_run_manifest.json",
    "final_delivery_manifest.json",
    ".delivery.lock",
})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(path: Path, root: Path) -> str:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"delivery artifact must be inside root: {path}") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"invalid delivery artifact path: {path}")
    return relative.as_posix()


def _records_digest(records: list[dict[str, str]]) -> str:
    encoded = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in _IGNORED_NAMES:
            continue
        yield path


def build_delivery_manifest(
    root: Path,
    *,
    required_paths: Iterable[Path] = (),
    identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a deterministic manifest for every file in ``root``.

    ``required_paths`` is a contract assertion, not a filter: required files
    must exist and be inside the attempt directory, while all other real files
    are included as well.  This prevents an untracked extra artifact from being
    silently introduced after the manifest is created.
    """

    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"delivery root is not a directory: {root}")
    records: list[dict[str, str]] = []
    for path in _iter_files(root):
        records.append({"path": _relative_file(path, root), "sha256": _sha256(path)})
    records.sort(key=lambda item: item["path"])

    declared_paths = {item["path"] for item in records}
    for required in required_paths:
        relative = _relative_file(Path(required), root)
        path = root / relative
        if not path.is_file():
            raise ValueError(f"required delivery artifact missing: {relative}")
        if relative not in declared_paths:
            raise ValueError(f"required delivery artifact not recorded: {relative}")

    return {
        "version": "delivery_manifest_v1",
        "root": str(root),
        "identity": dict(identity or {}),
        "files": records,
        "artifact_set_sha256": _records_digest(records),
    }


def validate_delivery_manifest(root: Path, manifest: Mapping[str, object]) -> dict[str, object]:
    """Validate the manifest against the current attempt directory."""

    failures: list[str] = []
    root = Path(root).resolve()
    if manifest.get("version") != "delivery_manifest_v1":
        failures.append("delivery_manifest_version")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        failures.append("delivery_files_missing")
        raw_files = []

    expected: dict[str, str] = {}
    for raw in raw_files:
        if not isinstance(raw, Mapping):
            failures.append("delivery_file_record_invalid")
            continue
        relative = raw.get("path")
        declared_sha = raw.get("sha256")
        if not isinstance(relative, str) or not isinstance(declared_sha, str):
            failures.append("delivery_file_record_invalid")
            continue
        if relative in expected:
            failures.append(f"delivery_duplicate_file:{relative}")
            continue
        try:
            path = root / relative
            canonical = _relative_file(path, root)
        except ValueError:
            failures.append(f"delivery_file_outside_root:{relative}")
            continue
        if canonical != relative or not path.is_file():
            failures.append(f"delivery_file_missing:{relative}")
            continue
        actual_sha = _sha256(path)
        expected[relative] = declared_sha
        if actual_sha != declared_sha:
            failures.append(f"delivery_file_hash_mismatch:{relative}")

    actual_paths = {
        _relative_file(path, root)
        for path in _iter_files(root)
    }
    declared_paths = set(expected)
    for relative in sorted(actual_paths - declared_paths):
        failures.append("delivery_extra_files")
        break
    for relative in sorted(declared_paths - actual_paths):
        failures.append(f"delivery_file_missing:{relative}")

    ordered_records = [
        {"path": relative, "sha256": expected[relative]}
        for relative in sorted(expected)
    ]
    declared_set_sha = manifest.get("artifact_set_sha256")
    if not isinstance(declared_set_sha, str):
        failures.append("artifact_set_sha256_missing")
    elif declared_set_sha != _records_digest(ordered_records):
        failures.append("artifact_set_sha256_mismatch")
    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "artifact_set_sha256": _records_digest(ordered_records),
        "file_count": len(ordered_records),
    }


def validate_attempt_bundle(
    root: Path,
    *,
    expected_identity: Mapping[str, object] | None = None,
    require_runner: bool = True,
) -> dict[str, object]:
    """Validate one immutable attempt bundle without selecting a directory."""
    root = Path(root).resolve()
    failures: list[str] = []
    delivery_path = root / _MANIFEST_NAME
    if not delivery_path.is_file():
        return {"passed": False, "failures": ["delivery_manifest_missing"], "root": str(root)}
    try:
        delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"passed": False, "failures": ["delivery_manifest_invalid"], "root": str(root)}
    result = validate_delivery_manifest(root, delivery)
    failures.extend(str(item) for item in result.get("failures") or [])
    if Path(str(delivery.get("root") or "")).resolve() != root:
        failures.append("delivery_root_mismatch")
    identity = delivery.get("identity") if isinstance(delivery.get("identity"), Mapping) else {}
    for key, expected in (expected_identity or {}).items():
        if expected not in (None, "") and str(identity.get(key) or "") != str(expected):
            failures.append(f"identity_mismatch:{key}")
    runner = {}
    runner_path = root / "video_toolchain_runner_manifest.json"
    if require_runner:
        if not runner_path.is_file():
            failures.append("runner_manifest_missing")
        else:
            try:
                runner = json.loads(runner_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                failures.append("runner_manifest_invalid")
            if runner.get("artifact_set_sha256") != delivery.get("artifact_set_sha256"):
                failures.append("runner_artifact_set_mismatch")
    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "root": str(root),
        "identity": dict(identity),
        "artifact_set_sha256": delivery.get("artifact_set_sha256"),
        "delivery": delivery,
        "runner": runner,
    }
