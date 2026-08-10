#!/usr/bin/env python3
"""Compare a small set of executable operational policy facts with skill text."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _policy_facts(payload: dict) -> dict:
    wechat = payload.get("wechat") or payload.get("platform_growth_playbooks", {}).get("wechat", {})
    frequency = wechat.get("publishing_frequency") if isinstance(wechat, dict) else {}
    video = payload.get("video") or {}
    return {
        "wechat_articles_per_week": str((wechat.get("articles_per_week") if isinstance(wechat, dict) else "") or (frequency or {}).get("recommended_articles_per_week") or ""),
        "newspic_dual_track": str((wechat.get("newspic_dual_track") if isinstance(wechat, dict) else "") or "").casefold(),
        "vertical_resolution": str(video.get("vertical_resolution") or ""),
        "short_max_seconds": str(video.get("short_max_seconds") or ""),
        "layered_motion": str(video.get("layered_motion") or "").casefold(),
    }


def _skill_facts(paths: list[Path]) -> dict:
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths if path.is_file())
    facts = {}
    for field in ("wechat_articles_per_week", "newspic_dual_track", "vertical_resolution", "short_max_seconds", "layered_motion"):
        match = re.search(rf"{field}\s*:\s*([^\s]+)", text, re.I)
        if match:
            facts[field] = match.group(1).casefold()
    return facts


def audit(policy_path: Path, skill_paths: list[Path]) -> dict:
    expected = _policy_facts(json.loads(Path(policy_path).read_text(encoding="utf-8")))
    actual = _skill_facts([Path(path) for path in skill_paths])
    conflicts = []
    for field, value in expected.items():
        if value and actual.get(field) != value.casefold():
            conflicts.append({"field": field, "policy": value, "skill": actual.get(field, "missing")})
    return {"passed": not conflicts, "policy_path": str(policy_path), "skill_paths": [str(path) for path in skill_paths], "conflicts": conflicts}


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect executable policy facts that conflict with skills.")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--skill", action="append", required=True)
    args = parser.parse_args()
    result = audit(Path(args.policy), [Path(item) for item in args.skill])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
