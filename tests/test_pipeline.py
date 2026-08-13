import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from content_platform.models import DeliveryResult
from content_platform.pipeline import Pipeline
from content_platform.store import Store


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root / "state.db")
        self.store.init()
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "risk": {"block_words": ["blocked-word"], "review_words": ["guaranteed"]},
                "publishers": {"default": {"type": "file"}},
                "notifications": {"log_path": str(root / "notifications.jsonl")},
            },
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_end_to_end_requires_approval_and_is_idempotent(self):
        job = self.pipeline.create("Practical automation", ["wechat", "xiaohongshu"], {"audience": "operators"})
        reviewed = self.pipeline.run(job["id"])
        self.assertEqual(reviewed["state"], "review_required")

        with self.assertRaises(PermissionError):
            self.pipeline.publish(job["id"])

        self.pipeline.approve(job["id"], "operator", "content checked")
        published = self.pipeline.publish(job["id"])
        repeated = self.pipeline.publish(job["id"])
        self.assertEqual(published["state"], "partial")
        self.assertEqual(repeated["state"], "partial")
        self.assertEqual(len(self.store.deliveries(job["id"])), 2)

    def test_blocked_content_cannot_be_approved(self):
        job = self.pipeline.create("blocked-word", ["file"])
        blocked = self.pipeline.run(job["id"])
        self.assertEqual(blocked["state"], "blocked")
        with self.assertRaises(ValueError):
            self.pipeline.approve(job["id"], "operator", "")

    def test_rejection_is_terminal_for_publish(self):
        job = self.pipeline.create("Ordinary topic", ["file"])
        self.pipeline.run(job["id"])
        rejected = self.pipeline.reject(job["id"], "operator", "rewrite")
        self.assertEqual(rejected["state"], "rejected")
        with self.assertRaises(PermissionError):
            self.pipeline.publish(job["id"])

    def test_run_can_auto_stage_review_required_drafts(self):
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "delivery": {"auto_stage_review_required": True},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        reviewed = self.pipeline.run(job["id"])
        self.assertEqual(reviewed["state"], "review_required")
        deliveries = self.store.deliveries(job["id"])
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["status"], "drafted")
        queue = self.store.list_delivery_queue("completed")
        self.assertEqual(len(queue), 1)

    def test_run_persists_intelligence_records(self):
        job = self.pipeline.create(
            "Automation visuals",
            ["wechat"],
            {"platforms": ["wechat", "douyin"], "reference_posts": [{"title": "Hook", "body": "1. A\n2. B\nSave this.", "account_handle": "example_creator"}]},
        )
        self.pipeline.run(job["id"])
        self.assertTrue(self.store.source_items(job["id"]))
        self.assertTrue(self.store.account_snapshots(job["id"]))
        self.assertTrue(self.store.idea_candidates(job["id"]))
        self.assertTrue(self.store.topic_clusters(job["id"]))

    def test_publish_uses_delivery_queue(self):
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        published = self.pipeline.publish(job["id"])
        self.assertEqual(published["state"], "partial")
        self.assertTrue(self.store.list_delivery_queue("completed"))
        self.assertTrue(self.store.workflow_reports(job["id"], "wechat"))
        self.assertIn("send_completion_report", [row["step_name"] for row in self.store.workflow_steps(job["id"], "wechat")])

    def test_required_quality_gate_blocks_before_publish(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "feature_flags": {"channel_auto_workflow_gate": "enforce"},
                "wechat_toolchain": {"enabled": False},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        with patch.object(pipeline.generator, "generate", return_value={
            "title": "Title",
            "body": "Body",
            "draft_meta": {"quality_gate": {"passed": False, "failed_dimensions": ["missing_structure"]}},
        }):
            result = pipeline.run(job["id"])
        self.assertEqual(result["state"], "blocked")
        reports = self.store.workflow_reports(job["id"], "")
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["status"], "blocked")
        self.assertTrue(Path(reports[0]["report_path"]).is_file())
        steps = self.store.workflow_steps(job["id"])
        self.assertIn("run_quality_gate", [row["step_name"] for row in steps])
        self.assertEqual([row for row in steps if row["step_name"] == "run_quality_gate"][-1]["status"], "BLOCKED")
        with patch("content_platform.pipeline.build_publisher") as publisher:
            with self.assertRaises(PermissionError):
                self.pipeline.publish(job["id"])
            publisher.assert_not_called()

    def test_enforced_growth_recipe_blocks_tool_demo_without_process_evidence(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "feature_flags": {"channel_auto_workflow_gate": "enforce"},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Tool demo", ["douyin"], {"audience": "operators"})
        with patch.object(pipeline.generator, "generate", return_value={
            "title": "Tool demo",
            "body": "A concrete tool demonstration with a clear workflow and limitations.",
            "draft_meta": {
                "quality_gate": {"passed": True},
                "strategy": {"primary_platforms": ["douyin"]},
                "content_form": "tool_demo_video",
                "growth_recipe": {
                    "content_form": "tool_demo_video",
                    "source_matrix": {"attempted_sources": [{"source": "douyin", "status": "success"}]},
                    "topic_decision": {"score": 0.9, "growth_signals": ["conflict", "user_benefit"]},
                    "tool_selection_plan": {"selected_tools": ["screencast"]},
                    "process_evidence": {},
                    "cta": {},
                },
            },
        }):
            result = pipeline.run(job["id"])

        self.assertEqual(result["state"], "blocked")
        quality = [row for row in self.store.workflow_steps(job["id"]) if row["step_name"] == "run_quality_gate"][-1]
        self.assertIn("G7_growth_recipe", quality["gate"]["gates"])
        self.assertIn("process_evidence", quality["gate"]["gates"]["G7_growth_recipe"]["failures"])


    def test_pre_populated_body_preserves_full_ops_brief_fields(self):
        job = self.pipeline.create(
            "Practical automation",
            ["file"],
            {
                "strategy_brief": {"account_stage": "growth"},
                "content_workflow_inputs": {"source_inputs": ["account_analysis"]},
                "asset_mix_plan": {"real_material_retrieval": True},
                "humanization_plan": {"voice": "human editor"},
                "real_scene_backgrounds": [{"path": "/tmp/cat.jpg", "source": "stock"}],
                "knowledge_card_plan": {"count": 6},
                "growth_plan": {"goal": "completion_rate"},
            },
        )
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET body=? WHERE id=?",
                ("This is a manually prepared article body. " * 8, job["id"]),
            )

        reviewed = self.pipeline.run(job["id"])

        self.assertEqual(reviewed["state"], "review_required")
        meta = reviewed["draft_meta"]
        self.assertEqual(meta["strategy_brief"]["account_stage"], "growth")
        self.assertEqual(meta["content_workflow_inputs"]["source_inputs"], ["account_analysis"])
        self.assertTrue(meta["asset_mix_plan"]["real_material_retrieval"])
        self.assertEqual(meta["humanization_plan"]["voice"], "human editor")
        self.assertEqual(meta["knowledge_card_plan"]["count"], 6)
        self.assertEqual(meta["growth_plan"]["goal"], "completion_rate")

    def test_enforced_wechat_requires_professional_toolchain_before_quality_gate(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "feature_flags": {"channel_auto_workflow_gate": "enforce"},
                "wechat_toolchain": {
                    "wewrite_bin": str(Path(self.tmp.name) / "missing_wewrite"),
                    # The production service enables Hermes fallback. This
                    # regression specifically verifies the no-fallback block.
                    "hermes_writer_fallback": False,
                },
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        result = pipeline.run(job["id"])
        self.assertEqual(result["state"], "blocked")
        steps = self.store.workflow_steps(job["id"])
        toolchain = [row for row in steps if row["step_name"] == "prepare_wechat_professional_toolchain"][-1]
        self.assertEqual(toolchain["status"], "BLOCKED")
        self.assertEqual(toolchain["reason_code"], "wechat_toolchain_unavailable")

    def test_hermes_writer_evidence_satisfies_wechat_writer_contract(self):
        self.assertTrue(
            Pipeline._has_wechat_writer_evidence(
                {
                    "wewrite": {"status": "failed", "commands": [{"name": "llm-write", "returncode": 4}]},
                    "hermes_writer": {"status": "used", "commands": [{"name": "hermes --cli", "returncode": 0}]},
                }
            )
        )
        self.assertFalse(Pipeline._has_wechat_writer_evidence({"hermes_writer": {"status": "used", "commands": []}}))

    def test_required_image_gate_blocks_when_artifact_missing(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "media": {"image": {"enabled": True, "required": True, "min_count": 1}},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        with patch.object(pipeline.media, "generate", return_value=None):
            result = pipeline.run(job["id"])
        self.assertEqual(result["state"], "blocked")
        image_step = [row for row in self.store.workflow_steps(job["id"]) if row["step_name"] == "generate_or_collect_images"][-1]
        self.assertEqual(image_step["status"], "BLOCKED")

    def test_pipeline_records_all_generated_images_and_section_map(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "media": {"image": {"enabled": True, "required": True, "min_count": 2}},
                "notifications": {"log_path": str(Path(self.tmp.name) / "notifications.jsonl")},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        artifact_dir = Path(self.tmp.name) / "artifacts" / job["id"]
        artifact_dir.mkdir(parents=True)
        cover = artifact_dir / "cover.png"
        inline = artifact_dir / "section-01.png"
        mapping = artifact_dir / "section_image_map.json"
        cover.write_bytes(b"cover")
        inline.write_bytes(b"inline")
        mapping.write_text("[]", encoding="utf-8")
        media_artifact = {
            "kind": "image",
            "path": str(cover),
            "checksum": "cover-checksum",
            "images": [
                {"kind": "image", "path": str(cover), "checksum": "cover-checksum", "role": "cover"},
                {"kind": "image", "path": str(inline), "checksum": "inline-checksum", "role": "section"},
            ],
            "section_image_map": [{"section": "method", "image": str(inline), "purpose": "explain method"}],
        }
        with patch.object(pipeline.media, "generate", return_value=media_artifact):
            result = pipeline.run(job["id"])

        self.assertEqual(result["state"], "review_required")
        artifacts = self.store.artifacts(job["id"])
        self.assertEqual(len([item for item in artifacts if item["kind"] == "image"]), 2)
        self.assertEqual(len([item for item in artifacts if item["kind"] == "section_image_map"]), 1)

    def test_delivery_worker_processes_one_item_by_default(self):
        job = self.pipeline.create("Practical automation", ["wechat", "devto"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        for platform in job["platforms"]:
            self.store.enqueue_delivery(job["id"], platform, "publish", {"state": "approved"})
        processed = self.pipeline.process_delivery_queue()
        self.assertEqual(processed, 1)
        self.assertEqual(len(self.store.list_delivery_queue("completed")), 1)
        self.assertEqual(len(self.store.list_delivery_queue("queued")), 1)

    def test_failed_publish_attempt_is_not_recorded_as_succeeded_step(self):
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        self.store.enqueue_delivery(job["id"], "wechat", "publish", {"state": "approved"})
        with patch.object(self.pipeline, "_deliver", return_value=DeliveryResult(False, "failed", error="temporary timeout")):
            processed = self.pipeline.process_delivery_queue()
        self.assertEqual(processed, 1)
        step = [row for row in self.store.workflow_steps(job["id"], "wechat") if row["step_name"] == "publish_or_create_draft"][-1]
        self.assertEqual(step["status"], "FAILED_RETRYABLE")
        self.assertEqual(len(self.store.list_delivery_queue("queued")), 1)

    def test_handoff_delivery_is_not_recorded_as_completed_publish_work(self):
        job = self.pipeline.create("Practical automation", ["douyin"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        self.store.enqueue_delivery(job["id"], "douyin", "publish", {"state": "approved"})
        with patch.object(self.pipeline, "_deliver", return_value=DeliveryResult(True, "handoff_pending", external_id="packet-1")):
            processed = self.pipeline.process_delivery_queue()
        self.assertEqual(processed, 1)
        self.assertEqual(len(self.store.list_delivery_queue("handoff_ready")), 1)
        self.assertEqual(len(self.store.list_delivery_queue("completed")), 0)

    def test_run_skips_local_video_and_audio_generation_by_default_policy(self):
        root = Path(self.tmp.name)
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "media": {
                    "video": {"enabled": True, "script": str(root / "missing-video.py")},
                    "audio": {"enabled": True},
                },
                "publishers": {"default": {"type": "file"}},
                "notifications": {"log_path": str(root / "notifications.jsonl")},
            },
        )
        job = self.pipeline.create("Visual workflow", ["douyin"], {"platforms": ["douyin"], "keywords": ["visual"]})
        reviewed = self.pipeline.run(job["id"])

        self.assertEqual(reviewed["state"], "review_required")
        failed_media = [event for event in self.store.events(job["id"]) if event["event"] == "media_failed"]
        self.assertFalse(any('"video"' in event["detail_json"] or '"audio"' in event["detail_json"] for event in failed_media))

    def test_run_blocks_near_duplicate_topic_before_generation(self):
        original = self.pipeline.create("Automation visuals", ["wechat"], {"audience": "operators"})
        self.pipeline.run(original["id"])

        duplicate = self.pipeline.create("Automation visuals", ["wechat"], {"audience": "operators"})
        blocked = self.pipeline.run(duplicate["id"])

        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["title"], "")
        events = self.store.events(duplicate["id"])
        self.assertTrue(any(event["event"] == "content_hygiene_blocked" for event in events))

    def test_run_marks_overlap_topics_for_review_when_not_blocked(self):
        root = Path(self.tmp.name)
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "content_hygiene": {"block_threshold": 0.95, "review_threshold": 0.2},
                "publishers": {"default": {"type": "file"}},
                "notifications": {"log_path": str(root / "notifications.jsonl")},
            },
        )
        original = self.pipeline.create("Automation visuals", ["wechat"], {"audience": "operators"})
        self.pipeline.run(original["id"])

        derivative = self.pipeline.create("Automation workflow visuals", ["wechat"], {"audience": "operators"})
        reviewed = self.pipeline.run(derivative["id"])

        self.assertEqual(reviewed["state"], "review_required")
        self.assertEqual(reviewed["risk_level"], "review")
        self.assertEqual(reviewed["draft_meta"]["content_hygiene"]["status"], "review")
        self.assertTrue(reviewed["draft_meta"]["cornerstone_mode"])


if __name__ == "__main__":
    unittest.main()
