#!/usr/bin/env python3
"""Compile a deterministic prompt bundle from a JSON intent specification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow direct execution from the repository root without installation.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.prompt_compiler import compile_prompt_bundle, validate_prompt_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="Input intent JSON path")
    parser.add_argument("--output", help="Optional output JSON path; stdout when omitted")
    parser.add_argument("--validate", action="store_true", help="Attach fail-closed validation result")
    args = parser.parse_args()

    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        bundle = compile_prompt_bundle(spec)
        if args.validate:
            bundle["validation"] = validate_prompt_bundle(bundle)
            if not bundle["validation"]["passed"]:
                payload = json.dumps(bundle, ensure_ascii=False, indent=2)
                if args.output:
                    Path(args.output).write_text(payload + "\n", encoding="utf-8")
                else:
                    print(payload)
                return 2
        payload = json.dumps(bundle, ensure_ascii=False, indent=2)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"compile_prompt_bundle: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
