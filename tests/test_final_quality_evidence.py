import pytest

from content_platform.final_quality_evidence import (
    InvalidFinalQualityEvidence,
    candidate_sha256,
    validate_final_quality_evidence,
)


def _evidence(candidate):
    digest = candidate_sha256(candidate)
    return {
        "version": "final_quality_evidence_v1",
        "candidate_sha256": digest,
        "auto": {"passed": True, "candidate_sha256": digest, "evidence_path": "auto.json"},
        "vlm": {"passed": True, "candidate_sha256": digest, "evidence_path": "vlm.json"},
        "watch": {"passed": True, "candidate_sha256": digest, "evidence_path": "watch.json"},
    }


def test_all_three_channels_must_bind_same_candidate(tmp_path):
    candidate = tmp_path / "final.mp4"
    candidate.write_bytes(b"candidate")
    result = validate_final_quality_evidence(candidate, _evidence(candidate))
    assert result["channels"] == ["auto", "vlm", "watch"]


@pytest.mark.parametrize("channel", ["auto", "vlm", "watch"])
def test_missing_or_failed_channel_is_rejected(tmp_path, channel):
    candidate = tmp_path / "final.mp4"
    candidate.write_bytes(b"candidate")
    evidence = _evidence(candidate)
    evidence[channel]["passed"] = False
    with pytest.raises(InvalidFinalQualityEvidence, match=f"{channel}_not_passed"):
        validate_final_quality_evidence(candidate, evidence)


def test_hash_drift_is_rejected(tmp_path):
    candidate = tmp_path / "final.mp4"
    candidate.write_bytes(b"candidate")
    evidence = _evidence(candidate)
    candidate.write_bytes(b"changed")
    with pytest.raises(InvalidFinalQualityEvidence, match="hash mismatch"):
        validate_final_quality_evidence(candidate, evidence)