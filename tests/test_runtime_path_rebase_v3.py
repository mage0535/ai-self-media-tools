from pathlib import Path

from content_platform.runtime_paths import rebase_runtime_config


def test_rebase_runtime_config_moves_data_and_project_script_paths(tmp_path: Path):
    script = tmp_path / "scripts" / "video_toolchain_runner.py"
    script.parent.mkdir()
    script.write_text("# script", encoding="utf-8")
    config = {
        "data_dir": "/old/release/data",
        "media": {"video": {"script": "/old/release/scripts/video_toolchain_runner.py"}},
        "publishers": {"default": {"outbox": "/old/release/data/outbox"}},
    }

    result = rebase_runtime_config(config, data_dir=tmp_path / "data", project_root=tmp_path)

    assert result["data_dir"] == str(tmp_path / "data")
    assert result["media"]["video"]["script"] == str(script)
    assert result["publishers"]["default"]["outbox"] == str(tmp_path / "data" / "outbox")


def test_rebase_does_not_rewrite_unknown_external_paths(tmp_path: Path):
    config = {"media": {"video": {"script": "/opt/external/video.py"}}}
    result = rebase_runtime_config(config, data_dir=tmp_path / "data", project_root=tmp_path)
    assert result["media"]["video"]["script"] == "/opt/external/video.py"
