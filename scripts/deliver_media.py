#!/usr/bin/env python3
"""Send generated media as separate Hermes messages.

The target must be supplied through HERMES_DELIVERY_TARGET, for example
``telegram:<chat-id>``. The script intentionally does not contain account IDs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def deliver(text: str, paths: list[str], target: str = "") -> dict:
    target = target or os.environ.get("HERMES_DELIVERY_TARGET", "").strip()
    if not target:
        return {"passed": False, "error": "HERMES_DELIVERY_TARGET_missing", "sent": []}
    sent = []
    failures = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            failures.append({"path": str(path), "error": "file_missing"})
            continue
        message = f"{text.strip()}\nMEDIA:{path}"
        result = subprocess.run(["hermes", "send", "-t", target], input=message, capture_output=True, text=True, timeout=180)
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0 and "sent" in output.casefold():
            sent.append(str(path))
        else:
            failures.append({"path": str(path), "error": output[-200:] or f"returncode={result.returncode}"})
    return {"passed": not failures, "target_kind": target.split(":", 1)[0], "sent": sent, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one or more generated media files as independent Hermes MEDIA messages.")
    parser.add_argument("text")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--target", default="")
    args = parser.parse_args()
    result = deliver(args.text, args.paths, args.target)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
