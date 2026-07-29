import tempfile
import unittest
from pathlib import Path

from content_platform.asset_license import validate_asset_licenses
from content_platform.duplication import check_exact_duplicates
from content_platform.media_quality import validate_article_structure, validate_publish_readiness, validate_video_structure
from content_platform.models import ContentPackage, PublishReceipt, new_content_package_id
from content_platform.niche_scorer import AccountProfiler, TopicScorer
from content_platform.performance_collector import register_review_tasks
from content_platform.pipeline import Pipeline
from content_platform.security_gate import scan_publish_payload
from content_platform.store import Store


class RuleSystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "state.db")
        self.store.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_content_package_store_round_trip_and_review_tasks(self):
        package = ContentPackage(
            content_package_id=new_content_package_id("wechat", "acc01"),
            status="created",
            platform="wechat",
            account_id="acc01",
            content_type="article",
            topic="workflow quality",
        )
        saved = self.store.save_content_package(package)
        loaded = self.store.get_content_package(saved["content_package_id"])
        self.assertEqual(loaded["payload"]["topic"], "workflow quality")

        receipt = PublishReceipt(status="published", verification_level="platform_api", platform_content_id="wx-1")
        self.store.save_publish_receipt(package.content_package_id, "wechat", receipt)
        self.assertEqual(self.store.publish_receipts(package.content_package_id)[0]["status"], "published")

        tasks = register_review_tasks(self.store, package.content_package_id, "wechat")
        self.assertEqual([item["review_point_hours"] for item in tasks], [1, 24, 72, 168])

    def test_account_and_topic_scoring_are_deterministic(self):
        profile = AccountProfiler().profile("wechat", "acc01", {"sample_count": 0})
        self.assertEqual(profile["account_stage"], "bootstrap")
        score = TopicScorer().score_topic("AI workflow", "wechat", profile)
        self.assertIn(score["production_decision"], {"auto_produce", "manual_review", "reject"})
        self.assertEqual(score["strategy_data_status"], "bootstrap")

    def test_asset_license_gate_blocks_unknown_publish_assets(self):
        package = {
            "assets": [{"asset_id": "a1"}],
            "asset_licenses": [{"asset_id": "a1", "source_type": "stock", "source_url": "https://example.com/a.jpg", "verification_status": "pending_review"}],
        }
        result = validate_asset_licenses(package, action="publish")
        self.assertFalse(result.passed)
        self.assertEqual(result.failures[0].code, "ASSET_LICENSE_NOT_VERIFIED")

    def test_security_gate_detects_secrets_without_echoing_value(self):
        result = scan_publish_payload({"title": "safe", "body": "OPENAI_API_KEY=sk-" + "a" * 30})
        self.assertFalse(result.passed)
        self.assertIn("SECRET_OPENAI_API_KEY", [failure.code for failure in result.failures])
        self.assertNotIn("a" * 30, str(result.to_dict()))

    def test_security_gate_detects_bearer_and_jwt_tokens(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + ("a" * 24) + "." + ("b" * 24)
        result = scan_publish_payload({"body": f"Authorization: Bearer {jwt}"})
        self.assertFalse(result.passed)
        codes = [failure.code for failure in result.failures]
        self.assertIn("SECRET_BEARER_TOKEN", codes)
        self.assertIn("SECRET_JWT", codes)

    def test_article_and_video_structure_gates(self):
        article = {
            "title": "Title",
            "body_or_script": "Body",
            "visual_strategy": {"section_image_map": [{"section": "s1", "asset_id": "a1"}]},
            "seo_keywords": ["workflow"],
        }
        self.assertTrue(validate_article_structure(article, {"min_illustration_count": 1}).passed)

        video = {
            "title": "Video",
            "body_or_script": "Script",
            "storyboard": [{"asset_ids": ["clip1"], "narration": "line"}],
            "visual_strategy": {"audio_asset_id": "audio1", "subtitle_asset_id": "sub1"},
        }
        self.assertTrue(validate_video_structure(video).passed)

        unreadiness = validate_publish_readiness({"status": "published"})
        self.assertFalse(unreadiness.passed)

    def test_publish_readiness_reports_unverified_asset_license(self):
        package = {
            "content_package_id": "cp_test",
            "status": "created",
            "assets": [{"asset_id": "a1"}],
            "asset_licenses": [{"asset_id": "a1", "source_type": "stock", "source_url": "https://example.com/a.jpg", "verification_status": "unknown"}],
        }
        result = validate_publish_readiness(package, {"postcheck": "backend"})
        self.assertFalse(result.passed)
        self.assertIn("ASSET_LICENSE_NOT_VERIFIED", [failure.code for failure in result.failures])

    def test_duplication_shadow_finds_exact_title(self):
        first = ContentPackage(
            content_package_id=new_content_package_id("wechat", "acc01"),
            status="created",
            platform="wechat",
            account_id="acc01",
            content_type="article",
            topic="Same topic",
            title="Same title",
        ).to_dict()
        second = dict(first)
        second["content_package_id"] = new_content_package_id("wechat", "acc01")
        self.store.save_content_package(first)
        result = check_exact_duplicates(second, self.store)
        self.assertFalse(result.passed)
        self.assertIn("TITLE_EXACT_DUPLICATE", [failure.code for failure in result.failures])

    def test_pipeline_feature_flags_create_package_and_receipt(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(self.root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "feature_flags": {
                    "content_package_v1": True,
                    "security_gate": "enforce",
                    "asset_license_gate": "enforce_for_new_content",
                    "duplication_detector": "shadow",
                    "performance_collector": True,
                },
                "delivery_health": {"allow_unknown_health": True},
                "notifications": {"log_path": str(self.root / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        pipeline.run(job["id"])
        packages = self.store.content_packages(job_id=job["id"], platform="wechat")
        self.assertEqual(len(packages), 1)

        pipeline.approve(job["id"], "operator", "ready")
        result = pipeline.publish(job["id"])
        self.assertEqual(result["state"], "partial")
        receipts = self.store.publish_receipts(job_id=job["id"])
        self.assertEqual(receipts[0]["status"], "created")
        tasks = self.store.review_tasks()
        self.assertTrue(tasks)
        self.assertIn("status", tasks[0]["purpose"].casefold())

    def test_store_init_db_alias_initializes_content_package_tables(self):
        other = Store(self.root / "alias.db")
        other.init_db()
        package = ContentPackage(
            content_package_id=new_content_package_id("wechat", "acc01"),
            status="created",
            platform="wechat",
            account_id="acc01",
            content_type="article",
        )
        other.save_content_package(package)
        self.assertEqual(len(other.content_packages()), 1)

    def test_store_constructor_initializes_content_package_tables(self):
        other = Store(self.root / "auto_init.db")
        package = ContentPackage(
            content_package_id=new_content_package_id("wechat", "acc01"),
            status="created",
            platform="wechat",
            account_id="acc01",
            content_type="article",
        )
        other.save_content_package(package)
        self.assertEqual(len(other.content_packages()), 1)

    def test_pipeline_creates_status_review_task_for_handoff_pending(self):
        renderer = self.root / "fake_video_renderer.py"
        renderer.write_text(
            "import json, os, pathlib\n"
            "out=pathlib.Path(os.environ['VIDEO_OUTPUT_DIR']); out.mkdir(parents=True, exist_ok=True)\n"
            "video=out/'generated.mp4'; video.write_bytes(b'video')\n"
            "tools=['cinema_composition.storyboard','video_toolchain_runner.build_cards','kuaishou_render.render_cards','kuaishou_render.gen_tts','kuaishou_render.render_segments','kuaishou_render.concat_video','kuaishou_render.download_bgm','mix_bgm_with_gate.mix_bgm','kuaishou_render.gen_subtitles','kuaishou_render.encode_final','visual_gate.py --cinema']\n"
            "manifest={'ok': True, 'status': 'rendered', 'output': str(video), 'selected_pipeline': 'knowledge_card_video', 'cinema_storyboard': [{} for _ in range(8)], 'cinema_visual_gate': {'passed': True}, 'toolchain_contract': {'planned_tools': tools}}\n"
            "(out/'video_toolchain_runner_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')\n"
            "print('{}')\n",
            encoding="utf-8",
        )
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(self.root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "media": {
                    "video": {"enabled": True, "script": str(renderer)},
                    "video_toolchain": {
                        "scripts": {
                            "localized_repost_video": str(renderer),
                            "knowledge_card_video": str(renderer),
                            "mixed_note_short_video": str(renderer),
                            "tutorial_video": str(renderer),
                        }
                    },
                },
                "delivery_health": {
                    "enabled": True,
                    "platforms": {
                        "kuaishou": {
                            "state": "usable_with_postcheck_required",
                            "can_publish_now": True,
                            "reason": "test health evidence",
                        }
                    },
                },
                "feature_flags": {
                    "content_package_v1": True,
                    "security_gate": "enforce",
                    "asset_license_gate": "enforce_for_new_content",
                    "performance_collector": True,
                },
                "notifications": {"log_path": str(self.root / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Postcheck video", ["kuaishou"], {"platforms": ["kuaishou"]})
        pipeline.run(job["id"])
        pipeline.approve(job["id"], "operator", "ready")
        result = pipeline.publish(job["id"])
        self.assertEqual(result["state"], "partial")
        tasks = self.store.review_tasks()
        self.assertTrue(tasks)
        self.assertEqual(tasks[0]["review_point_hours"], 1)
        self.assertIn("status", tasks[0]["purpose"].casefold())


if __name__ == "__main__":
    unittest.main()
