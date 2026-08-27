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

# Web-page residue that LLMs sometimes copy verbatim from source articles:
# cookie-banner JS stubs, HTML/JS tags, asset filenames, tracking strings.
WEB_RESIDUE_PATTERNS = [
    re.compile(r"function\s+\w+\(\)\s*\{[^}]{0,300}\}", re.I),
    re.compile(r"OptanonWrapper|OneTrust|CookieSettings|__NEXT_DATA__|window\.\w+\s*=|document\.\w+\s*=", re.I),
    re.compile(r"</?(?:script|style|div|span|section|article|p|h[1-6]|a|img)[^>]*>", re.I),
    re.compile(r"\.(?:js|css|png|jpg|jpeg|webp|svg)(?:\?[^\s)\]]*)?", re.I),
    re.compile(r"\{:entity\}|&nbsp;|&amp;|&lt;|&gt;", re.I),
    re.compile(r"(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|co|dev)(?::\d+)?/[a-z0-9][\w./\-]*\.(?:js|css|png|jpg|jpeg|webp|svg)", re.I),
    re.compile(r":root\s*\{[^}]{0,200}\}|--[\w-]+\s*:\s*[^;}]{1,80};", re.I),
    re.compile(r"@media[^{]+\{[^}]{0,200}\}|\.(?:css|scss|less)[^{]*\{[^}]{0,120}\}", re.I),
]


def _strip_web_residue(text: str) -> str:
    """Remove obvious webpage scaffolding the model may have copied into prose."""
    updated = str(text or "")
    for pattern in WEB_RESIDUE_PATTERNS:
        updated = pattern.sub("", updated)
    # Collapse the doubled separators that residue removal often leaves behind.
    updated = re.sub(r"\n{3,}", "\n\n", updated)
    updated = re.sub(r"[ \t]{2,}", " ", updated)
    return updated.strip()

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
    # English hooks should be judged by concrete problem/payoff signals, not only style samples.
    english_hook_signals = 0
    first_240 = text[:240]
    english_start = first_240.casefold()
    if not _contains_chinese(first_240):
        if body_lines and any(line.endswith("?") for line in body_lines[:2]):
            english_hook_signals += 1
        if re.search(r"\b(why|how|what if|before you|stop|avoid|mistake|problem|trap|cost|waste|fails?|broken|wrong|friction|vanish|vetted|practical filter)\b", english_start):
            english_hook_signals += 1
        if re.search(r"\b(most|many|teams|creators|developers|users|founders)\b.{0,90}\b(do not|don't|are not|aren't|fail|waste|lose|overlook|miss|wrong|need)\b", english_start):
            english_hook_signals += 1
        if re.search(r"^\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", english_start) or re.search(r"\b\d+\b", first_240[:120]):
            english_hook_signals += 1
        if re.search(r"[:—]\s*[A-Za-z]", first_240[:120]) or re.search(r"\s-\s*[A-Za-z]", first_240[:120]):
            english_hook_signals += 1
        if re.search(r"\bevery\s+(week|day|month|year)\b", english_start) and re.search(r"\b(most|few|but|friction|problem|waste|vetted|actually)\b", english_start):
            english_hook_signals += 1
        if english_hook_signals >= 2:
            hook_strength = max(hook_strength, 0.72)
        elif english_hook_signals == 1:
            hook_strength = max(hook_strength, 0.65)
    # Chinese-specific hook signals (independent of opening_patterns)
    first_200 = text[:200]
    cn_hook_signals = 0
    # 1. Rhetorical patterns: 难道, 是不是, 有没有, 凭什么, 为什么
    if re.search(r'(难道|是不是|有没有|凭什么|为什么|怎能|何不|岂不)', first_200):
        cn_hook_signals += 1
    # 2. Numbers at start (e.g. "15 个", "三个月", "第N刀")
    if re.search(r'^[\s\n]*[\d一二两三四五六七八九十]+', first_200):
        cn_hook_signals += 1
    # 3. First-person conflict / personal pain: 我+痛点词
    if re.search(r'(踩坑|踩了|我.*坏习惯|我.*后悔|我.*亏了|我.*错了|我.*教训)', first_200):
        cn_hook_signals += 1
    # 4. Colon-introduced conclusion (": " or "：")
    if re.search(r'[：:]\s*[^\s，。,.]', first_200[:100]):
        cn_hook_signals += 1
    # 5. Explicit pain / problem keywords near start
    if re.search(r'(问题|坑|陷阱|骗局|误区|反例|崩溃|翻车)', first_200[:100]):
        cn_hook_signals += 1
    # 6. First-person pronoun at text start
    if re.search(r'^[\s\n]*我[\s\u4e00-\u9fff]', first_200[:50]):
        cn_hook_signals += 1
    if cn_hook_signals >= 2:
        hook_strength = max(hook_strength, 0.72)
    elif cn_hook_signals == 1:
        hook_strength = max(hook_strength, 0.60)
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


def _contains_chinese(text):
    """Return True if text contains a significant proportion of Chinese characters."""
    if not text:
        return False
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return cn_chars / max(1, len(text)) > 0.15


def _burstiness_score(text):
    sentences = re.split(r"[。！？.!?\n]+", text)
    if _contains_chinese(text):
        # Chinese/ mixed: use character count per sentence (strip punctuation & whitespace)
        lens = [len(re.sub(r'[\s\u3000\ufeff,，、；:：""\'\'（）()【】\[\]{}]', '', s))
                for s in sentences if s.strip()]
    else:
        # English: use word-split count (original behavior)
        lens = [len(s.strip().split()) for s in sentences if s.strip()]
    if len(lens) < 3:
        return 0.3
    diffs = [abs(lens[i] - lens[i - 1]) for i in range(1, len(lens))]
    avg_diff = sum(diffs) / len(diffs)
    # Scale: for Chinese char-count, typical variation is 10-40 chars;
    # for English word-count, typical variation is 3-15 words.
    divisor = 20.0 if _contains_chinese(text) else 15.0
    return round(min(1.0, avg_diff / divisor), 3)


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
    # Strip web-page residue that LLMs sometimes copy from source articles:
    # JS function stubs, cookie-banner wrappers, HTML tags, and asset URLs.
    before_strip = updated
    updated = _strip_web_residue(updated)
    if updated != before_strip:
        notes.append("stripped web page residue")
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


def repair_weak_hook(title, body, context):
    """Repair only the opening hook without introducing factual claims."""
    original = str(body or "").strip()
    scores = _score(original, context or {})
    if scores.get("hook_strength", 0) >= QUALITY_TARGETS["hook_strength"]:
        return {"changed": False, "body": original, "quality_scores": scores, "quality_gate": quality_gate(scores)}
    subject = re.sub(r"[？?！!。.:：]+$", "", str(title or "").strip())[:56]
    if not subject:
        return {"changed": False, "body": original, "quality_scores": scores, "quality_gate": quality_gate(scores)}
    hook = f"为什么{subject}？" if _contains_chinese(subject + original[:80]) else f"Why does {subject} matter?"
    updated = hook + "\n" + original
    repaired_scores = _score(updated, context or {})
    return {
        "changed": True,
        "hook": hook,
        "body": updated,
        "quality_scores": repaired_scores,
        "quality_gate": quality_gate(repaired_scores),
    }
