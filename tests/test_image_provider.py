import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import content_platform.image_provider as image_provider
from content_platform.image_provider import ImageProviderError, _stock_result_index, generate_image, load_secret


def test_load_secret_reads_named_env_file_without_exposing_value(tmp_path, monkeypatch):
    env_file = tmp_path / "provider.env"
    env_file.write_text("OPENAI_API_KEY=secret-value\nOTHER=ignored\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert load_secret("OPENAI_API_KEY", [env_file]) == "secret-value"


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


def test_stock_candidate_index_changes_with_recovery_prompt():
    indexes = {_stock_result_index(f"same query quality recovery attempt {index}", 15) for index in range(1, 8)}

    assert len(indexes) >= 3


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


def test_auto_uses_stock_before_free_generation_when_stock_key_exists(tmp_path, monkeypatch):
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
        result = generate_image("AI automation cover", tmp_path / "out.jpg", provider="auto")

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


def test_auto_falls_back_to_pollinations_when_paid_providers_unavailable(tmp_path, monkeypatch):
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

    assert result["provider"] == "pollinations"
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

    assert result["provider"] == "pollinations"
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
        assert payload["width"] == 768
        assert payload["height"] == 1024
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


def test_auto_routes_photographic_prompts_to_stock_before_ai_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.delenv("IMAGE_PROVIDER_CHAIN", raising=False)
    output = tmp_path / "photo.jpg"
    ai_calls = []

    def fake_stock(prompt, output_path, **kwargs):
        Path(output_path).write_bytes(b"\xff\xd8" + b"s" * 3000)
        return {"provider": "pexels", "mode": "search", "license": "Pexels", "source_url": "https://pexels.test/photo"}

    monkeypatch.setattr(image_provider, "_stock_image", fake_stock)

    def fake_ai_provider(name):
        def provider(*args, **kwargs):
            ai_calls.append(name)
            raise ImageProviderError(f"{name} should not be selected")

        return provider

    monkeypatch.setattr(image_provider, "_pixazo_image", fake_ai_provider("pixazo"), raising=False)
    monkeypatch.setattr(image_provider, "_sensenova_image", fake_ai_provider("sensenova"), raising=False)

    result = generate_image(
        "real office photo for an AI workflow article cover, natural lighting",
        output,
        provider="auto",
        size="1200x800",
    )

    assert result["provider"] == "pexels"
    assert ai_calls == []
    assert result["provenance"]["route"] == "content_aware_auto"
    assert result["provenance"]["selected_for"] == "real_scene"


def test_auto_no_text_prompt_does_not_trigger_edit_without_input_image(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("IMAGE_PROVIDER_CHAIN", "sensenova,pixazo")
    output = tmp_path / "cover.png"

    def fake_pixazo(prompt, output_path, **kwargs):
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"p" * 3000)
        return {"provider": "pixazo", "mode": "generate", "model": "pixazo-image-v1"}

    def fake_sensenova(prompt, output_path, **kwargs):
        from PIL import Image
        Image.new("RGB", (1024, 1024), (20, 40, 60)).save(output_path)
        return {"provider": "sense_nova", "mode": "generate", "model": "sensenova-u1.5-lite"}

    monkeypatch.setattr(image_provider, "_pixazo_image", fake_pixazo, raising=False)
    monkeypatch.setattr(image_provider, "_sensenova_image", fake_sensenova, raising=False)

    result = generate_image("minimal product illustration, no text", output, provider="auto", size="1024x1024")

    assert result["provider"] == "sense_nova"
    assert result["mode"] == "generate"
    assert result.get("edited") is not True
    assert result["provenance"]["input_image_sha256"] == ""


def test_auto_routes_real_input_image_to_sensenova_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("IMAGE_PROVIDER_CHAIN", "pixazo,sense_nova,stock")
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nsource-real-image")
    output = tmp_path / "edited.png"
    generation_calls = []

    def fake_sensenova(prompt, output_path, **kwargs):
        assert Path(kwargs["input_image"]).read_bytes() == source.read_bytes()
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"e" * 3000)
        return {"provider": "sensenova", "mode": "edit", "model": "sensenova-image-edit"}

    monkeypatch.setattr(image_provider, "_sensenova_image", fake_sensenova, raising=False)

    def fake_pixazo(*args, **kwargs):
        generation_calls.append("pixazo")
        raise ImageProviderError("Pixazo cannot edit")

    monkeypatch.setattr(image_provider, "_pixazo_image", fake_pixazo, raising=False)

    result = generate_image("make the uploaded image warmer but keep its composition", output, provider="auto", input_image=source)

    assert result["provider"] == "sense_nova"
    assert result["mode"] == "edit"
    assert generation_calls == []
    assert result["provenance"]["input_image_sha256"]
    assert result["provenance"]["route"] == "content_aware_auto"


def test_stock_original_is_preserved_and_temp_edit_atomically_replaces_output(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("IMAGE_PROVIDER_CHAIN", "stock,sense_nova")
    output = tmp_path / "final.png"
    calls = []
    stock_color = (16, 32, 48)
    edited_color = (200, 120, 40)

    def fake_stock(prompt, output_path, **kwargs):
        calls.append(("stock", Path(output_path).name))
        from PIL import Image

        Image.new("RGB", (512, 512), stock_color).save(output_path)
        return {"provider": "pexels", "mode": "search", "license": "Pexels", "source_url": "https://pexels.test/photo"}

    def fake_sensenova(prompt, output_path, **kwargs):
        assert Path(output_path) != output
        calls.append(("edit", Path(output_path).name))
        from PIL import Image

        Image.new("RGB", (512, 512), edited_color).save(output_path, format="PNG")
        return {"provider": "sensenova", "mode": "edit", "model": "sensenova-image-edit"}

    monkeypatch.setattr(image_provider, "_stock_image", fake_stock)
    monkeypatch.setattr(image_provider, "_sensenova_image", fake_sensenova, raising=False)

    result = generate_image("editorial cover, remove watermark-like text", output, provider="auto")

    from PIL import Image

    assert Image.open(output).getpixel((0, 0)) == edited_color
    original_copy = Path(result["provenance"]["original_path"])
    assert original_copy.is_file()
    assert Image.open(original_copy).getpixel((0, 0)) == stock_color
    assert calls[0] == ("stock", "final.png")
    assert calls[1][0] == "edit"
    assert result["provider"] == "sense_nova"
    assert result["provenance"]["original_provider"] == "pexels"


def test_edit_failure_keeps_stock_output_and_reports_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("IMAGE_PROVIDER_CHAIN", "stock,sense_nova")
    output = tmp_path / "fallback.png"

    def fake_stock(prompt, output_path, **kwargs):
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"s" * 3000)
        return {"provider": "pixabay", "mode": "search", "license": "Pixabay", "source_url": "https://pixabay.test/photo"}

    def failing_sensenova(*args, **kwargs):
        raise ImageProviderError("edit provider unavailable")

    monkeypatch.setattr(image_provider, "_stock_image", fake_stock)
    monkeypatch.setattr(image_provider, "_sensenova_image", failing_sensenova, raising=False)

    result = generate_image("editorial cover, remove watermark-like text", output, provider="auto")

    assert result["provider"] == "pixabay"
    assert result["mode"] == "search"
    assert result["edit_status"] == "fallback_kept_stock"
    assert result["edit_error_provider"] == "sense_nova"
    assert output.read_bytes().endswith(b"s" * 3000)


def test_sensenova_edit_sends_source_image_and_aspect_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("SN_API_KEY", "sense-key")
    monkeypatch.delenv("SENSENOVA_API_KEY", raising=False)
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nsource-real-image")
    output = tmp_path / "edited.png"
    from PIL import Image
    import io
    buffer = io.BytesIO()
    Image.new("RGB", (768, 1024), (20, 40, 60)).save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.headers["Authorization"] == "Bearer sense-key"
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["size"] == "1664x2496"
        assert base64.b64decode(payload["image"]) == source.read_bytes()
        return Response()

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=fake_urlopen):
        result = generate_image(
            "preserve the original subject and adjust lighting",
            output,
            provider="sensenova",
            model="sensemirage-edit-test",
            size="768x1024",
            input_image=source,
        )

    assert result["provider"] == "sense_nova"
    assert result["mode"] == "edit"
    assert result["model"] == "sensemirage-edit-test"
    assert result["provenance"]["input_image_sha256"]


def test_pixazo_generation_sends_requested_dimensions_and_records_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("PIXAZO_API_KEY", "pixazo-key")
    output = tmp_path / "generated.png"
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"p" * 3000

    class ApiResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"imageUrl": "https://cdn.pixazo.test/generated.png"}).encode("utf-8")

    class Headers:
        def get(self, name, default=None):
            return "image/png" if name == "Content-Type" else default

    class ImageResponse:
        headers = Headers()
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return image_bytes

    def fake_urlopen(request, timeout):
        if "gateway.pixazo.ai" in request.full_url:
            assert request.headers["Ocp-apim-subscription-key"] == "pixazo-key"
            payload = json.loads(request.data.decode("utf-8"))
            assert payload["prompt"]
            assert payload["width"] == 1536
            assert payload["height"] == 864
            return ApiResponse()
        return ImageResponse()

    with patch("content_platform.image_provider.urllib.request.urlopen", side_effect=fake_urlopen):
        result = generate_image(
            "cinematic editorial illustration for AI workflow",
            output,
            provider="pixazo",
            model="pixazo-image-test",
            size="1536x864",
        )

    assert result["provider"] == "pixazo"
    assert result["mode"] == "generate"
    assert result["size"] == "1536x864"
    assert result["provenance"]["provider"] == "pixazo"
    assert result["provenance"]["prompt_sha256"] == image_provider.hashlib.sha256(
        "cinematic editorial illustration for AI workflow".encode("utf-8")
    ).hexdigest()
def test_agnes_generation_uses_ratio_and_base64_output(tmp_path, monkeypatch):
    output = tmp_path / "agnes.png"
    monkeypatch.setenv("AGNES_API_KEY", "agnes-test")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            payload = __import__("base64").b64encode(b"image-bytes").decode()
            return __import__("json").dumps({"data": [{"b64_json": payload}]}).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = __import__("json").loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("content_platform.image_provider.urllib.request.urlopen", fake_urlopen)
    result = generate_image("cinematic dashboard", output, provider="agnes", size="1080x1920")

    assert output.read_bytes() == b"image-bytes"
    assert captured["body"]["model"] == "agnes-image-2.1-flash"
    assert captured["body"]["size"] == "1K"
    assert captured["body"]["ratio"] == "9:16"
    assert captured["body"]["return_base64"] is True
    assert result["provider"] == "agnes"


def test_agnes_edit_sends_reference_image_in_extra_body(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    source.write_bytes(b"source-image")
    output = tmp_path / "edited.png"
    monkeypatch.setenv("AGNES_API_KEY", "agnes-test")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            payload = __import__("base64").b64encode(b"edited-image").decode()
            return __import__("json").dumps({"data": [{"b64_json": payload}]}).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = __import__("json").loads(request.data)
        return Response()

    monkeypatch.setattr("content_platform.image_provider.urllib.request.urlopen", fake_urlopen)
    result = generate_image("preserve composition", output, provider="agnes", input_image=source, size="1024x1024")

    references = captured["body"]["extra_body"]["image"]
    assert references[0].startswith("data:image/png;base64,")
    assert result["mode"] == "edit"
