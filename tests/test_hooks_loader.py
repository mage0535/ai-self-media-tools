"""hooks_loader / pexels_auto_bg / gen_cover 单元测试"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestHooksLoader(unittest.TestCase):
    def test_load_sections(self):
        from content_platform.hooks_loader import load_hooks
        lib = load_hooks()
        self.assertGreaterEqual(len(lib.get("title", [])), 10)
        self.assertGreaterEqual(len(lib.get("opening", [])), 5)

    def test_pick_hooks_platform_filter(self):
        from content_platform.hooks_loader import pick_hooks
        hooks = pick_hooks("douyin", 5)
        self.assertLessEqual(len(hooks), 5)
        self.assertGreater(len(hooks), 0)
        # 每个钩子应有 template 字段
        for h in hooks:
            self.assertTrue(h.get("template"))


if __name__ == "__main__":
    unittest.main()
