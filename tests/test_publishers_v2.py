import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.growth_policy import build_growth_strategy
from content_platform.content_recipe import build_article_recipe, build_knowledge_card_recipe, build_tool_invocation_manifest
from content_platform.preflight_manifest import build_preflight_manifest
from content_platform.tool_selection import build_tool_selection_evidence
from content_platform.publishers import (
    AiToEarnDraftPublisher,
    AiToEarnFlowPublisher,
    AyrsharePublisher,
    DevtoDraftPublisher,
    RedditDraftPublisher,
    SocialAutoUploadPublisher,
    HermesWechatAdapter,
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

    def test_build_publisher_uses_hermes_wechat_adapter_for_wechat_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = build_publisher(
                "wechat",
                {"publishers": {"platforms": {"wechat": {"type": "wechat-draft", "adapter_command": str(Path(tmp) / "missing.py")}}}},
                tmp,
            )
        self.assertIsInstance(publisher, HermesWechatAdapter)

    def test_hermes_wechat_adapter_blocks_incomplete_packet_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = Path(tmp) / "runner.py"
            runner.write_text("raise SystemExit(9)", encoding="utf-8")
            publisher = HermesWechatAdapter(data_dir=tmp, command=str(runner), require_cn_proxy=False)
            result = publisher.deliver({"id": "j1", "title": "T", "body": "B"}, "wechat")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("visual_content_design_policy", result.error)

    def test_hermes_wechat_adapter_blocks_packet_without_wewrite_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = Path(tmp) / "runner.py"
            runner.write_text("raise SystemExit(9)", encoding="utf-8")
            packet = self._complete_wechat_packet()
            packet.pop("tool_invocations")
            publisher = HermesWechatAdapter(data_dir=tmp, command=str(runner), require_cn_proxy=False)
            result = publisher.deliver(packet, "wechat")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("WeWrite llm-write", result.error)

    def test_hermes_wechat_adapter_returns_handoff_when_postcheck_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = Path(tmp) / "runner.py"
            runner.write_text(
                "import argparse,json\n"
                "p=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--output');a=p.parse_args()\n"
                "json.dump({'ok': False, 'status': 'handoff_pending', 'media_id': 'draft-1', 'postcheck': {'passed': False}, 'evidence_path': 'evidence.json'}, open(a.output,'w'))\n",
                encoding="utf-8",
            )
            packet = self._complete_wechat_packet()
            publisher = HermesWechatAdapter(data_dir=tmp, command=str(runner), require_cn_proxy=False)
            result = publisher.deliver(packet, "wechat")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "handoff_pending")
        self.assertEqual(result.external_id, "draft-1")

    def _complete_wechat_packet(self):
        body = "\n\n".join(["practical operating paragraph " * 10 for _ in range(5)])
        section_image_map = [
            {"section": "problem", "image": "01.png", "purpose": "open the pain point", "adjacent_to_text": True},
            {"section": "case", "image": "02.png", "purpose": "show the case", "adjacent_to_text": True},
            {"section": "method", "image": "03.png", "purpose": "explain the steps", "adjacent_to_text": True},
        ]
        embedded_cards = [
            {"section": "problem", "card_type": "step_tutorial", "layout": "timeline", "visual_subject": "matched visual 1", "information_value": "explains adjacent point", "self_check": ["readability", "attraction", "information_density", "visual_match"]},
            {"section": "case", "card_type": "case_map", "layout": "split_panel", "visual_subject": "matched visual 2", "information_value": "explains adjacent point", "self_check": ["readability", "attraction", "information_density", "visual_match"]},
            {"section": "method", "card_type": "checklist", "layout": "big_number", "visual_subject": "matched visual 3", "information_value": "explains adjacent point", "self_check": ["readability", "attraction", "information_density", "visual_match"]},
        ]
        visual_selection = {"selected": "case_story_v1", "ranked_scores": [{"template": "case_story_v1", "score": 80}, {"template": "magazine_grid", "score": 70}], "recent_same_platform_templates": [], "penalties": {}}
        tool_manifest = build_tool_invocation_manifest(
            planned_tools={
                "generator_normalize": "content_platform.generator",
                "preflight_manifest": "content_platform.preflight_manifest",
                "visual_policy": "content_platform.visual_content_policy",
                "knowledge_card_designer": "hermes_skill:content/knowledge-card-designer",
            },
            invocations={
                "generator_normalize": {"status": "ok", "output": "packet"},
                "preflight_manifest": {"status": "ok", "output": "packet.preflight_manifest"},
                "visual_policy": {"status": "ok", "output": "packet.visual_content_policy"},
                "knowledge_card_designer": {"status": "planned_internal", "output": "packet.embedded_knowledge_cards"},
            },
        )
        return {
            "id": "wechat-job",
            "platform": "wechat",
            "title": "WeChat adapter test",
            "body": body,
            "preflight_manifest": {
                "version": "content_preflight_manifest_v1",
                "channel": "wechat",
                "content_type": "long_article",
                "rulebook": {"loaded": True, "path": "config/channel_content_rulebook.json", "channel_rules_loaded": True},
                "strategy": {"source": "hermes_operating_strategy", "result_path": "/ignored-runtime/wechat_strategy.json", "summary": "strategy loaded"},
                **build_preflight_manifest(
                    channel="wechat",
                    content_type="long_article",
                    strategy_source="hermes_operating_strategy",
                    strategy_result_path="/ignored-runtime/wechat_strategy.json",
                    strategy_summary="strategy loaded",
                    selected_topic="WeChat adapter validation",
                    selection_reason="matches lane",
                    content_angle="case-led checklist article",
                    required_assets=["cover", "inline_images", "embedded_knowledge_cards"],
                    source_policy="licensed_or_verified_runtime_assets",
                    quality_gates=["wechat_auto_packet", "asset_license", "draft_batchget_postcheck"],
                    delivery_health_required=True,
                    postcheck_required=True,
                    extra_skills=["content/knowledge-card-designer"],
                ),
            },
            "visual_content_policy": {
                "policy_id": "visual_content_design_policy_v1",
                "skill": "hermes_skill:content/knowledge-card-designer",
                "tool_refs": {
                    "image_generation_engine": "hermes_tool:image_generation_engine",
                    "wechat_theme_renderer": "hermes_tool:wechat_theme_renderer",
                    "wechat_publisher": "hermes_tool:wechat_publisher",
                },
                "wechat_requirements": {"theme_count_required": 109},
            },
            "growth_strategy": build_growth_strategy(["wechat"], "long_article"),
            "opening_hook": "A useful article needs a real promise before it asks readers to spend attention.",
            "hook_type": "reader_payoff",
            "sections": ["problem", "case", "why old way fails", "method", "checklist"],
            "visual_template_selection": visual_selection,
            "strategy_brief": {
                "target_user": "operators", "channel_lane": "AI operations", "topic_basis": "recent delivery failures",
                "click_reason": "avoid repeating a costly publishing mistake", "reader_payoff": "a reusable checklist",
                "chosen_structure": "case-breakdown-method", "content_form": "longform article",
                "seo_geo_intent": "AI operations search and WeChat recommendation intent",
                "selected_theme_reason": "case-led technical operations article",
            },
            "section_image_map": section_image_map,
            "real_scene_background_plan": {
                "required": True, "source_policy": "licensed_or_verified_real_scene_assets",
                "primary_background_kind": "real_scene_photo", "no_css_gradient_primary": True,
                "per_slide_backgrounds": [
                    {"asset_id": "real-bg-1", "asset_type": "photo", "background_kind": "real_scene_photo", "source": "https://licensed.example/1.jpg", "rights_cleared": True, "real_scene": True, "match_reason": "matches", "section": "problem", "sections": ["problem"], "image": "01.png"},
                    {"asset_id": "real-bg-2", "asset_type": "photo", "background_kind": "real_scene_photo", "source": "https://licensed.example/2.jpg", "rights_cleared": True, "real_scene": True, "match_reason": "matches", "section": "case", "sections": ["case"], "image": "02.png"},
                    {"asset_id": "real-bg-3", "asset_type": "photo", "background_kind": "real_scene_photo", "source": "https://licensed.example/3.jpg", "rights_cleared": True, "real_scene": True, "match_reason": "matches", "section": "method", "sections": ["method"], "image": "03.png"},
                ],
            },
            "knowledge_card_plan": {"skill": "hermes_skill:content/knowledge-card-designer", "card_type": "knowledge_summary", "platform": "wechat", "audience": "operators", "visual_scheme": "professional", "typography_hierarchy": "4:2:1", "self_check": ["readability", "attraction", "information_density", "share_or_save_value", "visual_match", "mobile_safe_boundaries"]},
            "embedded_knowledge_cards": embedded_cards,
            "article_recipe": build_article_recipe(
                platform="wechat",
                content_type="long_article",
                title="WeChat adapter test",
                body=body,
                sections=["problem", "case", "why old way fails", "method", "checklist"],
                section_image_map=section_image_map,
                embedded_knowledge_cards=embedded_cards,
                visual_template_selection=visual_selection,
            ),
            "knowledge_card_recipe": build_knowledge_card_recipe(platform="wechat", cards=embedded_cards, content_type="long_article"),
            "tool_invocation_manifest": tool_manifest,
            **build_tool_selection_evidence(
                platform="wechat",
                content_type="long_article",
                content_goal="validate Hermes WeChat adapter packet without bypassing tool selection",
                planned_manifest=tool_manifest,
            ),
            "cover_design": {"visual_subject": "failed schedule checklist", "topic_alignment": "matches promise", "mobile_readable": True, "visual_hierarchy": "title, warning mark, checklist", "template_family": "casebook"},
            "differentiation_dimensions": ["case-led opening", "checklist structure", "warm warning tone"],
            "reader_payoff": "reader can apply a checklist today",
            "concrete_case": "failed scheduled publication diagnosis",
            "actionable_checklist": ["check title", "check cover", "check postcheck"],
            "tool_invocations": {"wewrite": {"status": "used", "commands": [{"name": "run start", "returncode": 0}, {"name": "llm-write", "returncode": 0}], "article_path": "/ignored-runtime/article.md"}},
        }

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

    def test_routing_defaults_send_kuaishou_to_social_auto_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = build_publisher(
                "kuaishou",
                {
                    "publishers": {
                        "routing_defaults": {
                            "enabled": True,
                            "domestic": {"account_name": "example", "project_dir": tmp, "python_bin": "python"},
                        }
                    }
                },
                tmp,
            )

        self.assertIsInstance(publisher, SocialAutoUploadPublisher)
        self.assertEqual(publisher.platform_name, "kuaishou")
        self.assertEqual(publisher.account_name, "example")

    def test_social_auto_upload_auto_schedule_resolves_to_cli_time(self):
        publisher = SocialAutoUploadPublisher(
            platform_name="kuaishou",
            account_name="main",
            project_dir="/tmp/social-auto-upload",
            python_bin="python",
            schedule_at="auto",
            schedule_delay_hours=3,
        )

        self.assertRegex(publisher._schedule_at(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_x_playwright_publisher_is_explicit_cookie_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = build_publisher(
                "twitter",
                {
                    "publishers": {
                        "platforms": {
                            "twitter": {
                                "type": "x-playwright",
                                "account": "main",
                                "cookie_dir": tmp,
                                "live": True,
                            }
                        }
                    }
                },
                tmp,
            )

        self.assertEqual(publisher.__class__.__name__, "XPlaywrightPublisher")

    def test_routing_defaults_send_international_to_manual_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = build_publisher(
                "tiktok",
                {"publishers": {"routing_defaults": {"enabled": True}}},
                tmp,
            )

            result = publisher.deliver({"id": "job7", "title": "T", "body": "B"}, "tiktok")

        self.assertEqual(result.status, "handoff_pending")
        self.assertIn("manual", result.error)

    def test_manual_only_platforms_override_any_auto_publisher_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            for platform in ["douyin", "shipinhao", "tiktok", "xiaohongshu"]:
                publisher = build_publisher(
                    platform,
                    {
                        "publishers": {
                            "platforms": {
                                platform: {
                                    "type": "aitoearn-flow",
                                    "account_id": "acct",
                                    "api_key": "secret",
                                }
                            }
                        }
                    },
                    tmp,
                )
                result = publisher.deliver({"id": "job7", "title": "T", "body": "B"}, platform)

                self.assertEqual(publisher.__class__.__name__, "ManualHandoffPublisher")
                self.assertEqual(result.status, "handoff_pending")
                self.assertIn("manual-only", result.error)

    def test_aitoearn_disabled_platforms_override_draft_and_flow_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ["aitoearn-draft", "aitoearn-flow"]:
                for platform in ["youtube", "tiktok", "twitter", "x", "threads"]:
                    with self.subTest(kind=kind, platform=platform):
                        publisher = build_publisher(
                            platform,
                            {
                                "publishers": {
                                    "platforms": {
                                        platform: {
                                            "type": kind,
                                            "account_id": "acct",
                                            "api_key": "secret",
                                        }
                                    }
                                }
                            },
                            tmp,
                        )
                        result = publisher.deliver({"id": "job7", "title": "T", "body": "B"}, platform)

                        self.assertEqual(publisher.__class__.__name__, "ManualHandoffPublisher")
                        self.assertEqual(result.status, "handoff_pending")
                        self.assertTrue("AiToEarn is disabled" in result.error or "manual-only" in result.error)

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

    def test_reddit_draft_publisher_writes_human_review_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = RedditDraftPublisher(outbox=Path(tmp) / "outbox", default_subreddit="SideProject")
            result = publisher.deliver(
                {
                    "id": "job10",
                    "title": "Launch checklist",
                    "body": "Useful field notes, not a hard sell.",
                    "draft_meta": {"subreddit": "Entrepreneur"},
                },
                "reddit",
            )
            payload = json.loads(Path(result.external_id).read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "review_required")
        self.assertEqual(payload["platform_payload"]["subreddit"], "Entrepreneur")
        self.assertFalse(payload["live_publish"])
        self.assertIn("human review", " ".join(payload["safety_notes"]))

    def test_build_publisher_supports_reddit_draft_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            publisher = build_publisher(
                "reddit",
                {"publishers": {"platforms": {"reddit": {"type": "reddit-draft", "outbox": str(Path(tmp) / "reddit")}}}},
                tmp,
            )
        self.assertIsInstance(publisher, RedditDraftPublisher)


if __name__ == "__main__":
    unittest.main()
