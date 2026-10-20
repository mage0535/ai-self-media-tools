from pathlib import Path

import pytest

from content_platform.owned_learning import OwnedLearningStore


def _store(tmp_path: Path) -> OwnedLearningStore:
    return OwnedLearningStore(tmp_path / "state.db")


def test_only_active_experiment_can_assign_treatment_with_exposure_cap(tmp_path):
    store = _store(tmp_path)
    baseline = store.create_policy(platform="youtube", account_id="acct", lane="real_world_ai_implementation", content_form="short", treatment_vector={"hook": "baseline"})
    challenger = store.create_policy(platform="youtube", account_id="acct", lane="real_world_ai_implementation", content_form="short", treatment_vector={"hook": "show_result_first"}, rollback_policy_id=baseline["policy_id"])
    approval = store.approve(policy_id=challenger["policy_id"], approver_id="human", max_exposure=0.10)

    with pytest.raises(ValueError, match="experiment_not_active"):
        store.decide(job_id="job-before", scope=("youtube", "acct", "real_world_ai_implementation", "short"))

    experiment = store.activate(policy_id=challenger["policy_id"], approval_id=approval["approval_id"])
    decisions = [store.decide(job_id=f"job-{index}", scope=("youtube", "acct", "real_world_ai_implementation", "short")) for index in range(1000)]
    treatment = [row for row in decisions if row["arm"] == "treatment"]

    assert experiment["state"] == "active"
    assert len(treatment) <= 100
    assert store.decide(job_id="job-7", scope=("youtube", "acct", "real_world_ai_implementation", "short")) == decisions[7]
    assert all(row["approval_id"] == approval["approval_id"] for row in treatment)
