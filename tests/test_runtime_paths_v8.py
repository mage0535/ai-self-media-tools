import json
from pathlib import Path

import pytest

from content_platform import mcp_server
from content_platform.runtime_paths import resolve_runtime_paths


def test_explicit_runtime_roots_override_release_home(tmp_path, monkeypatch):
    code = tmp_path / "release"
    data = tmp_path / "mutable-data"
    secrets = tmp_path / "private-secrets"
    config = tmp_path / "private-config.json"
    config.write_text(json.dumps({"data_dir": "/legacy/release/data", "media": {"image": {"enabled": True}}}), encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(code))
    monkeypatch.setenv("CONTENT_PLATFORM_CODE_ROOT", str(code))
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(config))
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(data))
    monkeypatch.setenv("CONTENT_PLATFORM_SECRETS_DIR", str(secrets))

    paths = resolve_runtime_paths()
    loaded = mcp_server._load_config(str(paths.database))

    assert paths.code_root == code
    assert paths.config == config
    assert paths.data_root == data
    assert paths.database == data / "state.db"
    assert loaded["data_dir"] == str(data)
    assert loaded["media"]["image"]["enabled"] is True


def test_production_runtime_rejects_missing_private_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path / "release"))
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(tmp_path / "missing-config.json"))
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(tmp_path / "data"))

    with pytest.raises(RuntimeError, match="production config is missing"):
        resolve_runtime_paths()


def test_mcp_database_never_uses_release_local_data_when_data_root_is_explicit(tmp_path, monkeypatch):
    release = tmp_path / "immutable-release"
    mutable = tmp_path / "mutable"
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(release))
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(mutable))

    assert Path(mcp_server._get_db_path()) == mutable / "state.db"
