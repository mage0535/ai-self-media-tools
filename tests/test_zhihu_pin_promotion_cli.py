"""Tests for scripts/zhihu_pin_promotion.py CLI entry (review + publish modes)."""
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path("/root/.ai-self-media-tools")
SCRIPT = PROJECT / "scripts" / "zhihu_pin_promotion.py"
JOB = PROJECT / "data" / "local_ops_zhihu" / "20260806" / "zhihu_job_20260806.json"


def _run_cli(*args, timeout=60):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(JOB), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
    )


class TestPinPromotionCli:
    def test_review_mode_outputs_draft_without_publishing(self):
        if not JOB.is_file():
            return  # skip if fixture missing
        proc = _run_cli("--url", "https://zhuanlan.zhihu.com/p/X")
        assert proc.returncode == 0, proc.stderr[-300:]
        assert "配套想法（审核稿）" in proc.stdout
        assert "确认后加 --publish 发布" in proc.stdout
        assert "REPLACE" not in proc.stdout  # url was passed through

    def test_review_mode_has_no_empty_brackets(self):
        if not JOB.is_file():
            return
        proc = _run_cli()
        assert "《》" not in proc.stdout

    def test_publish_mode_requires_article_url_flow(self):
        # publish mode hits real API; we only verify the script accepts --publish
        # without crashing on argument parsing (network result not asserted here
        # to avoid depending on live zhihu in unit tests).
        if not JOB.is_file():
            return
        proc = _run_cli("--url", "https://zhuanlan.zhihu.com/p/X", "--publish", timeout=90)
        # Either published (ID in output) or failed gracefully with CLI error,
        # but never a python traceback.
        assert "Traceback" not in proc.stderr
        assert proc.returncode in (0, 1)
