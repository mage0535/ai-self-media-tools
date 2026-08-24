"""Structured script analysis adapter."""

from __future__ import annotations

import re


def execute(inputs: dict) -> dict:
    segments = [str(item).strip() for item in inputs.get("segments", []) if str(item).strip()]
    patterns = {
        "pain_solution": (r"痛点|问题|困扰|错误", r"解决|步骤|方法|方案"),
        "reversal": (r"大家|一直|以为|常识", r"其实|真相|错|反而"),
        "result_first": (r"结果|实测|数据|提升", r"怎么|方法|关键|步骤"),
    }
    matched = []
    text = " ".join(segments)
    for name, (first, second) in patterns.items():
        if re.search(first, text) and re.search(second, text):
            matched.append(name)
    return {
        "version": "structure_match_v1",
        "matched_structures": matched,
        "confidence": min(1.0, len(matched) / 2),
        "segment_count": len(segments),
    }
