#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from content_platform.overnight_acceptance import validate_overnight_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate overnight result and real artifacts")
    parser.add_argument("--result", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = validate_overnight_result(args.result, args.state)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
