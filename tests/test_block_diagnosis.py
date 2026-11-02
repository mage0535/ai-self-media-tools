import pytest

from content_platform.block_diagnosis import diagnose_block


@pytest.mark.parametrize("code,kind", [
    ("source_same_lane_benchmark_unavailable", "data_access"),
    ("wechat_discovery_paused_after_verification", "data_access"),
    ("mediacrawler_login_required", "data_access"),
    ("source_requested_topic_not_selected", "retrieval_direction"),
    ("normal_topic_semantic_pool_rejected", "retrieval_direction"),
    ("source_strategy_observed_content_changed", "integrity"),
    ("normal_source_selected_account_identity_mismatch", "integrity"),
    ("knowledge_card_section_binding_missing", "content_quality"),
    ("final_platform_quality_gate_failed", "content_quality"),
    ("dependency_not_satisfied", "unclassified"),
])
def test_block_reasons_name_what_to_fix(code, kind):
    assert diagnose_block(code) == kind
