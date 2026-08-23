"""Rebase runtime-local paths without touching external credentials or services."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


def rebase_runtime_config(config: dict[str, Any], *, data_dir: str | Path, project_root: str | Path) -> dict[str, Any]:
    result = copy.deepcopy(config or {})
    data_dir = Path(data_dir).resolve()
    project_root = Path(project_root).resolve()
    old_data = str(result.get("data_dir") or "")

    def rewrite(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, str):
            return value
        if old_data and (value == old_data or value.startswith(old_data.rstrip("/") + "/")):
            suffix = value[len(old_data):].lstrip("/")
            return str(data_dir / suffix)
        normalized = value.replace("\\", "/")
        marker = "/scripts/"
        if marker in normalized:
            name = normalized.rsplit("/", 1)[-1]
            candidate = project_root / "scripts" / name
            if candidate.is_file():
                return str(candidate)
        return value

    result = rewrite(result)
    result["data_dir"] = str(data_dir)
    return result
