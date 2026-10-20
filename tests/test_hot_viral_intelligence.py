from content_platform.hot_viral_intelligence import build_hot_viral_intelligence


def _breakdown():
    return {
        "copy": "先给结论，再展示证据",
        "hook": "3 秒结果钩子",
        "writing_style": "短句、实测口吻",
        "illustration": "步骤截图",
        "cover": "结果数字 + 工具界面",
        "video_structure": ["hook", "proof", "steps", "CTA"],
        "motion": "关键数字放大",
        "transition": "步骤间硬切",
        "CTA": "评论区分享你的结果",
    }


def _sample(**overrides):
    sample = {
        "platform": "douyin",
        "lane": "AI 自动化",
        "source": "douyin_native_search",
        "signal_type": "viral_work",
        "canonical_url": "https://www.douyin.com/video/123",
        "content_id": "123",
        "author": "AI 实验室",
        "published_at": "2026-09-15T08:00:00+08:00",
        "observed_at": "2026-09-16T08:00:00+08:00",
        "metrics": {"likes": 12000},
        "content_evidence": {"title": "我用 Agent 自动处理日报", "transcript": "展示运行结果与三步配置"},
        "breakdown": _breakdown(),
    }
    sample.update(overrides)
    return sample


def test_complete_target_native_work_is_native_ready():
    result = build_hot_viral_intelligence(
        target_platform="douyin",
        lane="AI 自动化",
        samples=[_sample()],
        source_statuses={"douyin_native_search": "ready"},
    )

    assert result["status"] == "native_ready"
    assert result["native_ready"] is True
    assert result["native_verified"] is True
    assert result["evidence_grade"] == "A_native_content"
    assert result["strategy_context"]["mode"] == "target_platform_native"
    assert result["strategy_context"]["breakdown"] == _breakdown()


def test_native_ready_requires_identity_author_dates_metric_and_content_evidence():
    required_cases = {
        "identity": {"canonical_url": "", "content_id": ""},
        "author": {"author": ""},
        "published_at": {"published_at": ""},
        "observed_at": {"observed_at": ""},
        "native_signal": {"metrics": {}},
        "content_evidence": {"content_evidence": {}},
    }

    for missing, overrides in required_cases.items():
        result = build_hot_viral_intelligence(
            target_platform="douyin",
            lane="AI 自动化",
            samples=[_sample(**overrides)],
            source_statuses={"douyin_native_search": "ready"},
        )
        assert result["native_ready"] is False, missing
        assert result["native_verified"] is False, missing
        assert any(missing in reason for reason in result["blocking_reasons"]), missing


def test_missing_target_uses_honest_multi_source_adjacent_platform_fallback():
    samples = [
        _sample(
            platform="xiaohongshu",
            source="xiaohongshu_native_search",
            canonical_url="https://www.xiaohongshu.com/explore/a",
            content_id="a",
        ),
        _sample(
            platform="tiktok",
            source="tiktok_public_metadata",
            canonical_url="https://www.tiktok.com/@ai/video/b",
            content_id="b",
        ),
    ]

    result = build_hot_viral_intelligence(
        target_platform="douyin",
        lane="AI 自动化",
        samples=samples,
        source_statuses={
            "douyin_native_search": "blocked",
            "xiaohongshu_native_search": "ready",
            "tiktok_public_metadata": "partial",
        },
    )

    assert result["status"] == "fallback_ready"
    assert result["native_ready"] is False
    assert result["native_verified"] is False
    assert result["evidence_grade"] == "B_cross_platform_content"
    context = result["strategy_context"]
    assert context["mode"] == "fallback_generation_context"
    assert context["claim_scope"] == "cross_platform_same_lane_reference_only"
    assert context["not_target_platform_viral_proof"] is True
    assert set(context["source_platforms"]) == {"xiaohongshu", "tiktok"}
    assert context["breakdown"]["hook"] == ["3 秒结果钩子"]


def test_topic_signal_and_unavailable_sources_never_count_as_viral_work():
    topic = _sample(signal_type="topic_signal")
    empty_source_work = _sample(
        platform="tiktok",
        source="empty_source",
        canonical_url="https://www.tiktok.com/@ai/video/empty",
        content_id="empty",
    )
    blocked_source_work = _sample(
        platform="xiaohongshu",
        source="blocked_source",
        canonical_url="https://www.xiaohongshu.com/explore/blocked",
        content_id="blocked",
    )

    result = build_hot_viral_intelligence(
        target_platform="douyin",
        lane="AI 自动化",
        samples=[topic, empty_source_work, blocked_source_work],
        source_statuses={
            "douyin_native_search": "ready",
            "empty_source": "fresh_empty",
            "blocked_source": "blocked",
        },
    )

    assert result["status"] == "blocked"
    assert result["native_ready"] is False
    assert result["native_verified"] is False
    assert result["evidence_grade"] == "C_topic_signal_only"
    assert result["topic_signal_count"] == 1
    assert result["strategy_context"]["mode"] == "unavailable"
    assert result["source_statuses"] == {
        "douyin_native_search": "ready",
        "empty_source": "fresh_empty",
        "blocked_source": "blocked",
    }


def test_all_deep_breakdown_dimensions_are_required_and_declared():
    for dimension in _breakdown():
        incomplete = _breakdown()
        incomplete[dimension] = ""
        result = build_hot_viral_intelligence(
            target_platform="douyin",
            lane="AI 自动化",
            samples=[_sample(breakdown=incomplete)],
            source_statuses={"douyin_native_search": "ready"},
        )
        assert result["status"] == "blocked", dimension
        assert f"breakdown_{dimension}_missing" in result["blocking_reasons"], dimension
        assert dimension in result["required_breakdown_dimensions"]


def test_non_native_metric_names_do_not_satisfy_viral_evidence_gate():
    result = build_hot_viral_intelligence(
        target_platform="douyin",
        lane="AI 自动化",
        samples=[_sample(metrics={"temperature": 0.8})],
        source_statuses={"douyin_native_search": "ready"},
    )

    assert result["status"] == "blocked"
    assert "native_signal_missing" in result["blocking_reasons"]
