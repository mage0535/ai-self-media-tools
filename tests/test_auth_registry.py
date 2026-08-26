import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.auth_registry import cookie_inventory, resolve_cookie_file
from content_platform.health_refresh import classify_platform_health
from content_platform.publishers import build_publisher


class CookieRegistryTests(unittest.TestCase):
    def test_resolves_cookie_from_fallback_search_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cookie = root / "zhihu_main.json"
            cookie.write_text(json.dumps([{"name": "z_c0", "value": "present"}]), encoding="utf-8")
            with patch("content_platform.auth_registry.DEFAULT_SEARCH_DIRS", [str(root)]):
                resolved = resolve_cookie_file("zhihu", "main", "")
        self.assertEqual(resolved, cookie)

    def test_inventory_reports_status_without_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "juejin_main.json").write_text(json.dumps([{"name": "sessionid", "value": "secret-value"}]), encoding="utf-8")
            with patch("content_platform.auth_registry.DEFAULT_SEARCH_DIRS", [str(root)]):
                report = cookie_inventory(["juejin"])
        row = report["platforms"]["juejin"]
        self.assertTrue(row["valid"])
        self.assertEqual(row["cookie_count"], 1)
        self.assertNotIn("secret-value", json.dumps(report))

    def test_health_refresh_uses_auth_registry_search_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "juejin_main.json").write_text(json.dumps([{"name": "sessionid", "value": "x"}]), encoding="utf-8")
            with patch("content_platform.auth_registry.DEFAULT_SEARCH_DIRS", [str(root)]), patch.dict("os.environ", {"CN_PROXY": "socks5://127.0.0.1:1080"}):
                result = classify_platform_health("juejin", {"type": "juejin-api", "account": "main", "cookie_dir": str(root / "missing")})
        self.assertTrue(result["can_publish_now"])
        self.assertIn("cookie present", result["reason"])

    def test_build_publisher_supports_juejin_and_zhihu_types(self):
        config = {
            "publishers": {
                "platforms": {
                    "juejin": {"type": "juejin-api", "account": "main"},
                    "zhihu": {"type": "zhihu-playwright", "account": "main"},
                }
            }
        }
        self.assertEqual(type(build_publisher("juejin", config, "/tmp")).__name__, "JuejinPublisher")
        self.assertEqual(type(build_publisher("zhihu", config, "/tmp")).__name__, "ZhihuPublisher")

    def test_domestic_article_publishers_follow_cn_proxy(self):
        from content_platform.publishers import build_publisher
        config = {"publishers": {"platforms": {"juejin": {"type": "juejin-api"}, "zhihu": {"type": "zhihu-playwright"}}}}
        with patch.dict("os.environ", {"CN_PROXY": "socks5://127.0.0.1:2080"}, clear=False):
            assert build_publisher("juejin", config, "/tmp").proxy.endswith(":2080")
            assert build_publisher("zhihu", config, "/tmp").proxy.endswith(":2080")


if __name__ == "__main__":
    unittest.main()
