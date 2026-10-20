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
        (root / "content_platform" / "prompt_compiler.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "README.md").write_text("public docs", encoding="utf-8")
        (root / "data").mkdir()
        (root / "data" / "state.db").write_bytes(b"private-db")
        (root / ".codex-server-runtime").mkdir()
        (root / ".codex-server-runtime" / "cookie.json").write_text("private", encoding="utf-8")
        (root / "config.json").write_text("private config", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "run_platform_hot_refresh.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (root / "scripts" / "run_wechat_blowup_refresh.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (root / "config").mkdir()
        (root / "config" / "platform_hot_evidence_sources.json").write_text("{}\n", encoding="utf-8")
        (root / "config" / "platform_intelligence_capabilities_v1.json").write_text("{}\n", encoding="utf-8")
        (root / "config" / "growth_strategy_distilled_per_account.md").write_text(
            "canonical AI lane strategy\n", encoding="utf-8"
        )
        (root / "config" / "growth_strategy_douyin_ai_20260821.md").write_text(
            "canonical Douyin AI lane strategy\n", encoding="utf-8"
        )
        # A dirty production workspace may contain unsafe runtime material that
        # is not Git-controlled. It must neither enter the bundle nor block a
        # bundle composed solely of safe tracked files.
        (root / "runtime_cookie_dump.txt").write_text("OPENAI_API_KEY=" + "x" * 16, encoding="utf-8")

        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "README.md", "content_platform/__init__.py"], cwd=root, check=True, capture_output=True)

        result = export_bundle(root, target)

        assert result["ok"] is True
        assert (target / "README.md").is_file()
        assert (target / "content_platform" / "__init__.py").is_file()
        assert (target / "content_platform" / "prompt_compiler.py").is_file()
        assert (target / "scripts" / "run_platform_hot_refresh.sh").is_file()
        assert (target / "scripts" / "run_wechat_blowup_refresh.sh").is_file()
        assert (target / "config" / "platform_hot_evidence_sources.json").is_file()
        assert (target / "config" / "platform_intelligence_capabilities_v1.json").is_file()
        assert not (target / "data").exists()
        assert not (target / ".codex-server-runtime").exists()
        assert not (target / "config.json").exists()
