import unittest
from pathlib import Path
from content_platform.video_dedup_transform import build_dedup_filter_graph


class TestVideoDedupTransform(unittest.TestCase):
    def test_filter_graph_contains_all_high_order_elements(self):
        filter_str, record = build_dedup_filter_graph(
            hflip=True,
            zoom_ratio=1.04,
            contrast=1.025,
            brightness=0.015,
            saturation=1.035,
            inject_noise=True,
            noise_strength=4,
            speed_factor=0.98,
            target_fps=30,
        )
        self.assertIn("hflip", filter_str)
        self.assertIn("scale=1.0400*iw:1.0400*ih", filter_str)
        self.assertIn("crop=iw:ih", filter_str)
        self.assertIn("eq=contrast=1.025:brightness=0.015:saturation=1.035", filter_str)
        self.assertIn("noise=c1s=4:c0f=u", filter_str)
        self.assertIn("setpts=", filter_str)
        self.assertIn("fps=30", filter_str)

        self.assertTrue(record["hflip"])
        self.assertEqual(record["zoom_ratio"], 1.04)
        self.assertTrue(record["inject_noise"])


if __name__ == "__main__":
    unittest.main()
