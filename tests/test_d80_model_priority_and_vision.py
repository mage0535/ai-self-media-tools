import io
import json
import random
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from content_platform import asset_semantic_review as review
from content_platform import image_provider as ip
from content_platform.media import MediaBridge


def test_semantic_retry_escalates_stock_to_cloudflare_to_openai_codex(tmp_path):
    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j-esc", "title": "AI 团队自动化流程", "body": "正文", "platforms": ["xiaohongshu"]}
    chains = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            chain = (env or {}).get("IMAGE_PROVIDER_CHAIN", "")
            chains.append(chain)
            first = chain.split(",")[0]
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            rng = random.Random(len(chains) + 100)
            Image.frombytes("L", (64, 64), bytes(rng.randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "pexels" if first == "stock" else first}

    scores = iter([0.55, 0.68, 0.86])
    recorded = {}
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch.object(MediaBridge, "_image_prompts", return_value=[{"role": "cover", "prompt": "cover"}]), \
            patch.object(MediaBridge, "_required_image_count", return_value=1), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: {"score": next(scores)}), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"})

    assert chains == [
        "stock,cloudflare,openai-codex",
        "cloudflare,openai-codex",
        "openai-codex",
    ]
    assert recorded["images"][0]["provider_result"]["provider"] == "openai-codex"
    assert recorded["images"][0]["semantic_review"]["score"] == 0.86


def test_gateway_text_prefers_cloudflare_workers_ai_for_prompt_rewrites(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-test")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token-test")
    monkeypatch.delenv("IMAGE_PROMPT_REWRITE_PROVIDER", raising=False)
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open(req, timeout=0, attempts=1):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return Resp(json.dumps({"choices": [{"message": {"content": "clean isometric workflow diagram"}}]}).encode("utf-8"))

    with patch.object(ip, "_urlopen_retry", side_effect=fake_open):
        out = ip._gateway_text("rewrite this", "@cf/mistralai/mistral-small-3.1-24b-instruct", 120)

    assert out == "clean isometric workflow diagram"
    assert seen["url"] == "https://api.cloudflare.com/client/v4/accounts/acct-test/ai/v1/chat/completions"
    assert seen["auth"] == "Bearer cf-token-test"
    assert seen["body"]["model"] == "@cf/mistralai/mistral-small-3.1-24b-instruct"


def test_route_config_sets_openai_codex_billing_provider_and_keeps_cloudflare_fallback(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({
            "generator": {
                "hermes_command": "/srv/hermes-agent/.venv/bin/hermes",
                "hermes_provider": "openai-codex",
                "hermes_model": "gpt-6.2-sol",
                "vision_provider": "openai-codex",
                "vision_model": "gpt-6.2-sol",
                "vision_fallback_provider": "media-vision-fallback",
                "vision_fallback_model": "@cf/mistralai/mistral-small-3.1-24b-instruct",
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(cfg))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-role"))

    _, _, route = review.route_config()
    assert route["hermes_provider"] == "openai-codex"
    assert route["hermes_model"] == "gpt-6.2-sol"
    assert route["billing_provider"] == "openai-codex"
    assert route["fallback"]["hermes_provider"] == "media-vision-fallback"
    assert route["fallback"]["hermes_model"] == "@cf/mistralai/mistral-small-3.1-24b-instruct"
    assert route["fallback"]["billing_provider"] == "custom"
