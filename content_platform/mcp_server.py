"""
MCP Server — Model Context Protocol interface for content_platform.
Exposes pipeline capabilities as MCP tools for external AI agents.
Provides stdio and SSE transports. Requires `mcp` package (pip install mcp).
"""
import json
import os
import sys
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def _get_db_path():
    home = Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools"))
    return str(home / "data" / "state.db")


def _load_config(db_path):
    home = Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools"))
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
    pipeline, store = _pipeline()

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
        plats = [p.strip() for p in platforms.split(",") if p.strip()]
        job = pipeline.create(topic, plats, json.loads(brief))
        return {"job_id": job["id"], "state": job["state"], "topic": topic}

    async def mcp_run_job(job_id: str) -> dict:
        job = pipeline.run(job_id)
        return {"job_id": job_id, "state": job.get("state", "unknown")}

    async def mcp_approve_job(job_id: str, actor: str = "mcp-agent") -> dict:
        job = pipeline.approve(job_id, actor)
        return {"job_id": job_id, "state": job.get("state", "unknown")}

    async def mcp_publish_job(job_id: str) -> dict:
        job = pipeline.publish(job_id)
        return {"job_id": job_id, "state": job.get("state", "unknown"), "deliveries": job.get("deliveries", [])}

    async def mcp_review_status() -> dict:
        store2 = __import__("content_platform.store", fromlist=["Store"]).Store(_get_db_path())
        store2.init()
        pending = store2.list_jobs(limit=20, state="review_required")
        return {"pending_count": len(pending), "jobs": pending}

    async def mcp_generate_audio(text: str, lang: str = "auto", genre: str = "auto") -> dict:
        output_dir = Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools")) / "data" / "mcp_audio"
        output_dir.mkdir(parents=True, exist_ok=True)
        from scripts.voice_engine import VoiceEngine
        engine = VoiceEngine(str(output_dir))
        result = engine.synthesize(text, lang=lang, genre=genre)
        return {"audio": result.get("audio", ""), "subtitle": result.get("subtitle", "")}

    return [
        (mcp_seo_geo_check, "seo_geo_check", "Run 7-dim GEO quality check on text", {"text": str}),
        (mcp_trends_query, "trends_query", "Get current trending topics", {"limit": int}),
        (mcp_create_job, "create_job", "Create a new content generation job", {"topic": str, "platforms": str, "brief": str}),
        (mcp_run_job, "run_job", "Run content generation for a job", {"job_id": str}),
        (mcp_approve_job, "approve_job", "Approve a job for publishing", {"job_id": str, "actor": str}),
        (mcp_publish_job, "publish_job", "Publish a job to configured platforms", {"job_id": str}),
        (mcp_review_status, "review_status", "Get current review queue status", {}),
        (mcp_generate_audio, "generate_audio", "Generate audio narration", {"text": str, "lang": str, "genre": str}),
    ]


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
