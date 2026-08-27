import json
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

    def test_each_job_overwrites_generator_checkpoint_dir(self):
        first = self.pipeline.create("First topic", ["wechat"], {"audience": "operators"})
        second = self.pipeline.create("Second topic", ["wechat"], {"audience": "operators"})
        for job in (first, second):
            with self.store.connect() as conn:
                conn.execute("UPDATE jobs SET body=? WHERE id=?", ("Prepared body " * 20, job["id"]))
            self.pipeline.run(job["id"])
            assert self.pipeline.generator.config["checkpoint_dir"] == str(self.pipeline.data_dir / "jobs" / job["id"])

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


if __name__ == "__main__":
    unittest.main()
