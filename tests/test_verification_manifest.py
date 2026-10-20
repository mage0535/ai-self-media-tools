import pytest

from content_platform.verification_manifest import (
    InvalidVerificationManifest,
    new_verification_manifest,
    validate_verification_manifest,
    write_verification_manifest,
)


def test_targeted_scope_is_persisted_and_validated(tmp_path):
    manifest = new_verification_manifest(command="pytest -q tests/test_x.py", scope="targeted", selected_files=["tests/test_x.py"], passed=3, failed=0)
    path = tmp_path / "verification_manifest.json"
    write_verification_manifest(path, manifest)
    assert validate_verification_manifest(__import__("json").loads(path.read_text()))["passed"] is True
    assert manifest["scope"] == "targeted"


def test_scope_and_status_cannot_be_omitted_or_inflated():
    with pytest.raises(InvalidVerificationManifest):
        new_verification_manifest(command="pytest", scope="unknown", selected_files=[], passed=1, failed=0)
    manifest = new_verification_manifest(command="pytest", scope="targeted", selected_files=["tests/test_x.py"], passed=1, failed=1)
    manifest["status"] = "passed"
    with pytest.raises(InvalidVerificationManifest):
        validate_verification_manifest(manifest)