import re
from collections import Counter


def _tokens(text):
    return [
        token
        for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", str(text).casefold())
        if len(token) > 1
    ]


def _weighted_similarity(left, right):
    left_counts = Counter(_tokens(left))
    right_counts = Counter(_tokens(right))
    if not left_counts or not right_counts:
        return 0.0
    overlap = sum(min(left_counts[token], right_counts[token]) for token in left_counts if token in right_counts)
    total = sum(left_counts.values()) + sum(right_counts.values()) - overlap
    return round(overlap / max(1, total), 3)


def _candidate_similarity(topic, candidate):
    topic_text = str(topic or "")
    title_text = str(candidate.get("title") or candidate.get("topic") or "")
    body_text = str(candidate.get("body") or "")[:1200]
    topic_score = _weighted_similarity(topic_text, candidate.get("topic", ""))
    title_score = _weighted_similarity(topic_text, title_text)
    body_score = _weighted_similarity(topic_text, body_text)
    score = round(topic_score * 0.55 + title_score * 0.35 + body_score * 0.10, 3)
    return {
        "score": score,
        "topic_score": topic_score,
        "title_score": title_score,
        "body_score": body_score,
    }


def audit_topic(topic, candidates, config=None):
    cfg = config or {}
    block_threshold = float(cfg.get("block_threshold", 0.72))
    review_threshold = float(cfg.get("review_threshold", 0.58))
    top_matches = []
    for candidate in candidates or []:
        similarity = _candidate_similarity(topic, candidate)
        if similarity["score"] <= 0:
            continue
        top_matches.append(
            {
                "job_id": candidate.get("id", ""),
                "topic": candidate.get("topic", ""),
                "title": candidate.get("title", ""),
                "state": candidate.get("state", ""),
                "platforms": list(candidate.get("platforms", [])),
                **similarity,
            }
        )
    top_matches.sort(key=lambda row: (-row["score"], row["job_id"]))
    top_matches = top_matches[:5]
    best = top_matches[0] if top_matches else {}
    best_score = float(best.get("score", 0))
    if best_score >= block_threshold:
        status = "blocked"
        recommended_action = "refresh_existing_cornerstone"
    elif best_score >= review_threshold:
        status = "review"
        recommended_action = "merge_into_cornerstone"
    else:
        status = "pass"
        recommended_action = "proceed"
    return {
        "topic": topic,
        "status": status,
        "recommended_action": recommended_action,
        "best_score": round(best_score, 3),
        "block_threshold": block_threshold,
        "review_threshold": review_threshold,
        "canonical_job_id": best.get("job_id", ""),
        "canonical_title": best.get("title") or best.get("topic", ""),
        "matches": top_matches,
    }
