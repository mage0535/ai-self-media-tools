import json

from content_platform.content_quality_reference import (
    load_content_quality_reference_pack,
    validate_content_quality_reference_pack,
)
from content_platform.run_contract import bound_stage_payload, build_run_contract


def test_reference_pack_loads_compact_video_rules_for_ai_short_video():
    pack = load_content_quality_reference_pack("douyin_ai", content_form="short_video")

    assert pack["version"] == "content_quality_reference_pack_v1"
    assert pack["loaded"] is True
    assert "video_director_gate" in pack["sections"]
    assert "cover_design_gate" in pack["sections"]
    assert pack["video_director_gate"]["scene_contract"]["must_define"]
    assert validate_content_quality_reference_pack(pack)["passed"] is True


def test_reference_pack_fits_bounded_generate_payload():
    contract = build_run_contract("tiktok")
    pack = load_content_quality_reference_pack("tiktok", content_form="short_video")

    payload = bound_stage_payload(
        contract,
        "generate",
        {
            "content_blueprint": {"topic": "AI workflow"},
            "claim_ledger": [],
            "tool_selection_plan": {},
            "content_quality_reference_pack": pack,
        },
    )

    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert len(encoded) < contract["bounds"]["stage_payload_bytes"]
    assert payload["content_quality_reference_pack"]["cover_design_gate"]["single_job"] is True
