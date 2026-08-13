#!/usr/bin/env python3
"""
Unified Content Quality Gate - final audit for all content pipeline outputs.
Reuses promo_pipeline.py quality_review patterns.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from content_platform.content_depth import validate_content_depth_plan


def audit_autoclip(result):
    try:
        if not result or not result.get("clips"):
            return {"pass": False, "issues": ["No clips in result"]}
        clip_count = len(result["clips"])
        has_compilation = bool(result.get("compilation"))
        return {
            "pass": clip_count > 0,
            "clip_count": clip_count,
            "has_compilation": has_compilation,
            "issues": [] if clip_count > 0 else ["Zero clips generated"],
        }
    except Exception as exc:
        return {"pass": False, "issues": [str(exc)]}


def audit_github_star(project):
    if not project:
        return {"pass": False, "issues": ["Empty project"]}
    issues = []
    if not project.get("description") or len(str(project["description"])) < 10:
        issues.append("Description too short")
    if (project.get("stars") or 0) < 10:
        issues.append("Too few stars")
    return {"pass": len(issues) == 0, "issues": issues}


def audit_collected_data(data):
    if not data:
        return {"pass": False, "issues": ["No data"]}
    sources = data.get("data", [])
    if not sources:
        return {"pass": False, "issues": ["No sources"]}
    ok = sum(1 for s in sources if s.get("status") == 200)
    return {
        "pass": ok >= 1,
        "sources_ok": ok,
        "total": len(sources),
        "issues": [] if ok >= 1 else ["No valid sources"],
    }


GATES = {
    "video_autoclip": audit_autoclip,
    "github_star": audit_github_star,
    "collected_data": audit_collected_data,
    "content_depth": validate_content_depth_plan,
}


def run_quality_gate(content_type, content_data):
    checker = GATES.get(content_type)
    if not checker:
        return {"pass": True, "note": f"No quality gate registered for type: {content_type}"}
    return checker(content_data)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Unified Content Quality Gate")
    parser.add_argument("--type", choices=list(GATES.keys()), help="Content type to audit")
    parser.add_argument("--check-depth", action="store_true", help="Validate a content_depth_plan directly")
    parser.add_argument("--data", default="{}", help="JSON content data")
    args = parser.parse_args()

    if not args.type and not args.check_depth:
        parser.error("--type or --check-depth is required")
    data = json.loads(args.data)
    result = run_quality_gate("content_depth" if args.check_depth else args.type, data)
    if args.check_depth:
        result = {"pass": bool(result.get("passed")), **result}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["pass"] else 1)
