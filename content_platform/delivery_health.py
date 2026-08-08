import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .content_policy import is_manual_handoff_platform, normalize_platform, platform_region


BLOCKING_STATES = {
    "auth_required",
    "blocked_account_certification",
    "blocked_account_health",
    "cookie_expired",
    "health_score_restricted",
    "insufficient_current_evidence",
    "login_required",
    "platform_restricted",
    "proxy_unavailable",
    "route_unverified",
}

HEALTHY_STATES = {
    "usable",
    "usable_with_postcheck_required",
    "verified",
}

STAGE_ALLOWED_BLOCKING_STATES = {
    "manual_handoff_only",
    "recovery_draft_only",
}

AITOEARN_DISABLED_PLATFORMS = {"youtube", "tiktok", "twitter", "x", "threads"}
AITOEARN_PUBLISHER_TYPES = {"aitoearn-draft", "aitoearn-intl", "aitoearn-flow"}


@dataclass(frozen=True)
class DeliveryHealthDecision:
    ok: bool
    platform: str
    state: str
    reason: str
    source: str = ""
    require_postcheck: bool = False

    def error(self):
        suffix = f" source={self.source}" if self.source else ""
        return f"{self.platform} delivery health gate blocked: {self.state}; {self.reason}{suffix}"


def delivery_health_decision(platform, config, action="publish"):
    normalized = normalize_platform(platform)
    normalized_action = normalize_platform(action or "publish")
    cfg = (config or {}).get("delivery_health", {})
    if cfg.get("enabled") is False:
        return DeliveryHealthDecision(True, normalized, "disabled", "delivery health gate disabled by config")

    disabled_aitoearn = _disabled_aitoearn_decision(normalized, config or {}, normalized_action)
    if disabled_aitoearn:
        return disabled_aitoearn

    file_entry, source = _load_state_file_entry(normalized, cfg, config or {})
    if file_entry:
        proxy_block = _proxy_decision(normalized, cfg, normalized_action)
        if proxy_block:
            return proxy_block
        return _decision_from_entry(normalized, file_entry, source, normalized_action)

    explicit = _platform_entry(cfg.get("platforms", {}), normalized)
    if explicit:
        proxy_block = _proxy_decision(normalized, cfg, normalized_action)
        if proxy_block:
            return proxy_block
        return _decision_from_entry(normalized, explicit, "config.delivery_health.platforms", normalized_action)

    if cfg.get("enforce_builtin_risk_policies", False) and is_manual_handoff_platform(normalized):
        if normalized_action == "stage":
            return DeliveryHealthDecision(
                True,
                normalized,
                "manual_handoff_only",
                "Hermes may create local review packages; user publishes manually",
                "built_in_policy",
                require_postcheck=False,
            )
        return DeliveryHealthDecision(
            True,
            normalized,
            "manual_handoff_only",
            f"Hermes must not access {normalized} for live publishing; create a local package for manual handoff",
            "built_in_policy",
            require_postcheck=True,
        )

    if normalized_action == "stage":
        return DeliveryHealthDecision(True, normalized, "unknown", "local stage does not require live platform health evidence")

    block_unknown_domestic = cfg.get("block_unknown_domestic", True)
    if block_unknown_domestic and platform_region(normalized) == "domestic":
        if not cfg.get("allow_unknown_health", False):
            return DeliveryHealthDecision(
                False,
                normalized,
                "route_unverified",
                "domestic delivery requires current health evidence; set delivery_health.allow_unknown_health only for explicit dry-run/local-only exceptions",
                "built_in_policy",
            )

    return DeliveryHealthDecision(True, normalized, "unknown", "no blocking health state found")


def _disabled_aitoearn_decision(platform, config, action):
    publisher_cfg = ((config or {}).get("publishers") or {}).get("platforms") or {}
    cfg = _platform_entry(publisher_cfg, platform)
    if not isinstance(cfg, dict):
        return None
    kind = normalize_platform(cfg.get("type") or "")
    if platform not in AITOEARN_DISABLED_PLATFORMS or kind not in AITOEARN_PUBLISHER_TYPES:
        return None
    return DeliveryHealthDecision(
        True,
        platform,
        "manual_handoff_only",
        f"{platform} is configured for cookie/manual route; AiToEarn is disabled by operator policy",
        "built_in_policy",
        require_postcheck=action != "stage",
    )


def _proxy_decision(platform, cfg, action):
    if action == "stage":
        return None
    if not cfg.get("require_proxy_by_region", False):
        return None
    region = platform_region(platform)
    if region == "domestic" and not os.environ.get("CN_PROXY"):
        return DeliveryHealthDecision(False, platform, "proxy_unavailable", "domestic channel publish requires CN_PROXY", "built_in_policy")
    if region == "international" and not os.environ.get("US_PROXY"):
        return DeliveryHealthDecision(False, platform, "proxy_unavailable", "international channel publish requires US_PROXY", "built_in_policy")
    return None


def _platform_entry(mapping, platform):
    if not isinstance(mapping, dict):
        return None
    return mapping.get(platform) or mapping.get(platform.lower()) or mapping.get(platform.upper())


def _load_state_file_entry(platform, cfg, config=None):
    paths = []
    if os.environ.get("CONTENT_PLATFORM_DELIVERY_HEALTH_FILE"):
        paths.append(os.environ["CONTENT_PLATFORM_DELIVERY_HEALTH_FILE"])
    if cfg.get("state_file"):
        paths.append(cfg.get("state_file"))
    elif (config or {}).get("data_dir"):
        paths.append(str(Path(str(config.get("data_dir"))) / "delivery_health_state.json"))
    for raw_path in paths:
        path = Path(str(raw_path)).expanduser()
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entry = _extract_state_entry(data, platform)
        if entry:
            stale = _stale_entry(entry, data, cfg)
            if stale:
                return stale, str(path)
            return entry, str(path)
    return None, ""


def _extract_state_entry(data, platform):
    if not isinstance(data, dict):
        return None
    channels = data.get("channels")
    if isinstance(channels, dict):
        channel = _platform_entry(channels, platform)
        if isinstance(channel, dict):
            classification = channel.get("classification")
            if isinstance(classification, dict):
                return classification
            return channel
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        return _platform_entry(platforms, platform)
    return _platform_entry(data, platform)


def _stale_entry(entry, data, cfg):
    state = normalize_platform(entry.get("state") or entry.get("status") or "unknown")
    can_publish = entry.get("can_publish_now")
    if can_publish is False or state in BLOCKING_STATES:
        return None
    try:
        max_age = int(cfg.get("max_state_age_seconds", 7200))
    except Exception:
        max_age = 7200
    if max_age <= 0:
        return None
    checked_at = entry.get("checked_at") or data.get("generated_at")
    if not checked_at:
        return {
            "state": "insufficient_current_evidence",
            "can_publish_now": False,
            "reason": "delivery health state has no checked_at/generated_at timestamp",
        }
    try:
        timestamp = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except Exception:
        return {
            "state": "insufficient_current_evidence",
            "can_publish_now": False,
            "reason": "delivery health state timestamp is invalid",
        }
    age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    if age > max_age:
        return {
            "state": "insufficient_current_evidence",
            "can_publish_now": False,
            "reason": f"delivery health state is stale: age_seconds={int(age)} max_age_seconds={max_age}",
        }
    return None


def _decision_from_entry(platform, entry, source, action="publish"):
    if not isinstance(entry, dict):
        return DeliveryHealthDecision(True, platform, "unknown", "health entry is not an object", source)
    state = normalize_platform(entry.get("state") or entry.get("status") or "unknown")
    reason = str(entry.get("reason") or entry.get("error") or "no reason recorded")
    can_publish = entry.get("can_publish_now")
    if action == "stage" and state in STAGE_ALLOWED_BLOCKING_STATES:
        return DeliveryHealthDecision(True, platform, state, reason, source)
    if can_publish is False or state in BLOCKING_STATES:
        return DeliveryHealthDecision(False, platform, state, reason, source)
    if can_publish is True or state in HEALTHY_STATES:
        return DeliveryHealthDecision(
            True,
            platform,
            state,
            reason,
            source,
            require_postcheck=(state == "usable_with_postcheck_required" or bool(entry.get("require_postcheck"))),
        )
    return DeliveryHealthDecision(True, platform, state, reason, source)
