import tempfile
import unittest
from pathlib import Path

from content_platform.admin_store import AdminStore
from content_platform.store import Store


class AdminStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "state.db"
        self.store = Store(db_path)
        self.store.init()
        self.admin = AdminStore(db_path)
        self.admin.init()

    def tearDown(self):
        self.tmp.cleanup()

    def test_binding_round_trip_and_toggle(self):
        created = self.admin.upsert_binding(
            "wechat",
            {
                "display_name": "Main WeChat",
                "account_key": "wechat-main",
                "auth_type": "manual",
                "status": "pending",
                "credentials_ref": "WECHAT_APP_ID / WECHAT_APP_SECRET",
                "notes": "draft-first",
                "enabled": True,
            },
        )
        self.assertEqual(created["platform"], "wechat")
        listed = self.admin.list_bindings("wechat")
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0]["enabled"])

        toggled = self.admin.toggle_binding(created["id"], False)
        self.assertFalse(toggled["enabled"])

    def test_mark_binding_check_updates_status(self):
        binding = self.admin.upsert_binding(
            "xiaohongshu",
            {
                "display_name": "XHS Creator",
                "account_key": "xhs-creator",
                "auth_type": "cookie",
                "status": "pending",
                "credentials_ref": "cookies/xiaohongshu",
                "notes": "",
                "enabled": True,
            },
        )
        checked = self.admin.mark_binding_check(binding["id"], "connected", "")
        self.assertEqual(checked["status"], "connected")
        self.assertTrue(checked["last_checked_at"])


if __name__ == "__main__":
    unittest.main()
