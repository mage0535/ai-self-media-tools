import unittest
import tempfile
from pathlib import Path
import os
import subprocess
from unittest.mock import patch

from content_platform.project_audit import audit_project


class ProjectAuditTests(unittest.TestCase):
    def test_ignores_local_runtime_mirrors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / ".codex-server-runtime" / "runtime" / "root" / ".hermes"
            runtime.mkdir(parents=True)
            (runtime / ".env").write_text("OPENAI_API_KEY=dummy", encoding="utf-8")
            codex_tmp = root / ".codex-tmp"
            codex_tmp.mkdir()
            private_path = "/" + "root/" + ".hermes/private"
            (codex_tmp / "scratch.md").write_text(private_path, encoding="utf-8")
            codex_private = root / ".codex" / "attachments"
            codex_private.mkdir(parents=True)
            (codex_private / "pasted-text.txt").write_text("cookie=sessionid_private", encoding="utf-8")
            (root / "README.md").write_text("public docs", encoding="utf-8")

            result = audit_project(root)

        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["scanned_files"], 1)

    def test_flags_root_level_media_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "publish_screenshot.png").write_bytes(b"png")

            result = audit_project(root)

        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"][0]["reason"], "root_level_media_evidence")

    def test_flags_active_tree_backup_source_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "content_platform"
            package.mkdir()
            (package / "publishers.py.bak.v3").write_text("legacy publisher copy", encoding="utf-8")

            result = audit_project(root)

        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"][0]["reason"], "forbidden_filename_pattern")

    def test_ignores_secure_gitignored_runtime_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text(".env.*\n", encoding="utf-8")
            runtime_env = root / ".env.local"
            runtime_env.write_text("WRITER_API_KEY=private-value", encoding="utf-8")
            os.chmod(runtime_env, 0o600)

            with patch("content_platform.project_audit._owner_only_permissions", return_value=True):
                result = audit_project(root)

        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])

    def test_flags_env_file_when_not_gitignored_or_not_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_env = root / ".env.local"
            runtime_env.write_text("WRITER_API_KEY=private-value", encoding="utf-8")
            os.chmod(runtime_env, 0o644)

            result = audit_project(root)

        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"][0]["reason"], "forbidden_filename_pattern")


if __name__ == "__main__":
    unittest.main()
