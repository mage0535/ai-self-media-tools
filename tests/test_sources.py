import unittest

from content_platform.sources import infer_platform, normalize_source_items


class SourcePlatformTests(unittest.TestCase):
    def test_infer_platform_recognizes_shipinhao_sources(self):
        self.assertEqual(infer_platform("https://channels.weixin.qq.com/post/123"), "shipinhao")
        self.assertEqual(infer_platform("shipinhao same-lane sample"), "shipinhao")

    def test_normalize_source_items_keeps_shipinhao_platform(self):
        items = normalize_source_items(
            "Video channel topic",
            {},
            [{"title": "Hook", "url": "https://channels.weixin.qq.com/post/123"}],
        )

        self.assertEqual(items[0]["platform"], "shipinhao")


if __name__ == "__main__":
    unittest.main()
