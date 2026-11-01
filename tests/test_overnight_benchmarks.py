from content_platform import overnight_benchmarks


def test_ready_row_without_a_collector_is_blocked_and_others_untouched(tmp_path):
    prepared = {"tasks": [
        {"platform": "twitter", "state": "ready_for_plan", "brief": {}},
        {"platform": "wechat", "state": "deferred"},
    ]}

    overnight_benchmarks.attach_breakdowns(prepared, [], tmp_path)

    assert prepared["tasks"][0]["state"] == "blocked"
    assert "no typed public same-lane collector" in prepared["tasks"][0]["reason"]
    assert prepared["tasks"][1] == {"platform": "wechat", "state": "deferred"}


def test_breakdown_is_collected_once_per_platform_and_attached(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(overnight_benchmarks.COLLECTORS, "juejin", lambda items, out: calls.append(out) or ["row"])
    monkeypatch.setattr("content_platform.task_source_inputs._observed_strategy_inputs",
                        lambda platform, public: {"viral_breakdown": {"platform": platform}, "viral_collection": {}})
    prepared = {"tasks": [{"platform": "juejin", "state": "ready_for_plan", "brief": {"a": 1}},
                          {"platform": "juejin", "state": "ready_for_plan"}]}

    overnight_benchmarks.attach_breakdowns(prepared, [], tmp_path)

    assert len(calls) == 1
    assert prepared["tasks"][0]["brief"] == {"a": 1, "viral_breakdown": {"platform": "juejin"}, "viral_collection": {}}
    assert prepared["tasks"][1]["brief"]["viral_breakdown"] == {"platform": "juejin"}


def test_video_lanes_share_one_bilibili_observation_and_keep_its_platform(tmp_path, monkeypatch):
    calls, platforms = [], []
    monkeypatch.setitem(overnight_benchmarks.COLLECTORS, "bilibili_ai", lambda items, out: calls.append(1) or ["row"])
    monkeypatch.setattr("content_platform.task_source_inputs._observed_strategy_inputs",
                        lambda platform, public: platforms.append(platform) or {"viral_breakdown": {}})
    prepared = {"tasks": [{"platform": lane, "state": "ready_for_plan"} for lane in ("kuaishou", "shipinhao", "douyin_ai")]}

    overnight_benchmarks.attach_breakdowns(prepared, [], tmp_path)

    assert calls == [1] and platforms == ["bilibili"] * 3
    assert all(task["brief"]["cross_platform_source"] == "bilibili" for task in prepared["tasks"])


def test_xiaohongshu_takes_the_juejin_article_reference_without_reading_xiaohongshu(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(overnight_benchmarks.COLLECTORS, "juejin", lambda items, out: calls.append(1) or ["row"])
    monkeypatch.setattr("content_platform.task_source_inputs._observed_strategy_inputs",
                        lambda platform, public: {"viral_breakdown": {"platform": platform}})
    prepared = {"tasks": [{"platform": "xiaohongshu", "state": "ready_for_plan"}]}

    overnight_benchmarks.attach_breakdowns(prepared, [], tmp_path)

    assert calls == [1] and prepared["tasks"][0]["state"] == "ready_for_plan"
    assert prepared["tasks"][0]["brief"]["cross_platform_source"] == "juejin"


def _observed_row(platform, content_id, **overrides):
    row = {
        "platform": platform, "source": f"native.{platform}_video", "content_id": content_id,
        "canonical_url": f"https://example.com/{content_id}", "author": "up", "title": "猫咪拆家",
        "published_at": "2026-10-30T08:00:00+00:00", "observed_at": "2026-10-31T08:00:00+00:00",
        "metrics": {"view": 1000}, "raw_response_hash": "a" * 64, "copy_or_script": "猫咪趁主人不在把纸巾全拆了",
        "visual_evidence": [{"t": 0.0, "description": "猫蹲在纸巾盒旁"}, {"t": 5.0, "description": "满地纸屑"}],
        "voiceover": {"segments": [{"text": "你家猫也这样吗"}, {"text": "关注看更多"}]},
        "writing_style": {"observed": "口语"}, "content_structure": {"observed": ["悬念开场", "结果揭晓"]},
        "motion_combination": {"observed": ["跟拍"]}, "transition_combination": {"cuts_per_minute": 6.0, "observed": ["硬切"]},
    }
    row.update(overrides)
    return row


def test_pet_reference_samples_from_two_sources_reach_fallback_ready(tmp_path, monkeypatch):
    # Owner 10-31: other platforms' pet videos are analysed for learning only (reference_use), not reused.
    from content_platform.hot_viral_intelligence import build_hot_viral_intelligence

    monkeypatch.setitem(overnight_benchmarks.COLLECTORS, "bilibili_pet", lambda items, out: [
        _observed_row("bilibili", "BV1"), _observed_row("bilibili", "BV2", motion_combination={"observed": []})])
    monkeypatch.setitem(overnight_benchmarks.COLLECTORS, "youtube_pet", lambda items, out: [
        _observed_row("youtube", "yt1", metrics={"view": 9, "like": 2, "comment": None, "repost": None})])
    monkeypatch.setattr("content_platform.task_source_inputs._observed_strategy_inputs",
                        lambda platform, public: {"viral_breakdown": {"platform": platform}})
    prepared = {"tasks": [{"platform": "douyin_pet", "state": "ready_for_plan", "brief": {"lane": "pet_healing"}}]}

    overnight_benchmarks.attach_breakdowns(prepared, [], tmp_path)

    brief = prepared["tasks"][0]["brief"]
    assert [s["content_id"] for s in brief["hot_viral_samples"]] == ["BV1", "yt1"]  # BV2 lacks observed motion
    assert brief["hot_viral_source_statuses"] == {"native.bilibili_video": "ready", "native.youtube_video": "ready"}
    sample = brief["hot_viral_samples"][0]
    assert sample["reference_use"] == "analysis_only_no_reuse"
    assert sample["breakdown"]["CTA"] == {"observed": "关注看更多", "field": "voiceover.segments[-1]"}
    assert brief["hot_viral_samples"][1]["metrics"] == {"view": 9, "like": 2, "comment": None, "repost": None,
                                                        "view_count": 9, "like_count": 2}
    result = build_hot_viral_intelligence(target_platform="douyin_pet", lane="pet_healing",
                                          samples=brief["hot_viral_samples"], source_statuses=brief["hot_viral_source_statuses"])
    assert result["status"] == "fallback_ready"
    assert result["strategy_context"]["claim_scope"] == "cross_platform_same_lane_reference_only"


def test_pet_reference_with_one_source_stays_blocked(tmp_path, monkeypatch):
    from content_platform.hot_viral_intelligence import build_hot_viral_intelligence

    monkeypatch.setitem(overnight_benchmarks.COLLECTORS, "bilibili_pet", lambda items, out: [_observed_row("bilibili", "BV1")])
    def unavailable(items, out):
        raise ValueError("youtube_metadata_unavailable")
    monkeypatch.setitem(overnight_benchmarks.COLLECTORS, "youtube_pet", unavailable)
    monkeypatch.setattr("content_platform.task_source_inputs._observed_strategy_inputs",
                        lambda platform, public: {"viral_breakdown": {}})
    prepared = {"tasks": [{"platform": "douyin_pet", "state": "ready_for_plan", "brief": {"lane": "pet_healing"}}]}

    overnight_benchmarks.attach_breakdowns(prepared, [], tmp_path)

    brief = prepared["tasks"][0]["brief"]
    result = build_hot_viral_intelligence(target_platform="douyin_pet", lane="pet_healing",
                                          samples=brief["hot_viral_samples"], source_statuses=brief["hot_viral_source_statuses"])
    assert result["status"] == "blocked"
