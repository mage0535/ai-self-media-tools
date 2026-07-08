import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

from content_platform.admin_server import make_admin_server
from content_platform.store import Store


class AdminServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "state.db"
        self.store = Store(self.db_path)
        self.store.init()
        job = self.store.create_job("Automation visuals", ["wechat", "xiaohongshu"])
        self.store.save_draft(job["id"], "Title", "Body", "review", {"hits": []}, draft_meta={"topic_clusters": []})
        self.store.transition(job["id"], {"created"}, "review_required", "draft_ready")
        self.store.save_delivery(job["id"], "wechat", "drafted", "draft-1", "")
        self.store.record_performance(job["id"], "wechat", views=100, likes=10, comments=2, shares=1)

    def tearDown(self):
        self.tmp.cleanup()

    def _open_json(self, opener, url, method="GET", payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with opener.open(request, timeout=5) as response:
            body = response.read().decode()
        return response.status, json.loads(body)

    def test_one_time_launch_login_and_platform_binding_flow(self):
        server = make_admin_server(self.db_path, password="secret123", host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            launch_url = server.launch_url
            login_url = f"http://127.0.0.1:{server.server_port}/api/auth/login?" + launch_url.split("?", 1)[1]
            cookie_jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

            with opener.open(launch_url, timeout=5) as response:
                html = response.read().decode()
            self.assertIn("AI Self-Media Control Center", html)

            status, logged_in = self._open_json(opener, login_url, method="POST", payload={"password": "secret123"})
            self.assertEqual(status, 200)
            self.assertTrue(logged_in["ok"])

            overview_url = f"http://127.0.0.1:{server.server_port}/api/overview"
            status, overview = self._open_json(opener, overview_url)
            self.assertEqual(status, 200)
            self.assertIn("platforms", overview)
            self.assertIn("charts", overview)

            bind_url = f"http://127.0.0.1:{server.server_port}/api/platforms/wechat/bindings"
            status, binding = self._open_json(
                opener,
                bind_url,
                method="POST",
                payload={
                    "display_name": "Main WeChat",
                    "account_key": "wechat-main",
                    "auth_type": "manual",
                    "status": "pending",
                    "credentials_ref": "WECHAT_APP_ID / WECHAT_APP_SECRET",
                    "notes": "draft-first",
                    "enabled": True,
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(binding["display_name"], "Main WeChat")

            platform_url = f"http://127.0.0.1:{server.server_port}/api/platforms/wechat"
            status, platform_detail = self._open_json(opener, platform_url)
            self.assertEqual(status, 200)
            self.assertEqual(platform_detail["platform"]["key"], "wechat")
            self.assertTrue(platform_detail["bindings"])
            self.assertIn("readiness", platform_detail)
            self.assertIn("llm_analysis", platform_detail)

            with self.assertRaises(Exception):
                self._open_json(urllib.request.build_opener(), login_url, method="POST", payload={"password": "secret123"})
        finally:
            server.shutdown()
            server.server_close()

    def test_task_center_and_task_actions_round_trip(self):
        server = make_admin_server(self.db_path, password="secret123", host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            launch_url = server.launch_url
            login_url = f"http://127.0.0.1:{server.server_port}/api/auth/login?" + launch_url.split("?", 1)[1]
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            opener.open(launch_url, timeout=5).read()
            self._open_json(opener, login_url, method="POST", payload={"password": "secret123"})

            tasks_url = f"http://127.0.0.1:{server.server_port}/api/tasks"
            status, tasks = self._open_json(opener, tasks_url)
            self.assertEqual(status, 200)
            self.assertTrue(tasks["tasks"])
            task_id = tasks["tasks"][0]["id"]

            detail_url = f"http://127.0.0.1:{server.server_port}/api/tasks/{task_id}"
            status, detail = self._open_json(opener, detail_url)
            self.assertEqual(status, 200)
            self.assertIn("draft_versions", detail)
            self.assertIn("platform_payloads", detail)
            self.assertIn("comparisons", detail)

            approve_url = f"http://127.0.0.1:{server.server_port}/api/tasks/{task_id}/approve"
            status, approved = self._open_json(opener, approve_url, method="POST", payload={"actor": "admin", "note": "checked"})
            self.assertEqual(status, 200)
            self.assertEqual(approved["state"], "approved")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
