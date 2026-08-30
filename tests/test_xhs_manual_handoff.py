import hashlib
import json
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from content_platform.delivery_health import delivery_health_decision
from content_platform.publishers import SocialAutoUploadPublisher, XiaohongshuManualHandoffPublisher, build_publisher


class XiaohongshuManualHandoffTests(unittest.TestCase):
    def _write_png(self, path, *, width=1080, height=1440, marker=b""):
        def chunk(kind, payload):
            body = kind + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        row = b"\x00" + (marker[:3].ljust(3, b"\x00") * width)
        raw = row * height
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )

    def _asset_record(self, image, index):
        digest = hashlib.sha256(Path(image).read_bytes()).hexdigest()
        return {
            "scene_id": f"xhs_{index}",
            "path": str(image),
            "sha256": digest,
            "source_url": f"generated:test-{index}",
            "license": "generated_for_project",
            "render_evidence": {"verified": True, "renderer": "unit_test_carousel", "artifact_sha256": digest},
            "generation_evidence": {"provider": "unit-test"},
        }

    def _write_provenance(self, root, images):
        (Path(root) / "asset_provenance.json").write_text(
            json.dumps({"version": "asset_provenance_v1", "assets": [self._asset_record(image, index) for index, image in enumerate(images, 1)]}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _package(self, root, *, publish_mode="manual", image_count=6, duplicate_content=False, cover_size=(1080, 1440), include_provenance=True, operator_delivery=None):
        images = []
        for index in range(image_count):
            image = Path(root) / f"card-{index}.png"
            marker = b"dup" if duplicate_content and index > 0 else f"{index:03d}".encode("ascii")
            width, height = cover_size if index == 0 else (1080, 1440)
            self._write_png(image, width=width, height=height, marker=marker)
            images.append(str(image))
        if include_provenance:
            self._write_provenance(root, images)
        package = {
            "publish_mode": publish_mode,
            "title": "AI 工作流清单",
            "body": "这是可直接执行的三步工作流：先保存这份清单，再按步骤完成设置；每一步都有对应的验证结果和回退方法。" * 2,
            "topics": ["AI效率", "工作流"],
            "cover": images[0],
            "images": images,
            "image_manifest": [self._asset_record(image, index) for index, image in enumerate(images, 1)],
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
        if operator_delivery is not None:
            package["operator_delivery"] = {
                **operator_delivery,
                "expected_images": images,
                "delivered_image_sha256": [hashlib.sha256(Path(item).read_bytes()).hexdigest() for item in images],
            }
        path = Path(root) / "handoff_package.json"
        path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
        return path, package

    def test_gate_requires_explicit_manual_mode_and_six_unique_images(self):
        from scripts.xhs_manual_publish_gate import check_handoff_package

        with tempfile.TemporaryDirectory() as tmp:
            receipt = {"passed": True, "text_sent": True, "sent": ["one", "two", "three", "four", "five", "six"], "image_count": 6}
            path, package = self._package(tmp, publish_mode="", image_count=6, operator_delivery=receipt)
            self.assertFalse(check_handoff_package(str(path))["passed"])

            path, package = self._package(tmp, publish_mode="manual", image_count=5, operator_delivery=receipt)
            self.assertFalse(check_handoff_package(str(path))["passed"])

            path, package = self._package(tmp, publish_mode="manual", image_count=6, duplicate_content=True, operator_delivery=receipt)
            result = check_handoff_package(str(path))
            self.assertFalse(result["passed"])
            self.assertIn("xiaohongshu_card_sha256_not_unique", result["failures"])

            path, package = self._package(tmp, publish_mode="manual", image_count=6, operator_delivery=receipt)
            self.assertTrue(check_handoff_package(str(path))["passed"])

    def test_gate_requires_cover_three_to_four_and_operator_receipt(self):
        from scripts.xhs_manual_publish_gate import check_handoff_package

        with tempfile.TemporaryDirectory() as tmp:
            receipt = {"passed": True, "text_sent": True, "sent": ["one", "two", "three", "four", "five", "six"], "image_count": 6}
            path, package = self._package(tmp, cover_size=(1080, 1080), operator_delivery=receipt)
            result = check_handoff_package(str(path))
            self.assertFalse(result["passed"])
            self.assertIn("xiaohongshu_cover_not_3_to_4", result["failures"])

            path, package = self._package(tmp)
            result = check_handoff_package(str(path))
            self.assertFalse(result["passed"])
            self.assertIn("operator_delivery_receipt_missing", result["failures"])

    def test_gate_requires_source_license_and_render_evidence_from_manifest(self):
        from scripts.xhs_manual_publish_gate import check_handoff_package

        with tempfile.TemporaryDirectory() as tmp:
            receipt = {"passed": True, "text_sent": True, "sent": ["one", "two", "three", "four", "five", "six"], "image_count": 6}
            path, package = self._package(tmp, include_provenance=False, operator_delivery=receipt)
            package["image_manifest"][2].pop("license")
            package["image_manifest"][3].pop("render_evidence")
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            result = check_handoff_package(str(path))

        self.assertFalse(result["passed"])
        self.assertIn("xiaohongshu_card_3_license_missing", result["failures"])
        self.assertIn("xiaohongshu_card_4_render_evidence_missing", result["failures"])

    def test_gate_rejects_unreadable_body_card_even_with_valid_manifest(self):
        from scripts.xhs_manual_publish_gate import check_handoff_package

        with tempfile.TemporaryDirectory() as tmp:
            receipt = {"passed": True, "text_sent": True, "sent": ["one", "two", "three", "four", "five", "six"], "image_count": 6}
            path, package = self._package(tmp, operator_delivery=receipt)
            Path(package["images"][4]).write_bytes(b"not-a-real-image")
            package["image_manifest"][4] = self._asset_record(package["images"][4], 5)
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            result = check_handoff_package(str(path))

        self.assertFalse(result["passed"])
        self.assertIn("xiaohongshu_card_5_unreadable", result["failures"])

    def test_gate_rejects_header_only_image_and_malformed_receipt(self):
        from scripts.xhs_manual_publish_gate import check_handoff_package

        with tempfile.TemporaryDirectory() as tmp:
            receipt = {"passed": True, "text_sent": True, "sent": ["one"] * 6, "image_count": "six"}
            path, package = self._package(tmp, operator_delivery=receipt)
            broken = Path(package["images"][2])
            broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
            package["image_manifest"][2] = self._asset_record(broken, 3)
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")

            result = check_handoff_package(str(path))

        self.assertFalse(result["passed"])
        self.assertIn("xiaohongshu_card_3_unreadable", result["failures"])
        self.assertIn("operator_delivery_image_count_mismatch", result["failures"])

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
            for index in range(6):
                image = root / f"card-{index}.png"
                self._write_png(image, marker=f"{index:03d}".encode("ascii"))
                images.append({"kind": "image", "path": str(image)})
            self._write_provenance(root, [item["path"] for item in images])
            job = {"id": "xhs-job", "title": "AI 工作流清单", "body": "这是一份足够详细的小红书正文，用于验证人工交接包在发送失败时不能被标记为就绪。" * 2, "artifacts": images, "draft_meta": {"content_depth_plan": {"takeaway": "保存这份三步清单，按步骤完成并在每一步核对结果。"}}}
            publisher = XiaohongshuManualHandoffPublisher(root)
            with patch("content_platform.publishers.deliver_xiaohongshu_package", return_value={"passed": False, "error": "target_missing"}):
                result = publisher.deliver(job, "xiaohongshu")
                package = json.loads(Path(result.external_id).read_text(encoding="utf-8"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("operator delivery", result.error)
        self.assertEqual(package["status"], "blocked")

    def test_handoff_is_ready_only_after_media_are_sent_to_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = []
            for index in range(6):
                image = root / f"card-{index}.png"
                self._write_png(image, marker=f"{index:03d}".encode("ascii"))
                images.append({"kind": "image", "path": str(image)})
            self._write_provenance(root, [item["path"] for item in images])
            job = {"id": "xhs-job", "title": "AI 工作流清单", "body": "这是一份足够详细的小红书正文，用于验证全部文本和图片发送成功后才能进入人工交接状态。" * 2, "artifacts": images, "draft_meta": {"content_depth_plan": {"takeaway": "保存这份三步清单，按步骤完成并在每一步核对结果。"}}}
            publisher = XiaohongshuManualHandoffPublisher(root)
            paths = [item["path"] for item in images]
            receipt = {
                "passed": True,
                "text_sent": True,
                "sent": ["one", "two", "three", "four", "five", "six"],
                "image_count": 6,
                "expected_images": paths,
                "delivered_image_sha256": [hashlib.sha256(Path(item).read_bytes()).hexdigest() for item in paths],
            }
            with patch("content_platform.publishers.deliver_xiaohongshu_package", return_value=receipt):
                result = publisher.deliver(job, "xiaohongshu")
                package = json.loads(Path(result.external_id).read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "handoff_pending")
        self.assertEqual(package["operator_delivery"], receipt)
        self.assertEqual(len(package["images"]), 6)
        self.assertEqual(len(package["image_manifest"]), 6)
        self.assertTrue(all(item["source_url"].startswith("generated:") for item in package["image_manifest"]))
        self.assertTrue(all(item["license"] == "generated_for_project" for item in package["image_manifest"]))
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

    def test_xiaohongshu_delivery_receipt_records_package_and_image_count(self):
        from scripts.deliver_media import deliver_xiaohongshu_package

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path = root / "xhs.json"
            images = [str(root / f"card-{index}.png") for index in range(6)]
            package_path.write_text(
                json.dumps(
                    {
                        "title": "AI 工作流清单",
                        "body": "正文",
                        "topics": ["AI效率"],
                        "manual_publish_guide": "手动上传并核对后发布",
                        "images": images,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            expected_package_sha256 = hashlib.sha256(package_path.read_bytes()).hexdigest()
            with patch("scripts.deliver_media.deliver", return_value={"passed": True, "text_sent": True, "sent": images.copy()}):
                receipt = deliver_xiaohongshu_package(package_path)
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["image_count"], 6)
            self.assertEqual(receipt["expected_images"], images)
            self.assertEqual(receipt["package_sha256"], expected_package_sha256)
