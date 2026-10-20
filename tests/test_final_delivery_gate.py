from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from scripts.final_delivery_gate import validate_video_runtime
from content_platform.delivery_manifest import build_delivery_manifest
from content_platform.shotcraft_receipt import build_shotcraft_execution_receipt
from content_platform.video_artifact import verify_final_pixels


def _canonical_manifest(root: Path) -> None:
    Image.new("RGB", (1080, 1920), "#182433").save(root / "cover.png")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=8", "-t", "1", "-pix_fmt", "yuv420p", str(root / "final.mp4")],
        check=True,
        capture_output=True,
    )
    manifest = {
        "ok": True,
        "output": str(root / "final.mp4"),
        "renderer_command": ["python", "/root/project/scripts/film_renderer.py", "--output", str(root / "final.mp4")],
        "tool_invocation_manifest": {
            "invocations": {
                name: {"status": "ok", "artifact": str(root / "evidence.json")}
                for name in (
                    "cinema_composition.storyboard",
                    "shotcraft_moves.shot_plan_for_text",
                    "shotcraft_moves.shot_sequence",
                    "visual_gate.py --cinema",
                )
            }
        },
        "rendered_html_gate": {"passed": True},
        "cinema_visual_gate": {"passed": True},
        "artifact_gate": {"passed": True},
        "scene_duration_gate": {"passed": True},
        "motion_evidence": {"passed": True},
        "cover_quality_gate": {"passed": True, "status": "pass"},
        "segment_motion_evidence": {
            "segments": [
                {
                    "index": 1,
                    "move_id": "zoom_in_focus",
                    "profile": "element_motion_zoom_in_focus_1",
                    "rendered": True,
                    "renderer": "film_renderer",
                    "fallback": False,
                },
                {
                    "index": 2,
                    "move_id": "pan_down_flow",
                    "profile": "element_motion_pan_down_flow_2",
                    "rendered": True,
                    "renderer": "film_renderer",
                    "fallback": False,
                },
                {
                    "index": 3,
                    "move_id": "scale_punch",
                    "profile": "element_motion_scale_punch_3",
                    "rendered": True,
                    "renderer": "film_renderer",
                    "fallback": False,
                },
            ]
        },
    }
    account_identity = {"account_key": "douyin_ai", "lane": "real_world_ai_implementation_v1", "content_line": "practical_workflow_demo"}
    account_sha = hashlib.sha256(json.dumps(account_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    account_gate = {"passed": True, **account_identity, "account_lane_fingerprint": account_sha}
    (root / "account_lane_gate.json").write_text(json.dumps(account_gate), encoding="utf-8")
    analysis_binding = {"sha256": "a" * 64, "source": "test"}
    manifest["account_lane_gate"] = account_gate
    manifest["analysis_fingerprint"] = analysis_binding
    scene_contract = {"version": "scene_contract_v1", "account_lane": account_gate, "account_lane_fingerprint": account_sha, "analysis_fingerprint": analysis_binding, "scenes": [{"index": 1}]}
    scene_contract_path = root / "scene_contract.json"
    scene_contract_path.write_text(json.dumps(scene_contract), encoding="utf-8")
    (root / "scene_manifest.json").write_text(json.dumps({"scenes": [{"index": 1}]}), encoding="utf-8")
    shot_dir = root / "shots"
    shot_dir.mkdir()
    for index, row in enumerate(manifest["segment_motion_evidence"]["segments"], 1):
        outputs = []
        for suffix in ("A", "B"):
            shot_path = shot_dir / f"shot_{index:02d}{suffix}.mp4"
            shutil.copy2(root / "final.mp4", shot_path)
            outputs.append({"name": shot_path.stem, "path": str(shot_path), "sha256": hashlib.sha256(shot_path.read_bytes()).hexdigest(), "renderer": "playwright-video", "fallback": False, "reused": False})
        row["shot_outputs"] = outputs
        row["shotcraft_execution_receipt"] = {"version": "shotcraft_execution_receipt_v1", "all_outputs_bound": True}
    manifest["segment_motion_evidence"]["receipt_version"] = "segment_motion_evidence_v2"
    manifest["segment_motion_evidence"]["renderer"] = "film_renderer"
    manifest["segment_motion_evidence"]["final_video_sha256"] = hashlib.sha256((root / "final.mp4").read_bytes()).hexdigest()
    manifest["segment_motion_evidence"]["scene_contract_sha256"] = hashlib.sha256(scene_contract_path.read_bytes()).hexdigest()
    manifest["final_pixel_gate"] = verify_final_pixels(root / "final.mp4")
    (root / "final_pixel_gate.json").write_text(json.dumps(manifest["final_pixel_gate"]), encoding="utf-8")

    (root / "segment_motion_evidence.json").write_text(json.dumps(manifest["segment_motion_evidence"]), encoding="utf-8")
    receipt = build_shotcraft_execution_receipt(root, manifest["segment_motion_evidence"])
    (root / "shotcraft_execution_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    delivery = build_delivery_manifest(
        root,
        required_paths=[root / "final.mp4", root / "cover.png", root / "scene_manifest.json", root / "segment_motion_evidence.json", root / "shotcraft_execution_receipt.json"],
        identity={"run_id": "test", "attempt_id": "a1", "platform": "douyin_ai"},
    )
    (root / "delivery_manifest.json").write_text(json.dumps(delivery), encoding="utf-8")
    manifest["artifact_set_sha256"] = delivery["artifact_set_sha256"]
    (root / "video_toolchain_runner_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_handwritten_metadata_without_canonical_runner_is_blocked():
    root = Path("/root/.ai-self-media-tools/data/runs/douyin_ai/20260920_finance_reconciliation_r1")
    result = validate_video_runtime(root)
    assert result["passed"] is False
    assert "video_toolchain_manifest_missing" in result["failures"]


def test_canonical_runner_evidence_can_pass_runtime_identity_gate(tmp_path: Path):
    _canonical_manifest(tmp_path)
    result = validate_video_runtime(tmp_path)
    assert result["passed"] is True
    assert result["failures"] == []
