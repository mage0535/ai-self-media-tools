from pathlib import Path

from content_platform.strategy_compiler import compile_strategy, validate_compiled_strategy


def test_strategy_compiler_extracts_hooks_pillars_kpis_and_safe_structures(tmp_path: Path):
    source = tmp_path / "growth_strategy.md"
    source.write_text(
        """# Strategy\n\n| 类型 | AI解决问题 | 目的 |\n| 类型 | AI避坑指南 | 目的 |\n| 类型 | AI效率对比 | 目的 |\n\n身份锚点：「你是不是每周五都焦虑周报？」\n5s完播率：>30%\n收藏率：≥5%\n""",
        encoding="utf-8",
    )
    result = compile_strategy(source, "douyin_ai")
    assert validate_compiled_strategy(result)["passed"] is True
    assert result["platform"] == "douyin_ai"
    assert result["kpi_hypotheses"]["收藏率"] == "≥5%"
    assert result["selection_policy"]["shadow_can_create_jobs"] is False


def test_strategy_compiler_rejects_mojibake(tmp_path: Path):
    source = tmp_path / "bad.md"
    source.write_text("策略 ����", encoding="utf-8")
    try:
        compile_strategy(source, "douyin_ai")
    except ValueError as exc:
        assert "mojibake" in str(exc)
    else:
        raise AssertionError("corrupt strategy must fail")


def test_strategy_evidence_contract_requires_real_viral_keyword_and_prompt_inputs():
    from content_platform.strategy_compiler import (
        build_strategy_evidence_contract,
        validate_strategy_evidence_contract,
    )

    contract = build_strategy_evidence_contract(
        platform="douyin_pet",
        lane="pet_healing",
        viral_collection={"tool": "douyin-native-search", "collected_at": "2026-09-13T15:00:00+00:00", "sample_count": 3},
        viral_breakdown={"status": "ready", "summary": {"accepted_samples": 2}, "samples": [{"native_id": "a", "canonical_url": "https://www.douyin.com/video/a", "author": "creator-a", "published_at": "2026-09-13T10:00:00+08:00", "captured_at": "2026-09-13T12:00:00+08:00", "likes": 100, "visual_evidence": ["/tmp/a.jpg"]}, {"native_id": "b", "canonical_url": "https://www.douyin.com/video/b", "author": "creator-b", "published_at": "2026-09-13T11:00:00+08:00", "captured_at": "2026-09-13T12:00:00+08:00", "comments": 20, "visual_evidence": ["/tmp/b.jpg"]}]},
        keyword_tool={"tool": "keyword_strategy", "platform": "douyin_pet", "lane": "pet_healing", "queries": ["猫咪治愈", "猫咪踩奶"]},
        prompt_bundle={"validation": {"passed": True}, "fingerprint": "prompt123", "input": {"platform": "douyin_pet"}, "evidence": ["douyin://a"]},
    )

    assert validate_strategy_evidence_contract(contract)["passed"] is True
    assert contract["platform"] == "douyin_pet"
    assert contract["keyword_tool"]["queries"] == ["猫咪治愈", "猫咪踩奶"]


def test_strategy_evidence_contract_fails_closed_when_keyword_tool_or_breakdown_is_missing():
    from content_platform.strategy_compiler import validate_strategy_evidence_contract

    result = validate_strategy_evidence_contract({
        "platform": "douyin_pet",
        "lane": "pet_healing",
        "viral_collection": {"tool": "douyin-native-search", "collected_at": "now", "sample_count": 3},
        "viral_breakdown": {"status": "blocked", "samples": []},
        "keyword_tool": {"platform": "douyin_pet", "queries": []},
        "prompt_bundle": {},
    })

    assert result["passed"] is False
    assert "viral_breakdown_not_ready" in result["failures"]
    assert "keyword_tool_missing_or_not_executed" in result["failures"]
    assert "prompt_bundle_missing_or_invalid" in result["failures"]


def test_strategy_evidence_contract_rejects_cross_platform_viral_samples():
    from content_platform.strategy_compiler import validate_strategy_evidence_contract

    contract = {
        "platform": "douyin_pet",
        "lane": "pet_healing",
        "viral_collection": {"tool": "tiktok-collector", "collected_at": "2026-09-14T00:00:00+00:00", "sample_count": 1},
        "viral_breakdown": {
            "status": "ready",
            "summary": {"accepted_samples": 1},
            "samples": [{"canonical_url": "https://www.tiktok.com/@cat/video/123"}],
        },
        "keyword_tool": {"tool": "keyword_strategy", "platform": "douyin_pet", "lane": "pet_healing", "queries": ["猫咪治愈"]},
        "prompt_bundle": {"validation": {"passed": True}, "fingerprint": "p", "evidence": ["https://www.tiktok.com/@cat/video/123"]},
    }

    result = validate_strategy_evidence_contract(contract)
    assert result["passed"] is False
    assert "viral_breakdown_cross_platform_samples" in result["failures"]


def test_strategy_evidence_contract_requires_content_level_sample_metadata():
    from content_platform.strategy_compiler import validate_strategy_evidence_contract

    contract = {
        "platform": "douyin_pet",
        "lane": "pet_healing",
        "viral_collection": {"tool": "douyin-hot-board", "collected_at": "2026-09-14T00:00:00+08:00", "sample_count": 1},
        "viral_breakdown": {
            "status": "ready",
            "summary": {"accepted_samples": 1},
            "samples": [{"native_id": "123", "canonical_url": "https://www.douyin.com/video/123"}],
        },
        "keyword_tool": {"tool": "keyword_strategy", "platform": "douyin_pet", "lane": "pet_healing", "queries": ["猫咪治愈"]},
        "prompt_bundle": {"validation": {"passed": True}, "fingerprint": "p", "evidence": ["https://www.douyin.com/video/123"]},
    }

    result = validate_strategy_evidence_contract(contract)
    assert result["passed"] is False
    assert "viral_breakdown_sample_metadata_incomplete" in result["failures"]
