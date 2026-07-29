import argparse
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


if __name__ == "__main__":
    unittest.main()
