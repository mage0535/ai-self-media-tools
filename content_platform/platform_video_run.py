"""Independent identity and paths for each platform video run."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .video_platform_profile import VideoPlatformProfile, resolve_video_platform_profile


@dataclass(frozen=True, slots=True)
class PlatformVideoRun:
    job_id: str
    platform: str
    attempt_id: str
    profile_revision: str
    output_dir: Path
    evidence_dir: Path

    @property
    def platform_run_id(self) -> str:
        return f"{self.job_id}:{self.platform}:{self.attempt_id}:{self.profile_revision[:12]}"

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "platform": self.platform,
            "attempt_id": self.attempt_id,
            "profile_revision": self.profile_revision,
            "platform_run_id": self.platform_run_id,
            "output_dir": str(self.output_dir),
            "evidence_dir": str(self.evidence_dir),
        }


def profile_revision(profile: VideoPlatformProfile) -> str:
    payload = json.dumps(profile.__dict__ if hasattr(profile, "__dict__") else {
        field: getattr(profile, field) for field in ("id", "format_profile", "language", "aspect_ratio", "width", "height", "beat_count_min", "beat_count_max", "lane")
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def build_platform_video_run(*, data_dir: Path, job_id: str, platform: str, attempt_id: str = "attempt-1") -> PlatformVideoRun:
    profile = resolve_video_platform_profile(platform)
    canonical = profile.id
    revision = profile_revision(profile)
    root = Path(data_dir).resolve() / "artifacts" / str(job_id) / "platforms" / canonical / "runs" / f"{attempt_id}-{revision[:12]}"
    return PlatformVideoRun(str(job_id), canonical, str(attempt_id), revision, root / "artifacts", root / "evidence")