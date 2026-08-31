import hashlib

from content_platform.execution_dag import execute_capability_dag


HASH = "sha256:" + "a" * 64


def _run(result, *, verification_level="output_verified"):
    return execute_capability_dag(
        {
            "candidates": [
                {
                    "capability_id": "capability",
                    "stage": "assets",
                    "required_or_optional": "required",
                    "verification_level": verification_level,
                }
            ]
        },
        {},
        {},
        executor=lambda *_args: result,
        stages={"assets"},
    )


def test_assets_stage_without_file_hash_evidence_is_not_artifact_verified():
    result = _run(
        {"status": "executed", "contract_valid": True, "output_hash": HASH, "output": {"status": "executed"}},
        verification_level="artifact_verified",
    )

    assert result["artifact_verified"] == []
    assert result["passed"] is False
    assert any("required_artifact_not_verified" in str(item) for item in result["failures"])


def test_matching_file_hash_evidence_promotes_artifact(tmp_path):
    artifact = tmp_path / "asset.bin"
    artifact.write_bytes(b"verified artifact")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    result = _run(
        {
            "status": "executed",
            "contract_valid": True,
            "output_hash": HASH,
            "output": {"artifact_evidence": [{"path": str(artifact), "sha256": digest}]},
        },
        verification_level="artifact_verified",
    )

    assert [item["capability_id"] for item in result["artifact_verified"]] == ["capability"]
    assert result["passed"] is True


def test_effect_requires_probe_bound_to_verified_artifact(tmp_path):
    artifact = tmp_path / "final.mp4"
    artifact.write_bytes(b"final media")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    result = _run(
        {
            "status": "executed",
            "contract_valid": True,
            "output_hash": HASH,
            "output": {
                "artifact_evidence": [{"path": str(artifact), "sha256": digest}],
                "effect_evidence": {"passed": True, "artifact_sha256": digest, "probe": "subtitle_burn_probe"},
            },
        },
        verification_level="effect_verified",
    )

    assert [item["capability_id"] for item in result["effect_verified"]] == ["capability"]
    assert result["passed"] is True


def test_unbound_effect_probe_does_not_promote_effect(tmp_path):
    artifact = tmp_path / "final.mp4"
    artifact.write_bytes(b"final media")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    result = _run(
        {
            "status": "executed",
            "contract_valid": True,
            "output_hash": HASH,
            "output": {
                "artifact_evidence": [{"path": str(artifact), "sha256": digest}],
                "effect_evidence": {"passed": True, "artifact_sha256": "0" * 64, "probe": "motion_probe"},
            },
        },
        verification_level="effect_verified",
    )

    assert result["effect_verified"] == []
    assert result["passed"] is False
