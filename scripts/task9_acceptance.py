"""Fail-closed Task9 production acceptance evaluator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.task9_canary import build_canary_matrix, EXPECTED_CANARY_PLATFORMS


REQUIRED_AUDITS = ("full_pytest", "privacy_audit", "license_audit")


def evaluate_acceptance(report: dict[str, Any], *, repo_root: Path | str | None = None) -> dict[str, Any]:
    failures: list[str] = []
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    expected = build_canary_matrix()
    if len(cases) != len(expected):
        failures.append("exactly_12_canary_cases_required")
    actual_platforms = [item.get("platform") for item in cases if isinstance(item, dict)]
    if actual_platforms != list(EXPECTED_CANARY_PLATFORMS):
        failures.append("exact_platform_matrix_required")
    if report.get("execution", {}).get("mode") != "serial" or report.get("execution", {}).get("overlap_detected") is not False:
        failures.append("serial_execution_evidence_missing")
    if report.get("execution", {}).get("entrypoint") != "pipeline":
        failures.append("pipeline_entrypoint_evidence_missing")
    for expected_case, item in zip(expected, cases):
        if not isinstance(item, dict):
            failures.append("case_record_invalid")
            continue
        for key in ("order", "platform", "content_form", "language", "delivery_policy"):
            if item.get(key) != expected_case.get(key):
                failures.append(f"case_matrix_mismatch:{expected_case['platform']}:{key}")
        evidence = item.get("pipeline_evidence") if isinstance(item.get("pipeline_evidence"), dict) else {}
        if evidence.get("create_called") is not True or evidence.get("run_called") is not True or evidence.get("serial_index") != expected_case["order"]:
            failures.append(f"pipeline_evidence_missing:{expected_case['platform']}")
        probes = item.get("probes") if isinstance(item.get("probes"), dict) else {}
        if item.get("artifact_policy_passed") is not True or item.get("evidence_level") != "artifact_verified":
            failures.append(f"artifact_policy_not_verified:{expected_case['platform']}")
        capability = probes.get("capabilities") if isinstance(probes.get("capabilities"), dict) else {}
        if capability.get("passed") is not True or capability.get("evidence_level") != "artifact_verified":
            failures.append(f"capability_artifact_evidence_missing:{expected_case['platform']}")
        hotspot = probes.get("hotspot") if isinstance(probes.get("hotspot"), dict) else {}
        if hotspot.get("passed") is not True or hotspot.get("evidence_level") != "artifact_verified":
            failures.append(f"hotspot_independent_evidence_missing:{expected_case['platform']}")
        details = hotspot.get("details") if isinstance(hotspot.get("details"), dict) else {}
        contract = expected_case.get("hotspot_contract") if isinstance(expected_case.get("hotspot_contract"), dict) else {}
        if details.get("evidence_type") not in set(contract.get("allowed_evidence_types") or []):
            failures.append(f"hotspot_evidence_type_mismatch:{expected_case['platform']}")
        if details.get("association_mode") not in set(contract.get("allowed_association_modes") or []):
            failures.append(f"hotspot_association_mode_mismatch:{expected_case['platform']}")
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
    if report.get("model_reports_used") not in ([], None):
        failures.append("user_supplied_model_attestation_forbidden")
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
