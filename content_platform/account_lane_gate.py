"""Fail-closed account/lane/content-line validation for platform runs."""
from __future__ import annotations

import hashlib
import json


class AccountLaneGateError(ValueError):
    pass


ACCOUNT_RULES = {
    "douyin_pet": {
        "lane": "pet_healing",
        "content_lines": {
            "cat_dog_cold_knowledge",
            "healing_moments",
            "cat_care_avoidance_manual",
            "tiktok_deduplicated_repost",
        },
    },
    "douyin_ai": {
        "lane": "real_world_ai_implementation_v1",
        "content_lines": None,
    },
}


def validate_account_lane(plan: dict) -> dict:
    account = str(plan.get("account_key") or plan.get("platform_account") or "").strip()
    lane = str(plan.get("lane") or "").strip()
    content_line = str(plan.get("content_line") or "").strip()
    if not account:
        raise AccountLaneGateError("account_key_required")
    rule = ACCOUNT_RULES.get(account)
    if rule is None:
        raise AccountLaneGateError(f"unknown_account:{account}")
    failures = []
    if lane != rule["lane"]:
        failures.append(f"lane_mismatch:{account}:{lane}:{rule['lane']}")
    if not content_line:
        failures.append("content_line_required")
    elif rule["content_lines"] is not None and content_line not in rule["content_lines"]:
        failures.append(f"content_line_not_allowed:{account}:{content_line}")
    if failures:
        raise AccountLaneGateError(",".join(failures))
    identity = {
        "account_key": account,
        "lane": lane,
        "content_line": content_line,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "passed": True,
        **identity,
        "account_lane_fingerprint": fingerprint,
    }
