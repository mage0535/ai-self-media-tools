import json
import tempfile
import unittest
from pathlib import Path

from content_platform.performance_ingest import import_performance_file, review_performance
from content_platform.store import Store


class PerformanceIngestTests(unittest.TestCase):
    def test_imports_jsonl_metrics_and_reports_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "state.db")
            job = store.create_job("short video", ["kuaishou"])
            source = root / "metrics.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "job_id": job["id"],
                        "platform": "kuaishou",
                        "views": 100,
                        "likes": 3,
                        "comments": 1,
                        "shares": 0,
                        "saves": 2,
                        "follows": 0,
                        "completion_rate": 0.18,
                        "three_second_view_rate": 0.31,
                        "avg_watch_seconds": 11.5,
                        "metrics": {"comment_rate": 0.01},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = import_performance_file(store, source)
            review = review_performance(store)

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(review["platforms"]["kuaishou"]["sample_count"], 1)
        self.assertIn("low_completion_rate", review["platforms"]["kuaishou"]["findings"])
        self.assertIn("low_follow_conversion", review["platforms"]["kuaishou"]["findings"])
        self.assertEqual(review["platforms"]["kuaishou"]["confidence"], "low")

    def test_import_rejects_unknown_jobs_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "state.db")
            source = root / "metrics.json"
            source.write_text(json.dumps([{"job_id": "missing", "platform": "wechat", "views": 1}]), encoding="utf-8")

            result = import_performance_file(store, source)

        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertIn("job not found", result["errors"][0]["error"])

    def test_import_allow_unknown_job_creates_snapshot_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "state.db")
            source = root / "metrics.json"
            source.write_text(
                json.dumps(
                    [
                        {
                            "job_id": "wechat-backend-snapshot",
                            "platform": "wechat",
                            "follows": 8,
                            "metrics": {"total_followers": 43},
                        }
                    ]
                ),
                encoding="utf-8",
            )

            result = import_performance_file(store, source, allow_unknown_job=True)
            performance = store.performance()

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(performance[0]["platform"], "wechat")
        self.assertEqual(performance[0]["follows"], 8)
        self.assertEqual(performance[0]["extra_metrics"]["total_followers"], 43)

    def test_review_marks_expected_platforms_without_metrics_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")

            review = review_performance(store, expected_platforms=["wechat", "kuaishou"])

        self.assertEqual(review["platforms"]["wechat"]["confidence"], "none")
        self.assertIn("metrics_missing", review["platforms"]["wechat"]["findings"])
        self.assertIn("collect_platform_backend_metrics", review["platforms"]["wechat"]["recommended_focus"])

    def test_import_resolves_job_by_platform_and_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "state.db")
            job = store.create_job("AI agent incident", ["shipinhao"])
            store.save_draft(job["id"], "AI 写代码翻车实录", "body", "low", {})
            source = root / "metrics.csv"
            source.write_text(
                "platform,title,views,likes,comments,shares,saves,follows,completion_rate\n"
                "shipinhao,AI 写代码翻车实录,200,10,3,2,8,1,0.42\n",
                encoding="utf-8",
            )

            result = import_performance_file(store, source)
            performance = store.performance(job["id"])

        self.assertEqual(result["imported"], 1)
        self.assertEqual(performance[0]["platform"], "shipinhao")
        self.assertEqual(performance[0]["views"], 200)

    def test_csv_extra_numeric_columns_are_imported_as_platform_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "state.db")
            job = store.create_job("Bilibili guide", ["bilibili"])
            source = root / "metrics.csv"
            source.write_text(
                "job_id,platform,views,likes,coin_rate,danmaku_rate,operator_note\n"
                f"{job['id']},bilibili,300,12,0.08,0.03,checked manually\n",
                encoding="utf-8",
            )

            result = import_performance_file(store, source)
            performance = store.performance(job["id"])

        self.assertEqual(result["imported"], 1)
        self.assertEqual(performance[0]["extra_metrics"]["coin_rate"], 0.08)
        self.assertEqual(performance[0]["extra_metrics"]["danmaku_rate"], 0.03)
        self.assertNotIn("operator_note", performance[0]["extra_metrics"])

    def test_platform_export_aliases_are_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "state.db")
            job = store.create_job("Kuaishou export", ["kuaishou"])
            source = root / "kuaishou.csv"
            source.write_text(
                "job_id,platform,play_count,like_count,comment_count,share_count,collect_count,new_follows,finish_rate,3s_rate,avg_play_seconds\n"
                f"{job['id']},KWAI,1000,30,6,5,40,2,0.46,0.58,21.7\n",
                encoding="utf-8",
            )

            result = import_performance_file(store, source)
            performance = store.performance(job["id"])

        self.assertEqual(result["imported"], 1)
        self.assertEqual(performance[0]["platform"], "kuaishou")
        self.assertEqual(performance[0]["views"], 1000)
        self.assertEqual(performance[0]["saves"], 40)
        self.assertEqual(performance[0]["follows"], 2)
        self.assertEqual(performance[0]["completion_rate"], 0.46)
        self.assertEqual(performance[0]["three_second_view_rate"], 0.58)
        self.assertEqual(performance[0]["avg_watch_seconds"], 21.7)


if __name__ == "__main__":
    unittest.main()
