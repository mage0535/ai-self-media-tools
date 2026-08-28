"""Collect fail-closed Video Channels hot-work evidence with private browser state."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.hot_work_intelligence import collect_logged_short_video_search


def resolve_state_file(explicit: str | Path | None) -> Path:
    configured = explicit or os.environ.get("SHIPINHAO_STORAGE_STATE") or os.environ.get("TENCENT_STORAGE_STATE")
    if configured:
        return Path(configured).expanduser()
    social_root = Path(
        os.environ.get("SOCIAL_AUTO_UPLOAD_DIR")
        or os.environ.get("SOCIAL_AUTO_UPLOAD_HOME")
        or str(Path.home() / "social-auto-upload")
    ).expanduser()
    return social_root / "cookies" / "tencent_uploader" / "main.json"


def _validate_state_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Video Channels storage state not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cookies"), list):
        raise ValueError(f"Video Channels storage state is not Playwright JSON: {path}")


def _safe_query_name(query: str) -> str:
    name = "".join(character if character.isalnum() or character in "-_" else "_" for character in query).strip("_")
    return name[:40] or "query"


def collect(args: argparse.Namespace) -> dict[str, Any]:
    state_file = resolve_state_file(args.state_file)
    _validate_state_file(state_file)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for query in args.query:
        rows, status = collect_logged_short_video_search(
            "shipinhao",
            query,
            state_file=state_file,
            output_dir=output_dir / _safe_query_name(query),
            limit=args.limit,
            timeout_ms=args.timeout_ms,
            proxy_url=args.proxy,
            route_name="cn_proxy" if args.proxy else "direct",
        )
        items.extend(rows)
        statuses.append(status)

    passed = bool(items) and all(status.get("status") == "ok" for status in statuses)
    report: dict[str, Any] = {
        "platform": "shipinhao",
        "status": "ok" if passed else "failed_no_real_hot_works",
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(items),
        "queries": list(args.query),
        "items": items if passed else [],
        "statuses": statuses,
        "contract": "official_url_title_visible_engagement_dom_snapshot_screenshot_captured_at_required",
    }
    report_path = output_dir / "shipinhao_hot_work_collection.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect real Video Channels hot works with an existing private storage state.")
    parser.add_argument("--query", action="append", required=True, help="Official discovery/search query. Repeatable.")
    parser.add_argument("--state-file", default="", help="Private Playwright storage-state JSON; defaults to the existing Tencent uploader state.")
    parser.add_argument("--output-dir", required=True, help="Private evidence output directory.")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument("--proxy", default=os.environ.get("CN_PROXY", ""), help="Optional CN proxy; socks5h is normalized by the collector.")
    return parser.parse_args(argv)


def main() -> int:
    try:
        report = collect(parse_args())
    except Exception as exc:
        print(json.dumps({"platform": "shipinhao", "status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"platform": "shipinhao", "status": report["status"], "count": report["count"], "report_path": report["report_path"]}, ensure_ascii=False))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
