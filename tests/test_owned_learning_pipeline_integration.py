from pathlib import Path
from unittest.mock import patch

from content_platform.owned_learning import OwnedLearningStore
from content_platform.pipeline import Pipeline
from content_platform.store import Store


SCOPE = ("youtube", "owned:acct", "real_world_ai_implementation", "short")


def _activate(store):
    baseline = store.create_policy(platform=SCOPE[0], account_id=SCOPE[1], lane=SCOPE[2], content_form=SCOPE[3], treatment_vector={"hook": "baseline"})
    challenger = store.create_policy(platform=SCOPE[0], account_id=SCOPE[1], lane=SCOPE[2], content_form=SCOPE[3], treatment_vector={"hook": "show_result_first"}, rollback_policy_id=baseline["policy_id"])
    card = store.create_experiment_card(policy_id=challenger["policy_id"], primary_metric="views_72h", minimum_per_arm=2, minimum_effect=0.05, quality_gate_digest="quality:v1", randomization_salt="salt", analysis_method="bootstrap_ratio_ci_v1", stop_rule="quality_failure")
    approval = store.approve_experiment(card_id=card["card_id"], approver_id="human", max_exposure=.5)
    return store.activate_experiment(card_id=card["card_id"], approval_id=approval["approval_id"])


def test_pipeline_create_atomically_freezes_owned_decision_and_run_bounds_it(tmp_path):
    state = Store(tmp_path / "state.db")
    learning = OwnedLearningStore(state.path)
    _activate(learning)
    pipeline = Pipeline(state, {"data_dir": str(tmp_path), "generator": {"allow_fallback": True, "api_key_env": "__MISSING__"}, "feature_flags": {"owned_learning_control": "enforce"}, "owned_learning": {"enabled": True}})

    job = pipeline.create("AI dispatch workflow", ["youtube"], {"account_id": SCOPE[1], "lane": SCOPE[2], "content_form": SCOPE[3]})
    assert job["brief"]["owned_decision"]["assignment_id"]
    assert job["brief"]["owned_decision"]["arm"] in {"control", "treatment"}

    captured = {}
    def generate(topic, brief):
        captured.update(brief)
        return {"title": topic, "body": "A verified work process with a human takeover point.", "draft_meta": {"quality_gate": {"passed": True}, "claim_ledger": []}}
    with patch.object(pipeline.generator, "generate", side_effect=generate):
        pipeline.run(job["id"])
    bounded = captured["bounded_model_input"]
    assert bounded["owned_learning_decision"]["assignment_id"] == job["brief"]["owned_decision"]["assignment_id"]
    assert "treatment_vector" not in bounded["owned_learning_decision"] or bounded["owned_learning_decision"]["arm"] == "treatment"
