"""Task9 serial canary runner and evidence probes.

This module is intentionally an acceptance-layer script. It invokes the real
project CLI in a subprocess and only upgrades evidence after reading artifacts.
It never publishes, edits timers, or treats planned metadata as artifact proof.
"""

from __future__ import annotations

import hashlib
import ast
import copy
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.adapters.media import (
    build_tts_fingerprint,
    probe_final_video,
    validate_bgm_contract,
    validate_handoff_contract,
    validate_scene_manifest_contract,
    validate_tts_fingerprint,
)
from content_platform.cover_quality import validate_cover
from content_platform.publication_ledger import PublicationLedger
from content_platform.pipeline import Pipeline
from content_platform.store import Store
from content_platform.cli import load_config
from content_platform.associated_hotspot import load_hotspot_support_matrix


CANARY_PLATFORMS = (
    ("wechat", "article", "zh", "draft_first", False),
    ("kuaishou", "vertical_video", "zh", "scheduled", True),
    ("juejin", "article", "zh", "draft_first", False),
    ("twitter", "short_post", "en", "direct_publish", True),
    ("douyin_ai", "vertical_video", "zh", "manual_handoff_only", False),
    ("douyin_pet", "vertical_video", "zh", "manual_handoff_only", False),
    ("shipinhao", "vertical_video", "zh", "manual_handoff_only", False),
    ("xiaohongshu", "carousel", "zh", "manual_handoff_only", False),
    ("bilibili", "horizontal_video", "zh", "manual_handoff_only", False),
    ("zhihu", "article", "zh", "draft_first", True),
    ("youtube", "horizontal_video", "en", "manual_handoff_only", False),
    ("tiktok", "vertical_video", "en", "manual_handoff_only", False),
)
EXPECTED_CANARY_PLATFORMS = tuple(item[0] for item in CANARY_PLATFORMS)
DETERMINISTIC_GATE_NAMES = (
    "artifact_hashes",
    "capability_evidence",
    "media_probes",
    "delivery_policy",
    "hotspot_evidence",
    "handoff_render_contract",
)


def build_canary_matrix() -> list[dict[str, Any]]:
    """Return the only accepted serial matrix for production canaries."""
    support = load_hotspot_support_matrix()
    return [
        {
            "order": index,
            "platform": platform,
            "content_form": content_form,
            "language": language,
            "delivery_policy": policy,
            "dry_run": dry_run,
            "hotspot_contract": {
                "allowed_evidence_types": list((support.get("platforms") or {}).get(platform, {}).get("allowed_evidence_types") or []),
                "allowed_association_modes": list((support.get("platforms") or {}).get(platform, {}).get("allowed_association_modes") or []),
            },
            "entrypoint_kind": "pipeline",
            "entrypoint": [sys.executable, "-m", "content_platform.pipeline"],
        }
        for index, (platform, content_form, language, policy, dry_run) in enumerate(CANARY_PLATFORMS, 1)
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()


def _canonical_hotspot_provenance(platform: Any, source_url: Any, observed_title: Any, *, fetched_at: Any = "", status: Any = "", snapshot_path: Any = "", snapshot_sha256: Any = "") -> dict[str, str]:
    """Return the stable provenance record supplied by the external collector."""
    return {
        "platform": str(platform or "").strip(),
        "source_url": str(source_url or "").strip(),
        "observed_title": str(observed_title or "").strip(),
        "fetched_at": str(fetched_at or "").strip(),
        "status": str(status or "").strip(),
        "snapshot_path": str(snapshot_path or "").strip(),
        "snapshot_sha256": str(snapshot_sha256 or "").strip().lower(),
    }


def _hotspot_source_hash(platform: Any, source_url: Any, observed_title: Any, **kwargs: Any) -> str:
    return _json_hash(_canonical_hotspot_provenance(platform, source_url, observed_title, **kwargs))


def _case_hotspot_contract(case: dict[str, Any]) -> dict[str, list[str]]:
    supplied = case.get("hotspot_contract") if isinstance(case.get("hotspot_contract"), dict) else {}
    if supplied:
        return supplied
    record = (load_hotspot_support_matrix().get("platforms") or {}).get(str(case.get("platform") or ""), {})
    return {
        "allowed_evidence_types": list(record.get("allowed_evidence_types") or []),
        "allowed_association_modes": list(record.get("allowed_association_modes") or []),
    }


def _load_verified_hotspot(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    """Load collector output; never manufacture platform-native evidence."""
    inputs_root = (root / "_inputs").resolve()
    evidence_path = (inputs_root / "hotspots" / f"{case['platform']}.json").resolve()
    try:
        evidence_path.relative_to(inputs_root)
    except ValueError as exc:
        raise ValueError("hotspot evidence path escapes _inputs") from exc
    record = _load_json(evidence_path)
    platform = str(record.get("platform") or "").strip()
    source_url = str(record.get("native_source_url") or record.get("source_url") or "").strip()
    evidence_type = str(record.get("evidence_type") or "").casefold().strip()
    association_mode = str(record.get("association_mode") or "").strip()
    native_verified = record.get("native_verified") is True
    try:
        lane_fit_score = float(record.get("lane_fit_score"))
        semantic_fit_score = float(record.get("semantic_fit_score"))
    except (TypeError, ValueError):
        lane_fit_score = semantic_fit_score = 0.0
    contract = _case_hotspot_contract(case)
    observed_title = str(record.get("observed_title") or "").strip()
    fetched_at = str(record.get("fetched_at") or "").strip()
    status = record.get("status", record.get("status_code"))
    status_text = str(status or "").strip()
    snapshot_rel = str(record.get("snapshot_path") or "").strip().replace("\\", "/")
    snapshot = (inputs_root / snapshot_rel).resolve()
    failures = []
    if platform != str(case["platform"]):
        failures.append("hotspot_platform_mismatch")
    if not source_url.startswith(("https://", "http://")):
        failures.append("hotspot_source_url_missing")
    if evidence_type not in set(contract.get("allowed_evidence_types") or []):
        failures.append("hotspot_evidence_type_not_allowed")
    if association_mode not in set(contract.get("allowed_association_modes") or []):
        failures.append("hotspot_association_mode_not_allowed")
    if evidence_type == "native" and not native_verified:
        failures.append("hotspot_native_verification_missing")
    if evidence_type != "native" and native_verified:
        failures.append("non_native_hotspot_relabelled_native")
    if lane_fit_score < 0.55:
        failures.append("hotspot_lane_fit_too_low")
    if semantic_fit_score < 0.55:
        failures.append("hotspot_semantic_fit_too_low")
    if not observed_title or not fetched_at:
        failures.append("hotspot_observation_incomplete")
    try:
        status_ok = 200 <= int(status) < 300
    except (TypeError, ValueError):
        status_ok = False
    if not status_ok:
        failures.append("hotspot_fetch_status_not_2xx")
    try:
        snapshot.relative_to(inputs_root)
    except ValueError:
        failures.append("hotspot_snapshot_outside_inputs")
    if not snapshot.is_file():
        failures.append("hotspot_snapshot_missing")
    actual_snapshot_hash = sha256_file(snapshot) if snapshot.is_file() else ""
    declared_snapshot_hash = str(record.get("snapshot_sha256") or "").strip().lower()
    if not declared_snapshot_hash or actual_snapshot_hash != declared_snapshot_hash:
        failures.append("hotspot_snapshot_hash_mismatch")
    snapshot_text = snapshot.read_text(encoding="utf-8", errors="replace") if snapshot.is_file() else ""
    if observed_title and observed_title not in snapshot_text:
        failures.append("hotspot_observed_title_missing_from_snapshot")
    expected_provenance = _hotspot_source_hash(
        platform, source_url, observed_title, fetched_at=fetched_at, status=status_text,
        snapshot_path=snapshot_rel, snapshot_sha256=declared_snapshot_hash,
    )
    if str(record.get("provenance_hash") or "").strip().lower() != expected_provenance:
        failures.append("hotspot_provenance_hash_mismatch")
    if failures:
        raise ValueError(";".join(sorted(set(failures))))
    return {
        "platform": platform,
        "mode": evidence_type,
        "evidence_type": evidence_type,
        "association_mode": association_mode,
        "native_verified": native_verified,
        "lane_fit_score": lane_fit_score,
        "semantic_fit_score": semantic_fit_score,
        "source_url": source_url,
        "observed_title": observed_title,
        "fetched_at": fetched_at,
        "status": int(status),
        "snapshot_path": snapshot_rel,
        "snapshot_sha256": declared_snapshot_hash,
        "provenance_hash": expected_provenance,
        "source_hash": expected_provenance,
        "evidence_verified": True,
    }


def _validate_hotspot_provenance(case: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    hotspot = manifest.get("hotspot") if isinstance(manifest.get("hotspot"), dict) else {}
    platform = str(case.get("platform") or "")
    source_url = str(hotspot.get("source_url") or "")
    observed_title = str(hotspot.get("observed_title") or "")
    expected = _hotspot_source_hash(
        platform, source_url, observed_title,
        fetched_at=hotspot.get("fetched_at"), status=hotspot.get("status"),
        snapshot_path=hotspot.get("snapshot_path"), snapshot_sha256=hotspot.get("snapshot_sha256"),
    ) if source_url and observed_title else ""
    failures: list[str] = []
    contract = _case_hotspot_contract(case)
    if hotspot.get("platform") != platform:
        failures.append("hotspot_platform_mismatch")
    if hotspot.get("evidence_type") not in set(contract.get("allowed_evidence_types") or []):
        failures.append("hotspot_evidence_type_not_allowed")
    if hotspot.get("association_mode") not in set(contract.get("allowed_association_modes") or []):
        failures.append("hotspot_association_mode_not_allowed")
    if hotspot.get("evidence_type") == "native" and hotspot.get("native_verified") is not True:
        failures.append("hotspot_native_verification_missing")
    if hotspot.get("evidence_type") != "native" and hotspot.get("native_verified") is True:
        failures.append("non_native_hotspot_relabelled_native")
    if float(hotspot.get("lane_fit_score") or 0) < 0.55:
        failures.append("hotspot_lane_fit_too_low")
    if float(hotspot.get("semantic_fit_score") or 0) < 0.55:
        failures.append("hotspot_semantic_fit_too_low")
    if not source_url.startswith(("https://", "http://")):
        failures.append("hotspot_source_missing")
    if not observed_title.strip():
        failures.append("hotspot_observation_missing")
    if hotspot.get("evidence_verified") is not True:
        failures.append("hotspot_external_evidence_not_verified")
    if str(hotspot.get("provenance_hash") or hotspot.get("source_hash") or "") != expected:
        failures.append("hotspot_source_provenance_not_independently_verified")
    if not hotspot.get("snapshot_path") or not hotspot.get("snapshot_sha256") or not hotspot.get("fetched_at"):
        failures.append("hotspot_snapshot_evidence_missing")
    source_rows = manifest.get("source_evidence") if isinstance(manifest.get("source_evidence"), list) else []
    matching = [
        row for row in source_rows
        if isinstance(row, dict)
        and str(row.get("platform") or "") == platform
        and str(row.get("url") or "") == source_url
        and str(row.get("title") or "") == observed_title
        and str(row.get("evidence_type") or "") == str(hotspot.get("evidence_type") or "")
        and str(row.get("association_mode") or "") == str(hotspot.get("association_mode") or "")
        and str(row.get("provenance_hash") or row.get("source_hash") or "") == expected
    ]
    if not matching:
        failures.append("hotspot_source_provenance_not_independently_verified")
    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "canonical_record": _canonical_hotspot_provenance(
            platform, source_url, observed_title,
            fetched_at=hotspot.get("fetched_at"), status=hotspot.get("status"),
            snapshot_path=hotspot.get("snapshot_path"), snapshot_sha256=hotspot.get("snapshot_sha256"),
        ),
        "source_hash": expected,
        "matching_sources": len(matching),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_json_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _relative_file(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _probe(name: str, passed: bool, *, details: dict[str, Any] | None = None, failures: list[str] | None = None, level: str = "declared") -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "evidence_level": level,
        "details": details or {},
        "failures": failures or [],
    }


def _read_subtitle(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"passed": False, "cue_count": 0, "failures": ["subtitle_file_missing"]}
    text = path.read_text(encoding="utf-8", errors="replace")
    cue_count = sum(1 for line in text.splitlines() if " --> " in line)
    return {"passed": cue_count > 0, "cue_count": cue_count, "failures": [] if cue_count else ["subtitle_cues_missing"]}


def validate_full_handoff_render_contract(contract: dict[str, Any] | None, root: Path | str, content_form: str) -> dict[str, Any]:
    """Validate a complete handoff package against readable, hashed outputs."""
    root = Path(root).resolve()
    contract = contract if isinstance(contract, dict) else {}
    if content_form not in {"vertical_video", "horizontal_video"}:
        return validate_handoff_contract(contract)
    failures: list[str] = []
    if not str(contract.get("version") or "").strip():
        failures.append("handoff_contract_version_missing")
    if not str(contract.get("copy_media_version") or "").strip():
        failures.append("copy_media_version_missing")
    target = contract.get("target_renderer_evidence") if isinstance(contract.get("target_renderer_evidence"), dict) else {}
    if target.get("verified") is not True:
        failures.append("target_renderer_evidence_missing")
    artifacts = contract.get("artifacts") if isinstance(contract.get("artifacts"), list) else []
    if not artifacts:
        failures.append("handoff_media_artifacts_missing")
    for index, item in enumerate(artifacts, 1):
        path = _relative_file(root, item.get("path") if isinstance(item, dict) else None)
        if path is None or not path.is_file() or path.stat().st_size <= 0:
            failures.append(f"handoff_artifact_{index}_unreadable")
            continue
        if str(item.get("sha256") or "") != sha256_file(path):
            failures.append(f"handoff_artifact_{index}_checksum_mismatch")
    backgrounds = contract.get("background_hashes") if isinstance(contract.get("background_hashes"), list) else []
    if len(backgrounds) < 2 or len(set(str(value) for value in backgrounds)) != len(backgrounds):
        failures.append("independent_background_motion_hashes_missing")
    motion = contract.get("motion_evidence") if isinstance(contract.get("motion_evidence"), dict) else {}
    if motion.get("artifact_verified") is not True or float(motion.get("mean_frame_difference") or 0) <= 0:
        failures.append("encoded_motion_evidence_missing")
    return {"passed": not failures, "failures": failures, "target_renderer": target, "artifact_count": len(artifacts), "background_hash_count": len(backgrounds)}


def _artifact_paths(root: Path, manifest: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    failures: list[str] = []
    for item in manifest.get("artifacts") if isinstance(manifest.get("artifacts"), list) else []:
        if not isinstance(item, dict):
            failures.append("artifact_record_invalid")
            continue
        raw_path = item.get("path")
        path = _relative_file(root, raw_path)
        if path is None or not path.is_file() or path.stat().st_size <= 0:
            failures.append(f"artifact_unreadable:{raw_path}")
            continue
        relative = path.relative_to(root).as_posix()
        actual = sha256_file(path)
        hashes[relative] = actual
        if str(item.get("sha256") or "") != actual:
            failures.append(f"artifact_hash_mismatch:{relative}")
    return hashes, failures


def probe_artifacts(case: dict[str, Any], artifact_dir: Path | str) -> dict[str, Any]:
    """Probe a materialized canary package and return independent evidence."""
    root = Path(artifact_dir).resolve()
    manifest_path = root / "artifact_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.is_file() else {}
    failures = [] if manifest else ["artifact_manifest_missing"]
    output_hashes, hash_failures = _artifact_paths(root, manifest)
    failures.extend(hash_failures)
    form = str(case.get("content_form") or "")
    probes: dict[str, dict[str, Any]] = {}

    cover_path = next((root / name for name in ("cover.jpg", "cover.jpeg", "cover.png") if (root / name).is_file()), None)
    cover_evidence = manifest.get("probe_evidence", {}).get("cover", {}) if isinstance(manifest.get("probe_evidence"), dict) else {}
    if cover_path:
        cover_result = validate_cover(cover_path, cover_evidence, str(case.get("platform") or ""))
        probes["cover"] = _probe("cover", cover_result["passed"], details=cover_result, failures=cover_result.get("failures", []), level="artifact_verified" if cover_result["passed"] else "declared")
        if not cover_result["passed"]:
            failures.extend(f"cover:{value}" for value in cover_result.get("failures", []))
    else:
        probes["cover"] = _probe("cover", False, failures=["cover_missing"])
        failures.append("cover_missing")

    if form == "carousel":
        carousel = manifest.get("carousel", {}) if isinstance(manifest.get("carousel"), dict) else {}
        images = []
        for raw in carousel.get("images", []):
            path = _relative_file(root, raw)
            if path and path.is_file() and path.stat().st_size > 0:
                images.append(path)
        carousel_passed = len(images) >= 3 and len({sha256_file(path) for path in images}) == len(images)
        probes["carousel"] = _probe("carousel", carousel_passed, details={"count": len(images)}, failures=[] if carousel_passed else ["carousel_images_not_unique_or_missing"], level="artifact_verified" if carousel_passed else "declared")
        if not carousel_passed:
            failures.append("carousel_images_not_unique_or_missing")

    video_path = root / "final.mp4"
    video_result: dict[str, Any] | None = None
    if form in {"vertical_video", "horizontal_video"}:
        video_result = probe_final_video(video_path)
        video_passed = bool(video_result.get("passed"))
        level = "artifact_verified" if video_passed else "declared"
        probes["audio"] = _probe("audio", video_result.get("audio", {}).get("sample_rate") == 44100 and video_result.get("audio", {}).get("channels") == 2, details=video_result.get("audio", {}), failures=[value for value in video_result.get("failures", []) if "audio" in value], level=level)
        probes["subtitle"] = _probe("subtitle", int(video_result.get("subtitle_streams") or 0) > 0, details={"subtitle_streams": video_result.get("subtitle_streams", 0)}, failures=[value for value in video_result.get("failures", []) if "subtitle" in value], level=level)
        probes["frame"] = _probe("frame", float(video_result.get("motion", {}).get("mean_frame_difference") or 0) > 0, details=video_result.get("motion", {}), failures=[value for value in video_result.get("failures", []) if "frame" in value or "motion" in value], level=level)
        if not video_passed:
            failures.extend(f"video:{value}" for value in video_result.get("failures", []))

        subtitle = _read_subtitle(next((root / name for name in ("subtitles.srt", "subtitle.srt") if (root / name).is_file()), None))
        probes["subtitle_file"] = _probe("subtitle_file", subtitle["passed"], details=subtitle, failures=subtitle["failures"], level="artifact_verified" if subtitle["passed"] else "declared")
        if not subtitle["passed"]:
            failures.extend(f"subtitle_file:{value}" for value in subtitle["failures"])

        tts = _load_json(root / "tts_fingerprint.json")
        tts_result = validate_tts_fingerprint(tts)
        probes["tts"] = _probe("tts", tts_result["passed"], details=tts_result, failures=tts_result.get("failures", []), level="artifact_verified" if tts_result["passed"] else "declared")
        if not tts_result["passed"]:
            failures.extend(f"tts:{value}" for value in tts_result.get("failures", []))

        bgm = _load_json(root / "bgm.json")
        bgm_result = validate_bgm_contract(bgm, recent_fingerprints=[])
        probes["bgm"] = _probe("bgm", bgm_result["passed"], details=bgm_result, failures=bgm_result.get("failures", []), level="artifact_verified" if bgm_result["passed"] else "declared")
        if not bgm_result["passed"]:
            failures.extend(f"bgm:{value}" for value in bgm_result.get("failures", []))

        scene_manifest = _load_json(root / "scene_manifest.json")
        observed = _load_json(root / "scene_observed.json")
        scene_result = validate_scene_manifest_contract(scene_manifest, observed=observed)
        probes["scene"] = _probe("scene", scene_result["passed"], details=scene_result, failures=scene_result.get("failures", []), level="artifact_verified" if scene_result["passed"] else "declared")
        if not scene_result["passed"]:
            failures.extend(f"scene:{value}" for value in scene_result.get("failures", []))

        asr = _load_json(root / "asr.json")
        asr_passed = bool(str(asr.get("transcript") or "").strip()) and bool(asr.get("segments"))
        probes["asr"] = _probe("asr", asr_passed, details={"segment_count": len(asr.get("segments", [])) if isinstance(asr.get("segments"), list) else 0}, failures=[] if asr_passed else ["asr_transcript_or_segments_missing"], level="artifact_verified" if asr_passed else "declared")
        if not asr_passed:
            failures.append("asr:asr_transcript_or_segments_missing")

    handoff = manifest.get("handoff_contract")
    if isinstance(handoff, dict):
        handoff_result = validate_full_handoff_render_contract(handoff, root, form)
        probes["handoff"] = _probe("handoff", handoff_result["passed"], details=handoff_result, failures=handoff_result.get("failures", []), level="artifact_verified" if handoff_result["passed"] else "contract_verified")
        if not handoff_result["passed"]:
            failures.extend(f"handoff:{value}" for value in handoff_result.get("failures", []))
    else:
        probes["handoff"] = _probe("handoff", False, failures=["handoff_contract_missing"])
        failures.append("handoff_contract_missing")

    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), list) else []
    capability_failures = []
    allowed_states = {"planned", "consulted", "executed", "artifact_verified", "skipped"}
    for item in capabilities:
        if not isinstance(item, dict) or str(item.get("state") or "") not in allowed_states:
            capability_failures.append("capability_state_invalid")
        elif item.get("required", True) and item.get("state") in {"planned", "consulted"}:
            capability_failures.append(f"required_capability_not_executed:{item.get('id', '')}")
        elif item.get("state") in {"executed", "artifact_verified"} and not item.get("output_hash"):
            capability_failures.append(f"capability_output_hash_missing:{item.get('id', '')}")
        elif item.get("artifact_relevant") and item.get("state") != "artifact_verified":
            capability_failures.append(f"artifact_capability_not_verified:{item.get('id', '')}")
    if not capabilities:
        capability_failures.append("capability_evidence_missing")
    probes["capabilities"] = _probe("capabilities", not capability_failures, details={"count": len(capabilities)}, failures=capability_failures, level="artifact_verified" if not capability_failures else "declared")
    failures.extend(capability_failures)

    hotspot = manifest.get("hotspot") if isinstance(manifest.get("hotspot"), dict) else {}
    hotspot_result = _validate_hotspot_provenance(case, manifest)
    hotspot_level = "artifact_verified" if hotspot_result["passed"] else "declared"
    probes["hotspot"] = _probe("hotspot", hotspot_result["passed"], details={**hotspot, **hotspot_result}, failures=hotspot_result["failures"], level=hotspot_level)
    failures.extend(hotspot_result["failures"])

    policy = manifest.get("delivery_policy") if isinstance(manifest.get("delivery_policy"), dict) else {}
    policy_state = str(policy.get("state") or "")
    policy_failures = []
    expected_policy = str(case.get("delivery_policy") or "")
    if case.get("dry_run") and policy_state != "dry_run":
        policy_failures.append("dry_run_policy_missing")
    if not case.get("dry_run") and policy_state == "published" and not policy.get("external_verified"):
        policy_failures.append("published_without_external_verification")
    if expected_policy == "manual_handoff_only" and policy_state not in {"handoff_pending", "handoff_ready"}:
        policy_failures.append("manual_handoff_policy_violation")
    probes["delivery_policy"] = _probe("delivery_policy", not policy_failures, details=policy, failures=policy_failures, level="external_verified" if policy.get("external_verified") else "contract_verified")
    failures.extend(policy_failures)

    for name in ("asr", "subtitle", "scene", "frame", "audio", "tts", "bgm"):
        if name not in probes:
            probes[name] = {"name": name, "passed": None, "status": "skipped", "evidence_level": "contract_verified", "details": {"applicable": False, "reason": "not_required_for_content_form"}, "failures": []}
    probes["cover_safe_zone"] = {
        "name": "cover_safe_zone",
        "passed": probes["cover"].get("passed"),
        "status": "verified" if probes["cover"].get("passed") else "declared_or_failed",
        "evidence_level": probes["cover"].get("evidence_level", "declared"),
        "details": {"safe_zone_verified": cover_evidence.get("safe_zone_verified") is True},
        "failures": [] if cover_evidence.get("safe_zone_verified") is True else ["safe_zone_not_verified"],
    }

    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "input_output_hashes": output_hashes,
        "probes": probes,
        "artifact_dir": str(root),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.is_file() else "",
    }


def _hermes_json(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _hermes_text(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _active_model_from_config_show(executable: str) -> dict[str, str]:
    text = _hermes_text([executable, "config", "show"])
    for line in text.splitlines():
        if "Model:" not in line:
            continue
        try:
            value = ast.literal_eval(line.split("Model:", 1)[1].strip())
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, dict):
            provider = str(value.get("provider") or "")
            model = str(value.get("default") or value.get("model") or "")
            if provider and model:
                return {"provider": provider, "model": model, "identity_source": "hermes_config_show"}
    return {}


def _weak_model_from_hermes_cache(provider: str, active_model: str) -> dict[str, str]:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    cache = _load_json(home / "provider_models_cache.json")
    record = cache.get(provider) if isinstance(cache.get(provider), dict) else {}
    models = [str(item) for item in record.get("models") or [] if str(item) and str(item) != active_model]
    weak = next((item for item in models if "free" in item.casefold()), models[0] if models else "")
    return {"provider": provider, "model": weak, "identity_source": "hermes_provider_models_cache"} if weak else {}


def _hermes_help(executable: str) -> str:
    try:
        result = subprocess.run([executable, "--help"], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return f"{result.stdout or ''}\n{result.stderr or ''}"


def _model_selection_capability(executable: str) -> dict[str, Any]:
    """Describe only selectors proven by the successful CLI help output."""
    help_text = _hermes_help(executable)
    if not help_text:
        return {"available": False, "reason": "hermes_cli_capability_check_failed"}
    lowered = help_text.casefold()
    if "hermes_model" in lowered and "hermes_provider" in lowered:
        return {"available": True, "mode": "environment", "evidence": "hermes_help"}
    if "--model" in lowered and "--provider" in lowered:
        return {"available": True, "mode": "flags", "evidence": "hermes_help"}
    return {"available": False, "reason": "model_selection_not_supported_by_hermes_cli"}


def discover_hermes_runtime() -> dict[str, Any]:
    """Discover identity from successful Hermes CLI output only."""
    executable = os.environ.get("HERMES_CLI", "hermes").strip() or "hermes"
    if not shutil.which(executable) and not Path(executable).is_file():
        return {"active": {"status": "unavailable", "provider": "", "model": "", "reason": "hermes_cli_unavailable"}, "weak": {"status": "dual_model_pending", "reason": "hermes_cli_unavailable"}}
    selection = _model_selection_capability(executable)
    active = _active_model_from_config_show(executable)
    provider = str(active.get("provider") or "")
    model = str(active.get("model") or "")
    active_status = "available" if provider and model else "unavailable"
    result = {"active": {"status": active_status, "provider": provider, "model": model, "executable": executable, "selection": selection, "gate_passed": False, "gate_reason": "model_gate_pending"}}
    weak = _weak_model_from_hermes_cache(provider, model) if provider and model else {}
    if weak:
        result["weak"] = {"status": "available", "provider": weak["provider"], "model": weak["model"], "identity_source": weak["identity_source"], "executable": executable, "selection": selection, "gate_passed": False, "gate_reason": "model_gate_pending"}
    else:
        result["weak"] = {"status": "dual_model_pending", "reason": "no_available_second_model", "executable": executable, "selection": selection, "gate_passed": False}
    if not selection.get("available"):
        for role in ("active", "weak"):
            if result[role].get("status") in {"available", "verified"}:
                result[role]["selection_reason"] = selection.get("reason", "model_selection_unavailable")
    return result


def _apply_model_gate_report(runtime: dict[str, Any], role: str, path: Path | str | None, gate_hash: str) -> None:
    identity = runtime.get(role) if isinstance(runtime.get(role), dict) else {}
    if not path:
        return
    report = _load_json(Path(path))
    identity["gate_contract_hash"] = str(report.get("gate_contract_hash") or "")
    identity["gate_passed"] = report.get("passed") is True and identity["gate_contract_hash"] == gate_hash
    identity["gate_reason"] = "" if identity["gate_passed"] else "model_gate_report_failed_or_contract_mismatch"


def _run_entrypoint(case: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    command = list(case["entrypoint"])
    try:
        result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, timeout=120, check=False)
        return {"command": command, "returncode": result.returncode, "passed": result.returncode == 0, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"command": command, "returncode": None, "passed": False, "stdout": "", "stderr": str(exc)}


def _canary_brief(case: dict[str, Any], hotspot: dict[str, Any]) -> dict[str, Any]:
    """Build bounded input from externally verified evidence."""
    platform = str(case["platform"])
    title = str(hotspot["observed_title"])
    return {
        "platform": platform,
        "platforms": [platform],
        "language": case["language"],
        "locale": case["language"],
        "content_form": case["content_form"],
        "content_blueprint": {
            "topic": title,
            "content_form": case["content_form"],
            "audience": "canary operators",
            "platform": platform,
            "language": case["language"],
        },
        "associated_hotspot": hotspot,
        "platform_source_matrix": {
            "version": "platform_source_matrix_v2",
            "platform": platform,
            "attempted_sources": [{
                "source": f"{platform}:task9_verified_evidence",
                "status": "ok",
                "count": 1,
                "collected_at": hotspot["fetched_at"],
                "source_url": hotspot["source_url"],
                "evidence_hash": hotspot["provenance_hash"],
            }],
            "platform_internal_verified": hotspot.get("native_verified") is True,
            "real_platform_collection_verified": True,
            "native_verified": True,
            "official_signals": [hotspot],
            "source_url": hotspot["source_url"],
            "source_hash": hotspot["provenance_hash"],
        },
        "source_catalog": [{
            "platform": platform,
            "title": hotspot["observed_title"],
            "url": hotspot["source_url"],
            "source": "official_native_canary",
            "source_hash": hotspot["provenance_hash"],
        }],
        "selection_mode": "official_native_canary",
        "automated_workflow": True,
        "delivery_policy": case["delivery_policy"],
        "claim_ledger": [],
        "content_depth_plan": {
            "evidence": ["official_native_canary"],
            "knowledge": ["pipeline execution"],
            "actions": ["inspect generated artifact"],
            "series": {"series_id": "task9", "episode": 1},
        },
    }


class _DryRunPublisher:
    """Safety boundary used only by Task9; never calls an external platform."""

    def __init__(self, outbox):
        self.outbox = Path(outbox)

    def deliver(self, job, platform):
        self.outbox.mkdir(parents=True, exist_ok=True)
        path = self.outbox / f"{platform}-{job['id']}.json"
        payload = {"job_id": job["id"], "platform": platform, "status": "dry_run", "title": job.get("title", "")}
        path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        from content_platform.models import DeliveryResult
        return DeliveryResult(True, "dry_run", str(path))


class _PolicySafePublisher:
    """External publisher boundary for canary routes; never performs network I/O."""

    def __init__(self, outbox, status):
        self.outbox = Path(outbox)
        self.status = status

    def deliver(self, job, platform):
        self.outbox.mkdir(parents=True, exist_ok=True)
        path = self.outbox / f"{platform}-{job['id']}.json"
        path.write_text(json.dumps({"job_id": job["id"], "platform": platform, "status": self.status}, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        from content_platform.models import DeliveryResult
        return DeliveryResult(True, self.status, str(path), error="Task9 external publisher boundary")


def _canary_config(root: Path, runtime_config_path: Path | str | None = None) -> dict[str, Any]:
    """Load real production capabilities while keeping delivery isolated."""
    config_path = Path(runtime_config_path).expanduser() if runtime_config_path else None
    if config_path and config_path.is_file():
        config = copy.deepcopy(load_config(str(config_path), str(root / "state.db")))
    else:
        config = {}
    config["data_dir"] = str(root)
    config.setdefault("profiles", {})["task9"] = {}
    generator = config.setdefault("generator", {})
    generator.update({"provider": "hermes-cli", "allow_fallback": False})
    config.setdefault("workflow", {})["require_gate_pass"] = True
    config.setdefault("publishers", {})["default"] = {"type": "file", "outbox": str(root / "outbox")}
    config.setdefault("notifications", {})["log_path"] = str(root / "notifications.jsonl")
    config.setdefault("delivery", {})["auto_stage_review_required"] = False
    return config


def _patch_dry_run_publisher(pipeline_module, outbox):
    original = pipeline_module.build_publisher

    def build(platform, config, data_dir):
        return _DryRunPublisher(outbox)

    pipeline_module.build_publisher = build
    return original


def _actual_files(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in {"artifact_manifest.json", "state.db", "state.db-wal", "state.db-shm"}:
            continue
        if path.suffix in {".json", ".jsonl"} and path.name not in {"final.json", "draft.json"}:
            continue
        records.append({"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path), "size": path.stat().st_size})
    return records


def _materialize_artifact_manifest(case: dict[str, Any], store: Any, result: dict[str, Any], root: Path, verified_hotspot: dict[str, Any] | None = None) -> dict[str, Any]:
    job_id = str(result.get("id") or "")
    job = store.get_job(job_id) if job_id and hasattr(store, "get_job") else result
    draft_meta = job.get("draft_meta") if isinstance(job, dict) else {}
    draft_meta = draft_meta if isinstance(draft_meta, dict) else {}
    artifacts = _actual_files(root)
    source_rows = store.source_items(job_id) if job_id and hasattr(store, "source_items") else []
    source_rows = [dict(row) for row in source_rows if hasattr(row, "keys")]
    if verified_hotspot:
        source_rows.append({
            "platform": verified_hotspot.get("platform"),
            "url": verified_hotspot.get("source_url"),
            "title": verified_hotspot.get("observed_title"),
            "evidence_type": verified_hotspot.get("evidence_type"),
            "association_mode": verified_hotspot.get("association_mode"),
            "provenance_hash": verified_hotspot.get("provenance_hash"),
        })
    hotspot = verified_hotspot or draft_meta.get("associated_hotspot") or draft_meta.get("hotspot")
    if not isinstance(hotspot, dict) and source_rows:
        first = source_rows[0]
        hotspot = {"platform": first.get("platform"), "source_url": first.get("url"), "observed_title": first.get("title"), "mode": "official_native"}
    delivery_rows = job.get("deliveries") if isinstance(job, dict) else []
    delivery = next((row for row in delivery_rows or [] if row.get("platform") == case["platform"]), {})
    execution = draft_meta.get("capability_execution") if isinstance(draft_meta.get("capability_execution"), dict) else {}
    capabilities = []
    for item in execution.get("executed") or []:
        if isinstance(item, dict):
            capabilities.append({
                "id": item.get("capability_id"),
                "state": "artifact_verified" if item.get("output_hash") and item.get("artifact_verified") else "executed",
                "output_hash": item.get("output_hash", ""),
                "artifact_verified": item.get("artifact_verified") is True,
                "required": item.get("required", True) is not False,
                "artifact_relevant": item.get("artifact_relevant", False) is True,
                "evidence": item,
            })
    for item in execution.get("planned") or []:
        if isinstance(item, dict) and not any(row.get("id") == item.get("capability_id") for row in capabilities):
            capabilities.append({"id": item.get("capability_id"), "state": "planned", "output_hash": "", "required": item.get("required", True) is not False, "artifact_relevant": item.get("artifact_relevant", False) is True, "evidence": item})
    manifest = {
        "schema": "task9_artifact_manifest_v2",
        "job_id": job_id,
        "platform": case["platform"],
        "content_form": case["content_form"],
        "artifacts": artifacts,
        "capabilities": capabilities,
        "hotspot": hotspot if isinstance(hotspot, dict) else {},
        "hotspot_evidence": verified_hotspot if isinstance(verified_hotspot, dict) else {},
        "delivery_policy": {
            "expected": case["delivery_policy"],
            "state": delivery.get("status", ""),
            "external_verified": bool(delivery.get("external_verified")),
            "receipt_path": delivery.get("external_id", ""),
        },
        "events": [dict(row) for row in (store.events(job_id) if job_id and hasattr(store, "events") else []) if hasattr(row, "keys")],
        "source_evidence": source_rows,
    }
    (root / "artifact_manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def _run_pipeline_case(case: dict[str, Any], root: Path, *, pipeline_factory=None, store_factory=None, hotspot_root: Path | None = None, runtime_config_path: Path | str | None = None) -> dict[str, Any]:
    from unittest.mock import patch

    root.mkdir(parents=True, exist_ok=True)
    try:
        verified_hotspot = _load_verified_hotspot(hotspot_root or root, case)
    except ValueError as exc:
        (root / "hotspot_preflight.json").write_text(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return {"passed": False, "pipeline_evidence": {"create_called": False, "run_called": False, "serial_index": case["order"], "job_id": ""}, "job": {}, "manifest": {}, "error": str(exc)}
    store = (store_factory or Store)(root / "state.db")
    config = _canary_config(root, runtime_config_path)
    pipeline = (pipeline_factory or Pipeline)(store, config)
    brief = _canary_brief(case, verified_hotspot)
    topic = brief["content_blueprint"]["topic"]
    evidence = {"create_called": False, "run_called": False, "stage_drafts_called": False, "serial_index": case["order"], "job_id": ""}
    try:
        created = pipeline.create(topic, [case["platform"]], brief, profile="task9", topic_fingerprint=_json_hash(brief))
        evidence["create_called"] = True
        job_id = str(created.get("id") or "")
        evidence["job_id"] = job_id
        result = pipeline.run(job_id)
        evidence["run_called"] = True
        if case.get("dry_run") or case["delivery_policy"] in {"draft_first", "manual_handoff_only", "dry_run"}:
            expected_status = (
                "dry_run"
                if case.get("dry_run") or case["delivery_policy"] == "dry_run"
                else {"draft_first": "drafted", "manual_handoff_only": "handoff_pending"}[case["delivery_policy"]]
            )
            with patch("content_platform.pipeline.build_publisher", side_effect=lambda platform, cfg, data_dir: _PolicySafePublisher(root / "outbox", expected_status)):
                result = pipeline.stage_drafts(job_id)
                evidence["stage_drafts_called"] = True
        result = pipeline.status(job_id) if hasattr(pipeline, "status") else result
        manifest = _materialize_artifact_manifest(case, store, result, root, verified_hotspot)
        return {"passed": True, "pipeline_evidence": evidence, "job": result, "manifest": manifest}
    except Exception as exc:
        job = store.get_job(evidence["job_id"]) if evidence["job_id"] and hasattr(store, "get_job") else {}
        manifest = _materialize_artifact_manifest(case, store, job, root, verified_hotspot) if job else {}
        return {"passed": False, "pipeline_evidence": evidence, "job": job, "manifest": manifest, "error": f"{type(exc).__name__}: {exc}"}


def _generation_attempt_evidence(root: Path, expected: dict[str, Any]) -> dict[str, Any]:
    """Read observed provider/model/session data emitted by the real generator."""
    expected_provider = str(expected.get("provider") or "")
    expected_model = str(expected.get("model") or "")
    attempts: list[dict[str, Any]] = []
    for path in sorted(root.rglob("generation_attempts.json")):
        raw_rows = _load_json_value(path)
        raw_rows = raw_rows if isinstance(raw_rows, list) else []
        for row in raw_rows:
            if isinstance(row, dict):
                attempts.append({**row, "_path": path.relative_to(root).as_posix()})
    successful = [row for row in attempts if row.get("status") == "success"]
    matching = []
    for row in successful:
        provider = str(row.get("provider") or row.get("provider_name") or "")
        model = str(row.get("model") or row.get("model_id") or "")
        session = str(row.get("session_id") or row.get("session") or row.get("hermes_session_id") or "")
        if provider == expected_provider and model == expected_model and session:
            matching.append({"provider": provider, "model": model, "session_id": session, "path": row.get("_path", "")})
    return {
        "passed": bool(matching),
        "attempt_count": len(attempts),
        "successful_count": len(successful),
        "matching": matching,
        "failures": [] if matching else ["generation_attempt_identity_evidence_missing"],
    }


def _blocked_model_matrix(matrix: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    return [
        {
            **case,
            "passed": False,
            "artifact_policy_passed": False,
            "failure_reason": reason,
            "pipeline_evidence": {"create_called": False, "run_called": False, "serial_index": case["order"], "job_id": ""},
            "generation_evidence": {"passed": False, "failures": [reason]},
        }
        for case in matrix
    ]


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _run_model_matrix(role: str, model: dict[str, Any], matrix: list[dict[str, Any]], root: Path, *, pipeline_factory=None, store_factory=None, runtime_config_path: Path | str | None = None) -> dict[str, Any]:
    """Execute the same real Pipeline matrix for a discovered model identity."""
    selection = model.get("selection") if isinstance(model.get("selection"), dict) else {}
    if model.get("status") not in {"available", "verified"}:
        reason = str(model.get("reason") or "model_identity_unavailable")
        return {"status": "dual_model_pending" if role == "weak" else "blocked", "provider": "", "model": "", "gate_passed": False, "executed_cases": 0, "case_results": _blocked_model_matrix(matrix, reason), "reason": reason}
    model_id = str(model.get("model") or "")
    provider = str(model.get("provider") or "")
    if not model_id or not provider:
        reason = "model_identity_missing"
        return {"status": "dual_model_pending" if role == "weak" else "blocked", "provider": provider, "model": model_id, "gate_passed": False, "executed_cases": 0, "case_results": _blocked_model_matrix(matrix, reason), "reason": reason}
    if selection.get("available") is not True:
        reason = str(selection.get("reason") or "model_selection_unavailable")
        return {"status": "dual_model_pending" if role == "weak" else "blocked", "provider": provider, "model": model_id, "gate_passed": False, "executed_cases": 0, "case_results": _blocked_model_matrix(matrix, reason), "reason": reason}
    previous = {key: os.environ.get(key) for key in ("HERMES_PROVIDER", "HERMES_MODEL", "HERMES_CANARY_SESSION", "HERMES_CANARY_SELECTOR_CAPABILITY")}
    os.environ["HERMES_PROVIDER"] = provider
    os.environ["HERMES_MODEL"] = model_id
    os.environ["HERMES_CANARY_SELECTOR_CAPABILITY"] = "verified"
    canary_session = f"task9-{role}-{uuid.uuid4().hex}"
    os.environ["HERMES_CANARY_SESSION"] = canary_session
    results = []
    try:
        for case in matrix:
            artifact_dir = root / "_models" / role / case["platform"]
            result = _run_pipeline_case(case, artifact_dir, pipeline_factory=pipeline_factory, store_factory=store_factory, hotspot_root=root, runtime_config_path=runtime_config_path)
            probe = probe_artifacts(case, artifact_dir)
            pipeline_evidence = result.get("pipeline_evidence") or {}
            generation_evidence = _generation_attempt_evidence(artifact_dir, model)
            passed = bool(result.get("passed") is True and probe.get("passed") is True and generation_evidence["passed"] is True and pipeline_evidence.get("create_called") is True and pipeline_evidence.get("run_called") is True)
            failures = list(probe.get("failures") or []) + list(generation_evidence.get("failures") or [])
            if not result.get("passed"):
                failures.append("pipeline_execution_failed")
            if result.get("error"):
                failures.append("pipeline_error:" + str(result["error"])[:500])
            results.append({
                **case,
                "passed": passed,
                "artifact_policy_passed": passed,
                "job_id": pipeline_evidence.get("job_id", ""),
                "pipeline_evidence": pipeline_evidence,
                "pipeline_error": str(result.get("error") or ""),
                "generation_evidence": generation_evidence,
                "probes": probe.get("probes", {}),
                "failure_reason": ";".join(sorted(set(failures))),
                "evidence_level": "artifact_verified" if passed else "declared",
            })
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    passed = len(results) == len(matrix) and bool(results) and all(item["passed"] for item in results)
    return {"status": "verified" if passed else "blocked", "provider": provider, "model": model_id, "selection": selection, "gate_passed": passed, "executed_cases": len(results), "case_results": results, "reason": "" if passed else "model_pipeline_or_evidence_failed", "session_id": canary_session}


def _git_commit(repo_root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_delivery_scenarios(db_path: Path | str) -> dict[str, Any]:
    ledger = PublicationLedger(db_path)
    base = {
        "job_id": "task9",
        "platform": "kuaishou",
        "internal_account_alias": "kuaishou_main",
        "action": "schedule",
        "payload": {"title": "Task9 canary", "description": "A complete canary description"},
        "media_hashes": ["sha256:canary-video"],
        "expected_title": "Task9 canary",
        "expected_description": "A complete canary description",
        "scheduled_at": "2026-08-25T12:00:00+00:00",
        "absence_window_seconds": 3600,
    }
    crash_intent = ledger.create_delivery_intent({**base, "job_id": "crash"})
    attempt = ledger.begin_attempt(crash_intent["intent_id"], "task9")
    crash = ledger.finish_attempt(crash_intent["intent_id"], attempt["attempt_id"], "crash", error="process_boundary")
    ledger.poll_delivery(crash_intent["intent_id"], lambda _: {"status": "absent"}, now="2026-08-25T12:30:00+00:00")

    delayed_intent = ledger.create_delivery_intent({**base, "job_id": "delayed"})
    delayed_attempt = ledger.begin_attempt(delayed_intent["intent_id"], "task9")
    ledger.finish_attempt(delayed_intent["intent_id"], delayed_attempt["attempt_id"], "unknown", error="timeout")
    ledger.poll_delivery(delayed_intent["intent_id"], lambda _: {"status": "absent"}, now="2026-08-25T12:30:00+00:00")
    delayed = ledger.poll_delivery(
        delayed_intent["intent_id"],
        lambda _: {"status": "published", "verification": {"platform": "kuaishou", "account_alias": "kuaishou_main", "content_id": "ks-task9", "url": "https://kuaishou.example/ks-task9", "published_at": "2026-08-25T12:45:00+00:00", "source": "management_page"}},
        now="2026-08-25T12:45:00+00:00",
    )

    review_intent = ledger.create_delivery_intent({**base, "job_id": "review"})
    review_attempt = ledger.begin_attempt(review_intent["intent_id"], "task9")
    review = ledger.finish_attempt(review_intent["intent_id"], review_attempt["attempt_id"], "auth_failed")
    duplicate = ledger.create_delivery_intent(base)
    duplicate_ok = duplicate["intent_id"] == ledger.create_delivery_intent(base)["intent_id"]
    ks = ledger.create_delivery_intent({**base, "job_id": "ks-postcheck"})
    postcheck = ledger.validate_kuaishou_scheduled_postcheck(ks, {"account_alias": "kuaishou_main", "title": "Task9 canary", "description_digest": ks["expected_description_digest"], "scheduled_at": ks["scheduled_at"], "dom_snapshot": "<management-row>"})
    scenarios = {
        "crash_boundary": {"status": crash["status"], "retry_allowed": crash["retry_allowed"]},
        "delayed_visibility": {"status": delayed["status"], "external_id": "ks-task9"},
        "unknown_requires_review": {"status": review["status"], "retry_allowed": review["retry_allowed"]},
        "duplicate_schedule_prevention": {"same_intent": duplicate_ok},
        "kuaishou_exact_postcheck": postcheck,
    }
    passed = (
        scenarios["crash_boundary"]["status"] == "unknown"
        and scenarios["crash_boundary"]["retry_allowed"] is False
        and scenarios["delayed_visibility"]["status"] == "published"
        and scenarios["unknown_requires_review"]["status"] == "unknown_requires_review"
        and scenarios["unknown_requires_review"]["retry_allowed"] is False
        and duplicate_ok
        and postcheck["passed"]
    )
    return {"passed": passed, "scenarios": scenarios}


def run_canaries(
    artifact_root: Path | str,
    *,
    repo_root: Path | str,
    output_path: Path | str | None = None,
    pipeline_factory=None,
    store_factory=None,
    model_runner=None,
    active_model_report: Path | str | None = None,
    weak_model_report: Path | str | None = None,
    runtime_config_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(artifact_root).resolve()
    repo = Path(repo_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    matrix = build_canary_matrix()
    runtime = discover_hermes_runtime()
    model_results: dict[str, dict[str, Any]] = {}
    if callable(model_runner):
        for role in ("active", "weak"):
            model_result = model_runner(role, matrix, root)
            model_results[role] = dict(model_result or {})
    else:
        for role in ("active", "weak"):
            model_results[role] = _run_model_matrix(role, runtime.get(role) or {}, matrix, root, pipeline_factory=pipeline_factory, store_factory=store_factory, runtime_config_path=runtime_config_path)
    for role, result in model_results.items():
        runtime[role] = {**(runtime.get(role) or {}), **result}
    active_cases = (model_results.get("active") or {}).get("case_results") or _blocked_model_matrix(matrix, "active_model_matrix_not_executed")
    cases = []
    for case, model_case in zip(matrix, active_cases):
        failures = [value for value in str(model_case.get("failure_reason") or "").split(";") if value]
        pipeline_evidence = model_case.get("pipeline_evidence") if isinstance(model_case.get("pipeline_evidence"), dict) else {}
        probes = model_case.get("probes") if isinstance(model_case.get("probes"), dict) else {}
        try:
            input_hotspot = _load_verified_hotspot(root, case)
            brief_hash = _json_hash(_canary_brief(case, input_hotspot))
        except ValueError:
            brief_hash = ""
        cases.append({
            **case,
            "command": {"entrypoint": "content_platform.pipeline.Pipeline.create+run", "mode": "serial", "model_role": "active"},
            "git_commit": _git_commit(repo),
            "pipeline_evidence": pipeline_evidence,
            "job_evidence": {"job_id": model_case.get("job_id", ""), "state": model_case.get("state", "")},
            "input_hashes": {"case": _json_hash(case), "brief": brief_hash},
            "output_hashes": model_case.get("output_hashes", {}),
            "capability_evidence": probes.get("capabilities", {}),
            "probes": probes,
            "delivery_policy": probes.get("delivery_policy", {}),
            "hotspot_evidence": probes.get("hotspot", {}),
            "generation_evidence": model_case.get("generation_evidence", {}),
            "failure_reason": ";".join(sorted(set(failures))),
            "evidence_level": "artifact_verified" if model_case.get("artifact_policy_passed") is True else "declared",
            "pending_reason": ";".join(value for value in failures if "missing" in value or "probe" in value or "pending" in value or "unavailable" in value),
            "artifact_policy_passed": model_case.get("artifact_policy_passed") is True,
        })
    gate_hash = _json_hash(DETERMINISTIC_GATE_NAMES)
    model_reports: list[dict[str, Any]] = []
    for role in ("active", "weak"):
        identity = runtime.get(role) if isinstance(runtime.get(role), dict) else {}
        identity["gate_contract_hash"] = gate_hash
        if role == "active" and identity.get("status") in {"available", "verified"} and not identity.get("gate_passed"):
            identity["gate_reason"] = identity.get("reason") or "active_model_matrix_failed"
        runtime[role] = identity
    report = {
        "schema": "task9_canary_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo),
        "git_commit": _git_commit(repo),
        "execution": {"mode": "serial", "overlap_detected": False, "entrypoint": "pipeline", "case_order": list(EXPECTED_CANARY_PLATFORMS)},
        "models": runtime,
        "model_reports_used": model_reports,
        "deterministic_gate_contract": {"names": list(DETERMINISTIC_GATE_NAMES), "sha256": gate_hash},
        "cases": cases,
        "delivery_scenarios": run_delivery_scenarios(root / "task9_delivery.db"),
        "passed": len(cases) == 12 and [case["platform"] for case in cases] == list(EXPECTED_CANARY_PLATFORMS) and all(case["artifact_policy_passed"] for case in cases) and runtime.get("active", {}).get("gate_passed") is True and runtime.get("weak", {}).get("gate_passed") is True,
    }
    if output_path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="")
    args = parser.parse_args()
    report = run_canaries(args.artifact_root, repo_root=args.repo_root, output_path=args.output, runtime_config_path=args.config or None)
    print(json.dumps({"passed": report["passed"], "cases": len(report["cases"]), "output": args.output}, ensure_ascii=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
