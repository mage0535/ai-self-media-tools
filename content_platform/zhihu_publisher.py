"""Zhihu article publisher — MD import for formatting + pre-uploaded CDN images."""
import json, re
from pathlib import Path

from .auth_registry import resolve_cookie_file
from .formatters import format_for_platform
from .models import DeliveryResult


def _text_length(value):
    return len("".join(str(value or "").split()))


def _artifact_source(item):
    url = item.get("url") or item.get("public_url") or ""
    if isinstance(url, str) and url.startswith("http"):
        return url
    path = item.get("path") or ""
    if path and Path(path).is_file():
        return str(Path(path))
    return ""


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


def _mapped_sources(section_map, artifacts):
    lookup = {}
    for item in artifacts:
        source = _artifact_source(item)
        if not source:
            continue
        keys = {str(item.get("url") or ""), str(item.get("public_url") or ""), str(item.get("path") or "")}
        keys.add(Path(str(item.get("path") or source)).name)
        for key in keys:
            if key:
                lookup[key] = source
    sources = []
    for row in section_map:
        image = str(row.get("image") or "")
        source = lookup.get(image) or lookup.get(Path(image).name)
        if not source:
            return []
        sources.append(source)
    return sources


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
    if not _section_map_valid(section_map):
        missing.append("valid_section_image_map_3")
    elif len(_mapped_sources(section_map, artifacts)) < 3:
        missing.append("mapped_inline_images_3")
    if not isinstance(template, dict) or not template.get("selected"):
        missing.append("visual_template_selection")
    return missing


class ZhihuPublisher:
    def __init__(self, account="main", cookie_dir=str(Path.home() / "social-auto-upload" / "cookies"),
                 proxy="socks5://127.0.0.1:1080", headless=True, save_as_draft=True):
        self.account = account
        self.cookie_dir = cookie_dir
        self.proxy = proxy
        self.headless = headless
        self.save_as_draft = save_as_draft

    def _upload_to_zhihu_cdn(self, page, file_path):
        """Upload image file to zhihu CDN, return CDN URL."""
        result = []
        def on_resp(resp):
            if "api.zhihu.com/images" in resp.url and resp.status == 200:
                try:
                    data = json.loads(resp.body())
                    if data.get("src"): result.append(data["src"])
                except: pass
        page.on("response", on_resp)

        # Close any open modal first
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.query_selector('button[aria-label="图片"]').click()
        page.wait_for_timeout(1500)

        fi = page.query_selector("input.UploadPicture-input[type='file']")
        if not fi: return ""
        fi.set_input_files(file_path)

        for _ in range(25):
            page.wait_for_timeout(1000)
            if result: break

        # Close modal
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        # Second Escape to ensure modal is closed
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        return result[0] if result else ""

    def _import_markdown(self, page, md_path):
        """Import .md file into zhihu editor (formatting + CDN images)."""
        # Ensure no modal is blocking
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        page.query_selector('button[aria-label="导入" i]').click()
        page.wait_for_timeout(500)
        page.query_selector("text=导入文档MD/Doc").click()
        page.wait_for_timeout(1000)

        fis = page.query_selector_all("input[type='file']")
        for fi in fis:
            if ".markdown" in (fi.get_attribute("accept") or ""):
                fi.set_input_files(str(md_path))
                break

        # Wait for processing
        for _ in range(15):
            page.wait_for_timeout(1000)
            html = page.evaluate("() => document.querySelector('[contenteditable=true]')?.innerHTML || ''")
            if 'h3' in html or 'li' in html:
                break

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

    def deliver(self, job, platform):
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        title = formatted.get("title", job.get("title", ""))[:100]
        body_text = job.get("body", "")
        missing = _article_guard(job, title, body_text, formatted)
        if missing:
            return DeliveryResult(False, "blocked", error=f"zhihu article package incomplete: {', '.join(missing)}")

        cookie_file = resolve_cookie_file("zhihu", self.account, self.cookie_dir)
        if not cookie_file.is_file():
            return DeliveryResult(False, "blocked", error=f"zhihu cookie not found: {cookie_file}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return DeliveryResult(False, "blocked", error="playwright not installed")

        section_map = (
            formatted.get("section_image_map")
            or (job.get("draft_meta") or {}).get("section_image_map")
            or job.get("section_image_map")
            or []
        )
        cover_source = ""
        for item in job.get("artifacts", []):
            source = _artifact_source(item)
            if item.get("kind") == "cover" and source:
                cover_source = source
                break
        image_sources = _mapped_sources(section_map, job.get("artifacts", []))

        try:
            storage = json.loads(cookie_file.read_text(encoding="utf-8"))
        except Exception:
            return DeliveryResult(False, "failed", error="zhihu cookie file invalid")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless, args=["--no-sandbox"])
            context = browser.new_context(
                storage_state=storage if isinstance(storage, dict) else {"cookies": storage},
                locale="zh-CN",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                proxy={"server": self.proxy},
            )
            page = context.new_page()
            page.goto("https://zhuanlan.zhihu.com/write", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 1) Upload external images to zhihu CDN
            cdn_urls = []
            for i, img_source in enumerate([cover_source, *image_sources]):
                try:
                    local = str(img_source)
                    if str(img_source).startswith("http"):
                        import urllib.request
                        local = f"/tmp/zhihu_upload_{i}.jpg"
                        urllib.request.urlretrieve(img_source, local)
                    cdn = self._upload_to_zhihu_cdn(page, local)
                    if cdn:
                        # Fix domain: pic-private → pic1.zhimg (MD import only recognizes zhimg.com)
                        cdn = cdn.replace("pic-private.zhihu.com", "pic1.zhimg.com")
                        cdn = __import__("re").sub(r"~resize:[^?]+", "", cdn)
                        cdn_urls.append(cdn)
                except Exception as e:
                    print(f"  Upload {i} failed: {e}")

            md_body = body_text
            if cdn_urls:
                md_body = f"![cover]({cdn_urls[0]})\n\n{md_body}"
            import re as _re
            for row, url in zip(section_map, cdn_urls[1:]):
                label = str(row.get("purpose") or row.get("section") or "image")
                replaced = _re.sub(r'!\[([^\]]*)\]\(\)', f'![{label}]({url})', md_body, count=1)
                if replaced != md_body:
                    md_body = replaced
                    continue
                marker = str(row.get("section") or "").strip()
                if marker and marker in md_body:
                    md_body = md_body.replace(marker, f"{marker}\n\n![{label}]({url})", 1)
                    continue
                browser.close()
                return DeliveryResult(False, "blocked", error="zhihu article image markers do not match section_image_map")

            md_path = Path("/tmp") / f"zhihu_{job.get('id', 'article')}.md"
            md_path.write_text(md_body, encoding="utf-8")

            # 3) Fill title
            page.query_selector("textarea[placeholder*=\"标题\"]").fill(title)

            # 4) Clear editor (must use keyboard for Draft.js state)
            editor = page.query_selector(".public-DraftEditor-content")
            if editor:
                editor.click()
                page.wait_for_timeout(200)
                page.evaluate("document.execCommand('selectAll')")
                page.wait_for_timeout(100)
                page.keyboard.press("Backspace")
                page.wait_for_timeout(300)

            # 5) Import markdown
            self._import_markdown(page, md_path)
            page.wait_for_timeout(1000)

            if self.save_as_draft:
                page.wait_for_timeout(3000)
                browser.close()
                return DeliveryResult(True, "drafted", f"zhihu:{self.account}",
                                     error="zhihu draft with CDN images via MD import")
            else:
                pb = page.query_selector("button:has-text(\"发布\")")
                if not pb or pb.get_attribute("disabled"):
                    browser.close()
                    return DeliveryResult(False, "failed", error="zhihu publish button disabled")
                pb.click()
                page.wait_for_timeout(5000)
                browser.close()
                return DeliveryResult(True, "published", f"zhihu:{self.account}",
                                     error="zhihu article published with CDN images")
