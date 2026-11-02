"""What a block reason says to fix (owner 11-02: never report a bare failure).

The goal is the customer account's views, likes and interactions, so each block names
which part is off:
- data_access: the source could not be read (login, captcha, outage) -> restore access,
  meanwhile the labelled cross-platform reference;
- retrieval_direction: data was read but the wrong works came back -> change keywords/ordering;
- integrity: stored evidence no longer matches what was observed -> a pipeline bug; never loosened;
- content_quality: our draft missed a quality gate -> improve generation; when it keeps
  blocking drafts that would perform, recalibrate that gate.
"""
from __future__ import annotations

RULES = (
    ("integrity", ("_changed", "_mismatch", "raw_response")),
    ("data_access", ("unavailable", "login", "verification", "paused", "capture_failed", "transport", "timeout",
                     "rate_limit", "health")),
    ("retrieval_direction", ("not_selected", "no_current_native_candidate", "semantic_pool_rejected", "benchmark",
                             "candidate", "pool")),
    ("content_quality", ("quality", "image", "cover", "card", "caption", "factual", "claim", "depth", "hygiene",
                         "narration", "copy", "dedup", "duplicate", "safety", "policy", "article", "video")),
)


def diagnose_block(reason_code: str) -> str:
    code = str(reason_code or "").lower()
    for kind, words in RULES:
        if any(word in code for word in words):
            return kind
    return "unclassified"
