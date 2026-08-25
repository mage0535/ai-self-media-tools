"""Deterministic local content-search adapter."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def execute(inputs: dict[str, Any]) -> dict[str, Any]:
    query = " ".join(str(inputs.get("query") or "").split()).casefold()
    terms = [term for term in query.split() if term]
    matches = []
    for item in inputs.get("documents") or []:
        if not isinstance(item, dict):
            continue
        haystack = " ".join(str(item.get(key) or "") for key in ("id", "title", "text", "summary")).casefold()
        if terms and not all(term in haystack for term in terms):
            continue
        matches.append(dict(item))
    matches.sort(key=lambda item: (str(item.get("id") or ""), str(item.get("title") or "")))
    query_hash = "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()
    return {
        "version": "search_result_v1",
        "query_hash": query_hash,
        "result_ids": [str(item.get("id") or "") for item in matches],
        "results": matches,
        "result_count": len(matches),
        "affected_outputs": sorted({str(item) for item in (inputs.get("affected_outputs") or ["search_results"])}),
    }
