#!/usr/bin/env python3
"""Generate or publish a validated Zhihu companion pin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content_platform.zhihu_promotion import (  # noqa: E402
    ZhihuPinValidationError,
    build_pin_text,
    publish_article_pin,
    validate_pin_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Zhihu companion pin tool")
    parser.add_argument("job_file", help="Path to the article job JSON containing title/body")
    parser.add_argument("--url", default="", help="Published article URL to reference in the pin")
    parser.add_argument("--extra", default="", help="Extra line to append, such as an engagement prompt")
    parser.add_argument("--publish", action="store_true", help="Actually publish the pin; default is review only")
    args = parser.parse_args()

    job = json.loads(Path(args.job_file).read_text(encoding="utf-8"))

    if not args.publish:
        payload = build_pin_text(job, article_url=args.url, extra=args.extra)
        validation = payload.get("validation") or validate_pin_payload(job, payload, article_url=args.url)
        print("=== Zhihu companion pin review draft ===")
        print(f"Title: {payload['title']}")
        print("---")
        print(payload["content"])
        print("---")
        print("Validation:")
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        print("Review this draft before adding --publish.")
        return 0 if validation.get("passed") else 2

    try:
        result = publish_article_pin(job, article_url=args.url, extra=args.extra)
    except ZhihuPinValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Pin published! ID: {result.get('id')}")
    print(result.get("url", ""))
    if result.get("validation"):
        print(json.dumps(result["validation"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
