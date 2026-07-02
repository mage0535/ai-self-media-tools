def _stage_score(stage):
    return {
        "viral_candidate": 1.0,
        "hot": 0.9,
        "emerging": 0.6,
        "stable": 0.45,
    }.get(str(stage or "emerging"), 0.55)


def score_topic_candidate(topic, brief, references, niche_report):
    brief = brief or {}
    references = references or []
    niche_report = niche_report or {}
    text = " ".join(
        [
            str(topic or ""),
            " ".join(str(word) for word in brief.get("keywords", [])),
            " ".join(str(item.get("title", "")) for item in references),
        ]
    ).casefold()
    platforms = [str(item).casefold() for item in brief.get("platforms", [])]
    visual_promise = 0.9 if any(token in text for token in ("visual", "image", "video", "cover", "poster", "脚本", "封面")) else 0.55
    utility = 0.85 if any(token in text for token in ("workflow", "guide", "how", "steps", "automation", "教程", "方法")) else 0.55
    platform_distribution = niche_report.get("platform_distribution", {})
    platform_fit = 0.5
    if platforms:
        matches = sum(platform_distribution.get(platform, 0) for platform in platforms)
        platform_fit = min(1.0, 0.45 + matches / max(1, len(references) or 1))
    reference_depth = min(1.0, len(references) / 3)
    creator_fit = min(1.0, 0.4 + niche_report.get("account_count", 0) * 0.15)
    novelty_gap = 0.7 if len({item.get("title", "") for item in references}) == len(references) else 0.45
    feedback_signal = 0.5
    historical_feedback = brief.get("historical_feedback", {}).get("platforms", {})
    if historical_feedback and platforms:
        matched = []
        for platform in platforms:
            row = historical_feedback.get(platform, {})
            views = float(row.get("views", 0))
            engagement = float(row.get("engagement", 0))
            if views or engagement:
                matched.append(min(1.0, 0.35 + (engagement / max(views, 1)) + min(views / 5000.0, 0.4)))
        if matched:
            feedback_signal = round(sum(matched) / len(matched), 3)
    dimensions = {
        "trend_freshness": _stage_score(brief.get("trend_stage", "emerging")),
        "reference_depth": round(reference_depth, 3),
        "platform_fit": round(platform_fit, 3),
        "visual_promise": round(visual_promise, 3),
        "utility": round(utility, 3),
        "novelty_gap": round(novelty_gap, 3),
        "creator_fit": round(creator_fit, 3),
        "feedback_signal": round(feedback_signal, 3),
    }
    total = round(sum(dimensions.values()) / len(dimensions), 3)
    return {
        "topic": topic,
        "trend_stage": str(brief.get("trend_stage", "emerging")),
        "dimensions": dimensions,
        "total_score": total,
    }
