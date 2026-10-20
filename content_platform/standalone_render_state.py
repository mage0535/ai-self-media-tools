"""Fail-closed state marker for legacy standalone renderers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def write_rendered_unverified(output_dir: Path, *, platform: str, renderer: str, final_name: str = "final.mp4") -> dict:
    output_dir = Path(output_dir)
    final_path = output_dir / final_name
    payload = {
        "version": "standalone_render_state_v1",
        "status": "rendered_unverified",
        "publishable": False,
        "delivery_allowed": False,
        "requires_unified_release": True,
        "platform": str(platform),
        "renderer": str(renderer),
        "artifact": str(final_path),
        "artifact_sha256": hashlib.sha256(final_path.read_bytes()).hexdigest() if final_path.is_file() else "",
    }
    (output_dir / "standalone_render_state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload