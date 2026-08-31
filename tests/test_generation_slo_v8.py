from content_platform.generator import DraftGenerator
from content_platform.run_contract import build_run_contract


def test_run_contract_carries_bounded_generation_slo():
    bounds = build_run_contract("wechat")["bounds"]

    assert bounds["generation_soft_deadline_seconds"] == 90
    assert bounds["generation_hard_deadline_seconds"] == 180
    assert bounds["generation_heartbeat_seconds"] == 15
    assert bounds["generation_max_attempts"] == 2


def test_generator_prefers_contract_slo_over_looser_local_defaults():
    generator = DraftGenerator(
        {"soft_deadline": 240, "hard_deadline": 420, "heartbeat_interval": 30}
    )

    result = generator._generation_slo({"run_contract": build_run_contract("wechat")})

    assert result == {"soft": 90, "hard": 180, "heartbeat": 15, "max_attempts": 2}


def test_invalid_local_slo_is_normalized_for_nonproduction_drafts():
    generator = DraftGenerator(
        {"soft_deadline": 200, "hard_deadline": 100, "heartbeat_interval": 0}
    )

    result = generator._generation_slo({})

    assert result["heartbeat"] == 1
    assert result["soft"] < result["hard"]
