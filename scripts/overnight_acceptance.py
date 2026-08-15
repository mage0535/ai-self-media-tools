#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

# 2026-08-15 修复：直接运行缺 PYTHONPATH 时自动注入项目根（self-contained）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
