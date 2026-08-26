"""Audit production capabilities and asset policy for license-safe execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "creative_capability_registry.json"
ASSET_POLICY = ROOT / "config" / "asset_license_policy.json"
EXECUTABLE_LICENSES = {"internal", "public_knowledge", "permissive", "licensed", "public_domain"}


def audit_licenses(registry_path: Path = REGISTRY, policy_path: Path = ASSET_POLICY) -> dict[str, Any]:
    issues: list[str] = []
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "ok": False, "issues": [f"license_input_unreadable:{type(exc).__name__}"]}
    capabilities = registry.get("capabilities") if isinstance(registry.get("capabilities"), list) else []
    for capability in capabilities:
        if not isinstance(capability, dict):
            issues.append("capability_record_invalid")
            continue
        capability_id = str(capability.get("id") or "missing")
        license_name = str(capability.get("license") or "").casefold()
        lifecycle = str(capability.get("lifecycle") or "")
        if lifecycle == "executable" and license_name not in EXECUTABLE_LICENSES:
            issues.append(f"executable_license_unverified:{capability_id}:{license_name or 'missing'}")
        if license_name == "unverified" and lifecycle != "inventory_only":
            issues.append(f"unverified_capability_not_isolated:{capability_id}")
    allowed_sources = policy.get("allowed_source_types") if isinstance(policy.get("allowed_source_types"), list) else []
    if policy.get("verified_required_for_auto_publish") is not True:
        issues.append("auto_publish_license_verification_not_required")
    if not {"self_owned", "licensed", "stock", "public_domain"}.issubset(set(allowed_sources)):
        issues.append("asset_license_source_types_incomplete")
    return {
        "schema": "license_audit_v1",
        "passed": not issues,
        "ok": not issues,
        "issues": sorted(set(issues)),
        "capability_count": len(capabilities),
        "registry": registry_path.relative_to(ROOT).as_posix() if registry_path.is_relative_to(ROOT) else registry_path.name,
        "asset_policy": policy_path.relative_to(ROOT).as_posix() if policy_path.is_relative_to(ROOT) else policy_path.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(REGISTRY))
    parser.add_argument("--policy", default=str(ASSET_POLICY))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_licenses(Path(args.registry), Path(args.policy))
    serialized = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
