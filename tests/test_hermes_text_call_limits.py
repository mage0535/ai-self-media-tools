import subprocess

from content_platform import humanizer


def test_humanizer_calls_hermes_without_tools_or_auto_rules(monkeypatch):
    seen = []
    monkeypatch.delenv("CONTENT_PLATFORM_NO_MODEL_CALLS", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda command, **kw: seen.append(command) or subprocess.CompletedProcess(command, 0, "ok", ""))

    assert humanizer._hermes_llm_call("rewrite this") == "ok"
    command = seen[0]
    assert command[command.index("--toolsets") + 1] == "todo" and "--ignore-rules" in command
    assert command.index("--toolsets") < command.index("-z")
