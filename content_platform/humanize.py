GENERIC_PHRASES = [
    "in conclusion",
    "overall",
    "it is important to note",
    "this solution is very important",
]

QUALITY_TARGETS = {
    "clarity": 0.72,
    "authenticity": 0.72,
    "hook_strength": 0.68,
    "platform_fit": 0.68,
}


def _score(body, context):
    text = str(body or "")
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    unique_ratio = len(set(words)) / max(1, len(words))
    style = context.get("style", {})
    strategy = context.get("strategy", {})
    clarity = min(1.0, 0.45 + unique_ratio)
    authenticity = max(0.2, 1.0 - sum(text.casefold().count(phrase) for phrase in GENERIC_PHRASES) * 0.1)
    body_lines = [line.strip() for line in text.splitlines() if line.strip()]
    line_variance = min(0.2, len({len(line.split()) for line in body_lines}) * 0.03)
    clarity = min(1.0, clarity + line_variance)
    hook_strength = 0.8 if style.get("opening_patterns") else 0.5
    if body_lines and any(line.endswith("?") for line in body_lines[:2]):
        hook_strength = min(1.0, hook_strength + 0.1)
    platform_fit = 0.8 if strategy.get("content_form") else 0.5
    if strategy.get("content_form") in {"short_video", "social_note"} and len(body_lines) >= 3:
        platform_fit = min(1.0, platform_fit + 0.08)
    return {
        "clarity": round(clarity, 3),
        "authenticity": round(min(authenticity, 1.0), 3),
        "hook_strength": round(hook_strength, 3),
        "platform_fit": round(platform_fit, 3),
    }


def quality_gate(scores):
    failures = [name for name, threshold in QUALITY_TARGETS.items() if float(scores.get(name, 0.0)) < threshold]
    return {
        "passed": not failures,
        "failed_dimensions": failures,
        "targets": dict(QUALITY_TARGETS),
    }


def _sentence_break(text):
    return text.replace(". ", ".\n").replace("! ", "!\n").replace("? ", "?\n")


def naturalize_copy(body, context):
    updated = str(body or "")
    notes = []
    for phrase in GENERIC_PHRASES:
        if phrase in updated.casefold():
            notes.append(f"removed generic phrase: {phrase}")
            parts = updated.split(phrase, 1) if phrase in updated else None
            if parts:
                updated = " ".join(part.strip(" ,.") for part in parts if part.strip())
            else:
                updated = updated.replace(phrase.title(), "")
                updated = updated.replace(phrase, "")
    updated = updated.replace("  ", " ").strip()
    if context.get("style", {}).get("opening_patterns"):
        opening = context["style"]["opening_patterns"][0]
        if opening and opening not in updated[: len(opening) + 12]:
            updated = f"{opening}\n\n{updated}"
            notes.append("prepended same-track opening rhythm")
    updated = _sentence_break(updated).strip()
    scores = _score(updated, context)
    gate = quality_gate(scores)
    if not gate["passed"]:
        strategy = context.get("strategy", {})
        if strategy.get("content_form") in {"social_note", "short_video"}:
            updated = updated.replace("\n\n", "\n").strip()
            notes.append("tightened spacing for feed-native rhythm")
        cta = context.get("style", {}).get("cta", "")
        if cta and cta not in updated:
            updated = f"{updated}\n\n{cta}".strip()
            notes.append("restored call to action")
        scores = _score(updated, context)
        gate = quality_gate(scores)
    return {
        "body": updated.strip(),
        "quality_scores": scores,
        "quality_gate": gate,
        "rewrite_notes": notes or ["kept original structure"],
    }
