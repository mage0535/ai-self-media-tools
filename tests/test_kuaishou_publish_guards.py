import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class KuaishouPublishGuardTests(unittest.TestCase):
    def test_thumbnail_path_accepts_nested_cover_object(self):
        from scripts import kuaishou_publish_with_postcheck as wrapper

        self.assertEqual(wrapper._thumbnail_path({"cover": {"path": "/tmp/cover.png"}}), "/tmp/cover.png")
        self.assertEqual(wrapper._thumbnail_path({"thumbnail_path": "/tmp/thumb.png"}), "/tmp/thumb.png")

    def test_publish_wrapper_rejects_direct_invocation_without_workflow_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"not-a-real-video")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "platform": "kuaishou",
                        "title": "Guard test",
                        "description": "Guard test description",
                        "tags": ["AI"],
                        "schedule_time": "2026-07-29 12:30",
                        "video_file": str(video),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            for key in ["CONTENT_PLATFORM_OPS_RUNNER", "WORKFLOW_ID", "RUN_ID", "JOB_ID"]:
                env.pop(key, None)

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "kuaishou_publish_with_postcheck.py"), str(manifest)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ops_runner_required", result.stdout)

    def test_skip_preflight_requires_ops_audit_authorization(self):
        from scripts import kuaishou_publish_with_postcheck as wrapper

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"not-a-real-video")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "platform": "kuaishou",
                        "title": "Guard test",
                        "description": "Guard test description",
                        "tags": ["AI"],
                        "schedule_time": "2026-07-29 12:30",
                        "video_file": str(video),
                        "skip_preflight_reason": "historical bypass should not be enough",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "CONTENT_PLATFORM_OPS_RUNNER": "1",
                    "WORKFLOW_ID": "wf_test",
                    "RUN_ID": "run_test",
                    "JOB_ID": "job_test",
                    "KUAISHOU_ALLOW_HISTORICAL_SKIP_PREFLIGHT": "1",
                },
                clear=False,
            ), patch.object(sys, "argv", ["kuaishou_publish_with_postcheck.py", str(manifest), "--skip-preflight"]):
                code = wrapper.main()

        self.assertEqual(code, 2)


class KuaishouPostcheckSemanticsTests(unittest.TestCase):
    # The classifier reads management-page cards (one labelled field per line), not a page text blob.
    MANIFEST = {"title": "Expected title", "description": "Expected description body", "schedule_time": "2026-07-29 12:30"}

    def test_under_review_without_title_or_schedule_is_not_passed(self):
        from scripts import kuaishou_postcheck_manifest as postcheck

        result = postcheck._classify_management_postcheck(
            self.MANIFEST, [{"text": "状态：审核中\n描述：Expected description body"}])

        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "management_postcheck_not_found")

    def test_under_review_with_matching_work_is_a_submitted_review_state(self):
        from scripts import kuaishou_postcheck_manifest as postcheck

        result = postcheck._classify_management_postcheck(
            self.MANIFEST, [{"text": "状态：审核中\n标题：Expected title\n描述：Expected description body", "work_id": "w1"}])

        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "success_under_review")
        self.assertEqual(result["delivery_state"], "under_review")

    def test_publish_wrapper_accepts_a_passing_under_review_postcheck(self):
        from scripts import kuaishou_publish_with_postcheck as wrapper

        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "postcheck.png"
            evidence.write_bytes(b"png")
            work = {"title": "Expected title", "description": "Expected description body", "state": "under_review"}
            report = {"passed": True, "status": "success_under_review", "delivery_state": "under_review",
                      "matched_work": work, "title_found": True, "description_found": True,
                      "evidence_path": str(evidence)}
            self.assertTrue(wrapper._postcheck_passed(report, self.MANIFEST))
            self.assertFalse(wrapper._postcheck_passed(dict(report, status="under_review"), self.MANIFEST))
            self.assertFalse(wrapper._postcheck_passed(dict(report, evidence_path=str(Path(tmp) / "missing.png")),
                                                       self.MANIFEST))

    def test_scheduled_postcheck_requires_title_and_schedule_match(self):
        from scripts import kuaishou_postcheck_manifest as postcheck

        card = "状态：定时发布\n标题：Expected title\n描述：Expected description body\n定时发布时间：{}"
        result = postcheck._classify_management_postcheck(self.MANIFEST, [{"text": card.format("2026-07-29 12:30")}])
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "management_postcheck_found")

        wrong_time = postcheck._classify_management_postcheck(self.MANIFEST, [{"text": card.format("2026-07-29 18:30")}])
        self.assertFalse(wrong_time["passed"])


if __name__ == "__main__":
    unittest.main()
