import re

GENERIC_PHRASES = [
    "in conclusion", "overall", "it is important to note",
    "this solution is very important", "furthermore", "moreover",
    "however", "nevertheless", "in addition", "consequently",
    "thus", "therefore", "notably", "significantly", "crucial",
    "vital", "essential", "imperative", "paramount",
    "delve into", "delve deeper", "it is worth noting",
    "it should be noted", "as previously mentioned",
    "in today's world", "in the modern era",
    "a testament to", "in the realm of", "it cannot be overstated",
]

SYCOPHANCY_PATTERNS = [
    (r"\bI apologize[^.]*\.", ""),
    (r"\bI understand your concern[^.]*\.", ""),
    (r"\bI appreciate your[^.]*\.", ""),
    (r"\bThank you for[^.]*\.", ""),
    (r"\bI hope this[^.]*\.", ""),
    (r"\bPlease let me know[^.]*\.", ""),
    (r"\bIf you have any[^.]*\.", ""),
]

HEDGE_PATTERNS = [
    (r"\bPerhaps you might consider\b", "Try"),
    (r"\bIt could be argued that\b", ""),
    (r"\bOne possible approach might involve\b", "Try"),
    (r"\bIt is generally believed that\b", ""),
    (r"\bIt may be the case that\b", ""),
    (r"\bIn some cases,\b", "Sometimes"),
]

QUALITY_TARGETS = {
    "clarity": 0.65,
    "authenticity": 0.62,
    "hook_strength": 0.60,
    "platform_fit": 0.60,
    "burstiness": 0.45,
}

TERM_LOCK_PATTERNS = [
    re.compile(r"\d+(?:\.\d+)?%", re.I),
    re.compile(r'\$?\d+(?:,\d{3})*(?:\.\d+)?(?:k|K|M|B|万|亿)?'),
    re.compile(r"https?://[^\s)]+"),
    re.compile(r"@[A-Za-z0-9_]+"),
    re.compile(r"#[A-Za-z0-9_]+"),
    re.compile(r"\d{4}(?:-\d{2}){0,2}"),
    re.compile(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+){1,4}"),
]


def _score(body, context):
    text = str(body or "")
    words = [word for word in text.replace("\n", " ").split(" ") if word]
    if not words:
        return {"clarity": 0, "authenticity": 0, "hook_strength": 0, "platform_fit": 0, "burstiness": 0}
    unique_ratio = len(set(words)) / max(1, len(words))
    style = context.get("style", {})
    strategy = context.get("strategy", {})
    clarity = min(1.0, 0.40 + unique_ratio)
    auth_penalty = sum(text.casefold().count(p) for p in GENERIC_PHRASES) * 0.08
    authenticity = max(0.15, 1.0 - auth_penalty)
    body_lines = [line.strip() for line in text.splitlines() if line.strip()]
    hook_strength = 0.75 if style.get("opening_patterns") else 0.45
    if body_lines and any(line.endswith("?") for line in body_lines[:2]):
        hook_strength = min(1.0, hook_strength + 0.12)
    platform_fit = 0.75 if strategy.get("content_form") else 0.45
    if strategy.get("content_form") in {"short_video", "social_note"} and len(body_lines) >= 3:
        platform_fit = min(1.0, platform_fit + 0.10)
    burstiness = _burstiness_score(text)
    return {
        "clarity": round(clarity, 3),
        "authenticity": round(min(authenticity, 1.0), 3),
        "hook_strength": round(hook_strength, 3),
        "platform_fit": round(platform_fit, 3),
        "burstiness": round(burstiness, 3),
    }


def _burstiness_score(text):
    sentences = re.split(r"[。！？.!?\n]+", text)
    lens = [len(s.strip().split()) for s in sentences if s.strip()]
    if len(lens) < 3:
        return 0.3
    diffs = [abs(lens[i] - lens[i - 1]) for i in range(1, len(lens))]
    avg_diff = sum(diffs) / len(diffs)
    return round(min(1.0, avg_diff / 15.0), 3)


def _lock_terms(original_text):
    terms = set()
    for pattern in TERM_LOCK_PATTERNS:
        for m in pattern.findall(str(original_text)):
            terms.add(str(m))
    return terms


def _verify_terms(locked_terms, rewritten_text):
    found = sum(1 for t in locked_terms if t in str(rewritten_text))
    total = len(locked_terms)
    return {"preserved": found, "total": total, "intact": found == total}


def quality_gate(scores):
    failures = [name for name, threshold in QUALITY_TARGETS.items()
                if float(scores.get(name, 0.0)) < threshold]
    return {"passed": not failures, "failed_dimensions": failures, "targets": dict(QUALITY_TARGETS)}


def _sentence_break(text):
    return re.sub(r"([。！？.!?])\s*", r"\1\n", str(text))


def naturalize_copy(body, context):
    updated = str(body or "")
    notes = []
    locked = _lock_terms(body)
    for phrase in GENERIC_PHRASES:
        if phrase in updated.casefold():
            notes.append(f"removed generic: {phrase}")
            idx = updated.casefold().find(phrase)
            if idx >= 0:
                before = updated[:idx].rstrip(",;. \t")
                after = updated[idx + len(phrase):].lstrip(",;. \t")
                updated = (before + " " + after).strip()
    for pattern, replacement in SYCOPHANCY_PATTERNS:
        if re.search(pattern, updated, re.I):
            updated = re.sub(pattern, replacement, updated, flags=re.I).strip()
            notes.append("removed sycophancy pattern")
            break
    for pattern, replacement in HEDGE_PATTERNS:
        if re.search(pattern, updated, flags=re.I):
            updated = re.sub(pattern, replacement, updated, flags=re.I).strip()
            notes.append("replaced hedging language")
            break
    updated = re.sub(r"\s{2,}", " ", updated)
    updated = re.sub(r"(-{2,}|—{2,})(?!-)", "—", updated)
    em_count = updated.count("—")
    if em_count > 4:
        updated = updated.replace("—", ", ")
        notes.append(f"reduced {em_count} em-dashes")
    if context.get("style", {}).get("opening_patterns"):
        opening = context["style"]["opening_patterns"][0]
        if opening and opening not in updated[:len(opening) + 12]:
            updated = f"{opening}\n\n{updated}"
            notes.append("prepended same-track opening rhythm")
    updated = _sentence_break(updated)
    updated = re.sub(r"\n{3,}", "\n\n", updated).strip()
    term_check = _verify_terms(locked, updated)
    if not term_check["intact"]:
        notes.append(f"term integrity: {term_check['preserved']}/{term_check['total']}")
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
        "locked_terms": list(locked),
        "term_verification": term_check,
        "quality_scores": scores,
        "quality_gate": gate,
        "rewrite_notes": notes or ["kept original structure"],
    }
