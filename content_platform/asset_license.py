"""P0 source and license validation for content assets."""

from __future__ import annotations

from typing import Any

from .models import GateFailure, GateResult


def validate_asset_licenses(content_package: dict[str, Any], action: str = "publish") -> GateResult:
    licenses = list(content_package.get("asset_licenses") or [])
    assets = list(content_package.get("assets") or [])
    failures: list[GateFailure] = []
    if assets and not licenses:
        failures.append(
            GateFailure(
                code="ASSET_LICENSE_MISSING",
                rule_ref="C1.1",
                severity="blocking",
                message="Assets are present but no asset license records were attached.",
                remediation="Add asset_id, source_type, source_url when applicable, and verification_status before publishing.",
            )
        )
    for item in licenses:
        status = str(item.get("verification_status", "unknown")).casefold()
        source_type = str(item.get("source_type", "unknown")).casefold()
        asset_id = str(item.get("asset_id", "")).strip()
        if not asset_id:
            failures.append(
                GateFailure("ASSET_ID_MISSING", "C1.2", "blocking", "Asset license record is missing asset_id.", "Add a stable asset_id.")
            )
        if source_type != "self_owned" and not str(item.get("source_url", "")).strip():
            failures.append(
                GateFailure("ASSET_SOURCE_URL_MISSING", "C1.3", "blocking", "Non-self-owned asset is missing source_url.", "Record the original asset URL or move to manual review.")
            )
        if action == "publish" and status != "verified":
            failures.append(
                GateFailure(
                    "ASSET_LICENSE_NOT_VERIFIED",
                    "C1.4",
                    "blocking",
                    f"Asset {asset_id or '<missing>'} has verification_status={status}.",
                    "Use verified assets for automatic publishing, or keep the item as draft/manual review.",
                )
            )
    return GateResult("asset_license_gate", "failed" if failures else "passed", failures)
