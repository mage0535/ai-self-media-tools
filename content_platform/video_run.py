"""Trustworthy, immutable video-run manifests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Mapping


class RunState(str, Enum):
    PLANNED = "PLANNED"
    CONTRACT_VALIDATED = "CONTRACT_VALIDATED"
    ASSETS_VALIDATED = "ASSETS_VALIDATED"
    PREVIEW_VALIDATED = "PREVIEW_VALIDATED"
    RENDERING = "RENDERING"
    RENDERED_UNVERIFIED = "RENDERED_UNVERIFIED"
    DEDUP_GATED = "DEDUP_GATED"
    MEDIA_GATED = "MEDIA_GATED"
    VISUAL_GATED = "VISUAL_GATED"
    AUDIO_GATED = "AUDIO_GATED"
    COVER_GATED = "COVER_GATED"
    PACKAGE_GATED = "PACKAGE_GATED"
    HANDOFF_READY = "HANDOFF_READY"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    BLOCKED_DEDUP = "BLOCKED_DEDUP"
    DEGRADED_REQUIRES_REVIEW = "DEGRADED_REQUIRES_REVIEW"

    @property
    def is_gate(self) -> bool:
        return self in {
            RunState.DEDUP_GATED,
            RunState.MEDIA_GATED,
            RunState.VISUAL_GATED,
            RunState.AUDIO_GATED,
            RunState.COVER_GATED,
            RunState.PACKAGE_GATED,
        }


_FAILURE_STATES = {
    RunState.FAILED_RETRYABLE,
    RunState.FAILED_TERMINAL,
    RunState.BLOCKED_DEDUP,
    RunState.DEGRADED_REQUIRES_REVIEW,
}
_STATE_SEQUENCE = tuple(state for state in RunState if state not in _FAILURE_STATES)


class ArtifactRole(str, Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    name: str
    path: Path
    role: ArtifactRole = ArtifactRole.INPUT

    def __post_init__(self) -> None:
        path = Path(self.path)
        if any(character in str(path) for character in "*?[]{}"):
            raise ValueError("artifact paths must be explicit, not patterns")
        if not path.is_absolute() or path != path.resolve():
            raise ValueError("artifact path must be a canonical absolute path")
        if not self.name:
            raise ValueError("artifact name must not be empty")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "role", ArtifactRole(self.role))


@dataclass(frozen=True, slots=True)
class RunSpec:
    run_id: str
    revision: int
    artifacts: tuple[ArtifactSpec, ...]
    attempt_id: str = "attempt-1"

    def __post_init__(self) -> None:
        artifacts = tuple(self.artifacts)
        names = [artifact.name for artifact in artifacts]
        if not self.run_id:
            raise ValueError("run_id must not be empty")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if not self.attempt_id:
            raise ValueError("attempt_id must not be empty")
        if len(names) != len(set(names)):
            raise ValueError("artifact names must be unique")
        object.__setattr__(self, "artifacts", artifacts)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class GateEvidence:
    gate: RunState
    run_id: str
    revision: int
    attempt_id: str
    artifact_sha256: Mapping[str, str] = field(repr=False)
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.gate.is_gate:
            raise ValueError("evidence may only describe a gate state")
        object.__setattr__(
            self, "artifact_sha256", MappingProxyType(dict(self.artifact_sha256))
        )


@dataclass(frozen=True, slots=True)
class RunManifest:
    spec: RunSpec
    state: RunState
    artifact_sha256: Mapping[str, str] = field(repr=False)
    gate_evidence: tuple[GateEvidence, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_sha256", MappingProxyType(dict(self.artifact_sha256))
        )
        object.__setattr__(self, "gate_evidence", tuple(self.gate_evidence))

    @classmethod
    def plan(cls, spec: RunSpec) -> "RunManifest":
        hashes = {
            artifact.name: file_sha256(artifact.path)
            for artifact in spec.artifacts
            if artifact.role is ArtifactRole.INPUT or artifact.path.is_file()
        }
        return cls(spec=spec, state=RunState.PLANNED, artifact_sha256=hashes)

    @property
    def missing_outputs(self) -> tuple[str, ...]:
        return tuple(
            artifact.name
            for artifact in self.spec.artifacts
            if artifact.role is ArtifactRole.OUTPUT and artifact.name not in self.artifact_sha256
        )

    def bind_outputs(self) -> "RunManifest":
        missing = [
            artifact.name
            for artifact in self.spec.artifacts
            if artifact.role is ArtifactRole.OUTPUT and not artifact.path.is_file()
        ]
        if missing:
            raise ValueError(f"expected output artifacts missing: {', '.join(missing)}")
        return self.refresh_artifact_hashes()

    def make_gate_evidence(
        self, gate: RunState, *, evidence_sha256: str | None = None
    ) -> GateEvidence:
        return GateEvidence(
            gate=gate,
            run_id=self.spec.run_id,
            revision=self.spec.revision,
            attempt_id=self.spec.attempt_id,
            artifact_sha256=self.artifact_sha256,
            evidence_sha256=evidence_sha256,
        )

    def is_gate_evidence_current(self, evidence: GateEvidence) -> bool:
        return (
            evidence.run_id == self.spec.run_id
            and evidence.revision == self.spec.revision
            and evidence.attempt_id == self.spec.attempt_id
            and dict(evidence.artifact_sha256) == dict(self.artifact_sha256)
        )

    def advance(
        self, target: RunState, *, evidence: GateEvidence | None = None
    ) -> "RunManifest":
        if self.state in _FAILURE_STATES:
            raise ValueError(f"terminal state cannot advance: {self.state.value}")
        if target in _FAILURE_STATES:
            raise ValueError("use fail() to enter an explicit failure state")
        current_index = _STATE_SEQUENCE.index(self.state)
        expected = (
            _STATE_SEQUENCE[current_index + 1]
            if current_index + 1 < len(_STATE_SEQUENCE)
            else None
        )
        if target is not expected:
            raise ValueError(f"illegal transition: {self.state.value} -> {target.value}")
        if target.is_gate:
            if evidence is None:
                raise ValueError(f"gate evidence required for {target.value}")
            if evidence.gate is not target:
                raise ValueError("gate evidence is for a different gate")
            if not self.is_gate_evidence_current(evidence):
                raise ValueError("gate evidence does not match this run or its artifacts")
            return replace(
                self,
                state=target,
                gate_evidence=self.gate_evidence + (evidence,),
            )
        if evidence is not None:
            raise ValueError("gate evidence supplied for a non-gate transition")
        return replace(self, state=target)

    def fail(self, target: RunState, *, reason: str) -> "RunManifest":
        if target not in _FAILURE_STATES:
            raise ValueError("target is not a failure state")
        if self.state in _FAILURE_STATES or self.state is RunState.HANDOFF_READY:
            raise ValueError(f"terminal state cannot fail again: {self.state.value}")
        if not str(reason).strip():
            raise ValueError("failure reason must not be empty")
        return replace(self, state=target, failure_reason=str(reason).strip())

    def refresh_artifact_hashes(self) -> "RunManifest":
        hashes = {
            artifact.name: file_sha256(artifact.path)
            for artifact in self.spec.artifacts
            if artifact.path.is_file()
        }
        return replace(self, artifact_sha256=hashes)

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_sha256": dict(self.artifact_sha256),
            "artifacts": [
                {
                    "name": artifact.name,
                    "path": str(artifact.path),
                    "role": artifact.role.value,
                }
                for artifact in self.spec.artifacts
            ],
            "gate_evidence": [
                {
                    "artifact_sha256": dict(evidence.artifact_sha256),
                    "evidence_sha256": evidence.evidence_sha256,
                    "gate": evidence.gate.value,
                    "attempt_id": evidence.attempt_id,
                    "revision": evidence.revision,
                    "run_id": evidence.run_id,
                }
                for evidence in self.gate_evidence
            ],
            "revision": self.spec.revision,
            "run_id": self.spec.run_id,
            "attempt_id": self.spec.attempt_id,
            "state": self.state.value,
            "failure_reason": self.failure_reason,
        }


def write_manifest_atomic(manifest: RunManifest, destination: Path) -> None:
    """Durably replace ``destination`` with canonical manifest JSON."""
    destination = Path(destination)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                manifest.to_dict(),
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
