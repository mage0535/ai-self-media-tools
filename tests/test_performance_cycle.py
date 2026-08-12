import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from content_platform.performance_cycle import DEFAULT_GROWTH_PLATFORMS, metrics_readiness_report, run_performance_cycle
from content_platform.store import Store


FAKE_COLLECTION = {
    "status": "ok",
    "platforms": {
        "youtube": {"status": "ok", "account_metrics": {"subscribers": 8, "videos": 227, "views": 11016, "extra_metrics": {"metric_source": "test_content_export", "metric_scope": "content_aggregate", "strategy_eligible": True}}},
        "bilibili": {"status": "ok", "account_metrics": {"fans": 12, "videos": 3, "likes": 44, "extra_metrics": {"metric_source": "test_content_export", "metric_scope": "content_aggregate", "strategy_eligible": True}}},
        "douyin": {"status": "login_required", "reason": "state_file missing"},
    },
}


def test_default_growth_platforms_cover_current_single_line_workflow():
    assert DEFAULT_GROWTH_PLATFORMS == [
        "wechat",
        "kuaishou",
        "bilibili",
        "zhihu",
        "juejin",
        "douyin",
        "shipinhao",
        "xiaohongshu",
        "youtube",
        "tiktok",
        "x",
    ]


def test_performance_cycle_persists_metrics_and_growth_strategy():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=FAKE_COLLECTION):
            report = run_performance_cycle(
                store,
                platforms=["youtube", "bilibili", "douyin"],
                collector_config={},
                output_dir=Path(tmp) / "performance",
                use_hermes_scraper=False,
            )

        assert report["activity"]["collector_ran"] is True
        assert report["activity"]["metrics_saved"] == 2
        assert report["activity"]["unavailable_count"] == 1
        assert Path(report["output"]).is_file()
        summary = store.feedback_summary()
        assert summary["platforms"]["youtube"]["follows"] == 8
        assert summary["platforms"]["bilibili"]["follows"] == 12
        assert store.latest_tool_inventory("growth_strategy:youtube:latest")["payload"]["historical_feedback_status"] == "available"


def test_performance_cycle_refreshes_douyin_account_variant_strategies():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=FAKE_COLLECTION):
            report = run_performance_cycle(
                store,
                platforms=["douyin"],
                collector_config={},
                output_dir=Path(tmp) / "performance",
                use_hermes_scraper=False,
            )

        assert "douyin_pet" in report["growth_strategies"]
        assert "douyin_ai" in report["growth_strategies"]
        assert store.latest_tool_inventory("growth_strategy:douyin_pet:latest")["payload"]["account_key"] == "douyin_pet"
        assert store.latest_tool_inventory("growth_strategy:douyin_ai:latest")["payload"]["account_key"] == "douyin_ai"


def test_douyin_account_variants_do_not_borrow_base_platform_history():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        base_job = store.create_job("base Douyin snapshot", ["douyin"], {"source": "test"})
        store.record_performance(
            base_job["id"],
            "douyin",
            views=1000,
            likes=80,
            extra_metrics={"strategy_eligible": True, "metric_scope": "content_aggregate"},
        )
        collection = {"status": "ok", "platforms": {"douyin": {"status": "login_required", "reason": "test"}}}
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["douyin"], output_dir=Path(tmp) / "performance")

        for account_key in ("douyin_pet", "douyin_ai"):
            strategy = report["growth_strategies"][account_key]
            assert strategy["historical_feedback_status"] == "missing_or_empty"
            assert strategy["data_driven_improvement_plan"]["status"] == "needs_metrics"


def test_unverified_creator_snapshot_is_saved_for_audit_but_excluded_from_strategy():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "zhihu": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "views": 400,
                        "likes": 20,
                        "extra_metrics": {
                            "metric_source": "creator_backend_page",
                            "metric_scope": "account_snapshot",
                            "strategy_eligible": False,
                        },
                    },
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["zhihu"], output_dir=Path(tmp) / "performance")

        assert len(store.performance()) == 1
        assert store.feedback_summary()["platforms"] == {}
        assert report["persisted"]["items"][0]["status"] == "saved_snapshot_only"
        assert report["growth_strategies"]["zhihu"]["data_driven_improvement_plan"]["status"] == "needs_metrics"


def test_metrics_readiness_requires_separate_douyin_account_sources():
    report = metrics_readiness_report(
        ["douyin"],
        {"douyin": {"state_file": "/private/douyin-main.json"}},
    )

    assert report["accounts"]["douyin"]["status"] == "base_platform_not_strategy_eligible"
    assert report["accounts"]["douyin_pet"]["status"] == "account_source_missing"
    assert report["accounts"]["douyin_ai"]["status"] == "account_source_missing"
    assert report["summary"]["strategy_eligible_count"] == 0


def test_metrics_readiness_accepts_content_aggregate_account_config():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pet = root / "pet.json"
        ai = root / "ai.json"
        pet.write_text(json.dumps({"videos": [{"video_id": "pet-1", "views": 10}]}), encoding="utf-8")
        ai.write_text(json.dumps({"videos": [{"video_id": "ai-1", "views": 20}]}), encoding="utf-8")
        report = metrics_readiness_report(
            ["douyin"],
            {
                "douyin_accounts": {
                    "douyin_pet": {"state_file": "/private/pet.json", "metrics_file": str(pet)},
                    "douyin_ai": {"state_file": "/private/ai.json", "metrics_file": str(ai)},
                }
            },
        )

    assert report["accounts"]["douyin_pet"]["status"] == "content_metrics_configured"
    assert report["accounts"]["douyin_ai"]["status"] == "content_metrics_configured"
    assert report["summary"]["strategy_eligible_count"] == 2


def test_metrics_readiness_requires_identified_rows_in_metrics_file():
    with tempfile.TemporaryDirectory() as tmp:
        metrics_file = Path(tmp) / "aggregate.json"
        metrics_file.write_text(json.dumps({"videos": [{"views": 10, "likes": 1}]}), encoding="utf-8")
        report = metrics_readiness_report(["shipinhao"], {"shipinhao": {"metrics_file": str(metrics_file)}})

    assert report["accounts"]["shipinhao"]["status"] == "content_identity_missing"
    assert report["accounts"]["shipinhao"]["strategy_eligible"] is False


def test_legacy_creator_page_snapshot_is_excluded_without_strategy_flag():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        job = store.create_job("legacy creator page", ["juejin"], {"source": "test"})
        store.record_performance(
            job["id"],
            "juejin",
            views=1_000_000,
            likes=99,
            extra_metrics={"metric_source": "creator_backend_page", "works": 2026},
        )

        assert store.historical_performance(["juejin"], "")["platforms"] == {}


def test_legacy_performance_cycle_without_content_evidence_is_excluded():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        job = store.create_job("performance_snapshot", ["youtube"], {"source": "performance_cycle"})
        store.record_performance(job["id"], "youtube", views=1000, likes=20)
        assert store.feedback_summary()["platforms"] == {}
        assert store.historical_performance(["youtube"], "")["platforms"] == {}


def test_hermes_fallback_snapshot_is_saved_for_audit_only():
    from content_platform.performance_cycle import _merge_collection_reports

    merged = _merge_collection_reports(
        {"status": "ok", "platforms": {"youtube": {"status": "unavailable"}}},
        {"status": "ok", "source": "hermes_platform_scraper", "platforms": {"youtube": {"status": "public_signal", "account_metrics": {"views": 100, "likes": 2}}}},
    )
    extra = merged["platforms"]["youtube"]["account_metrics"]["extra_metrics"]
    assert extra["metric_scope"] == "account_snapshot"
    assert extra["strategy_eligible"] is False


def test_single_platform_cycle_does_not_overwrite_full_cycle_report_file():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        out = Path(tmp) / "performance"
        full_collection = {
            "status": "ok",
            "platforms": {
                platform: {"status": "login_required", "reason": "test only"}
                for platform in DEFAULT_GROWTH_PLATFORMS
            },
        }
        single_collection = {"status": "ok", "platforms": {"x": {"status": "public_signal", "account_metrics": {"followers": 7, "views": 73}}}}
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=full_collection):
            full = run_performance_cycle(store, collector_config={}, output_dir=out)
        full_path = Path(full["output"])
        full_payload = json.loads(full_path.read_text(encoding="utf-8"))
        assert full_payload["activity"]["platform_count"] == 11

        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=single_collection):
            single = run_performance_cycle(store, platforms=["x"], collector_config={}, output_dir=out)

        assert Path(single["output"]).name == "performance_cycle_x.json"
        assert json.loads(full_path.read_text(encoding="utf-8"))["activity"]["platform_count"] == 11
        assert store.latest_tool_inventory("performance_cycle_full_latest")["payload"]["activity"]["platform_count"] == 11


def test_performance_cycle_cli_runs_without_publishing():
    from content_platform.cli import main

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = root / "collector.json"
        cfg.write_text(json.dumps({"youtube": {"channel_url": "https://example.com/youtube"}}), encoding="utf-8")
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value={"status": "ok", "platforms": {"youtube": FAKE_COLLECTION["platforms"]["youtube"]}}):
            code = main(
                [
                    "--db",
                    str(root / "state.db"),
                    "--config",
                    "",
                    "performance-cycle",
                    "--platform",
                    "youtube",
                    "--collector-config",
                    str(cfg),
                    "--output-dir",
                    str(root / "performance"),
                ]
            )
        assert code == 0


def test_performance_cycle_cli_tolerates_missing_private_config():
    from content_platform.cli import main

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value={"status": "ok", "platforms": {}}):
            code = main(
                [
                    "--db",
                    str(root / "state.db"),
                    "--config",
                    "",
                    "performance-cycle",
                    "--platform",
                    "youtube",
                    "--collector-config",
                    str(root / "missing-private.json"),
                    "--output-dir",
                    str(root / "performance"),
                ]
            )
        assert code == 0


def test_performance_cycle_reports_metrics_source_coverage():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value={"status": "ok", "platforms": {}}):
            report = run_performance_cycle(
                store,
                platforms=["douyin", "youtube", "kuaishou"],
                collector_config={
                    "douyin": {"state_file": "/private/douyin.json"},
                    "youtube": {"channel_url": "https://youtube.example/channel"},
                    "kuaishou": {"state_file": "/private/kuaishou.json", "public_profile_url": "https://example.com/kwai"},
                },
                output_dir=Path(tmp) / "performance",
            )

        coverage = report["source_coverage"]
        assert coverage["platforms"]["douyin"]["status"] == "backend_only"
        assert coverage["platforms"]["youtube"]["status"] == "configured"
        assert coverage["platforms"]["kuaishou"]["status"] == "configured"
        assert coverage["needs_attention"] == ["douyin"]


def test_performance_cycle_merges_hermes_fallback_without_overwriting_authenticated_metrics():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        primary = {
            "status": "ok",
            "platforms": {
                "bilibili": {"status": "ok", "account_metrics": {"fans": 12, "videos": 3, "likes": 44}},
                "youtube": {"status": "failed", "reason": "public URL failed"},
            },
        }
        fallback = {
            "status": "ok",
            "source": "hermes_platform_scraper",
            "platforms": {
                "bilibili": {"status": "ok", "account_metrics": {"fans": 0, "videos": 0, "likes": 0}},
                "youtube": {"status": "ok", "account_metrics": {"subscribers": 8, "videos": 227, "views": 11016}},
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=primary), patch(
            "content_platform.performance_cycle.collect_with_hermes_platform_scraper", return_value=fallback
        ):
            report = run_performance_cycle(store, platforms=["bilibili", "youtube"], use_hermes_scraper=True, output_dir=Path(tmp) / "performance")

        rows = {row["platform"]: row for row in store.performance()}
        assert rows["bilibili"]["likes"] == 44
        assert rows["youtube"]["views"] == 11016
        assert report["activity"]["metrics_saved"] == 2


def test_performance_cycle_persists_low_confidence_public_signal():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "douyin": {
                    "status": "public_signal",
                    "account_metrics": {
                        "followers": 123,
                        "likes": 456,
                        "views": 789,
                        "extra_metrics": {"metric_source": "public_page", "metric_confidence": "low"},
                    },
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["douyin"], output_dir=Path(tmp) / "performance")

        rows = store.performance()
        assert len(rows) == 1
        assert rows[0]["platform"] == "douyin"
        assert rows[0]["views"] == 789
        assert rows[0]["likes"] == 456
        assert rows[0]["follows"] == 123
        assert rows[0]["extra_metrics"]["metric_source"] == "public_page"
        assert rows[0]["extra_metrics"]["metric_confidence"] == "low"
        assert rows[0]["extra_metrics"]["metric_status"] == "public_signal"
        assert report["activity"]["metrics_saved"] == 1


def test_performance_cycle_persists_medium_confidence_backend_signal():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "kuaishou": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "followers": 88,
                        "likes": 99,
                        "views": 1234,
                        "extra_metrics": {"metric_source": "creator_backend_page", "metric_confidence": "medium"},
                    },
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["kuaishou"], output_dir=Path(tmp) / "performance")

        row = store.performance()[0]
        assert row["platform"] == "kuaishou"
        assert row["views"] == 1234
        assert row["follows"] == 88
        assert row["extra_metrics"]["metric_source"] == "creator_backend_page"
        assert row["extra_metrics"]["metric_confidence"] == "medium"
        assert row["extra_metrics"]["metric_status"] == "backend_signal"
        assert report["activity"]["metrics_saved"] == 1


def test_performance_cycle_does_not_persist_weak_non_growth_metrics():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "tiktok": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "works": 136,
                        "extra_metrics": {"metric_source": "creator_backend_page", "metric_confidence": "medium"},
                    },
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["tiktok"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert report["activity"]["metrics_saved"] == 0
        assert report["activity"]["unavailable_count"] == 1
        assert report["persisted"]["items"][0]["status"] == "metrics_insufficient"


def test_performance_cycle_does_not_persist_bilibili_likes_without_reach():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "bilibili": {
                    "status": "ok",
                    "account_metrics": {"fans": 0, "videos": 16, "likes": 51},
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["bilibili"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert report["persisted"]["items"][0]["status"] == "metrics_insufficient"


def test_performance_cycle_does_not_persist_suspicious_tiktok_placeholder_metrics():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "tiktok": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "views": 2500,
                        "followers": 2500,
                        "likes": 44,
                        "extra_metrics": {"works": 2500, "metric_source": "creator_backend_page", "metric_confidence": "medium"},
                    },
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["tiktok"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert store.feedback_summary()["platforms"] == {}
        assert report["persisted"]["items"][0]["status"] == "metrics_suspicious"


def test_performance_cycle_does_not_persist_creator_page_chrome_counts():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "xiaohongshu": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "views": 68,
                        "followers": 0,
                        "extra_metrics": {
                            "works": 307000,
                            "metric_source": "creator_backend_page",
                            "metric_confidence": "medium",
                        },
                    },
                }
            },
        }

        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["xiaohongshu"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert report["activity"]["metrics_saved"] == 0
        assert report["persisted"]["items"][0]["status"] == "metrics_suspicious"


def test_performance_cycle_does_not_persist_implausible_creator_backend_ratio():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "juejin": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "views": 2500000,
                        "likes": 211,
                        "comments": 22000,
                        "extra_metrics": {
                            "metric_source": "creator_backend_page",
                            "metric_confidence": "medium",
                        },
                    },
                }
            },
        }

        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["juejin"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert report["persisted"]["items"][0]["status"] == "metrics_suspicious"


def test_performance_cycle_does_not_persist_huge_views_with_tiny_engagement():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "juejin": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "views": 1300000,
                        "likes": 2,
                        "extra_metrics": {
                            "metric_source": "creator_backend_page",
                            "metric_confidence": "medium",
                        },
                    },
                }
            },
        }

        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["juejin"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert report["persisted"]["items"][0]["status"] == "metrics_suspicious"


def test_performance_cycle_does_not_persist_tiktok_zero_view_save_placeholder():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "tiktok": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "works": 139,
                        "views": 0,
                        "saves": 2,
                        "extra_metrics": {"metric_source": "creator_backend_page", "metric_confidence": "medium"},
                    },
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["tiktok"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert report["persisted"]["items"][0]["status"] == "metrics_insufficient"


def test_performance_cycle_does_not_persist_tiktok_followers_only_metrics():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        collection = {
            "status": "ok",
            "platforms": {
                "tiktok": {
                    "status": "backend_signal",
                    "account_metrics": {
                        "followers": 1,
                        "works": 1,
                        "extra_metrics": {"metric_source": "creator_backend_page", "metric_confidence": "medium"},
                    },
                }
            },
        }
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=collection):
            report = run_performance_cycle(store, platforms=["tiktok"], output_dir=Path(tmp) / "performance")

        assert store.performance() == []
        assert store.feedback_summary()["platforms"] == {}
        assert report["persisted"]["items"][0]["status"] == "metrics_insufficient"


def test_tiktok_followers_only_history_is_excluded_from_strategy_feedback():
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "state.db")
        job = store.create_job("legacy tiktok weak snapshot", ["tiktok"], {"source": "test"})
        store.record_performance(job["id"], "tiktok", follows=1, extra_metrics={"works": 1})

        assert store.feedback_summary()["platforms"] == {}
        assert store.historical_performance(["tiktok"], "")["platforms"] == {}


def test_performance_cycle_metrics_feed_future_pipeline_brief():
    from content_platform.pipeline import Pipeline

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = Store(root / "state.db")
        with patch("content_platform.performance_cycle.collect_platform_metrics", return_value=FAKE_COLLECTION):
            run_performance_cycle(store, platforms=["youtube"], output_dir=root / "performance")

        pipeline = Pipeline(store, {"generator": {"allow_fallback": True}})
        job = pipeline.create("new video topic", ["youtube"], {"audience": "builders"})
        enriched = pipeline._enrich_brief(job, {})

        feedback = enriched["historical_feedback"]["platforms"]["youtube"]
        assert feedback["views"] == 11016
        assert feedback["follows"] == 8
        assert feedback["sample_count"] == 1
