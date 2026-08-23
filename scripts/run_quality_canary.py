#!/usr/bin/env python3
"""Reproducible contract canary runner; never publishes or invents media evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.capability_context import build_generation_capability_context
from content_platform.capability_runtime import execute_generation_capabilities
from content_platform.content_assets import load_compiled_assets
from content_platform.content_profile import classify_content_profile
from content_platform.publication_ledger import PublicationLedger
from content_platform.tts_cache import tts_fingerprint


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def run_canary() -> dict:
    cases = []
    inputs = [
        ("article", "AI工具实测清单", "wechat"), ("carousel", "文化海报清单", "xiaohongshu"),
        ("short_video", "电影感AI工具教程", "douyin_ai"), ("long_video", "AI工作流横屏复盘", "bilibili"),
        ("profile_tech", "AI工具效率", "douyin_ai"), ("profile_culture", "地域文化海报", "xiaohongshu"),
        ("profile_pets", "猫狗知识", "douyin_pet"), ("router", "电影感AI工具", "douyin_ai"),
        ("structure", "问题解决步骤", "zhihu"), ("tts", "AI API TTS", "douyin_ai"),
        ("ledger", "verified publication", "x"), ("insufficient", "collector failure", "x"),
    ]
    for name, topic, platform in inputs:
        result = {"name": name, "platform": platform, "input_sha256": _hash({"topic": topic, "platform": platform}), "status": "declared", "evidence": {}}
        if name.startswith("profile"):
            result["evidence"] = classify_content_profile(topic, platform)
            result["status"] = "contract_verified"
        elif name in {"article", "carousel", "short_video", "long_video", "router"}:
            result["evidence"] = build_generation_capability_context(platform, {"topic": topic, "content_form": name})
            result["status"] = "contract_verified"
        elif name == "structure":
            result["evidence"] = execute_generation_capabilities({"title": topic, "body": "问题导致结果失败。按步骤解决并验证。"}, {"platform": platform, "content_form": "article"})
            result["status"] = "contract_verified" if result["evidence"].get("passed") else "failed"
        elif name == "tts":
            result["evidence"] = {"fingerprint": tts_fingerprint(display_text=topic, tts_text="A I A P I 语音合成", provider="edge", model="edge-v1", voice="default", rate="-5%", pitch="+0Hz", pronunciation_dictionary_version="test", postprocess_profile="none")}
            result["status"] = "contract_verified"
        else:
            result["evidence"] = {"status": "contract_only", "note": "publication and media canaries require real verified external identity or media input"}
        cases.append(result)
    contract_passed = sum(c["status"] in {"contract_verified", "artifact_verified", "external_verified"} for c in cases)
    external_pending = [c["name"] for c in cases if c["evidence"].get("status") == "contract_only"]
    return {
        "version": "quality_canary_v1",
        "total": len(cases),
        "declared": len(cases),
        "passed": contract_passed,
        "failed": sum(c["status"] == "failed" for c in cases),
        "pending": [c["name"] for c in cases if c["status"] == "declared"],
        "evidence_level": "contract_only" if external_pending else "full",
        "production_ready": not external_pending,
        "external_evidence_pending": external_pending,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="tests/quality_canary_report.json")
    args = parser.parse_args()
    report = run_canary()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
