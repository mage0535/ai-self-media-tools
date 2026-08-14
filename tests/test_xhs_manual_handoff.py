import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.delivery_health import delivery_health_decision
from content_platform.publishers import SocialAutoUploadPublisher, XiaohongshuManualHandoffPublisher, build_publisher


class XiaohongshuManualHandoffTests(unittest.TestCase):
    def _package(self, root, *, publish_mode="manual", image_count=3):
        images = []
        for index in range(image_count):
            image = Path(root) / f"card-{index}.png"
            image.write_bytes(b"png")
            images.append(str(image))
        package = {
            "publish_mode": publish_mode,
            "title": "AI 工作流清单",
            "body": "这是可直接执行的三步工作流：先保存这份清单，再按步骤完成设置；每一步都有对应的验证结果和回退方法。" * 2,
            "topics": ["AI效率", "工作流"],
            "cover": images[0],
            "images": images,
            "manual_publish_guide": "在小红书 App 中手动上传图片，核对标题、正文和话题后，由账号所有者点击发布。",
            "growth_strategy": {
                "strategy_id": "xiaohongshu_recovery_v1",
                "content_pillar": "ai_efficiency_workflow_system",
                "first_image_promise": "三步把 AI 工作流变成可复用清单",
                "save_value": "包含可保存的步骤清单和一个具体示例。",
                "min_publish_interval_hours": 36,
                "post_publish_review_hours": [1, 24, 72],
                "publish_boundary": "manual_handoff_only",
            },
        }
        path = Path(root) / "handoff_package.json"
        path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
        return path, package

    def test_gate_requires_explicit_manual_mode_and_three_images(self):
        from scripts.xhs_manual_publish_gate import check_handoff_package

        with tempfile.TemporaryDirectory() as tmp:
            path, package = self._package(tmp, publish_mode="", image_count=3)
            self.assertFalse(check_handoff_package(str(path))["passed"])

            path, package = self._package(tmp, publish_mode="manual", image_count=2)
            self.assertFalse(check_handoff_package(str(path))["passed"])

            path, package = self._package(tmp, publish_mode="manual", image_count=3)
            self.assertTrue(check_handoff_package(str(path))["passed"])

    def test_gate_requires_recovery_strategy_evidence(self):
        from scripts.xhs_manual_publish_gate import check_handoff_package

        with tempfile.TemporaryDirectory() as tmp:
            path, package = self._package(tmp)
            package.pop("growth_strategy")
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

            result = check_handoff_package(str(path))

        self.assertFalse(result["passed"])
        self.assertIn("growth_strategy_missing", result["failures"])

    def test_health_gate_stays_manual_when_config_is_disabled(self):
        decision = delivery_health_decision("xiaohongshu", {"delivery_health": {"enabled": False}}, action="publish")

        self.assertTrue(decision.ok)
        self.assertEqual(decision.state, "manual_handoff_only")
        self.assertTrue(decision.require_postcheck)

    def test_factory_cannot_select_an_automatic_xiaohongshu_publisher(self):
        publisher = build_publisher(
            "xiaohongshu",
            {"publishers": {"platforms": {"xiaohongshu": {"type": "social-auto-upload"}}}},
            tempfile.gettempdir(),
        )

        self.assertIsInstance(publisher, XiaohongshuManualHandoffPublisher)

    def test_direct_social_auto_uploader_cannot_reach_xiaohongshu(self):
        publisher = SocialAutoUploadPublisher("xiaohongshu", "main", project_dir="/missing", python_bin="/missing")

        result = publisher.deliver({"title": "T", "body": "B", "artifacts": []}, "xiaohongshu")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("manual publish only", result.error)

    def test_handoff_requires_successful_operator_delivery_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = []
            for index in range(3):
                image = root / f"card-{index}.png"
                image.write_bytes(b"png")
                images.append({"kind": "image", "path": str(image)})
            job = {"id": "xhs-job", "title": "AI 工作流清单", "body": "这是一份足够详细的小红书正文，用于验证人工交接包在发送失败时不能被标记为就绪。" * 2, "artifacts": images, "draft_meta": {"content_depth_plan": {"takeaway": "保存这份三步清单，按步骤完成并在每一步核对结果。"}}}
            publisher = XiaohongshuManualHandoffPublisher(root)
            with patch("content_platform.publishers.deliver_xiaohongshu_package", return_value={"passed": False, "error": "target_missing"}):
                result = publisher.deliver(job, "xiaohongshu")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("operator delivery", result.error)

    def test_handoff_is_ready_only_after_media_are_sent_to_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = []
            for index in range(3):
                image = root / f"card-{index}.png"
                image.write_bytes(b"png")
                images.append({"kind": "image", "path": str(image)})
            job = {"id": "xhs-job", "title": "AI 工作流清单", "body": "这是一份足够详细的小红书正文，用于验证全部文本和图片发送成功后才能进入人工交接状态。" * 2, "artifacts": images, "draft_meta": {"content_depth_plan": {"takeaway": "保存这份三步清单，按步骤完成并在每一步核对结果。"}}}
            publisher = XiaohongshuManualHandoffPublisher(root)
            receipt = {"passed": True, "text_sent": True, "sent": ["one", "two", "three"]}
            with patch("content_platform.publishers.deliver_xiaohongshu_package", return_value=receipt):
                result = publisher.deliver(job, "xiaohongshu")
                package = json.loads(Path(result.external_id).read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "handoff_pending")
        self.assertEqual(package["operator_delivery"], receipt)
        self.assertEqual(package["growth_strategy"]["strategy_id"], "xiaohongshu_recovery_v1")
        self.assertEqual(package["growth_strategy"]["post_publish_review_hours"], [1, 24, 72])


class DeliveryMediaTests(unittest.TestCase):
    def test_delivery_loads_target_from_private_environment_file_without_exposing_it(self):
        from scripts.deliver_media import resolve_target

        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "notifications.env"
            env_file.write_text("AI_SELF_MEDIA_TELEGRAM_TARGET=telegram:private\n", encoding="utf-8")
            with patch.dict(os.environ, {"HERMES_DELIVERY_ENV_FILE": str(env_file)}, clear=True):
                self.assertEqual(resolve_target(), "telegram:private")
