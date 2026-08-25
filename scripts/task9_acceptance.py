"""Fail-closed Task9 production acceptance evaluator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_AUDITS = ("full_pytest", "privacy_audit", "license_audit")


def evaluate_acceptance(report: dict[str, Any], *, repo_root: Path | str | None = None) -> dict[str, Any]:
    failures: list[str] = []
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    if len(cases) != 12:
        failures.append("exactly_12_canary_cases_required")
    if any(item.get("artifact_policy_passed") is not True for item in cases if isinstance(item, dict)):
        failures.append("all_cases_artifact_and_policy_pass_required")
    audits = report.get("audits") if isinstance(report.get("audits"), dict) else {}
    for name in REQUIRED_AUDITS:
        item = audits.get(name) if isinstance(audits.get(name), dict) else {}
        path = Path(str(item.get("path") or ""))
        if item.get("passed") is not True or not path.is_file():
            failures.append(f"audit_evidence_missing:{name}")
    parity = report.get("commit_parity") if isinstance(report.get("commit_parity"), dict) else {}
    endpoints = [str(parity.get(key) or "") for key in ("source", "release", "hermes")]
    if not all(endpoints) or len(set(endpoints)) != 1:
        failures.append("three_end_commit_parity_missing")
    rehearsal = report.get("rollback_rehearsal") if isinstance(report.get("rollback_rehearsal"), dict) else {}
    if rehearsal.get("passed") is not True:
        failures.append("rollback_rehearsal_missing")
    shadows = report.get("shadow_batches") if isinstance(report.get("shadow_batches"), list) else []
    if len(shadows) < 2 or any(item.get("passed") is not True or item.get("code_edits", 1) != 0 or item.get("manual_recovery", True) for item in shadows[:2] if isinstance(item, dict)):
        failures.append("two_clean_shadow_batches_required")
    models = report.get("models") if isinstance(report.get("models"), dict) else {}
    active = models.get("active") if isinstance(models.get("active"), dict) else {}
    weak = models.get("weak") if isinstance(models.get("weak"), dict) else {}
    if active.get("status") != "verified" or not active.get("provider") or not active.get("model"):
        failures.append("active_model_identity_unverified")
    if active.get("gate_passed") is not True:
        failures.append("active_model_gate_unverified")
    weak_pending = weak.get("status") == "dual_model_pending"
    if weak_pending:
        failures.append("weak_model_required")
    elif weak.get("status") != "verified" or not weak.get("provider") or not weak.get("model"):
        failures.append("weak_model_identity_unverified")
    elif weak.get("gate_passed") is not True:
        failures.append("weak_model_gate_unverified")
    gate = report.get("deterministic_gate_contract") if isinstance(report.get("deterministic_gate_contract"), dict) else {}
    active_gate = active.get("gate_contract_hash")
    weak_gate = weak.get("gate_contract_hash")
    if not gate.get("sha256") or active_gate != gate.get("sha256") or weak_gate != gate.get("sha256"):
        failures.append("model_gate_contract_mismatch")
    delivery = report.get("delivery_scenarios") if isinstance(report.get("delivery_scenarios"), dict) else {}
    if delivery and delivery.get("passed") is not True:
        failures.append("delivery_scenarios_failed")
    status = "production_ready" if not failures else ("dual_model_pending" if weak_pending else "blocked")
    return {
        "schema": "task9_acceptance_report_v1",
        "status": status,
        "production_ready": status == "production_ready",
        "failures": sorted(set(failures)),
        "repo_root": str(repo_root or ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-production-ready", action="store_true")
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    result = evaluate_acceptance(report, repo_root=Path(__file__).resolve().parents[1])
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["production_ready"] or not args.require_production_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
