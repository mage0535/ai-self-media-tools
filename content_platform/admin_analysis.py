import json
import os
import subprocess
import urllib.request


def _setting(config, name):
    if os.environ.get(name):
        return os.environ[name]
    env_file = str(config.get("env_file", "")).strip()
    if env_file and os.path.isfile(env_file):
        for line in open(env_file, encoding="utf-8").read().splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("'\"")
    return ""


def _fallback_summary(payload):
    bindings = payload.get("bindings", [])
    latest = payload.get("latest_works", [])
    tracks = [item.get("track", "") for item in bindings if item.get("track")]
    current_states = [item.get("current_status", "") for item in bindings if item.get("current_status")]
    total_views = sum(int(item.get("performance", {}).get("views", 0)) for item in latest)
    total_engagement = sum(int(item.get("engagement", 0)) for item in latest)
    recommendations = []
    if total_views <= 0:
        recommendations.append("先补全真实账号绑定和历史表现回写，再提高自动判断质量。")
    if payload.get("stats", {}).get("delivery_counts", {}).get("drafted", 0):
        recommendations.append("保持 draft-first，先验证赛道和平台适配，再逐步开启 live 发布。")
    if tracks:
        recommendations.append(f"当前账号主要赛道：{' / '.join(sorted(set(tracks))[:3])}。建议保持聚焦。")
    if current_states:
        recommendations.append(f"当前账号现状关键词：{' / '.join(sorted(set(current_states))[:4])}。")
    if not recommendations:
        recommendations.append("继续积累更多真实内容与表现数据，让 ranking 调优更稳定。")
    return {
        "summary": (
            f"当前平台共 {len(bindings)} 个绑定账号，最近 5 条内容累计浏览 {total_views}，"
            f"累计互动 {total_engagement}。建议结合赛道聚焦与历史反馈继续优化发布策略。"
        ),
        "recommendations": recommendations,
        "provider": "fallback",
    }


def platform_llm_analysis(config, payload):
    provider = str(config.get("provider", "")).strip()
    api_key = _setting(config, config.get("api_key_env", "OPENAI_API_KEY"))
    if provider == "hermes-cli":
        try:
            prompt = (
                "Return JSON with keys summary and recommendations. "
                "Analyze platform account state, track focus, recent content performance, and next actions.\n"
                + json.dumps(payload, ensure_ascii=False)
            )
            proc = subprocess.run(
                [config.get("hermes_command", "hermes"), "-z", prompt, "--cli"],
                capture_output=True,
                text=True,
                timeout=int(config.get("timeout", 20)),
                check=False,
            )
            if proc.returncode == 0:
                content = proc.stdout.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                result = json.loads(content)
                result["provider"] = "hermes-cli"
                return result
        except Exception:
            pass
    if api_key:
        try:
            request = urllib.request.Request(
                (config.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/") + "/chat/completions",
                data=json.dumps(
                    {
                        "model": config.get("model") or os.environ.get("CONTENT_PLATFORM_MODEL", "gpt-4.1-mini"),
                        "messages": [
                            {
                                "role": "user",
                                "content": "Return JSON with keys summary and recommendations. Analyze this platform data:\n"
                                + json.dumps(payload, ensure_ascii=False),
                            }
                        ],
                        "temperature": 0.2,
                    }
                ).encode(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=int(config.get("timeout", 15))) as response:
                result = json.loads(response.read())
            content = result["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(content)
            parsed["provider"] = "openai-compatible"
            return parsed
        except Exception:
            pass
    return _fallback_summary(payload)
