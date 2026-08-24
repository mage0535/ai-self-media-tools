"""Deterministic platform-native topic scoring for production selection."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

WEIGHTS = {
    "official_signal": 0.20,
    "native_heat": 0.18,
    "lane_fit": 0.15,
    "utility": 0.12,
    "proofability": 0.10,
    "account_gap": 0.10,
    "hook_potential": 0.08,
    "feasibility": 0.07,
}

def _now():
    return datetime.now(timezone.utc)

def _float(value, default=0.0):
    try: return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError): return default

def _expires(hotspot):
    raw=str((hotspot or {}).get("expires_at") or "").strip()
    if not raw: return False
    try:
        value=datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value <= _now()
    except ValueError:
        return True

def score_topic_candidate(candidate: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile=profile or {}
    platform=str(profile.get("platform") or candidate.get("platform") or "").casefold()
    title=str(candidate.get("title") or "").strip()
    text=title.casefold()
    keywords=[str(x).casefold() for x in profile.get("keywords") or [] if str(x).strip()]
    hotspot=candidate.get("associated_hotspot") if isinstance(candidate.get("associated_hotspot"),dict) else {}
    reasons=[]
    official=bool(candidate.get("official_reference_only") or candidate.get("official_activity") or hotspot.get("native_verified"))
    hotspot_platform=str(hotspot.get("platform") or candidate.get("platform") or "").casefold()
    if official and hotspot_platform != platform:
        reasons.append("hotspot_platform_mismatch")
    if official and _expires(hotspot):
        reasons.append("hotspot_expired")
    official_signal=1.0 if official and not reasons else 0.0
    keyword_hits=sum(1 for word in keywords if word in text)
    hotspot_fit = max(_float(hotspot.get("lane_fit_score")), _float(hotspot.get("semantic_fit_score")))
    lane_fit=max(_float(candidate.get("platform_fit_score")), hotspot_fit, min(1.0, keyword_hits / max(1, min(3, len(keywords)))))
    heat=_float(candidate.get("heat_score"), min(1.0, math.log1p(max(0.0,float(candidate.get("points") or 0))) / 12.0))
    utility=0.85 if any(x in text for x in ("教程","步骤","方法","实测","清单","workflow","how to")) else 0.45
    proof=1.0 if any(candidate.get(k) for k in ("evidence_refs","source_url","demo_asset","screenshot_path","claim_ledger")) else 0.25
    gap=_float(candidate.get("account_gap_score"), 0.5)
    hook=0.85 if re.search(r"\d|实测|结果|为什么|how to|why|mistake|before|after", text) else 0.45
    feasibility=_float(candidate.get("feasibility_score"), 0.8 if proof >= .8 else .5)
    breakdown={
        "official_signal": official_signal, "native_heat": heat, "lane_fit": lane_fit,
        "utility": utility, "proofability": proof, "account_gap": gap,
        "hook_potential": hook, "feasibility": feasibility,
    }
    score=sum(WEIGHTS[k]*v for k,v in breakdown.items())
    saturation=_float(candidate.get("competition_saturation"), 0.0)
    duplicate_penalty=_float(candidate.get("duplicate_penalty"), 0.0)
    score=max(0.0, score - saturation*.12 - duplicate_penalty*.20)
    eligible=bool(title and not reasons and lane_fit >= .45 and proof >= .25)
    if not title: reasons.append("title_missing")
    if lane_fit < .45: reasons.append("lane_fit_below_threshold")
    return {"eligible":eligible,"score":round(score,6),"score_breakdown":breakdown,"penalties":{"competition_saturation":saturation,"duplicate":duplicate_penalty},"reasons":reasons,"platform":platform,"title":title}

def rank_topic_candidates(candidates: list[dict[str, Any]], profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ranked=[]
    for candidate in candidates or []:
        result=score_topic_candidate(candidate, profile)
        if result["eligible"]:
            ranked.append({**candidate, **result})
    return sorted(ranked,key=lambda row:(-float(row["score"]),str(row.get("title") or "")))
