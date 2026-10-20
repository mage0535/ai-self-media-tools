"""Recoverable, fail-closed local repost workflow.

This module is intentionally platform-agnostic.  It owns stage orchestration,
content-addressed evidence, leases, and the local TikTok -> Douyin handoff
contract; it never downloads from a platform and never publishes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from typing import Any, Callable, Iterable, Mapping

SCHEMA_VERSION = "repost_workflow_v1"
CACHE_SCHEMA_VERSION = "repost_cache_v1"
LEASE_SCHEMA_VERSION = "stage_lease_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def atomic_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def content_cache_key(**fields: Any) -> str:
    """Return a full SHA-256 key from every meaningful render input."""
    required = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "source_asset_sha256": "",
        "script_hash": "",
        "shot_spec_hash": "",
        "narration_text_hash": "",
        "tts_provider": "",
        "tts_model": "",
        "tts_voice": "",
        "tts_parameters": {},
        "tts_sample_rate": 0,
        "subtitle_key": "",
        "intro_frame_key": "",
        "outro_frame_key": "",
        "transform_ledger_hash": "",
        "cover_contract_hash": "",
        "renderer_source_hash": "",
        "browser_version_or_binary_hash": "",
        "font_hash": "",
        "gate_version": "",
        "width": 0,
        "height": 0,
        "fps": 0,
        "codec": "",
        "pixel_format": "",
        "render_mode": "",
        "bgm_sha256": "",
        "final_mux_parameters": {},
    }
    required.update(fields)
    return sha256_bytes(canonical_json(required))


class RepostState(str, Enum):
    INIT = "INIT"
    SOURCE_REGISTERED = "SOURCE_REGISTERED"
    SCRIPT_READY = "SCRIPT_READY"
    TTS_READY = "TTS_READY"
    VISUAL_PLAN_READY = "VISUAL_PLAN_READY"
    COVER_READY = "COVER_READY"
    INTRO_OUTRO_READY = "INTRO_OUTRO_READY"
    INTERNAL_DUP_CHECKED = "INTERNAL_DUP_CHECKED"
    TIMELINE_VERIFIED = "TIMELINE_VERIFIED"
    NARRATION_VERIFIED = "NARRATION_VERIFIED"
    PREFLIGHT_PASSED = "PREFLIGHT_PASSED"
    RENDERING = "RENDERING"
    MUXED = "MUXED"
    DEEP_QA_PASSED = "DEEP_QA_PASSED"
    HANDOFF_READY = "HANDOFF_READY"
    RIGHTS_EXTERNAL_PENDING = "RIGHTS_EXTERNAL_PENDING"
    PUBLISHED_USER_VERIFIED = "PUBLISHED_USER_VERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


_TERMINAL = {RepostState.BLOCKED, RepostState.FAILED, RepostState.PUBLISHED_USER_VERIFIED}
_ALLOWED: dict[RepostState, set[RepostState]] = {
    RepostState.INIT: {RepostState.SOURCE_REGISTERED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.SOURCE_REGISTERED: {RepostState.SCRIPT_READY, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.SCRIPT_READY: {
        RepostState.TTS_READY, RepostState.VISUAL_PLAN_READY, RepostState.COVER_READY,
        RepostState.INTRO_OUTRO_READY, RepostState.BLOCKED, RepostState.FAILED,
    },
    RepostState.TTS_READY: {RepostState.VISUAL_PLAN_READY, RepostState.COVER_READY, RepostState.INTRO_OUTRO_READY, RepostState.INTERNAL_DUP_CHECKED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.VISUAL_PLAN_READY: {RepostState.TTS_READY, RepostState.COVER_READY, RepostState.INTRO_OUTRO_READY, RepostState.INTERNAL_DUP_CHECKED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.COVER_READY: {RepostState.TTS_READY, RepostState.VISUAL_PLAN_READY, RepostState.INTRO_OUTRO_READY, RepostState.INTERNAL_DUP_CHECKED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.INTRO_OUTRO_READY: {RepostState.TTS_READY, RepostState.VISUAL_PLAN_READY, RepostState.COVER_READY, RepostState.INTERNAL_DUP_CHECKED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.INTERNAL_DUP_CHECKED: {RepostState.TIMELINE_VERIFIED, RepostState.NARRATION_VERIFIED, RepostState.PREFLIGHT_PASSED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.TIMELINE_VERIFIED: {RepostState.NARRATION_VERIFIED, RepostState.PREFLIGHT_PASSED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.NARRATION_VERIFIED: {RepostState.TIMELINE_VERIFIED, RepostState.PREFLIGHT_PASSED, RepostState.DEEP_QA_PASSED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.PREFLIGHT_PASSED: {RepostState.RENDERING, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.RENDERING: {RepostState.MUXED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.MUXED: {RepostState.TIMELINE_VERIFIED, RepostState.NARRATION_VERIFIED, RepostState.DEEP_QA_PASSED, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.DEEP_QA_PASSED: {RepostState.HANDOFF_READY, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.HANDOFF_READY: {RepostState.RIGHTS_EXTERNAL_PENDING, RepostState.BLOCKED, RepostState.FAILED},
    RepostState.RIGHTS_EXTERNAL_PENDING: set(),
    RepostState.PUBLISHED_USER_VERIFIED: set(),
    RepostState.BLOCKED: set(),
    RepostState.FAILED: set(),
}


class WorkflowError(RuntimeError):
    pass


class UnknownStateError(WorkflowError):
    pass


class StageName(str, Enum):
    SOURCE_REGISTER = "source_register"
    TOPIC_AND_SCRIPT = "topic_and_script"
    TTS = "tts"
    SOURCE_ANALYSIS = "source_analysis"
    COVER = "cover"
    ASSET_PREPARE = "asset_prepare"
    SUBTITLES = "subtitles"
    TRANSFORM_PLAN = "transform_plan"
    INTRO_OUTRO = "intro_outro"
    PREFLIGHT = "preflight"
    RENDERING = "rendering"
    MUX = "mux"
    DEEP_QUALITY_GATE = "deep_quality_gate"
    HANDOFF_BUNDLE = "handoff_bundle"


STAGE_DEPS: dict[StageName, tuple[StageName, ...]] = {
    StageName.SOURCE_REGISTER: (),
    StageName.TOPIC_AND_SCRIPT: (StageName.SOURCE_REGISTER,),
    StageName.TTS: (StageName.TOPIC_AND_SCRIPT,),
    StageName.SOURCE_ANALYSIS: (StageName.TOPIC_AND_SCRIPT,),
    StageName.COVER: (StageName.TOPIC_AND_SCRIPT,),
    StageName.ASSET_PREPARE: (StageName.TOPIC_AND_SCRIPT,),
    StageName.SUBTITLES: (StageName.TTS,),
    StageName.TRANSFORM_PLAN: (StageName.SOURCE_ANALYSIS,),
    StageName.INTRO_OUTRO: (StageName.TOPIC_AND_SCRIPT,),
    StageName.PREFLIGHT: (StageName.TTS, StageName.SOURCE_ANALYSIS, StageName.COVER, StageName.ASSET_PREPARE, StageName.SUBTITLES, StageName.TRANSFORM_PLAN, StageName.INTRO_OUTRO),
    StageName.RENDERING: (StageName.PREFLIGHT,),
    StageName.MUX: (StageName.RENDERING,),
    StageName.DEEP_QUALITY_GATE: (StageName.MUX,),
    StageName.HANDOFF_BUNDLE: (StageName.DEEP_QUALITY_GATE,),
}


def _descendants(stage: StageName) -> set[StageName]:
    result = {stage}
    changed = True
    while changed:
        changed = False
        for candidate, deps in STAGE_DEPS.items():
            if candidate not in result and any(dep in result for dep in deps):
                result.add(candidate)
                changed = True
    return result


def _stage_hash(paths: Iterable[str | Path], payload: Mapping[str, Any] | None = None) -> str:
    records: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        records.append({"path": str(path.resolve()), "sha256": sha256_file(path) if path.is_file() else "MISSING"})
    return sha256_bytes(canonical_json({"files": records, "payload": dict(payload or {})}))


@dataclass
class SourceLedger:
    source_id: str
    source_platform: str
    source_uri: str
    source_content_id: str
    source_creator: str
    source_title: str
    retrieved_at: str
    source_sha256: str
    source_duration: float
    source_resolution: str
    rights_status: str = "external_manual_pending"
    rights_note: str = "Manual rights confirmation required outside automation."
    acquisition_status: str = "provided_local_fixture"
    source_manifest_path: str = ""

    @classmethod
    def from_file(cls, path: str | Path, *, source_uri: str, source_content_id: str, source_creator: str, source_title: str, source_id: str = "") -> "SourceLedger":
        candidate = Path(path).resolve()
        if not candidate.is_file():
            raise WorkflowError(f"source file missing: {candidate}")
        duration, resolution = probe_media(candidate)
        return cls(
            source_id=source_id or f"src_{sha256_file(candidate)[:16]}",
            source_platform="tiktok",
            source_uri=str(source_uri),
            source_content_id=str(source_content_id),
            source_creator=str(source_creator),
            source_title=str(source_title),
            retrieved_at=utc_now(),
            source_sha256=sha256_file(candidate),
            source_duration=duration,
            source_resolution=resolution,
            rights_status="external_manual_pending",
            rights_note="Automation does not contact the author or assert authorization.",
            acquisition_status="provided_local_file",
        )

    def validate(self) -> list[str]:
        failures: list[str] = []
        required = ("source_id", "source_platform", "source_uri", "source_content_id", "source_creator", "source_title", "retrieved_at", "source_sha256", "source_resolution", "source_manifest_path")
        failures.extend(f"missing:{field}" for field in required if not str(getattr(self, field, "") or "").strip())
        if self.source_platform != "tiktok":
            failures.append("source_platform_must_be_tiktok")
        if self.rights_status != "external_manual_pending":
            failures.append("rights_status_must_remain_external_manual_pending")
        if self.source_duration <= 0:
            failures.append("source_duration_invalid")
        if not self.source_uri or not self.source_content_id:
            failures.append("source_unverified")
        return sorted(set(failures))

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass
class TransformationLedger:
    entries: list[dict[str, Any]] = field(default_factory=list)
    reviewer_decision: str = "pending_manual_review"

    def add(self, *, segment: str, edit_type: str, reason: str, content_impact: str, quality_check: str, manual_review: str = "pending") -> None:
        if not all(str(item).strip() for item in (segment, edit_type, reason, content_impact, quality_check, manual_review)):
            raise WorkflowError("transformation ledger entries require complete fields")
        self.entries.append({"segment": segment, "edit_type": edit_type, "reason": reason, "content_impact": content_impact, "quality_check": quality_check, "manual_review": manual_review})

    def validate(self) -> list[str]:
        failures: list[str] = []
        for index, entry in enumerate(self.entries):
            for field_name in ("segment", "edit_type", "reason", "content_impact", "quality_check", "manual_review"):
                if not str(entry.get(field_name) or "").strip():
                    failures.append(f"entry_{index}_{field_name}_missing")
        if not self.entries:
            failures.append("transformation_ledger_empty")
        if self.reviewer_decision not in {"pending_manual_review", "accepted", "rejected"}:
            failures.append("reviewer_decision_invalid")
        return sorted(set(failures))

    def to_dict(self) -> dict[str, Any]:
        return {"version": "transformation_ledger_v1", "entries": list(self.entries), "reviewer_decision": self.reviewer_decision}


@dataclass
class StageRecord:
    stage: str
    status: str
    attempt: int
    started_at: str
    finished_at: str
    monotonic_duration_ms: int
    input_sha256: str
    output_sha256: str
    cache_hit: bool
    error_code: str
    error_message: str
    evidence_paths: list[str]
    next_action: str
    cache_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


class StageLease:
    """Short stage lease with PID/expiry/fencing checks; never blind-deletes locks."""

    def __init__(self, root: str | Path, stage: str, *, ttl_seconds: int = 300, owner_pid: int | None = None, hostname: str = ""):
        self.root = Path(root).resolve()
        self.stage = str(stage)
        self.ttl_seconds = int(ttl_seconds)
        self.owner_pid = int(owner_pid or os.getpid())
        self.hostname = hostname or os.uname().nodename
        self.path = self.root / ".leases" / f"{self.stage}.lock"
        self.token = ""

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def acquire(self, *, input_key: str = "", output_dir: str | Path = "") -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        existing = self._read() if self.path.exists() else {}
        expires = float(existing.get("lease_expires_at") or 0)
        if existing and (self._pid_alive(int(existing.get("owner_pid") or 0)) or expires > now):
            raise WorkflowError(f"stage lease busy: {self.stage}")
        if existing:
            # Reclaim only a provably stale lease: owner is gone and TTL expired.
            # Never remove a live or merely malformed lease as a shortcut.
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise WorkflowError(f"cannot reclaim stale stage lease: {self.stage}") from exc
        self.token = uuid.uuid4().hex
        payload = {
            "schema_version": LEASE_SCHEMA_VERSION,
            "lock_key": f"{self.root}:{self.stage}",
            "owner_pid": self.owner_pid,
            "hostname": self.hostname,
            "stage": self.stage,
            "acquired_at": utc_now(),
            "heartbeat_at": utc_now(),
            "lease_expires_at": now + self.ttl_seconds,
            "fencing_token": self.token,
            "input_key": input_key,
            "output_dir": str(output_dir),
        }
        descriptor = None
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise WorkflowError(f"stage lease raced: {self.stage}") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            self.path.unlink(missing_ok=True)
            raise
        return payload

    def heartbeat(self) -> bool:
        current = self._read()
        if current.get("fencing_token") != self.token or current.get("owner_pid") != self.owner_pid:
            return False
        current["heartbeat_at"] = utc_now()
        current["lease_expires_at"] = time.time() + self.ttl_seconds
        atomic_json(self.path, current)
        return True

    def release(self) -> bool:
        current = self._read()
        if current.get("fencing_token") != self.token or current.get("owner_pid") != self.owner_pid:
            return False
        self.path.unlink(missing_ok=True)
        return True

    def __enter__(self) -> "StageLease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class StageDAG:
    def __init__(self, records: Mapping[str, Mapping[str, Any]] | None = None):
        self.records: dict[str, dict[str, Any]] = {str(k): dict(v) for k, v in (records or {}).items()}

    @staticmethod
    def normalize(stage: str | StageName) -> StageName:
        try:
            return stage if isinstance(stage, StageName) else StageName(str(stage))
        except ValueError as exc:
            raise WorkflowError(f"unknown stage: {stage}") from exc

    def dependencies(self, stage: str | StageName) -> tuple[str, ...]:
        return tuple(item.value for item in STAGE_DEPS[self.normalize(stage)])

    def dependency_closure(self, stage: str | StageName) -> list[str]:
        return [item.value for item in sorted(_descendants(self.normalize(stage)), key=lambda item: list(StageName).index(item))]

    def can_run(self, stage: str | StageName) -> tuple[bool, list[str]]:
        name = self.normalize(stage).value
        missing = [dep.value for dep in STAGE_DEPS[self.normalize(stage)] if self.records.get(dep.value, {}).get("status") != "SUCCEEDED"]
        return not missing, missing

    def record(self, stage: str | StageName) -> dict[str, Any]:
        return dict(self.records.get(self.normalize(stage).value, {}))


class RepostRun:
    """Persistent run state and stage execution facade."""

    def __init__(self, run_dir: str | Path, *, create: bool = True):
        self.run_dir = Path(run_dir).resolve()
        if create:
            self.run_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.run_dir / "checkpoint.json"
        self.stage_log_path = self.run_dir / "stage_records.jsonl"
        if self.checkpoint_path.is_file():
            self.data = self._load_checkpoint()
        else:
            self.data = {"schema_version": SCHEMA_VERSION, "run_id": self.run_dir.name, "state": RepostState.INIT.value, "stages": {}, "created_at": utc_now(), "updated_at": utc_now(), "platform": "douyin", "source_platform": "tiktok"}
            self._save()
        self.dag = StageDAG(self.data.get("stages"))

    def _load_checkpoint(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"checkpoint invalid: {self.checkpoint_path}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise WorkflowError("checkpoint schema invalid")
        try:
            RepostState(str(payload.get("state")))
        except ValueError as exc:
            raise UnknownStateError(f"unknown persisted state: {payload.get('state')}") from exc
        return payload

    @property
    def state(self) -> RepostState:
        try:
            return RepostState(str(self.data.get("state")))
        except ValueError as exc:
            raise UnknownStateError(f"unknown state: {self.data.get('state')}") from exc

    def _save(self) -> None:
        self.data["updated_at"] = utc_now()
        self.data["stages"] = self.dag.records if hasattr(self, "dag") else self.data.get("stages", {})
        atomic_json(self.checkpoint_path, self.data)

    def transition(self, target: str | RepostState, *, human_verified: bool = False, evidence: Mapping[str, Any] | None = None) -> None:
        target_state = target if isinstance(target, RepostState) else RepostState(str(target))
        current = self.state
        if target_state is RepostState.PUBLISHED_USER_VERIFIED and not human_verified:
            raise WorkflowError("PUBLISHED_USER_VERIFIED requires explicit human verification")
        if target_state not in _ALLOWED.get(current, set()):
            raise WorkflowError(f"illegal transition: {current.value} -> {target_state.value}")
        if target_state is RepostState.HANDOFF_READY:
            if not (self.data.get("publishable") is False and self.data.get("manual_publish_required") is True):
                raise WorkflowError("handoff cannot be ready without publishable=false and manual_publish_required=true")
        self.data["state"] = target_state.value
        if evidence:
            self.data.setdefault("state_evidence", {})[target_state.value] = dict(evidence)
        self._save()

    def set_flags(self, **flags: Any) -> None:
        self.data.update(flags)
        self._save()

    def write_json(self, name: str, payload: Mapping[str, Any]) -> Path:
        path = self.run_dir / name
        atomic_json(path, payload)
        return path

    def execute_stage(self, stage: str | StageName, *, input_paths: Iterable[str | Path] = (), input_payload: Mapping[str, Any] | None = None, output_paths: Iterable[str | Path] = (), cache_key: str = "", evidence_paths: Iterable[str | Path] = (), func: Callable[[], Any]) -> Any:
        name = self.dag.normalize(stage).value
        can_run, missing = self.dag.can_run(name)
        if not can_run:
            raise WorkflowError(f"dependencies not satisfied for {name}: {','.join(missing)}")
        inputs = [Path(item) for item in input_paths]
        outputs = [Path(item) for item in output_paths]
        input_hash = _stage_hash(inputs, input_payload)
        old = self.dag.record(name)
        attempt = int(old.get("attempt") or 0) + 1
        if old.get("status") == "SUCCEEDED" and old.get("input_sha256") == input_hash and (not cache_key or old.get("cache_key") == cache_key) and all(path.is_file() for path in outputs):
            record = StageRecord(name, "SUCCEEDED", attempt, utc_now(), utc_now(), 0, input_hash, str(old.get("output_sha256") or _stage_hash(outputs)), True, "", "", list(map(str, evidence_paths)), "reused", cache_key)
            self.dag.records[name] = record.to_dict()
            self._save()
            return {"cache_hit": True, "outputs": [str(path) for path in outputs]}
        lease = StageLease(self.run_dir, name)
        started = utc_now()
        mono = time.monotonic()
        try:
            lease.acquire(input_key=cache_key, output_dir=self.run_dir)
            result = func()
            missing_outputs = [str(path) for path in outputs if not path.is_file()]
            if missing_outputs:
                raise WorkflowError(f"stage outputs missing: {','.join(missing_outputs)}")
            output_hash = _stage_hash(outputs)
            record = StageRecord(name, "SUCCEEDED", attempt, started, utc_now(), int((time.monotonic() - mono) * 1000), input_hash, output_hash, False, "", "", list(map(str, evidence_paths)), "next", cache_key)
            self.dag.records[name] = record.to_dict()
            self._save()
            return result
        except Exception as exc:
            record = StageRecord(name, "FAILED", attempt, started, utc_now(), int((time.monotonic() - mono) * 1000), input_hash, "", False, type(exc).__name__, str(exc), list(map(str, evidence_paths)), "repair_or_retry", cache_key)
            self.dag.records[name] = record.to_dict()
            self.data["last_error"] = record.to_dict()
            self._save()
            raise
        finally:
            lease.release()

    def invalidate_from(self, stage: str | StageName) -> list[str]:
        normalized = self.dag.normalize(stage)
        names = self.dag.dependency_closure(normalized)
        # Cover and subtitle changes invalidate their gates and handoff evidence,
        # but not the browser/scene render when its own content key is unchanged.
        preserve_render = normalized in {StageName.COVER, StageName.SUBTITLES}
        preserved = {StageName.RENDERING.value, StageName.MUX.value} if preserve_render else set()
        for name in names:
            if name not in preserved:
                self.dag.records.pop(name, None)
        self.data["invalidated_stages"] = [name for name in names if name not in preserved]
        self._save()
        return names

    def status(self) -> dict[str, Any]:
        return {"run_id": self.data.get("run_id"), "state": self.state.value, "stages": self.dag.records, "last_error": self.data.get("last_error", {}), "publishable": self.data.get("publishable"), "manual_publish_required": self.data.get("manual_publish_required"), "rights_status": self.data.get("rights_status")}


def probe_media(path: str | Path) -> tuple[float, str]:
    candidate = Path(path)
    try:
        process = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "json", str(candidate)], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowError(f"ffprobe unavailable: {exc}") from exc
    if process.returncode != 0:
        raise WorkflowError(f"ffprobe failed: {(process.stderr or '')[-500:]}")
    try:
        payload = json.loads(process.stdout)
        duration = float(payload.get("format", {}).get("duration") or 0)
        stream = next((item for item in payload.get("streams", []) if item.get("width") and item.get("height")), {})
        resolution = f"{int(stream.get('width'))}x{int(stream.get('height'))}" if stream else "unknown"
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WorkflowError("ffprobe returned invalid media metadata") from exc
    if duration <= 0:
        raise WorkflowError("media duration must be positive")
    return duration, resolution


def validate_timeline(timeline: Mapping[str, Any], final_duration: float) -> dict[str, Any]:
    failures: list[str] = []
    intro = (timeline.get("intro") if isinstance(timeline.get("intro"), Mapping) else {}) or {}
    outro = (timeline.get("outro") if isinstance(timeline.get("outro"), Mapping) else {}) or {}
    main = (timeline.get("main_content") if isinstance(timeline.get("main_content"), Mapping) else {}) or {}
    last_narration_end = float(timeline.get("last_narration_end") or 0)
    intro_start = float(intro.get("start", -1))
    intro_duration = float(intro.get("duration_actual", 0))
    outro_start = float(outro.get("start_actual", -1))
    outro_duration = float(outro.get("duration_actual", 0))
    main_end = float(main.get("end", 0))
    if intro_start != 0:
        failures.append("intro_must_start_at_zero")
    if intro_duration < 1.0:
        failures.append("intro_duration_below_one_second")
    if outro_start < main_end or outro_start < 0:
        failures.append("outro_must_follow_main_content")
    if outro_duration < float(outro.get("minimum_duration") or 2.0):
        failures.append("outro_duration_below_minimum")
    if last_narration_end > final_duration + 0.05:
        failures.append("narration_extends_beyond_video")
    if outro_start + outro_duration > final_duration + 0.05:
        failures.append("outro_extends_beyond_video")
    declared = float(timeline.get("final_video_duration") or 0)
    if declared <= 0 or abs(declared - final_duration) > 0.1:
        failures.append("timeline_final_duration_mismatch")
    breakdown = {
        "narration_duration": float(timeline.get("narration_duration") or 0),
        "scene_content_duration": max(0.0, main_end - float(main.get("start") or 0)),
        "intro_duration": intro_duration,
        "outro_duration": outro_duration,
        "padding_duration": max(0.0, final_duration - last_narration_end),
        "final_video_duration": final_duration,
    }
    return {"passed": not failures, "failures": sorted(set(failures)), "breakdown": breakdown}


def validate_narration_manifest(narration: Mapping[str, Any], final_duration: float) -> dict[str, Any]:
    failures: list[str] = []
    segments = narration.get("segments") if isinstance(narration.get("segments"), list) else []
    if not segments:
        failures.append("narration_segments_missing")
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping):
            failures.append(f"narration_segment_{index}_invalid")
            continue
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or 0)
        if end <= start or end > final_duration + 0.05:
            failures.append(f"narration_segment_{index}_outside_final_video")
        if not str(segment.get("text") or "").strip():
            failures.append(f"narration_segment_{index}_text_missing")
    audio_path = Path(str(narration.get("audio_path") or ""))
    if not audio_path.is_file():
        failures.append("narration_audio_missing")
    elif narration.get("audio_sha256") != sha256_file(audio_path):
        failures.append("narration_audio_hash_mismatch")
    return {"passed": not failures, "failures": sorted(set(failures))}


def build_repost_evidence_bundle(run: RepostRun, source_manifest: Mapping[str, Any], transform_ledger: Mapping[str, Any], narration_manifest: Mapping[str, Any], timeline_manifest: Mapping[str, Any], similarity_report: Mapping[str, Any], *, cover_evidence: Mapping[str, Any] | None = None, final_video: str | Path = "", cover: str | Path = "") -> dict[str, Any]:
    final_path = Path(final_video).resolve() if final_video else None
    cover_path = Path(cover).resolve() if cover else None
    bundle = {
        "version": "repost_evidence_bundle_v1",
        "run_id": run.data.get("run_id"),
        "source_manifest": dict(source_manifest),
        "transformation_ledger": dict(transform_ledger),
        "narration_manifest": dict(narration_manifest),
        "timeline_manifest": dict(timeline_manifest),
        "similarity_report": dict(similarity_report),
        "cover_evidence": dict(cover_evidence or {}),
        "final_video": {"path": str(final_path) if final_path else "", "sha256": sha256_file(final_path) if final_path and final_path.is_file() else ""},
        "cover": {"path": str(cover_path) if cover_path else "", "sha256": sha256_file(cover_path) if cover_path and cover_path.is_file() else ""},
        "manual_rights_confirmation_required": True,
        "publishable": False,
        "manual_publish_required": True,
        "platform_publish_not_attempted": True,
    }
    return bundle


def validate_similarity_report(report: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if report.get("reviewer_decision") not in {"pass", "MANUAL_REVIEW_REQUIRED", "BLOCKED_INTERNAL_SIMILARITY"}:
        failures.append("reviewer_decision_missing")
    for key in ("source_video_sha256", "candidate_video_sha256", "source_frame_fingerprint", "candidate_frame_fingerprint", "source_audio_fingerprint", "candidate_audio_fingerprint", "source_segment_to_output_segment_mapping", "similarity_scores", "threshold_version", "model_version", "transformation_ledger"):
        if key not in report:
            failures.append(f"similarity_{key}_missing")
    if report.get("reviewer_decision") in {"MANUAL_REVIEW_REQUIRED", "BLOCKED_INTERNAL_SIMILARITY"}:
        return {"passed": False, "failures": sorted(set(failures + [str(report.get("reviewer_decision"))]))}
    return {"passed": not failures, "failures": sorted(set(failures))}


def validate_handoff_directory(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    required = ("final.mp4", "cover.png", "script.md", "intro_frame.png", "outro_frame.png", "source_manifest.json", "scene_manifest.json", "transformation_ledger.json", "narration_manifest.json", "timeline_manifest.json", "similarity_report.json", "cover_evidence.json", "performance_manifest.json", "final_delivery_manifest.json", "manual_rights_confirmation.md", "manual_publish_checklist.md")
    failures = [f"missing:{name}" for name in required if not (root / name).is_file()]
    manifest_path = root / "final_delivery_manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append("final_delivery_manifest_invalid")
    if manifest.get("publishable") is not False:
        failures.append("publishable_must_be_false")
    if manifest.get("manual_publish_required") is not True:
        failures.append("manual_publish_required_missing")
    if manifest.get("rights_status") != "external_manual_pending":
        failures.append("rights_status_invalid")
    if manifest.get("source_platform") != "tiktok" or manifest.get("target_platform") != "douyin":
        failures.append("platform_boundary_invalid")
    if manifest.get("platform_publish_not_attempted") is not True:
        failures.append("platform_publish_not_attempted_missing")
    if manifest.get("state") not in {RepostState.RIGHTS_EXTERNAL_PENDING.value, RepostState.HANDOFF_READY.value}:
        failures.append("handoff_state_invalid")
    artifacts = (manifest.get("artifacts") if isinstance(manifest.get("artifacts"), Mapping) else {}) or {}
    for name, declared in artifacts.items():
        artifact_path = root / str(name)
        if not artifact_path.is_file():
            failures.append(f"artifact_missing:{name}")
        elif str(declared) != sha256_file(artifact_path):
            failures.append(f"artifact_hash_mismatch:{name}")
    final_video = root / "final.mp4"
    if final_video.is_file():
        try:
            duration, _ = probe_media(final_video)
            timeline = json.loads((root / "timeline_manifest.json").read_text(encoding="utf-8"))
            timeline_result = validate_timeline(timeline, duration)
            failures.extend(timeline_result["failures"])
        except (WorkflowError, OSError, json.JSONDecodeError) as exc:
            failures.append(f"timeline_validation_error:{type(exc).__name__}")
    return {"passed": not failures, "failures": sorted(set(failures)), "root": str(root)}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


__all__ = ["CACHE_SCHEMA_VERSION", "RepostState", "StageName", "StageDAG", "StageLease", "StageRecord", "SourceLedger", "TransformationLedger", "RepostRun", "WorkflowError", "UnknownStateError", "content_cache_key", "validate_timeline", "validate_narration_manifest", "build_repost_evidence_bundle", "validate_similarity_report", "validate_handoff_directory", "probe_media", "percentile", "sha256_file", "atomic_json"]
