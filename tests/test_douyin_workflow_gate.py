import argparse
import json
from pathlib import Path
import unittest

from scripts.enforce_douyin_workflow import command_validate_packet, validate_tiktok_repost_packet


class DouyinWorkflowGateTests(unittest.TestCase):
    def valid_packet(self):
        return {
            "content_line": "tiktok_hot_localized_repost",
            "source_url": "https://www.tiktok.com/@cat/video/123",
            "video_id": "123",
            "keyword": "catsoftiktok",
            "trend_reason": "fresh high-intent cat meme trend",
            "source_caption_or_overlay": "cat screams at camera",
            "source_evidence": [{"kind": "video_page_caption", "caption": "cat screams at camera", "pet_positive": True}],
            "source_decision_reason": "video_caption_pet_positive",
            "source_entertainment_or_story_intent": "funny cat reaction, not a knowledge explainer",
            "localization_angle": "preserve the funny reaction and translate for Douyin users",
            "translation_rewrite_plan": "short Chinese reaction narration with pauses",
            "scene_to_script_mapping": [{"scene": "cat jumps", "line": "it suddenly panics"}],
            "visual_review": "passed",
            "title": "这只猫突然开嗓，旁边那只直接看懵",
            "script": "它刚刚还很淡定，下一秒突然开嗓。旁边那只猫完全没反应过来。",
        }

    def test_valid_tiktok_repost_packet_passes(self):
        failures = validate_tiktok_repost_packet(self.valid_packet(), require_visual_review=True)
        self.assertEqual(failures, [])

    def test_missing_source_story_fields_fail(self):
        packet = self.valid_packet()
        del packet["source_entertainment_or_story_intent"]
        failures = validate_tiktok_repost_packet(packet)
        self.assertTrue(any("source_entertainment_or_story_intent" in item for item in failures))

    def test_generic_cat_knowledge_script_cannot_pass_as_tiktok_repost(self):
        packet = self.valid_packet()
        packet["title"] = "猫咪日常"
        packet["script"] = "你有没有发现，猫咪摇尾巴其实是一种行为信号，这说明它很放松。"
        failures = validate_tiktok_repost_packet(packet)
        self.assertIn("generic Douyin title is not allowed for TikTok repost lane", failures)
        self.assertIn("TikTok repost script looks like cat knowledge explainer", failures)

    def test_pending_visual_review_blocks_publish_gate(self):
        packet = self.valid_packet()
        packet["visual_review"] = "pending"
        failures = validate_tiktok_repost_packet(packet, require_visual_review=True)
        self.assertIn("visual_review must be passed before publish package", failures)

    def test_non_pet_source_caption_fails_lane_fit(self):
        packet = self.valid_packet()
        packet["source_caption_or_overlay"] = "Good night routine and mindfulness hook"
        packet["source_entertainment_or_story_intent"] = "sleep motivation quote"
        failures = validate_tiktok_repost_packet(packet)
        self.assertIn("source caption/story does not prove cat or pet lane fit", failures)

    def test_unavailable_caption_requires_visual_review(self):
        packet = self.valid_packet()
        packet["source_caption_or_overlay"] = "TikTok #catsoftiktok candidate; caption unavailable"
        packet["visual_review"] = "pending"
        failures = validate_tiktok_repost_packet(packet)
        self.assertIn("source caption unavailable requires passed visual review before content generation", failures)

    def test_source_evidence_is_required_for_tiktok_repost(self):
        packet = self.valid_packet()
        del packet["source_evidence"]
        failures = validate_tiktok_repost_packet(packet)
        self.assertIn("missing required TikTok repost field: source_evidence", failures)
        self.assertIn("source_evidence must record TikTok tag/caption/visual decision inputs", failures)

    def test_final_video_validation_rejects_source_candidate_only(self):
        import tempfile
        from pathlib import Path

        packet = self.valid_packet()
        packet["artifact_stage"] = "source_candidate"
        packet["path"] = "/tmp/source-candidate.mp4"
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "packet.json"
            packet_path.write_text(__import__("json").dumps(packet, ensure_ascii=False), encoding="utf-8")
            rc = command_validate_packet(
                argparse.Namespace(packet=str(packet_path), require_visual_review=True, require_final_video=True)
            )
        self.assertEqual(rc, 1)


    def test_trend_analysis_requires_11_sources_and_repost_dedup(self):
        from scripts.enforce_douyin_workflow import command_step, REQUIRED_11_TREND_PLATFORMS
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            status_file = f.name
        old_env = os.environ.get("DOUYIN_WORKFLOW_STATUS")
        os.environ["DOUYIN_WORKFLOW_STATUS"] = status_file
        try:
            # 1. ops_strategy
            command_step(argparse.Namespace(name="ops_strategy", artifacts=json.dumps({"lane": "pet"})))

            # 2. trend_analysis with only 5 sources -> must fail (not covering 11 platforms)
            incomplete_sources = [{"platform": p, "status": "success", "evidence": "ok"} for p in list(REQUIRED_11_TREND_PLATFORMS)[:5]]
            rc = command_step(argparse.Namespace(name="trend_analysis", artifacts=json.dumps({"sources": incomplete_sources})))
            self.assertEqual(rc, 1)

            # 3. trend_analysis with all 11 platforms -> must succeed
            full_sources = []
            for idx, p in enumerate(REQUIRED_11_TREND_PLATFORMS):
                if idx < 6:
                    full_sources.append({"platform": p, "status": "success", "evidence": f"verified data for {p}"})
                else:
                    full_sources.append({"platform": p, "status": "failed", "failure_reason": f"WAF 403 on {p}"})
            rc_full = command_step(argparse.Namespace(name="trend_analysis", artifacts=json.dumps({"sources": full_sources})))
            self.assertEqual(rc_full, 0)

            # 4. content_decision
            rc_dec = command_step(argparse.Namespace(name="content_decision", artifacts=json.dumps({
                "cross_sources": ["douyin", "tiktok", "weibo"],
                "selected_topic": "打工猫周末被迫开机"
            })))
            self.assertEqual(rc_dec, 0)

            # 5. content_generation
            rc_gen = command_step(argparse.Namespace(name="content_generation", artifacts=json.dumps({"script": "ok"})))
            self.assertEqual(rc_gen, 0)

            # 6. quality_gate without dedup_evidence -> must fail for repost
            rc_qg_fail = command_step(argparse.Namespace(name="quality_gate", artifacts=json.dumps({
                "is_repost": True,
                "video_path": None,
                "packet_path": None,
                "dedup_evidence_path": "/nonexistent/dedup.json"
            })))
            self.assertEqual(rc_qg_fail, 1)

            # 7. quality_gate with valid high-order dedup evidence -> must pass
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as ef:
                evi_path = ef.name
            evi_payload = {
                "version": "repost_dedup_v1",
                "stage": "post_render",
                "passed": True,
                "transform": {
                    "kind": "high_order_multimodal_dedup",
                    "description": "hflip+zoom_crop+color_jitter+noise_injection+audio_replacement"
                },
                "post_render_verification": {
                    "required": True,
                    "passed": True
                }
            }
            Path(evi_path).write_text(json.dumps(evi_payload), encoding="utf-8")

            rc_qg_ok = command_step(argparse.Namespace(name="quality_gate", artifacts=json.dumps({
                "is_repost": True,
                "dedup_evidence_path": evi_path
            })))
            self.assertEqual(rc_qg_ok, 0)
            if os.path.exists(evi_path):
                os.unlink(evi_path)

        finally:
            if old_env:
                os.environ["DOUYIN_WORKFLOW_STATUS"] = old_env
            else:
                os.environ.pop("DOUYIN_WORKFLOW_STATUS", None)
            if os.path.exists(status_file):
                os.unlink(status_file)


if __name__ == "__main__":
    unittest.main()
