import json
from pathlib import Path

from scripts.license_audit import audit_licenses


def test_checked_in_capability_registry_passes_license_audit():
    result = audit_licenses()

    assert result["passed"] is True
    assert result["issues"] == []


def test_executable_unverified_capability_fails_audit(tmp_path: Path):
    registry = json.loads(Path("config/creative_capability_registry.json").read_text(encoding="utf-8"))
    registry["capabilities"][0].update(lifecycle="executable", license="unverified")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    result = audit_licenses(registry_path, Path("config/asset_license_policy.json").resolve())

    assert result["passed"] is False
    assert any(issue.startswith("executable_license_unverified:") for issue in result["issues"])
