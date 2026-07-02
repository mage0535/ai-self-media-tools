import os
import tempfile
import time
import unittest
from pathlib import Path

from content_platform.resource import ResourceGuard


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_video_is_blocked_below_memory_threshold(self):
        guard = ResourceGuard(self.root, {"min_available_mb": 1024}, probe=lambda: {"available_mb": 512, "disk_used_percent": 20})
        with self.assertRaises(RuntimeError):
            guard.check("video")

    def test_video_lock_is_exclusive(self):
        guard = ResourceGuard(self.root, {}, probe=lambda: {"available_mb": 4096, "disk_used_percent": 20})
        with guard.video_lock():
            with self.assertRaises(RuntimeError):
                with guard.video_lock():
                    pass

    def test_cleanup_removes_only_unprotected_old_files(self):
        old = self.root / "artifacts" / "old.bin"
        kept = self.root / "artifacts" / "kept.bin"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old")
        kept.write_bytes(b"kept")
        past = time.time() - 10 * 86400
        os.utime(old, (past, past))
        os.utime(kept, (past, past))
        result = ResourceGuard(self.root, {}).cleanup({str(kept)}, 7)
        self.assertEqual(result["removed"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(kept.exists())


if __name__ == "__main__":
    unittest.main()

