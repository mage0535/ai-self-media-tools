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
from content_platform.prompt_compiler import compile_prompt_bundle, validate_prompt_bundle


def _normalize_image_prompt(prompt: str) -> str:
    text = " ".join(str(prompt or "").split()).strip()
    if not text:
        return text
    lower = text.casefold()
    additions: list[str] = []
    pet_prompt = any(marker in lower for marker in ("cat", "dog", "pet", "猫", "狗", "宠物", "萌宠"))
    indoor_pet_prompt = any(marker in lower for marker in ("indoors", "indoor", "home", "room", "cushion", "sofa", "chair", "室内", "家里", "沙发", "软垫"))
    if not any(marker in lower for marker in ["subject", "主体", "main subject", "visual metaphor"]):
        additions.append("clear main subject")
    environment_markers = [
        "environment", "背景", "scene", "workspace", "studio", "office", "desk", "financial", "finance",
        "invoice", "document", "laptop", "data center", "server", "server rack", "coding", "code editor",
        "chip", "circuit board", "meeting", "kitchen", "street", "outdoor", "indoor", "home", "room",
        "办公", "办公室", "桌", "财务", "发票", "文件", "电脑", "数据中心", "服务器", "机房", "代码",
        "芯片", "电路板", "会议室", "厨房", "街道", "室外", "室内", "家里", "房间",
    ]
    if pet_prompt:
        if not any(marker in lower for marker in ["environment", "背景", "scene", "workspace", "studio"]):
            additions.append("natural indoor pet environment" if indoor_pet_prompt else "natural outdoor pet environment")
    elif not any(marker in lower for marker in environment_markers):
        additions.append("topic-matched environment relevant to the described subject")
    if not any(marker in lower for marker in ["light", "光", "lighting", "well-lit"]):
        additions.append("soft natural lighting")
    if not any(marker in lower for marker in ["composition", "构图", "close-up", "wide angle", "centered"]):
        additions.append("balanced composition with foreground and background depth")
    if not any(marker in lower for marker in ["style", "风格", "photography", "illustration", "cinematic"]):
        additions.append("clean editorial illustration style")
    if "no text" not in lower and "无文字" not in lower:
        additions.append("no text")
    return text if not additions else f"{text}, {', '.join(additions)}"


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
    parser.add_argument(
        "--provider",
        choices=["auto", "openai", "openai-codex", "gemini", "go_gemini", "go", "stock", "pexels", "pixabay", "pollinations", "cloudflare", "sense_nova", "pixazo"],
        default="auto",
    )
    parser.add_argument("--model", default="")
    parser.add_argument("--platform", default="generic_image", help="Prompt registry profile")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="low")
    parser.add_argument(
        "--quality-first",
        action="store_true",
        help="Prefer high-quality AI providers while retaining bounded fallback",
    )
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-visual-gate", action="store_true")
    # Retained for old MediaBridge callers. The provider now decides the method.
    parser.add_argument("--method", default="")
    args = parser.parse_args()
    if args.quality_first:
        # Explicit quality-first is the user authorization to spend paid image quota.
        os.environ["IMAGE_PROVIDER_QUALITY_FIRST"] = "1"
        os.environ["IMAGE_PROVIDER_ALLOW_PAID"] = "1"

    prompt = _normalize_image_prompt(args.prompt or args.positional_prompt or "")
    output = Path(args.output)
    prompt_bundle = None
    try:
        if (args.skip_preflight or args.skip_visual_gate) and not _skip_gate_authorized():
            raise RuntimeError("image gate skip is disabled; set IMAGE_GEN_ALLOW_SKIP_GATES=1 only for audited emergency runs")
        if not args.skip_preflight:
            prompt_bundle = compile_prompt_bundle(
                {
                    "platform": args.platform,
                    "content_type": "image",
                    "topic": prompt,
                    "audience": "content viewer",
                    "goal": "create a topic-matched image",
                    "evidence": ["user-provided prompt"],
                    "visual_style": "写实、清晰、内容相关",
                    "constraints": ["保留原始主题语义", "不要新增无关主体"],
                }
            )
            bundle_gate = validate_prompt_bundle(prompt_bundle)
            if not bundle_gate["passed"]:
                raise RuntimeError(f"prompt bundle gate failed: {bundle_gate['errors']}")
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
        if prompt_bundle is not None:
            result["prompt_bundle_fingerprint"] = prompt_bundle["fingerprint"]
            result["prompt_quality_contract"] = prompt_bundle["quality_contract"]
            result["prompt_platform"] = args.platform
        skipped_gates = []
        if args.skip_preflight:
            skipped_gates.append("prompt_preflight")
        if args.skip_visual_gate:
            skipped_gates.append("visual_gate")
        if skipped_gates:
            result["skipped_gates"] = skipped_gates
            result["gate_skip_mode"] = "audited_local_emergency"
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ImageProviderError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)[:500]}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
