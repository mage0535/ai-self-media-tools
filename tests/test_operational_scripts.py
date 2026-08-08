import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class OperationalScriptTests(unittest.TestCase):
    def test_bgm_uniqueness_fails_closed_without_source_or_fingerprint(self):
        from scripts.check_bgm_uniqueness import check

        with tempfile.TemporaryDirectory() as tmp:
            result = check(Path(tmp), platform="kuaishou", registry_path=Path(tmp) / "registry.json")

        self.assertFalse(result["passed"])
        self.assertIn("bgm_source_json_missing", result["failed_dimensions"])
        self.assertIn("bgm_fingerprint_missing", result["failed_dimensions"])

    def test_bgm_uniqueness_rejects_duplicate_and_registers_new_track(self):
        from scripts.check_bgm_uniqueness import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bgm = root / "bgm.mp3"
            bgm.write_bytes(b"a" * 80_000)
            source = {"sha256": "fp1", "title": "Acoustic", "source_url": "https://example.test/a.mp3", "license": "cc-by"}
            (root / "bgm_source.json").write_text(json.dumps(source), encoding="utf-8")
            registry = root / "registry.json"
            with patch("scripts.check_bgm_uniqueness._mean_volume", return_value=-18.0):
                first = check(root, platform="kuaishou", registry_path=registry)
                second = check(root, platform="kuaishou", registry_path=registry)

        self.assertTrue(first["passed"])
        self.assertFalse(second["passed"])
        self.assertIn("bgm_fingerprint_duplicate", second["failed_dimensions"])

    def test_media_delivery_requires_configured_target(self):
        from scripts.deliver_media import deliver

        with patch.dict(os.environ, {}, clear=True):
            result = deliver("video", ["missing.mp4"])

        self.assertFalse(result["passed"])
        self.assertEqual(result["error"], "HERMES_DELIVERY_TARGET_missing")

    def test_topic_independence_requires_source_matrix(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "platform_source_matrix_20260807.json").write_text(
                json.dumps(
                    {
                        "selected_topic": "独立选题",
                        "platform_source_matrix": {
                            "attempted_sources": ["a", "b", "c", "d", "e"],
                            "successful_sources": ["a", "b", "c"],
                            "platform_internal_verified": True,
                            "shared_trend_only": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ok = check("20260807", ["wechat"], root=root)
            bad = check("20260807", ["kuaishou"], root=root)

        self.assertTrue(ok["passed"])
        self.assertFalse(bad["passed"])
        self.assertEqual(bad["failures"][0]["failed_dimensions"][0], "analysis_file_missing")

    def test_topic_independence_accepts_markdown_source_matrix(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "analysis_20260809.md").write_text(
                """
# WeChat analysis

选题方向：AI 自动化效率幻觉实测复盘

| 来源 | 状态 | 关键发现 |
| --- | --- | --- |
| 搜狗微信（平台内） | ✅ 成功 | 公众号同赛道活跃 |
| 微博 | ✅ 成功 | AI 降本讨论升温 |
| 抖音 | ✅ 成功 | AI 工具短视频高频 |
| 知乎 | ✅ 成功 | 工具实测和血泪教训 |
| B站 | ✅ 成功 | AI 自动化教程活跃 |
| GitHub | ✅ 成功 | automation 项目上升 |
| 小红书 | ❌ login_required | 记录失败原因 |

shared_trend_only: false
""",
                encoding="utf-8",
            )
            result = check("20260809", ["wechat"], root=root)

        self.assertTrue(result["passed"], result)
        matrix = result["records"]["wechat"]["matrix"]
        self.assertGreaterEqual(matrix["attempted_count"], 5)
        self.assertGreaterEqual(matrix["successful_count"], 3)
        self.assertTrue(matrix["platform_internal_evidence"])
        self.assertEqual(result["records"]["wechat"]["selected_topic"], "AI 自动化效率幻觉实测复盘")

    def test_topic_independence_accepts_markdown_source_matrix_without_emoji_status(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "analysis_20260809.md").write_text(
                """
# 公众号运营分析

内容主题：AI 自动化效率幻觉实测复盘

| 来源 | 状态 | 关键发现 |
| --- | --- | --- |
| wechat internal | success | 公众号同赛道活跃 |
| weibo | success | AI 降本讨论升温 |
| douyin | success | AI 工具短视频高频 |
| zhihu | success | 工具实测和血泪教训 |
| bilibili | success | AI 自动化教程活跃 |
| github | success | automation 项目上升 |
| xiaohongshu | login_required | 记录失败原因 |

shared_trend_only: false
""",
                encoding="utf-8",
            )
            result = check("20260809", ["wechat"], root=root)

        self.assertTrue(result["passed"], result)
        matrix = result["records"]["wechat"]["matrix"]
        self.assertEqual(matrix["attempted_count"], 7)
        self.assertEqual(matrix["successful_count"], 6)
        self.assertTrue(matrix["platform_internal_evidence"])

    def test_public_scripts_do_not_embed_private_runtime_paths_or_targets(self):
        checked = [
            "scripts/build_kuaishou_packet.py",
            "scripts/check_bgm_uniqueness.py",
            "scripts/check_platform_topic_independence.py",
            "scripts/deliver_media.py",
            "scripts/normalize_kuaishou_render_dir.py",
            "scripts/render_landscape_video.py",
        ]
        for rel in checked:
            text = Path(rel).read_text(encoding="utf-8")
            self.assertNotIn("/roo" + "t/", text, rel)
            self.assertNotIn("5975" + "133381", text, rel)


if __name__ == "__main__":
    unittest.main()
