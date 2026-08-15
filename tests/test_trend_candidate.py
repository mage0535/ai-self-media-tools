from content_platform.trend_candidate import build_trend_candidate, validate_trend_candidate


def test_trend_candidate_requires_eight_attempts_and_five_successes():
    candidate = build_trend_candidate(
        platform="zhihu",
        topic="AI workflow checklist",
        direction="agent_workflow",
        source_report=[{"source": f"source-{n}", "status": "ok"} for n in range(4)],
        platform_signal="saved posts on this platform prefer concrete checklists",
        platform_adaptation_reason="use a cited argument with an implementation checklist",
    )

    result = validate_trend_candidate(candidate)

    assert result["passed"] is False
    assert "sources_attempted_lt_8" in result["failures"]
    assert "sources_succeeded_lt_5" in result["failures"]


def test_trend_candidate_is_valid_with_platform_specific_evidence():
    candidate = build_trend_candidate(
        platform="zhihu",
        topic="AI workflow checklist",
        direction="agent_workflow",
        source_report=[{"source": f"source-{n}", "status": "ok"} for n in range(5)] + [{"source": f"failed-{n}", "status": "failed"} for n in range(3)],
        platform_signal="saved posts on this platform prefer concrete checklists",
        platform_adaptation_reason="use a cited argument with an implementation checklist",
        heat_score=0.82,
    )

    assert validate_trend_candidate(candidate)["passed"] is True
