#!/usr/bin/env python3
"""Fail-closed BGM check used by the render pipeline."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.check_bgm_uniqueness import check


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("render_dir")
    parser.add_argument("--platform", default="")
    args = parser.parse_args()
    render_dir = Path(args.render_dir)
    registry = Path(os.environ.get("BGM_FINGERPRINT_REGISTRY", str(Path(__file__).resolve().parents[1] / "data" / "bgm_fingerprint_registry.json")))
    result = check(render_dir, args.platform, registry_path=registry, register=False)
    if not result.get("passed"):
        print(json.dumps({"ok": False, "checked": result}, ensure_ascii=False))
        return 2
    registered = check(render_dir, args.platform, registry_path=registry, register=True)
    evidence = {
        "version": "bgm_history_check_v1",
        "ok": bool(registered.get("passed")),
        "current_fingerprint": registered.get("fingerprint", ""),
        "checker_passed": bool(registered.get("passed")),
        "failed_dimensions": registered.get("failed_dimensions", []),
    }
    (render_dir / "bgm_history_check.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
