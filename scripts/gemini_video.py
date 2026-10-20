#!/usr/bin/env python3
"""Gemini Veo text-to-video and image-to-video adapter.

The adapter is opt-in. It uses the Hermes Gemini credential pool, inherits the
process HTTP(S)/SOCKS proxy, polls the long-running operation, and writes the
returned MP4 without logging credentials.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.image_provider import _gemini_keys

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "veo-3.1-fast-generate-preview"


class GeminiVideoError(RuntimeError):
    pass


def _request(url: str, key: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
            "User-Agent": "ai-self-media-tools/gemini-video",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        error = GeminiVideoError(f"HTTP {exc.code}: {detail}")
        error.http_code = exc.code  # type: ignore[attr-defined]
        raise error from exc
    except (OSError, ValueError) as exc:
        raise GeminiVideoError(str(exc)[:500]) from exc


def _operation_url(name: str) -> str:
    if name.startswith("http://") or name.startswith("https://"):
        return name
    return f"{BASE_URL}/{name.lstrip('/')}"


def _build_instance(prompt: str, input_image: Path | None) -> dict:
    instance = {"prompt": prompt}
    if input_image:
        mime = mimetypes.guess_type(str(input_image))[0] or "image/png"
        instance["image"] = {
            "bytesBase64Encoded": base64.b64encode(input_image.read_bytes()).decode("ascii"),
            "mimeType": mime,
        }
    return instance


def _generate_with_key(
    key: str,
    *,
    model: str,
    prompt: str,
    input_image: Path | None,
    aspect_ratio: str,
    duration_seconds: int,
    generate_audio: bool,
    timeout: int,
    poll_interval: int,
) -> dict:
    payload = {
        "instances": [_build_instance(prompt, input_image)],
        "parameters": {
            "aspectRatio": aspect_ratio,
            "durationSeconds": duration_seconds,
            "generateAudio": generate_audio,
        },
    }
    start = _request(f"{BASE_URL}/models/{model}:predictLongRunning", key, method="POST", payload=payload)
    operation = start.get("name")
    if not operation:
        raise GeminiVideoError("Veo response did not include an operation name")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _request(_operation_url(operation), key)
        if state.get("done"):
            if state.get("error"):
                raise GeminiVideoError(json.dumps(state["error"], ensure_ascii=False)[:500])
            response = state.get("response") or {}
            video = response.get("generateVideoResponse") or response
            samples = video.get("generatedSamples") or video.get("generated_videos") or []
            if not samples:
                raise GeminiVideoError("Veo operation completed without a generated video")
            item = samples[0]
            uri = (item.get("video") or {}).get("uri") or item.get("uri")
            if not uri:
                raise GeminiVideoError("Veo response did not include a video URI")
            return {"operation": operation, "video_uri": uri, "model": model}
        time.sleep(poll_interval)
    raise GeminiVideoError(f"Veo operation timed out after {timeout}s")


def generate_video(
    *,
    prompt: str,
    output: Path,
    model: str = DEFAULT_MODEL,
    input_image: Path | None = None,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 8,
    generate_audio: bool = True,
    timeout: int = 900,
    poll_interval: int = 10,
) -> dict:
    keys = _gemini_keys()
    if not keys:
        raise GeminiVideoError("No Gemini credential is configured")
    failures: list[str] = []
    for key in keys:
        try:
            result = _generate_with_key(
                key,
                model=model,
                prompt=prompt,
                input_image=input_image,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                generate_audio=generate_audio,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            uri = result["video_uri"]
            request = urllib.request.Request(
                uri,
                headers={"x-goog-api-key": key, "User-Agent": "ai-self-media-tools/gemini-video"},
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(response.read())
            result.update({
                "provider": "gemini",
                "mode": "image-to-video" if input_image else "text-to-video",
                "path": str(output),
                "bytes": output.stat().st_size,
            })
            return result
        except GeminiVideoError as exc:
            code = getattr(exc, "http_code", None)
            failures.append(f"HTTP {code}: {exc}" if code else str(exc))
            if code not in {401, 403, 429}:
                break
    raise GeminiVideoError("All Gemini credentials failed; " + " | ".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=os.environ.get("GEMINI_VIDEO_MODEL", DEFAULT_MODEL))
    parser.add_argument("--input-image")
    parser.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16", "1:1"])
    parser.add_argument("--duration-seconds", type=int, default=8, choices=[4, 6, 8])
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-interval", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        result = generate_video(
            prompt=args.prompt,
            output=Path(args.output),
            model=args.model,
            input_image=Path(args.input_image) if args.input_image else None,
            aspect_ratio=args.aspect_ratio,
            duration_seconds=args.duration_seconds,
            generate_audio=not args.no_audio,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
    except GeminiVideoError as exc:
        print(json.dumps({"ok": False, "provider": "gemini", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
