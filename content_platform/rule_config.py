"""Small helpers for rule feature flags without adding a YAML dependency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def feature_flags(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    flags = dict(config.get("feature_flags") or {})
    path = config.get("feature_flags_file")
    if path:
        flags.update(_read_simple_yaml(Path(path)))
    return flags


def flag_mode(config: dict[str, Any] | None, name: str, default: str = "off") -> str:
    value = feature_flags(config).get(name, default)
    if isinstance(value, bool):
        return "enforce" if value else "off"
    return str(value or default).casefold()


def flag_enabled(config: dict[str, Any] | None, name: str, default: bool = False) -> bool:
    mode = flag_mode(config, name, "on" if default else "off")
    return mode not in {"", "0", "false", "off", "disabled", "no"}


def load_json_config(config: dict[str, Any] | None, key: str, default: Any) -> Any:
    config = config or {}
    inline = config.get(key)
    if inline is not None:
        return inline
    path = config.get(f"{key}_file")
    if not path:
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_simple_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, value = line.strip().split(":", 1)
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value = value.strip()
        if not value:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)
    return result


def _parse_scalar(value: str) -> Any:
    lowered = value.casefold()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value
