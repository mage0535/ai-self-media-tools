import json
from pathlib import Path

import pytest

from content_platform.generator import DraftGenerator, GenerationTimeoutError


class FakeProcess:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.returncode = None
        self.stdout = ""
        self.stderr = ""
        self.terminated = False

    def poll(self):
        try:
            state = next(self.outcomes)
        except StopIteration:
            state = (0, '{"title":"T","body":"' + 'body ' * 80 + '"}')
        if state is None:
            return None
        self.returncode, self.stdout = state
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def communicate(self):
        return self.stdout, self.stderr


def test_hermes_command_uses_active_model_and_retries_hard_timeout_once(monkeypatch, tmp_path):
    clock = iter([0, 421, 421, 421, 421])
    processes = [FakeProcess([None]), FakeProcess([(0, '{"title":"T","body":"' + 'body ' * 80 + '"}')])]
    commands = []

    def popen(command, **kwargs):
        commands.append(command)
        return processes.pop(0)

    monkeypatch.setattr("content_platform.generator.subprocess.Popen", popen)
    generator = DraftGenerator({"provider": "hermes-cli", "checkpoint_dir": str(tmp_path), "clock": lambda: next(clock), "sleep": lambda _: None})
    generator._normalize = lambda draft, context, provider, topic, brief: draft
    brief = {
        "platform": "wechat",
        "content_blueprint": {"topic": "topic", "background": "x" * 5000},
        "claim_ledger": [{"claim": "y" * 5000, "evidence_path": "e"}],
        "compiled_skill_rules": {"rules": [{"id": f"r{i}", "text": "z" * 1000} for i in range(30)]},
    }
    result = generator._hermes("topic", brief, {"language": "zh", "platform_rules": ""})
    assert result["title"] == "T"
    assert all("--provider" not in commands[0] and "--model" not in commands[0] for _ in [0])
    assert commands[0][-1] == "--cli"
    assert len(commands) == 2
    checkpoint = next(tmp_path.glob("*checkpoint*.json"))
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["status"] == "hard_timeout"


def test_non_transient_error_is_not_retried(monkeypatch, tmp_path):
    calls = []

    class ErrorProcess(FakeProcess):
        def poll(self):
            self.returncode, self.stdout = 1, "permission denied"
            return 1

    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: (calls.append(1) or ErrorProcess([])))
    generator = DraftGenerator({"provider": "hermes-cli", "checkpoint_dir": str(tmp_path), "clock": lambda: 0, "sleep": lambda _: None})
    generator._normalize = lambda draft, context, provider, topic, brief: draft
    with pytest.raises(RuntimeError, match="Hermes generation command failed"):
        generator._hermes("topic", {"platform": "wechat", "content_blueprint": {"topic": "topic"}}, {"language": "zh", "platform_rules": ""})
    assert len(calls) == 1


def test_transient_provider_error_retries_once_with_reduced_context(monkeypatch, tmp_path):
    commands = []
    outputs = [FakeProcess([(1, "HTTP 503 unavailable")]), FakeProcess([(0, '{"title":"T","body":"' + 'body ' * 80 + '"}')])]
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda command, **kwargs: (commands.append(command) or outputs.pop(0)))
    generator = DraftGenerator({"provider": "hermes-cli", "checkpoint_dir": str(tmp_path), "clock": lambda: 0, "sleep": lambda _: None})
    generator._normalize = lambda draft, context, provider, topic, brief: draft
    brief = {
        "platform": "wechat",
        "content_blueprint": {"topic": "topic", "background": "x" * 5000},
        "claim_ledger": [{"claim": "y" * 5000, "evidence_path": "e"}],
        "compiled_skill_rules": {"rules": [{"id": f"r{i}", "text": "z" * 1000} for i in range(30)]},
    }
    result = generator._hermes("topic", brief, {"language": "zh", "platform_rules": ""})
    assert result["title"] == "T"
    assert len(commands) == 2
    assert len(commands[1][2]) < len(commands[0][2])


def test_checkpoint_is_atomic_and_recovery_has_evidence(tmp_path):
    generator = DraftGenerator({"checkpoint_dir": str(tmp_path)})
    path = generator._write_generation_checkpoint({"attempt": 1, "status": "hard_timeout"})
    assert path.is_file()
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "hard_timeout"
