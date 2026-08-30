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
        content_home / "secrets" / "agnes.env",
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
    intent: str = "auto",
) -> dict:
    """Generate or edit an image and return a structured artifact record."""
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ImageProviderError("image prompt is empty")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    provider = _normalize_provider_name(provider)

    normalized_intent = _normalize_image_intent(intent, prompt, input_image)
    providers = _provider_chain(provider, intent=normalized_intent, input_image=input_image)
    errors: list[str] = []
    for name in providers:
        cached = _read_cache(prompt, output_path, name, model=model, size=size, input_image=input_image, intent=normalized_intent)
        if cached:
            return _finalize_image_result(
                cached,
                prompt=prompt,
                input_image=input_image,
                intent=normalized_intent,
                route="content_aware_auto" if provider == "auto" else "explicit_provider",
            )
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
            elif name == "sense_nova":
                result = _sensenova_image(prompt, output_path, model=model, size=size, input_image=input_image)
            elif name == "pixazo":
                result = _pixazo_image(prompt, output_path, model=model, size=size, input_image=input_image)
            elif name == "agnes":
                result = _agnes_image(prompt, output_path, model=model, size=size, input_image=input_image)
            else:
                raise ImageProviderError(f"unsupported image provider: {name}")
            result["path"] = str(output_path)
            result["bytes"] = output_path.stat().st_size
            result["intent"] = normalized_intent
            if provider == "auto" and name in {"stock", "pexels", "pixabay"} and _needs_ai_retouch(prompt, normalized_intent):
                result = _retouch_stock_image(prompt, output_path, result, size=size)
            result = _finalize_image_result(
                result,
                prompt=prompt,
                input_image=input_image,
                intent=normalized_intent,
                route="content_aware_auto" if provider == "auto" else "explicit_provider",
            )
            _write_cache(prompt, output_path, name, result, model=model, size=size, input_image=input_image, intent=normalized_intent)
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
        {"query": query, "per_page": "15", "orientation": orientation}
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
    photo = photos[_stock_result_index(prompt, len(photos))]
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
            "per_page": "15",
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
    hit = hits[_stock_result_index(prompt, len(hits))]
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


def _stock_result_index(prompt: str, count: int) -> int:
    if count <= 1:
        return 0
    digest = hashlib.sha256(str(prompt or "").encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count


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


def _sensenova_image(
    prompt: str,
    output: Path,
    model: str = "",
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    key = load_secret("SN_IMAGE_GEN_API_KEY") or load_secret("SN_API_KEY") or load_secret("SENSENOVA_API_KEY")
    if not key:
        raise ImageProviderError("SN_API_KEY is not configured")
    base_url = (load_secret("SN_IMAGE_GEN_BASE_URL") or load_secret("SN_BASE_URL") or "https://token.sensenova.cn/v1").rstrip("/")
    models = [item.strip() for item in (model or os.environ.get("SN_IMAGE_GEN_MODEL") or os.environ.get("SN_IMAGE_MODEL") or "sensenova-u1.5-lite,sensenova-u1-fast").split(",") if item.strip()]
    last_error: Exception | None = None
    for model_name in models:
        selected_size = _sensenova_size(size)
        payload = {
            "model": model_name,
            "prompt": prompt[:4000],
            "size": selected_size,
            "n": 1,
        }
        if input_image:
            source = Path(input_image)
            if not source.is_file():
                raise ImageProviderError("SenseNova input image is missing")
            payload["image"] = base64.b64encode(source.read_bytes()).decode("ascii")
        request = urllib.request.Request(
            f"{base_url}/images/generations",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"},
            method="POST",
        )
        try:
            with _urlopen_retry(request, timeout=240, attempts=2) as response:
                body = json.loads(response.read().decode("utf-8"))
            rows = body.get("data") or []
            if not rows:
                raise ImageProviderError("SenseNova response contained no image data")
            url = str(rows[0].get("url") or "")
            encoded = str(rows[0].get("b64_json") or "")
            if url:
                _download_image(url, output)
            elif encoded:
                output.write_bytes(base64.b64decode(encoded))
            else:
                raise ImageProviderError("SenseNova response had no url or b64_json")
            return {
                "provider": "sense_nova",
                "model": model_name,
                "mode": "edit" if input_image else "generate",
                "source_url": "generated:sense_nova",
                "license": "generated_for_project",
                "size": selected_size,
                "requested_size": size,
            }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:180]
            last_error = ImageProviderError(f"SenseNova {model_name} failed: HTTP {exc.code} {detail}")
        except (ImageProviderError, OSError, ValueError) as exc:
            last_error = exc
    raise ImageProviderError(f"SenseNova image generation failed: {str(last_error or 'unknown')[:180]}")


def _sensenova_size(size: str) -> str:
    width, height = _parse_size(size)
    ratio = width / max(1, height)
    if ratio >= 1.45:
        return "2752x1536"
    if ratio <= 0.69:
        return "1536x2752"
    if ratio >= 1.15:
        return "2496x1664"
    if ratio <= 0.87:
        return "1664x2496"
    return "2048x2048"


def _pixazo_image(
    prompt: str,
    output: Path,
    model: str = "",
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    if input_image:
        raise ImageProviderError("Pixazo provider does not support image editing")
    key = load_secret("PIXAZO_API_KEY")
    if not key:
        raise ImageProviderError("PIXAZO_API_KEY is not configured")
    width, height = _parse_size(size)
    request = urllib.request.Request(
        "https://gateway.pixazo.ai/getImage/v1/getSDXLImage",
        data=json.dumps({"prompt": prompt, "width": width, "height": height}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Ocp-Apim-Subscription-Key": key, "User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0.0"},
        method="POST",
    )
    try:
        with _urlopen_retry(request, timeout=60, attempts=2) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"Pixazo image call failed: HTTP {exc.code} {detail}") from exc
    url = str(body.get("imageUrl") or body.get("image_url") or "")
    if not url:
        raise ImageProviderError("Pixazo response missing imageUrl")
    _download_image(url, output)
    return {
        "provider": "pixazo",
        "model": model or "sdxl",
        "mode": "generate",
        "source_url": "generated:pixazo",
        "license": "generated_for_project",
        "size": f"{width}x{height}",
    }


def _agnes_image(
    prompt: str,
    output: Path,
    model: str = "",
    size: str = "1024x1024",
    input_image: str | Path | None = None,
) -> dict:
    key = load_secret("AGNES_API_KEY")
    if not key:
        raise ImageProviderError("AGNES_API_KEY is not configured")
    base_url = load_secret("AGNES_BASE_URL") or "https://apihub.agnes-ai.com/v1"
    model_name = model or load_secret("AGNES_IMAGE_MODEL") or "agnes-image-2.1-flash"
    width, height = _requested_dimensions(size)
    ratio = _agnes_ratio(width, height)
    tier = "2K" if max(width, height) > 1024 else "1K"
    payload: dict = {
        "model": model_name,
        "prompt": prompt,
        "size": tier,
        "ratio": ratio,
        "return_base64": True,
    }
    if input_image:
        source = Path(input_image)
        if not source.is_file():
            raise ImageProviderError("Agnes input image does not exist")
        mime = mimetypes.guess_type(source.name)[0] or "image/png"
        data_uri = f"data:{mime};base64,{base64.b64encode(source.read_bytes()).decode('ascii')}"
        payload["extra_body"] = {"image": [data_uri], "response_format": "b64_json"}
        payload.pop("return_base64", None)
    request = urllib.request.Request(
        base_url.rstrip("/") + "/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "ai-self-media-tools/agnes-image",
        },
        method="POST",
    )
    try:
        with _urlopen_retry(request, timeout=180, attempts=2) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:240]
        raise ImageProviderError(f"Agnes image call failed: HTTP {exc.code} {detail}") from exc
    row = (body.get("data") or [{}])[0] if isinstance(body, dict) else {}
    encoded = str(row.get("b64_json") or "") if isinstance(row, dict) else ""
    url = str(row.get("url") or "") if isinstance(row, dict) else ""
    if encoded:
        output.write_bytes(base64.b64decode(encoded))
    elif url:
        _download_image(url, output)
    else:
        raise ImageProviderError("Agnes image response missing url or b64_json")
    return {
        "provider": "agnes",
        "model": model_name,
        "mode": "edit" if input_image else "generate",
        "source_url": "generated:agnes",
        "license": "agnes_api_terms",
        "size": f"{width}x{height}",
        "native_tier": tier,
        "native_ratio": ratio,
    }


def _agnes_ratio(width: int, height: int) -> str:
    supported = [(1, 1), (3, 4), (4, 3), (16, 9), (9, 16), (2, 3), (3, 2), (21, 9)]
    target = width / max(1, height)
    left, right = min(supported, key=lambda pair: abs(pair[0] / pair[1] - target))
    return f"{left}:{right}"


def _requested_dimensions(size: str) -> tuple[int, int]:
    try:
        width, height = [int(part) for part in str(size).lower().split("x", 1)]
        return max(1, width), max(1, height)
    except Exception:
        return 1024, 1024


def _normalize_image_intent(intent: str, prompt: str, input_image: str | Path | None) -> str:
    normalized = str(intent or "auto").casefold().strip().replace("-", "_")
    if input_image:
        return "image_edit"
    if normalized not in {"", "auto"}:
        return normalized
    lower = str(prompt or "").casefold()
    if any(token in lower for token in ("cinematic advertising key art", "movie poster", "电影海报", "广告大片")):
        return "cinematic_cover"
    if any(token in lower for token in ("knowledge card", "知识卡", "infographic", "diagram")):
        return "knowledge_card_background"
    if any(token in lower for token in ("real scene", "real-scene", "documentary photo", "真实场景", "实景")):
        return "real_scene"
    if any(token in lower for token in ("illustration", "插画", "visual metaphor")):
        return "editorial_illustration"
    return "real_scene"


def _needs_ai_retouch(prompt: str, intent: str) -> bool:
    flag = os.environ.get("IMAGE_PROVIDER_AUTO_EDIT", "auto").casefold().strip()
    if flag in {"0", "false", "off", "disable"}:
        return False
    if flag in {"1", "true", "on", "force"}:
        return True
    if intent == "image_edit":
        return True
    lower = str(prompt or "").casefold()
    verbs = ("修图", "去水印", "换背景", "擦除", "移除人物", "retouch", "inpaint", "remove watermark", "replace background")
    return any(token in lower for token in verbs)


def _retouch_stock_image(prompt: str, output: Path, original: dict, *, size: str) -> dict:
    evidence_dir = Path(os.environ.get("IMAGE_PROVIDER_ORIGINAL_DIR") or output.parent / "image_edit_evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    original_copy = evidence_dir / output.name
    shutil.copy2(output, original_copy)
    failures: list[str] = []
    edit_prompt = f"Retouch the supplied image to match this content: {prompt[:1200]}. Preserve the main subject and remove unwanted text or visual clutter."
    for name in _provider_chain("auto", intent="image_edit", input_image=original_copy):
        temporary = output.with_name(output.name + ".tmp")
        try:
            if name == "sense_nova":
                edited = _sensenova_image(edit_prompt, temporary, size=size, input_image=original_copy)
            elif name == "gemini":
                edited = _gemini_image(edit_prompt, temporary, size=size, input_image=original_copy)
            elif name == "openai":
                edited = _openai_image(edit_prompt, temporary, size=size, input_image=original_copy)
            else:
                continue
            _verify_image_file(temporary)
            temporary.replace(output)
            return {
                **edited,
                "path": str(output),
                "bytes": output.stat().st_size,
                "edited": True,
                "edit_provider": name,
                "edit_reason": "explicit_retouch_intent",
                "original_provider": original.get("provider", ""),
                "original_source_url": original.get("source_url", ""),
                "original_license": original.get("license", ""),
                "original_evidence_path": str(original_copy),
            }
        except Exception as exc:
            failures.append(f"{name}:{type(exc).__name__}")
            temporary.unlink(missing_ok=True)
    return {
        **original,
        "edited": False,
        "edit_attempted": True,
        "edit_status": "fallback_kept_stock",
        "edit_error_provider": failures[-1].split(":", 1)[0] if failures else "",
        "edit_failures": failures,
        "original_evidence_path": str(original_copy),
    }


def _verify_image_file(path: Path) -> None:
    try:
        from PIL import Image, UnidentifiedImageError
        with Image.open(path) as image:
            image.load()
            if min(image.size) < 256:
                raise ImageProviderError("edited image resolution is too low")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ImageProviderError(f"edited image failed decoding: {exc}") from exc


def _normalize_provider_name(provider: str) -> str:
    normalized = str(provider or "auto").casefold().strip().replace("-", "_")
    return "sense_nova" if normalized == "sensenova" else normalized


def _finalize_image_result(result: dict, *, prompt: str, input_image: str | Path | None, intent: str, route: str) -> dict:
    payload = dict(result or {})
    payload["provider"] = _normalize_provider_name(payload.get("provider") or "")
    input_hash = ""
    if input_image:
        try:
            input_hash = hashlib.sha256(Path(input_image).read_bytes()).hexdigest()
        except OSError:
            input_hash = ""
    payload["provenance"] = {
        "provider": str(payload.get("provider") or ""),
        "model": str(payload.get("model") or ""),
        "mode": str(payload.get("mode") or ""),
        "route": route,
        "selected_for": intent,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "input_image_sha256": input_hash,
        "source_url": str(payload.get("source_url") or ""),
        "license": str(payload.get("license") or ""),
        "original_provider": str(payload.get("original_provider") or ""),
        "original_source_url": str(payload.get("original_source_url") or ""),
        "original_path": str(payload.get("original_evidence_path") or ""),
    }
    return payload


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
        # 2026-08-16 修复：flux-1-schnell 不接受 seed/steps（HTTP 400），仅传 prompt
        payload = json.dumps({"prompt": prompt[:2048]}).encode("utf-8")
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


def _provider_chain(provider: str, *, intent: str = "auto", input_image: str | Path | None = None) -> list[str]:
    if provider != "auto":
        return [provider]
    configured = os.environ.get("IMAGE_PROVIDER_CHAIN", "").strip()
    if configured:
        chain = [_normalize_provider_name(p) for p in configured.split(",") if p.strip()]
    elif input_image or intent == "image_edit":
        chain = ["agnes", "sense_nova"]
    elif intent in {"cinematic_cover", "editorial_illustration", "knowledge_card_background"}:
        chain = ["agnes", "sense_nova", "pixazo", "cloudflare", "pollinations", "stock"]
    elif intent == "fast_fallback":
        chain = ["cloudflare", "pixazo", "pollinations", "stock"]
    else:
        chain = ["stock", "agnes", "sense_nova", "pixazo", "cloudflare", "pollinations"]
    if os.environ.get("IMAGE_PROVIDER_ALLOW_PAID") == "1":
        chain.extend(["openai", "gemini"])
    if input_image or intent == "image_edit":
        chain = [name for name in chain if name in {"agnes", "sense_nova", "gemini", "openai"}]
    return list(dict.fromkeys(chain))


def _cache_dir() -> Path:
    content_home = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
    path = Path(os.environ.get("IMAGE_PROVIDER_CACHE_DIR", str(content_home / "data" / "cache" / "image_provider")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(prompt: str, provider: str, model: str = "", size: str = "1024x1024", input_image: str | Path | None = None, intent: str = "auto") -> str:
    h = hashlib.sha256()
    h.update(provider.encode("utf-8"))
    h.update(b"\0")
    h.update((model or "").encode("utf-8"))
    h.update(b"\0")
    h.update(size.encode("utf-8"))
    h.update(b"\0")
    h.update(prompt.encode("utf-8"))
    h.update(b"\0")
    h.update(str(intent or "auto").encode("utf-8"))
    if input_image:
        source = Path(input_image)
        h.update(b"\0")
        h.update(str(source).encode("utf-8"))
        try:
            h.update(hashlib.sha256(source.read_bytes()).digest())
        except OSError:
            pass
    return h.hexdigest()


def _read_cache(prompt: str, output: Path, provider: str, model: str = "", size: str = "1024x1024", input_image: str | Path | None = None, intent: str = "auto") -> dict | None:
    if os.environ.get("IMAGE_PROVIDER_DISABLE_CACHE") == "1":
        return None
    key = _cache_key(prompt, provider, model=model, size=size, input_image=input_image, intent=intent)
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


def _write_cache(prompt: str, output: Path, provider: str, result: dict, model: str = "", size: str = "1024x1024", input_image: str | Path | None = None, intent: str = "auto") -> None:
    if os.environ.get("IMAGE_PROVIDER_DISABLE_CACHE") == "1":
        return
    if not output.is_file() or output.stat().st_size < 2048:
        return
    key = _cache_key(prompt, provider, model=model, size=size, input_image=input_image, intent=intent)
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
