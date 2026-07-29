"""Juejin article publisher — API-based, supports markdown + cover."""
import json
import urllib.request
from pathlib import Path

from .auth_registry import resolve_cookie_file
from .formatters import format_for_platform
from .models import DeliveryResult


def _read_setting(name, env_file, default=""):
    if env_file and Path(env_file).is_file():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            if k.strip() == name:
                return v.strip().strip("'\"")
    return default


class JuejinPublisher:
    """掘金文章发布器 — 基于 API，支持 Markdown + 封面."""
    def __init__(self, account="main", cookie_dir=str(Path.home() / "social-auto-upload" / "cookies"),
                 proxy="socks5://127.0.0.1:1080", save_as_draft=True):
        self.account = account
        self.cookie_dir = cookie_dir
        self.proxy = proxy
        self.save_as_draft = save_as_draft

    def _cookie_and_csrf(self):
        cookie_file = resolve_cookie_file("juejin", self.account, self.cookie_dir)
        if not cookie_file.is_file():
            return None, None, ""
        storage = json.loads(cookie_file.read_text(encoding="utf-8"))
        cookies = storage.get("cookies", []) if isinstance(storage, dict) else (storage if isinstance(storage, list) else [])
        cookie_str = "; ".join([f'{item["name"]}={item["value"]}' for item in cookies if item.get("value")])
        csrf = ""
        for item in cookies:
            if item.get("name") in ("csrf_token", "XSRF-TOKEN", "sso_jae_rem"):
                csrf = item.get("value", "")
                break
        return cookie_str, csrf, storage

    def _api(self, endpoint, data):
        cookie_str, csrf, _ = self._cookie_and_csrf()
        if not cookie_str:
            return {"err_no": -1, "err_msg": "cookie not found"}
        headers = {
            "Cookie": cookie_str,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Origin": "https://juejin.cn",
            "Referer": "https://juejin.cn/",
            "x-csrf-token": csrf,
        }
        body = json.dumps(data).encode()
        req = urllib.request.Request(f"https://api.juejin.cn{endpoint}", data=body, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        except urllib.request.HTTPError as e:
            return {"err_no": e.code, "err_msg": e.read().decode()[:200]}
        except Exception as e:
            return {"err_no": -1, "err_msg": str(e)}

    def deliver(self, job, platform):
        cookie_str, csrf, storage = self._cookie_and_csrf()
        if not cookie_str:
            return DeliveryResult(False, "blocked", error="juejin cookie not found")

        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        title = formatted.get("title", job.get("title", ""))[:100]
        body_text = job.get("body", "")

        # Build markdown with CDN image URLs at marker positions
        md_body = body_text
        for item in job.get("artifacts", []):
            if item.get("kind") in ("image", "cover"):
                url = item.get("url") or item.get("public_url") or ""
                if url.startswith("http"):
                    # Replace first empty image marker with the actual URL
                    import re as _re
                    replaced = _re.sub(r'!\[([^\]]*)\]\(\)', f'![\\1]({url})', md_body, count=1)
                    if replaced != md_body:
                        md_body = replaced
                    else:
                        # No empty marker found, append at end
                        md_body += f"\n\n![插图]({url})"

        # Extract cover — only use if empty or already a juejin URL
        cover = ""
        for item in job.get("artifacts", []):
            if item.get("kind") == "cover":
                url = item.get("url") or ""
                if "juejin" in url or "zhimg" in url:
                    cover = url
                    break

        # 1) Create draft
        brief = body_text[:100].replace("\n", " ") if body_text else title[:50]
        result = self._api("/content_api/v1/article_draft/create", {
            "title": title,
            "mark_content": md_body,
            "brief_content": brief,
            "category_id": "1",
            "tag_ids": ["6809640405535096840"],
            "edit_type": 10,
            "cover_image": cover,
        })
        if result.get("err_no") != 0:
            return DeliveryResult(False, "failed", error=f"juejin create draft failed: {result.get('err_msg','')[:200]}")
        draft_id = result["data"]["id"]

        if self.save_as_draft:
            return DeliveryResult(True, "drafted", f"juejin:{draft_id}",
                                 error=f"juejin draft created: {draft_id}")

        # 2) Publish
        pub_result = self._api("/content_api/v1/article/publish", {
            "draft_id": draft_id,
            "sync_to_org": False,
            "column_ids": [],
            "theme_ids": [],
        })
        if pub_result.get("err_no") != 0:
            return DeliveryResult(True, "drafted", f"juejin:{draft_id}",
                                 error=f"juejin draft saved but publish blocked: {pub_result.get('err_msg','')[:200]}")
        article_id = pub_result.get("data", {}).get("article_id", "")
        return DeliveryResult(True, "published", f"juejin:{article_id}",
                             error=f"https://juejin.cn/post/{article_id}")
