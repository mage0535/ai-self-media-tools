"""Task9 serial canary runner and evidence probes.

This module is intentionally an acceptance-layer script. It invokes the real
project CLI in a subprocess and only upgrades evidence after reading artifacts.
It never publishes, edits timers, or treats planned metadata as artifact proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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


CANARY_PLATFORMS = (
    ("douyin", "vertical_video", "zh", "manual_handoff_only", False),
    ("kuaishou", "vertical_video", "zh", "dry_run", True),
    ("shipinhao", "vertical_video", "zh", "manual_handoff_only", False),
    ("wechat", "article", "zh", "draft_first", False),
    ("xiaohongshu", "carousel", "zh", "manual_handoff_only", False),
    ("juejin", "article", "zh", "draft_first", False),
    ("zhihu", "article", "zh", "draft_first", True),
    ("bilibili", "horizontal_video", "zh", "manual_handoff_only", False),
    ("tiktok", "vertical_video", "en", "manual_handoff_only", False),
    ("youtube", "horizontal_video", "en", "manual_handoff_only", False),
    ("twitter", "carousel", "en", "dry_run", True),
    ("devto", "article", "en", "draft_first", False),
)
DETERMINISTIC_GATE_NAMES = (
    "artifact_hashes",
    "capability_evidence",
    "media_probes",
    "delivery_policy",
    "hotspot_evidence",
    "handoff_render_contract",
)


def build_canary_matrix() -> list[dict[str, Any]]:
    """Return the fixed serial matrix without embedding model/provider data."""
    return [
        {
            "order": index,
            "platform": platform,
            "content_form": content_form,
            "language": language,
            "delivery_policy": policy,
            "dry_run": dry_run,
            "hotspot_mode": "official_native",
            "entrypoint": [sys.executable, "-m", "content_platform.cli", "project-audit"],
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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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
        elif item.get("state") == "artifact_verified" and not item.get("output_hash"):
            capability_failures.append(f"capability_artifact_hash_missing:{item.get('id', '')}")
    if not capabilities:
        capability_failures.append("capability_evidence_missing")
    probes["capabilities"] = _probe("capabilities", not capability_failures, details={"count": len(capabilities)}, failures=capability_failures, level="artifact_verified" if not capability_failures else "declared")
    failures.extend(capability_failures)

    hotspot = manifest.get("hotspot") if isinstance(manifest.get("hotspot"), dict) else {}
    hotspot_failures = []
    if hotspot.get("mode") != "official_native" or hotspot.get("platform") != case.get("platform"):
        hotspot_failures.append("hotspot_not_platform_native")
    if not str(hotspot.get("source_url") or "").startswith(("https://", "http://")):
        hotspot_failures.append("hotspot_source_missing")
    if not str(hotspot.get("observed_title") or "").strip():
        hotspot_failures.append("hotspot_observation_missing")
    probes["hotspot"] = _probe("hotspot", not hotspot_failures, details=hotspot, failures=hotspot_failures, level="artifact_verified" if not hotspot_failures else "declared")
    failures.extend(hotspot_failures)

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
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def discover_hermes_runtime() -> dict[str, Any]:
    """Discover runtime identity; never supplies a pinned fallback identity."""
    executable = os.environ.get("HERMES_CLI", "hermes").strip() or "hermes"
    if not shutil.which(executable) and not Path(executable).is_file():
        return {"active": {"status": "unavailable", "provider": "", "model": "", "reason": "hermes_cli_unavailable"}, "weak": {"status": "dual_model_pending", "reason": "hermes_cli_unavailable"}}
    status = _hermes_json([executable, "status", "--json"])
    models = _hermes_json([executable, "models", "--json"])
    active = status.get("active") if isinstance(status.get("active"), dict) else status
    provider = str(active.get("provider") or status.get("provider") or os.environ.get("HERMES_PROVIDER", ""))
    model = str(active.get("model") or active.get("model_id") or status.get("model") or os.environ.get("HERMES_MODEL", ""))
    result = {"active": {"status": "verified" if provider or model else "unavailable", "provider": provider, "model": model, "gate_passed": False, "gate_reason": "model_gate_report_missing"}}
    candidates = models.get("models") if isinstance(models.get("models"), list) else []
    weak = next((item for item in candidates if isinstance(item, dict) and str(item.get("id") or item.get("model") or "") not in {model, ""}), None)
    if weak:
        result["weak"] = {"status": "available", "provider": str(weak.get("provider") or ""), "model": str(weak.get("id") or weak.get("model") or ""), "gate_passed": False, "gate_reason": "model_gate_report_missing"}
    else:
        result["weak"] = {"status": "dual_model_pending", "reason": "no_available_second_model", "gate_passed": False}
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


def run_canaries(artifact_root: Path | str, *, repo_root: Path | str, output_path: Path | str | None = None, active_model_report: Path | str | None = None, weak_model_report: Path | str | None = None) -> dict[str, Any]:
    root = Path(artifact_root).resolve()
    repo = Path(repo_root).resolve()
    runtime = discover_hermes_runtime()
    cases = []
    for case in build_canary_matrix():
        artifact_dir = root / case["platform"]
        entrypoint = _run_entrypoint(case, repo)
        probe = probe_artifacts(case, artifact_dir)
        policy_passed = probe["probes"].get("delivery_policy", {}).get("passed", False)
        case_result = {
            **case,
            "command": entrypoint,
            "git_commit": _git_commit(repo),
            "input_hashes": {"case": _json_hash(case), "artifact_manifest": probe.get("manifest_sha256", "")},
            "output_hashes": probe["input_output_hashes"],
            "capability_evidence": probe["probes"].get("capabilities", {}),
            "probes": probe["probes"],
            "delivery_policy": probe["probes"].get("delivery_policy", {}),
            "hotspot_evidence": probe["probes"].get("hotspot", {}),
            "failure_reason": ";".join(probe["failures"] + (["entrypoint_failed"] if not entrypoint["passed"] else [])),
            "evidence_level": "artifact_verified" if probe["passed"] else "declared",
            "pending_reason": ";".join(value for value in probe["failures"] if "missing" in value or "probe" in value),
            "artifact_policy_passed": bool(entrypoint["passed"] and probe["passed"] and policy_passed),
        }
        cases.append(case_result)
    gate_hash = _json_hash(DETERMINISTIC_GATE_NAMES)
    _apply_model_gate_report(runtime, "active", active_model_report, gate_hash)
    _apply_model_gate_report(runtime, "weak", weak_model_report, gate_hash)
    report = {
        "schema": "task9_canary_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo),
        "git_commit": _git_commit(repo),
        "execution": "serial",
        "models": runtime,
        "deterministic_gate_contract": {"names": list(DETERMINISTIC_GATE_NAMES), "sha256": gate_hash},
        "cases": cases,
        "delivery_scenarios": run_delivery_scenarios(root / "task9_delivery.db"),
        "passed": len(cases) == 12 and all(case["artifact_policy_passed"] for case in cases),
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
    parser.add_argument("--active-model-report")
    parser.add_argument("--weak-model-report")
    args = parser.parse_args()
    report = run_canaries(args.artifact_root, repo_root=args.repo_root, output_path=args.output, active_model_report=args.active_model_report, weak_model_report=args.weak_model_report)
    print(json.dumps({"passed": report["passed"], "cases": len(report["cases"]), "output": args.output}, ensure_ascii=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
