"""Build and load immutable, public content-quality assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def compile_content_assets(hooks_path: Path, rules_path: Path, output_dir: Path) -> dict[str, Any]:
    hooks_path = Path(hooks_path)
    rules_path = Path(rules_path)
    output_dir = Path(output_dir)
    hooks = _read(hooks_path)
    rules = _read(rules_path)
    failures = []
    for source in rules.get("sources", []) if isinstance(rules.get("sources"), list) else []:
        if isinstance(source, dict) and str(source.get("license", "")).casefold() == "unverified":
            failures.append(f"unverified_source:{source.get('id', 'unknown')}")
    source_sha256 = hashlib.sha256(
        hooks_path.read_bytes() + b"\n" + rules_path.read_bytes()
    ).hexdigest()
    if failures:
        return {"passed": False, "failures": failures, "source_sha256": source_sha256}
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {"version": "content_assets_v1", "source_sha256": source_sha256}
    (output_dir / "hooks.json").write_text(
        json.dumps({"metadata": metadata, **{k: hooks.get(k, []) for k in ("title", "opening", "ending")}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    structures = rules.get("content_structure_gate", {}).get("structure_pool", [])
    formulas = rules.get("hook_title_gate", {}).get("allowed_hook_families", [])
    (output_dir / "structures.json").write_text(
        json.dumps({"metadata": metadata, "structures": structures}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "formulas.json").write_text(
        json.dumps({"metadata": metadata, "formulas": formulas}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"passed": True, "failures": [], "source_sha256": source_sha256, "output_dir": str(output_dir)}


def load_compiled_assets(asset_dir: Path) -> dict[str, Any]:
    asset_dir = Path(asset_dir)
    hooks = _read(asset_dir / "hooks.json")
    structures = _read(asset_dir / "structures.json")
    formulas = _read(asset_dir / "formulas.json")
    return {"hooks": hooks, "structures": structures, "formulas": formulas}


def select_content_asset_ids(profile: dict[str, Any], assets: dict[str, Any]) -> dict[str, Any]:
    """Choose a small deterministic asset set for the current content format."""
    content_format = str((profile or {}).get("content_format") or "article")
    structures = list((assets.get("structures") or {}).get("structures") or [])
    formulas = list((assets.get("formulas") or {}).get("formulas") or [])
    seed = hashlib.sha256(f"{profile.get('platform','')}:{profile.get('topic','')}:{content_format}".encode()).hexdigest()
    def choose(rows, preference, offset=0):
        if not rows:
            return ""
        if preference in rows:
            return preference
        return rows[(int(seed[offset:offset + 8], 16) + offset) % len(rows)]
    structure_preference = {
        "carousel": "saveable_checklist",
        "short_video": "before_after_test",
        "long_video": "tool_demo",
        "article": "pain_reversal_tutorial",
    }.get(content_format, "pain_reversal_tutorial")
    formula_preference = {
        "carousel": "numbered_checklist",
        "short_video": "result_first",
        "long_video": "before_after_gap",
        "article": "practical_rescue",
    }.get(content_format, "practical_rescue")
    hook_ids = []
    hooks = assets.get("hooks") or {}
    for key in ("title", "opening", "ending"):
        rows = hooks.get(key) if isinstance(hooks.get(key), list) else []
        if rows:
            index = int(seed[16 + len(hook_ids) * 8:24 + len(hook_ids) * 8], 16) % len(rows)
            selected = rows[index]
            if isinstance(selected, dict) and selected.get("id"):
                hook_ids.append(str(selected["id"]))
    return {
        "structure_id": choose(structures, structure_preference, 0),
        "formula_id": choose(formulas, formula_preference, 8),
        "hook_ids": hook_ids,
        "selection_reason": f"format-aware selection for {content_format}",
    }
