import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, value: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")
    return path


def test_canary_matrix_is_serial_and_covers_required_platform_forms_and_languages():
    from scripts.task9_canary import build_canary_matrix

    matrix = build_canary_matrix()

    assert len(matrix) == 12
    assert [case["order"] for case in matrix] == list(range(1, 13))
    assert len({case["platform"] for case in matrix}) == 12
    assert {case["content_form"] for case in matrix} >= {"article", "carousel", "vertical_video", "horizontal_video"}
    assert {case["language"] for case in matrix} >= {"zh", "en"}
    assert any(case["delivery_policy"] == "manual_handoff_only" for case in matrix)
    assert any(case["dry_run"] for case in matrix)
    assert all(case["hotspot_mode"] == "official_native" for case in matrix)


def test_canary_artifact_probe_uses_actual_file_hashes_and_contract_evidence(tmp_path: Path):
    from scripts.task9_canary import probe_artifacts

    cover = _write(tmp_path / "cover.jpg", b"cover-bytes")
    manifest = {
        "artifacts": [{"path": "cover.jpg", "sha256": "wrong"}],
        "probe_evidence": {"cover": {"safe_zone_verified": True}},
    }
    _write(tmp_path / "artifact_manifest.json", json.dumps(manifest))

    result = probe_artifacts({"content_form": "article", "platform": "wechat"}, tmp_path)

    assert result["passed"] is False
    assert "artifact_hash_mismatch:cover.jpg" in result["failures"]
    assert result["input_output_hashes"]["cover.jpg"]
    assert result["probes"]["cover"]["evidence_level"] == "declared"


def test_delivery_scenarios_use_real_ledger_and_prove_unknown_boundaries(tmp_path: Path):
    from scripts.task9_canary import run_delivery_scenarios

    result = run_delivery_scenarios(tmp_path / "delivery.db")

    assert result["passed"] is True
    assert result["scenarios"]["crash_boundary"]["status"] == "unknown"
    assert result["scenarios"]["delayed_visibility"]["status"] == "published"
    assert result["scenarios"]["unknown_requires_review"]["retry_allowed"] is False
    assert result["scenarios"]["duplicate_schedule_prevention"]["same_intent"] is True
    assert result["scenarios"]["kuaishou_exact_postcheck"]["passed"] is True


def test_acceptance_refuses_production_ready_when_weak_model_is_unavailable(tmp_path: Path):
    from scripts.task9_acceptance import evaluate_acceptance

    report = _valid_acceptance_report(tmp_path)
    report["models"]["weak"] = {"status": "dual_model_pending", "reason": "no available second model"}

    result = evaluate_acceptance(report, repo_root=ROOT)

    assert result["status"] == "dual_model_pending"
    assert result["production_ready"] is False
    assert "weak_model_required" in result["failures"]


def test_acceptance_requires_all_evidence_before_production_ready(tmp_path: Path):
    from scripts.task9_acceptance import evaluate_acceptance

    result = evaluate_acceptance(_valid_acceptance_report(tmp_path), repo_root=ROOT)

    assert result["status"] == "production_ready"
    assert result["production_ready"] is True
    assert result["failures"] == []


def test_rollback_dry_run_preserves_db_cookies_and_media(tmp_path: Path):
    from scripts.task9_rollback import rehearse_rollback

    protected = {
        "db": _write(tmp_path / "data" / "state.db", b"db"),
        "cookies": _write(tmp_path / "cookies" / "session.json", b"cookie"),
        "media": _write(tmp_path / "media" / "final.mp4", b"media"),
    }
    before = {name: path.read_bytes() for name, path in protected.items()}

    result = rehearse_rollback(tmp_path / "current", tmp_path / "rollback", dry_run=True, protected_root=tmp_path)

    assert result["passed"] is True
    assert result["dry_run"] is True
    assert {name: path.read_bytes() for name, path in protected.items()} == before


def _valid_acceptance_report(tmp_path: Path) -> dict:
    from scripts.task9_canary import DETERMINISTIC_GATE_NAMES

    gate_hash = __import__("hashlib").sha256(json.dumps(DETERMINISTIC_GATE_NAMES, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()
    evidence = {}
    for name in ("full_pytest", "privacy_audit", "license_audit"):
        path = _write(tmp_path / f"{name}.json", json.dumps({"passed": True}))
        evidence[name] = {"passed": True, "path": str(path)}
    cases = [
        {"platform": f"platform-{index}", "artifact_policy_passed": True, "evidence_level": "artifact_verified"}
        for index in range(12)
    ]
    return {
        "cases": cases,
        "audits": evidence,
        "commit_parity": {"source": "abc", "release": "abc", "hermes": "abc"},
        "rollback_rehearsal": {"passed": True},
        "shadow_batches": [
            {"passed": True, "code_edits": 0, "manual_recovery": False},
            {"passed": True, "code_edits": 0, "manual_recovery": False},
        ],
        "models": {
            "active": {"status": "verified", "provider": "dynamic", "model": "dynamic", "gate_passed": True, "gate_contract_hash": gate_hash},
            "weak": {"status": "verified", "provider": "dynamic", "model": "dynamic", "gate_passed": True, "gate_contract_hash": gate_hash},
        },
        "deterministic_gate_contract": {"sha256": gate_hash},
    }
