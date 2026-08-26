"""Juejin article publisher — API-based, supports markdown + cover."""
import json
import urllib.request
import urllib.parse
import tempfile
from pathlib import Path

from .auth_registry import resolve_cookie_file
from .formatters import format_for_platform
from .models import DeliveryResult


def _text_length(value):
    return len("".join(str(value or "").split()))


def _public_url(item):
    url = item.get("url") or item.get("public_url") or item.get("path") or ""
    return url if isinstance(url, str) and url.startswith("http") else ""


def _artifact_source(item):
    path = Path(str(item.get("path") or ""))
    if path.is_file():
        return str(path)
    return _public_url(item)


def _juejin_cdn_url(url):
    host = (urllib.parse.urlparse(str(url or "")).hostname or "").casefold()
    return bool(host and (host.endswith(".juejin.cn") or host.endswith(".byteimg.com")))


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


def _mapped_sources(section_map, artifacts):
    lookup = {}
    for item in artifacts:
        source = _artifact_source(item)
        if not source:
            continue
        for key in {str(item.get("url") or ""), str(item.get("public_url") or ""), str(item.get("path") or ""), Path(source).name}:
            if key:
                lookup[key] = source
    return [lookup.get(str(row.get("image") or "")) or lookup.get(Path(str(row.get("image") or "")).name) for row in section_map]


def _renderer_visibility_evidence(response, expected_urls, *, expected_cover="", expected_markdown=""):
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
    mark_content = str(data.get("mark_content") or data.get("markdown") or response.get("mark_content") or "")
    cover_image = str(data.get("cover_image") or response.get("cover_image") or "")
    if not observed_urls:
        observed_urls = [url for url in expected_urls if url and url in mark_content]
    draft_id = str(data.get("id") or data.get("draft_id") or "")
    exact_markdown = bool(expected_markdown and mark_content and mark_content.strip() == expected_markdown.strip())
    visible = bool(draft_id and exact_markdown and expected_cover and cover_image == expected_cover)
    visible = visible or (evidence.get("verified") is True and data.get("editor_visible") is True)
    mapping_count = int(evidence.get("mapping_count") or data.get("mapping_count") or len(observed_urls))
    passed = visible and mapping_count >= 3 and set(expected_urls).issubset(set(str(url) for url in observed_urls))
    return {
        "renderer": str(evidence.get("renderer") or data.get("target_renderer") or "juejin_markdown_editor"),
        "verified": passed,
        "mapping_count": mapping_count,
        "public_inline_image_urls": [str(url) for url in observed_urls],
        "response_evidence": evidence,
        "draft_id": draft_id,
        "cover_verified": bool(expected_cover and cover_image == expected_cover),
        "markdown_verified": exact_markdown,
        "failure": "editor visibility response missing or incomplete" if not passed else "",
    }


def _record_renderer_evidence(job, evidence, uploaded_urls=None):
    metadata = job.get("draft_meta") if isinstance(job.get("draft_meta"), dict) else {}
    contract = metadata.get("article_media_contract")
    contract_path = None
    if not contract:
        contract_path = next((Path(str(item.get("path") or "")) for item in job.get("artifacts") or [] if item.get("kind") == "article_media_contract"), None)
        contract = str(contract_path) if contract_path else None
    if isinstance(contract, str):
        contract_path = Path(contract)
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            contract = None
    if not isinstance(contract, dict):
        return
    handoff = contract.get("handoff_contract") if isinstance(contract.get("handoff_contract"), dict) else contract
    if uploaded_urls:
        for artifact, url in zip(handoff.get("artifacts") or [], uploaded_urls):
            if isinstance(artifact, dict):
                artifact["public_url"] = url
        cdn_passed = len(uploaded_urls) == 4 and len(set(uploaded_urls)) == 4 and all(_juejin_cdn_url(url) for url in uploaded_urls)
        handoff["platform_upload_required"] = True
        handoff["platform_cdn_evidence"] = {"passed": cdn_passed, "urls": list(uploaded_urls), "platform": "juejin", "count": len(uploaded_urls)}
    handoff["target_renderer_evidence"] = evidence
    handoff["state"] = "handoff_ready" if evidence.get("verified") is True else "handoff_blocked"
    if contract_path is None and metadata.get("article_media_contract_path"):
        contract_path = Path(str(metadata["article_media_contract_path"]))
    if contract_path:
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")


def _article_contract(job):
    metadata = job.get("draft_meta") if isinstance(job.get("draft_meta"), dict) else {}
    contract = metadata.get("article_media_contract")
    if not contract:
        contract = next((item.get("path") for item in job.get("artifacts") or [] if item.get("kind") == "article_media_contract"), None)
    if isinstance(contract, str) and Path(contract).is_file():
        try:
            contract = json.loads(Path(contract).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return contract if isinstance(contract, dict) else {}


def _article_guard(job, title, body_text, platform_payload):
    artifacts = job.get("artifacts") or []
    draft_meta = job.get("draft_meta") or {}
    section_map = (
        platform_payload.get("section_image_map")
        or draft_meta.get("section_image_map")
        or job.get("section_image_map")
        or _article_contract(job).get("section_image_map")
        or []
    )
    template = (
        platform_payload.get("visual_template_selection")
        or draft_meta.get("visual_template_selection")
        or job.get("visual_template_selection")
        or {}
    )
    covers = [item for item in artifacts if item.get("kind") == "cover" and _artifact_source(item)]
    images = [item for item in artifacts if item.get("kind") == "image" and _artifact_source(item)]
    missing = []
    if _text_length(title) < 8:
        missing.append("title")
    if _text_length(body_text) < 1200:
        missing.append("body_1200_chars")
    if not covers:
        missing.append("cover_image")
    if len(images) < 3:
        missing.append("inline_images_3")
    mapped_images = [str(item.get("image") or "") for item in section_map if isinstance(item, dict)]
    if mapped_images and len(mapped_images) != len(set(mapped_images)):
        missing.append("duplicate_media_assets")
    if not _section_map_valid(section_map):
        missing.append("valid_section_image_map_3")
    elif not all(_mapped_sources(section_map, artifacts)):
        missing.append("mapped_inline_images_3")
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

    def _upload_image(self, source):
        urls = self._upload_images([source])
        return urls[0] if urls else ""

    def _upload_images(self, sources):
        self._last_upload_error = ""
        sources = [str(source or "") for source in sources]
        if all(_juejin_cdn_url(source) for source in sources):
            return sources
        _, _, storage = self._cookie_and_csrf()
        if not storage:
            return []
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []
        urls, temporary_files = [], []
        try:
          with sync_playwright() as pw:
            browser = None
            context = None
            try:
              browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
              context_options = {"storage_state": storage if isinstance(storage, dict) else {"cookies": storage}, "locale": "zh-CN", "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
              if self.proxy:
                  context_options["proxy"] = {"server": self.proxy}
              context = browser.new_context(**context_options)
              page = context.new_page()
              page.goto("https://juejin.cn/editor/drafts/new?v=2", wait_until="networkidle", timeout=60000)
              if "/editor/" not in page.url:
                  self._last_upload_error = "juejin editor login expired"
                  return []
              editor = page.locator(".CodeMirror")
              upload = page.locator('.bytemd-toolbar-icon[bytemd-tippy-path="5"]').first
              for source in sources:
                if _juejin_cdn_url(source):
                    urls.append(source)
                    continue
                if source.startswith(("http://", "https://")):
                    suffix = Path(urllib.parse.urlparse(source).path).suffix or ".jpg"
                    target = Path(tempfile.gettempdir()) / f"juejin-source-{len(temporary_files)}{suffix}"
                    try:
                        urllib.request.urlretrieve(source, target)
                        temporary_files.append(target)
                        source = str(target)
                    except Exception as exc:
                        self._last_upload_error = f"source download failed: {type(exc).__name__}"
                        urls.append("")
                        continue
                path = Path(source)
                if not path.is_file() or path.stat().st_size <= 0 or upload.count() != 1:
                    self._last_upload_error = "juejin image upload control missing or source unreadable"
                    urls.append("")
                    continue
                before = editor.evaluate("e => e.CodeMirror && e.CodeMirror.getValue()") or ""
                try:
                    with page.expect_file_chooser(timeout=5000) as chooser:
                        upload.click()
                    chooser.value.set_files(str(path))
                    value = before
                    for _ in range(30):
                        page.wait_for_timeout(1000)
                        value = editor.evaluate("e => e.CodeMirror && e.CodeMirror.getValue()") or ""
                        if value != before and "http" in value:
                            break
                    matches = __import__("re").findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", value)
                    url = matches[-1] if matches and _juejin_cdn_url(matches[-1]) else ""
                    if not url:
                        self._last_upload_error = "juejin ImageX returned no verified CDN URL"
                    urls.append(url)
                except Exception as exc:
                    self._last_upload_error = f"juejin ImageX upload failed: {type(exc).__name__}"
                    urls.append("")
            finally:
              if context is not None:
                  context.close()
              if browser is not None:
                  browser.close()
        finally:
            for path in temporary_files:
                path.unlink(missing_ok=True)
        return urls

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
            or _article_contract(job).get("section_image_map")
            or []
        )
        artifacts = job.get("artifacts", [])
        cover_source = next((_artifact_source(item) for item in artifacts if item.get("kind") == "cover"), "")
        image_sources = _mapped_sources(section_map, artifacts)
        selected_sources = [cover_source, *image_sources]
        if not cover_source or not all(image_sources) or len(selected_sources) != len(set(selected_sources)):
            return DeliveryResult(False, "blocked", error="juejin selected media contains missing or duplicate assets")
        uploaded = self._upload_images(selected_sources)
        if len(uploaded) != len(section_map) + 1 or any(not url.startswith("http") for url in uploaded):
            detail = getattr(self, "_last_upload_error", "")
            return DeliveryResult(False, "blocked", error=f"juejin platform image upload incomplete: {len([url for url in uploaded if url])}/{len(section_map)+1}; {detail}".rstrip("; "))
        cover, mapped_urls = uploaded[0], uploaded[1:]
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
        renderer_evidence = _renderer_visibility_evidence(detail, mapped_urls, expected_cover=cover, expected_markdown=md_body)
        _record_renderer_evidence(job, renderer_evidence, [cover, *mapped_urls])
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
