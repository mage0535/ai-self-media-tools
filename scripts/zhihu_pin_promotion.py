#!/usr/bin/env python3
"""Zhihu companion pin (想法) tool — generate or publish a pin that teases an
article after it has been published.

Usage:
    python3 scripts/zhihu_pin_promotion.py <job.json> [--url https://zhuanlan.zhihu.com/p/XXX] [--publish]

Default (no --publish): print the generated pin text for human review.
With --publish: post the pin via the zhihu CLI adapter and print {id, url}.

Note: publish only after the article is actually visible on Zhihu — a pin
linking to an invisible draft is pointless.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content_platform.zhihu_promotion import build_pin_text, publish_article_pin  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Zhihu companion pin tool")
    parser.add_argument("job_file", help="Path to the article job JSON (needs title/body)")
    parser.add_argument("--url", default="", help="Published article URL to reference in the pin")
    parser.add_argument("--extra", default="", help="Extra line to append (e.g. engagement prompt)")
    parser.add_argument("--publish", action="store_true", help="Actually publish the pin (default: review only)")
    args = parser.parse_args()

    job = json.loads(Path(args.job_file).read_text(encoding="utf-8"))

    if not args.publish:
        payload = build_pin_text(job, article_url=args.url, extra=args.extra)
        print("=== 配套想法（审核稿）===")
        print(f"标题: {payload['title']}")
        print("---")
        print(payload["content"])
        print("---")
        print("确认后加 --publish 发布")
        return 0

    result = publish_article_pin(job, article_url=args.url, extra=args.extra)
    print(f"✓ Pin published! ID: {result.get('id')}")
    print(result.get("url", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
