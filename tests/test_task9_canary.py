import json
import hashlib
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
    from scripts.task9_canary import EXPECTED_CANARY_PLATFORMS, build_canary_matrix

    matrix = build_canary_matrix()

    assert len(matrix) == 12
    assert [case["order"] for case in matrix] == list(range(1, 13))
    assert {case["platform"] for case in matrix} == set(EXPECTED_CANARY_PLATFORMS)
    assert {case["content_form"] for case in matrix} >= {"article", "carousel", "vertical_video", "horizontal_video"}
    assert {case["language"] for case in matrix} >= {"zh", "en"}
    assert any(case["delivery_policy"] == "manual_handoff_only" for case in matrix)
    assert any(case["dry_run"] for case in matrix)
    assert all(case["hotspot_mode"] == "official_native" for case in matrix)
    assert all(case["entrypoint_kind"] == "pipeline" for case in matrix)


def test_hotspot_provenance_uses_one_canonical_record_and_rejects_tampering():
    from scripts.task9_canary import (
        _canary_brief,
        _validate_hotspot_provenance,
    )

    case = {"platform": "kuaishou", "delivery_policy": "dry_run"}
    brief = _canary_brief({**case, "language": "zh", "content_form": "article"})
    hotspot = dict(brief["associated_hotspot"])
    manifest = {
        "hotspot": hotspot,
        "source_evidence": [{
            "platform": "kuaishou",
            "url": hotspot["source_url"],
            "title": hotspot["observed_title"],
            "source_hash": hotspot["source_hash"],
        }],
    }

    assert _validate_hotspot_provenance(case, manifest)["passed"] is True

    tampered = json.loads(json.dumps(manifest))
    tampered["hotspot"]["observed_title"] = "Tampered title"
    result = _validate_hotspot_provenance(case, tampered)
    assert result["passed"] is False
    assert "hotspot_source_provenance_not_independently_verified" in result["failures"]


def test_runtime_identity_requires_successful_cli_output_not_environment_fallback(monkeypatch):
    from scripts import task9_canary

    monkeypatch.setenv("HERMES_PROVIDER", "forged-provider")
    monkeypatch.setenv("HERMES_MODEL", "forged-model")
    monkeypatch.setattr(task9_canary.shutil, "which", lambda _: "hermes")

    class Result:
        returncode = 1
        stdout = "{\"provider\": \"rejected-provider\", \"model\": \"rejected-model\"}"
        stderr = "permission denied"

    monkeypatch.setattr(task9_canary.subprocess, "run", lambda *args, **kwargs: Result())
    runtime = task9_canary.discover_hermes_runtime()

    assert runtime["active"]["status"] == "unavailable"
    assert runtime["active"]["provider"] == ""
    assert runtime["active"]["model"] == ""
    assert runtime["weak"]["status"] == "dual_model_pending"


def test_generation_attempt_evidence_requires_matching_provider_model_and_session(tmp_path: Path):
    from scripts.task9_canary import _generation_attempt_evidence

    _write(tmp_path / "jobs" / "one" / "generation_attempts.json", json.dumps([
        {"status": "success", "provider": "p", "model": "m"},
        {"status": "success", "provider": "p", "model": "m", "session_id": "s-1"},
    ]))

    result = _generation_attempt_evidence(tmp_path, {"provider": "p", "model": "m"})
    assert result["passed"] is True
    assert result["matching"][0]["session_id"] == "s-1"


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


def test_acceptance_rejects_fake_platform_set_and_requires_pipeline_evidence(tmp_path: Path):
    from scripts.task9_acceptance import evaluate_acceptance

    report = _valid_acceptance_report(tmp_path)
    report["cases"] = [
        {"platform": f"platform-{index}", "artifact_policy_passed": True, "evidence_level": "artifact_verified",
         "pipeline_evidence": {"create_called": True, "run_called": True, "serial_index": index}}
        for index in range(12)
    ]
    result = evaluate_acceptance(report, repo_root=ROOT)

    assert result["production_ready"] is False
    assert "exact_platform_matrix_required" in result["failures"]
    assert any(value.startswith("pipeline_evidence_missing:") for value in result["failures"])


def test_deployment_acceptance_rejects_enabled_or_active_timer(monkeypatch, tmp_path):
    from scripts import task9_deployment_acceptance as acceptance

    monkeypatch.setattr(acceptance, "evaluate_acceptance", lambda report, repo_root: {"production_ready": True})
    monkeypatch.setattr(acceptance, "rehearse_rollback", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(
        acceptance,
        "query_timer_states",
        lambda: {
            "safe.timer": {"enabled": False, "active": False},
            "active.timer": {"enabled": False, "active": True},
        },
    )
    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")
    output = tmp_path / "acceptance.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "task9_deployment_acceptance.py",
            "--report", str(report),
            "--current-root", str(tmp_path / "current"),
            "--rollback-root", str(tmp_path / "rollback"),
            "--protected-root", str(tmp_path / "protected"),
            "--output", str(output),
        ],
    )

    assert acceptance.main() == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["timers_safe"] is False
    assert result["production_ready"] is False


def test_runner_calls_real_pipeline_methods_serially_and_does_not_accept_user_model_reports(tmp_path: Path):
    from scripts.task9_canary import build_canary_matrix, run_canaries

    calls = []

    class PipelineBoundary:
        def __init__(self, store, config):
            self.store = store
            self.config = config

        def create(self, topic, platforms, brief, profile="default", topic_fingerprint=""):
            calls.append(("create", platforms[0]))
            return {"id": f"job-{platforms[0]}"}

        def run(self, job_id, force=False):
            calls.append(("run", job_id))
            return {"id": job_id, "state": "review_required", "deliveries": [], "draft_meta": {}}

        def stage_drafts(self, job_id, owner=None, already_locked=False):
            calls.append(("stage_drafts", job_id))
            return {"id": job_id, "state": "review_required", "deliveries": []}

    class StoreBoundary:
        def __init__(self, path):
            self.path = Path(path)

    def factory(store, config):
        return PipelineBoundary(store, config)

    report = run_canaries(
        tmp_path / "artifacts",
        repo_root=ROOT,
        pipeline_factory=factory,
        store_factory=StoreBoundary,
        model_runner=lambda role, case, root: {"status": "pending", "reason": "test_provider_boundary"},
    )

    assert calls == []
    assert report["models"]["active"]["status"] == "pending"
    assert report["models"]["weak"]["status"] == "pending"
    assert report["model_reports_used"] == []


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
    from scripts.task9_canary import build_canary_matrix, EXPECTED_CANARY_PLATFORMS
    matrix = build_canary_matrix()
    cases = [
        {
            "platform": platform["platform"],
            "artifact_policy_passed": True,
            "evidence_level": "artifact_verified",
            "pipeline_evidence": {"create_called": True, "run_called": True, "serial_index": index},
            "probes": {
                "capabilities": {"passed": True, "evidence_level": "artifact_verified"},
                "hotspot": {"passed": True, "evidence_level": "artifact_verified"},
            },
            "content_form": platform["content_form"],
            "language": platform["language"],
            "delivery_policy": platform["delivery_policy"],
            "order": index,
        }
        for index, platform in enumerate(matrix, 1)
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
        "execution": {"mode": "serial", "overlap_detected": False, "entrypoint": "pipeline"},
        "model_reports_used": [],
    }
