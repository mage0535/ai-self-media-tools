import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from content_platform.image_provider import (
    ImageProviderError,
    _provider_chain,
    _stock_query,
    generate_image,
    load_secret,
)


def test_load_secret_reads_named_env_file_without_exposing_value(tmp_path, monkeypatch):
    env_file = tmp_path / "provider.env"
    env_file.write_text("OPENAI_API_KEY=secret-value\nOTHER=ignored\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert load_secret("OPENAI_API_KEY", [env_file]) == "secret-value"


def test_stock_query_prioritizes_pet_cover_semantics_over_generic_ai_terms():
    query = _stock_query(
        "猫咪治愈日记，真实猫咪在阳光草地上放松，电影海报封面，竖屏构图，无文字无水印"
    )
    assert "cat" in query.casefold()
    assert "artificial intelligence" not in query.casefold()


def test_generate_image_fails_closed_when_provider_has_no_key(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ImageProviderError, match="OPENAI_API_KEY"):
        generate_image("simple prompt", tmp_path / "out.png", provider="openai")


def test_openai_generation_writes_base64_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    image_bytes = b"\x89PNG\r\n\x1a\nfake"

    class Data:
        b64_json = base64.b64encode(image_bytes).decode("ascii")
        url = None

    class Images:
        def generate(self, **kwargs):
            assert kwargs["model"] == "gpt-image-test"
            return type("Response", (), {"data": [Data()]})()

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.images = Images()

    with patch("openai.OpenAI", FakeOpenAI):
        result = generate_image("draw a concise diagram", tmp_path / "out.png", provider="openai", model="gpt-image-test")

    assert result["provider"] == "openai"
    assert Path(result["path"]).read_bytes() == image_bytes


def test_gemini_generation_writes_interactions_image(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    image_bytes = b"\x89PNG\r\n\x1a\nfake"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"output_image": {"data": base64.b64encode(image_bytes).decode("ascii")}}).encode()

    def fake_urlopen(request, timeout):
        assert request.headers["X-goog-api-key"] == "test-key"
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "gemini-test-image"
        return Response()

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=fake_urlopen):
        result = generate_image("draw a clean cover", tmp_path / "out.png", provider="gemini", model="gemini-test-image")

    assert result["provider"] == "gemini"
    assert Path(result["path"]).read_bytes() == image_bytes


def test_go_gemini_chat_completions_supports_generation_and_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("GO_GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GO_GEMINI_API_BASE_URL", "http://go.test/v1")
    monkeypatch.setenv("GO_GEMINI_USE_SYSTEM_PROXY", "1")
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    image_bytes = b"\xff\xd8" + b"x" * 3000
    source = tmp_path / "source.jpg"
    source.write_bytes(image_bytes)

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return self.body

    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "images": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
                                },
                            }
                        ],
                    }
                }
            ]
        }
    ).encode()
    requests = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode())
        requests.append(payload)
        assert request.full_url == "http://go.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert payload["model"] == "gemini-3.1-flash-image"
        assert payload["modalities"] == ["text", "image"]
        return Response(response_body)

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=fake_urlopen):
        generated = generate_image("draw a blue circle", tmp_path / "generated.jpg", provider="go_gemini")
        edited = generate_image("add a red dot", tmp_path / "edited.jpg", provider="go_gemini", input_image=source)

    assert generated["provider"] == "go_gemini"
    assert generated["mode"] == "generate"
    assert edited["provider"] == "go_gemini"
    assert edited["mode"] == "edit"
    assert Path(edited["path"]).read_bytes() == image_bytes
    assert isinstance(requests[1]["messages"][0]["content"], list)
    assert requests[1]["messages"][0]["content"][0]["type"] == "image_url"


def test_go_gemini_reads_markdown_data_url_from_content():
    from content_platform.image_provider import _extract_go_gemini_image

    image_bytes = b"\xff\xd8" + b"x" * 3000
    body = {"choices": [{"message": {"content": "![image](data:image/jpeg;base64," + base64.b64encode(image_bytes).decode() + ")"}}]}

    assert _extract_go_gemini_image(body) == image_bytes


def test_sensenova_key_falls_back_to_hermes_provider_key_env(tmp_path, monkeypatch):
    from content_platform.image_provider import _hermes_provider_secret

    (tmp_path / "config.yaml").write_text("custom_providers:\n  - name: sensenova\n    key_env: SN_TEST_KEY\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SN_TEST_KEY", "sn-value")

    assert _hermes_provider_secret("sensenova") == "sn-value"
    assert _hermes_provider_secret("missing") == ""


def test_auto_provider_chain_assigns_generation_and_edit_tasks(monkeypatch):
    monkeypatch.delenv("IMAGE_PROVIDER_CHAIN", raising=False)
    monkeypatch.delenv("IMAGE_PROVIDER_ALLOW_PAID", raising=False)
    monkeypatch.delenv("IMAGE_PROVIDER_QUALITY_FIRST", raising=False)
    assert _provider_chain("auto") == ["go_gemini", "sense_nova", "cloudflare", "pollinations", "stock"]
    assert _provider_chain("auto", input_image="/tmp/source.jpg") == ["go_gemini", "sense_nova"]

    monkeypatch.setenv("IMAGE_PROVIDER_QUALITY_FIRST", "1")
    assert _provider_chain("auto") == ["go_gemini", "sense_nova", "cloudflare", "pollinations", "stock"]
    monkeypatch.setenv("IMAGE_PROVIDER_ALLOW_PAID", "1")
    assert _provider_chain("auto") == ["openai", "go_gemini", "sense_nova", "cloudflare", "pollinations"]
    assert _provider_chain("auto", input_image="/tmp/source.jpg") == ["openai", "go_gemini", "sense_nova", "gemini"]
    assert _provider_chain("go") == ["go_gemini"]


def test_pollinations_generation_writes_downloaded_image(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 3000

    class Headers:
        def get(self, name, default=None):
            return "image/png" if name == "Content-Type" else default

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    with patch("content_platform.image_provider.urllib.request.urlopen", return_value=Response()) as urlopen:
        result = generate_image("draw a useful editorial cover", tmp_path / "out.png", provider="pollinations")

    assert result["provider"] == "pollinations"
    assert result["model"] == "flux"
    assert Path(result["path"]).read_bytes() == image_bytes
    assert "model=flux" in urlopen.call_args.args[0].full_url


def test_pollinations_rejects_image_editing(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")

    with pytest.raises(ImageProviderError, match="does not support image editing"):
        generate_image("edit this", tmp_path / "out.png", provider="pollinations", input_image=source)


def test_pexels_search_downloads_stock_image(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-key")
    image_bytes = b"\xff\xd8" + b"x" * 3000

    class JsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(
                {
                    "photos": [
                        {
                            "url": "https://www.pexels.com/photo/example",
                            "photographer": "Example Photographer",
                            "src": {"large2x": "https://images.pexels.com/photos/example.jpeg"},
                        }
                    ]
                }
            ).encode("utf-8")

    class Headers:
        def get(self, name, default=None):
            return "image/jpeg" if name == "Content-Type" else default

    class ImageResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    def fake_urlopen(request, timeout):
        if "api.pexels.com" in request.full_url:
            assert request.headers["Authorization"] == "pexels-key"
            assert "query=artificial+intelligence+workspace" in request.full_url
            return JsonResponse()
        return ImageResponse()

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=fake_urlopen):
        result = generate_image("AI tools article cover", tmp_path / "out.jpg", provider="pexels")

    assert result["provider"] == "pexels"
    assert result["mode"] == "search"
    assert result["license"] == "Pexels"
    assert Path(result["path"]).read_bytes() == image_bytes


def test_pixabay_search_downloads_stock_image(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-key")
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 3000

    class JsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(
                {
                    "hits": [
                        {
                            "pageURL": "https://pixabay.com/photos/example",
                            "user": "Example User",
                            "largeImageURL": "https://cdn.pixabay.com/photo/example.png",
                        }
                    ]
                }
            ).encode("utf-8")

    class Headers:
        def get(self, name, default=None):
            return "image/png" if name == "Content-Type" else default

    class ImageResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    def fake_urlopen(request, timeout):
        if "pixabay.com/api" in request.full_url:
            assert "key=pixabay-key" in request.full_url
            assert "q=technology+workspace" in request.full_url
            return JsonResponse()
        return ImageResponse()

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=fake_urlopen):
        result = generate_image("工具效率文章配图", tmp_path / "out.png", provider="pixabay")

    assert result["provider"] == "pixabay"
    assert result["mode"] == "search"
    assert result["license"] == "Pixabay"
    assert Path(result["path"]).read_bytes() == image_bytes


def test_explicit_stock_provider_uses_stock_when_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-key")
    image_bytes = b"\xff\xd8" + b"x" * 3000

    class JsonResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"photos": [{"src": {"large": "https://images.pexels.com/photo.jpeg"}}]}).encode("utf-8")

    class Headers:
        def get(self, name, default=None):
            return "image/jpeg" if name == "Content-Type" else default

    class ImageResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=[JsonResponse(), ImageResponse()]):
        result = generate_image("AI automation cover", tmp_path / "out.jpg", provider="stock")

    assert result["provider"] == "pexels"
    assert Path(result["path"]).read_bytes() == image_bytes


def test_legacy_pexels_search_wrapper_uses_unified_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-key")
    from scripts import pexels_image_search

    def fake_generate_image(prompt, output, provider, size):
        assert provider == "pexels"
        Path(output).write_bytes(b"\xff\xd8" + b"x" * 3000)
        return {"source_url": "https://www.pexels.com/photo/example", "photographer": "Example", "license": "Pexels"}

    with patch("scripts.pexels_image_search.generate_image", side_effect=fake_generate_image):
        results = pexels_image_search.search_images("AI workspace", count=2)

    assert results == [
        {
            "url": "https://www.pexels.com/photo/example",
            "original_url": "https://www.pexels.com/photo/example",
            "alt": "AI workspace",
            "photographer": "Example",
            "width": 800,
            "height": 400,
            "license": "Pexels",
        }
    ]


def test_auto_falls_back_to_configured_free_model_when_paid_providers_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    image_bytes = b"\xff\xd8" + b"x" * 3000

    class Headers:
        def get(self, name, default=None):
            return "image/jpeg" if name == "Content-Type" else default

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    with patch("content_platform.image_provider.urllib.request.urlopen", return_value=Response()):
        result = generate_image("fallback image", tmp_path / "out.jpg", provider="auto")

    assert result["provider"] == "cloudflare"
    assert Path(result["path"]).read_bytes() == image_bytes


def test_auto_does_not_try_paid_providers_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("OPENAI_API_KEY", "paid-key")
    monkeypatch.setenv("GEMINI_API_KEY", "paid-key")
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 3000

    class Headers:
        def get(self, name, default=None):
            return "image/png" if name == "Content-Type" else default

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    with patch("content_platform.image_provider.urllib.request.urlopen", return_value=Response()), patch(
        "content_platform.image_provider._openai_image"
    ) as openai_image, patch("content_platform.image_provider._gemini_image") as gemini_image:
        result = generate_image("free image only", tmp_path / "out.png", provider="auto")

    assert result["provider"] == "cloudflare"
    openai_image.assert_not_called()
    gemini_image.assert_not_called()


def test_cloudflare_generation_writes_direct_image_response(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("CF_WORKER_URL", "https://example.worker.dev/image")
    monkeypatch.setenv("CF_WORKER_KEY", "worker-key")
    # A live account token has higher provider priority than the worker key.
    # Remove it so this test stays a local mocked worker contract.
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_IMAGE_WORKER_URL", raising=False)
    image_bytes = b"\xff\xd8" + b"x" * 3000

    class Headers:
        def get(self, name, default=None):
            return "image/jpeg" if name == "Content-Type" else default

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://example.worker.dev/image"
        assert request.headers["Authorization"] == "Bearer worker-key"
        payload = json.loads(request.data.decode("utf-8"))
        # 10-31 hotfix: Workers AI flux-1-schnell takes prompt + steps only and rejects width/height.
        assert set(payload) == {"prompt", "steps"}
        return Response()

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=fake_urlopen):
        result = generate_image("vertical tech cover", tmp_path / "out.jpg", provider="cloudflare", size="768x1024")

    assert result["provider"] == "cloudflare"
    assert Path(result["path"]).read_bytes() == image_bytes


def test_image_provider_cache_reuses_previous_success(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 3000

    class Headers:
        def get(self, name, default=None):
            return "image/png" if name == "Content-Type" else default

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return image_bytes

    with patch("content_platform.image_provider.urllib.request.urlopen", return_value=Response()) as urlopen:
        first = generate_image("cached visual", tmp_path / "one.png", provider="pollinations")
        second = generate_image("cached visual", tmp_path / "two.png", provider="pollinations")

    assert first["provider"] == "pollinations"
    assert second["cache_hit"] is True
    assert Path(second["path"]).read_bytes() == image_bytes
    assert urlopen.call_count == 1


def test_flux_providers_get_a_short_english_scene_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from content_platform import image_provider
    image_provider._SCENE_PROMPTS.clear()
    long_prompt = "Create a section illustration using these article facts: " + "考勤异常自动提醒" * 400
    seen = []

    def fake_cloudflare(prompt, output, model="", size="1024x1024", input_image=None):
        seen.append(prompt)
        output.write_bytes(b"\x89PNG" + b"x" * 3000)
        return {"provider": "cloudflare", "model": "flux", "mode": "generate"}

    with patch("content_platform.image_provider._gateway_scene_prompt", return_value="An HR clerk reviews attendance alerts.") as rewrite, \
            patch("content_platform.image_provider._cloudflare_image", side_effect=fake_cloudflare):
        result = generate_image(long_prompt, tmp_path / "out.png", provider="cloudflare")

    assert seen == ["An HR clerk reviews attendance alerts."]
    assert rewrite.call_args.args[0] == long_prompt
    assert result["prompt_rewrite"]["mode"] == "model_rewrite"


def test_flux_prompt_without_rewrite_keeps_english_instructions_first(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from content_platform import image_provider
    image_provider._SCENE_PROMPTS.clear()
    prompt = "Section facts: " + "销售新人" * 600 + " Professional editorial illustration, no logo or watermark."
    seen = []

    def fake_pollinations(prompt, output, model="", size="1024x1024", input_image=None):
        seen.append(prompt)
        output.write_bytes(b"\x89PNG" + b"x" * 3000)
        return {"provider": "pollinations", "model": "flux", "mode": "generate"}

    with patch("content_platform.image_provider._gateway_scene_prompt", side_effect=ImageProviderError("down")), \
            patch("content_platform.image_provider._pollinations_image", side_effect=fake_pollinations):
        result = generate_image(prompt, tmp_path / "out.png", provider="pollinations")

    assert seen[0].startswith("Section facts: Professional editorial illustration, no logo or watermark.")
    assert len(seen[0]) <= 1001
    assert result["prompt_rewrite"]["mode"] == "compacted"
