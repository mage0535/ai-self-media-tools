import unittest

from content_platform.topic_engagement import engagement_quality
from content_platform.trends import rank_trends


class TopicEngagementTests(unittest.TestCase):
    def test_interactions_per_view(self):
        item = {"metrics": {"views": 1000, "likes": 50, "favorites": 30, "comments": 20, "coins": None}}
        self.assertEqual(engagement_quality(item), 0.1)

    def test_no_counts_or_views_is_unknown(self):
        self.assertIsNone(engagement_quality({"points": 900}))
        self.assertIsNone(engagement_quality({"metrics": {"views": 1000}}))
        self.assertIsNone(engagement_quality({"metrics": {"views": 0, "likes": 5}}))
        self.assertIsNone(engagement_quality({"metrics": {"views": "n/a", "likes": 5}}))

    def test_shadow_value_does_not_change_ranking(self):
        items = [
            {"title": "AI quality inspection on the line", "source": "bilibili", "points": 900,
             "metrics": {"views": 900, "likes": 1}},
            {"title": "AI meeting notes for the office", "source": "bilibili", "points": 100,
             "metrics": {"views": 100, "likes": 40}},
        ]
        profile = {"keywords": ["AI"], "source_weights": {"bilibili": 1}}
        ranked = rank_trends(items, profile, used=set(), limit=2)
        self.assertEqual([row["points"] for row in ranked], [900, 100])
        self.assertEqual([row["engagement_quality"] for row in ranked], [0.0011, 0.4])


if __name__ == "__main__":
    unittest.main()
