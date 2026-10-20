#!/usr/bin/env python3
"""CLI adapter for the canonical pixel-grounded cover validator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from content_platform.cover_quality import validate_cover as _validate_cover


def validate_cover(cover: Path, evidence_path: Path) -> dict:
    """Delegate to the only cover validator and persist its complete verdict."""
    result = _validate_cover(cover, evidence_path)
    if evidence_path.parent.is_dir():
        evidence_path.with_name("cover_quality_gate.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cover", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    result = validate_cover(Path(args.cover), Path(args.evidence))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "pass":
        return 0
    return 3 if result["status"] == "review_required" else 2


if __name__ == "__main__":
    raise SystemExit(main())
