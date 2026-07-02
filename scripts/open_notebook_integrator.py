#!/usr/bin/env python3
"""
Open Notebook 素材消化模块 — 将 Open Notebook 的深度研究能力集成到内容管线。
基于 lfnovo/open-notebook (33.7k⭐) REST API。

用法:
  # CLI: 消化单个 URL
  python3 -m scripts.open_notebook_integrator digest --url https://example.com/article

  # CLI: 消化文本内容
  python3 -m scripts.open_notebook_integrator digest --text "来源内容..."

  # CLI: 多素材主题研究
  python3 -m scripts.open_notebook_integrator research --topic "AI Agents" --urls url1 url2

  # Python: 编程调用
  from scripts.open_notebook_integrator import digest_source, research_topic
  result = digest_source("https://example.com/article")
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests

# ── 配置 ─────────────────────────────────────────────
OPEN_NOTEBOOK_API = os.environ.get("OPEN_NOTEBOOK_API", "http://<open-notebook-host>")
OPEN_NOTEBOOK_PASSWORD = os.environ.get("OPEN_NOTEBOOK_PASSWORD", "")
DEFAULT_TIMEOUT = 60


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[ONI] {ts} {msg}", flush=True)


# ── API 客户端 ────────────────────────────────────────


class OpenNotebookClient:
    """Open Notebook REST API 客户端"""

    def __init__(self, base_url: str = OPEN_NOTEBOOK_API, password: str = OPEN_NOTEBOOK_PASSWORD):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "HermesOpenNotebookIntegrator/1.0",
        })
        if password:
            self.session.headers["Authorization"] = f"Bearer {password}"

    def _json(self, method: str, path: str, data: dict = None) -> dict:
        """发送 JSON body 请求"""
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(method, url, json=data, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            if not resp.text.strip():
                return {}
            return resp.json()
        except requests.RequestException as e:
            raise RuntimeError(f"{method} {path}: {e}")

    def _multipart(self, path: str, fields: dict) -> dict:
        """发送 multipart/form-data POST 请求"""
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.post(url, data=fields, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            if not resp.text.strip():
                return {}
            return resp.json()
        except requests.RequestException as e:
            raise RuntimeError(f"POST {path}: {e}")

    def health(self) -> dict:
        """检查 Open Notebook 服务健康状态"""
        return self._json("GET", "/health")

    def create_notebook(self, name: str, description: str = "") -> dict:
        """创建一个新的 Notebook"""
        return self._json("POST", "/api/notebooks", {"name": name, "description": description})

    def add_source(self, notebook_id: str, source_type: str, content: str, title: str = "") -> dict:
        """添加素材来源到 Notebook（multipart/form-data）

        Args:
            notebook_id: Notebook ID
            source_type: "link" (URL) 或 "text" (文本)
            content: URL 或文本内容
            title: 可选标题
        """
        fields = {
            "type": source_type,
            "notebook_id": notebook_id,
            "async_processing": "false",
        }
        if source_type == "link":
            fields["url"] = content
        elif source_type == "text":
            fields["content"] = content
        if title:
            fields["title"] = title
        return self._multipart("/api/sources", fields)

    def search(self, query: str, notebook_id: str = None, limit: int = 10) -> dict:
        """搜索 Notebook 内容"""
        payload = {"query": query, "limit": limit}
        if notebook_id:
            payload["notebook_id"] = notebook_id
        return self._json("POST", "/api/search", payload)

    def ask(self, question: str, notebook_id: str = None, models: dict = None) -> dict:
        """提问（搜索+综合回答）

        Args:
            question: 问题文本
            notebook_id: Notebook ID (可选)
            models: 模型配置字典 {strategy_model, answer_model, final_answer_model}
        """
        payload = {"question": question}
        if models:
            payload.update(models)
        if notebook_id:
            payload["notebook_id"] = notebook_id
        return self._json("POST", "/api/search/ask", payload)

    def get_defaults(self) -> list:
        """获取可用的模型列表"""
        return self._json("GET", "/api/models")

    def list_notebooks(self) -> list:
        """列出所有 Notebook"""
        return self._json("GET", "/api/notebooks")

    def list_notes(self, notebook_id: str = None, limit: int = 20) -> dict:
        """获取 Notebook 中的笔记"""
        params = f"?limit={limit}"
        if notebook_id:
            params += f"&notebook_id={notebook_id}"
        return self._json("GET", f"/api/notes{params}")


# ── 素材消化引擎 ─────────────────────────────────────


def digest_source(
    url: str = None,
    text: str = None,
    title: str = "",
    topic: str = "untitled",
    api_url: str = OPEN_NOTEBOOK_API,
    password: str = OPEN_NOTEBOOK_PASSWORD,
) -> dict:
    """素材消化入口：接收 URL 或文本 → Open Notebook 分析 → 返回结构化摘要

    Args:
        url: 待分析的 URL（网页/文章/视频等）
        text: 待分析的文本内容
        title: 可选标题
        topic: 主题标签
        api_url: Open Notebook API 地址
        password: Open Notebook 密码

    Returns:
        dict: {notes, insights, notebook_id, source_id, summary}
    """
    client = OpenNotebookClient(api_url, password)

    # 1. 检查服务可用
    try:
        health = client.health()
        if health.get("status") != "healthy":
            return {"error": f"Open Notebook not healthy: {health}"}
    except Exception as e:
        return {"error": f"Open Notebook unreachable: {e}"}

    # 2. 创建 Notebook
    notebook_name = title or f"digest_{topic}_{int(time.time())}"
    try:
        nb = client.create_notebook(notebook_name, f"Auto-digested: {topic}")
        notebook_id = nb.get("id") or nb.get("notebook_id") or ""
        if not notebook_id:
            return {"error": f"Failed to create notebook: {nb}"}
        log(f"Created notebook: {notebook_id}")
    except Exception as e:
        return {"error": f"Failed to create notebook: {e}"}

    # 3. 添加素材
    source_type = "link" if url else "text"
    try:
        src = client.add_source(notebook_id, source_type, url or text, title)
        source_id = src.get("id") or src.get("source_id") or ""
        log(f"Added {source_type} source: {source_id}")
    except Exception as e:
        return {"error": f"Failed to add source: {e}"}

    # 4. 等待处理
    time.sleep(2)

    # 5. 提问获取摘要
    qa = {}
    questions = [
        "Summarize this content in 3-5 key points",
        "What are the main arguments or findings?",
        "What is the target audience and purpose?",
    ]
    for question in questions:
        try:
            answer = client.ask(question, notebook_id=notebook_id)
            qa[question[:30].strip()] = answer
        except Exception as e:
            qa[question[:30].strip()] = {"error": str(e)}

    # 6. 搜索分析
    search_result = {}
    try:
        search_result = client.search(f"key insights from {title or topic}", notebook_id=notebook_id)
    except Exception as e:
        search_result = {"error": str(e)}

    # 7. 获取笔记
    notes = []
    try:
        notes_resp = client.list_notes(notebook_id=notebook_id)
        notes = notes_resp if isinstance(notes_resp, list) else notes_resp.get("items", [])
    except Exception:
        pass

    result = {
        "notebook_id": notebook_id,
        "source_id": source_id,
        "notebook_name": notebook_name,
        "topic": topic,
        "source_type": source_type,
        "source_url": url or "",
        "notes": notes[:10],
        "qa": qa,
        "search": search_result,
        "digested_at": datetime.now().isoformat(),
    }
    log(f"Digest complete: {len(notes)} notes, {len(qa)} QA pairs")
    return result


def research_topic(
    topic: str,
    urls: list = None,
    texts: list = None,
    api_url: str = OPEN_NOTEBOOK_API,
    password: str = OPEN_NOTEBOOK_PASSWORD,
) -> dict:
    """研究一个主题（多素材联合分析）

    创建单个 Notebook，添加多个来源，然后综合提问。
    """
    client = OpenNotebookClient(api_url, password)

    try:
        nb = client.create_notebook(f"research_{topic}", f"Multi-source research: {topic}")
        notebook_id = nb.get("id") or nb.get("notebook_id") or ""
    except Exception as e:
        return {"error": f"Failed to create research notebook: {e}"}

    sources = []
    for url in (urls or []):
        try:
            src = client.add_source(notebook_id, "link", url)
            sources.append(src)
        except Exception as e:
            sources.append({"url": url, "error": str(e)})

    for text in (texts or []):
        try:
            src = client.add_source(notebook_id, "text", text)
            sources.append(src)
        except Exception as e:
            sources.append({"text_preview": text[:50], "error": str(e)})

    time.sleep(3)

    qa = {}
    for question in [
        f"What are the key trends and patterns about {topic}?",
        f"Summarize all sources about {topic} in 5 bullet points",
        f"What actionable insights can be derived about {topic}?",
    ]:
        try:
            answer = client.ask(question, notebook_id=notebook_id)
            qa[question[:40].strip()] = answer
        except Exception:
            pass

    return {
        "notebook_id": notebook_id,
        "topic": topic,
        "sources_added": len(sources),
        "qa_pairs": len(qa),
        "insights": qa,
        "researched_at": datetime.now().isoformat(),
    }


# ── CLI ───────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Open Notebook 素材消化工具")
    sub = parser.add_subparsers(dest="command")

    digest_p = sub.add_parser("digest", help="消化单个素材来源")
    digest_p.add_argument("--url", help="待分析的 URL")
    digest_p.add_argument("--text", help="待分析的文本内容")
    digest_p.add_argument("--title", default="", help="可选标题")
    digest_p.add_argument("--topic", default="general", help="主题标签")

    research_p = sub.add_parser("research", help="多素材主题研究")
    research_p.add_argument("--topic", required=True, help="研究主题")
    research_p.add_argument("--urls", nargs="*", default=[], help="相关 URL 列表")
    research_p.add_argument("--texts", nargs="*", default=[], help="相关文本列表")

    sub.add_parser("health", help="检查 Open Notebook 服务状态")

    args = parser.parse_args()

    if args.command == "digest":
        if not args.url and not args.text:
            print("❌ 需要 --url 或 --text")
            sys.exit(1)
        result = digest_source(url=args.url, text=args.text, title=args.title, topic=args.topic)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "research":
        result = research_topic(topic=args.topic, urls=args.urls, texts=args.texts)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "health":
        try:
            client = OpenNotebookClient()
            h = client.health()
            print(f"✅ Open Notebook: {h.get('status', 'unknown')}")
            print(f"   API: {OPEN_NOTEBOOK_API}")
        except Exception as e:
            print(f"❌ Open Notebook unreachable: {e}")
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
