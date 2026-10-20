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


def source_quality_gate(item: dict[str, Any]) -> dict[str, Any]:
    failures=[]
    if not isinstance(item,dict):return {'passed':False,'failures':['source_object_missing']}
    if item.get('source_unavailable'):failures.append('source_unavailable')
    if str(item.get('provenance_kind')or'').casefold()in{'synthetic_fallback','hypothesis'}:failures.append('source_synthetic')
    if not text_quality(str(item.get('title')or''))['passed']:failures.append('source_text_corrupt_or_code_contaminated')
    views=[item]
    for key in ['quality','source_quality','viral_growth','viral_growth_report','trend_candidate']:
        if isinstance(item.get(key),dict):
            report=item[key];views.append(report)
            for row in report.get('items')or[]:
                if isinstance(row,dict)and((item.get('url')or item.get('canonical_url'))and(row.get('url')or row.get('canonical_url'))==(item.get('url')or item.get('canonical_url'))or(bool(item.get('title'))and row.get('title')==item.get('title'))):
                    views.append(row)
    for row in views:
        if str(row.get('grade')or'').casefold()=='low_quality':failures.append('source_low_quality')
        if str(row.get('recommendation')or'').casefold()=='avoid_repeating':failures.append('source_avoid_repeating')
        if 'freshness_score'in row:
            value=row['freshness_score']
            if isinstance(value,bool)or not isinstance(value,(int,float))or not __import__('math').isfinite(value)or value<=0:failures.append('source_freshness_not_positive')
    return {'passed':not failures,'failures':list(dict.fromkeys(failures))}


def source_is_rankable(item: dict[str, Any]) -> bool:
    return source_quality_gate(item)['passed']
