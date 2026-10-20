"""Identity- and artifact-bound release gate for video deliverables."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType

from .video_run import RunManifest, RunState


class ReleaseBlocked(RuntimeError):
    """Raised when no canonical handoff may be promoted."""


class DedupBlocked(ReleaseBlocked):
    """Raised when duplicate evidence blocks canonical handoff."""


def _block_checker(name: str, message: str) -> None:
    error_type = DedupBlocked if name == "dedup" else ReleaseBlocked
    raise error_type(message)


_GATE_ORDER = (
    ("dedup", RunState.DEDUP_GATED),
    ("media", RunState.MEDIA_GATED),
    ("visual", RunState.VISUAL_GATED),
    ("audio", RunState.AUDIO_GATED),
    ("cover", RunState.COVER_GATED),
    ("package", RunState.PACKAGE_GATED),
)


_ALLOWED_CHECKERS = frozenset(name for name, _ in _GATE_ORDER)
_BIND_TOKEN = object()


class _BoundCheckerResult(Mapping[str, object]):
    """Immutable checker result minted only by ``bind_checker_result``."""

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, object], *, token: object) -> None:
        if token is not _BIND_TOKEN:
            raise TypeError("checker results must be created by bind_checker_result")
        self._data = MappingProxyType(dict(data))

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _assert_artifacts_unchanged(
    manifest: RunManifest, expected_hashes: Mapping[str, str]
) -> None:
    try:
        disk_hashes = dict(manifest.refresh_artifact_hashes().artifact_sha256)
    except OSError as error:
        raise ReleaseBlocked(f"release artifact could not be hashed: {error}") from error
    if disk_hashes != dict(expected_hashes):
        raise ReleaseBlocked("release artifacts changed on disk")


def bind_checker_result(
    manifest: RunManifest,
    *,
    checker: str,
    passed: bool,
    failures: list[str] | tuple[str, ...],
    evidence_sha256: str | None = None,
) -> Mapping[str, object]:
    """Bind a real checker's verdict to the exact candidate artifacts."""
    if checker not in _ALLOWED_CHECKERS:
        raise ValueError(f"unsupported checker: {checker}")
    if not isinstance(passed, bool):
        raise TypeError("passed must be a bool")
    if (
        not isinstance(evidence_sha256, str)
        or len(evidence_sha256) != 64
        or any(character not in "0123456789abcdef" for character in evidence_sha256)
    ):
        raise ValueError("evidence_sha256 must be a non-empty lowercase SHA-256 hex digest")
    return _BoundCheckerResult({
        "checker": checker,
        "passed": passed is True,
        "failures": [str(item) for item in failures],
        "evidence_sha256": evidence_sha256,
        "run_id": manifest.spec.run_id,
        "revision": manifest.spec.revision,
        "attempt_id": manifest.spec.attempt_id,
        "artifact_sha256": dict(manifest.artifact_sha256),
    }, token=_BIND_TOKEN)


def release_to_handoff(
    manifest: RunManifest,
    checker_results: Mapping[str, Mapping],
) -> RunManifest:
    """Advance only an exact rendered candidate through all release gates."""
    if manifest.state is not RunState.RENDERED_UNVERIFIED:
        raise ReleaseBlocked(
            f"release requires RENDERED_UNVERIFIED, got {manifest.state.value}"
        )
    if manifest.missing_outputs:
        raise ReleaseBlocked(
            "release outputs missing: " + ", ".join(manifest.missing_outputs)
        )

    expected_hashes = dict(manifest.artifact_sha256)
    _assert_artifacts_unchanged(manifest, expected_hashes)

    current = manifest
    for name, state in _GATE_ORDER:
        result = checker_results.get(name)
        if not isinstance(result, Mapping):
            _block_checker(name, f"{name} checker result missing")
        if not isinstance(result, _BoundCheckerResult):
            _block_checker(name, f"{name} checker result is not bound")
        if result.get("checker") != name:
            _block_checker(name, f"{name} checker identity mismatch")
        identity = (
            result.get("run_id"),
            result.get("revision"),
            result.get("attempt_id"),
        )
        expected_identity = (
            manifest.spec.run_id,
            manifest.spec.revision,
            manifest.spec.attempt_id,
        )
        if identity != expected_identity:
            _block_checker(name, f"{name} run identity mismatch")
        if dict(result.get("artifact_sha256") or {}) != expected_hashes:
            _block_checker(name, f"{name} artifact hashes are stale or mismatched")
        if result.get("passed") is not True:
            failures = ", ".join(str(item) for item in result.get("failures") or [])
            _block_checker(name, f"{name} checker failed: {failures or 'unknown'}")
        evidence = current.make_gate_evidence(
            state, evidence_sha256=str(result["evidence_sha256"])
        )
        current = current.advance(state, evidence=evidence)

    _assert_artifacts_unchanged(manifest, expected_hashes)
    return current.advance(RunState.HANDOFF_READY)
