#!/usr/bin/env python3
"""Legacy Kuaishou video entrypoint guarded by the unified workflow gate.

This script used to generate a fixed Kuaishou card video directly. That path
skipped operations strategy, trend evidence, diverse card layouts, approved
music checks, schedule planning, and management-page postcheck planning.

It is now intentionally a compatibility guard: callers must pass a complete
manifest that has already been produced by the standard Pipeline workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform.media_quality import validate_kuaishou_auto_packet


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Pipeline-produced Kuaishou manifest before legacy handoff."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to the Kuaishou packet/manifest produced by the standard Pipeline workflow.",
    )
    parser.add_argument(
        "--allow-legacy-handoff",
        action="store_true",
        help="Allow this compatibility wrapper to return success after validation.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "manifest_not_found",
                    "path": str(manifest_path),
                    "required_route": "Pipeline -> strategy -> trend_analysis -> generation -> validate_kuaishou_auto_packet -> uploader -> management_postcheck",
                },
                ensure_ascii=False,
            )
        )
        return 2

    packet = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = validate_kuaishou_auto_packet(packet)
    if not result.get("passed"):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "kuaishou_auto_workflow_gate_failed",
                    "failed_dimensions": result.get("failed_dimensions", []),
                    "validator": "content_platform.media_quality.validate_kuaishou_auto_packet",
                },
                ensure_ascii=False,
            )
        )
        return 2

    if not args.allow_legacy_handoff:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "legacy_generation_disabled",
                    "message": "Manifest passed validation, but direct legacy generation/upload is disabled. Use the standard Pipeline publisher and management-page postcheck.",
                },
                ensure_ascii=False,
            )
        )
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "status": "validated_for_standard_pipeline_handoff",
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
