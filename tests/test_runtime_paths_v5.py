import json
from pathlib import Path

from content_platform.cli import load_config


def test_environment_data_dir_overrides_legacy_config_path(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"data_dir": "/root/.ai-self-media-tools-releases/aebd7a9/data", "media": {"video": {"script": "/root/.ai-self-media-tools-releases/aebd7a9/scripts/video_toolchain_runner.py"}}}), encoding="utf-8")
    runtime_data = tmp_path / "runtime-data"
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(runtime_data))
    result = load_config(str(config_path), str(runtime_data / "state.db"))
    assert result["data_dir"] == str(runtime_data)
    assert "aebd7a9" not in json.dumps(result)


def test_load_config_uses_db_parent_when_no_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTENT_PLATFORM_DATA_DIR", raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"publishers": {}}), encoding="utf-8")
    runtime_data = tmp_path / "runtime-data"
    result = load_config(str(config_path), str(runtime_data / "state.db"))
    assert result["data_dir"] == str(runtime_data)


def test_overnight_entrypoint_uses_external_runtime_roots():
    script = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")
    assert 'data_root="${CONTENT_PLATFORM_DATA_DIR:-$root/data}"' in script
    assert 'secrets_root="${CONTENT_PLATFORM_SECRETS_DIR:-$root/secrets}"' in script
    assert 'out="$data_root/overnight/$day"' in script


def test_supervisor_entrypoint_uses_external_runtime_roots():
    script = Path("scripts/run_overnight_supervisor.sh").read_text(encoding="utf-8")
    assert "data_root=\"${CONTENT_PLATFORM_DATA_DIR:-$root/data}\"" in script
    assert "out=\"$data_root/overnight/$day\"" in script
