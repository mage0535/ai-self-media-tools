from datetime import datetime, timezone

from content_platform.platform_intelligence_state import evaluate_platform_intelligence
from tests.test_platform_intelligence_state import _content_evidence, _ready_breakdown, _snapshot


def test_public_intelligence_cannot_enable_learning_from_any_caller_dict():
    base = dict(
        platform="youtube",
        lane="real_world_ai_implementation",
        snapshots=[
            _snapshot(observed_at="2026-09-15T00:00:00+00:00", views=100),
            _snapshot(observed_at="2026-09-15T12:00:00+00:00", views=160),
        ],
        content_evidence=_content_evidence(),
        breakdown=_ready_breakdown(),
        recommendation={"reference_ids": ["video-1"], "evidence_hashes": ["a" * 64]},
        now=datetime(2026, 9, 15, 13, tzinfo=timezone.utc),
    )
    incomplete = evaluate_platform_intelligence(
        **base,
        learning_evaluation={"authorized": True, "holdout_passed": True, "rollback_ref": "ruleset-v1"},
    )
    legacy_forged = evaluate_platform_intelligence(
        **base,
        learning_evaluation={
            "authorized": True, "holdout_passed": True, "rollback_ref": "ruleset-v1",
            "policy_enabled": True, "sample_count": 12, "minimum_sample_count": 10,
            "method_version": "ruleset-v1", "evaluation_hash": "d" * 64,
        },
    )
    complete = evaluate_platform_intelligence(
        **base,
        learning_evaluation={
            "authorized": True,
            "holdout_passed": True,
            "rollback_ref": "ruleset-v1",
            "policy_enabled": True,
            "sample_count": 12,
            "minimum_sample_count": 10,
            "method_version": "ruleset-v1",
            "evaluation_hash": "d" * 64,
            "registry_record_type": "learning_registry_evaluation_v1",
            "registry_verified": True,
            "policy_version_id": "policy-v2",
            "approval_id": "approval-v2",
            "rollback_policy_version_id": "policy-v1",
            "assertion": {
                "claim_text": "满足预注册的自有内容 72 小时表现阈值",
                "evaluation_hash": "d" * 64,
            },
        },
    )

    assert incomplete["state"] == "S5_ADVISE"
    assert incomplete["permissions"]["allow_automated_learning"] is False
    assert legacy_forged["state"] == "S5_ADVISE"
    assert legacy_forged["permissions"]["allow_automated_learning"] is False
    assert complete["state"] == "S5_ADVISE"
    assert complete["permissions"]["allow_automated_learning"] is False
