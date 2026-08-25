"""
MCP Server — Model Context Protocol interface for content_platform.
Exposes pipeline capabilities as MCP tools for external AI agents.
Provides stdio and SSE transports. Requires `mcp` package (pip install mcp).
"""
import json
import os
import sys
import asyncio
import inspect
import uuid
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


_CONTENT_PRODUCTION_MCP_TOOLS = frozenset(
    {
        "build_content_recipe",
        "content_search",
        "memory_context",
    }
)


def _get_db_path():
    configured_home = os.environ.get("CONTENT_PLATFORM_HOME")
    home = Path(configured_home) if configured_home else Path.home() / ".ai-self-media-tools"
    return str(home / "data" / "state.db")


def _load_config(db_path):
    configured_home = os.environ.get("CONTENT_PLATFORM_HOME")
    home = Path(configured_home) if configured_home else Path.home() / ".ai-self-media-tools"
    config_path = home / "config.json"
    if config_path.is_file():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {"data_dir": str(home / "data")}


def _pipeline():
    from content_platform.store import Store
    from content_platform.pipeline import Pipeline
    db = _get_db_path()
    store = Store(db)
    store.init()
    cfg = _load_config(db)
    return Pipeline(store, cfg), store


def _tools():
    runtime = {}

    def pipeline_and_store():
        if "pair" not in runtime:
            runtime["pair"] = _pipeline()
        return runtime["pair"]

    async def mcp_seo_geo_check(text: str = "") -> dict:
        from content_platform.seo import geo_check
        return geo_check(text)

    async def mcp_trends_query(limit: int = 10) -> dict:
        from content_platform.trends import TrendCollector, rank_trends
        tc = TrendCollector()
        items = tc.collect()
        ranked = rank_trends(items, limit=int(limit))
        return {"count": len(ranked), "trends": ranked}

    async def mcp_create_job(topic: str, platforms: str = "wechat", brief: str = "{}") -> dict:
        pipeline, _store = pipeline_and_store()
        plats = [p.strip() for p in platforms.split(",") if p.strip()]
        job = pipeline.create(topic, plats, json.loads(brief))
        return {"job_id": job["id"], "state": job["state"], "topic": topic}

    async def mcp_run_job(job_id: str) -> dict:
        pipeline, _store = pipeline_and_store()
        job = pipeline.run(job_id)
        return {"job_id": job_id, "state": job.get("state", "unknown")}

    async def mcp_approve_job(job_id: str, actor: str = "mcp-agent") -> dict:
        pipeline, _store = pipeline_and_store()
        job = pipeline.approve(job_id, actor)
        return {"job_id": job_id, "state": job.get("state", "unknown")}

    async def mcp_publish_job(job_id: str) -> dict:
        pipeline, _store = pipeline_and_store()
        job = pipeline.publish(job_id)
        return {"job_id": job_id, "state": job.get("state", "unknown"), "deliveries": job.get("deliveries", [])}

    async def mcp_review_status() -> dict:
        store2 = __import__("content_platform.store", fromlist=["Store"]).Store(_get_db_path())
        store2.init()
        pending = store2.list_jobs(limit=20, state="review_required")
        return {"pending_count": len(pending), "jobs": pending}

    async def mcp_reddit_channel_status() -> dict:
        from content_platform.admin_store import AdminStore
        from content_platform.platform_catalog import platform_definition
        from content_platform.readiness import inspect_delivery_readiness

        db_path = _get_db_path()
        config = _load_config(db_path)
        admin_store = AdminStore(db_path)
        admin_store.init()
        bindings = admin_store.list_bindings("reddit")
        readiness = inspect_delivery_readiness(config)
        trend_cfg = config.get("trends", {}).get("reddit", {})
        publisher_cfg = config.get("publishers", {}).get("platforms", {}).get("reddit", {})
        _pipeline_instance, store = pipeline_and_store()
        pending = [
            job
            for job in store.list_jobs(limit=50, state="review_required")
            if "reddit" in [str(platform).casefold() for platform in job.get("platforms", [])]
        ]
        return {
            "platform": platform_definition("reddit"),
            "configured": bool(trend_cfg or publisher_cfg or bindings),
            "trend_enabled": bool(trend_cfg.get("enabled", False)),
            "subreddits": trend_cfg.get("subreddits", []),
            "publisher_type": publisher_cfg.get("type", ""),
            "binding_count": len(bindings),
            "connected_count": sum(1 for item in bindings if item.get("status") == "connected"),
            "pending_review_count": len(pending),
            "pending_reviews": pending[:10],
            "readiness": readiness.get("publishers", {}).get("reddit", {}),
            "policy": "human_review_draft_only",
        }

    async def mcp_generate_audio(text: str, lang: str = "auto", genre: str = "auto") -> dict:
        output_dir = Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools")) / "data" / "mcp_audio"
        output_dir.mkdir(parents=True, exist_ok=True)
        from scripts.voice_engine import VoiceEngine
        engine = VoiceEngine(str(output_dir))
        result = engine.synthesize(text, lang=lang, genre=genre)
        return {"audio": result.get("audio", ""), "subtitle": result.get("subtitle", "")}

    async def mcp_capability_status() -> dict:
        from content_platform.capability_catalog import load_capability_registry
        from content_platform.runtime_capabilities import build_runtime_capability_snapshot

        snapshot = build_runtime_capability_snapshot()
        modules = snapshot["video_effect_modules"].get("modules") or {}
        families = snapshot["video_effect_modules"].get("template_families") or {}
        inventory = mcp_tool_inventory()
        registry_tools = [
            item["mcp_tool"]
            for item in load_capability_registry()["capabilities"]
            if item.get("kind") == "mcp_tool"
        ]
        return {
            "tools": snapshot["tools"],
            "video_effect_modules": {
                "version": snapshot["video_effect_modules"].get("version", ""),
                "module_count": len(modules or {}),
                "template_family_count": len(families or {}),
            },
            "mcp_tools": [item["name"] for item in inventory],
            "registry_mcp_tools": registry_tools,
            "non_registry_mcp_tools": [
                item["name"] for item in inventory if item["name"] not in registry_tools
            ],
        }

    async def mcp_build_tool_selection_plan(packet: str = "{}", platform: str = "") -> dict:
        from content_platform.tool_selection import build_tool_selection_evidence
        from content_platform.runtime_capabilities import build_runtime_capability_snapshot

        data = json.loads(packet or "{}")
        channel = platform or str(data.get("platform") or "")
        content_type = str(data.get("content_type") or data.get("content_form") or "article")
        snapshot = build_runtime_capability_snapshot()
        return build_tool_selection_evidence(
            platform=channel,
            content_type=content_type,
            content_goal=str(data.get("content_goal") or data.get("goal") or ""),
            capability_status={"tools": snapshot["tools"]},
            video_effect_registry=snapshot["video_effect_modules"],
            planned_manifest=data.get("tool_invocation_manifest") or {},
        )

    async def mcp_build_content_recipe(packet: str = "{}", platform: str = "") -> dict:
        from content_platform.content_recipe import build_article_recipe, build_image_text_card_recipe, build_knowledge_card_recipe

        data = json.loads(packet or "{}")
        channel = platform or str(data.get("platform") or "")
        cards = data.get("embedded_knowledge_cards") or data.get("knowledge_card_sequence") or []
        image_cards = data.get("cards") or data.get("image_cards") or cards
        result = {
            "platform": channel,
            "knowledge_card_recipe": build_knowledge_card_recipe(
                platform=channel,
                cards=cards,
                content_type=str(data.get("content_type") or data.get("content_form") or "knowledge_cards"),
            ),
            "image_text_card_recipe": build_image_text_card_recipe(
                platform=channel,
                content_type=str(data.get("content_type") or data.get("content_form") or "image_text_cards"),
                title=str(data.get("title") or ""),
                cards=image_cards,
                sections=data.get("sections") or [],
                content_goal=str(data.get("content_goal") or data.get("goal") or ""),
            ),
        }
        content_type = str(data.get("content_type") or data.get("content_form") or "")
        if content_type in {"long_article", "article", "checklist_article", "longform article"} or data.get("body"):
            result["article_recipe"] = build_article_recipe(
                platform=channel,
                content_type=content_type or "article",
                title=str(data.get("title") or ""),
                body=str(data.get("body") or ""),
                sections=data.get("sections") or [],
                section_image_map=data.get("section_image_map") or data.get("image_text_plan") or [],
                embedded_knowledge_cards=cards,
                visual_template_selection=data.get("visual_template_selection") or {},
            )
        return result

    async def mcp_content_search(query: str = "", documents: str = "[]") -> dict:
        from content_platform.adapters.search import execute
        rows = json.loads(documents or "[]")
        return execute({"query": query, "documents": rows if isinstance(rows, list) else []})

    async def mcp_memory_context(context: str = "{}") -> dict:
        payload = json.loads(context or "{}")
        return {"version": "memory_context_v1", "context": payload if isinstance(payload, dict) else {}}

    async def mcp_validate_content_package(packet: str = "{}", platform: str = "") -> dict:
        from content_platform.media_quality import (
            validate_article_packet,
            validate_platform_article_packet,
            validate_video_packet,
            validate_xiaohongshu_auto_packet,
        )

        data = json.loads(packet or "{}")
        channel = (platform or str(data.get("platform") or "")).casefold()
        content_type = str(data.get("content_type") or data.get("content_form") or "").casefold()
        if channel in {"xiaohongshu", "rednote"}:
            return validate_xiaohongshu_auto_packet(data)
        if "video" in content_type or data.get("video_plan") or data.get("audio_probe"):
            return validate_video_packet(data)
        if channel in {"toutiao", "juejin", "zhihu"}:
            return validate_platform_article_packet(data, channel)
        return validate_article_packet(data)

    async def mcp_zhihu_open_search(query: str = "", limit: int = 10, scope: str = "zhihu") -> dict:
        if not query:
            return {"count": 0, "items": [], "error": "query required"}
        from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

        try:
            items = ZhihuOpenAdapter().search(query, limit=limit, scope=scope)
            return {"count": len(items), "items": items}
        except Exception as exc:
            return {"count": 0, "items": [], "error": str(exc)[:200]}

    async def mcp_zhihu_open_ask(query: str = "", model: str = "fast") -> dict:
        if not query:
            return {"error": "query required"}
        from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

        try:
            return ZhihuOpenAdapter().ask(query, model=model)
        except Exception as exc:
            return {"error": str(exc)[:200]}

    async def mcp_zhihu_open_user(content_type: str = "all", limit: int = 20) -> dict:
        from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

        try:
            items = ZhihuOpenAdapter().user_contents(content_type=content_type, limit=limit)
            return {"count": len(items), "items": items}
        except Exception as exc:
            return {"count": 0, "items": [], "error": str(exc)[:200]}

    async def mcp_zhihu_open_user_followees(limit: int = 20) -> dict:
        from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

        try:
            items = ZhihuOpenAdapter().user_followees(limit=limit)
            return {"count": len(items), "items": items}
        except Exception as exc:
            return {"count": 0, "items": [], "error": str(exc)[:200]}

    async def mcp_zhihu_open_user_collections(limit: int = 20) -> dict:
        from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

        try:
            items = ZhihuOpenAdapter().user_collections(limit=limit)
            return {"count": len(items), "items": items}
        except Exception as exc:
            return {"count": 0, "items": [], "error": str(exc)[:200]}

    async def mcp_zhihu_open_trending(limit: int = 20) -> dict:
        from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

        try:
            items = ZhihuOpenAdapter().trending(limit=limit, retries=1, retry_delay=15)
            return {"count": len(items), "items": items}
        except Exception as exc:
            return {"count": 0, "items": [], "error": str(exc)[:200]}

    async def mcp_zhihu_open_quota() -> dict:
        from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

        try:
            return ZhihuOpenAdapter().quota()
        except Exception as exc:
            return {"error": str(exc)[:200]}

    return [
        (mcp_seo_geo_check, "seo_geo_check", "Run 7-dim GEO quality check on text", {"text": str}),
        (mcp_trends_query, "trends_query", "Get current trending topics", {"limit": int}),
        (mcp_zhihu_open_search, "zhihu_open_search", "Search Zhihu or web through Zhihu Open Platform", {"query": str, "limit": int, "scope": str}),
        (mcp_zhihu_open_ask, "zhihu_open_ask", "Ask Zhihu Zhida through Zhihu Open Platform", {"query": str, "model": str}),
        (mcp_zhihu_open_user, "zhihu_open_user_contents", "Fetch own Zhihu published contents through Zhihu Open Platform", {"content_type": str, "limit": int}),
        (mcp_zhihu_open_user_followees, "zhihu_open_user_followees", "Fetch own Zhihu followees through Zhihu Open Platform", {"limit": int}),
        (mcp_zhihu_open_user_collections, "zhihu_open_user_collections", "Fetch own Zhihu collections through Zhihu Open Platform", {"limit": int}),
        (mcp_zhihu_open_trending, "zhihu_open_trending", "Fetch Zhihu hot list through Zhihu Open Platform", {"limit": int}),
        (mcp_zhihu_open_quota, "zhihu_open_quota", "Show Zhihu Open Platform quota usage", {}),
        (mcp_create_job, "create_job", "Create a new content generation job", {"topic": str, "platforms": str, "brief": str}),
        (mcp_run_job, "run_job", "Run content generation for a job", {"job_id": str}),
        (mcp_approve_job, "approve_job", "Approve a job for publishing", {"job_id": str, "actor": str}),
        (mcp_publish_job, "publish_job", "Publish a job to configured platforms", {"job_id": str}),
        (mcp_review_status, "review_status", "Get current review queue status", {}),
        (mcp_reddit_channel_status, "reddit_channel_status", "Get Reddit trend, draft, binding, and review status", {}),
        (mcp_generate_audio, "generate_audio", "Generate audio narration", {"text": str, "lang": str, "genre": str}),
        (mcp_capability_status, "capability_status", "Report available tools, skills bridge, and video effect registry", {}),
        (mcp_build_tool_selection_plan, "build_tool_selection_plan", "Build tool capability analysis and selected tool stack evidence for a packet", {"packet": str, "platform": str}),
        (mcp_build_content_recipe, "build_content_recipe", "Build article and knowledge-card recipe evidence for a packet", {"packet": str, "platform": str}),
        (mcp_content_search, "content_search", "Search bounded content-production context", {"query": str, "documents": str}),
        (mcp_memory_context, "memory_context", "Retrieve bounded workflow memory context", {"context": str}),
        (mcp_validate_content_package, "validate_content_package", "Validate article, video, Xiaohongshu, or platform article package gates", {"packet": str, "platform": str}),
    ]


def mcp_tool_inventory() -> list[dict[str, str]]:
    """Return the registered MCP names and their registry eligibility."""
    return [
        {
            "name": name,
            "registry_scope": "content_production" if name in _CONTENT_PRODUCTION_MCP_TOOLS else "endpoint_only",
        }
        for _handler, name, _description, _params in _tools()
    ]


def invoke_registered_tool(tool_name: str, payload: dict | None = None) -> dict:
    """Invoke the exact handler registered by the checked-in MCP server."""
    handlers = {name: handler for handler, name, _description, _params in _tools()}
    if tool_name not in handlers:
        raise KeyError(f"MCP tool is not registered: {tool_name}")
    handler = handlers[tool_name]
    signature = inspect.signature(handler)
    values = dict(payload or {})
    kwargs = {name: values[name] for name in signature.parameters if name in values}
    result = asyncio.run(handler(**kwargs))
    return {
        "_mcp_transport": "in_process_registered_mcp",
        "_mcp_session_id": uuid.uuid4().hex,
        "_mcp_server": "content-platform",
        "result": result,
    }


def serve_stdio():
    if not HAS_MCP:
        print("MCP not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)
    mcp = FastMCP("content-platform")
    for handler, name, desc, params in _tools():
        mcp.tool(name, description=desc)(handler)
    mcp.run(transport="stdio")


def serve_sse(host="127.0.0.1", port=9600):
    if not HAS_MCP:
        print("MCP not installed. Run: pip install mcp", file=sys.stderr)
        sys.exit(1)
    mcp = FastMCP("content-platform")
    for handler, name, desc, params in _tools():
        mcp.tool(name, description=desc)(handler)
    mcp.run(transport="sse", host=host, port=port)


def main():
    import argparse
    p = argparse.ArgumentParser(description="content-platform MCP server")
    p.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9600)
    args = p.parse_args()
    if args.transport == "sse":
        serve_sse(args.host, args.port)
    else:
        serve_stdio()


if __name__ == "__main__":
    main()
