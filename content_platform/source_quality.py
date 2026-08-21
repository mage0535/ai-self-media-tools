"""Quality checks for trend/source text before ranking or generation."""

from __future__ import annotations

import re
from typing import Any


MOJIBAKE_MARKERS = ("�", "锟斤拷", "Ã", "Â", "å›", "æ–", "ï¿½")
CODE_PREFIX = re.compile(r"^(?:var|let|const|function|<script|<style|:root\s*\{)", re.I)


def text_quality(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    marker_count = sum(value.count(marker) for marker in MOJIBAKE_MARKERS)
    replacement_ratio = value.count("�") / max(len(value), 1)
    code_like = bool(CODE_PREFIX.search(value))
    passed = bool(value) and marker_count == 0 and replacement_ratio < 0.01 and not code_like
    return {
        "passed": passed,
        "marker_count": marker_count,
        "replacement_ratio": round(replacement_ratio, 5),
        "code_like": code_like,
        "failure": "source_text_corrupt_or_code_contaminated" if not passed else "",
    }


def source_is_rankable(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict) or item.get("source_unavailable"):
        return False
    if str(item.get("provenance_kind") or "").casefold() in {"synthetic_fallback", "hypothesis"}:
        return False
    return bool(text_quality(str(item.get("title") or "")).get("passed"))
