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
