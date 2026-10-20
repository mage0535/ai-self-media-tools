"""Identity-bound AUTO/VLM/WATCH evidence for a final video candidate."""
from __future__ import annotations

import hashlib
from pathlib import Path


class InvalidFinalQualityEvidence(ValueError):
    pass


def candidate_sha256(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise InvalidFinalQualityEvidence("final candidate is missing")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_final_quality_evidence(candidate: Path, evidence: dict) -> dict:
    digest = candidate_sha256(candidate)
    if evidence.get("version") != "final_quality_evidence_v1":
        raise InvalidFinalQualityEvidence("final quality evidence version is invalid")
    if evidence.get("candidate_sha256") != digest:
        raise InvalidFinalQualityEvidence("final quality evidence candidate hash mismatch")
    failures = []
    for channel in ("auto", "vlm", "watch"):
        item = evidence.get(channel)
        if not isinstance(item, dict):
            failures.append(f"{channel}_evidence_missing")
            continue
        if item.get("candidate_sha256") != digest:
            failures.append(f"{channel}_candidate_hash_mismatch")
        if item.get("passed") is not True:
            failures.append(f"{channel}_not_passed")
        if not str(item.get("evidence_path") or "").strip():
            failures.append(f"{channel}_evidence_path_missing")
    if failures:
        raise InvalidFinalQualityEvidence(",".join(failures))
    return {"passed": True, "candidate_sha256": digest, "channels": ["auto", "vlm", "watch"]}