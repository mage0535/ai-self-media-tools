import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from content_platform.models import DeliveryResult
from content_platform.pipeline import Pipeline
from content_platform.store import Store
from content_platform.seo import geo_check


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

    def test_renderer_tool_invocation_manifest_is_promoted_to_draft_metadata(self):
        manifest = {
            "planned_tools": {"video_toolchain_runner": "renderer"},
            "invocations": {"video_toolchain_runner": {"status": "ok", "output": "final.mp4"}},
        }
        draft = {"draft_meta": {}}
        Pipeline._attach_video_render_evidence(
            draft,
            {"render_manifest": {"tool_invocation_manifest": manifest}, "render_packet": {}},
        )
        self.assertEqual(draft["draft_meta"]["renderer_tool_invocation_manifest"], manifest)
        self.assertNotIn("tool_invocation_manifest", draft["draft_meta"])

    def test_renderer_sidecars_are_promoted_to_final_media_contract(self):
        artifact_dir = self.pipeline.data_dir / "artifacts" / "sidecars"
        artifact_dir.mkdir(parents=True)
        final = artifact_dir / "final.mp4"
        final.write_bytes(b"video")
        (artifact_dir / "scene_manifest.json").write_text(json.dumps({"version": "scene_manifest_v2"}), encoding="utf-8")
        (artifact_dir / "bgm_source.json").write_text(json.dumps({"source_url": "https://example.test/bgm", "sha256": "abc"}), encoding="utf-8")
        (artifact_dir / "tts_fingerprint.json").write_text(json.dumps({"provider": "edge-tts", "sha256": "voice"}), encoding="utf-8")
        (artifact_dir / "subtitle_burn_evidence.json").write_text(json.dumps({"passed": True, "sample_count": 8}), encoding="utf-8")
        (artifact_dir / "scene_execution_evidence.json").write_text(json.dumps({"scenes": [{"scene_id": "s01", "frame_difference": 0.02, "static_ratio": 0.2, "renderer_modes": ["playwright-video"], "fallback": False}]}), encoding="utf-8")
        draft = {"draft_meta": {}}

        Pipeline._attach_video_render_evidence(draft, {"path": str(final), "checksum": "hash", "render_manifest": {"status": "rendered"}})

        meta = draft["draft_meta"]
        self.assertEqual(meta["scene_manifest"]["version"], "scene_manifest_v2")
        self.assertEqual(meta["bgm_source"]["sha256"], "abc")
        self.assertEqual(meta["tts_fingerprint"]["provider"], "edge-tts")
        self.assertTrue(meta["subtitle_evidence"]["passed"])
        self.assertEqual(meta["observed_scene_evidence"]["s01"]["frame_difference"], 0.02)
        self.assertEqual(meta["scene_execution_evidence"]["scenes"][0]["scene_id"], "s01")

    def test_video_generation_registers_renderer_verified_cover_artifact(self):
        self.pipeline.config.setdefault("media", {})["video"] = {"enabled": True}
        job = self.pipeline.create("Video cover", ["kuaishou"], {})
        artifact_dir = self.pipeline.data_dir / "artifacts" / job["id"]
        artifact_dir.mkdir(parents=True)
        video = artifact_dir / "final.mp4"
        cover = artifact_dir / "cover_1080x1440.jpg"
        video.write_bytes(b"video")
        cover.write_bytes(b"cover")
        artifact = {
            "kind": "video",
            "path": str(video),
            "checksum": __import__("hashlib").sha256(video.read_bytes()).hexdigest(),
            "render_manifest": {
                "ok": True,
                "status": "rendered",
                "cover": str(cover),
                "cover_quality_evidence": {"passed": True},
                "cover_quality_gate": {"passed": True},
            },
        }
        runner = Mock()
        runner.run.side_effect = lambda _step, func, **_kwargs: func()

        with patch.object(self.pipeline.media, "generate", return_value=artifact):
            self.pipeline._generate_optional_media(job["id"], "video", runner, [])

        stored = self.store.artifacts(job["id"])
        assert {row["kind"] for row in stored} == {"video", "cover"}
        saved_cover = next(row for row in stored if row["kind"] == "cover")
        assert saved_cover["checksum"] == __import__("hashlib").sha256(cover.read_bytes()).hexdigest()

    def test_each_job_overwrites_generator_checkpoint_dir(self):
        first = self.pipeline.create("First topic", ["wechat"], {"audience": "operators"})
        second = self.pipeline.create("Second topic", ["wechat"], {"audience": "operators"})
        for job in (first, second):
            with self.store.connect() as conn:
                conn.execute("UPDATE jobs SET body=? WHERE id=?", ("Prepared body " * 20, job["id"]))
            self.pipeline.run(job["id"])
            assert self.pipeline.generator.config["checkpoint_dir"] == str(self.pipeline.data_dir / "jobs" / job["id"])
            assert self.pipeline.generator.config["session_id"] == f"content-job:{job['id']}"

    def test_blocked_generation_gate_persists_capability_evidence(self):
        job = self.pipeline.create("Persist blocked evidence", ["juejin"], {"audience": "developers"})
        with self.store.connect() as conn:
            conn.execute("UPDATE jobs SET body=? WHERE id=?", ("Concrete workflow evidence. " * 20, job["id"]))
        self.pipeline.require_gate_pass = True

        with patch.object(self.pipeline, "_quality_gate", return_value={"passed": False, "gates": {"forced": {"passed": False}}}):
            result = self.pipeline.run(job["id"])

        persisted = self.store.get_job(job["id"])
        self.assertEqual(result["state"], "blocked")
        self.assertIn("capability_execution", persisted["draft_meta"])
        self.assertIn("tool_invocation_manifest", persisted["draft_meta"])

    def test_rendered_gate_recovers_manifest_after_later_optional_media_failure(self):
        import json

        job_id = "render-recovery"
        artifact_dir = self.pipeline.data_dir / "artifacts" / job_id
        artifact_dir.mkdir(parents=True)
        output = artifact_dir / "final.mp4"
        output.write_bytes(b"video")
        manifest = {
            "status": "rendered",
            "ok": True,
            "output": str(output),
            "tool_invocation_manifest": {
                "planned_tools": {"video_toolchain_runner": "renderer"},
                "invocations": {"video_toolchain_runner": {"status": "ok"}},
            },
        }
        (artifact_dir / "video_toolchain_runner_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        draft = {"draft_meta": {}}

        self.pipeline._recover_video_render_evidence(job_id, draft)

        self.assertEqual(draft["draft_meta"]["render_manifest"]["status"], "rendered")
        self.assertEqual(
            draft["draft_meta"]["renderer_tool_invocation_manifest"]["invocations"]["video_toolchain_runner"]["status"],
            "ok",
        )

    def test_rendered_gate_reads_renderer_sidecar_measurements(self):
        import json
        from unittest.mock import patch

        root = self.pipeline.data_dir / "artifacts" / "sidecar-render"
        (root / "backgrounds").mkdir(parents=True)
        output = root / "final.mp4"
        output.write_bytes(b"video")
        for index in range(4):
            (root / "backgrounds" / f"bg_{index:02d}.png").write_bytes(b"image")
        (root / "bgm_source.json").write_text(json.dumps({
            "source": "licensed_local_library", "source_url": "https://example.test/license",
            "license": "CC BY", "fit_reason": "matched", "fallback_used": False,
        }), encoding="utf-8")
        (root / "narration.srt").write_text("\n".join(f"{i}\n00:00:00,000 --> 00:00:01,000\ntext" for i in range(1, 9)), encoding="utf-8")
        required = {
            "cinema_composition.storyboard", "shotcraft_moves.shot_plan_for_text",
            "kuaishou_render.render_cards", "kuaishou_render.download_bgm",
            "kuaishou_render.gen_subtitles", "kuaishou_render.encode_final",
        }
        manifest = {
            "ok": True, "status": "rendered", "output": str(output),
            "toolchain_contract": {"planned_tools": sorted(required)},
            "motion_evidence": {"passed": True, "unique_frame_count": 4},
            "segment_motion_evidence": {"segments": [{"move_id": "m1", "profile": "p1"}] * 3},
        }
        packet = {
            "video_toolchain_plan": {"required": True, "platforms": ["kuaishou"]},
            "video_artifact": {"path": str(output)},
            "render_manifest": manifest,
        }
        probe = type("Result", (), {"stdout": json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "45"}})})()
        with patch("content_platform.pipeline.subprocess.run", return_value=probe):
            result = Pipeline._rendered_video_platform_gate(packet, "kuaishou")

        assert result["passed"] is True

    def test_rendered_gate_reprobes_incomplete_audio_and_counts_jpg_backgrounds(self):
        root = self.pipeline.data_dir / "artifacts" / "jpg-sidecars"
        (root / "backgrounds").mkdir(parents=True)
        output = root / "final.mp4"
        output.write_bytes(b"video")
        for index in range(4):
            (root / "backgrounds" / f"bg_{index:02d}.jpg").write_bytes(b"image")
        (root / "narration.srt").write_text("\n".join(f"{i}\n00:00:00,000 --> 00:00:01,000\ntext" for i in range(1, 9)), encoding="utf-8")
        required = {
            "cinema_composition.storyboard", "shotcraft_moves.shot_plan_for_text",
            "kuaishou_render.render_cards", "kuaishou_render.download_bgm",
            "kuaishou_render.gen_subtitles", "kuaishou_render.encode_final",
        }
        packet = {
            "video_toolchain_plan": {"required": True, "platforms": ["kuaishou"]},
            "video_artifact": {"path": str(output)},
            "render_manifest": {
                "ok": True, "status": "rendered", "output": str(output),
                "toolchain_contract": {"planned_tools": sorted(required)},
                "motion_evidence": {"passed": True, "unique_frame_count": 4},
                "segment_motion_evidence": {"segments": [{"move_id": "m", "profile": "p"}] * 3},
            },
            "audio_probe": {"sample_rate": 44100, "channels": 2},
            "bgm_source": {"source": "openverse_audio", "source_url": "https://example.test/bgm", "license": "CC BY", "fit_reason": "matched"},
        }
        probe = type("Result", (), {"stdout": json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "45"}})})()
        with patch("content_platform.pipeline.subprocess.run", return_value=probe):
            result = Pipeline._rendered_video_platform_gate(packet, "kuaishou")

        assert result["gates"]["audio_stream"]["passed"] is True
        assert result["gates"]["visual_backgrounds"]["passed"] is True

    def test_rendered_gate_accepts_measured_burned_subtitle_evidence(self):
        root = self.pipeline.data_dir / "artifacts" / "burned-subtitle"
        (root / "backgrounds").mkdir(parents=True)
        video = root / "final.mp4"
        video.write_bytes(b"video")
        for index in range(4):
            (root / "backgrounds" / f"bg_{index}.jpg").write_bytes(b"image")
        packet = {
            "video_toolchain_plan": {"required": True, "platforms": ["kuaishou"]},
            "video_artifact": {"path": str(video)},
            "render_manifest": {
                "ok": True, "status": "rendered", "output": str(video),
                "toolchain_contract": {"planned_tools": ["cinema_composition.storyboard", "shotcraft_moves.shot_plan_for_text", "kuaishou_render.render_cards", "kuaishou_render.download_bgm", "kuaishou_render.gen_subtitles", "kuaishou_render.encode_final"]},
                "motion_evidence": {"passed": True, "unique_frame_count": 4},
                "segment_motion_evidence": {"segments": [{"move_id": "m", "profile": "p"}] * 3},
            },
            "subtitle_evidence": {"burned_in": True, "sample_count": 8, "position": "lower_third", "font_size": 46, "max_chars_per_line": 18, "max_lines": 2, "margin_v": 290},
            "bgm_source": {"source": "openverse_audio", "source_url": "https://example.test/bgm", "license": "CC BY", "fit_reason": "matched"},
        }
        probe = type("Result", (), {"stdout": json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "45"}})})()
        with patch("content_platform.pipeline.subprocess.run", return_value=probe):
            result = Pipeline._rendered_video_platform_gate(packet, "kuaishou")

        assert result["gates"]["subtitle_safety"]["passed"] is True

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

    def test_compiled_pipeline_preserves_quality_reference_in_provider_brief(self):
        """A compiled strategy must not discard the executable quality rules."""
        from content_platform.content_quality_reference import load_content_quality_reference_pack

        reference = load_content_quality_reference_pack("wechat", content_form="long_article")
        context = {
            "strategy": {"compiled": {"version": "compiled_strategy_v1", "content_pillars": ["practical"]}},
            "content_quality_reference_pack": reference,
        }
        captured = {}
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})

        def generate(topic, brief):
            captured["brief"] = brief
            return {
                "title": topic,
                "body": "A concrete, evidence-backed workflow with a reusable checklist.",
                "draft_meta": {"quality_gate": {"passed": True}, "strategy": {}},
            }

        with patch("content_platform.pipeline.load_platform_workflow_context", return_value=context):
            with patch.object(self.pipeline.generator, "generate", side_effect=generate):
                self.pipeline.run(job["id"])

        bounded = captured["brief"]["bounded_model_input"]
        self.assertTrue(bounded["content_quality_reference_pack"]["loaded"])
        self.assertEqual(bounded["content_quality_reference_pack"]["sha256"], reference["sha256"])

    def test_pipeline_persists_topic_decision_and_sends_it_to_provider(self):
        captured = {}
        candidate = {
            "platform": "wechat",
            "title": "AI工作流三步实测",
            "evidence_type": "same_lane_hot_work",
            "identity_role": "target_platform",
            "url": "https://mp.weixin.qq.com/s/example",
            "captured_at": "2026-09-10T08:00:00+00:00",
            "collector": "wechat_article_collector",
            "views": 1200,
            "lane_fit_score": 0.9,
            "content_value_score": 0.8,
            "saturation_score": 0.2,
        }
        job = self.pipeline.create(
            candidate["title"],
            ["wechat"],
            {"topic_candidates": [candidate], "topic_keywords": ["AI", "工作流"]},
        )

        def generate(topic, brief):
            captured["brief"] = brief
            return {
                "title": topic,
                "body": "A concrete, evidence-backed workflow with a reusable checklist.",
                "draft_meta": {"quality_gate": {"passed": True}, "strategy": {}},
            }

        with patch.object(self.pipeline.generator, "generate", side_effect=generate):
            self.pipeline.run(job["id"])

        saved = self.store.get_job(job["id"])
        self.assertEqual(saved["brief"]["topic_decision"]["version"], "topic_decision_v1")
        self.assertEqual(
            captured["brief"]["bounded_model_input"]["topic_decision"]["selected"]["title"],
            candidate["title"],
        )

    def test_publish_uses_delivery_queue(self):
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})
        self.pipeline.run(job["id"])
        self.pipeline.approve(job["id"], "operator", "ready")
        published = self.pipeline.publish(job["id"])
        self.assertEqual(published["state"], "partial")
        self.assertTrue(self.store.list_delivery_queue("completed"))
        self.assertTrue(self.store.workflow_reports(job["id"], "wechat"))
        self.assertIn("send_completion_report", [row["step_name"] for row in self.store.workflow_steps(job["id"], "wechat")])

    def test_generation_input_includes_latest_same_lane_playbook(self):
        report_path = Path(self.tmp.name) / "same_lane.json"
        report_path.write_text(
            json.dumps(
                {
                    "reports": {
                        "wechat": {
                            "platform": "wechat",
                            "own_data_status": "insufficient",
                            "topic_patterns": ["tool_workflow_tutorial"],
                            "proof_requirements": ["screen_or_tool_stack_demo"],
                            "recommended_content_moves": ["show a concrete tool stack"],
                            "top_accounts": [{"account": "Sample", "total_views": 100}],
                            "top_works": [{"title": "AI 工作流案例", "account": "Sample", "views": 100}],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.store.save_tool_inventory("same_lane_intelligence:latest", {"report_path": str(report_path), "platforms": ["wechat"]})
        captured = {}
        job = self.pipeline.create("Practical automation", ["wechat"], {"audience": "operators"})

        def generate(topic, brief):
            captured["brief"] = brief
            return {
                "title": topic,
                "body": "A concrete, evidence-backed workflow with a reusable checklist.",
                "draft_meta": {"quality_gate": {"passed": True}, "strategy": {}},
            }

        with patch.object(self.pipeline.generator, "generate", side_effect=generate):
            self.pipeline.run(job["id"])

        same_lane = captured["brief"]["bounded_model_input"]["same_lane_intelligence"]
        self.assertEqual(same_lane["own_data_status"], "insufficient")
        self.assertEqual(same_lane["topic_patterns"], ["tool_workflow_tutorial"])
        self.assertIn("show a concrete tool stack", same_lane["recommended_content_moves"])

    def test_required_unified_acceptance_blocks_publish(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "workflow": {"require_unified_acceptance": True},
            },
        )
        job = pipeline.create("Practical automation", ["wechat"])
        pipeline.run(job["id"])
        pipeline.approve(job["id"], "operator", "ready")
        self.store.save_workflow_acceptance(job["id"], {"passed": False, "failures": ["long_form_cta_missing"]})

        with self.assertRaises(PermissionError):
            pipeline.publish(job["id"])

    def test_compiled_run_cannot_publish_without_passing_acceptance(self):
        from content_platform.run_contract import build_run_contract

        job = self.pipeline.create("Compiled work", ["wechat"], {"run_contract": build_run_contract("wechat")})
        self.store.transition(job["id"], {"created"}, "approved", "test_approved")
        with self.assertRaises(PermissionError, msg="compiled scheduled work must always fail closed"):
            self.pipeline.publish(job["id"])

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

    def test_unsourced_operational_claim_blocks_before_media_generation(self):
        from content_platform.run_contract import build_run_contract

        job = self.pipeline.create("Provider fallback", ["juejin"], {"audience": "developers", "run_contract": build_run_contract("juejin")})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Provider fallback",
            "body": "我实测运行了 8 个月，成功率达到 99%。",
            "draft_meta": {"claim_ledger": []},
        }), patch.object(self.pipeline.media, "generate") as media:
            result = self.pipeline.run(job["id"])

        self.assertEqual(result["state"], "blocked")
        steps = self.store.workflow_steps(job["id"])
        claim_step = [row for row in steps if row["step_name"] == "validate_factual_claims"][-1]
        self.assertEqual(claim_step["status"], "BLOCKED")
        media.assert_not_called()

    def test_automated_workflow_blocks_unsourced_numeric_claim_without_run_contract(self):
        job = self.pipeline.create(
            "Automated video",
            ["kuaishou"],
            {"automated_workflow": True, "selection_mode": "official_native_canary"},
        )
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Automated video",
            "body": "三分钟通过审核，一个月省下两万元。" * 12,
            "draft_meta": {"claim_ledger": []},
        }), patch.object(self.pipeline.media, "generate") as media:
            result = self.pipeline.run(job["id"])

        self.assertEqual(result["state"], "blocked")
        claim_step = [row for row in self.store.workflow_steps(job["id"]) if row["step_name"] == "validate_factual_claims"][-1]
        self.assertEqual(claim_step["status"], "BLOCKED")
        media.assert_not_called()

    def test_automated_workflow_removes_unsourced_external_attribution_before_media(self):
        safe_body = (
            "## 明确目标\n先把任务目标写清楚，再拆出输入、步骤和验收标准。"
            "每一步只保留能够核对的来源和结果，失败时返回当前步骤修正。"
            "\n\n## 核对来源\nClaude Code 的官方插件市场直接集成了 Skills。"
            "接着核对每个步骤的输入契约、输出契约和失败恢复条件。"
            "\n\n## 验收结果\n最后检查正文、配图和交付回执是否对应同一个主题，并保存可复查的证据。"
        )
        job = self.pipeline.create("操作手册", ["juejin"], {"automated_workflow": True})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "操作手册",
            "body": safe_body,
            "draft_meta": {"claim_ledger": [], "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        self.assertNotIn("官方插件市场", current["body"])
        self.assertTrue(current["draft_meta"]["claim_sanitization"]["passed"])
        claim_step = [
            row for row in self.store.workflow_steps(job["id"])
            if row["step_name"] == "validate_factual_claims"
        ][-1]
        self.assertEqual(claim_step["status"], "SUCCEEDED")

    def test_pipeline_repairs_split_technical_filename_before_claim_and_media_steps(self):
        job = self.pipeline.create("操作手册", ["juejin"], {})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "操作手册",
            "body": "先创建 SKILL.\nmd，再逐项检查输入、输出和验收结果。" * 5,
            "draft_meta": {"claim_ledger": [], "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        self.assertIn("SKILL.md", current["body"])
        self.assertNotIn("SKILL.\nmd", current["body"])

    def test_automated_workflow_blocks_unrepairable_prose_hygiene_before_media(self):
        paragraph = "先确认输入来源，再检查输出契约，最后保存能够复查的证据。"
        job = self.pipeline.create("操作手册", ["juejin"], {"automated_workflow": True})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "操作手册",
            "body": f"{paragraph}\n\n{paragraph}\n\n最后核对交付结果。",
            "draft_meta": {"claim_ledger": [], "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate") as media:
            result = self.pipeline.run(job["id"])

        self.assertEqual(result["state"], "blocked")
        step = [
            row for row in self.store.workflow_steps(job["id"])
            if row["step_name"] == "validate_factual_claims"
        ][-1]
        self.assertEqual(step["reason_code"], "generated_text_hygiene_failed")
        media.assert_not_called()
        persisted = self.store.get_job(job["id"])
        self.assertEqual(persisted["body"], f"{paragraph}\n\n{paragraph}\n\n最后核对交付结果。")
        self.assertTrue(
            {"repeated_paragraph", "repeated_sentence"}.intersection(
                persisted["draft_meta"]["generated_text_hygiene"]["reasons"]
            )
        )

    def test_automated_article_requires_three_readable_h2_sections_before_media(self):
        body = (
            "## 问题\n先确认输入来源，再检查输出契约，最后保存能够复查的证据。\n\n"
            "## 方法\n把任务拆成收集、生成和验收，并为每一步记录失败原因。"
        )
        job = self.pipeline.create(
            "操作手册", ["juejin"], {"automated_workflow": True, "content_form": "article"}
        )
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "操作手册", "body": body,
            "draft_meta": {"claim_ledger": [], "content_form": "article", "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate") as media:
            result = self.pipeline.run(job["id"])

        self.assertEqual(result["state"], "blocked")
        step = [
            row for row in self.store.workflow_steps(job["id"])
            if row["step_name"] == "validate_factual_claims"
        ][-1]
        self.assertEqual(step["reason_code"], "generated_article_structure_failed")
        media.assert_not_called()

    def test_article_appends_verified_sources_before_geo_and_quality_gate(self):
        body = (
            "## 核心结论\n先解释目录约定。\n\n"
            "## 文件结构\n再说明入口文件。\n\n"
            "## 执行检查\n最后核对输出。"
        )
        source = {
            "claim": "Agent Skill 是一个目录。",
            "source_url": "https://agentskills.io/specification",
            "evidence_path": "sources/specification.md",
            "provenance_hash": "a" * 64,
            "verified": True,
        }
        job = self.pipeline.create(
            "Agent Skills", ["juejin"], {"content_form": "article", "claim_ledger": [source]}
        )
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Agent Skills", "body": body,
            "draft_meta": {"claim_ledger": [source], "content_form": "article", "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        self.assertIn("## 参考来源", current["body"])
        self.assertIn("https://agentskills.io/specification", current["body"])
        self.assertTrue(current["draft_meta"]["geo_details"]["checks"]["claims_with_sources"])
        self.assertTrue(current["draft_meta"]["geo_details"]["checks"]["structured_list"])

    def test_claim_sanitization_recompiles_cover_from_clean_copy(self):
        body = (
            "## 明确场景\n先明确工作场景，再拆解输入、步骤、输出和失败恢复条件。"
            "每一步都要保存能够复查的来源与结果，完成后检查正文和图片是否一致。"
            "\n\n## 执行步骤\n逐项完成输入、处理和输出，并记录异常。"
            "\n\n## 验收结果\n最后记录验收结论，并把不符合要求的结果返回对应步骤修正。"
        )
        job = self.pipeline.create("Agent Skills 操作手册", ["juejin"], {"automated_workflow": True})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Agent Skills 让效率翻 5 倍",
            "body": body,
            "draft_meta": {
                "claim_ledger": [],
                "quality_gate": {"passed": True},
                "cover_design": {
                    "title_text": "效率翻 5 倍",
                    "subtitle_text": "旧承诺",
                    "visual_subject": "generic face",
                },
            },
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        cover = current["draft_meta"]["cover_design"]
        self.assertNotIn("5 倍", current["title"])
        self.assertNotIn("5 倍", cover["title_text"])
        self.assertNotEqual(cover["subtitle_text"], "旧承诺")
        self.assertIn("workflow playbook", cover["background_prompt"])

    def test_deterministic_claim_cleanup_avoids_second_model_call_for_unclosed_fence(self):
        safe = (
            "## 明确场景\n先明确场景，再拆解输入、步骤、输出和失败恢复条件。"
            "每一步都保留可复查的来源和结果，完成后核对正文与配图。"
            "\n\n## 执行任务\n接着运行一项真实任务，记录触发条件和输出契约。"
            "\n\n## 验收结果\n最后把不符合要求的结果返回对应步骤修正，并保存验收结论。"
        )
        body = safe + "\n\n这个方法让效率翻 5 倍。\n\n```yaml\nname: my-skill"
        job = self.pipeline.create("Agent Skills 操作手册", ["juejin"], {"automated_workflow": True})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "10 分钟写完 Agent Skill",
            "body": body,
            "draft_meta": {"claim_ledger": [], "quality_gate": {"passed": True}},
        }) as generate, patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        self.assertEqual(generate.call_count, 1)
        self.assertNotIn("5 倍", current["body"])
        self.assertEqual(current["body"].count("```"), 2)
        self.assertTrue(current["draft_meta"]["claim_sanitization"]["passed"])

    def test_automated_workflow_repairs_unsupported_claims_once_before_media(self):
        from content_platform.content_depth import build_content_depth_plan
        from content_platform.run_contract import build_run_contract

        safe_body = (
            "为什么工具越多流程越乱？先把目标写清楚再选择能力。\n"
            "先列出当前任务，并确认真正需要处理的输入。\n"
            "再确认输入来源，避免把未经核对的信息带进流程。\n"
            "选择对应能力，并明确每项工具应该产生什么结果。\n"
            "核对输出，保留来源，检查结果，最后记录下一步。\n"
            "如果任一环节缺少证据，就返回该环节修正后重新验证。"
        )
        brief = {
            "automated_workflow": True,
            "run_contract": build_run_contract("kuaishou"),
            "content_depth_plan": build_content_depth_plan(
                "工具流程", safe_body,
                evidence=["https://example.test/source"],
                actions=["列出任务", "确认输入", "核对输出"], platform="kuaishou",
            ),
        }
        job = self.pipeline.create("工具流程", ["kuaishou"], brief)
        drafts = [
            {"title": "十分钟搞定", "body": "我实测十分钟省下一半成本。" * 12, "draft_meta": {"claim_ledger": []}},
            {"title": "工具流程", "body": safe_body, "draft_meta": {"claim_ledger": [], "quality_gate": {"passed": True}}},
        ]
        with patch.object(self.pipeline.generator, "generate", side_effect=drafts) as generate, patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        self.assertEqual(generate.call_count, 2)
        repair_brief = generate.call_args_list[1].args[1]
        self.assertIn("factual_repair", repair_brief)
        claim_step = [row for row in self.store.workflow_steps(job["id"]) if row["step_name"] == "validate_factual_claims"][-1]
        self.assertEqual(claim_step["status"], "SUCCEEDED")

    def test_automated_juejin_technical_article_rebuilds_from_primary_fact_pack(self):
        claims = [
            {"claim": claim, "source_url": "https://agentskills.io/specification", "evidence_path": "sources/spec.md", "provenance_hash": "a" * 64, "verified": True, "source_type": "verified_primary_source"}
            for claim in (
                "Agent Skill 是一个目录，至少包含一个 SKILL.md 文件。",
                "SKILL.md 必须包含 YAML frontmatter，后面接 Markdown 正文。",
                "Skill 目录可以包含 scripts、references 和 assets 等可选资源目录。",
                "Agent 会渐进式加载 Skill，只在任务需要时拉取更多细节。",
            )
        ]
        job = self.pipeline.create("Agent Skills 入门", ["juejin"], {
            "automated_workflow": True, "content_form": "article", "claim_ledger": claims,
        })
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "一行命令让 AI 质量翻倍",
            "body": "Agent Skills 会自动执行高级工程师的完整工作流，输出质量直接翻倍。" * 20,
            "draft_meta": {"claim_ledger": claims, "content_form": "article", "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        self.assertEqual(current["title"], "Agent Skill 入门：一份来源核对清单")
        self.assertTrue(current["body"].startswith("为什么要先核对 Agent Skill 的目录、文件和资源？"))
        self.assertNotIn("为什么Agent Skill 入门", current["body"])
        self.assertNotIn("质量翻倍", current["body"])
        self.assertIn("Agent Skill 是一个目录", current["body"])
        self.assertEqual(current["draft_meta"]["grounded_technical_rebuild"]["version"], "verified_primary_claims_v1")

    def test_short_video_normalizes_spaced_domain_before_factual_and_media_steps(self):
        job = self.pipeline.create("Domain workflow", ["kuaishou"], {"automated_workflow": True})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Domain workflow",
            "body": "打开 ai. kuaishou. com。检查来源。确认配置。执行流程。核对结果。保存证据。复查输出。完成记录。",
            "draft_meta": {"claim_ledger": [], "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        self.assertIn("ai.kuaishou.com", current["body"])
        self.assertNotIn("ai.\nkuaishou", current["body"])

    def test_short_video_restores_verified_domain_suffix_before_media_steps(self):
        hotspot = {
            "observed_title": "打开 ai.kuaishou.com 注册开发者账号。",
            "source_url": "https://cp.kuaishou.com/profile",
            "snapshot_path": "hotspots/kuaishou.txt",
            "provenance_hash": "a" * 64,
            "evidence_type": "native",
            "evidence_verified": True,
        }
        job = self.pipeline.create("Domain workflow", ["kuaishou"], {"associated_hotspot": hotspot})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Domain workflow",
            "body": "第一步，打开 ai.kuaishou.\n\n第二步，检查来源。\n\n第三步，确认配置。",
            "draft_meta": {"claim_ledger": [], "quality_gate": {"passed": True}},
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        current = self.store.get_job(job["id"])
        self.assertIn("ai.kuaishou.com", current["body"])
        self.assertTrue(current["draft_meta"]["claim_ledger"])

    def test_short_video_rechecks_stale_hook_score_after_copy_transforms(self):
        job = self.pipeline.create("AI workflow", ["kuaishou"], {})
        draft = {
            "title": "AI 工作流",
            "body": "做内容还在来回切工具？\n\n先确认输入。\n\n再核对结果。",
            "draft_meta": {
                "quality_scores": {"clarity": 1, "authenticity": 1, "hook_strength": 0.45, "platform_fit": 0.75, "burstiness": 0.6},
                "quality_gate": {"passed": False, "failed_dimensions": ["hook_strength"]},
                "strategy": {"content_form": "vertical_video", "primary_platforms": ["kuaishou"]},
            },
        }
        with patch.object(self.pipeline.generator, "generate", return_value=draft), patch.object(self.pipeline.media, "generate", return_value=None):
            result = self.pipeline.run(job["id"])

        assert result["state"] != "blocked"
        assert result["draft_meta"]["quality_gate"]["gates"]["G3_anti_generic"]["passed"] is True

    def test_scheduled_contract_requires_content_depth_before_media(self):
        from content_platform.run_contract import build_run_contract

        job = self.pipeline.create(
            "Workflow tutorial",
            ["tiktok"],
            {"run_contract": build_run_contract("tiktok")},
        )
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Workflow tutorial",
            "body": "Useful but shallow advice without a structured depth plan.",
            "draft_meta": {"claim_ledger": []},
        }), patch.object(self.pipeline.media, "generate") as media:
            result = self.pipeline.run(job["id"])

        self.assertEqual(result["state"], "blocked")
        depth_step = [row for row in self.store.workflow_steps(job["id"]) if row["step_name"] == "validate_content_depth"][-1]
        self.assertEqual(depth_step["status"], "BLOCKED")
        media.assert_not_called()

    def test_scheduled_contract_preserves_compiled_depth_plan_when_model_omits_it(self):
        from content_platform.content_depth import build_content_depth_plan
        from content_platform.run_contract import build_run_contract

        depth_plan = build_content_depth_plan(
            "Workflow tutorial",
            "Verify the source. Explain the workflow. Inspect the artifact.",
            evidence=["https://example.test/evidence"],
            actions=["verify source", "explain workflow", "inspect artifact"],
            platform="kuaishou",
        )
        job = self.pipeline.create(
            "Workflow tutorial",
            ["kuaishou"],
            {"run_contract": build_run_contract("kuaishou"), "content_depth_plan": depth_plan},
        )
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "Workflow tutorial",
            "body": "为什么这个流程容易失败？\n先核对来源。\n再检查配置。\n然后运行工具。\n查看证据。\n修复错误。\n重新验证。\n最后记录结果。",
            "draft_meta": {
                "claim_ledger": [],
                "quality_gate": {"passed": True},
                "content_depth_plan": {"version": "content_depth_plan_v1", "title": "Workflow tutorial"},
            },
        }), patch.object(self.pipeline.media, "generate", return_value=None):
            self.pipeline.run(job["id"])

        depth_step = [row for row in self.store.workflow_steps(job["id"]) if row["step_name"] == "validate_content_depth"][-1]
        self.assertEqual(depth_step["status"], "SUCCEEDED")

    def test_compiled_run_sanitizes_unsupported_numeric_title(self):
        from content_platform.run_contract import build_run_contract

        job = self.pipeline.create("Verified workflow", ["twitter"], {"run_contract": build_run_contract("twitter")})
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "99% success in 30 seconds",
            "body": "Use the verified source. Check the owner. Check the deadline. Check the source before acting. " * 3,
            "draft_meta": {"claim_ledger": [], "content_depth_plan": {
                "version": "content_depth_plan_v1", "title": "Verified workflow", "knowledge_points": ["owner", "deadline", "source"],
                "case_or_demo": "verified source", "steps": ["owner", "deadline"], "counterexample": "do not guess",
                "takeaway": "verify", "interaction_prompt": "which step?", "continuation_claimed": False,
            }},
        }):
            result = self.pipeline.run(job["id"])
        assert result["state"] == "review_required"
        assert result["title"] == "Verified workflow"

    def test_long_unsafe_topic_does_not_become_a_multi_sentence_title_fallback(self):
        from content_platform.run_contract import build_run_contract

        long_topic = "九十九秒完成工作。朋友每天节省八小时。" * 8
        job = self.pipeline.create(long_topic, ["twitter"], {"run_contract": build_run_contract("twitter")})
        safe_body = "先核对来源。\n再确认负责人。\n记录下一步。" * 8
        with patch.object(self.pipeline.generator, "generate", return_value={
            "title": "九十九秒完成工作",
            "body": safe_body,
            "draft_meta": {"claim_ledger": [], "content_depth_plan": {
                "version": "content_depth_plan_v1", "title": "workflow", "knowledge_points": ["a", "b", "c"],
                "case_or_demo": "source", "steps": ["a", "b"], "counterexample": "none", "takeaway": "verify",
                "interaction_prompt": "which?", "continuation_claimed": False,
            }},
        }):
            result = self.pipeline.run(job["id"])

        self.assertLessEqual(len(result["title"]), 40)
        self.assertNotEqual(result["title"], long_topic)

    def test_short_video_geo_gate_uses_short_form_contract(self):
        draft = {
            "draft_meta": {
                "content_form": "short_video",
                "strategy": {"primary_platforms": ["douyin_ai"]},
                "quality_gate": {"passed": True},
                "media_plan": ["cover", "human_voiceover"],
                "growth_recipe": {},
            }
        }
        geo = {
            "score": 30,
            "checks": {"direct_answer": True, "short_paragraphs": True},
        }

        gate = self.pipeline._quality_gate("job-1", draft, {"level": "pass"}, geo, phase="generation")

        assert gate["gates"]["G2_geo"]["passed"] is True
        assert gate["gates"]["G2_geo"]["contract"] == "short_video"

    def test_short_video_allows_only_burstiness_variance_without_waiving_other_quality_rules(self):
        draft = {
            "draft_meta": {
                "content_form": "short_video",
                "strategy": {"primary_platforms": ["douyin_ai"]},
                "quality_gate": {"passed": False, "failed_dimensions": ["burstiness"]},
                "media_plan": ["cover", "human_voiceover"],
                "growth_recipe": {},
            }
        }
        geo = {"score": 30, "checks": {"direct_answer": True, "short_paragraphs": True}}

        gate = self.pipeline._quality_gate("job-1", draft, {"level": "pass"}, geo, phase="generation")

        assert gate["gates"]["G3_anti_generic"]["passed"] is True
        assert gate["gates"]["G3_anti_generic"]["contract"] == "short_video"

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

    def test_pre_populated_checkpoint_preserves_generated_metadata_for_media_resume(self):
        job = self.pipeline.create("Checkpoint resume", ["file"], {"audience": "operators"})
        persisted = {
            "knowledge_card_recipe": {"version": "knowledge_card_recipe_v1", "card_count": 3},
            "platform_source_matrix": {"successful_source_count": 5},
            "growth_strategy": {"policy_id": "resume-policy"},
        }
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE jobs SET body=?, draft_meta_json=? WHERE id=?",
                ("This is an evidence-backed checkpoint body. " * 8, json.dumps(persisted), job["id"]),
            )

        reviewed = self.pipeline.run(job["id"])

        assert reviewed["draft_meta"]["knowledge_card_recipe"]["card_count"] == 3
        assert reviewed["draft_meta"]["platform_source_matrix"]["successful_source_count"] == 5
        assert reviewed["draft_meta"]["growth_strategy"]["policy_id"] == "resume-policy"

    def test_enforced_wechat_requires_professional_toolchain_before_quality_gate(self):
        pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(Path(self.tmp.name)),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "publishers": {"default": {"type": "file"}},
                "feature_flags": {"channel_auto_workflow_gate": "enforce"},
                "wechat_toolchain": {"wewrite_bin": str(Path(self.tmp.name) / "missing_wewrite")},
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
        self.assertEqual(len([item for item in artifacts if item["kind"] == "image"]), 1)
        self.assertEqual(len([item for item in artifacts if item["kind"] == "cover"]), 1)
        self.assertEqual(len([item for item in artifacts if item["kind"] == "section_image_map"]), 1)

    def test_image_render_evidence_builds_explicit_verified_generated_plan(self):
        artifact_dir = Path(self.tmp.name) / "artifacts" / "generated-article"
        artifact_dir.mkdir(parents=True)
        image = artifact_dir / "section-01.png"
        image.write_bytes(b"generated-image")
        digest = __import__("hashlib").sha256(image.read_bytes()).hexdigest()
        provenance = {
            "assets": [{
                "path": str(image),
                "role": "section",
                "section": "method",
                "source_url": "generated:deterministic_editorial",
                "license": "generated_for_project",
                "generation_evidence": {
                    "provider": "knowledge_card_renderer",
                    "model": "deterministic_editorial_v1",
                    "prompt_hash": "a" * 64,
                },
                "semantic_evidence": {
                    "passed": True,
                    "image_sha256": digest,
                    "semantic_match_score": 0.8,
                    "evidence_level": "artifact_verified",
                },
                "semantic_match_score": 0.8,
                "match_reason": "workflow explanation",
            }],
        }
        (artifact_dir / "asset_provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        (artifact_dir / "section_image_map.json").write_text(json.dumps([{
            "section": "method",
            "image": str(image),
            "asset_id": "section-01",
            "purpose": "workflow explanation",
            "adjacent_to_text": True,
        }]), encoding="utf-8")
        draft = {"body": "Method explanation", "draft_meta": {}}

        Pipeline._attach_image_render_evidence(draft, artifact_dir)

        plan = draft["draft_meta"]["real_scene_background_plan"]
        self.assertTrue(plan["allow_all_verified_generated"])
        self.assertEqual(plan["primary_background_kind"], "verified_semantic_generated_visual")
        self.assertTrue(plan["per_slide_backgrounds"][0]["verified_generated_fallback"])

    def test_image_render_evidence_reads_article_media_contract_as_primary_source(self):
        artifact_dir = Path(self.tmp.name) / "artifacts" / "contract-article"
        artifact_dir.mkdir(parents=True)
        image = artifact_dir / "section-01.png"
        image.write_bytes(b"contract-generated-image")
        digest = __import__("hashlib").sha256(image.read_bytes()).hexdigest()
        asset = {
            "path": str(image),
            "role": "section",
            "section": "method",
            "source_url": "generated:deterministic_editorial",
            "license": "generated_for_project",
            "generation_evidence": {
                "provider": "knowledge_card_renderer",
                "model": "deterministic_editorial_v1",
                "prompt_hash": "a" * 64,
            },
            "semantic_evidence": {
                "passed": True,
                "image_sha256": digest,
                "semantic_match_score": 0.8,
                "evidence_level": "artifact_verified",
            },
            "semantic_match_score": 0.8,
            "match_reason": "workflow explanation",
        }
        mapping = [{
            "section": "method",
            "image": str(image),
            "asset_id": "section-01",
            "purpose": "workflow explanation",
            "adjacent_to_text": True,
        }]
        (artifact_dir / "article_media_contract.json").write_text(json.dumps({
            "version": "article_media_contract_v1",
            "assets": [asset],
            "section_image_map": mapping,
        }), encoding="utf-8")
        draft = {"body": "Method explanation", "draft_meta": {}}

        Pipeline._attach_image_render_evidence(draft, artifact_dir)

        self.assertEqual(draft["draft_meta"]["section_image_map"], mapping)
        self.assertTrue(draft["draft_meta"]["real_scene_background_plan"]["allow_all_verified_generated"])

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

    def test_article_platform_does_not_generate_optional_narration_audio(self):
        root = Path(self.tmp.name)
        self.pipeline = Pipeline(
            self.store,
            {
                "data_dir": str(root),
                "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
                "content_policy": {"allow_local_audio_generation": True},
                "media": {"audio": {"enabled": True}},
                "publishers": {"default": {"type": "file"}},
                "notifications": {"log_path": str(root / "notifications.jsonl")},
            },
        )
        job = self.pipeline.create("Article workflow", ["juejin"], {"content_form": "article"})

        with patch.object(self.pipeline.media, "generate", wraps=self.pipeline.media.generate) as generate:
            self.pipeline.run(job["id"])

        assert not any(call.args and call.args[0] == "audio" for call in generate.call_args_list)
        assert not any(item["kind"] == "audio" for item in self.store.artifacts(job["id"]))

    def test_humanized_copy_is_normalized_before_persistence(self):
        job = self.pipeline.create("Skill guide", ["juejin"], {})
        draft = {"title": "Skill guide", "body": "Original body", "draft_meta": {}}
        with patch("content_platform.humanizer.humanize_text", return_value={
            "ok": True,
            "title": "Skill guide",
            "body": "从 Skills.\nsh 找工具，再调用 skill_registry.\nfind(request)。",
            "patterns_detected": {"rhythm": True},
            "score": 0.8,
        }):
            self.pipeline._humanize_draft(job["id"], draft)

        self.assertIn("Skills.sh", draft["body"])
        self.assertIn("skill_registry.find(request)", draft["body"])

    def test_humanizer_rejects_new_unsupported_claims_and_keeps_verified_copy(self):
        job = self.pipeline.create("Skill guide", ["juejin"], {})
        original = "先按任务类型筛选能力，再检查输出证据。"
        draft = {
            "title": "Skill guide",
            "body": original,
            "draft_meta": {"claim_ledger": []},
        }
        with patch("content_platform.humanizer.humanize_text", return_value={
            "ok": True,
            "title": "Skill guide",
            "body": "vercel-react-best-practices 是必装工具。运行 npx skills add 即可。",
            "patterns_detected": {"rhythm": True},
            "score": 0.9,
        }):
            self.pipeline._humanize_draft(job["id"], draft)

        self.assertEqual(draft["body"], original)
        rejected = [event for event in self.store.events(job["id"]) if event["event"] == "humanize_rejected"]
        self.assertEqual(len(rejected), 1)
        detail = json.loads(rejected[0]["detail_json"])
        self.assertIn("unsourced_tool_recommendation_claim", detail["claim_failures"])
        self.assertIn("unsourced_install_command_claim", detail["claim_failures"])

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

    def test_unsourced_claims_block_before_media_generation(self):
        job = self.pipeline.create("Editorial engineering guide", ["juejin"], {
            "selection_mode": "editorial_calendar",
            "editorial_evidence": {
                "strategy_source": "growth_strategy:juejin:latest",
                "calendar_column": "engineering",
                "planned_date": "2026-08-18",
                "dedupe": "7d_clear",
            },
        })
        compliance = {
            "level": "review",
            "findings": [{"code": "numeric_claim_without_source", "level": "review"}],
            "platforms": ["juejin"],
        }

        with patch.object(self.pipeline.compliance, "evaluate", return_value=compliance), \
             patch.object(self.pipeline, "_generate_optional_media") as generate_media:
            blocked = self.pipeline.run(job["id"])

        self.assertEqual(blocked["state"], "blocked")
        generate_media.assert_not_called()

    def test_prepopulated_markdown_keeps_fenced_code_structure(self):
        job = self.pipeline.create("Code guide", ["juejin"], {"audience": "builders"})
        body = "# Guide\n\n```python\ndef run():\n    return True\n```\n\n" + ("正文内容。" * 100)
        with self.store.connect() as conn:
            conn.execute("UPDATE jobs SET title=?, body=? WHERE id=?", ("Code guide", body, job["id"]))

        reviewed = self.pipeline.run(job["id"])

        self.assertIn("def run():\n    return True", reviewed["body"])

    def test_youtube_english_script_budget_rejects_short_model_output(self):
        short = {"body": "Plan act observe adapt. " * 8}
        complete = {"body": "Plan act observe adapt with evidence and a clear operating boundary now. " * 10}

        self.assertFalse(self.pipeline._video_script_budget(short, {"platforms": ["youtube"]})["passed"])
        self.assertTrue(self.pipeline._video_script_budget(complete, {"platforms": ["youtube"]})["passed"])
        self.assertTrue(self.pipeline._video_script_budget(short, {"platforms": ["kuaishou"]})["passed"])

    def test_overlong_english_video_script_is_trimmed_without_inventing_words(self):
        original = "\n\n".join((f"Scene {index} " + " ".join(f"word{index}x{word}" for word in range(55))) for index in range(8))

        fitted = self.pipeline._fit_english_video_script(original)
        result = self.pipeline._video_script_budget({"body": fitted}, {"platforms": ["youtube"]})

        self.assertTrue(result["passed"])
        self.assertEqual(len(fitted.split("\n\n")), 8)
        self.assertNotIn("word0x40", fitted)
        self.assertTrue(geo_check(fitted)["checks"]["short_paragraphs"])


if __name__ == "__main__":
    unittest.main()
