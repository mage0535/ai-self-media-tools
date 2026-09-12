import re
import html
from collections import Counter


_TECHNICAL_FILE_EXTENSION = r"(?:md|json|ya?ml|toml|py|js|ts|tsx|jsx|html|css|sh|ps1)"

_KNOWN_TERMINAL_CTAS = {
    "save this": ".",
    "save this for later": ".",
    "follow for more": ".",
    "comment below": ".",
    "先收藏": "。",
    "收藏一下": "。",
    "评论区说说": "。",
    "关注获取更多": "。",
}


def normalize_generated_markdown(text):
    """Repair deterministic model formatting damage without rewriting prose."""
    value = str(text or "")
    value = re.sub(r"(?<!\n)[ \t]+(```[A-Za-z0-9_-]*)", r"\n\1", value)
    value = re.sub(r"```[ \t]+(?=\S)", "```\n", value)
    value = re.sub(r"(?m)^\s*,\s*$\n?", "", value)
    value = re.sub(r"\.\s*\n\s*([A-Za-z][A-Za-z0-9_-]*/)", r".\1", value)
    value = re.sub(r"\bpackageon\b", "package.json", value, flags=re.I)
    value = re.sub(r"(?m)^(\d+)\.\s*\n\s*(\S.+)$", r"\1. \2", value)
    value = re.sub(r"(?m)^—\s*$", "---", value)
    value = re.sub(r"(?m)^—\s*#\s*(.+)$", r"---\n# \1", value)
    fenced_parts = re.split(r"(```.*?```|~~~.*?~~~)", value, flags=re.S)
    for index in range(0, len(fenced_parts), 2):
        prose = fenced_parts[index]
        prose = re.sub(
            r"(?m)^(##\s+.{4,80}?)[ \t]+((?:先|很多人|目录结构|一句话|具体|以下|这种|这个|当|如果|对于|除了|关键|推荐).{6,}。)$",
            r"\1\n\2",
            prose,
        )
        without_contractions = re.sub(r"(?<=\w)'(?=\w)", "", prose)
        for quote in ('"', "'"):
            if without_contractions.count(quote) % 2:
                position = prose.rfind(quote)
                if position >= 0:
                    prose = prose[:position] + prose[position + 1:]
                    without_contractions = re.sub(r"(?<=\w)'(?=\w)", "", prose)
        fenced_parts[index] = prose
    value = "".join(fenced_parts)
    value = re.sub(r"!\s*\n?\s*\[\s*\]\(\s*\)", "", value)
    value = re.sub(r"(?m)^\s*!\s*$", "", value)
    value = re.sub(
        rf"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]+)\.\s*\n\s*({_TECHNICAL_FILE_EXTENSION})(?![A-Za-z0-9_-])",
        r"\1.\2",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\.\s*\n\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\1.\2(",
        value,
    )
    repaired_lines = []
    for line in value.splitlines():
        cells = line.strip().strip("|").split("|")
        if len(cells) >= 2 and all(re.fullmatch(r"[\s,:-]*", cell) for cell in cells):
            repaired_lines.append("|" + "|".join("---" for _ in cells) + "|")
        else:
            repaired_lines.append(line)
    value = "\n".join(repaired_lines)
    value = re.sub(r"\n{3,}", "\n\n", value)
    if value.count("```") % 2:
        value = value.rstrip() + "\n```"
    return value


def complete_known_terminal_cta(text):
    """Complete only a known standalone CTA at the end of generated prose."""
    value = str(text or "")
    match = re.search(r"(?P<cta>[^\s\n][^\n]*?)(?P<trailing>[ \t\r\n]*)$", value)
    if not match:
        return value
    cta = match.group("cta").strip()
    punctuation = _KNOWN_TERMINAL_CTAS.get(cta.casefold())
    if not punctuation:
        return value
    return value[: match.start("cta")] + cta + punctuation + match.group("trailing")


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


def validate_generated_text(text):
    value = str(text or "")
    head = value[:4000].casefold()
    code_markers = ("<script", "</script", "function ()", "function()", "var options", "bdms:", "verifycenter:", "growth_api/v1", "interact_api/v1")
    chrome_markers = (
        "首页 沸点 课程 app 搜索历史 清空 创作者中心 写文章",
        "首页 沸点 课程 app 搜索历史 清空 创作者中心",
        "写文章 发沸点 写笔记 写代码 草稿",
    )
    code_hits = [marker for marker in code_markers if marker in head]
    chrome_hits = [marker for marker in chrome_markers if marker in head]
    hits = code_hits + chrome_hits
    reasons = []
    findings = []
    if code_hits:
        reasons.append("source_page_code_contamination")
        findings.append({"reason": reasons[-1], "matches": code_hits})
    if chrome_hits:
        reasons.append("source_page_navigation_contamination")
        findings.append({"reason": reasons[-1], "matches": chrome_hits})

    prose = _prose_without_code(value)
    paragraphs = _prose_paragraphs(prose)
    normalized_paragraphs = [_normalize_prose(item) for item in paragraphs]
    repeated_paragraphs = [
        paragraph
        for paragraph, count in Counter(item for item in normalized_paragraphs if len(item) >= 30).items()
        if count > 1
    ]
    if repeated_paragraphs:
        reasons.append("repeated_paragraph")
        findings.append({"reason": reasons[-1], "matches": repeated_paragraphs[:3]})

    sentences = re.findall(r"[^.!?。！？\n]+[.!?。！？]+", prose)
    normalized_sentences = [_normalize_prose(item) for item in sentences]
    repeated_sentences = [
        sentence
        for sentence, count in Counter(item for item in normalized_sentences if len(item) >= 10).items()
        if count > 1
    ]
    if repeated_sentences:
        reasons.append("repeated_sentence")
        findings.append({"reason": reasons[-1], "matches": repeated_sentences[:3]})

    duplicated_conclusions = _duplicated_conclusions(value)
    if duplicated_conclusions:
        reasons.append("duplicated_conclusion")
        findings.append({"reason": reasons[-1], "matches": duplicated_conclusions[:3]})

    quote_issues = _quote_issues(prose)
    if quote_issues:
        reasons.append("malformed_quotes")
        findings.append({"reason": reasons[-1], "matches": quote_issues})

    fragments = [sentence.strip() for sentence in sentences if _is_obvious_fragment(sentence)]
    if fragments:
        reasons.append("sentence_fragment")
        findings.append({"reason": reasons[-1], "matches": fragments[:3]})

    terminal = _terminal_prose_line(prose)
    if terminal and not re.search(r"[.!?。！？…][\"'”’」』）》】]*$", terminal):
        reasons.append("truncated_terminal_sentence")
        findings.append({"reason": reasons[-1], "matches": [terminal[-160:]]})

    reason = reasons[0] if reasons else ""
    return {
        "passed": not reasons,
        "reason": reason,
        "reasons": reasons,
        "markers": hits,
        "findings": findings,
    }


def _prose_without_code(text):
    value = re.sub(r"```[^\n]*\n.*?```", "\n", str(text or ""), flags=re.S)
    value = re.sub(r"~~~[^\n]*\n.*?~~~", "\n", value, flags=re.S)
    value = re.sub(r"`[^`\n]+`", "", value)
    value = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"</?(?:p|div|section|article|h[1-6]|li|blockquote|br)\b[^>]*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(value)


def _prose_paragraphs(text):
    paragraphs = []
    for block in re.split(r"\n\s*\n+", text):
        lines = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or re.match(r"^(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\|)", line):
                continue
            lines.append(re.sub(r"^>\s?", "", line))
        paragraph = " ".join(lines).strip()
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs


def _normalize_prose(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").casefold())


def _quote_issues(text):
    issues = []
    pairs = (("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』"))
    for opening, closing in pairs:
        if text.count(opening) != text.count(closing):
            issues.append(f"{opening}{closing}")
    straight = re.sub(r"(?<=\w)'(?=\w)", "", text)
    if straight.count('"') % 2:
        issues.append('"')
    if straight.count("'") % 2:
        issues.append("'")
    return issues


def _is_obvious_fragment(sentence):
    value = re.sub(r"[.!?。！？\s]+$", "", str(sentence or "").strip()).casefold()
    if value in _KNOWN_TERMINAL_CTAS:
        return False
    if re.search(r"\b(?:a|an|the|this|that|these|those|to|of|for|with|and|or|but)$", value):
        return True
    if re.search(r"(?:因为|所以|但是|以及|或者)$", value):
        return True
    return bool(re.search(r"(?:这是|只是|成为|提供|包含|需要|选择|创建)(?:一个|一种|这个|那个)$", value))


def _terminal_prose_line(text):
    for raw_line in reversed(text.splitlines()):
        line = raw_line.strip()
        if not line or re.match(r"^(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\|)", line):
            continue
        return re.sub(r"^>\s?", "", line)
    return ""


def _duplicated_conclusions(text):
    conclusion_headings = re.compile(
        r"^#{1,6}\s*(?:conclusion|final takeaway|takeaway|summary|结论|总结|最后总结|写在最后)\s*$",
        flags=re.I | re.M,
    )
    matches = list(conclusion_headings.finditer(str(text or "")))
    conclusions = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = _prose_without_code(text[match.end():end])
        paragraphs = _prose_paragraphs(section)
        if paragraphs:
            conclusions.append(_normalize_prose(paragraphs[0]))
    return [item for item, count in Counter(item for item in conclusions if len(item) >= 20).items() if count > 1]
