"""Zhihu article publisher — MD import for formatting + pre-uploaded CDN images."""
import json, re
from pathlib import Path

from .auth_registry import resolve_cookie_file
from .formatters import format_for_platform
from .models import DeliveryResult


class ZhihuPublisher:
    def __init__(self, account="main", cookie_dir="/root/social-auto-upload/cookies",
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
        cookie_file = resolve_cookie_file("zhihu", self.account, self.cookie_dir)
        if not cookie_file.is_file():
            return DeliveryResult(False, "blocked", error=f"zhihu cookie not found: {cookie_file}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return DeliveryResult(False, "blocked", error="playwright not installed")

        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        title = formatted.get("title", job.get("title", ""))[:100]
        body_text = job.get("body", "")

        # Collect external image URLs (separate cover from inline)
        cover_url = ""
        ext_images = []
        for item in job.get("artifacts", []):
            if item.get("kind") == "cover":
                url = item.get("url") or item.get("public_url") or ""
                if url.startswith("http"): cover_url = url
            elif item.get("kind") == "image":
                url = item.get("url") or item.get("public_url") or ""
                if url.startswith("http"): ext_images.append(url)

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
            for i, img_url in enumerate(ext_images):
                try:
                    import urllib.request
                    local = f"/tmp/zhihu_upload_{i}.jpg"
                    urllib.request.urlretrieve(img_url, local)
                    cdn = self._upload_to_zhihu_cdn(page, local)
                    if cdn:
                        # Fix domain: pic-private → pic1.zhimg (MD import only recognizes zhimg.com)
                        cdn = cdn.replace("pic-private.zhihu.com", "pic1.zhimg.com")
                        cdn = __import__("re").sub(r"~resize:[^?]+", "", cdn)
                        cdn_urls.append(cdn)
                except Exception as e:
                    print(f"  Upload {i} failed: {e}")

            # 2) Build markdown with CDN image URLs at marker positions
            md_body = body_text
            for url in cdn_urls:
                # Replace the first empty image marker with the CDN URL
                # Markers look like: ![工具对比]  or  ![插图]
                import re as _re
                replaced = _re.sub(r'!\[([^\]]*)\]\(\)', f'![插图]({url})', md_body, count=1)
                if replaced == md_body:
                    # No empty marker found, append at end
                    md_body += f"\n\n![插图]({url})"
                else:
                    md_body = replaced

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
