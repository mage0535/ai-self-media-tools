import json
from pathlib import Path

import pytest

from content_platform.generator import DraftGenerator, GenerationTimeoutError


class FakeProcess:
    def __init__(self, outcomes, *, terminate_exits=True, kill_exits=True, events=None):
        self.outcomes = iter(outcomes)
        self.returncode = None
        self.stdout = ""
        self.stderr = ""
        self.terminated = False
        self.killed = False
        self.terminate_exits = terminate_exits
        self.kill_exits = kill_exits
        self.events = events if events is not None else []

    def poll(self):
        if self.terminated and self.terminate_exits:
            self.returncode = -15
            return self.returncode
        if self.killed and self.kill_exits:
            self.returncode = -9
            return self.returncode
        try:
            state = next(self.outcomes)
        except StopIteration:
            state = (0, '{"title":"T","body":"' + 'body ' * 80 + '"}')
        if state is None:
            return None
        self.returncode, self.stdout = state
        return self.returncode

    def terminate(self):
        self.events.append("terminate")
        self.terminated = True

    def kill(self):
        self.events.append("kill")
        self.killed = True
        self.terminated = True

    def wait(self, timeout=None):
        self.events.append(("wait", timeout))
        if self.poll() is None:
            raise __import__("subprocess").TimeoutExpired("fake", timeout)
        return self.returncode

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
    generator = DraftGenerator({"provider": "hermes-cli", "checkpoint_dir": str(tmp_path), "generation_attempts_path": str(tmp_path / "generation_attempts.json"), "clock": lambda: next(clock), "sleep": lambda _: None})
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
    attempts = json.loads((tmp_path / "generation_attempts.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in attempts] == ["hard_timeout", "success"]
    assert all("prompt" not in row for row in attempts)


def test_canary_command_uses_verified_dynamic_selectors_and_records_identity(monkeypatch, tmp_path):
    process = FakeProcess([(0, '{"title":"T","body":"body " * 80}')])
    commands = []

    monkeypatch.setenv("HERMES_CANARY_SESSION", "task9-active-session")
    monkeypatch.setenv("HERMES_PROVIDER", "active-provider")
    monkeypatch.setenv("HERMES_MODEL", "active-model")
    monkeypatch.setenv("HERMES_CANARY_SELECTOR_CAPABILITY", "verified")
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda command, **kwargs: (commands.append(command) or process))
    attempts_path = tmp_path / "generation_attempts.json"
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(attempts_path), "clock": lambda: 0, "sleep": lambda _: None,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    result = generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})

    assert result["title"] == "T"
    assert commands[0][-4:] == ["--provider", "active-provider", "--model", "active-model"]
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    assert attempts[-1]["provider"] == "active-provider"
    assert attempts[-1]["model"] == "active-model"
    assert attempts[-1]["session_id"] == "task9-active-session"


def test_automated_workflow_prompt_forbids_unsupported_claim_patterns(monkeypatch, tmp_path):
    process = FakeProcess([(0, '{"title":"T","body":"Use verified steps only. "}')])
    commands = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda command, **kwargs: (commands.append(command) or process))
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "clock": lambda: 0, "sleep": lambda _: None,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    generator._hermes(
        "topic",
        {"platform": "kuaishou", "automated_workflow": True, "claim_ledger": []},
        {"language": "zh", "platform_rules": ""},
    )

    prompt = commands[0][2]
    assert "friend/customer anecdotes" in prompt
    assert "Do not claim free, no-code, all-in-one" in prompt
    assert "exact claim appears in claim_ledger" in prompt


def test_factual_repair_prompt_requires_complete_evidence_safe_rewrite(monkeypatch, tmp_path):
    process = FakeProcess([(0, '{"title":"T","body":"Use neutral verified steps only. "}')])
    commands = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda command, **kwargs: (commands.append(command) or process))
    generator = DraftGenerator({"provider": "hermes-cli", "checkpoint_dir": str(tmp_path), "clock": lambda: 0, "sleep": lambda _: None})
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    generator._hermes("topic", {"platform": "kuaishou", "automated_workflow": True, "factual_repair": {"failures": ["unsourced_numeric_claim"]}}, {"language": "zh", "platform_rules": ""})

    assert "single factual-repair attempt" in commands[0][2]
    assert "Rewrite the complete draft from scratch" in commands[0][2]


def test_canary_without_verified_selectors_fails_before_launch(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("HERMES_CANARY_SESSION", "task9-missing-selector-proof")
    monkeypatch.delenv("HERMES_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_MODEL", raising=False)
    monkeypatch.delenv("HERMES_CANARY_SELECTOR_CAPABILITY", raising=False)
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *args, **kwargs: calls.append(1))
    generator = DraftGenerator({"provider": "hermes-cli", "checkpoint_dir": str(tmp_path)})

    with pytest.raises(RuntimeError, match="selectors are not verified"):
        generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})
    assert calls == []


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


def test_permission_error_is_persisted_as_non_transient_and_not_retried(monkeypatch, tmp_path):
    process = FakeProcess([(1, "permission denied")])
    calls = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: (calls.append(1) or process))
    attempts_path = tmp_path / "generation_attempts.json"
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(attempts_path), "clock": lambda: 10, "sleep": lambda _: None,
    })

    with pytest.raises(RuntimeError, match="Hermes generation command failed"):
        generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})
    assert len(calls) == 1
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    assert attempts[-1]["status"] == "provider_error"
    assert attempts[-1]["error_class"] == "permission_denied"


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
        "compiled_skill_rules": {"rules": [{"id": f"r{i}", "text": f"z{i}" * 500} for i in range(30)]},
    }
    result = generator._hermes("topic", brief, {"language": "zh", "platform_rules": ""})
    assert result["title"] == "T"
    assert len(commands) == 2
    assert len(commands[1][2]) < len(commands[0][2])


def test_exit_zero_http503_is_persisted_as_transient_and_retries(monkeypatch, tmp_path):
    output = '{"title":"T","body":"' + "body " * 80 + '"}'
    processes = [FakeProcess([(0, "HTTP 503 unavailable")]), FakeProcess([(0, output)])]
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: processes.pop(0))
    attempts_path = tmp_path / "generation_attempts.json"
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(attempts_path), "clock": lambda: 10, "sleep": lambda _: None,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    assert generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})["title"] == "T"
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    assert [(row["attempt"], row["status"], row["error_class"]) for row in attempts] == [
        (1, "transient_provider_error", "provider_5xx"), (2, "success", "")
    ]
    checkpoint = json.loads((tmp_path / "generation_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "success"
    assert [(row["attempt"], row["error_class"]) for row in checkpoint["transitions"]] == [
        (1, "provider_5xx"), (2, "")
    ]


def test_exit_zero_http429_is_transient_and_retries_with_attempt_evidence(monkeypatch, tmp_path):
    output = '{"title":"T","body":"' + "body " * 80 + '"}'
    processes = [FakeProcess([(0, "HTTP 429 rate limit")]), FakeProcess([(0, output)])]
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: processes.pop(0))
    attempts_path = tmp_path / "generation_attempts.json"
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(attempts_path), "clock": lambda: 10, "sleep": lambda _: None,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    assert attempts[0]["status"] == "transient_provider_error"
    assert attempts[0]["error_class"] == "provider_429"
    assert attempts[0]["prompt_hash"] and attempts[0]["prompt_length"] > 0
    assert attempts[0]["started_at"] == attempts[0]["finished_at"] == 10


def test_invalid_json_is_persisted_and_not_retried(monkeypatch, tmp_path):
    process = FakeProcess([(0, "not json")])
    calls = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: (calls.append(1) or process))
    attempts_path = tmp_path / "generation_attempts.json"
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(attempts_path), "clock": lambda: 10, "sleep": lambda _: None,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    with pytest.raises(ValueError, match="non-JSON"):
        generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})
    assert len(calls) == 1
    attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
    assert attempts[-1]["status"] == "provider_error"
    assert attempts[-1]["error_class"] == "invalid_json"


def test_checkpoint_is_atomic_and_recovery_has_evidence(tmp_path):
    generator = DraftGenerator({"checkpoint_dir": str(tmp_path)})
    path = generator._write_generation_checkpoint({"attempt": 1, "status": "hard_timeout"})
    assert path.is_file()
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "hard_timeout"


def test_each_generation_checkpoint_has_uniform_safe_attempt_fields(monkeypatch, tmp_path):
    checkpoints = []
    output = '{"title":"T","body":"' + "body " * 80 + '"}'
    process = FakeProcess([(0, output)])
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: process)
    generator = DraftGenerator({"provider": "hermes-cli", "checkpoint_dir": str(tmp_path), "clock": lambda: 10, "sleep": lambda _: None})
    generator._write_generation_checkpoint = lambda payload: checkpoints.append(payload)
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})

    assert checkpoints[-1]["status"] == "success"
    assert set(("attempt", "status", "prompt_hash", "prompt_length", "error_class", "started_at", "finished_at")) <= checkpoints[-1].keys()
    assert "prompt" not in checkpoints[-1]
    assert all("secret" not in json.dumps(item).casefold() for item in checkpoints)


def test_soft_deadline_writes_bounded_periodic_heartbeats_until_success(monkeypatch, tmp_path):
    class FakeClock:
        # A non-zero monotonic origin catches relative/absolute clock mixing.
        now = 10000

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    fake_clock = FakeClock()
    process = FakeProcess([None, None, None, None, None, (0, '{"title":"T","body":"body"}')])
    checkpoints = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: process)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "clock": fake_clock.time, "sleep": lambda _: fake_clock.sleep(1),
        "soft_deadline": 1, "heartbeat_interval": 2, "hard_deadline": 10,
    })
    generator._write_generation_checkpoint = lambda payload: checkpoints.append(payload)
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    result = generator._hermes_attempt(
        "topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""},
        retry=False, language_instruction="", factual_boundary="", body_requirement="", style_limit=100,
    )

    heartbeat_rows = [row for row in checkpoints if row["status"] == "running_after_soft_deadline"]
    assert result["title"] == "T"
    assert len(heartbeat_rows) >= 2
    assert all(row["error_class"] == "soft_deadline" for row in heartbeat_rows)
    assert all(row["attempt"] == 1 and row["prompt_length"] > 0 for row in heartbeat_rows)
    assert [row["heartbeat_at"] for row in heartbeat_rows] == sorted(row["heartbeat_at"] for row in heartbeat_rows)
    assert checkpoints[-1]["status"] == "success"


def test_hermes_launch_uses_files_and_an_isolated_process_group(monkeypatch, tmp_path):
    process = FakeProcess([(0, '{"title":"T","body":"body"}')])
    launch = {}

    def popen(command, **kwargs):
        launch.update(kwargs)
        return process

    monkeypatch.setattr("content_platform.generator.subprocess.Popen", popen)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "clock": lambda: 10, "sleep": lambda _: None,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    generator._hermes("topic", {"platform": "wechat"}, {
        "language": "zh", "platform_rules": "中文规则" * 5000,
        "hook_samples": "中文钩子" * 5000,
    })

    assert launch["stdout"] is not __import__("subprocess").PIPE
    assert launch["stderr"] is not __import__("subprocess").PIPE
    if __import__("os").name == "nt":
        assert launch["creationflags"] & __import__("subprocess").CREATE_NEW_PROCESS_GROUP
    else:
        assert launch["start_new_session"] is True


def test_final_hermes_prompt_obeys_utf8_stage_payload_budget(monkeypatch, tmp_path):
    process = FakeProcess([(0, '{"title":"T","body":"body"}')])
    commands = []
    monkeypatch.setattr(
        "content_platform.generator.subprocess.Popen",
        lambda command, **kwargs: (commands.append(command) or process),
    )
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "clock": lambda: 10, "sleep": lambda _: None,
        "stage_payload_bytes": 16384,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    generator._hermes("topic", {
        "platform": "wechat",
        "content_blueprint": {f"section_{index}": "中文蓝图" * 500 for index in range(12)},
    }, {
        "language": "zh", "platform_rules": "中文规则" * 5000,
        "hook_samples": "中文钩子" * 5000,
    })

    prompt = commands[0][commands[0].index("-z") + 1]
    assert len(prompt.encode("utf-8")) <= 16384


def test_posix_timeout_terminates_the_isolated_process_group(monkeypatch):
    class GroupProcess:
        pid = 4321

        def wait(self, timeout=None):
            return 0

    signals = []
    monkeypatch.setattr(
        __import__("content_platform.generator", fromlist=["os"]).os,
        "killpg", lambda pid, sent_signal: signals.append((pid, sent_signal)),
        raising=False,
    )

    generator = DraftGenerator({"termination_grace": 1})
    generator._platform_name = lambda: "posix"
    generator._terminate_generation_process(GroupProcess())

    assert signals == [(4321, __import__("signal").SIGTERM)]


def test_verbose_hermes_output_is_stopped_at_the_combined_file_limit(monkeypatch, tmp_path):
    class VerboseProcess:
        returncode = None
        pid = None
        terminated = False

        def __init__(self, stdout_file, stderr_file):
            self.stdout_file = stdout_file
            self.stderr_file = stderr_file

        def poll(self):
            if self.terminated:
                self.returncode = -15
                return self.returncode
            self.stdout_file.write(b"x" * 700)
            self.stderr_file.write(b"y" * 700)
            self.stdout_file.flush()
            self.stderr_file.flush()
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.returncode = -15
            return self.returncode

    def popen(command, **kwargs):
        return VerboseProcess(kwargs["stdout"], kwargs["stderr"])

    monkeypatch.setattr("content_platform.generator.subprocess.Popen", popen)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(tmp_path / "attempts.json"),
        "clock": lambda: 10, "sleep": lambda _: None,
    })
    brief = {
        "platform": "wechat",
        "run_contract": {"bounds": {"provider_response_bytes": 1024}},
    }

    with pytest.raises(ValueError, match="output exceeds 1024 bytes"):
        generator._hermes("topic", brief, {"language": "zh", "platform_rules": ""})

    checkpoint = json.loads((tmp_path / "generation_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["error_class"] == "provider_output_limit"


def test_exited_oversized_hermes_output_records_a_terminal_checkpoint(monkeypatch, tmp_path):
    class ExitedVerboseProcess:
        returncode = 0

        def poll(self):
            return self.returncode

    def popen(command, **kwargs):
        kwargs["stdout"].write(b"x" * 700)
        kwargs["stderr"].write(b"y" * 700)
        return ExitedVerboseProcess()

    monkeypatch.setattr("content_platform.generator.subprocess.Popen", popen)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(tmp_path / "attempts.json"),
        "clock": lambda: 10, "sleep": lambda _: None,
    })

    with pytest.raises(ValueError, match="output exceeds 1024 bytes"):
        generator._hermes("topic", {
            "platform": "wechat",
            "run_contract": {"bounds": {"provider_response_bytes": 1024}},
        }, {"language": "zh", "platform_rules": ""})

    checkpoint = json.loads((tmp_path / "generation_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "provider_error"
    assert checkpoint["error_class"] == "provider_output_limit"


def test_hard_timeout_stops_heartbeats_and_terminates_process(monkeypatch, tmp_path):
    class FakeClock:
        now = 0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    fake_clock = FakeClock()
    process = FakeProcess([None] * 20)
    checkpoints = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: process)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "clock": fake_clock.time, "sleep": lambda _: fake_clock.sleep(1),
        "soft_deadline": 1, "heartbeat_interval": 2, "hard_deadline": 5,
    })
    generator._write_generation_checkpoint = lambda payload: checkpoints.append(payload)

    with pytest.raises(GenerationTimeoutError):
        generator._hermes_attempt(
            "topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""},
            retry=False, language_instruction="", factual_boundary="", body_requirement="", style_limit=100,
        )

    assert process.terminated
    assert checkpoints[-1]["status"] == "hard_timeout"
    assert len([row for row in checkpoints if row["status"] == "running_after_soft_deadline"]) == 2


@pytest.mark.parametrize(
    ("process", "grace", "expected_events"),
    [
        (FakeProcess([None] * 20), 5, ["terminate", ("wait", 5)]),
        (FakeProcess([None] * 20, terminate_exits=False), 5, ["terminate", ("wait", 5), "kill", ("wait", 5)]),
        (FakeProcess([None] * 20), 7, ["terminate", ("wait", 7)]),
    ],
)
def test_hard_timeout_confirms_exit_before_terminal_checkpoint(monkeypatch, tmp_path, process, grace, expected_events):
    class FakeClock:
        now = 0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    fake_clock = FakeClock()
    checkpoints = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: process)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "clock": fake_clock.time, "sleep": lambda _: fake_clock.sleep(1),
        "soft_deadline": 1, "heartbeat_interval": 2, "hard_deadline": 5,
        **({"termination_grace": grace} if grace != 5 else {}),
    })
    generator._write_generation_checkpoint = lambda payload: checkpoints.append(payload)

    with pytest.raises(GenerationTimeoutError):
        generator._hermes_attempt(
            "topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""},
            retry=False, language_instruction="", factual_boundary="", body_requirement="", style_limit=100,
        )

    assert process.events == expected_events
    assert checkpoints[-1]["status"] == "hard_timeout"


def test_hard_timeout_kill_failure_is_not_retried_and_preserves_checkpoint(monkeypatch, tmp_path):
    class KillFailureProcess(FakeProcess):
        def kill(self):
            self.events.append("kill")
            raise OSError("kill failed")

    process = KillFailureProcess([None] * 20, terminate_exits=False)
    checkpoints = []
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: process)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(tmp_path / "generation_attempts.json"),
        "clock": lambda: 0, "sleep": lambda _: None, "hard_deadline": 0,
    })
    generator._write_generation_checkpoint = lambda payload: checkpoints.append(payload)

    with pytest.raises(RuntimeError, match="process termination failed"):
        generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})

    assert len([item for item in checkpoints if item["status"] == "process_termination_failed"]) == 1
    attempts = json.loads((tmp_path / "generation_attempts.json").read_text(encoding="utf-8"))
    assert attempts[-1]["error_class"] == "process_termination_failed"
    assert len(attempts) == 1


def test_hard_timeout_terminate_failure_is_not_retried(monkeypatch, tmp_path):
    class TerminateFailureProcess(FakeProcess):
        def terminate(self):
            self.events.append("terminate")
            raise OSError("terminate failed")

    process = TerminateFailureProcess([None] * 20)
    monkeypatch.setattr("content_platform.generator.subprocess.Popen", lambda *a, **k: process)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "generation_attempts_path": str(tmp_path / "generation_attempts.json"),
        "clock": lambda: 0, "sleep": lambda _: None, "hard_deadline": 0,
    })

    with pytest.raises(RuntimeError, match="process termination failed"):
        generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})

    attempts = json.loads((tmp_path / "generation_attempts.json").read_text(encoding="utf-8"))
    assert len(attempts) == 1
    assert attempts[0]["error_class"] == "process_termination_failed"


def test_old_process_exit_is_confirmed_before_second_attempt(monkeypatch, tmp_path):
    events = []
    old_process = FakeProcess([None] * 20, terminate_exits=False, events=events)
    new_process = FakeProcess([(0, '{"title":"T","body":"' + 'body ' * 80 + '"}')], events=events)
    processes = [old_process, new_process]

    def popen(*args, **kwargs):
        events.append("popen")
        return processes.pop(0)

    monkeypatch.setattr("content_platform.generator.subprocess.Popen", popen)
    generator = DraftGenerator({
        "provider": "hermes-cli", "checkpoint_dir": str(tmp_path),
        "clock": lambda: 0, "sleep": lambda _: None, "hard_deadline": 0,
    })
    generator._normalize = lambda draft, context, provider, topic, brief: draft

    result = generator._hermes("topic", {"platform": "wechat"}, {"language": "zh", "platform_rules": ""})

    assert result["title"] == "T"
    assert events.index(("wait", 5)) < events.index("popen", 1)
