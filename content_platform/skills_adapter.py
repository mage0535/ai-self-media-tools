"""
skills_adapter.py — 桥接项目三 (Hermes Skills + AutoCLI) 到项目一的 CLI。

提供：
  - fetch_hot_data()   → 调用 AutoCLI 采集实时数据
  - generate_content() → 调用 content_gen_fusion.py 生成内容
  - get_status()       → 探测哪些增强能力可用

用法:
    from .skills_adapter import fetch_hot_data, generate_content

集成到项目一 CLI:
    python -m content_platform gen-content --topic "AI" --type article
    python -m content_platform hot-data --source bilibili --limit 5
    python -m content_platform skill-status
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _hermes_home():
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


FUSION_SCRIPT = _hermes_home() / "scripts" / "content_gen_fusion.py"
OUTPUT_DIR = _hermes_home() / "pipeline" / "content_queue"


def _check_autocli():
    """Check if autocli binary + daemon are available."""
    ok = bool(subprocess.run(
        ["which", "autocli"], capture_output=True, text=True
    ).returncode == 0)
    daemon = False
    if ok:
        try:
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "http://127.0.0.1:19925/health"],
                capture_output=True, text=True, timeout=3
            )
            daemon = r.stdout.strip() == "200"
        except Exception:
            pass
    return {"available": ok, "daemon_running": daemon}


def _check_follow_builders():
    path = _hermes_home() / "skills" / "follow-builders"
    ok = path.is_dir() and (path / "SKILL.md").exists()
    return {"available": ok, "builder_count": 26, "kind": "ai_news_digest"}


def _check_aliens_eye():
    path = _hermes_home() / "skills" / "aliens-eye"
    ok = path.is_dir() and (path / "README.md").exists()
    return {"available": ok, "platform_count": 840, "kind": "osint_username_scan"}


def _check_skills():
    """Check which Hermes skill sets are available."""
    skills_base = _hermes_home() / "skills"
    checks = {}
    for name in ["khazix-skills", "kangarooking-skills",
                  "canghe-skills", "huashu-skills"]:
        path = skills_base / name
        count = 0
        if path.is_dir():
            count = len(list(path.rglob("SKILL.md")))
        checks[name.replace("-skills", "")] = {
            "available": count > 0, "skill_count": count
        }
    return checks


def _check_chrome_ext():
    """Check if AutoCLI Chrome extension is active."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        s.connect(("127.0.0.1", 9223))
        s.close()
        return True
    except (socket.timeout, ConnectionRefusedError):
        return False


def get_status():
    """Return dict of all available enhancements."""
    autocli = _check_autocli()
    skills = _check_skills()
    return {
        "autocli": autocli,
        "chrome_ext": _check_chrome_ext(),
        "fusion_script": FUSION_SCRIPT.exists(),
        "follow_builders": _check_follow_builders(),
        "aliens_eye": _check_aliens_eye(),
        "skills": skills,
        "total_skills": sum(s["skill_count"] for s in skills.values()),
    }


def fetch_hot_data(source="bilibili", limit=5):
    """
    Fetch real-time hot data via AutoCLI.

    Args:
        source: "bilibili", "douban", "hackernews"
        limit: max items

    Returns:
        list of dicts, or None on failure
    """
    autocli = _check_autocli()
    if not autocli["available"]:
        return {"error": "autocli binary not found"}
    if not autocli["daemon_running"]:
        return {"error": "autocli daemon not running (needed for browser-based sources)"}

    command_map = {
        "bilibili": f"autocli bilibili hot --limit {limit} --format json",
        "douban": f"autocli douban movie-hot --limit {limit} --format json",
        "hackernews": f"autocli hackernews top --limit {limit} --format json",
    }

    cmd = command_map.get(source)
    if not cmd:
        return {"error": f"unknown source: {source}"}

    env = os.environ.copy()
    env["AUTOCLI_API_KEY"] = env.get("AUTOCLI_API_KEY", "")

    try:
        r = subprocess.run(
            cmd.split(),
            capture_output=True, text=True, timeout=30, env=env
        )
        if r.returncode != 0:
            return {"error": f"autocli exit code {r.returncode}: {r.stderr[:200]}"}
        if not r.stdout.strip():
            return {"error": "autocli returned empty"}

        data = json.loads(r.stdout)
        items = data if isinstance(data, list) else data.get("data", [])
        return {
            "source": source,
            "count": len(items),
            "items": items,
            "fetched_at": datetime.now().isoformat(),
        }
    except json.JSONDecodeError:
        return {"error": "autocli returned non-JSON output"}
    except subprocess.TimeoutExpired:
        return {"error": "autocli timed out"}
    except FileNotFoundError:
        return {"error": "autocli command not found"}


def generate_content(topic, content_type="article", save_to_pipeline=False):
    """
    Generate content using Hermes skills bridge (content_gen_fusion.py).

    Args:
        topic: content topic
        content_type: article|video-script|social-post|newsletter|image-series|topic-research
        save_to_pipeline: if True, save task to pipeline queue

    Returns:
        dict with status and generated task info
    """
    if not FUSION_SCRIPT.exists():
        return {"error": f"fusion script not found at {FUSION_SCRIPT}"}

    env = os.environ.copy()
    env["AUTOCLI_API_KEY"] = env.get("AUTOCLI_API_KEY", "")
    env["PYTHONUNBUFFERED"] = "1"

    try:
        r = subprocess.run(
            [sys.executable, str(FUSION_SCRIPT),
             "--topic", topic,
             "--type", content_type],
            capture_output=True, text=True, timeout=120, env=env
        )
        if r.returncode != 0:
            return {"error": f"fusion script failed: {r.stderr[:300]}"}

        return {
            "status": "ok",
            "topic": topic,
            "content_type": content_type,
            "output": r.stdout,
            "generated_at": datetime.now().isoformat(),
        }
    except subprocess.TimeoutExpired:
        return {"error": "fusion script timed out (120s)"}
