"""Agnes multimodal provider adapters with auditable async video polling."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

from .image_provider import ImageProviderError, load_secret


class AgnesVideoProvider:
    def __init__(self, *, timeout: int = 600, poll_interval: float = 2.0):
        self.timeout = int(timeout)
        self.poll_interval = float(poll_interval)

    def available(self) -> bool:
        return bool(load_secret("AGNES_API_KEY"))

    def generate(
        self,
        prompt: str,
        output: str | Path,
        *,
        model: str = "",
        seconds: int = 5,
        aspect_ratio: str = "16:9",
        first_frame: str = "",
        last_frame: str = "",
        images: list[str] | None = None,
    ) -> dict:
        key = load_secret("AGNES_API_KEY")
        if not key:
            raise RuntimeError("AGNES_API_KEY is not configured")
        model_name = model or load_secret("AGNES_VIDEO_MODEL") or "agnes-video-2.5-flash"
        if model_name == "agnes-video-2.5-flash" and not 4 <= int(seconds) <= 12:
            raise ValueError("Agnes Video 2.5 Flash seconds must be in 4..12")
        references = list(images or [])
        if model_name == "agnes-video-2.5-flash" and len(references) > 5:
            raise ValueError("Agnes Video 2.5 Flash accepts at most five reference images")
        mode = "keyframe" if first_frame or last_frame else "reference" if references else "text"
        payload = {
            "model": model_name,
            "prompt": str(prompt),
            "seconds": str(int(seconds)),
            "mode": mode,
            "n": 1,
        }
        if model_name == "agnes-video-2.5-flash":
            payload.update({"size": "720P", "aspect_ratio": aspect_ratio})
        if first_frame:
            payload["first_frame"] = first_frame
        if last_frame:
            payload["last_frame"] = last_frame
        if references:
            payload["images"] = references
        base = load_secret("AGNES_BASE_URL") or "https://apihub.agnes-ai.com/v1"
        created = self._request(base.rstrip("/") + "/videos", key, payload)
        video_id = str(created.get("video_id") or created.get("id") or "")
        task_id = str(created.get("task_id") or created.get("id") or "")
        if not video_id and not task_id:
            raise RuntimeError("Agnes video task response missing task identity")
        deadline = time.monotonic() + self.timeout
        final = created
        while time.monotonic() < deadline:
            status = str(final.get("status") or "").casefold()
            if status == "completed":
                break
            if status in {"failed", "cancelled", "canceled"}:
                raise RuntimeError("Agnes video generation failed")
            query = {"video_id": video_id}
            if model_name != "agnes-video-v2.0":
                query["model_name"] = model_name
            poll_url = "https://apihub.agnes-ai.com/agnesapi?" + urllib.parse.urlencode(query)
            if self.poll_interval:
                time.sleep(self.poll_interval)
            final = self._request(poll_url, key)
        else:
            raise TimeoutError("Agnes video generation timed out")
        metadata = final.get("metadata") if isinstance(final.get("metadata"), dict) else {}
        url = str(metadata.get("url") or final.get("url") or "")
        if not url:
            raise RuntimeError("Agnes completed task missing video URL")
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        _download(url, target)
        if not target.is_file() or target.stat().st_size <= 0:
            raise RuntimeError("Agnes video download produced no artifact")
        return {
            "provider": "agnes",
            "model": model_name,
            "status": "completed",
            "mode": mode,
            "video_id": video_id,
            "task_id": task_id,
            "source_url": url,
            "license": "agnes_api_terms",
            "path": str(target),
            "bytes": target.stat().st_size,
            "seconds": str(final.get("seconds") or seconds),
            "aspect_ratio": aspect_ratio,
        }

    @staticmethod
    def _request(url: str, key: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Agnes API HTTP {exc.code}: {detail}") from exc
        if not isinstance(body, dict):
            raise RuntimeError("Agnes response is not a JSON object")
        return body


def _download(url: str, output: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ai-self-media-tools/agnes-video"})
    with urllib.request.urlopen(request, timeout=180) as response:
        output.write_bytes(response.read())


def probe_agnes() -> dict:
    configured = bool(load_secret("AGNES_API_KEY"))
    return {
        "available": configured,
        "configured": configured,
        "image_auto_enabled": configured and os.environ.get("AGNES_IMAGE_AUTO_ENABLED") == "1",
        "video_auto_enabled": configured and os.environ.get("AGNES_VIDEO_AUTO_ENABLED") == "1",
        "image_model": load_secret("AGNES_IMAGE_MODEL") or "agnes-image-2.1-flash",
        "video_model": load_secret("AGNES_VIDEO_MODEL") or "agnes-video-2.5-flash",
    }
