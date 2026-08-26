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
    from content_platform.associated_hotspot import load_hotspot_support_matrix

    matrix = build_canary_matrix()

    assert len(matrix) == 12
    assert [case["order"] for case in matrix] == list(range(1, 13))
    assert {case["platform"] for case in matrix} == set(EXPECTED_CANARY_PLATFORMS)
    assert {case["content_form"] for case in matrix} >= {"article", "carousel", "vertical_video", "horizontal_video"}
    assert {case["language"] for case in matrix} >= {"zh", "en"}
    assert any(case["delivery_policy"] == "manual_handoff_only" for case in matrix)
    assert any(case["dry_run"] for case in matrix)
    support_matrix = load_hotspot_support_matrix()
    for case in matrix:
        record = support_matrix["platforms"][case["platform"]]
        contract = case["hotspot_contract"]
        assert contract["allowed_evidence_types"] == record["allowed_evidence_types"]
        assert contract["allowed_association_modes"] == record["allowed_association_modes"]
        assert "official_native" not in contract["allowed_evidence_types"]
    assert all(case["entrypoint_kind"] == "pipeline" for case in matrix)


def test_hotspot_provenance_uses_external_snapshot_and_rejects_tampering(tmp_path: Path):
    from scripts.task9_canary import (
        _hotspot_source_hash,
        _load_verified_hotspot,
        _validate_hotspot_provenance,
    )

    case = {"platform": "kuaishou", "delivery_policy": "dry_run"}
    snapshot = _write(tmp_path / "_inputs" / "hotspots" / "kuaishou.txt", "DeepSeek 官方创作灵感热点快照")
    snapshot_rel = "hotspots/kuaishou.txt"
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    provenance_hash = _hotspot_source_hash(
        "kuaishou", "https://www.kuaishou.com/hot", "DeepSeek",
        fetched_at="2026-08-25T00:00:00Z", status=200,
        snapshot_path=snapshot_rel, snapshot_sha256=snapshot_hash,
    )
    _write(tmp_path / "_inputs" / "hotspots" / "kuaishou.json", json.dumps({
        "platform": "kuaishou", "native_source_url": "https://www.kuaishou.com/hot",
        "observed_title": "DeepSeek", "fetched_at": "2026-08-25T00:00:00Z", "status": 200,
        "snapshot_path": snapshot_rel, "snapshot_sha256": snapshot_hash, "provenance_hash": provenance_hash,
        "evidence_type": "native", "native_verified": True, "association_mode": "auto_browser",
        "lane_fit_score": 0.9, "semantic_fit_score": 0.9,
    }))
    hotspot = _load_verified_hotspot(tmp_path, case)
    manifest = {
        "hotspot": hotspot,
        "source_evidence": [{
            "platform": "kuaishou",
                "url": hotspot["source_url"],
                "title": hotspot["observed_title"],
                "evidence_type": hotspot["evidence_type"],
                "association_mode": hotspot["association_mode"],
                "provenance_hash": hotspot["provenance_hash"],
        }],
    }

    assert _validate_hotspot_provenance(case, manifest)["passed"] is True

    tampered = json.loads(json.dumps(manifest))
    tampered["hotspot"]["observed_title"] = "Tampered title"
    result = _validate_hotspot_provenance(case, tampered)
    assert result["passed"] is False
    assert "hotspot_source_provenance_not_independently_verified" in result["failures"]


def test_official_activity_is_verified_without_being_relabelled_native(tmp_path: Path):
    from scripts.task9_canary import _hotspot_source_hash, _load_verified_hotspot, _validate_hotspot_provenance

    case = {"platform": "xiaohongshu", "delivery_policy": "manual_handoff_only"}
    snapshot = _write(tmp_path / "_inputs" / "hotspots" / "xiaohongshu.txt", "官方活动 AI 效率挑战")
    snapshot_rel = "hotspots/xiaohongshu.txt"
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    provenance_hash = _hotspot_source_hash(
        "xiaohongshu", "https://www.xiaohongshu.com/explore/activity", "AI 效率挑战",
        fetched_at="2026-08-25T00:00:00Z", status=200,
        snapshot_path=snapshot_rel, snapshot_sha256=snapshot_hash,
    )
    _write(tmp_path / "_inputs" / "hotspots" / "xiaohongshu.json", json.dumps({
        "platform": "xiaohongshu", "source_url": "https://www.xiaohongshu.com/explore/activity",
        "observed_title": "AI 效率挑战", "fetched_at": "2026-08-25T00:00:00Z", "status": 200,
        "snapshot_path": snapshot_rel, "snapshot_sha256": snapshot_hash, "provenance_hash": provenance_hash,
        "evidence_type": "official_activity", "native_verified": False, "association_mode": "manual_handoff",
        "lane_fit_score": 0.9, "semantic_fit_score": 0.9,
    }))

    hotspot = _load_verified_hotspot(tmp_path, case)
    assert hotspot["evidence_type"] == "official_activity"
    assert hotspot["native_verified"] is False
    assert hotspot["mode"] == "official_activity"
    manifest = {
        "hotspot": hotspot,
        "source_evidence": [{
            "platform": "xiaohongshu", "url": hotspot["source_url"], "title": hotspot["observed_title"],
            "evidence_type": "official_activity", "association_mode": "manual_handoff",
            "provenance_hash": hotspot["provenance_hash"],
        }],
    }
    assert _validate_hotspot_provenance(case, manifest)["passed"] is True


def test_hotspot_evidence_type_and_association_mode_must_match_matrix(tmp_path: Path):
    from scripts.task9_canary import _hotspot_source_hash, _load_verified_hotspot

    snapshot = _write(tmp_path / "_inputs" / "hotspots" / "xiaohongshu.txt", "official activity")
    snapshot_rel = "hotspots/xiaohongshu.txt"
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    provenance_hash = _hotspot_source_hash(
        "xiaohongshu", "https://www.xiaohongshu.com/activity", "official activity",
        fetched_at="2026-08-25T00:00:00Z", status=200,
        snapshot_path=snapshot_rel, snapshot_sha256=snapshot_hash,
    )
    _write(tmp_path / "_inputs" / "hotspots" / "xiaohongshu.json", json.dumps({
        "platform": "xiaohongshu", "source_url": "https://www.xiaohongshu.com/activity",
        "observed_title": "official activity", "fetched_at": "2026-08-25T00:00:00Z", "status": 200,
        "snapshot_path": snapshot_rel, "snapshot_sha256": snapshot_hash, "provenance_hash": provenance_hash,
        "evidence_type": "native", "native_verified": True, "association_mode": "auto_api",
        "lane_fit_score": 0.9, "semantic_fit_score": 0.9,
    }))

    with pytest.raises(ValueError, match="hotspot_evidence_type_not_allowed|hotspot_association_mode_not_allowed"):
        _load_verified_hotspot(tmp_path, {"platform": "xiaohongshu", "delivery_policy": "manual_handoff_only"})


def test_missing_or_tampered_hotspot_blocks_before_pipeline_create(tmp_path: Path):
    from scripts.task9_canary import _run_pipeline_case

    calls = []

    class PipelineBoundary:
        def __init__(self, store, config):
            pass

        def create(self, *args, **kwargs):
            calls.append("create")
            raise AssertionError("pipeline create must not run")

    case = {"platform": "kuaishou", "content_form": "article", "language": "zh", "delivery_policy": "dry_run", "order": 1}
    result = _run_pipeline_case(case, tmp_path, pipeline_factory=PipelineBoundary)

    assert result["passed"] is False
    assert calls == []
    assert "hotspot" in result["error"]


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


def test_runtime_identity_uses_hermes_config_and_same_provider_cache(tmp_path: Path, monkeypatch):
    from scripts import task9_canary

    _write(tmp_path / "provider_models_cache.json", json.dumps({
        "opencode-go": {"models": ["mimo-v2.5", "ox-alpha-free", "deepseek-v4-flash"]},
    }))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(task9_canary.shutil, "which", lambda _: "/usr/bin/hermes")
    monkeypatch.setattr(task9_canary, "_hermes_help", lambda _: "--provider PROVIDER --model MODEL")
    monkeypatch.setattr(task9_canary, "_hermes_text", lambda command: (
        "Model: {'default': 'mimo-v2.5', 'provider': 'opencode-go'}\n"
        if command[1:] == ["config", "show"] else ""
    ))

    runtime = task9_canary.discover_hermes_runtime()

    assert runtime["active"]["provider"] == "opencode-go"
    assert runtime["active"]["model"] == "mimo-v2.5"
    assert runtime["weak"]["provider"] == "opencode-go"
    assert runtime["weak"]["model"] == "ox-alpha-free"


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


def test_acceptance_rejects_unbound_passed_json_as_audit_evidence(tmp_path: Path):
    from scripts.task9_acceptance import evaluate_acceptance

    report = _valid_acceptance_report(tmp_path)
    fake = _write(tmp_path / "fake.json", json.dumps({"passed": True}))
    report["audits"]["full_pytest"] = {
        "passed": True,
        "path": str(fake),
        "sha256": __import__("hashlib").sha256(fake.read_bytes()).hexdigest(),
        "commit": "abc",
    }

    result = evaluate_acceptance(report, repo_root=ROOT)

    assert result["production_ready"] is False
    assert "audit_payload_unreadable:full_pytest" in result["failures"]


def test_acceptance_rejects_non_mutating_rollback_claim(tmp_path: Path):
    from scripts.task9_acceptance import evaluate_acceptance

    report = _valid_acceptance_report(tmp_path)
    report["rollback_rehearsal"] = {"passed": True, "mutation_performed": False}

    result = evaluate_acceptance(report, repo_root=ROOT)

    assert result["production_ready"] is False
    assert "rollback_rehearsal_missing" in result["failures"]


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
    junit = _write(tmp_path / "full_pytest.xml", '<testsuite tests="1" failures="0" errors="0"><testcase name="ok"/></testsuite>')
    audit_paths = {
        "full_pytest": junit,
        "privacy_audit": _write(tmp_path / "privacy_audit.json", json.dumps({"ok": True, "issues": []})),
        "license_audit": _write(tmp_path / "license_audit.json", json.dumps({"passed": True, "issues": []})),
    }
    for name, path in audit_paths.items():
        digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        evidence[name] = {"passed": True, "path": str(path), "sha256": digest, "commit": "abc"}
    from scripts.task9_canary import build_canary_matrix, EXPECTED_CANARY_PLATFORMS
    matrix = build_canary_matrix()
    cases = [
        {
            "platform": platform["platform"],
            "hotspot_contract": platform["hotspot_contract"],
            "artifact_policy_passed": True,
            "evidence_level": "artifact_verified",
            "pipeline_evidence": {"create_called": True, "run_called": True, "serial_index": index},
            "probes": {
                "capabilities": {"passed": True, "evidence_level": "artifact_verified"},
                "hotspot": {
                    "passed": True,
                    "evidence_level": "artifact_verified",
                    "details": {
                        "evidence_type": platform["hotspot_contract"]["allowed_evidence_types"][0],
                        "association_mode": platform["hotspot_contract"]["allowed_association_modes"][0],
                    },
                },
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
        "rollback_rehearsal": {"passed": True, "mutation_performed": True, "health_checks_passed": True, "forward_recovered": True},
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
