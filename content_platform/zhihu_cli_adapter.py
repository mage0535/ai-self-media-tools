"""Zhihu CLI adapter — wraps the `zhihu` binary (pyzhihu-cli) for trend collection
and short-form publishing (pins/questions) without Playwright.

Hot/search data feeds trend analysis; pin/ask/delete enable the short-content
operations ZhihuPublisher (Playwright, article-only) does not cover.

Binary: installed via `uv tool install pyzhihu-cli`, login state at ~/.zhihu-cli/cookies.json
(0600). Reuses the zhihu_raw.json cookie file through `zhihu login --cookie`.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

BINARY = os.environ.get("ZHIHU_CLI_BIN") or shutil.which("zhihu") or str(Path.home() / ".local" / "bin" / "zhihu")


def _to_int(value, default=0):
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

    # ------------------------------------------------------------------ base
    def _run(self, args):
        if not Path(self.binary).is_file():
            raise ZhihuCliError(f"zhihu CLI not found: {self.binary} (install: uv tool install pyzhihu-cli)")
        try:
            proc = subprocess.run(
                [self.binary] + args,
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

    def _run_json(self, args):
        stdout = self._run(args)
        if not stdout.strip():
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # some commands emit rich text on stdout even with --json; salvage
            raise ZhihuCliError(f"zhihu {args[0]} returned non-JSON: {stdout[:200]}")

    # --------------------------------------------------------------- auth
    def login_with_cookie(self, cookie_str: str) -> bool:
        """Persist a raw cookie string (z_c0=...; _xsrf=...; d_c0=...) to the CLI store.

        NOTE: the cookie travels via argv (zhihu CLI contract), so it is briefly
        visible in `ps`. Only use on a single-user trusted host.
        """
        self._run(["login", "--cookie", cookie_str])
        return True

    def is_authenticated(self) -> bool:
        try:
            stdout = self._run(["status"])
            return "Authenticated" in stdout
        except ZhihuCliError:
            return False

    def whoami(self) -> dict:
        """Return basic profile of the logged-in account (may be empty dict)."""
        try:
            return self._run_json(["whoami", "--json"])
        except ZhihuCliError:
            return {}

    # ------------------------------------------------------------- trends
    def fetch_hot(self, limit: int = 20, with_answers: int = 0) -> list:
        """Zhihu hot list with per-question heat metrics (new_pv, follows, answers).

        Returns items in the standard trend schema:
        {title, source:"zhihu", url, points (heat proxy), metric:{...}}
        """
        args = ["hot", "--json", "-l", str(limit), "-a", str(with_answers)]
        payload = self._run_json(args)
        rows = payload if isinstance(payload, list) else payload.get("data") or payload.get("items") or []
        if not isinstance(rows, list):
            raise ZhihuCliError(f"zhihu hot returned unexpected structure: {type(rows).__name__}")
        items = []
        for row in rows:
            q = row.get("question") or {}
            title = str(q.get("title") or "").strip()
            if not title:
                continue
            reaction = row.get("reaction") or {}
            url = q.get("url") or f"https://www.zhihu.com/question/{q.get('id')}"
            pv = _to_int(reaction.get("new_pv"))
            items.append({
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
            })
        return items[:limit]

    def search(self, query: str, limit: int = 10, scope: str = "general") -> list:
        """Search zhihu; returns article/answer/question rows with author/votes."""
        args = ["search", query, "--json", "-l", str(limit), "-t", scope]
        payload = self._run_json(args)
        data = payload.get("data") or []
        if not isinstance(data, list):
            raise ZhihuCliError(f"zhihu search returned unexpected structure: {type(data).__name__}")
        items = []
        for row in data[:limit]:
            obj = row.get("object") or {}
            t = obj.get("type", "")
            title = str(obj.get("title") or obj.get("excerpt") or "").strip()
            if not title:
                continue
            author = ((obj.get("author") or {}).get("name")) or ""
            items.append({
                "title": title[:120],
                "source": "zhihu",
                "url": obj.get("url") or "",
                "points": _to_int(obj.get("voteup_count") or obj.get("follower_count")),
                "type": t,
                "author": author,
                "comment_count": _to_int(obj.get("comment_count")),
            })
        return items

    # ---------------------------------------------------------- publishing
    def publish_pin(self, title: str, content: str = "", images: list | None = None) -> dict:
        """Publish a pin (想法). Returns {id, url}."""
        args = ["pin", title]
        if content:
            args += ["-c", content]
        for img in (images or []):
            args += ["-i", str(img)]
        stdout = self._run(args)
        pin_id = ""
        url = ""
        for line in stdout.splitlines():
            if "ID:" in line:
                pin_id = line.split("ID:")[-1].strip()
            if line.strip().startswith("http"):
                url = line.strip()
        return {"id": pin_id, "url": url, "raw": stdout.strip()}

    def publish_ask(self, title: str, detail: str = "", images: list | None = None) -> dict:
        """Post a new question (提问). Returns {id, url}.

        NOTE: Zhihu requires the question title to end with a question mark
        (？ or ?). Without it the API returns 400 "您还没有给问题添加问号".
        """
        if not title.rstrip().endswith(("？", "?")):
            title = title.rstrip() + "？"
        args = ["ask", title]
        if detail:
            args += ["-d", detail]
        for img in (images or []):
            args += ["-i", str(img)]
        stdout = self._run(args)
        qid = ""
        url = ""
        for line in stdout.splitlines():
            if "ID:" in line:
                qid = line.split("ID:")[-1].strip()
            if line.strip().startswith("http"):
                url = line.strip()
        return {"id": qid, "url": url, "raw": stdout.strip()}

    # ------------------------------------------------------------- delete
    def delete_pin(self, pin_id: str) -> bool:
        self._run(["delete-pin", str(pin_id), "-y"])
        return True

    def delete_question(self, qid: str) -> bool:
        self._run(["delete-question", str(qid), "-y"])
        return True
