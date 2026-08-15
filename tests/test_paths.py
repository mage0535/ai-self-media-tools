from pathlib import Path

from content_platform.paths import agent_scripts_dir


def test_agent_scripts_dir_prefers_explicit_configuration(monkeypatch, tmp_path: Path):
    configured = tmp_path / "agent-scripts"
    monkeypatch.setenv("CONTENT_PLATFORM_AGENT_SCRIPTS_DIR", str(configured))
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "ignored-agent-home"))

    assert agent_scripts_dir() == configured


def test_agent_scripts_dir_uses_agent_home_without_hermes_specific_path(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CONTENT_PLATFORM_AGENT_SCRIPTS_DIR", raising=False)
    monkeypatch.setenv("AGENT_HOME", str(tmp_path / "agent"))
    monkeypatch.delenv("HERMES_HOME", raising=False)

    assert agent_scripts_dir() == tmp_path / "agent" / "scripts"
