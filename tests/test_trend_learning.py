import tempfile
import unittest
from pathlib import Path

from content_platform.store import Store
from content_platform.trends import rank_trends


class TrendLearningTests(unittest.TestCase):
    def test_rank_trends_can_use_learned_context(self):
        items = [
            {"title": "AI automation workflow", "source": "github", "points": 10},
            {"title": "General lifestyle topic", "source": "other", "points": 50},
        ]
        profile = {"keywords": ["AI", "automation"], "source_weights": {"github": 1}}
        learned = {
            "preferred_clusters": [{"label": "automation", "weight": 1.2}],
            "preferred_sources": {"github": 0.5},
        }
        ranked = rank_trends(items, profile, used=set(), limit=2, learned=learned)
        self.assertEqual(ranked[0]["source"], "github")

    def test_store_can_build_learned_ranking_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.init()
            job = store.create_job("Automation visuals", ["wechat"])
            store.save_topic_clusters(job["id"], [{"cluster_key": "automation-visuals", "label": "automation", "score": 0.8, "topic_signals": ["automation"]}])
            store.record_performance(job["id"], "wechat", views=1000, likes=100, comments=10, shares=5)
            learned = store.learned_ranking_context("default")
        self.assertIn("preferred_clusters", learned)
        self.assertTrue(learned["preferred_clusters"])
