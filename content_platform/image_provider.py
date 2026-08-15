"""Unified image generation and editing providers."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import time
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

    providers = _provider_chain(provider)
    errors: list[str] = []
    for name in providers:
        cached = _read_cache(prompt, output_path, name, model=model, size=size, input_image=input_image)
        if cached:
            return cached
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
            elif name == "cloudflare":
                result = _cloudflare_image(prompt, output_path, model=model, size=size, input_image=input_image)
            else:
                raise ImageProviderError(f"unsupported image provider: {name}")
            result["path"] = str(output_path)
            result["bytes"] = output_path.stat().st_size
            _write_cache(prompt, output_path, name, result, model=model, size=size, input_image=input_image)
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
        with _urlopen_retry(url, timeout=120) as resp:
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
        with _urlopen_retry(req, timeout=180) as resp:
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
        with _urlopen_retry(req, timeout=30) as resp:
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
        with _urlopen_retry(req, timeout=30) as resp:
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
        with _urlopen_retry(req, timeout=90) as resp:
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
    # Cover prompts embed "Topic context: <topic>". Prefer topic-specific
    # English keywords so two covers never collapse to the same photo.
    # NOTE: section prompts also embed "Topic context:" — they must skip this
    # branch or every section collapses to the same cover query (2026-08-15 fix).
    cover_topic = ""
    if "topic context:" in lower and "section illustration for:" not in lower:
        marker_idx = lower.find("topic context:")
        if marker_idx != -1:
            cover_topic = text[marker_idx + len("topic context:"):].split(". clear subject", 1)[0].strip()
    if cover_topic:
        # 2026-08-15 优化：先匹配主题关键词（cn_map），再退回英文词，
        # 避免 cover 查询落到模板残留词（如 "Concrete visual metaphor"）。
        cn_map = {
            "记忆": "memory brain knowledge",
            "模型": "artificial intelligence model",
            "智能体": "artificial intelligence agent robot",
            "效率": "productivity workspace",
            "工具": "technology workspace",
            "自动化": "automation workflow",
            "编程": "programming developer",
            "代码": "programming developer",
            "商业": "business meeting",
            "实验": "research laboratory",
            "研究": "research laboratory",
            "数据": "data analytics",
            "安全": "cybersecurity lock",
            "成本": "finance calculator",
            "价格": "finance calculator",
            "工作": "office workspace",
            "团队": "team collaboration",
            "用户": "person using smartphone",
            "视频": "video production camera",
            "内容": "content creation desk",
            "写作": "writing desk notebook",
            "翻译": "translation language",
            "会议": "business meeting",
            "笔记": "notebook study",
            "办公": "office workspace",
            "开源": "open source code",
            "软件": "software development",
            "测试": "software testing",
            "对比": "comparison charts",
            "选型": "choosing technology options",
            "养宠": "pet cat dog care",
            "宠物": "pet cat dog",
            "猫咪": "cute cat",
            "狗狗": "cute dog",
        }
        for marker, query in cn_map.items():
            if marker in cover_topic:
                return query
    # Section illustrations embed their own section title (e.g.
    # "Section illustration for: AI Agent 最大的短板..."); extract that
    # section text so every image gets a distinct query instead of all
    # collapsing to the same topic_map hit.
    section_text = ""
    if "section illustration for:" in lower:
        marker_idx = lower.find("section illustration for:")
        if marker_idx != -1:
            section_text = text[marker_idx + len("section illustration for:"):].split("Topic context:", 1)[0].strip()
            if "topic context:" in section_text.casefold():
                section_text = section_text.split("topic context:", 1)[0].strip()
    if section_text:
        words = [
            part.strip(".,:;!?()[]{}\"'")
            for part in section_text.split(" ")
            if len(part.strip(".,:;!?()[]{}\"'")) >= 3
        ]
        ascii_words = [w for w in words if w.isascii()]
        if ascii_words:
            return " ".join(ascii_words[:5])
        cn_map = {
            "记忆": "memory brain knowledge",
            "失忆": "memory brain knowledge",
            "模型": "artificial intelligence model",
            "智能体": "artificial intelligence agent robot",
            "效率": "productivity workspace",
            "工具": "technology workspace",
            "自动化": "automation workflow",
            "编程": "programming developer",
            "代码": "programming developer",
            "商业": "business meeting",
            "实验": "research laboratory",
            "研究": "research laboratory",
            "数据": "data analytics",
            "安全": "cybersecurity lock",
            "成本": "finance calculator",
            "价格": "finance calculator",
            "工作": "office workspace",
            "团队": "team collaboration",
            "用户": "person using smartphone",
            "视频": "video production camera",
            "内容": "content creation desk",
            "写作": "writing desk notebook",
            "翻译": "translation language",
            "会议": "business meeting",
            "笔记": "notebook study",
            "办公": "office workspace",
            "选型": "choosing technology options",
            "踩坑": "problem solving debug",
            "效果": "results comparison charts",
            "对比": "comparison charts",
            "架构": "system architecture blueprint",
            "设计": "design blueprint workspace",
            "方案": "solution planning whiteboard",
            "复盘": "review analysis report",
            "边界": "boundary limitations discussion",
            "适合": "target audience personas",
            "流程": "workflow diagram process",
            "调度": "automation scheduler pipeline",
            "发布": "publishing content online",
            "选题": "topic selection research",
            "流水线": "automation workflow pipeline",
        }
        for marker, query in cn_map.items():
            if marker in section_text:
                return query
    for marker, query in topic_map.items():
        if marker in lower:
            return query
    # 中文 section 兜底：用文本中的汉字生成差异化查询，禁止全部落到同一默认词
    zh_segment = re.findall(r"[\u4e00-\u9fff]+", text)
    if zh_segment:
        joined = "".join(zh_segment)
        kw = joined[:6]
        return f"editorial illustration {kw}"
    words = [part.strip(".,:;!?()[]{}\\\"'") for part in text.split(" ") if len(part.strip(".,:;!?()[]{}\\\"'\"")) >= 3]
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
        with _urlopen_retry(req, timeout=90, attempts=3) as resp:
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


def _cloudflare_image(
    prompt: str,
    output: Path,
    model: str = "",
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    if input_image:
        raise ImageProviderError("Cloudflare image provider does not support image editing")
    worker_url = load_secret("CF_WORKER_URL") or load_secret("CLOUDFLARE_IMAGE_WORKER_URL")
    account_id = load_secret("CLOUDFLARE_ACCOUNT_ID")
    token = load_secret("CLOUDFLARE_API_TOKEN") or load_secret("CF_WORKER_KEY")
    model_name = model or os.environ.get("CLOUDFLARE_IMAGE_MODEL") or "@cf/black-forest-labs/flux-1-schnell"
    width, height = _parse_size(size)
    if worker_url:
        url = worker_url
        payload = json.dumps({"prompt": prompt, "width": width, "height": height, "model": model_name}).encode("utf-8")
    elif account_id and token:
        quoted_model = urllib.parse.quote(model_name, safe="/@")
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{quoted_model}"
        payload = json.dumps({"prompt": prompt[:2048], "seed": int(time.time()) % 2_147_483_647, "steps": 4}).encode("utf-8")
    else:
        raise ImageProviderError("Cloudflare image provider is not configured")
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with _urlopen_retry(req, timeout=90, attempts=3) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"Cloudflare image call failed: HTTP {exc.code} {detail}") from exc
    image = _extract_cloudflare_image(body, content_type)
    if len(image) < 2048:
        raise ImageProviderError("Cloudflare response was too small to be a valid image")
    output.write_bytes(image)
    return {"provider": "cloudflare", "model": model_name, "mode": "generate"}


def _extract_cloudflare_image(body: bytes, content_type: str) -> bytes:
    if "image" in content_type.lower() or body.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):
        return body
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise ImageProviderError(f"Cloudflare response was not an image: {content_type}") from exc
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict):
        b64 = result.get("image") or result.get("b64_json")
        if isinstance(b64, str) and b64:
            return base64.b64decode(b64)
        url = result.get("url")
        if isinstance(url, str) and url:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"})
            with _urlopen_retry(req, timeout=90) as resp:
                return resp.read()
    raise ImageProviderError("Cloudflare response did not include image data")


def _parse_size(size: str) -> tuple[int, int]:
    try:
        width, height = [int(part) for part in str(size).lower().split("x", 1)]
    except Exception:
        return (1024, 1024)
    width = max(256, min(width, 1536))
    height = max(256, min(height, 1536))
    return (width, height)


def _provider_chain(provider: str) -> list[str]:
    if provider != "auto":
        return [provider]
    configured = os.environ.get("IMAGE_PROVIDER_CHAIN", "").strip()
    if configured:
        return [p.strip() for p in configured.split(",") if p.strip()]
    chain = ["stock", "pollinations", "cloudflare"]
    if os.environ.get("IMAGE_PROVIDER_ALLOW_PAID") == "1":
        chain.extend(["openai", "gemini"])
    return chain


def _cache_dir() -> Path:
    content_home = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
    path = Path(os.environ.get("IMAGE_PROVIDER_CACHE_DIR", str(content_home / "data" / "cache" / "image_provider")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(prompt: str, provider: str, model: str = "", size: str = "1024x1024", input_image: str | Path | None = None) -> str:
    h = hashlib.sha256()
    h.update(provider.encode("utf-8"))
    h.update(b"\0")
    h.update((model or "").encode("utf-8"))
    h.update(b"\0")
    h.update(size.encode("utf-8"))
    h.update(b"\0")
    h.update(prompt.encode("utf-8"))
    if input_image:
        source = Path(input_image)
        h.update(b"\0")
        h.update(str(source).encode("utf-8"))
        try:
            h.update(hashlib.sha256(source.read_bytes()).digest())
        except OSError:
            pass
    return h.hexdigest()


def _read_cache(prompt: str, output: Path, provider: str, model: str = "", size: str = "1024x1024", input_image: str | Path | None = None) -> dict | None:
    if os.environ.get("IMAGE_PROVIDER_DISABLE_CACHE") == "1":
        return None
    key = _cache_key(prompt, provider, model=model, size=size, input_image=input_image)
    image = _cache_dir() / f"{key}.img"
    meta = _cache_dir() / f"{key}.json"
    if not image.is_file() or image.stat().st_size < 2048 or not meta.is_file():
        return None
    try:
        result = json.loads(meta.read_text(encoding="utf-8"))
        shutil.copyfile(image, output)
        result.update({"path": str(output), "bytes": output.stat().st_size, "cache_hit": True})
        return result
    except Exception:
        return None


def _write_cache(prompt: str, output: Path, provider: str, result: dict, model: str = "", size: str = "1024x1024", input_image: str | Path | None = None) -> None:
    if os.environ.get("IMAGE_PROVIDER_DISABLE_CACHE") == "1":
        return
    if not output.is_file() or output.stat().st_size < 2048:
        return
    key = _cache_key(prompt, provider, model=model, size=size, input_image=input_image)
    image = _cache_dir() / f"{key}.img"
    meta = _cache_dir() / f"{key}.json"
    cache_result = {k: v for k, v in result.items() if k not in {"path"}}
    cache_result.update({"cache_key": key, "cached_at": int(time.time())})
    try:
        shutil.copyfile(output, image)
        meta.write_text(json.dumps(cache_result, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _urlopen_retry(request, timeout: int = 90, attempts: int = 2):
    last: Exception | None = None
    for idx in range(max(1, attempts)):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise
            last = exc
        except urllib.error.URLError as exc:
            last = exc
        if idx + 1 < attempts:
            time.sleep(min(2 ** idx, 8))
    if last:
        raise last
    raise ImageProviderError("urlopen failed without exception")
