#!/usr/bin/env python3
"""Zhihu companion pin tool.

Generate or publish a Zhihu pin that teases an article after it has been
published. Default mode prints a review draft; `--publish` calls the Zhihu CLI
adapter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content_platform.zhihu_promotion import build_pin_text, publish_article_pin  # noqa: E402


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
        print("=== 配套想法（审核稿）===")
        print(f"标题: {payload['title']}")
        print("---")
        print(payload["content"])
        print("---")
        print("确认后加 --publish 发布")
        return 0

    result = publish_article_pin(job, article_url=args.url, extra=args.extra)
    print(f"Pin published! ID: {result.get('id')}")
    print(result.get("url", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
