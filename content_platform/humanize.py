GENERIC_PHRASES = [
    "in conclusion",
    "overall",
    "it is important to note",
    "this solution is very important",
]


def _score(body, context):
    text = str(body or "")
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    unique_ratio = len(set(words)) / max(1, len(words))
    style = context.get("style", {})
    clarity = min(1.0, 0.45 + unique_ratio)
    authenticity = max(0.2, 1.0 - sum(text.casefold().count(phrase) for phrase in GENERIC_PHRASES) * 0.1)
    hook_strength = 0.8 if style.get("opening_patterns") else 0.5
    platform_fit = 0.8 if context.get("strategy", {}).get("content_form") else 0.5
    return {
        "clarity": round(clarity, 3),
        "authenticity": round(min(authenticity, 1.0), 3),
        "hook_strength": round(hook_strength, 3),
        "platform_fit": round(platform_fit, 3),
    }


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
    return {
        "body": updated.strip(),
        "quality_scores": _score(updated, context),
        "rewrite_notes": notes or ["kept original structure"],
    }
