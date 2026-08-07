"""Tests for scripts/zhihu_pin_promotion.py CLI entry."""

import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts" / "zhihu_pin_promotion.py"


def _job_file(tmp_path):
    path = tmp_path / "zhihu_job.json"
    path.write_text(
        json.dumps(
            {
                "title": "I used AI to write tests for 30 days: four real traps",
                "topic": "AI test automation",
                "body": (
                    "Thirty days ago I still wrote every unit test by hand. "
                    "After I gave the first draft to AI, the first week failed because "
                    "nobody had written acceptance criteria."
                ),
                "strategy_brief": {
                    "reader_payoff": "a practical checklist for deciding which test work can be automated"
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_cli(job_file, *args, timeout=60):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(job_file), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


class TestPinPromotionCli:
    def test_review_mode_outputs_validation_without_publishing(self, tmp_path):
        proc = _run_cli(_job_file(tmp_path), "--url", "https://zhuanlan.zhihu.com/p/X")

        assert proc.returncode == 0, proc.stderr[-300:]
        assert "Zhihu companion pin review draft" in proc.stdout
        assert "Validation:" in proc.stdout
        assert '"passed": true' in proc.stdout
        assert "Review this draft before adding --publish" in proc.stdout

    def test_review_mode_does_not_copy_article_opening(self, tmp_path):
        proc = _run_cli(_job_file(tmp_path), "--url", "https://zhuanlan.zhihu.com/p/X")

        assert "Thirty days ago I still wrote every unit test by hand" not in proc.stdout

    def test_publish_mode_without_url_is_blocked_before_adapter(self, tmp_path):
        proc = _run_cli(_job_file(tmp_path), "--publish", timeout=90)

        assert proc.returncode == 2
        assert "pin_publish_requires_visible_article_url" in proc.stderr
        assert "Traceback" not in proc.stderr
