import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.publishers import (
    AiToEarnDraftPublisher,
    AiToEarnFlowPublisher,
    AyrsharePublisher,
    DevtoDraftPublisher,
    SocialAutoUploadPublisher,
    WechatDraftPublisher,
    build_publisher,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.payload


class PublisherV2Tests(unittest.TestCase):
    def test_devto_always_creates_private_draft(self):
        with patch("content_platform.publishers.urllib.request.urlopen", return_value=FakeResponse({"id": 12})) as call:
            result = DevtoDraftPublisher(api_key="key").deliver({"title": "T", "body": "B"}, "devto")
        body = json.loads(call.call_args.args[0].data)
        self.assertTrue(result.ok)
        self.assertFalse(body["article"]["published"])
        self.assertIn("HermesContentPlatform", call.call_args.args[0].headers["User-agent"])

    def test_wechat_uses_token_and_draft_endpoints_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "cover.png"
            image.write_bytes(b"png")
            job = {
                "title": "T",
                "body": "B",
                "platform_payload": {"html": "<p>B</p>"},
                "artifacts": [{"kind": "image", "path": str(image)}],
            }
            responses = [
                FakeResponse({"access_token": "token", "expires_in": 7200}),
                FakeResponse({"media_id": "thumb-1", "url": "https://example.com/image"}),
                FakeResponse({"media_id": "draft-1"}),
            ]
            with patch("content_platform.publishers.urllib.request.urlopen", side_effect=responses) as call:
                result = WechatDraftPublisher(app_id="app", app_secret="secret").deliver(job, "wechat")
        urls = [item.args[0].full_url for item in call.call_args_list]
        self.assertTrue(result.ok)
        self.assertTrue(any("/cgi-bin/token" in url for url in urls))
        self.assertTrue(any("/cgi-bin/material/add_material" in url for url in urls))
        self.assertTrue(any("/cgi-bin/draft/add" in url for url in urls))
        self.assertFalse(any("freepublish" in url for url in urls))
        draft_request = call.call_args_list[-1].args[0]
        self.assertEqual(json.loads(draft_request.data)["articles"][0]["thumb_media_id"], "thumb-1")

    def test_ayrshare_live_gate_falls_back_to_local_draft_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"AYRSHARE_API_KEY": "key"}, clear=True):
                publisher = AyrsharePublisher(live_enabled=True, fallback_outbox=str(Path(tmp) / "outbox"))
                with patch("content_platform.publishers.urllib.request.urlopen") as call:
                    result = publisher.deliver({"id": "job1", "title": "T", "body": "B"}, "bluesky")
            self.assertTrue(result.ok)
            self.assertEqual(result.status, "drafted")
            self.assertIn("live publishing is disabled", result.error)
            self.assertTrue(Path(result.external_id).is_file())
            call.assert_not_called()

    def test_ayrshare_sends_only_public_media_urls_and_maps_x_to_twitter(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_image = Path(tmp) / "local.png"
            local_image.write_bytes(b"png")
            job = {
                "id": "job2",
                "title": "T",
                "body": "B",
                "artifacts": [
                    {"kind": "image", "path": str(local_image)},
                    {"kind": "image", "url": "https://cdn.example.com/cover.png"},
                ],
            }
            publisher = AyrsharePublisher(
                api_key="key",
                live_enabled=True,
                fallback_outbox=str(Path(tmp) / "outbox"),
                quota_db_path=str(Path(tmp) / "quota.db"),
            )
            with patch.dict(os.environ, {"CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH": "1"}, clear=True):
                with patch("content_platform.publishers.urllib.request.urlopen", return_value=FakeResponse({"status": "success", "id": "post1"})) as call:
                    result = publisher.deliver(job, "x")
            payload = json.loads(call.call_args.args[0].data)
            self.assertTrue(result.ok)
            self.assertEqual(result.status, "published")
            self.assertEqual(payload["platforms"], ["twitter"])
            self.assertEqual(payload["mediaUrls"], ["https://cdn.example.com/cover.png"])
            self.assertNotIn("file://", json.dumps(payload))

    def test_ayrshare_quota_exhaustion_falls_back_without_consuming_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = AyrsharePublisher(
                api_key="key",
                live_enabled=True,
                fallback_outbox=str(Path(tmp) / "outbox"),
                quota_db_path=str(Path(tmp) / "quota.db"),
                monthly_limit=1,
            )
            with patch.dict(os.environ, {"CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH": "1"}, clear=True):
                with patch("content_platform.publishers.urllib.request.urlopen", return_value=FakeResponse({"status": "success", "id": "post1"})) as call:
                    first = publisher.deliver({"id": "job3", "title": "T", "body": "B"}, "bluesky")
                    second = publisher.deliver({"id": "job4", "title": "T", "body": "B"}, "bluesky")
            self.assertEqual(first.status, "published")
            self.assertEqual(second.status, "drafted")
            self.assertIn("monthly quota", second.error)
            self.assertEqual(call.call_count, 1)

    def test_build_publisher_selects_ayrshare_account_eligible_for_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "publishers": {
                    "platforms": {
                        "bluesky": {
                            "type": "ayrshare",
                            "live": True,
                            "fallback": {"outbox": str(Path(tmp) / "outbox")},
                            "accounts": [
                                {"label": "reddit-only", "api_key": "wrong", "platforms": ["reddit"]},
                                {"label": "bluesky-primary", "api_key": "right", "platforms": ["bluesky"]},
                            ],
                        }
                    }
                }
            }
            publisher = build_publisher("bluesky", config, tmp)
            with patch.dict(os.environ, {"CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH": "1"}, clear=True):
                with patch("content_platform.publishers.urllib.request.urlopen", return_value=FakeResponse({"status": "success", "id": "post1"})) as call:
                    result = publisher.deliver({"id": "job5", "title": "T", "body": "B"}, "bluesky")
            self.assertTrue(result.ok)
            self.assertEqual(call.call_args.args[0].headers["Authorization"], "Bearer right")

    def test_aitoearn_draft_publisher_returns_drafted(self):
        class FakeClient:
            def create_image_text_draft(self, **kwargs):
                return {"task_ids": ["task-1"]}

            def get_draft_task_status(self, task_id):
                return {"status": "success", "draft_id": "draft-1", "raw_text": "status: success\ndraftId: draft-1"}

        publisher = AiToEarnDraftPublisher(client=FakeClient(), image_model="gpt-image-2")
        result = publisher.deliver({"id": "job6", "title": "T", "body": "B"}, "xiaohongshu")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "drafted")
        self.assertEqual(result.external_id, "draft-1")

    def test_aitoearn_flow_publisher_returns_handoff_pending(self):
        class FakeClient:
            def get_platform_metadata(self, platform):
                return {"publishPolicy": {"completionStrategy": "user_handoff"}}

            def create_channel_publish_flow(self, payload):
                return {"flow_id": "flow-1", "raw_text": "flowId: flow-1"}

        publisher = AiToEarnFlowPublisher(client=FakeClient(), account_id="douyin-1", delivery_status="drafted")
        result = publisher.deliver({"id": "job7", "title": "T", "body": "B"}, "douyin")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "handoff_pending")
        self.assertEqual(result.external_id, "flow-1")

    def test_aitoearn_flow_publisher_returns_drafted_for_polling_strategy(self):
        class FakeClient:
            def get_platform_metadata(self, platform):
                return {"publishPolicy": {"completionStrategy": "polling"}}

            def create_channel_publish_flow(self, payload):
                return {"flow_id": "flow-2", "raw_text": "flowId: flow-2"}

            def get_channel_publish_record_by_flow_id(self, flow_id):
                return {"status": 1, "publish_record_id": "record-1", "work_link": "https://example.com/work"}

        publisher = AiToEarnFlowPublisher(client=FakeClient(), account_id="bili-1", delivery_status="drafted")
        result = publisher.deliver({"id": "job8", "title": "T", "body": "B"}, "bilibili")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "drafted")
        self.assertEqual(result.external_id, "record-1")

    def test_social_auto_upload_publisher_uses_scheduled_pending_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "demo.mp4"
            video.write_bytes(b"video")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            publisher = SocialAutoUploadPublisher(
                platform_name="bilibili",
                account_name="creator",
                project_dir=tmp,
                python_bin="python",
                schedule_at="2099-12-31 23:59",
            )
            with patch("content_platform.publishers.subprocess.run", side_effect=fake_run):
                result = publisher.deliver(
                    {
                        "id": "job9",
                        "title": "T",
                        "body": "B",
                        "platform_payload": {"kind": "video", "title": "Title", "caption": "Caption", "hashtags": ["#AI"]},
                        "artifacts": [{"kind": "video", "path": str(video)}],
                    },
                    "bilibili",
                )
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "drafted")
        self.assertEqual(calls[0][2:5], ["bilibili", "check", "--account"])
        self.assertIn("--schedule", calls[1])


if __name__ == "__main__":
    unittest.main()
