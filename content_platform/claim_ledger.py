"""Evidence-backed factual claim validation before media generation."""

from __future__ import annotations

import re
from typing import Any


NUMERIC_CLAIM = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|小时|分钟|秒|天|周|个月|年|元|万|亿|ms|seconds?|minutes?|hours?|days?|weeks?|months?|years?))",
    re.I,
)
FIRST_PERSON_OPERATION = re.compile(
    r"(?:我(?:实测|测试|运行|用了|使用|部署|发布|修复|运营)|\bI\s+(?:tested|ran|used|deployed|published|fixed|operated)\b)",
    re.I,
)


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[。！？!?])|\n+", str(text or "")) if item.strip()]


def _valid_evidence(row: dict[str, Any], *, first_person: bool) -> bool:
    source = str(row.get("source_url") or "").strip()
    evidence = str(row.get("evidence_path") or "").strip()
    if row.get("verified") is not True:
        return False
    if not (source.startswith("https://") or source.startswith("http://")):
        return False
    return bool(evidence) if first_person else True


def _covered(sentence: str, ledger: list[dict[str, Any]], *, first_person: bool) -> bool:
    normalized = re.sub(r"\s+", "", sentence).casefold()
    for row in ledger:
        claim = re.sub(r"\s+", "", str(row.get("claim") or "")).casefold()
        if claim and (claim in normalized or normalized in claim) and _valid_evidence(row, first_person=first_person):
            return True
    return False


def validate_claims(text: str, ledger: list[dict[str, Any]] | None) -> dict[str, Any]:
    ledger = [row for row in (ledger or []) if isinstance(row, dict)]
    failures: list[str] = []
    findings: list[dict[str, Any]] = []
    if str(text or "").count("```") % 2:
        failures.append("malformed_code_fence")
    for sentence in _sentences(text):
        if NUMERIC_CLAIM.search(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "numeric", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_numeric_claim")
        if FIRST_PERSON_OPERATION.search(sentence):
            covered = _covered(sentence, ledger, first_person=True)
            findings.append({"type": "first_person_operation", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_first_person_operation")
    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "findings": findings,
        "ledger_count": len(ledger),
    }
