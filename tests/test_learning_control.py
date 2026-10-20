from datetime import datetime, timedelta, timezone

from content_platform.learning_control import LearningRegistry


def _outcome(index, arm, *, views, policy_id, assignment_id):
    published = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index)
    return {
        "version": "owned_outcome_v1", "platform": "youtube", "account_id": "owned-channel",
        "lane": "real_world_ai_implementation", "content_form": "short_video",
        "content_id": f"video-{index}", "job_id": f"job-{index}", "publish_receipt_id": f"receipt-{index}",
        "policy_version_id": policy_id, "assignment_id": assignment_id, "assignment_arm": arm,
        "metric_window": "72h", "published_at": published.isoformat(),
        "observed_at": (published + timedelta(hours=72)).isoformat(),
        "metrics": {"views": views, "likes": max(1, views // 20), "comments": 1, "shares": 1, "saves": 1, "follows": 1},
        "source_class": "authorized_owned_analytics", "authorization_ref": "auth-handle", "native_verified": True,
        "strategy_eligible": True, "raw_response_hash": f"{index:064x}",
    }


def test_control_rejects_public_or_unmapped_outcomes(tmp_path):
    registry = LearningRegistry(tmp_path / "registry.json")
    result = registry.record_outcome({"source_class": "public_web_observation"})
    assert result["accepted"] is False
    assert "owned_outcome_source_not_authorized" in result["reason_codes"]


def test_holdout_cannot_pass_before_minimum_complete_owned_cohort(tmp_path):
    registry = LearningRegistry(tmp_path / "registry.json")
    baseline = registry.create_policy(platform="youtube", account_id="owned-channel", lane="real_world_ai_implementation", content_form="short_video", treatment_vector={"hook": "baseline"})
    candidate = registry.create_policy(platform="youtube", account_id="owned-channel", lane="real_world_ai_implementation", content_form="short_video", treatment_vector={"hook": "result_first"}, rollback_target_policy_version_id=baseline["policy_version_id"])
    approval = registry.approve(policy_version_id=candidate["policy_version_id"], approver_id="human-1", max_exposure=0.5)
    assignment = registry.assign(job_id="job-1", policy_version_id=candidate["policy_version_id"], approval_id=approval["approval_id"])
    registry.record_outcome(_outcome(1, assignment["arm"], views=200, policy_id=candidate["policy_version_id"], assignment_id=assignment["assignment_id"]))
    evaluation = registry.evaluate(policy_version_id=candidate["policy_version_id"])
    assert evaluation["passed"] is False
    assert "minimum_cohort_not_met" in evaluation["reason_codes"]


def test_holdout_pass_emits_only_auditable_posthoc_outcome_assertion(tmp_path):
    registry = LearningRegistry(tmp_path / "registry.json")
    baseline = registry.create_policy(platform="youtube", account_id="owned-channel", lane="real_world_ai_implementation", content_form="short_video", treatment_vector={"hook": "baseline"})
    candidate = registry.create_policy(platform="youtube", account_id="owned-channel", lane="real_world_ai_implementation", content_form="short_video", treatment_vector={"hook": "result_first"}, rollback_target_policy_version_id=baseline["policy_version_id"])
    approval = registry.approve(policy_version_id=candidate["policy_version_id"], approver_id="human-1", max_exposure=0.5)
    for index in range(120):
        policy_id = candidate["policy_version_id"] if index % 2 else baseline["policy_version_id"]
        arm = "treatment" if index % 2 else "control"
        assignment = registry.assign(job_id=f"job-{index}", policy_version_id=policy_id, approval_id=approval["approval_id"] if arm == "treatment" else None, arm=arm)
        registry.record_outcome(_outcome(index, arm, views=220 if arm == "treatment" else 100, policy_id=policy_id, assignment_id=assignment["assignment_id"]))
    evaluation = registry.evaluate(policy_version_id=candidate["policy_version_id"])
    assert evaluation["passed"] is True
    assert evaluation["assertion"]["claim_text"] == "满足预注册的自有内容 72 小时表现阈值"
    assert "guaranteed" not in evaluation["assertion"]["claim_text"].lower()


def test_rollback_restores_champion_and_stops_new_treatment_assignments(tmp_path):
    registry = LearningRegistry(tmp_path / "registry.json")
    champion = registry.create_policy(platform="youtube", account_id="owned-channel", lane="real_world_ai_implementation", content_form="short_video", treatment_vector={"hook": "baseline"})
    challenger = registry.create_policy(platform="youtube", account_id="owned-channel", lane="real_world_ai_implementation", content_form="short_video", treatment_vector={"hook": "result_first"}, rollback_target_policy_version_id=champion["policy_version_id"])
    approval = registry.approve(policy_version_id=challenger["policy_version_id"], approver_id="human-1", max_exposure=0.5)
    registry.activate(policy_version_id=challenger["policy_version_id"], approval_id=approval["approval_id"])
    event = registry.rollback(policy_version_id=challenger["policy_version_id"], reason="integrity_hash_mismatch")
    assert event["event_type"] == "rollback"
    assert registry.active_policy(scope=("youtube", "owned-channel", "real_world_ai_implementation", "short_video"))["policy_version_id"] == champion["policy_version_id"]
    try:
        registry.assign(job_id="new-job", policy_version_id=challenger["policy_version_id"], approval_id=approval["approval_id"], arm="treatment")
    except ValueError as exc:
        assert "policy_not_approved" in str(exc)
    else:
        raise AssertionError("rolled-back policy received a treatment assignment")
