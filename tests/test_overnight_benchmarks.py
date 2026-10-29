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
    prepared = {"tasks": [{"platform": lane, "state": "ready_for_plan"} for lane in ("kuaishou", "tiktok", "douyin_ai")]}

    overnight_benchmarks.attach_breakdowns(prepared, [], tmp_path)

    assert calls == [1] and platforms == ["bilibili"] * 3
    assert all(task["brief"]["cross_platform_source"] == "bilibili" for task in prepared["tasks"])
