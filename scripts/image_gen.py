#!/usr/bin/env python3
"""Project image generation and editing CLI.

This script is intentionally provider-neutral. It emits only JSON on stdout so
Pipeline adapters can parse it reliably; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.image_provider import ImageProviderError, generate_image


def _skip_gate_authorized() -> bool:
    return os.environ.get("IMAGE_GEN_ALLOW_SKIP_GATES") == "1"


def _run_optional_gate(command: list[str], timeout: int) -> None:
    if not Path(command[1]).is_file():
        return
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "gate failed")[-800:]
        raise RuntimeError(detail)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or edit project images")
    parser.add_argument("positional_prompt", nargs="?", help="Prompt text for legacy callers")
    parser.add_argument("--prompt", help="Prompt text")
    parser.add_argument("--input-image", help="Optional image to edit")
    parser.add_argument("--output", default="/tmp/ai-self-media-image.png")
    parser.add_argument("--provider", choices=["auto", "openai", "gemini", "stock", "pexels", "pixabay", "pollinations"], default="auto")
    parser.add_argument("--model", default="")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="low")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-visual-gate", action="store_true")
    # Retained for old MediaBridge callers. The provider now decides the method.
    parser.add_argument("--method", default="")
    args = parser.parse_args()

    prompt = args.prompt or args.positional_prompt or ""
    output = Path(args.output)
    try:
        if (args.skip_preflight or args.skip_visual_gate) and not _skip_gate_authorized():
            raise RuntimeError("image gate skip is disabled; set IMAGE_GEN_ALLOW_SKIP_GATES=1 only for audited emergency runs")
        if not args.skip_preflight:
            _run_optional_gate(
                [sys.executable, str(ROOT / "scripts" / "preflight_prompt.py"), "--prompt", prompt, "--type", "image"],
                timeout=15,
            )
        result = generate_image(
            prompt=prompt,
            output=output,
            provider=args.provider,
            model=args.model,
            size=args.size,
            quality=args.quality,
            input_image=args.input_image,
        )
        if not args.skip_visual_gate:
            _run_optional_gate([sys.executable, str(ROOT / "scripts" / "visual_gate.py"), "--image", str(output)], timeout=30)
        checksum = hashlib.sha256(output.read_bytes()).hexdigest()
        result.update({"ok": True, "checksum": checksum})
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ImageProviderError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)[:500]}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
