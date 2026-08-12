import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.performance_collectors import collect_platform_metrics, collect_with_hermes_platform_scraper, _browser_backend_signal, _playwright_state_file
from content_platform.performance_collectors import _probe_browser_backend_route
from content_platform.performance_collectors import _extract_public_metrics


class PerformanceCollectorTests(unittest.TestCase):
    def test_public_metric_parser_handles_chinese_labels_and_units(self):
        html = "总用户数 43 昨日阅读 1,867 昨日分享 35 粉丝 1.2万 获赞 3.02万 收藏 88"

        metrics = _extract_public_metrics(html)

        self.assertEqual(metrics["followers"], 43)
        self.assertEqual(metrics["views"], 1867)
        self.assertEqual(metrics["shares"], 35)
        self.assertEqual(metrics["likes"], 30200)
        self.assertEqual(metrics["saves"], 88)

    def test_public_metric_parser_handles_kuaishou_creator_overview_totals(self):
        text = "数据概览 播放量 昨日 +239 3,369 点赞量 昨日 +3 23 净增粉丝量 昨日 +2 13 评论量 昨日 +1 9 分享量 昨日 +0 0"

        metrics = _extract_public_metrics(text)

        self.assertEqual(metrics["views"], 3369)
        self.assertEqual(metrics["likes"], 23)
        self.assertEqual(metrics["followers"], 13)
        self.assertEqual(metrics["comments"], 9)
        self.assertEqual(metrics["shares"], 0)

    def test_public_metric_parser_handles_zhihu_creator_analytics(self):
        text = "数据总览 流量 阅读总量 401 今日 6 播放总量 0 今日 0 互动 赞同总量 3 今日 0 评论总量 12 今日 0 收藏总量 9 今日 0 分享总量 1 今日 0 关注者总数 1"

        metrics = _extract_public_metrics(text)

        self.assertEqual(metrics["views"], 401)
        self.assertEqual(metrics["likes"], 3)
        self.assertEqual(metrics["comments"], 12)
        self.assertEqual(metrics["saves"], 9)
        self.assertEqual(metrics["shares"], 1)
        self.assertEqual(metrics["followers"], 1)

    def test_browser_backend_snapshot_marks_account_scope_and_requires_content_evidence(self):
        metrics = _extract_public_metrics("阅读总量 401 赞同总量 3 评论总量 12")

        self.assertEqual(metrics["extra_metrics"]["metric_scope"], "account_snapshot")
        self.assertFalse(metrics["extra_metrics"]["strategy_eligible"])

    def test_public_metric_parser_ignores_unreasonable_page_ids(self):
        text = "浏览 71 点赞 63884588199 收藏 63884588199 评论 1"

        metrics = _extract_public_metrics(text)

        self.assertEqual(metrics["views"], 71)
        self.assertEqual(metrics["comments"], 1)
        self.assertNotIn("likes", metrics)
        self.assertNotIn("saves", metrics)

    def test_collects_youtube_and_bilibili_account_snapshots(self):
        def fetch(url, timeout=15):
            if "youtube.com" in url:
                return '{"subscriberCountText":"8 subscribers","videoCountText":"227 videos","viewCountText":"11,016 views"}'
            return json.dumps({"code": 0, "data": {"card": {"name": "Magic", "fans": 12, "videos": 3, "likes": 44}}})

        report = collect_platform_metrics(
            ["youtube", "bilibili"],
            {
                "youtube": {"channel_url": "https://www.youtube.com/channel/test/about"},
                "bilibili": {"mid": "123"},
            },
            fetcher=fetch,
        )

        self.assertEqual(report["platforms"]["youtube"]["status"], "ok")
        self.assertEqual(report["platforms"]["youtube"]["account_metrics"]["subscribers"], 8)
        self.assertEqual(report["platforms"]["bilibili"]["account_metrics"]["fans"], 12)
        self.assertFalse(report["platforms"]["youtube"]["account_metrics"]["extra_metrics"]["strategy_eligible"])
        self.assertFalse(report["platforms"]["bilibili"]["account_metrics"]["extra_metrics"]["strategy_eligible"])

    def test_tiktok_metrics_api_adapter_collects_growth_metrics(self):
        def http_json(method, url, *, params=None, data=None, headers=None, timeout=15):
            self.assertEqual(method, "GET")
            self.assertEqual(url, "https://metrics.example/tiktok")
            self.assertEqual(headers["Authorization"], "Bearer test-token")
            return {
                "data": {"followers": 9},
                "videos": [
                    {"video_views": 100, "like_count": 8, "comment_count": 2, "share_count": 1},
                    {"video_views": 40, "like_count": 3, "favorite_count": 4},
                ],
            }

        with patch.dict("os.environ", {"TIKTOK_METRICS_API_TOKEN": "test-token"}):
            report = collect_platform_metrics(
                ["tiktok"],
                {"tiktok": {"api_url": "https://metrics.example/tiktok"}},
                http_json=http_json,
            )

        metrics = report["platforms"]["tiktok"]["account_metrics"]
        self.assertEqual(report["platforms"]["tiktok"]["status"], "ok")
        self.assertEqual(metrics["views"], 140)
        self.assertEqual(metrics["likes"], 11)
        self.assertEqual(metrics["comments"], 2)
        self.assertEqual(metrics["shares"], 1)
        self.assertEqual(metrics["saves"], 4)
        self.assertEqual(metrics["followers"], 9)
        self.assertEqual(metrics["extra_metrics"]["metric_source"], "tiktok_metrics_api")
        self.assertTrue(metrics["extra_metrics"]["strategy_eligible"])

    def test_tiktok_empty_content_list_is_not_strategy_eligible(self):
        report = collect_platform_metrics(
            ["tiktok"],
            {"tiktok": {"api_url": "https://metrics.example/tiktok"}},
            http_json=lambda *args, **kwargs: {"followers": 9, "videos": []},
        )
        extra = report["platforms"]["tiktok"]["account_metrics"]["extra_metrics"]
        self.assertEqual(extra["metric_scope"], "account_snapshot")
        self.assertFalse(extra["strategy_eligible"])

    def test_marks_backend_only_platforms_as_export_required(self):
        report = collect_platform_metrics(["wechat", "kuaishou", "shipinhao", "xiaohongshu", "douyin"], {}, fetcher=lambda *_: "")

        self.assertEqual(report["platforms"]["wechat"]["status"], "backend_export_required")
        self.assertIn("performance-import", report["platforms"]["kuaishou"]["next_action"])

    def test_writes_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "collect.json"
            report = collect_platform_metrics(["youtube"], {}, output=output, fetcher=lambda *_: "")
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["platforms"]["youtube"]["status"], report["platforms"]["youtube"]["status"])

    def test_hermes_platform_scraper_output_is_normalized(self):
        def runner(command):
            return (
                0,
                json.dumps(
                    {
                        "youtube": {"subscribers": 8, "videos": 227, "views": 11016},
                        "bilibili": {"fans": 0, "videos": 0, "likes": 0},
                        "twitter": {"followers": 7, "following": 91},
                    }
                ),
                "",
            )

        report = collect_with_hermes_platform_scraper(["youtube", "bilibili", "twitter"], script_path="/tmp/platform_scraper.py", runner=runner)

        self.assertEqual(report["platforms"]["youtube"]["status"], "ok")
        self.assertEqual(report["platforms"]["youtube"]["account_metrics"]["subscribers"], 8)
        self.assertEqual(report["platforms"]["twitter"]["account_metrics"]["followers"], 7)

    def test_hermes_platform_scraper_accepts_wrapped_platforms_output(self):
        def runner(command):
            return (
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "platforms": {
                            "youtube": {"status": "ok", "account_metrics": {"subscribers": 8}},
                            "bilibili": {"status": "ok", "account_metrics": {"fans": 0, "videos": 12}},
                        },
                    }
                ),
                "",
            )

        report = collect_with_hermes_platform_scraper(["youtube", "bilibili"], script_path="/tmp/platform_scraper.py", runner=runner)

        self.assertEqual(report["platforms"]["youtube"]["status"], "ok")
        self.assertEqual(report["platforms"]["youtube"]["account_metrics"]["subscribers"], 8)
        self.assertEqual(report["platforms"]["bilibili"]["account_metrics"]["videos"], 12)

    def test_bilibili_cookie_info_file_collects_authenticated_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "bilibili.json"
            cookie_file.write_text(
                json.dumps({"cookie_info": {"DedeUserID": "123", "SESSDATA": "redacted", "bili_jct": "redacted"}}),
                encoding="utf-8",
            )

            def fetch(url, timeout=15, headers=None):
                if "nav" in url:
                    return json.dumps({"code": 0, "data": {"isLogin": True, "mid": 123}})
                self.assertIn("Cookie", headers or {})
                return json.dumps({"code": 0, "data": {"card": {"name": "wordMagic", "fans": 0, "attention": 1}, "archive_count": 12, "like_num": 51}})

            report = collect_platform_metrics(["bilibili"], {"bilibili": {"cookie_file": str(cookie_file)}}, fetcher=fetch)

            self.assertEqual(report["platforms"]["bilibili"]["status"], "ok")
            self.assertEqual(report["platforms"]["bilibili"]["account_metrics"]["videos"], 12)
            self.assertEqual(report["platforms"]["bilibili"]["account_metrics"]["likes"], 51)

    def test_wechat_datacube_48001_reports_permission_blocked(self):
        def http_json(method, url, *, params=None, data=None, headers=None, timeout=15):
            if "cgi-bin/token" in url:
                return {"access_token": "redacted"}
            return {"errcode": 48001, "errmsg": "api unauthorized"}

        report = collect_platform_metrics(
            ["wechat"],
            {"wechat": {"app_id": "configured", "app_secret": "configured", "datacube": True}},
            http_json=http_json,
        )

        self.assertEqual(report["platforms"]["wechat"]["status"], "api_permission_blocked")
        self.assertIn("backend", report["platforms"]["wechat"]["next_action"])

    def test_wechat_datacube_blocked_uses_backend_browser_when_state_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "wechat_state.json"
            state.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

            def http_json(method, url, *, params=None, data=None, headers=None, timeout=15):
                if "cgi-bin/token" in url:
                    return {"access_token": "redacted"}
                return {"errcode": 48001, "errmsg": "api unauthorized"}

            backend = {
                "status": "backend_signal",
                "account_metrics": {"views": 123, "followers": 4},
                "reason": "visible backend metrics",
            }
            with patch("content_platform.performance_collectors._browser_backend_signal", return_value=backend):
                report = collect_platform_metrics(
                    ["wechat"],
                    {"wechat": {"app_id": "configured", "app_secret": "configured", "datacube": True, "state_file": str(state)}},
                    http_json=http_json,
                )

        result = report["platforms"]["wechat"]
        self.assertEqual(result["status"], "backend_signal")
        self.assertEqual(result["datacube_status"], "api_permission_blocked")
        self.assertEqual(result["account_metrics"]["views"], 123)

    def test_wechat_backend_probe_failure_is_reported_when_datacube_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "wechat_state.json"
            state.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

            def http_json(method, url, *, params=None, data=None, headers=None, timeout=15):
                if "cgi-bin/token" in url:
                    return {"access_token": "redacted"}
                return {"errcode": 48001, "errmsg": "api unauthorized"}

            backend = {"status": "login_required_or_verification", "reason": "creator backend requires login or verification"}
            with patch("content_platform.performance_collectors._browser_backend_signal", return_value=backend):
                report = collect_platform_metrics(
                    ["wechat"],
                    {"wechat": {"app_id": "configured", "app_secret": "configured", "datacube": True, "state_file": str(state)}},
                    http_json=http_json,
                )

        result = report["platforms"]["wechat"]
        self.assertEqual(result["status"], "api_permission_blocked")
        self.assertEqual(result["backend_probe_status"], "login_required_or_verification")

    def test_wechat_datacube_can_load_private_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "wechat.env"
            env_file.write_text("WECHAT_APP_ID=configured\nWECHAT_APP_SECRET=configured\n", encoding="utf-8")

            def http_json(method, url, *, params=None, data=None, headers=None, timeout=15):
                if "cgi-bin/token" in url:
                    self.assertEqual(params["appid"], "configured")
                    return {"access_token": "redacted"}
                return {"list": [{"ref_date": "2026-08-03", "int_page_read_count": 10}]}

            report = collect_platform_metrics(["wechat"], {"wechat": {"datacube": True, "env_file": str(env_file)}}, http_json=http_json)

            self.assertEqual(report["platforms"]["wechat"]["status"], "ok")
            self.assertEqual(report["platforms"]["wechat"]["metrics"]["article_summary"]["count"], 1)

    def test_login_state_platform_reports_missing_state_file(self):
        report = collect_platform_metrics(["douyin"], {"douyin": {"state_file": "/tmp/does-not-exist.json"}}, fetcher=lambda *_: "")

        self.assertEqual(report["platforms"]["douyin"]["status"], "login_required")

    def test_backend_platform_uses_public_profile_signal_when_login_is_missing(self):
        html = """
        <html><head><title>猫咪治愈日记</title></head>
        <body>粉丝 1,234 作品 56 获赞 7,890 播放 12,345 收藏 67</body></html>
        """
        report = collect_platform_metrics(
            ["douyin"],
            {"douyin": {"state_file": "/tmp/does-not-exist.json", "public_profile_url": "https://example.com/douyin/user"}},
            fetcher=lambda *_args, **_kwargs: html,
        )

        result = report["platforms"]["douyin"]
        self.assertEqual(result["status"], "public_signal")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["account_metrics"]["followers"], 1234)
        self.assertEqual(result["account_metrics"]["likes"], 7890)
        self.assertEqual(result["account_metrics"]["works"], 56)

    def test_public_profile_signal_reports_unavailable_when_no_numbers_visible(self):
        report = collect_platform_metrics(
            ["xiaohongshu"],
            {"xiaohongshu": {"public_profile_url": "https://example.com/xhs/user"}},
            fetcher=lambda *_args, **_kwargs: "<html><title>Blocked</title><body>login</body></html>",
        )

        self.assertEqual(report["platforms"]["xiaohongshu"]["status"], "public_signal_unavailable")

    def test_public_profile_signal_parses_compact_numbers(self):
        body = "\u7c89\u4e1d 1.2\u4e07 \u83b7\u8d5e 34.5k views 2.1M"
        report = collect_platform_metrics(
            ["douyin"],
            {"douyin": {"public_profile_url": "https://example.com/douyin/user"}},
            fetcher=lambda *_args, **_kwargs: f"<html><body>{body}</body></html>",
        )

        metrics = report["platforms"]["douyin"]["account_metrics"]
        self.assertEqual(metrics["followers"], 12000)
        self.assertEqual(metrics["likes"], 34500)
        self.assertEqual(metrics["views"], 2100000)

    def test_backend_platform_keeps_export_required_when_no_state_file(self):
        report = collect_platform_metrics(["kuaishou"], {"kuaishou": {}}, fetcher=lambda *_args, **_kwargs: "")

        self.assertEqual(report["platforms"]["kuaishou"]["status"], "backend_export_required")

    def test_cookie_list_is_converted_to_playwright_storage_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.json"
            cookie_file.write_text(
                json.dumps(
                    [
                        {
                            "name": "sid",
                            "value": "redacted",
                            "domain": ".douyin.com",
                            "path": "/",
                            "expirationDate": 1999999999,
                            "httpOnly": True,
                            "secure": True,
                            "sameSite": "lax",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            state_file = Path(_playwright_state_file(str(cookie_file)))
            data = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertIn("cookies", data)
        self.assertEqual(data["cookies"][0]["name"], "sid")
        self.assertEqual(data["cookies"][0]["sameSite"], "Lax")

    def test_backend_browser_direct_diagnostic_route_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            state.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
            calls = []

            def fake_probe(pw, state_file, target, config, route_name, proxy_url, diagnostic_only):
                calls.append((route_name, proxy_url, diagnostic_only))
                if route_name == "direct_diagnostic":
                    return {"status": "backend_signal", "account_metrics": {"views": 1}, "reason": "ok"}
                return {"status": "browser_probe_failed", "reason": "ERR_NO_SUPPORTED_PROXIES"}

            class FakeSync:
                def __enter__(self):
                    return object()

                def __exit__(self, exc_type, exc, tb):
                    return False

            fake_playwright = types.ModuleType("playwright")
            fake_sync_api = types.ModuleType("playwright.sync_api")
            fake_sync_api.sync_playwright = lambda: FakeSync()
            with patch.dict(
                sys.modules,
                {"playwright": fake_playwright, "playwright.sync_api": fake_sync_api},
            ), patch.dict("os.environ", {"CN_PROXY": "socks5://127.0.0.1:1080"}, clear=False), patch(
                "content_platform.performance_collectors._probe_browser_backend_route", side_effect=fake_probe
            ):
                result = _browser_backend_signal("douyin", {"state_file": str(state), "diagnose_direct_without_proxy": True})

        self.assertEqual(result["status"], "backend_signal")
        self.assertEqual([item[0] for item in calls], ["CN_PROXY", "direct_diagnostic"])
        self.assertTrue(calls[1][2])

    def test_backend_browser_route_normalizes_socks5h_for_playwright(self):
        launched = {}

        class FakePage:
            url = "https://example.test"

            def goto(self, *args, **kwargs):
                return None

            def wait_for_timeout(self, *args, **kwargs):
                return None

            def locator(self, *args, **kwargs):
                return self

            def inner_text(self, *args, **kwargs):
                return "阅读总量 123 点赞总量 4"

            def close(self):
                return None

        class FakeContext:
            def new_page(self):
                return FakePage()

            def close(self):
                return None

        class FakeBrowser:
            def new_context(self, **kwargs):
                return FakeContext()

            def close(self):
                return None

        class FakeChromium:
            def launch(self, **kwargs):
                launched.update(kwargs)
                return FakeBrowser()

        fake_pw = type("FakePlaywright", (), {"chromium": FakeChromium()})()
        result = _probe_browser_backend_route(
            fake_pw,
            state_file="state.json",
            target={"urls": ["https://example.test"]},
            config={"timeout_ms": 1000, "settle_ms": 1},
            route_name="CN_PROXY",
            proxy_url="socks5h://127.0.0.1:1080",
            diagnostic_only=False,
        )

        self.assertEqual(result["status"], "backend_signal")
        self.assertEqual(launched["proxy"]["server"], "socks5://127.0.0.1:1080")

    def test_metrics_file_collects_shipinhao_eval_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics_file = Path(tmp) / "shipinhao_eval.json"
            metrics_file.write_text(
                json.dumps(
                    {
                        "videos": [
                            {"播放": 10, "喜欢": 1, "评论": 2, "分享": 3, "关注": 4},
                            {"播放": 20, "喜欢": 2, "评论": 0, "分享": 1, "关注": 0},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = collect_platform_metrics(["shipinhao"], {"shipinhao": {"metrics_file": str(metrics_file)}})
        metrics = report["platforms"]["shipinhao"]["account_metrics"]
        self.assertEqual(report["platforms"]["shipinhao"]["status"], "ok")
        self.assertEqual(metrics["views"], 30)
        self.assertEqual(metrics["likes"], 3)
        self.assertEqual(metrics["comments"], 2)
        self.assertEqual(metrics["shares"], 4)
        self.assertEqual(metrics["followers"], 4)
        self.assertEqual(metrics["works"], 2)
        self.assertEqual(metrics["extra_metrics"]["metric_source"], "metrics_file")
        self.assertEqual(metrics["extra_metrics"]["metric_scope"], "account_snapshot")
        self.assertFalse(metrics["extra_metrics"]["strategy_eligible"])

    def test_metrics_file_with_content_identifiers_is_strategy_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics_file = Path(tmp) / "metrics.json"
            metrics_file.write_text(
                json.dumps({"videos": [{"video_id": "v-1", "title": "Example", "views": 10, "likes": 1}]}),
                encoding="utf-8",
            )
            report = collect_platform_metrics(["shipinhao"], {"shipinhao": {"metrics_file": str(metrics_file)}})
        extra = report["platforms"]["shipinhao"]["account_metrics"]["extra_metrics"]
        self.assertEqual(extra["metric_scope"], "content_aggregate")
        self.assertTrue(extra["strategy_eligible"])


if __name__ == "__main__":
    unittest.main()
