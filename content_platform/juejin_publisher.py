"""Juejin article publisher — API-based, supports markdown + cover."""
import json
import urllib.request
from pathlib import Path

from .auth_registry import resolve_cookie_file
from .formatters import format_for_platform
from .models import DeliveryResult


def _text_length(value):
    return len("".join(str(value or "").split()))


def _public_url(item):
    url = item.get("url") or item.get("public_url") or item.get("path") or ""
    return url if isinstance(url, str) and url.startswith("http") else ""


def _section_map_valid(section_map):
    if not isinstance(section_map, list) or len(section_map) < 3:
        return False
    seen = set()
    for item in section_map:
        if not isinstance(item, dict):
            return False
        image = str(item.get("image") or "").strip()
        if not image or image in seen:
            return False
        seen.add(image)
        if not item.get("section") or not item.get("purpose") or not item.get("adjacent_to_text"):
            return False
        purpose = str(item.get("purpose") or item.get("match_reason") or "").casefold()
        if any(word in purpose for word in ["decorative", "random", "scenery", "unrelated", "placeholder"]):
            return False
    return True


def _mapped_public_urls(section_map, artifacts):
    lookup = {}
    for item in artifacts:
        url = _public_url(item)
        if not url:
            continue
        keys = {str(item.get("url") or ""), str(item.get("public_url") or ""), str(item.get("path") or "")}
        keys.add(Path(str(item.get("path") or url)).name)
        for key in keys:
            if key:
                lookup[key] = url
    urls = []
    for row in section_map:
        image = str(row.get("image") or "")
        url = lookup.get(image) or lookup.get(Path(image).name)
        if not url:
            return []
        urls.append(url)
    return urls


def _renderer_visibility_evidence(response, expected_urls):
    response = response if isinstance(response, dict) else {}
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    evidence = data.get("target_renderer_evidence") or response.get("target_renderer_evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    observed_urls = list(
        evidence.get("public_inline_image_urls")
        or evidence.get("inline_image_urls")
        or data.get("public_inline_image_urls")
        or data.get("inline_image_urls")
        or data.get("rendered_image_urls")
        or []
    )
    visible = evidence.get("verified") is True or data.get("editor_visible") is True
    mapping_count = int(evidence.get("mapping_count") or data.get("mapping_count") or len(observed_urls))
    passed = visible and mapping_count >= 3 and set(expected_urls).issubset(set(str(url) for url in observed_urls))
    return {
        "renderer": str(evidence.get("renderer") or data.get("target_renderer") or "juejin_markdown_editor"),
        "verified": passed,
        "mapping_count": mapping_count,
        "public_inline_image_urls": [str(url) for url in observed_urls],
        "response_evidence": evidence,
        "failure": "editor visibility response missing or incomplete" if not passed else "",
    }


def _record_renderer_evidence(job, evidence):
    metadata = job.get("draft_meta") if isinstance(job.get("draft_meta"), dict) else {}
    contract = metadata.get("article_media_contract")
    contract_path = None
    if isinstance(contract, str):
        contract_path = Path(contract)
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            contract = None
    if not isinstance(contract, dict):
        return
    handoff = contract.get("handoff_contract") if isinstance(contract.get("handoff_contract"), dict) else contract
    handoff["target_renderer_evidence"] = evidence
    handoff["state"] = "handoff_ready" if evidence.get("verified") is True else "handoff_blocked"
    if contract_path is None and metadata.get("article_media_contract_path"):
        contract_path = Path(str(metadata["article_media_contract_path"]))
    if contract_path:
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")


def _article_guard(job, title, body_text, platform_payload):
    artifacts = job.get("artifacts") or []
    draft_meta = job.get("draft_meta") or {}
    section_map = (
        platform_payload.get("section_image_map")
        or draft_meta.get("section_image_map")
        or job.get("section_image_map")
        or []
    )
    template = (
        platform_payload.get("visual_template_selection")
        or draft_meta.get("visual_template_selection")
        or job.get("visual_template_selection")
        or {}
    )
    covers = [item for item in artifacts if item.get("kind") == "cover" and _public_url(item)]
    images = [item for item in artifacts if item.get("kind") == "image" and _public_url(item)]
    missing = []
    if _text_length(title) < 8:
        missing.append("title")
    if _text_length(body_text) < 1200:
        missing.append("body_1200_chars")
    if not covers:
        missing.append("public_cover_image")
    if len(images) < 3:
        missing.append("public_inline_images_3")
    if not _section_map_valid(section_map):
        missing.append("valid_section_image_map_3")
    elif len(_mapped_public_urls(section_map, artifacts)) < 3:
        missing.append("mapped_public_inline_images_3")
    if not isinstance(template, dict) or not template.get("selected"):
        missing.append("visual_template_selection")
    return missing


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
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        title = formatted.get("title", job.get("title", ""))[:100]
        body_text = job.get("body", "")
        missing = _article_guard(job, title, body_text, formatted)
        if missing:
            return DeliveryResult(False, "blocked", error=f"juejin article package incomplete: {', '.join(missing)}")

        cookie_str, csrf, storage = self._cookie_and_csrf()
        if not cookie_str:
            return DeliveryResult(False, "blocked", error="juejin cookie not found")

        section_map = (
            formatted.get("section_image_map")
            or (job.get("draft_meta") or {}).get("section_image_map")
            or job.get("section_image_map")
            or []
        )
        mapped_urls = _mapped_public_urls(section_map, job.get("artifacts", []))
        md_body = body_text
        import re as _re

        for row, url in zip(section_map, mapped_urls):
            label = str(row.get("purpose") or row.get("section") or "image")
            replaced = _re.sub(r'!\[([^\]]*)\]\(\)', f'![{label}]({url})', md_body, count=1)
            if replaced != md_body:
                md_body = replaced
                continue
            marker = str(row.get("section") or "").strip()
            if marker and marker in md_body:
                md_body = md_body.replace(marker, f"{marker}\n\n![{label}]({url})", 1)
                continue
            return DeliveryResult(False, "blocked", error="juejin article image markers do not match section_image_map")

        # The production contract supplies the adaptive public cover directly.
        cover = str(formatted.get("cover_image") or "")
        if not cover:
            cover = next((_public_url(item) for item in job.get("artifacts", []) if item.get("kind") == "cover"), "")
        inline_urls = list(formatted.get("public_inline_image_urls") or formatted.get("inline_image_urls") or mapped_urls)

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
            "inline_image_urls": inline_urls,
            "public_inline_image_urls": inline_urls,
        })
        if result.get("err_no") != 0:
            return DeliveryResult(False, "failed", error=f"juejin create draft failed: {result.get('err_msg','')[:200]}")
        draft_id = result["data"]["id"]
        detail = self._api("/content_api/v1/article_draft/detail", {"draft_id": draft_id})
        if detail.get("err_no") != 0:
            return DeliveryResult(False, "blocked", f"juejin:{draft_id}", error="juejin editor postcheck failed")
        renderer_evidence = _renderer_visibility_evidence(detail, mapped_urls)
        _record_renderer_evidence(job, renderer_evidence)
        if not renderer_evidence["verified"]:
            return DeliveryResult(False, "blocked", f"juejin:{result.get('data', {}).get('id', '')}", error="juejin editor visibility response missing or incomplete")
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
