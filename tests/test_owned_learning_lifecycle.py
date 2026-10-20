from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_platform.owned_learning import OwnedLearningStore
from content_platform.owned_learning_outcomes import ingest_authorized_outcome
from content_platform.owned_learning_verifier import sign_claim_for_verifier

SCOPE = ("youtube", "owned:acct", "real_world_ai_implementation", "short")
SECRET = b"test-verifier-secret"


def _claim(kind, nonce, **payload):
    now = datetime.now(timezone.utc)
    return sign_claim_for_verifier({
        "kind": kind, "issuer": "test-verifier", "nonce": nonce,
        "expires_at": (now + timedelta(days=7)).isoformat(timespec="seconds"), **payload,
    }, SECRET)


def _active_experiment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OWNED_LEARNING_VERIFIER_SECRET", SECRET.decode())
    store = OwnedLearningStore(tmp_path / "state.db")
    champion = store.create_policy(platform=SCOPE[0], account_id=SCOPE[1], lane=SCOPE[2], content_form=SCOPE[3], treatment_vector={"hook": "baseline"})
    challenger = store.create_policy(platform=SCOPE[0], account_id=SCOPE[1], lane=SCOPE[2], content_form=SCOPE[3], treatment_vector={"hook": "show_result_first"}, rollback_policy_id=champion["policy_id"])
    card = store.create_experiment_card(policy_id=challenger["policy_id"], primary_metric="views_72h", minimum_per_arm=2, minimum_effect=0.05, quality_gate_digest="quality:v1", randomization_salt="test-salt", analysis_method="bootstrap_ratio_ci_v1", stop_rule="quality_failure_or_ci_fail")
    approval = store.approve_experiment(card_id=card["card_id"], approver_id="human", max_exposure=0.5)
    experiment = store.activate_experiment(card_id=card["card_id"], approval_id=approval["approval_id"])
    grant = store.register_authorization_grant(claim=_claim("owned_analytics_grant", "grant-1", platform=SCOPE[0], account_id=SCOPE[1], scope=list(SCOPE), evidence_digest="a" * 64))
    return store, experiment, grant


def _seal_and_ingest(store, decision, grant_id, index, value):
    observed = datetime.now(timezone.utc).replace(microsecond=0)
    published = observed - timedelta(hours=72)
    receipt = store.seal_verified_postcheck(claim=_claim("owned_postcheck", f"receipt-{index}", receipt_id=f"receipt:{index}", assignment_id=decision["assignment_id"], job_id=decision["job_id"], platform=SCOPE[0], account_id=SCOPE[1], platform_content_id=f"video:{index}", quality_gate_digest="quality:v1", evidence_digest=f"evidence-{index}".ljust(64, "0"), verified_at=observed.isoformat()))
    analytics = store.register_analytics_claim(claim=_claim("owned_analytics_72h", f"analytics-{index}", receipt_id=receipt["receipt_id"], response_digest=f"response-{index}".ljust(64, "0"), observed_at=observed.isoformat(), published_at=published.isoformat(), metrics={"views_72h": value}))
    return ingest_authorized_outcome(store, authorization_grant_id=grant_id, analytics_claim_id=analytics["claim_id"])


def test_only_signed_sealed_evidence_enters_evaluation(tmp_path, monkeypatch):
    store, experiment, grant = _active_experiment(tmp_path, monkeypatch)
    decisions = [store.decide(job_id=f"job-{index}", scope=SCOPE) for index in range(16)]
    for index, decision in enumerate(decisions):
        _seal_and_ingest(store, decision, grant["grant_id"], index, 240 if decision["arm"] == "treatment" else 100)
    evaluation = store.evaluate_experiment(experiment["experiment_id"])
    assert evaluation["status"] == "pass"
    assert evaluation["eligible_for_automation"] is True
    assert evaluation["allow_automated_learning"] is False


def test_raw_caller_receipt_and_untrusted_grant_are_rejected(tmp_path, monkeypatch):
    store, _, _ = _active_experiment(tmp_path, monkeypatch)
    with pytest.raises(TypeError):
        getattr(store, "record_outcome")(**{"assignment_id": "x", "receipt_id": "x", "platform_content_id": "x", "observed_at": "x", "published_at": "x", "raw_evidence": b"x", "authorization_grant_id": "x", "quality_gate_digest": "x", "metrics": {}})
    monkeypatch.delenv("OWNED_LEARNING_VERIFIER_SECRET")
    with pytest.raises(ValueError, match="trusted_verifier_unavailable"):
        store.register_authorization_grant(claim={"kind": "owned_analytics_grant"})


def test_72h_window_has_five_minute_bounded_grace(tmp_path, monkeypatch):
    store, _, grant = _active_experiment(tmp_path, monkeypatch)
    decision = store.decide(job_id="job-window", scope=SCOPE)
    observed = datetime.now(timezone.utc).replace(microsecond=0)
    receipt = store.seal_verified_postcheck(claim=_claim("owned_postcheck", "receipt-window", receipt_id="receipt:window", assignment_id=decision["assignment_id"], job_id=decision["job_id"], platform=SCOPE[0], account_id=SCOPE[1], platform_content_id="video:window", quality_gate_digest="quality:v1", evidence_digest="e" * 64, verified_at=observed.isoformat()))
    analytics = store.register_analytics_claim(claim=_claim("owned_analytics_72h", "analytics-window", receipt_id=receipt["receipt_id"], response_digest="r" * 64, observed_at=observed.isoformat(), published_at=(observed - timedelta(hours=72, minutes=6)).isoformat(), metrics={"views_72h": 1}))
    with pytest.raises(ValueError, match="outcome_window_invalid"):
        ingest_authorized_outcome(store, authorization_grant_id=grant["grant_id"], analytics_claim_id=analytics["claim_id"])


def test_control_plane_digest_drift_and_rollback_force_control(tmp_path, monkeypatch):
    store, experiment, _ = _active_experiment(tmp_path, monkeypatch)
    decision = store.decide(job_id="job-drift", scope=SCOPE)
    assert store.resolve_treatment(assignment_id=decision["assignment_id"], scope=SCOPE, explicit_enable=True)["arm"] == "control"
    store.rollback_experiment(experiment_id=experiment["experiment_id"], reason="quality_gate_failed", actor="reviewer")
    assert store.strategy_health(experiment["experiment_id"])["allow_automated_learning"] is False
    with pytest.raises(ValueError, match="experiment_not_active"):
        store.decide(job_id="job-after-rollback", scope=SCOPE)


def test_expired_or_tampered_control_plane_fails_closed(tmp_path, monkeypatch):
    store, experiment, _ = _active_experiment(tmp_path, monkeypatch)
    assert store.strategy_health(experiment["experiment_id"])["allow_automated_learning"] is False
    store.tamper_for_test(experiment["experiment_id"])
    assert store.strategy_health(experiment["experiment_id"])["status"] == "revoked"
