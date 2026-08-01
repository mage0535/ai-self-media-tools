import subprocess
import tempfile
from pathlib import Path

from scripts.release_bundle import export_bundle


def test_release_bundle_exports_only_publish_safe_tracked_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        target = Path(tmp) / "bundle"
        root.mkdir()
        (root / "content_platform").mkdir()
        (root / "content_platform" / "__init__.py").write_text("", encoding="utf-8")
        (root / "README.md").write_text("public docs", encoding="utf-8")
        (root / "data").mkdir()
        (root / "data" / "state.db").write_bytes(b"private-db")
        (root / ".codex-server-runtime").mkdir()
        (root / ".codex-server-runtime" / "cookie.json").write_text("private", encoding="utf-8")
        (root / "config.json").write_text("private config", encoding="utf-8")

        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "README.md", "content_platform/__init__.py"], cwd=root, check=True, capture_output=True)

        result = export_bundle(root, target)

        assert result["ok"] is True
        assert (target / "README.md").is_file()
        assert (target / "content_platform" / "__init__.py").is_file()
        assert not (target / "data").exists()
        assert not (target / ".codex-server-runtime").exists()
        assert not (target / "config.json").exists()
