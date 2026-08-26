import json
from pathlib import Path

from content_platform.overnight_batch import (
    BatchEventJournal,
    build_due_tasks,
    build_batch_plan,
    execute_batch,
    growth_strategy_snapshot_status,
    normalize_delivery_boundary,
    candidate_matches_topic_keywords,
    candidate_matches_platform_language,
    prefer_platform_source_candidates,
    topic_keywords_for_slot,
)
from content_platform.store import Store


def test_platform_source_preference_keeps_real_platform_candidates_first():
    candidates = [
        {"title": "Generic AI headline", "source": "hackernews"},
        {"title": "Platform trend", "source": "kuaishou"},
    ]
    sources = [{"source": "kuaishou", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}]

    ordered = prefer_platform_source_candidates("kuaishou", candidates, sources)

    assert [row["title"] for row in ordered] == ["Platform trend", "Generic AI headline"]


def test_platform_source_preference_does_not_claim_missing_source_is_verified():
    candidates = [{"title": "Generic AI headline", "source": "hackernews"}]
    sources = [{"source": "hackernews", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}]

    assert prefer_platform_source_candidates("xiaohongshu", candidates, sources) == candidates


def test_batch_plan_schedules_all_due_work_before_morning_window():
    plan = build_batch_plan(
        [
            {"platform": "wechat", "stage": "article", "estimate_minutes": 25},
            {"platform": "kuaishou", "stage": "video", "estimate_minutes": 70},
            {"platform": "youtube", "stage": "handoff_video", "estimate_minutes": 70},
        ],
        start_minute=0,
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "scheduled"
    assert plan["remaining_minutes"] >= 0
    assert [row["platform"] for row in plan["tasks"]] == ["wechat", "kuaishou", "youtube"]
    assert all(row["state"] == "queued" for row in plan["tasks"])


def test_batch_plan_fails_closed_when_all_due_work_cannot_finish_before_morning():
    plan = build_batch_plan(
        [{"platform": "kuaishou", "stage": "video", "estimate_minutes": 300}],
        start_minute=0,
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "capacity_blocked"
    assert plan["tasks"][0]["state"] == "blocked"
    assert "deadline" in plan["tasks"][0]["reason"]


def test_batch_plan_runs_admitted_rows_even_when_later_rows_exceed_capacity():
    plan = build_batch_plan(
        [
            {"platform": "wechat", "estimate_minutes": 10},
            {"platform": "youtube", "estimate_minutes": 300},
        ],
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "partial_capacity"
    assert plan["tasks"][0]["state"] == "queued"
    assert plan["tasks"][1]["state"] == "blocked"


def test_batch_plan_preserves_an_upstream_blocked_topic_selection():
    plan = build_batch_plan(
        [{"platform": "zhihu", "estimate_minutes": 10, "state": "blocked", "reason": "no source evidence"}],
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "capacity_blocked"
    assert plan["tasks"][0]["reason"] == "no source evidence"


def test_batch_event_journal_persists_recoverable_redacted_events(tmp_path: Path):
    journal = BatchEventJournal(tmp_path / "events.jsonl")
    journal.append("platform_started", "wechat", {"token": "abc123-secret", "stage": "analysis"})
    journal.append("platform_finished", "wechat", {"state": "handoff_ready"})

    rows = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["event"] == "platform_started"
    assert "abc123-secret" not in json.dumps(rows[0])
    assert journal.latest_by_platform()["wechat"]["event"] == "platform_finished"


def test_manual_handoff_platform_cannot_be_normalized_to_published():
    assert normalize_delivery_boundary("youtube", "published") == "handoff_ready"
    assert normalize_delivery_boundary("douyin", "drafted") == "handoff_ready"
    assert normalize_delivery_boundary("kuaishou", "published") == "published"


def test_due_task_builder_selects_a_distinct_topic_for_each_due_platform():
    def rank(platform, _items, _slot):
        return [{"title": f"{platform} topic", "platform": platform, "source": platform, "score": 3, "fingerprint": platform}]

    prepared = build_due_tasks(
        [{"platform": "wechat", "estimate_minutes": 20}, {"platform": "youtube", "estimate_minutes": 50}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
    )

    assert [task["topic"] for task in prepared["tasks"]] == ["wechat topic", "youtube topic"]
    assert prepared["tasks"][0]["action"] == "stage"
    assert prepared["tasks"][1]["action"] == "handoff"


def test_due_task_builder_uses_the_next_candidate_when_the_top_topic_is_already_reserved():
    def rank(platform, _items, _slot):
        return [
            {"title": "Shared topic", "platform": platform, "source": "github", "score": 5, "fingerprint": "shared-topic"},
            {"title": "Distinct topic", "platform": platform, "source": "github", "score": 4, "fingerprint": "distinct-topic"},
        ]

    prepared = build_due_tasks(
        [{"platform": "wechat"}, {"platform": "kuaishou"}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
    )

    assert [task["topic"] for task in prepared["tasks"]] == ["Shared topic", "Distinct topic"]


def test_due_task_builder_blocks_a_duplicate_only_candidate_instead_of_reusing_it():
    def rank(platform, _items, _slot):
        return [{"title": "Shared topic", "platform": platform, "source": "github", "score": 5, "fingerprint": "shared-topic"}]

    prepared = build_due_tasks(
        [{"platform": "wechat"}, {"platform": "kuaishou"}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
    )

    assert prepared["tasks"][1]["state"] == "blocked"
    assert prepared["tasks"][1]["reason"] == "no independently evidenced same-platform topic candidate"


def test_due_task_builder_blocks_a_topic_reserved_by_a_prior_manual_publication():
    prepared = build_due_tasks(
        [{"platform": "kuaishou"}],
        items=[],
        source_report=[{"source": "kuaishou", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}],
        rank_for_platform=lambda *_args: [{"title": "AI workflow", "platform": "kuaishou", "source": "kuaishou", "fingerprint": "ai-workflow", "score": 1.0}],
        reserved_topic_fingerprints={"ai-workflow"},
    )

    task = prepared["tasks"][0]
    assert task["state"] == "blocked"
    assert task["reason"] == "topic already reserved by recent delivery"


def test_due_task_builder_allows_evidenced_natural_overlap_with_distinct_execution_angles():
    def rank(platform, _items, _slot):
        return [{"title": "Shared topic", "platform": platform, "source": platform, "score": 5, "fingerprint": "shared-topic"}]

    report = [
        {"source": source, "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}
        for source in ("wechat", "zhihu", "github", "hackernews", "bilibili", "weibo", "x", "juejin")
    ]
    prepared = build_due_tasks(
        [
            {"platform": "wechat", "platform_adaptation_reason": "personal field guide", "platform_signal": "wechat reader questions", "follow_up_to": "shared-topic", "difference_angle": "personal checklist", "recap_reason": "same source, different reader job"},
            {"platform": "zhihu", "platform_adaptation_reason": "evidence-led answer", "platform_signal": "zhihu question demand", "follow_up_to": "shared-topic", "difference_angle": "evidence answer", "recap_reason": "same source, different reader job"},
        ],
        items=[],
        source_report=report,
        rank_for_platform=rank,
        growth_strategy_status={"wechat": {"status": "ok"}, "zhihu": {"status": "ok"}},
        strict_trend_evidence=True,
    )

    assert [task["state"] for task in prepared["tasks"]] == ["ready_for_plan", "ready_for_plan"]
    assert prepared["tasks"][1]["brief"]["platform_source_matrix"]["platform_internal_verified"] is True


def test_due_task_builder_blocks_same_topic_for_two_video_lanes_even_with_evidence():
    def rank(platform, _items, _slot):
        return [{"title": "Shared topic", "source": platform, "score": 5, "fingerprint": "shared-topic"}]

    report = [{"source": source, "status": "ok"} for source in ("kuaishou", "douyin", "github", "hackernews", "bilibili", "weibo", "x", "juejin")]
    prepared = build_due_tasks(
        [
            {"platform": "kuaishou", "stage": "video", "platform_adaptation_reason": "short practical hook", "platform_signal": "kuaishou signal"},
            {"platform": "douyin_ai", "stage": "handoff_video", "platform_adaptation_reason": "AI demo story", "platform_signal": "douyin signal"},
        ],
        items=[],
        source_report=report,
        rank_for_platform=rank,
        growth_strategy_status={"kuaishou": {"status": "ok"}, "douyin_ai": {"status": "ok"}},
        strict_trend_evidence=True,
    )

    assert prepared["tasks"][1]["state"] == "blocked"


def test_due_task_builder_applies_a_final_platform_candidate_filter():
    prepared = build_due_tasks(
        [{"platform": "wechat"}],
        items=[],
        source_report=[],
        rank_for_platform=lambda *_args: [{"title": "irrelevant", "fingerprint": "irrelevant"}],
        candidate_filter=lambda *_args: False,
    )

    assert prepared["tasks"][0]["state"] == "blocked"


def test_due_task_builder_researches_the_lane_before_blocking():
    rounds = []

    def requery(platform, _items, _slot, round_number):
        rounds.append((platform, round_number))
        if round_number == 2:
            return [{"title": "AI meeting workflow", "platform": "tiktok", "source": "tiktok", "fingerprint": "meeting", "score": 2.0}]
        return []

    report = [
        {"source": source, "status": "ok", "collected_at": "2026-08-18T00:00:00+00:00"}
        for source in ("tiktok", "youtube", "github", "hackernews", "bilibili", "weibo", "x", "juejin")
    ]
    prepared = build_due_tasks(
        [{"platform": "tiktok", "topic_keywords": ["AI", "workflow"]}],
        items=[],
        source_report=report,
        rank_for_platform=lambda *_args: [{"title": "unrelated sport", "source": "tiktok"}],
        candidate_filter=lambda _platform, candidate, _slot: "AI" in candidate.get("title", ""),
        requery_for_platform=requery,
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    assert task["state"] == "ready_for_plan"
    assert task["topic"] == "AI meeting workflow"
    assert task["research_attempts"] == [
        {"round": 1, "candidate_count": 0},
        {"round": 2, "candidate_count": 1},
    ]


def test_due_task_builder_uses_only_complete_labeled_editorial_fallback():
    prepared = build_due_tasks(
        [{
            "platform": "tiktok",
            "editorial_fallback": {
                "topic": "Three checks before trusting AI notes",
                "strategy_source": "growth_strategy:tiktok:latest",
                "calendar_column": "workflow_checklist",
                "planned_for": "2026-08-18",
                "dedupe_passed": True,
            },
        }],
        items=[],
        source_report=[],
        rank_for_platform=lambda *_args: [],
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    assert task["state"] == "ready_for_plan"
    assert task["selection_mode"] == "editorial_calendar"
    assert task["brief"]["editorial_evidence"]["dedupe_passed"] is True


def test_due_task_builder_rejects_incomplete_editorial_fallback():
    prepared = build_due_tasks(
        [{"platform": "tiktok", "editorial_fallback": {"topic": "generic idea"}}],
        items=[],
        source_report=[],
        rank_for_platform=lambda *_args: [],
        strict_trend_evidence=True,
    )
    assert prepared["tasks"][0]["state"] == "blocked"


def test_due_task_builder_blocks_when_strict_trend_evidence_is_incomplete():
    prepared = build_due_tasks(
        [{"platform": "zhihu"}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=lambda *_args: [{"title": "AI workflow", "platform": "zhihu", "fingerprint": "ai-workflow", "score": 1.0}],
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    assert task["state"] == "blocked"
    assert task["rejected_matrix"]["sources_attempted"] == 1


def test_due_task_builder_does_not_fabricate_platform_evidence_from_generic_sources():
    report = [{"source": f"generic-{index}", "status": "ok"} for index in range(8)]
    prepared = build_due_tasks(
        [{"platform": "zhihu"}],
        items=[],
        source_report=report,
        rank_for_platform=lambda *_args: [{"title": "Agent workflow", "platform": "zhihu", "fingerprint": "agent-workflow", "score": 1.0}],
        growth_strategy_status={"zhihu": {"status": "ok", "key": "growth_strategy:zhihu:latest"}},
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    matrix = task["rejected_matrix"]
    assert task["state"] == "blocked"
    assert matrix["platform_internal_verified"] is False
    assert task["reason"] == "no independently evidenced same-platform topic candidate"


def test_due_task_builder_rejects_a_platform_named_candidate_without_real_collection_evidence():
    report = [
        {"source": f"generic-{index}", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}
        for index in range(8)
    ]
    prepared = build_due_tasks(
        [{"platform": "zhihu"}],
        items=[],
        source_report=report,
        rank_for_platform=lambda *_args: [{"title": "Agent workflow", "platform": "zhihu", "source": "zhihu_hot", "fingerprint": "agent-workflow", "score": 1.0}],
        growth_strategy_status={"zhihu": {"status": "ok", "key": "growth_strategy:zhihu:latest"}},
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    assert task["state"] == "blocked"
    assert task["reason"] == "no independently evidenced same-platform topic candidate"


def test_due_task_builder_rejects_a_web_search_candidate_as_native_platform_evidence():
    report = [
        {"source": f"generic-{index}", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}
        for index in range(7)
    ] + [{"source": "douyin", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}]
    prepared = build_due_tasks(
        [{"platform": "douyin_ai"}],
        items=[],
        source_report=report,
        rank_for_platform=lambda *_args: [{"title": "AI workflow", "platform": "douyin_ai", "source": "douyin:web_search", "fingerprint": "ai-workflow", "score": 1.0}],
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    assert task["state"] == "blocked"
    assert task["rejected_matrix"]["real_platform_collection_verified"] is False


def test_due_task_builder_accepts_candidate_only_when_its_exact_native_source_was_collected():
    report = [
        {"source": f"generic-{index}", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}
        for index in range(7)
    ] + [{"source": "douyin", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}]
    prepared = build_due_tasks(
        [{"platform": "douyin_ai"}],
        items=[],
        source_report=report,
        rank_for_platform=lambda *_args: [{"title": "AI workflow", "platform": "douyin_ai", "source": "douyin", "fingerprint": "ai-workflow", "score": 1.0}],
        strict_trend_evidence=True,
        growth_strategy_status={
            "douyin_ai": {
                "status": "ok",
                "same_lane_intelligence": {
                    "version": "same_lane_playbook_compact_v1",
                    "topic_patterns": ["tool_workflow_tutorial"],
                },
            }
        },
    )

    task = prepared["tasks"][0]
    assert task["state"] == "ready_for_plan"
    assert task["brief"]["platform_source_matrix"]["real_platform_collection_verified"] is True
    assert task["brief"]["run_contract"]["platform"] == "douyin_ai"
    assert task["brief"]["run_contract"]["publish_boundary"] == "manual_handoff_only"
    assert task["brief"]["bounded_model_input"]["content_blueprint"]["topic"] == "AI workflow"
    assert set(task["brief"]["bounded_model_input"]) <= {
        "content_blueprint", "claim_ledger", "tool_selection_plan", "strategy", "content_quality_reference_pack", "runtime_capabilities", "same_lane_intelligence", "hot_work_parameter_pack"
    }
    assert task["brief"]["bounded_model_input"]["same_lane_intelligence"]["topic_patterns"] == ["tool_workflow_tutorial"]
    assert task["brief"]["content_blueprint_gate"]["passed"] is True
    assert task["brief"]["content_quality_reference_gate"]["passed"] is True
    assert task["brief"]["bounded_model_input"]["content_quality_reference_pack"]["loaded"] is True
    assert task["brief"]["bounded_model_input"]["runtime_capabilities"]["version"] == "runtime_capabilities_v1"
    assert len(__import__("json").dumps(task["brief"]["bounded_model_input"], ensure_ascii=False).encode("utf-8")) <= 16384
    tool_plan = task["brief"]["bounded_model_input"]["tool_selection_plan"]
    assert len(tool_plan["selected_tools"]) >= 6
    assert tool_plan["invocation_order"] == tool_plan["selected_tools"]
    assert tool_plan["selection_reasons"]


def test_due_task_builder_treats_platform_web_search_as_discovery_only():
    report = [
        {"source": f"generic-{index}", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}
        for index in range(7)
    ] + [{"source": "kuaishou:web_search", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}]
    prepared = build_due_tasks(
        [{"platform": "kuaishou", "content_form": "short_video"}],
        items=[],
        source_report=report,
        rank_for_platform=lambda *_args: [{
            "title": "快手 AI 开放平台",
            "platform": "kuaishou",
            "source": "kuaishou:web_search",
            "url": "https://ai.kuaishou.com/creation",
            "fingerprint": "kuaishou-ai",
            "score": 1.0,
        }],
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    assert task["state"] == "blocked"
    assert task["reason"] == "no independently evidenced same-platform topic candidate"


def test_platform_source_preference_does_not_promote_web_search_discovery():
    from content_platform.overnight_batch import prefer_platform_source_candidates

    candidates = [
        {"title": "External", "source": "github", "url": "https://github.com/example/project"},
        {"title": "Native", "source": "kuaishou:web_search", "url": "https://ai.kuaishou.com/creation"},
    ]
    ordered = prefer_platform_source_candidates(
        "kuaishou",
        candidates,
        [{"source": "kuaishou", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}],
    )
    assert ordered[0]["title"] == "External"


def test_due_task_builder_uses_editorial_fallback_after_invalid_native_candidate():
    report = [
        {"source": f"generic-{index}", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}
        for index in range(7)
    ] + [{"source": "zhihu", "status": "ok", "collected_at": "2026-08-16T00:00:00+00:00"}]
    prepared = build_due_tasks(
        [{
            "platform": "zhihu",
            "editorial_fallback": {
                "topic": "A unique engineering field guide",
                "direction": "engineering_field_guide",
                "strategy_source": "growth_strategy:zhihu:latest",
                "calendar_column": "engineering",
                "planned_date": "2026-08-18",
                "dedupe": "7d_clear",
            },
        }],
        items=[],
        source_report=report,
        rank_for_platform=lambda *_args: [{"title": "Bad web candidate", "source": "zhihu:web_search", "fingerprint": "bad", "score": 1.0}],
        growth_strategy_status={"zhihu": {"status": "ok", "key": "growth_strategy:zhihu:latest"}},
        strict_trend_evidence=True,
    )

    task = prepared["tasks"][0]
    assert task["state"] == "ready_for_plan"
    assert task["selection_mode"] == "editorial_calendar"
    assert task["topic"] == "A unique engineering field guide"


def test_sync_batch_state_records_actual_job_and_delivery_state(tmp_path: Path):
    from content_platform.overnight_batch import sync_batch_state

    store = Store(tmp_path / "state.db")
    job = store.create_job("topic", ["kuaishou"])
    store.save_delivery(job["id"], "kuaishou", "drafted", "remote-draft")
    state = {"status": "partial", "tasks": [{"platform": "kuaishou", "job_id": job["id"], "state": "failed"}]}

    report = sync_batch_state(state, store, summary_path=tmp_path / "acceptance_summary.json")

    task = state["tasks"][0]
    assert task["state"] == "drafted"
    assert task["job_state"] == "created"
    assert task["delivery_states"] == ["drafted"]
    assert report["platforms"][0]["state"] == "drafted"
    assert (tmp_path / "acceptance_summary.json").is_file()


def test_sync_batch_state_keeps_failed_acceptance_blocked(tmp_path: Path):
    from content_platform.overnight_batch import sync_batch_state

    store = Store(tmp_path / "state.db")
    job = store.create_job("topic", ["wechat"])
    store.save_workflow_acceptance(job["id"], {"passed": False, "failures": ["long_form_cta_missing"]})
    state = {"status": "partial", "tasks": [{"platform": "wechat", "job_id": job["id"], "state": "review_required"}]}

    sync_batch_state(state, store)

    assert state["tasks"][0]["state"] == "blocked"


def test_sync_batch_state_maps_legacy_review_required_to_awaiting_review(tmp_path: Path):
    from content_platform.overnight_batch import sync_batch_state

    store = Store(tmp_path / "state.db")
    job = store.create_job("topic", ["twitter"])
    store.transition(job["id"], {"created"}, "review_required", "review_requested")
    state = {"status": "partial", "tasks": [{"platform": "twitter", "job_id": job["id"], "state": "review_required"}]}

    sync_batch_state(state, store)

    assert state["tasks"][0]["state"] == "awaiting_review"


def test_sync_batch_state_marks_legacy_published_delivery_pending_verification(tmp_path: Path):
    from content_platform.overnight_batch import sync_batch_state

    store = Store(tmp_path / "state.db")
    job = store.create_job("topic", ["twitter"])
    store.save_delivery(job["id"], "twitter", "published", "remote:123")
    state = {"status": "partial", "tasks": [{"platform": "twitter", "job_id": job["id"], "state": "published"}]}

    sync_batch_state(state, store)

    assert state["tasks"][0]["state"] == "published_pending_verification"


def test_sync_batch_state_does_not_upgrade_a_blocked_manual_handoff(tmp_path: Path):
    from content_platform.overnight_batch import sync_batch_state

    store = Store(tmp_path / "state.db")
    job = store.create_job("topic", ["douyin_ai"])
    store.save_delivery(job["id"], "douyin_ai", "handoff_pending", "packet")
    state = {
        "status": "partial",
        "tasks": [{"platform": "douyin_ai", "job_id": job["id"], "state": "handoff_ready", "reason": "handoff_media_missing"}],
    }

    sync_batch_state(state, store)

    assert state["tasks"][0]["state"] == "blocked"
    assert state["tasks"][0]["reason"] == "handoff_media_missing"


def test_sync_batch_state_marks_parent_partial_when_a_job_is_blocked(tmp_path: Path):
    from content_platform.overnight_batch import sync_batch_state

    store = Store(tmp_path / "state.db")
    job = store.create_job("topic", ["wechat"])
    store.save_workflow_acceptance(job["id"], {"passed": False, "failures": ["long_form_too_short"]})
    state = {"status": "completed", "tasks": [{"platform": "wechat", "job_id": job["id"], "state": "drafted"}]}

    report = sync_batch_state(state, store)

    assert state["status"] == "partial"
    assert report["batch_status"] == "partial"


def test_due_task_builder_blocks_when_growth_strategy_snapshot_is_missing():
    def rank(platform, _items, _slot):
        return [{"title": f"{platform} topic", "source": platform, "score": 3, "fingerprint": platform}]

    prepared = build_due_tasks(
        [{"platform": "zhihu", "estimate_minutes": 20}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
        growth_strategy_status={"zhihu": {"status": "missing", "key": "growth_strategy:zhihu:latest"}},
    )

    assert prepared["tasks"][0]["state"] == "blocked"
    assert prepared["tasks"][0]["reason"] == "growth strategy snapshot missing"


def test_growth_strategy_snapshot_status_reads_store_inventory(tmp_path: Path):
    store = Store(tmp_path / "state.db")
    store.save_tool_inventory("growth_strategy:wechat:latest", {
        "policy_id": "growth_quality_policy_v1",
        "primary_metric": "click_through_rate",
        "retention_plan": {"first_3_seconds": "lead with a concrete result"},
    })

    status = growth_strategy_snapshot_status(store, ["wechat", "zhihu"])

    assert status["wechat"]["status"] == "ok"
    assert status["wechat"]["compiled_strategy"]["version"] == "compiled_strategy_v1"
    assert status["wechat"]["runtime_growth_strategy"]["primary_metric"] == "click_through_rate"
    assert status["zhihu"] == {"status": "missing", "key": "growth_strategy:zhihu:latest"}


def test_growth_strategy_snapshot_status_maps_twitter_to_the_x_strategy_snapshot(tmp_path: Path):
    store = Store(tmp_path / "state.db")
    store.save_tool_inventory("growth_strategy:x:latest", {"policy_id": "growth_quality_policy_v1"})

    status = growth_strategy_snapshot_status(store, ["twitter"])

    assert status["twitter"]["status"] == "ok"
    assert status["twitter"]["key"] == "growth_strategy:x:latest"


def test_pet_lane_rejects_an_unrelated_general_news_candidate():
    keywords = topic_keywords_for_slot("douyin_pet", {}, {"keywords": ["AI"]})

    assert candidate_matches_topic_keywords({"title": "Facebook pays controversial rage-bait creators"}, keywords) is False
    assert candidate_matches_topic_keywords({"title": "Three signs your cat is stressed"}, keywords) is True


def test_ai_keyword_does_not_match_a_substring_inside_an_unrelated_word():
    assert candidate_matches_topic_keywords({"title": "Facebook pays rage-bait creators"}, ["ai"]) is False
    assert candidate_matches_topic_keywords({"title": "AI agents change workflows"}, ["ai"]) is True
    title = "\u6296\u97f3AI\u77ed\u89c6\u9891\u5de5\u5177\u5b9e\u6218"
    assert candidate_matches_topic_keywords({"title": title}, ["ai"]) is True


def test_english_platform_rejects_a_chinese_headline_even_when_it_mentions_ai():
    assert candidate_matches_platform_language("twitter", {"title": "如何看待 AIGC 工具"}) is False
    assert candidate_matches_platform_language("twitter", {"title": "AI agents change team workflows"}) is True


def test_execute_batch_runs_each_platform_independently_and_persists_resume_state(tmp_path: Path):
    final = tmp_path / "final.mp4"
    cover = tmp_path / "cover.png"
    final.write_bytes(b"video")
    cover.write_bytes(b"cover")

    class Pipeline:
        def __init__(self):
            self.created = []

        def create(self, topic, platforms, brief, profile="default"):
            self.created.append((topic, platforms, brief, profile))
            return {"id": f"job-{len(self.created)}"}

        def run(self, job_id):
            return {
                "id": job_id,
                "state": "review_required",
                "artifacts": [
                    {"kind": "video", "path": str(final)},
                    {"kind": "cover", "path": str(cover)},
                ],
            }

        def stage_drafts(self, job_id):
            if job_id == "job-2":
                return {"id": job_id, "state": "partial", "deliveries": [{"platform": "youtube", "status": "handoff_pending", "external_id": "handoff:youtube"}]}
            return {"id": job_id, "state": "partial", "deliveries": [{"platform": "wechat", "status": "drafted", "external_id": "draft:wechat"}]}

    plan = build_batch_plan(
        [
            {"platform": "wechat", "topic": "WeChat topic", "brief": {}, "stage": "article", "estimate_minutes": 10, "action": "stage"},
            {"platform": "youtube", "topic": "YouTube topic", "brief": {}, "stage": "handoff_video", "estimate_minutes": 10},
        ],
        deadline_minute=280,
        finalization_minutes=20,
    )
    pipeline = Pipeline()
    state_path = tmp_path / "state.json"
    summary = execute_batch(pipeline, plan, state_path=state_path, journal=BatchEventJournal(tmp_path / "events.jsonl"))

    assert summary["status"] == "completed"
    assert [item[1] for item in pipeline.created] == [["wechat"], ["youtube"]]
    assert all(item[2]["automated_workflow"] is True for item in pipeline.created)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["tasks"][0]["state"] == "staged"
    assert state["tasks"][1]["state"] == "handoff_ready"
    events = [json.loads(line)["event"] for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "platform_job_created" in events
    assert "platform_generation_complete" in events
    assert "platform_staging_started" in events


def test_execute_batch_records_a_completed_topic_in_the_global_ledger(tmp_path: Path):
    store = Store(tmp_path / "state.db")

    class Pipeline:
        def create(self, topic, platforms, brief, profile="default"):
            return store.create_job(topic, platforms, brief, profile, "ai-workflow")

        def run(self, _job_id):
            return {"id": "job-1", "state": "review_required", "artifacts": []}

        def stage_drafts(self, _job_id):
            store.save_delivery(_job_id, "twitter", "drafted", "draft:demo")
            return {"state": "drafted"}

    plan = {
        "status": "scheduled",
        "tasks": [{"platform": "twitter", "topic": "AI workflow", "topic_fingerprint": "ai-workflow", "brief": {"source": "twitter"}, "action": "stage", "state": "ready_for_plan"}],
    }

    result = execute_batch(Pipeline(), plan, state_path=tmp_path / "state.json", journal=BatchEventJournal(tmp_path / "events.jsonl"), store=store)

    assert result["tasks"][0]["state"] == "drafted"
    assert "ai-workflow" in store.used_topics(lookback_days=7)


def test_execute_batch_marks_failed_rows_as_batch_failure_without_rerunning_them(tmp_path: Path):
    class Pipeline:
        def create(self, *_args, **_kwargs):
            return {"id": "job-1"}

        def run(self, _job_id):
            raise RuntimeError("provider_auth_failed")

    plan = build_batch_plan([{"platform": "wechat", "topic": "topic", "brief": {}, "estimate_minutes": 10}], deadline_minute=280, finalization_minutes=20)
    state_path = tmp_path / "state.json"
    summary = execute_batch(Pipeline(), plan, state_path=state_path, journal=BatchEventJournal(tmp_path / "events.jsonl"))

    assert summary["status"] == "failed"
    assert summary["tasks"][0]["state"] == "failed"
    assert execute_batch(Pipeline(), plan, state_path=state_path, journal=BatchEventJournal(tmp_path / "events.jsonl"))["status"] == "failed"


def test_execute_batch_retries_one_transient_provider_failure_without_republishing(tmp_path: Path):
    class Pipeline:
        def __init__(self):
            self.runs = 0

        def create(self, *_args, **_kwargs):
            return {"id": "job-1"}

        def run(self, _job_id):
            self.runs += 1
            if self.runs == 1:
                raise RuntimeError("upstream timeout while generating draft")
            return {"id": "job-1", "state": "review_required", "artifacts": []}

        def stage_drafts(self, _job_id):
            return {"id": "job-1", "state": "partial"}

    plan = build_batch_plan([{"platform": "wechat", "topic": "topic", "brief": {}, "estimate_minutes": 10}], deadline_minute=280, finalization_minutes=20)
    pipeline = Pipeline()
    journal_path = tmp_path / "events.jsonl"
    summary = execute_batch(pipeline, plan, state_path=tmp_path / "state.json", journal=BatchEventJournal(journal_path))

    assert summary["status"] == "completed"
    assert summary["tasks"][0]["state"] == "staged"
    assert summary["tasks"][0]["retry_count"] == 1
    assert pipeline.runs == 2
    events = [json.loads(line)["event"] for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert "platform_retry_scheduled" in events


def test_execute_batch_marks_only_blocked_rows_partial(tmp_path: Path):
    class Pipeline:
        def create(self, *_args, **_kwargs):
            return {"id": "job-1"}

        def run(self, _job_id):
            return {"id": "job-1", "state": "review_required"}

        def stage_drafts(self, _job_id):
            return {"id": "job-1", "state": "partial"}

    plan = build_batch_plan(
        [
            {"platform": "wechat", "topic": "topic", "brief": {}, "action": "stage", "estimate_minutes": 10},
            {"platform": "douyin_pet", "state": "blocked", "reason": "no source", "estimate_minutes": 10},
        ],
        deadline_minute=280,
        finalization_minutes=20,
    )

    summary = execute_batch(Pipeline(), plan, state_path=tmp_path / "state.json", journal=BatchEventJournal(tmp_path / "events.jsonl"))

    assert summary["status"] == "partial"


def test_interrupted_running_task_is_retried_once_after_reconciliation(tmp_path: Path):
    plan = build_batch_plan([{"platform": "wechat", "topic": "topic", "brief": {}, "estimate_minutes": 10}], deadline_minute=280, finalization_minutes=20)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"status": "running", "tasks": [{"platform": "wechat", "state": "running", "topic": "topic"}]}), encoding="utf-8")

    class Pipeline:
        creates = 0

        def create(self, *_args, **_kwargs):
            self.creates += 1
            return {"id": "replacement-job"}

        def run(self, _job_id):
            return {"id": "replacement-job", "state": "review_required"}

        def stage_drafts(self, _job_id):
            return {"id": "replacement-job", "state": "partial"}

    pipeline = Pipeline()
    summary = execute_batch(pipeline, plan, state_path=state_path, journal=BatchEventJournal(tmp_path / "events.jsonl"))

    assert summary["status"] == "completed"
    assert summary["tasks"][0]["state"] == "staged"
    assert summary["tasks"][0]["recovery_count"] == 1
    assert pipeline.creates == 1


def test_review_required_task_is_terminal_on_resume(tmp_path: Path):
    plan = build_batch_plan([{"platform": "wechat", "topic": "topic", "brief": {}, "estimate_minutes": 10}], deadline_minute=280, finalization_minutes=20)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"status": "partial", "tasks": [{"platform": "wechat", "state": "review_required", "topic": "topic"}]}), encoding="utf-8")

    class Pipeline:
        def create(self, *_args, **_kwargs):
            raise AssertionError("review-required work must not be recreated")

    summary = execute_batch(Pipeline(), plan, state_path=state_path, journal=BatchEventJournal(tmp_path / "events.jsonl"))

    assert summary["tasks"][0]["state"] == "awaiting_review"


def test_manual_video_handoff_is_blocked_when_the_pipeline_returns_no_video_or_cover(tmp_path: Path):
    class Pipeline:
        def create(self, *_args, **_kwargs):
            return {"id": "job-video"}

        def run(self, _job_id):
            return {"id": "job-video", "state": "review_required", "artifacts": []}

        def stage_drafts(self, _job_id):
            return {"id": "job-video", "state": "partial", "deliveries": []}

    plan = build_batch_plan([{"platform": "douyin_ai", "topic": "topic", "brief": {}, "estimate_minutes": 10}], deadline_minute=280, finalization_minutes=20)
    summary = execute_batch(Pipeline(), plan, state_path=tmp_path / "state.json", journal=BatchEventJournal(tmp_path / "events.jsonl"))

    assert summary["status"] == "partial"
    assert summary["tasks"][0]["state"] == "blocked"
    assert summary["tasks"][0]["reason"] == "verified handoff package was not produced"
