#!/usr/bin/env python3
"""
今日头条文章上传器 — Playwright + cookie 自动化发布

使用方式：
  python toutiao_uploader.py --file article.md --title "标题" --tags tag1,tag2

环境变量：
  CN_PROXY — 国内代理地址（默认 socks5://127.0.0.1:1080）
  TOUTIAO_COOKIE — cookie 文件路径
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# 尝试多种 playwright 导入路径
try:
    from playwright.async_api import async_playwright
except ImportError:
    # 可能在 social-auto-upload venv 里
    sys.path.insert(0, str(Path.home() / "social-auto-upload"))
    from playwright.async_api import async_playwright

CN_PROXY = os.environ.get("CN_PROXY", "socks5://127.0.0.1:1080")
COOKIE_PATH = os.environ.get("TOUTIAO_COOKIE", "")
HEADLESS = os.environ.get("HEADLESS", "1") == "1"

# 头条号编辑页 URL（按优先级尝试）
EDITOR_URLS = [
    "https://mp.toutiao.com/profile_v4/form/article",
    "https://mp.toutiao.com/profile_v4/graphic/article",
    "https://mp.toutiao.com/profile_v4/graphic",
]


async def cookie_auth(cookie_path: str) -> bool:
    """验证 cookie 是否有效"""
    if not cookie_path or not Path(cookie_path).exists():
        print("❌ Cookie 文件不存在")
        return False
    async with async_playwright() as p:
        proxy = {"server": CN_PROXY} if CN_PROXY else None
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            storage_state=cookie_path,
            proxy=proxy,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = await context.new_page()
        await page.goto("https://mp.toutiao.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        # 检测是否已登录：登录页有「登录」按钮，首页有用户头像/昵称
        login_btn = page.locator('.web-login-button, .login-btn, a:has-text("登录")')
        user_indicator = page.locator('.user-avatar, .user-name, [class*="avatar"], [class*="user"]')
        if await login_btn.count() > 0 and await login_btn.first.is_visible():
            # 也可能登录后仍有登录元素，再查是否有用户指示
            if await user_indicator.count() == 0:
                print("❌ Cookie 已失效，需要重新登录")
                await browser.close()
                return False
        print("✅ Cookie 有效")
        await browser.close()
        return True


async def cookie_gen(cookie_path: str):
    """交互式登录获取 cookie"""
    if not cookie_path:
        cookie_path = str(Path.home() / ".hermes" / "cookies" / "toutiao.json")
    print(f"🔑 打开浏览器进行头条号登录，cookie 将保存到: {cookie_path}")
    async with async_playwright() as p:
        proxy = {"server": CN_PROXY} if CN_PROXY else None
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            proxy=proxy,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = await context.new_page()
        await page.goto("https://mp.toutiao.com", wait_until="domcontentloaded", timeout=30000)
        print("请扫码/账号登录头条号...登录完成后按 Enter 继续")
        input()
        # 保存 cookie
        Path(cookie_path).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=cookie_path)
        print(f"✅ Cookie 已保存到 {cookie_path}")
        await browser.close()


def parse_markdown(file_path: str) -> tuple[str, str]:
    """解析 Markdown 文件，返回 (title, html_content)"""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    title = ""
    content = text

    # 提取 YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        title_m = re.search(r"^title:\s*(.+)$", fm, re.MULTILINE)
        if title_m:
            title = title_m.group(1).strip().strip('"\'')
        content = text[fm_match.end():]

    # 如果没有 frontmatter title，从第一个 # 标题提取
    if not title:
        h1 = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if h1:
            title = h1.group(1).strip()
            content = content[h1.end():].strip()

    # 简单的 Markdown → 基础 HTML 转换（头条编辑器接受纯文本/Markdown）
    # 头条编辑器通常支持 Markdown 粘贴，所以保留原始格式
    return title, content


async def upload_article(
    file_path: str,
    title: str = "",
    tags: list[str] = None,
    cookie_path: str = "",
    save_as_draft: bool = True,
) -> dict:
    """上传文章到头条号"""
    tags = tags or []
    if not cookie_path:
        cookie_path = COOKIE_PATH
    if not cookie_path:
        cookie_path = str(Path.home() / ".hermes" / "cookies" / "toutiao.json")

    # 解析内容
    md_title, md_content = parse_markdown(file_path)
    final_title = title or md_title or Path(file_path).stem
    print(f"📄 标题: {final_title}")
    print(f"📝 正文: {len(md_content)} chars")

    # 验证 cookie
    if not await cookie_auth(cookie_path):
        return {"success": False, "error": "Cookie 失效"}

    async with async_playwright() as p:
        proxy = {"server": CN_PROXY} if CN_PROXY else None
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            storage_state=cookie_path,
            proxy=proxy,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = await context.new_page()

        # 尝试进入编辑页
        editor_url = None
        for url in EDITOR_URLS:
            print(f"  → 尝试编辑页: {url}")
            try:
                resp = await page.goto(url, wait_until="load", timeout=30000)
                await page.wait_for_timeout(3000)
                if resp and resp.status < 400:
                    editor_url = url
                    break
            except Exception as e:
                print(f"    ⚠ {e}")
                continue

        if not editor_url:
            # fallback: 从首页导航
            print("  → 编辑页直接访问失败，尝试首页导航")
            await page.goto("https://mp.toutiao.com/profile_v4/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            # 找「写文章」按钮
            write_btn = page.locator(
                'a:has-text("写文章"), button:has-text("写文章"), '
                'a:has-text("创作"), [class*="write"], [class*="create"]'
            )
            if await write_btn.count() > 0:
                await write_btn.first.click()
                await page.wait_for_timeout(5000)
            else:
                # 打印页面信息帮助调试
                print(f"  ⚠ 当前 URL: {page.url}")
                page_title = await page.title()
                print(f"  ⚠ 页面标题: {page_title}")
                buttons = await page.evaluate('''() =>
                    Array.from(document.querySelectorAll('a, button')).slice(0,20).map(e => ({
                        t: e.textContent?.trim()?.slice(0,40),
                        h: e.href || '',
                        c: e.className?.slice(0,50)
                    }))
                ''')
                for b in buttons:
                    if any(k in (b['t'] + b['c']).lower() for k in ['文章', '创作', '写', 'editor', 'publish']):
                        print(f"    [{b['t']}] href={b['h'][:60]}")

        await page.wait_for_timeout(2000)
        print(f"📍 当前 URL: {page.url}")

        # --- 填写标题 ---
        try:
            # 头条编辑器常见标题选择器
            title_selectors = [
                'input[placeholder*="标题"]',
                '.article-title input',
                '[class*="title"] input',
                'input:not([type="hidden"])',
                '#title',
            ]
            title_el = None
            for sel in title_selectors:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    title_el = el
                    break

            if title_el:
                await title_el.click(force=True, timeout=5000)
                await page.wait_for_timeout(300)
                await title_el.fill(final_title[:100])
                print(f"✅ 标题已填写: {final_title[:50]}")
            else:
                print("⚠ 未找到标题输入框")
        except Exception as e:
            print(f"⚠ 标题填写异常: {e}")

        # --- 填写正文 ---
        try:
            # 头条编辑器通常是 contenteditable div 或 iframe
            body_selectors = [
                '[contenteditable="true"]',
                '.article-content',
                '[class*="editor"] [contenteditable]',
                'iframe',
                'textarea',
            ]
            body_el = None
            is_iframe = False
            for sel in body_selectors:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    if sel == 'iframe':
                        is_iframe = True
                        # 通过 iframe 内的 body 填写
                        try:
                            frame = page.frame_locator(sel).first
                            body = frame.locator('body')
                            if await body.count() > 0:
                                body_el = body
                                break
                        except:
                            continue
                    else:
                        body_el = el
                        break

            if body_el:
                await body_el.click(force=True, timeout=5000)
                await page.wait_for_timeout(500)
                # 头条编辑器通常支持直接粘贴 Markdown
                # 先清空
                await body_el.fill("")
                await page.wait_for_timeout(300)
                # 填入内容（限制长度 50000）
                content_truncated = md_content[:50000]
                if len(md_content) > 50000:
                    print(f"⚠ 正文超过5万字，已截断到5万字")
                await body_el.fill(content_truncated)
                print(f"✅ 正文已填写 {len(content_truncated)} chars")
            else:
                print("⚠ 未找到编辑器区域")
        except Exception as e:
            print(f"⚠ 正文填写异常: {e}")

        # --- 添加标签 ---
        if tags:
            try:
                tag_selectors = [
                    'input[placeholder*="标签"]',
                    'input[placeholder*="话题"]',
                    '[class*="tag"] input',
                ]
                tag_el = None
                for sel in tag_selectors:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible():
                        tag_el = el
                        break

                if tag_el:
                    for t in tags[:5]:
                        await tag_el.fill(t)
                        await page.wait_for_timeout(500)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(300)
                    print(f"✅ 标签已添加: {', '.join(tags[:5])}")
            except Exception as e:
                print(f"⚠ 标签填写异常: {e}")
        else:
            print("  无标签")

        # --- 保存/发布 ---
        result = {"success": False, "url": "", "action": ""}

        if save_as_draft:
            # 先找「存草稿」按钮
            draft_btn_selectors = [
                'button:has-text("存草稿")',
                'button:has-text("保存草稿")',
                'span:has-text("存草稿")',
                'button:has-text("草稿")',
                '[class*="draft"]',
            ]
            clicked = False
            for sel in draft_btn_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(force=True, timeout=10000)
                        await page.wait_for_timeout(3000)
                        result["action"] = "draft"
                        clicked = True
                        print("✅ 已存为草稿")
                        break
                except:
                    continue

            if not clicked:
                # 检查是否已保存（自动保存）
                print("ℹ️ 未找到存草稿按钮，可能已自动保存")
                result["action"] = "auto_save"
                result["success"] = True

        # 获取当前 URL 作为参考
        result["url"] = page.url
        result["editor_url"] = editor_url or page.url

        # 更新 cookie
        await context.storage_state(path=cookie_path)

        await browser.close()
        return result


async def main():
    parser = argparse.ArgumentParser(description="今日头条文章发布器")
    parser.add_argument("--file", "-f", help="文章文件 (.md)")
    parser.add_argument("--title", "-t", default="", help="文章标题")
    parser.add_argument("--tags", default="", help="标签（逗号分隔）")
    parser.add_argument("--cookie", help="Cookie 文件路径")
    parser.add_argument("--login", action="store_true", help="交互式登录获取 cookie")
    parser.add_argument("--check", action="store_true", help="检查 cookie 状态")
    parser.add_argument("--publish", action="store_true", help="直接发布（默认存草稿）")
    parser.add_argument("--headless", action="store_true", help="无头模式")

    args = parser.parse_args()

    global HEADLESS
    if args.headless:
        HEADLESS = True

    if args.login:
        await cookie_gen(args.cookie or "")
        return

    if args.check:
        cookie = args.cookie or COOKIE_PATH or str(Path.home() / ".hermes" / "cookies" / "toutiao.json")
        ok = await cookie_auth(cookie)
        sys.exit(0 if ok else 1)

    if not args.file:
        parser.print_help()
        return

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    result = await upload_article(
        file_path=args.file,
        title=args.title,
        tags=tags,
        cookie_path=args.cookie or "",
        save_as_draft=not args.publish,
    )

    print(f"\n{'='*40}")
    if result["success"] or result["action"]:
        print(f"✅ 操作完成")
        print(f"📎 编辑页: {result.get('editor_url', '')}")
        print(f"📌 当前页: {result.get('url', '')}")
        print(f"📋 操作: {result.get('action', 'done')}")
    else:
        print(f"❌ 失败: {result.get('error', '未知错误')}")


if __name__ == "__main__":
    asyncio.run(main())
