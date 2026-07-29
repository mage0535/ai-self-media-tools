"""Deterministic account, niche, and topic scoring for the first rule-system pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AccountProfiler:
    config: dict[str, Any] | None = None

    def profile(self, platform: str, account_id: str = "default", history: dict[str, Any] | None = None) -> dict[str, Any]:
        history = history or {}
        sample_count = int(history.get("sample_count", 0) or 0)
        if str(history.get("account_state", "")).casefold() in {"restricted", "blocked", "banned"}:
            stage = "restricted"
        elif sample_count <= 0:
            stage = "bootstrap"
        elif sample_count < 5:
            stage = "cold_start"
        elif sample_count < 20:
            stage = "exploration"
        else:
            stage = "growth"
        data_status = "sufficient" if sample_count >= 20 else "partial" if sample_count else "bootstrap"
        return {
            "platform": platform,
            "account_id": account_id,
            "account_stage": stage,
            "strategy_data_status": data_status,
            "sample_count": sample_count,
        }


@dataclass
class NicheScorer:
    config: dict[str, Any] | None = None

    def score(self, topic: str, primary_track: str = "", sub_track: str = "", blocked_topics: list[str] | None = None) -> dict[str, Any]:
        topic_l = str(topic or "").casefold()
        blocked = [item for item in (blocked_topics or []) if str(item).casefold() in topic_l]
        track_tokens = [token for token in f"{primary_track} {sub_track}".casefold().replace("_", " ").split() if token]
        overlap = sum(1 for token in track_tokens if token in topic_l)
        score = 20 if not track_tokens else min(20, 8 + overlap * 4)
        if blocked:
            score = 0
        return {"score": score, "blocked_topics": blocked, "track_tokens": track_tokens}


@dataclass
class TopicScorer:
    config: dict[str, Any] | None = None

    def score_topic(
        self,
        topic: str,
        platform: str,
        account_profile: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        account_profile = account_profile or {}
        evidence = evidence or {}
        weights = (self.config or {}).get("weights") or {
            "account_track_match": 20,
            "audience_demand": 15,
            "platform_trend": 15,
            "platform_fit": 10,
            "title_potential": 10,
            "save_share_value": 10,
            "differentiation": 10,
            "asset_availability": 10,
            "duplication_risk": -5,
            "compliance_risk": -5,
        }
        stage = account_profile.get("account_stage", "bootstrap")
        data_status = account_profile.get("strategy_data_status", "bootstrap")
        track_score = float(evidence.get("account_track_match", weights["account_track_match"] if stage != "restricted" else 0))
        breakdown = {
            "account_track_match": min(float(weights["account_track_match"]), track_score),
            "audience_demand": float(evidence.get("audience_demand", 10 if data_status == "bootstrap" else 12)),
            "platform_trend": float(evidence.get("platform_trend", 8 if data_status == "bootstrap" else 12)),
            "platform_fit": float(evidence.get("platform_fit", 8)),
            "title_potential": float(evidence.get("title_potential", 7)),
            "save_share_value": float(evidence.get("save_share_value", 7)),
            "differentiation": float(evidence.get("differentiation", 7)),
            "asset_availability": float(evidence.get("asset_availability", 6)),
            "duplication_risk": -abs(float(evidence.get("duplication_risk", 0))),
            "compliance_risk": -abs(float(evidence.get("compliance_risk", 0))),
        }
        total = round(sum(breakdown.values()), 3)
        if total >= 70:
            decision = "auto_produce"
        elif total >= 60:
            decision = "manual_review"
        else:
            decision = "reject"
        if stage == "restricted":
            decision = "reject"
        return {
            "topic": topic,
            "platform": platform,
            "total_score": total,
            "breakdown": breakdown,
            "production_decision": decision,
            "account_stage": stage,
            "strategy_data_status": data_status,
        }
