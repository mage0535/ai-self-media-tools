"""Zhihu CLI adapter for trend collection and short-form publishing.

The adapter wraps the `zhihu` binary from pyzhihu-cli. Hot/search data feeds
trend analysis; pin/ask/delete cover short-content operations that the article
publisher does not handle.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

BINARY = os.environ.get("ZHIHU_CLI_BIN") or shutil.which("zhihu") or str(Path.home() / ".local" / "bin" / "zhihu")


def _to_int(value: Any, default: int = 0) -> int:
    """Robust int coercion for API values that may be None/str/float."""
    if value is None:
        return default
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


class ZhihuCliError(RuntimeError):
    pass


class ZhihuCliAdapter:
    """Thin wrapper around the zhihu CLI with structured JSON output."""

    def __init__(self, binary: str = BINARY, timeout: int = 60):
        self.binary = binary
        self.timeout = timeout

    def _run(self, args: list[str]) -> str:
        if not Path(self.binary).is_file():
            raise ZhihuCliError(f"zhihu CLI not found: {self.binary} (install: uv tool install pyzhihu-cli)")
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
            raise ZhihuCliError(f"zhihu {args[0]} timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "zhihu CLI failed").strip()
            raise ZhihuCliError(f"zhihu {args[0]} failed: {msg[:300]}")
        return proc.stdout

    def _run_json(self, args: list[str]) -> Any:
        stdout = self._run(args)
        if not stdout.strip():
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ZhihuCliError(f"zhihu {args[0]} returned non-JSON: {stdout[:200]}") from exc

    def login_with_cookie(self, cookie_str: str) -> bool:
        """Persist a raw cookie string to the CLI store.

        The upstream CLI accepts cookies through argv, so use this only on a
        trusted single-user machine and never print the cookie.
        """
        self._run(["login", "--cookie", cookie_str])
        return True

    def is_authenticated(self) -> bool:
        try:
            stdout = self._run(["status"])
            return "Authenticated" in stdout
        except ZhihuCliError:
            return False

    def whoami(self) -> dict[str, Any]:
        """Return basic profile of the logged-in account, or an empty dict."""
        try:
            result = self._run_json(["whoami", "--json"])
            return result if isinstance(result, dict) else {}
        except ZhihuCliError:
            return {}

    def fetch_hot(self, limit: int = 20, with_answers: int = 0) -> list[dict[str, Any]]:
        """Return Zhihu hot-list items in the standard trend schema."""
        payload = self._run_json(["hot", "--json", "-l", str(limit), "-a", str(with_answers)])
        rows = payload if isinstance(payload, list) else payload.get("data") or payload.get("items") or []
        if not isinstance(rows, list):
            raise ZhihuCliError(f"zhihu hot returned unexpected structure: {type(rows).__name__}")
        items: list[dict[str, Any]] = []
        for row in rows:
            q = row.get("question") or {}
            title = str(q.get("title") or "").strip()
            if not title:
                continue
            reaction = row.get("reaction") or {}
            url = q.get("url") or f"https://www.zhihu.com/question/{q.get('id')}"
            pv = _to_int(reaction.get("new_pv"))
            items.append(
                {
                    "title": title,
                    "source": "zhihu",
                    "url": url,
                    "points": pv,
                    "metric": {
                        "new_pv": pv,
                        "new_pv_7d": _to_int(reaction.get("new_pv_7_days")),
                        "new_answers": _to_int(reaction.get("new_answer_num")),
                        "new_follows": _to_int(reaction.get("new_follow_num")),
                    },
                }
            )
        return items[:limit]

    def search(self, query: str, limit: int = 10, scope: str = "general") -> list[dict[str, Any]]:
        """Search Zhihu and normalize article/answer/question rows."""
        payload = self._run_json(["search", query, "--json", "-l", str(limit), "-t", scope])
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise ZhihuCliError(f"zhihu search returned unexpected structure: {type(data).__name__}")
        items: list[dict[str, Any]] = []
        for row in data[:limit]:
            obj = row.get("object") or {}
            title = str(obj.get("title") or obj.get("excerpt") or "").strip()
            if not title:
                continue
            items.append(
                {
                    "title": title[:120],
                    "source": "zhihu",
                    "url": obj.get("url") or "",
                    "points": _to_int(obj.get("voteup_count") or obj.get("follower_count")),
                    "type": obj.get("type", ""),
                    "author": ((obj.get("author") or {}).get("name")) or "",
                    "comment_count": _to_int(obj.get("comment_count")),
                }
            )
        return items

    def publish_pin(self, title: str, content: str = "", images: list[str] | None = None) -> dict[str, Any]:
        """Publish a Zhihu pin. Returns {id, url, raw}."""
        args = ["pin", title]
        if content:
            args += ["-c", content]
        for img in images or []:
            args += ["-i", str(img)]
        stdout = self._run(args)
        return _parse_publish_stdout(stdout)

    def publish_ask(self, title: str, detail: str = "", images: list[str] | None = None) -> dict[str, Any]:
        """Post a new Zhihu question. Returns {id, url, raw}."""
        if not title.rstrip().endswith(("？", "?")):
            title = title.rstrip() + "？"
        args = ["ask", title]
        if detail:
            args += ["-d", detail]
        for img in images or []:
            args += ["-i", str(img)]
        stdout = self._run(args)
        return _parse_publish_stdout(stdout)

    def delete_pin(self, pin_id: str) -> bool:
        self._run(["delete-pin", str(pin_id), "-y"])
        return True

    def delete_question(self, qid: str) -> bool:
        self._run(["delete-question", str(qid), "-y"])
        return True


def _parse_publish_stdout(stdout: str) -> dict[str, Any]:
    item_id = ""
    url = ""
    for line in stdout.splitlines():
        if "ID:" in line:
            item_id = line.split("ID:")[-1].strip()
        if line.strip().startswith("http"):
            url = line.strip()
    return {"id": item_id, "url": url, "raw": stdout.strip()}
