"""Zhihu Open Platform adapter wrapping the `zhihu-search` CLI.

This read-only channel uses the Zhihu Open Platform Access Secret stored by the
CLI itself. Publishing remains handled by the existing cookie/browser route.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

BINARY = os.environ.get("ZHIHU_SEARCH_BIN") or shutil.which("zhihu-search") or str(Path.home() / ".local" / "bin" / "zhihu-search")


class ZhihuOpenError(RuntimeError):
    pass


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


class ZhihuOpenAdapter:
    """Thin wrapper around the official `zhihu-search` CLI."""

    def __init__(self, binary: str = BINARY, timeout: int = 120):
        self.binary = binary
        self.timeout = timeout

    def _run(self, args: list[str]) -> str:
        if not Path(self.binary).is_file():
            raise ZhihuOpenError(
                f"zhihu-search CLI not found: {self.binary} "
                "(install it and persist the Access Secret with zhihu-search --save-token)"
            )
        try:
            proc = subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ZhihuOpenError(f"zhihu-search {args[0]} timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "zhihu-search failed").strip()
            raise ZhihuOpenError(f"zhihu-search {args[0]} failed: {message[:300]}")
        return proc.stdout

    def _run_json(self, args: list[str]) -> Any:
        stdout = self._run(args)
        if not stdout.strip():
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ZhihuOpenError(f"zhihu-search {args[0]} returned non-JSON: {stdout[:200]}") from exc

    def check_token(self) -> dict[str, Any]:
        try:
            return {"ok": True, "source": self._run(["--check-token"]).strip()}
        except ZhihuOpenError:
            return {"ok": False, "source": ""}

    def save_token(self, secret: str) -> bool:
        self._run(["--save-token", secret])
        return True

    def quota(self) -> dict[str, Any]:
        return {"quota": self._run(["--quota"]).strip()}

    def trending(self, limit: int = 20, retries: int = 2, retry_delay: int = 15) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {}
        for attempt in range(retries + 1):
            try:
                payload = self._run_json(["trending", "--limit", str(limit), "--format", "json"])
                break
            except ZhihuOpenError as exc:
                if "rate limit" in str(exc).lower() and attempt < retries:
                    import time

                    time.sleep(retry_delay)
                    continue
                raise
        items = payload.get("data", {}).get("Items") or []
        if not isinstance(items, list):
            raise ZhihuOpenError(f"zhihu-search trending unexpected structure: {type(items).__name__}")
        output = []
        for row in items:
            title = str(row.get("Title") or row.get("title") or "").strip()
            if not title:
                continue
            output.append(
                {
                    "title": title,
                    "source": "zhihu",
                    "url": row.get("Url") or row.get("url") or "",
                    "points": _to_int(row.get("hot_score") or row.get("Score") or row.get("Heat")),
                    "metric": {"rank": _to_int(row.get("index") or row.get("rank") or row.get("Rank"))},
                }
            )
        return output[:limit]

    def search(self, query: str, limit: int = 10, scope: str = "zhihu") -> list[dict[str, Any]]:
        payload = self._run_json(["search", query, "--scope", scope, "--count", str(limit), "--format", "json"])
        items = payload.get("data", {}).get("Items") or []
        if not isinstance(items, list):
            raise ZhihuOpenError(f"zhihu-search search unexpected structure: {type(items).__name__}")
        output = []
        for row in items[:limit]:
            title = str(row.get("Title") or row.get("title") or "").strip()
            if not title:
                continue
            output.append(
                {
                    "title": title[:150],
                    "source": "zhihu_open",
                    "url": row.get("Url") or row.get("url") or "",
                    "points": _to_int(row.get("VoteUpCount") or row.get("LikeCount")),
                    "type": row.get("ContentType") or row.get("type", ""),
                    "author": row.get("AuthorName") or ((row.get("author") or {}).get("name") or ""),
                    "comment_count": _to_int(row.get("CommentCount")),
                    "content_excerpt": str(row.get("ContentText") or row.get("excerpt") or "")[:200],
                }
            )
        return output

    def ask(self, query: str, model: str = "fast") -> dict[str, Any]:
        payload = self._run_json(["ask", query, "--model", model, "--format", "json"])
        data = payload.get("data") or {}
        return {
            "answer": data.get("content", ""),
            "model": data.get("model", model),
            "id": data.get("id", ""),
            "quota": payload.get("quota", {}),
        }

    def user_contents(self, content_type: str = "all", limit: int = 20, sort_field: str = "ts", sort_order: str = "desc") -> list[dict[str, Any]]:
        payload = self._run_json(
            [
                "user-contents",
                "--content-type",
                content_type,
                "--limit",
                str(limit),
                "--sort-field",
                sort_field,
                "--sort-order",
                sort_order,
                "--format",
                "json",
            ]
        )
        items = payload.get("data", {}).get("Items") or []
        if not isinstance(items, list):
            raise ZhihuOpenError(f"zhihu-search user-contents unexpected structure: {type(items).__name__}")
        return [
            {
                "title": str(item.get("Title") or item.get("title") or "")[:150],
                "type": item.get("ContentType") or item.get("type", ""),
                "url": item.get("Url") or item.get("url") or "",
                "likes": _to_int(item.get("LikeCount") or item.get("VoteUpCount")),
                "comments": _to_int(item.get("CommentCount")),
                "time": item.get("EditTime") or item.get("CreateTime") or item.get("time"),
            }
            for item in items[:limit]
        ]

    def user_followees(self, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._run_json(["user-followees", "--limit", str(limit), "--format", "json"])
        items = payload.get("data", {}).get("Items") or payload.get("data", {}).get("users") or []
        return items[:limit] if isinstance(items, list) else []

    def user_collections(self, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._run_json(["user-collections", "--limit", str(limit), "--format", "json"])
        items = payload.get("data", {}).get("Items") or []
        return items[:limit] if isinstance(items, list) else []
