#!/usr/bin/env python3
"""Fail-closed final delivery evidence gate.

The gate is deliberately boring: every successful delivery must identify the
same job/package/platform, carry real files and declared hashes, and have a
successful verification state.  It never upgrades a failed or blocked result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from content_platform.delivery_manifest import validate_attempt_bundle, validate_delivery_manifest
from content_platform.shotcraft_receipt import validate_shotcraft_execution_receipt
from content_platform.video_artifact import verify_final_pixels

LIGHT_TEXT = {"#E5F0FA", "#E8E8E8", "#B8D4EE", "#FFFFFF", "WHITE"}
SUCCESS_STATES = {"published", "drafted", "draft_published", "manual_confirmed", "handoff_ready"}
FAILURE_STATES = {"publish_failed", "failed", "blocked", "skipped", "queued", "pending", "handoff_pending"}
TERMINAL_STATES = SUCCESS_STATES | FAILURE_STATES


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hex_luminance(value: str) -> float | None:
    value = value.strip().upper()
    if not value.startswith("#") or len(value) not in {4, 7}:
        return None
    if len(value) == 4:
        value = "#" + "".join(ch * 2 for ch in value[1:])
    try:
        channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    except ValueError:
        return None
    return sum(channels) / 3


def validate_article_html(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    failures: list[str] = []
    body_bg = re.search(r"<body[^>]*style=\"[^\"]*background\s*:\s*([^;\"]+)", text, re.I)
    body_background = body_bg.group(1).strip() if body_bg else "#ffffff"
    inline_colors = re.findall(r"<(?:body|p|li|blockquote|code|h[1-6])\b[^>]*style=\"[^\"]*color\s*:\s*([^;\"]+)", text, re.I)
    light_on_light = []
    for color in inline_colors:
        upper = color.strip().upper()
        lum = _hex_luminance(upper)
        if upper in LIGHT_TEXT or (lum is not None and lum > 0.82 and _hex_luminance(body_background) is not None and _hex_luminance(body_background) > 0.75):
            light_on_light.append(upper)
    if light_on_light:
        failures.append("article_light_text_on_light_background")
    image_count = len(re.findall(r"data-src=", text))
    if image_count == 0:
        failures.append("article_has_no_rendered_images")
    return {"passed": not failures, "failures": failures, "body_background": body_background, "data_src_count": image_count}


def validate_assets(manifest: dict[str, Any], root: Path, *, job_id: str, platform: str, content_package_id: str) -> dict[str, Any]:
    failures: list[str] = []
    if str(manifest.get("job_id") or "") != str(job_id):
        failures.append("job_identity_mismatch")
    if str(manifest.get("platform") or "").casefold() != str(platform).casefold():
        failures.append("platform_identity_mismatch")
    if str(manifest.get("content_package_id") or "") != str(content_package_id):
        failures.append("content_package_identity_mismatch")
    records = manifest.get("assets") or manifest.get("images") or []
    if not isinstance(records, list) or not records:
        return {"passed": False, "failures": [*failures, "asset_manifest_missing"], "records": []}
    hashes: dict[str, str] = {}
    normalized = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            failures.append(f"asset_{index}_not_object")
            continue
        raw_path = str(record.get("path") or "").strip()
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            failures.append(f"asset_{index}_missing")
            continue
        for field in ("role", "source", "rights", "match_reason"):
            if not str(record.get(field) or "").strip():
                failures.append(f"asset_{index}_{field}_missing")
        if record.get("semantic_match") is not True and not isinstance(record.get("semantic_evidence"), dict):
            failures.append(f"asset_{index}_semantic_evidence_missing")
        digest = _sha256(path)
        declared = str(record.get("sha256") or record.get("asset_hash") or "").lower()
        if declared != digest:
            failures.append(f"asset_{index}_hash_mismatch")
        if digest in hashes:
            failures.append(f"asset_duplicate:{path.name}:{hashes[digest]}")
        else:
            hashes[digest] = path.name
        normalized.append({"path": str(path), "role": record.get("role"), "sha256": digest})
    roles = [item["role"] for item in normalized]
    if roles.count("cover") != 1:
        failures.append("cover_count_not_one")
    return {"passed": not failures, "failures": list(dict.fromkeys(failures)), "records": normalized}


def validate_publish_state(state: dict[str, Any], *, root: Path, job_id: str, platform: str, content_package_id: str) -> dict[str, Any]:
    failures: list[str] = []
    status = str(state.get("status") or "").strip().casefold()
    if status not in TERMINAL_STATES:
        failures.append("publish_state_missing_or_invalid")
    if str(state.get("job_id") or "") != str(job_id):
        failures.append("state_job_identity_mismatch")
    if str(state.get("platform") or "").casefold() != str(platform).casefold():
        failures.append("state_platform_identity_mismatch")
    if str(state.get("content_package_id") or "") != str(content_package_id):
        failures.append("state_content_package_identity_mismatch")
    if status in FAILURE_STATES:
        failures.append("failure_state_cannot_pass")
    if status in SUCCESS_STATES:
        if not bool(state.get("publish_verified") or state.get("draft_batchget_verified") or state.get("postcheck_verified")):
            failures.append("successful_state_without_verification")
        evidence = str(state.get("evidence") or state.get("evidence_path") or "").strip()
        if not evidence or not (Path(evidence) if Path(evidence).is_absolute() else root / evidence).is_file():
            failures.append("successful_state_without_evidence")
    return {"passed": not failures, "failures": failures, "status": status}


def validate_video_runtime(root: Path) -> dict[str, Any]:
    """Require evidence produced by the canonical video renderer, not hand-written metadata."""
    failures: list[str] = []
    manifest_path = root / "video_toolchain_runner_manifest.json"
    if not manifest_path.is_file():
        return {"passed": False, "failures": ["video_toolchain_manifest_missing"]}
    try:
        manifest = _read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"passed": False, "failures": [f"video_toolchain_manifest_invalid:{type(exc).__name__}"]}
    delivery_path = root / "delivery_manifest.json"
    if not delivery_path.is_file():
        failures.append("delivery_manifest_missing")
        delivery_result = {"passed": False, "artifact_set_sha256": "", "failures": []}
    else:
        try:
            delivery_result = validate_delivery_manifest(root, _read_json(delivery_path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            delivery_result = {"passed": False, "artifact_set_sha256": "", "failures": [f"delivery_manifest_invalid:{type(exc).__name__}"]}
        if delivery_result.get("passed") is not True:
            failures.extend(str(item) for item in delivery_result.get("failures") or [])
    if manifest.get("artifact_set_sha256") != delivery_result.get("artifact_set_sha256"):
        failures.append("runner_delivery_artifact_set_mismatch")
    bundle_result = validate_attempt_bundle(root, require_runner=True)
    if bundle_result.get("passed") is not True:
        failures.extend(f"attempt_bundle:{item}" for item in bundle_result.get("failures") or ["failed"])
    account_path = root / "account_lane_gate.json"
    scene_contract_path = root / "scene_contract.json"
    if not account_path.is_file() or not scene_contract_path.is_file():
        failures.append("account_scene_contract_binding_missing")
    else:
        try:
            account_gate = _read_json(account_path)
            scene_contract = _read_json(scene_contract_path)
            account_identity = {
                "account_key": str(account_gate.get("account_key") or ""),
                "lane": str(account_gate.get("lane") or ""),
                "content_line": str(account_gate.get("content_line") or ""),
            }
            expected_account_sha = hashlib.sha256(json.dumps(account_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            if account_gate.get("passed") is not True or account_gate.get("account_lane_fingerprint") != expected_account_sha:
                failures.append("account_lane_fingerprint_invalid")
            if manifest.get("account_lane_gate", {}).get("account_lane_fingerprint") != account_gate.get("account_lane_fingerprint"):
                failures.append("runner_account_lane_binding_mismatch")
            if scene_contract.get("account_lane_fingerprint") != account_gate.get("account_lane_fingerprint"):
                failures.append("scene_account_lane_binding_mismatch")
            analysis = scene_contract.get("analysis_fingerprint") or {}
            if not isinstance(analysis, dict) or not str(analysis.get("sha256") or ""):
                failures.append("scene_analysis_fingerprint_missing")
            elif manifest.get("analysis_fingerprint") != analysis:
                failures.append("runner_analysis_binding_mismatch")
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            failures.append("account_scene_contract_binding_invalid")
    final_video = root / "final.mp4"
    if not final_video.is_file():
        failures.append("final_mp4_missing")
    else:
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(final_video)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            parsed = json.loads(probe.stdout or "{}") if probe.returncode == 0 else {}
            if probe.returncode != 0 or not parsed.get("streams") or not parsed.get("format", {}).get("duration"):
                failures.append("final_mp4_probe_failed")
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            failures.append("final_mp4_probe_failed")
    declared_output = manifest.get("output")
    if declared_output and Path(str(declared_output)).resolve() != final_video.resolve():
        failures.append("final_mp4_path_mismatch")
    cover_candidates = []
    if manifest.get("cover"):
        cover_candidates.append(Path(str(manifest["cover"])))
    cover_candidates.extend(root / name for name in ("cover.png", "cover.jpg", "cover.jpeg", "cover_1080x1920.jpg", "cover_1920x1080.jpg"))
    if not any(path.is_file() for path in cover_candidates):
        failures.append("cover_file_missing")
    renderer_command = " ".join(str(item) for item in (manifest.get("renderer_command") or []))
    if not any(name in renderer_command for name in ("/film_renderer.py", "/kuaishou_render.py")):
        failures.append("noncanonical_video_renderer")
    if manifest.get("ok") is not True:
        failures.append("video_toolchain_not_ok")
    required_tools = {
        "cinema_composition.storyboard",
        "shotcraft_moves.shot_plan_for_text",
        "shotcraft_moves.shot_sequence",
        "visual_gate.py --cinema",
    }
    invocations = (manifest.get("tool_invocation_manifest") or {}).get("invocations") or {}
    failures.extend(f"runtime_tool_not_verified:{name}" for name in sorted(required_tools) if (invocations.get(name) or {}).get("status") != "ok")
    for key in ("rendered_html_gate", "final_pixel_gate", "cinema_visual_gate", "artifact_gate", "scene_duration_gate", "motion_evidence"):
        if (manifest.get(key) or {}).get("passed") is not True:
            failures.append(f"{key}_failed_or_missing")
    final_pixel_evidence_path = root / "final_pixel_gate.json"
    if final_video.is_file():
        actual_pixel_gate = verify_final_pixels(final_video)
        if not actual_pixel_gate.get("passed"):
            failures.extend(f"final_pixel:{item}" for item in actual_pixel_gate.get("failures") or ["failed"])
        if not final_pixel_evidence_path.is_file():
            failures.append("final_pixel_gate_evidence_missing")
        else:
            try:
                declared_pixel_gate = _read_json(final_pixel_evidence_path)
                if declared_pixel_gate.get("candidate_sha256") != actual_pixel_gate.get("candidate_sha256"):
                    failures.append("final_pixel_gate_candidate_sha256_mismatch")
            except (OSError, ValueError, json.JSONDecodeError):
                failures.append("final_pixel_gate_evidence_invalid")
    cover_gate = manifest.get("cover_quality_gate") or {}
    if cover_gate.get("passed") is not True and cover_gate.get("status") != "pass":
        failures.append("cover_quality_gate_failed_or_missing")
    segment_path = root / "segment_motion_evidence.json"
    segment_payload = {}
    if segment_path.is_file():
        try:
            segment_payload = _read_json(segment_path)
        except (OSError, ValueError, json.JSONDecodeError):
            failures.append("segment_motion_evidence_invalid")
    else:
        failures.append("segment_motion_evidence_missing")
    receipt_path = root / "shotcraft_execution_receipt.json"
    if not receipt_path.is_file():
        failures.append("shotcraft_execution_receipt_missing")
    else:
        try:
            receipt_result = validate_shotcraft_execution_receipt(root, _read_json(receipt_path))
            if receipt_result.get("passed") is not True:
                failures.extend(f"shotcraft_receipt:{item}" for item in receipt_result.get("failures") or ["failed"])
        except (OSError, ValueError, json.JSONDecodeError):
            failures.append("shotcraft_execution_receipt_invalid")
    if not segment_payload:
        segment_path = root / "segment_motion_evidence.json"
        if segment_path.is_file():
            try:
                segment_payload = _read_json(segment_path)
            except (OSError, ValueError, json.JSONDecodeError):
                segment_payload = {}
    segments = segment_payload.get("segments") if isinstance(segment_payload, dict) else None
    if not isinstance(segments, list) or len(segments) < 3:
        failures.append("segment_motion_evidence_missing")
    else:
        expected_final_sha = _sha256(final_video) if final_video.is_file() else ""
        declared_final_sha = str(segment_payload.get("final_video_sha256") or "")
        if declared_final_sha != expected_final_sha:
            failures.append("segment_final_video_sha256_mismatch")
        if str(segment_payload.get("renderer") or "") != "film_renderer":
            failures.append("segment_renderer_not_canonical")
        if str(segment_payload.get("receipt_version") or "") != "segment_motion_evidence_v2":
            failures.append("segment_execution_receipt_missing")
        if not str(segment_payload.get("scene_contract_sha256") or ""):
            failures.append("segment_scene_contract_sha256_missing")
        for index, row in enumerate(segments, 1):
            if not isinstance(row, dict) or not row.get("move_id") or not row.get("profile") or row.get("rendered") is not True or not row.get("renderer") or row.get("fallback") is True:
                failures.append(f"segment_{index}_runtime_evidence_invalid")
                continue
            receipt = row.get("shotcraft_execution_receipt")
            outputs = row.get("shot_outputs")
            if not isinstance(receipt, dict) or receipt.get("version") != "shotcraft_execution_receipt_v1" or receipt.get("all_outputs_bound") is not True:
                failures.append(f"segment_{index}_shotcraft_receipt_invalid")
            if not isinstance(outputs, list) or len(outputs) != 2:
                failures.append(f"segment_{index}_shot_outputs_missing")
                continue
            for output in outputs:
                if not isinstance(output, dict):
                    failures.append(f"segment_{index}_shot_output_invalid")
                    continue
                path = Path(str(output.get("path") or ""))
                if not path.is_file():
                    failures.append(f"segment_{index}_shot_output_missing")
                    continue
                if str(output.get("sha256") or "") != _sha256(path):
                    failures.append(f"segment_{index}_shot_output_hash_mismatch")
                if output.get("fallback") is True or str(output.get("renderer") or "") == "still-motion":
                    failures.append(f"segment_{index}_shot_output_degraded")
    return {"passed": not failures, "failures": list(dict.fromkeys(failures)), "manifest_path": str(manifest_path)}


def run_gate(root: Path, *, platform: str, job_id: str, content_package_id: str, html: Path | None, assets: Path | None, state: Path | None) -> dict[str, Any]:
    """Validate a complete, identity-bound evidence packet. All three inputs are required."""
    checks: dict[str, Any] = {}
    if not str(platform).strip():
        checks["identity"] = {"passed": False, "failures": ["platform_missing"]}
    video_platforms = {"kuaishou", "douyin", "douyin_ai", "douyin_pet", "tiktok", "shipinhao", "youtube", "bilibili"}
    required_inputs = [("assets", assets), ("publish_state", state)]
    if str(platform).casefold() not in video_platforms:
        required_inputs.append(("article_html", html))
    for name, path in required_inputs:
        if path is None:
            checks[name] = {"passed": False, "failures": [f"{name}_required"]}
        elif not path.is_file():
            checks[name] = {"passed": False, "failures": [f"{name}_file_missing"], "path": str(path)}
    if html and html.is_file():
        checks["article_html"] = validate_article_html(html)
    if str(platform).casefold() in video_platforms:
        checks["video_runtime"] = validate_video_runtime(root)
    if assets and assets.is_file():
        try:
            checks["assets"] = validate_assets(_read_json(assets), root, job_id=job_id, platform=platform, content_package_id=content_package_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks["assets"] = {"passed": False, "failures": [f"assets_manifest_invalid:{type(exc).__name__}"]}
    if state and state.is_file():
        try:
            checks["publish_state"] = validate_publish_state(_read_json(state), root=root, job_id=job_id, platform=platform, content_package_id=content_package_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks["publish_state"] = {"passed": False, "failures": [f"publish_state_invalid:{type(exc).__name__}"]}
    failures = [f"{name}:{item}" for name, result in checks.items() for item in result.get("failures", []) if not result.get("passed")]
    return {"passed": not failures, "platform": platform, "job_id": str(job_id), "content_package_id": str(content_package_id), "failures": failures, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--content-package-id", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--html", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    result = run_gate(Path(args.root), platform=args.platform, job_id=args.job_id, content_package_id=args.content_package_id, html=Path(args.html), assets=Path(args.assets), state=Path(args.state))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
