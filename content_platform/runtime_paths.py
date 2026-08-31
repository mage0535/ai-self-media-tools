"""Resolve immutable code and private mutable runtime roots from one contract."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    code_root: Path
    config: Path
    data_root: Path
    secrets_root: Path
    database: Path
    production: bool


def resolve_runtime_paths() -> RuntimePaths:
    home = Path(os.environ.get("CONTENT_PLATFORM_HOME") or Path.home() / ".ai-self-media-tools").expanduser()
    code_root = Path(os.environ.get("CONTENT_PLATFORM_CODE_ROOT") or home).expanduser()
    data_root = Path(os.environ.get("CONTENT_PLATFORM_DATA_DIR") or home / "data").expanduser()
    secrets_root = Path(os.environ.get("CONTENT_PLATFORM_SECRETS_DIR") or home / "secrets").expanduser()
    config = Path(os.environ.get("CONTENT_PLATFORM_CONFIG") or home / "config.json").expanduser()
    database = Path(os.environ.get("CONTENT_PLATFORM_DB") or data_root / "state.db").expanduser()
    production = str(os.environ.get("CONTENT_PLATFORM_RUNTIME_MODE") or "").casefold() == "production"
    if production and not config.is_file():
        raise RuntimeError(f"production config is missing: {config}")
    if production and _inside(database, code_root):
        raise RuntimeError("production database must not be stored inside the code release")
    return RuntimePaths(
        code_root=code_root,
        config=config,
        data_root=data_root,
        secrets_root=secrets_root,
        database=database,
        production=production,
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True

