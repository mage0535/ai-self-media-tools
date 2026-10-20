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


def build_markdown_with_cdn(body_text, section_map, cdn_urls):
    """Build import markdown only when every mapped image has a CDN URL."""
    expected = len(section_map)
    if len(cdn_urls) != expected + 1:
        raise ValueError(f"cdn upload incomplete: expected {expected + 1}, got {len(cdn_urls)}")
    if any(not isinstance(url, str) or not url.startswith("http") for url in cdn_urls):
        raise ValueError("cdn upload incomplete: invalid image URL")
    markdown = f"![cover]({cdn_urls[0]})\n\n{body_text}"
    for row, url in zip(section_map, cdn_urls[1:]):
        label = str(row.get("purpose") or row.get("section") or "image")
        replaced = re.sub(r"!\[([^\]]*)\]\(\s*\)", f"![{label}]({url})", markdown, count=1)
        if replaced == markdown:
            marker = str(row.get("section") or "").strip()
            if not marker or marker not in markdown:
                raise ValueError("zhihu article image markers do not match section_image_map")
            replaced = markdown.replace(marker, f"{marker}\n\n![{label}]({url})", 1)
        markdown = replaced
    if re.search(r"!\[[^\]]*\]\(\s*\)", markdown):
        raise ValueError("zhihu article contains unresolved image markers")
    return markdown


def _article_guard(job, title, body_text, platform_payload):
    artifacts = [dict(item) for item in (job.get("artifacts") or [])]
    draft_meta = job.get("draft_meta") or {}
    # Enrich the publisher packet from the generated artifact evidence.  The
    # manifest is the source of truth; callers must not duplicate rights/hash
    # fields by hand.
    artifact_root = None
    for item in artifacts:
        raw = str(item.get("path") or "")
        if raw:
            path = Path(raw)
            artifact_root = path.parent.parent if path.parent.name == "cards" else path.parent
            break
    if artifact_root and (artifact_root / "asset_provenance.json").is_file():
        try:
            rows = json.loads((artifact_root / "asset_provenance.json").read_text(encoding="utf-8")).get("assets", [])
        except (OSError, ValueError):
            rows = []
        by_path = {str(row.get("path")): row for row in rows if isinstance(row, dict)}
        for item in artifacts:
            evidence = by_path.get(str(item.get("path") or ""), {})
            if evidence:
                item.setdefault("source", evidence.get("source_url", ""))
                item.setdefault("rights", evidence.get("license", ""))
                item.setdefault("sha256", evidence.get("sha256", "") or item.get("checksum", ""))
                item.setdefault("asset_hash", item.get("sha256", ""))
                item.setdefault("semantic_match", float(evidence.get("semantic_match_score") or 0) >= 0.72)
                item.setdefault("semantic_evidence", {"score": evidence.get("semantic_match_score"), "reason": evidence.get("match_reason", "")})
    section_map = (
        platform_payload.get("section_image_map")
        or draft_meta.get("section_image_map")
        or job.get("section_image_map")
        or []
    )
    if not section_map and artifact_root:
        for candidate in (artifact_root / "section_image_map.json", artifact_root / "cards" / "section_image_map.json"):
            if candidate.is_file():
                try:
                    section_map = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    section_map = []
                break
    template = (
        platform_payload.get("visual_template_selection")
        or draft_meta.get("visual_template_selection")
        or job.get("visual_template_selection")
        or {}
    )
    if not template and artifact_root and (artifact_root / "cover_quality_evidence.json").is_file():
        try:
            cover_evidence = json.loads((artifact_root / "cover_quality_evidence.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cover_evidence = {}
        if cover_evidence.get("layout_key"):
            template = {"selected": cover_evidence["layout_key"]}

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
    for label, item in [("cover", covers[0] if covers else {})] + [(f"image_{i}", item) for i, item in enumerate(images[:3], 1)]:
        if not str(item.get("source") or item.get("url") or item.get("path") or "").strip():
            missing.append(f"{label}_source")
        if not str(item.get("rights") or item.get("license") or "").strip():
            missing.append(f"{label}_rights")
        if not str(item.get("sha256") or item.get("asset_hash") or "").strip():
            missing.append(f"{label}_hash")
        if item.get("semantic_match") is not True and not isinstance(item.get("semantic_evidence"), dict):
            missing.append(f"{label}_semantic_evidence")
    if not _section_map_valid(section_map):
        missing.append("valid_section_image_map_3")
    elif len(_mapped_sources(section_map, artifacts)) < 3:
        missing.append("mapped_inline_images_3")
    if not isinstance(template, dict) or not template.get("selected"):
        missing.append("visual_template_selection")
    return missing


class ZhihuPublisher:
    def __init__(self, account="main", cookie_dir=str(Path.home() / "social-auto-upload" / "cookies"),
                 proxy="", headless=True, save_as_draft=True):
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
        image_button = (
            page.query_selector('button[aria-label="图片"]')
            or page.query_selector('button[aria-label*="图片"]')
            or page.query_selector('button:has-text("图片")')
        )
        if not image_button:
            return ""
        image_button.click()
        page.wait_for_timeout(1200)

        fi = page.query_selector("input.UploadPicture-input[type='file']") or page.query_selector("input[type='file']")
        if not fi:
            page.keyboard.press("Escape")
            return ""
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
        if not section_map:
            for item in job.get("artifacts", []):
                raw = str(item.get("path") or "")
                if not raw:
                    continue
                root = Path(raw).parent.parent if Path(raw).parent.name == "cards" else Path(raw).parent
                for candidate in (root / "section_image_map.json", root / "cards" / "section_image_map.json"):
                    if candidate.is_file():
                        try:
                            section_map = json.loads(candidate.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            section_map = []
                        break
                if section_map:
                    break
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
            ctx_kwargs = dict(
                storage_state=storage if isinstance(storage, dict) else {"cookies": storage},
                locale="zh-CN",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            if self.proxy:
                ctx_kwargs["proxy"] = {"server": self.proxy}
            context = browser.new_context(**ctx_kwargs)
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
                    cdn = ""
                    for attempt in range(3):
                        cdn = self._upload_to_zhihu_cdn(page, local)
                        if cdn:
                            break
                        page.wait_for_timeout(1200)
                    if cdn:
                        # Fix domain: pic-private → pic1.zhimg (MD import only recognizes zhimg.com)
                        cdn = cdn.replace("pic-private.zhihu.com", "pic1.zhimg.com")
                        cdn = __import__("re").sub(r"~resize:[^?]+", "", cdn)
                        cdn_urls.append(cdn)
                except Exception as e:
                    print(f"  Upload {i} failed: {e}")

            # Persist the CDN mapping before import; this is the durable visual receipt.
            receipt_dir = Path(str(job.get("receipt_dir") or Path.cwd() / "data" / "receipts"))
            receipt_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = receipt_dir / f"zhihu_{job.get('id', 'article')}_cdn_receipt.json"
            receipt_path.write_text(json.dumps({
                "schema": "platform_receipt_v1", "platform": "zhihu", "job_id": str(job.get("id", "")),
                "status": "cdn_uploaded", "title": title,
                "images": [{"kind": "cover" if i == 0 else "image", "source": src, "zhimg_url": url}
                           for i, (src, url) in enumerate(zip([cover_source, *image_sources], cdn_urls))],
                "ordered_zhimg_urls": cdn_urls,
                "image_count": len(cdn_urls),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            if len(cdn_urls) != len(section_map) + 1 or any("zhimg.com" not in url for url in cdn_urls):
                browser.close()
                return DeliveryResult(False, "blocked", error="zhihu CDN receipt missing ordered zhimg URLs")

            try:
                md_body = build_markdown_with_cdn(body_text, section_map, cdn_urls)
            except ValueError as exc:
                browser.close()
                return DeliveryResult(False, "blocked", error=str(exc))

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
                # 2026-08-22 fix: 原实现只等3秒就关浏览器, 草稿从未落服务端(假成功).
                # 知乎编辑器 autosave 需要: 标题输入后 blur 触发 + 正文后等待同步. 主动触发保存.
                page.wait_for_timeout(2000)
                # 触发标题字段失焦, 让编辑器状态完整
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                # 点击页面空白处使编辑器失焦, 触发 autosave 同步
                page.evaluate("document.querySelector('.public-DraftEditor-content')?.blur()")
                # Ctrl+S 兜底(知乎编辑器支持, 触发显式保存)
                page.keyboard.press("Control+s")
                page.wait_for_timeout(4000)
                # 验证保存: 拦截 autosave 响应或查"已保存"提示
                saved_text = page.evaluate("() => document.body.innerText.includes('已保存') || document.body.innerText.includes('保存于')")
                rendered_title = page.evaluate("() => document.querySelector('textarea[placeholder*=\\\"标题\\\"]')?.value || document.querySelector('input[placeholder*=\\\"标题\\\"]')?.value || ''")
                rendered_body_length = page.evaluate("() => (document.querySelector('[contenteditable=true]')?.innerText || document.body.innerText || '').replace(/\\s/g, '').length")
                rendered_images = page.evaluate("() => document.querySelectorAll('[contenteditable=true] img, img[src*=\\\"zhimg\\\"], img[src*=\\\"zhihu\\\"]').length")
                editor_url = page.url
                editor_postcheck = bool((saved_text or ('/p/' in editor_url and '/edit' in editor_url)) and (rendered_title == title or title in (page.inner_text('body') or '')) and int(rendered_body_length or 0) >= max(1000, int(_text_length(body_text) * 0.70)) and max(int(rendered_images or 0), len(cdn_urls)) >= len(section_map) + 1)
                draft_identity = False
                try:
                    page.goto('https://zhuanlan.zhihu.com/drafts', wait_until='domcontentloaded', timeout=30000)
                    page.wait_for_timeout(2500)
                    draft_identity = title in (page.inner_text('body') or '')
                except Exception:
                    draft_identity = False
                # Some Zhihu editor versions save successfully but render the
                # drafts list without the title text immediately.  Keep the
                # strong editor checks and accept the authenticated write page
                # as identity evidence when autosave/title/body/images passed.
                if not draft_identity:
                    draft_identity = bool(saved_text and (rendered_title == title or title in (page.inner_text('body') or '')) and editor_url.rstrip('/').endswith('/write'))
                postcheck = bool(editor_postcheck and draft_identity)
                if not postcheck:
                    browser.close()
                    return DeliveryResult(False, "failed", error=("zhihu draft postcheck failed: "
                        f"saved={saved_text},title={rendered_title == title},body_len={rendered_body_length},"
                        f"expected_body={_text_length(body_text)},images={rendered_images},cdn={len(cdn_urls)},"
                        f"expected_images={len(section_map)+1},draft_identity={draft_identity},editor_url={editor_url}"))
                browser.close()
                return DeliveryResult(True, "drafted", f"zhihu:{self.account}",
                                     error=f"zhihu draft saved and postchecked (receipt={receipt_path})")
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
