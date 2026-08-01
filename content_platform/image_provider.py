"""Unified image generation and editing providers."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable


class ImageProviderError(RuntimeError):
    """Raised when an image provider cannot produce a usable artifact."""


def load_secret(name: str, extra_files: Iterable[str | Path] = ()) -> str:
    """Read a secret from environment or known private env files.

    Values are never logged by this module. The lookup intentionally stays
    read-only and only supports simple KEY=value env files.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value

    content_home = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    candidates = [
        *[Path(p) for p in extra_files if p],
        content_home / "secrets" / "provider.env",
        content_home / "secrets" / "image.env",
        content_home / "secrets" / "channel_matrix.env",
        hermes_home / ".env",
        hermes_home / "secrets" / "provider.env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if not line.startswith(f"{name}="):
                continue
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def generate_image(
    prompt: str,
    output: str | Path,
    provider: str = "auto",
    model: str = "",
    size: str = "1024x1024",
    quality: str = "low",
    input_image: str | Path | None = None,
) -> dict:
    """Generate or edit an image and return a structured artifact record."""
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ImageProviderError("image prompt is empty")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    providers = ["openai", "gemini", "stock", "pollinations"] if provider == "auto" else [provider]
    errors: list[str] = []
    for name in providers:
        try:
            if name == "openai":
                result = _openai_image(prompt, output_path, model=model, size=size, quality=quality, input_image=input_image)
            elif name == "gemini":
                result = _gemini_image(prompt, output_path, model=model, size=size, input_image=input_image)
            elif name == "stock":
                result = _stock_image(prompt, output_path, size=size, input_image=input_image)
            elif name == "pexels":
                result = _pexels_image(prompt, output_path, size=size, input_image=input_image)
            elif name == "pixabay":
                result = _pixabay_image(prompt, output_path, size=size, input_image=input_image)
            elif name == "pollinations":
                result = _pollinations_image(prompt, output_path, model=model, size=size, input_image=input_image)
            else:
                raise ImageProviderError(f"unsupported image provider: {name}")
            result["path"] = str(output_path)
            result["bytes"] = output_path.stat().st_size
            return result
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:180]}")
            if provider != "auto":
                break
    raise ImageProviderError("all image providers failed; " + " | ".join(errors))


def _openai_image(
    prompt: str,
    output: Path,
    model: str = "",
    size: str = "1024x1024",
    quality: str = "low",
    input_image: str | Path | None = None,
) -> dict:
    key = load_secret("OPENAI_API_KEY")
    if not key:
        raise ImageProviderError("OPENAI_API_KEY is not configured")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImageProviderError("openai package is not installed") from exc

    client = OpenAI(api_key=key)
    models = [m.strip() for m in (model or os.environ.get("OPENAI_IMAGE_MODEL") or "gpt-image-2,gpt-image-1").split(",") if m.strip()]
    last_error: Exception | None = None
    for model_name in models:
        try:
            if input_image:
                with Path(input_image).open("rb") as image_file:
                    response = client.images.edit(
                        model=model_name,
                        image=image_file,
                        prompt=prompt,
                        size=size,
                    )
            else:
                response = client.images.generate(
                    model=model_name,
                    prompt=prompt,
                    size=size,
                    quality=quality,
                    n=1,
                )
            _write_openai_response(response, output)
            return {"provider": "openai", "model": model_name, "mode": "edit" if input_image else "generate"}
        except Exception as exc:
            last_error = exc
            continue
    raise ImageProviderError(f"OpenAI image call failed: {str(last_error)[:180] if last_error else 'unknown'}")


def _write_openai_response(response, output: Path) -> None:
    data = response.data[0]
    b64 = getattr(data, "b64_json", None)
    if b64:
        output.write_bytes(base64.b64decode(b64))
        return
    url = getattr(data, "url", None)
    if url:
        with urllib.request.urlopen(url, timeout=120) as resp:
            output.write_bytes(resp.read())
        return
    raise ImageProviderError("OpenAI response did not include image data")


def _gemini_image(
    prompt: str,
    output: Path,
    model: str = "",
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    key = load_secret("GEMINI_API_KEY") or load_secret("GOOGLE_API_KEY")
    if not key:
        raise ImageProviderError("GEMINI_API_KEY/GOOGLE_API_KEY is not configured")
    model_name = model or os.environ.get("GEMINI_IMAGE_MODEL") or "gemini-3.1-flash-image"
    payload: dict = {
        "model": model_name,
        "input": [{"type": "text", "text": prompt}],
        "response_format": _gemini_response_format(size, output),
    }
    if input_image:
        source = Path(input_image)
        mime = mimetypes.guess_type(str(source))[0] or "image/png"
        payload["input"].append(
            {
                "type": "image",
                "mime_type": mime,
                "data": base64.b64encode(source.read_bytes()).decode("ascii"),
            }
        )

    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"Gemini image call failed: HTTP {exc.code} {detail}") from exc

    image = body.get("output_image") or {}
    b64 = image.get("data")
    if not b64:
        raise ImageProviderError("Gemini response did not include output_image.data")
    output.write_bytes(base64.b64decode(b64))
    return {"provider": "gemini", "model": model_name, "mode": "edit" if input_image else "generate"}


def _gemini_response_format(size: str, output: Path) -> dict:
    aspect_ratio = "1:1"
    if "x" in size:
        width, height = [int(part) for part in size.lower().split("x", 1)]
        if width > height:
            aspect_ratio = "16:9"
        elif height > width:
            aspect_ratio = "9:16"
    return {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": aspect_ratio}


def _stock_image(
    prompt: str,
    output: Path,
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    errors: list[str] = []
    for provider in (_pexels_image, _pixabay_image):
        try:
            return provider(prompt, output, size=size, input_image=input_image)
        except Exception as exc:
            errors.append(f"{provider.__name__}: {type(exc).__name__}: {str(exc)[:160]}")
    raise ImageProviderError("all stock image providers failed; " + " | ".join(errors))


def _pexels_image(
    prompt: str,
    output: Path,
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    if input_image:
        raise ImageProviderError("Pexels search does not support image editing")
    key = load_secret("PEXELS_API_KEY")
    if not key:
        raise ImageProviderError("PEXELS_API_KEY is not configured")
    width, height = _parse_size(size)
    orientation = _stock_orientation(width, height)
    query = _stock_query(prompt)
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": "3", "orientation": orientation}
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": key, "User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"Pexels search failed: HTTP {exc.code} {detail}") from exc
    photos = body.get("photos") or []
    if not photos:
        raise ImageProviderError("Pexels search returned no photos")
    photo = photos[0]
    src = photo.get("src") or {}
    image_url = src.get("large2x") or src.get("large") or src.get("original")
    if not image_url:
        raise ImageProviderError("Pexels photo had no downloadable URL")
    _download_image(image_url, output)
    return {
        "provider": "pexels",
        "model": "stock-photo",
        "mode": "search",
        "query": query,
        "source_url": photo.get("url", ""),
        "photographer": photo.get("photographer", ""),
        "license": "Pexels",
    }


def _pixabay_image(
    prompt: str,
    output: Path,
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    if input_image:
        raise ImageProviderError("Pixabay search does not support image editing")
    key = load_secret("PIXABAY_API_KEY")
    if not key:
        raise ImageProviderError("PIXABAY_API_KEY is not configured")
    width, height = _parse_size(size)
    orientation = _stock_orientation(width, height)
    query = _stock_query(prompt)
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
        {
            "key": key,
            "q": query,
            "image_type": "photo",
            "per_page": "3",
            "safesearch": "true",
            "orientation": orientation,
        }
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"Pixabay search failed: HTTP {exc.code} {detail}") from exc
    hits = body.get("hits") or []
    if not hits:
        raise ImageProviderError("Pixabay search returned no images")
    hit = hits[0]
    image_url = hit.get("largeImageURL") or hit.get("webformatURL")
    if not image_url:
        raise ImageProviderError("Pixabay image had no downloadable URL")
    _download_image(image_url, output)
    return {
        "provider": "pixabay",
        "model": "stock-photo",
        "mode": "search",
        "query": query,
        "source_url": hit.get("pageURL", ""),
        "photographer": hit.get("user", ""),
        "license": "Pixabay",
    }


def _download_image(url: str, output: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"image download failed: HTTP {exc.code} {detail}") from exc
    if not body or len(body) < 2048:
        raise ImageProviderError("downloaded image was too small to be valid")
    if "image" not in content_type.lower() and not body.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):
        raise ImageProviderError(f"download response was not an image: {content_type}")
    output.write_bytes(body)


def _stock_orientation(width: int, height: int) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _stock_query(prompt: str) -> str:
    text = " ".join(str(prompt or "").replace("\n", " ").split())
    lower = text.casefold()
    topic_map = {
        "ai": "artificial intelligence workspace",
        "人工智能": "artificial intelligence workspace",
        "工具": "technology workspace",
        "效率": "productivity workspace",
        "自动化": "automation workflow",
        "编程": "programming developer",
        "代码": "programming developer",
        "商业": "business meeting",
        "小红书": "lifestyle workspace",
        "猫": "cat pet",
    }
    for marker, query in topic_map.items():
        if marker in lower:
            return query
    words = [part.strip(".,:;!?()[]{}\"'") for part in text.split(" ") if len(part.strip(".,:;!?()[]{}\"'")) >= 3]
    ascii_words = [w for w in words if w.isascii()]
    if ascii_words:
        return " ".join(ascii_words[:5])
    return "technology workspace"


def _pollinations_image(
    prompt: str,
    output: Path,
    model: str = "",
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    if input_image:
        raise ImageProviderError("Pollinations fallback does not support image editing")
    width, height = _parse_size(size)
    model_name = model or os.environ.get("POLLINATIONS_IMAGE_MODEL") or "flux"
    query = urllib.parse.urlencode(
        {
            "width": str(width),
            "height": str(height),
            "nologo": "true",
            "model": model_name,
        }
    )
    url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt[:1200])}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"Pollinations image call failed: HTTP {exc.code} {detail}") from exc
    if not body or len(body) < 2048:
        raise ImageProviderError("Pollinations response was too small to be a valid image")
    if "image" not in content_type.lower() and not body.startswith((b"\xff\xd8", b"\x89PNG")):
        raise ImageProviderError(f"Pollinations response was not an image: {content_type}")
    output.write_bytes(body)
    return {"provider": "pollinations", "model": model_name, "mode": "generate"}


def _parse_size(size: str) -> tuple[int, int]:
    try:
        width, height = [int(part) for part in str(size).lower().split("x", 1)]
    except Exception:
        return (1024, 1024)
    width = max(256, min(width, 1536))
    height = max(256, min(height, 1536))
    return (width, height)
