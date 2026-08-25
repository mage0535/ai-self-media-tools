import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import deploy_release as deploy_release_module
from scripts.deploy_release import deploy_release, rollback_release


CURRENT = "%h/.ai-self-media-tools-current"
MUTABLE = "%h/.ai-self-media-tools"


def _systemd_result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


class FakeSystemd:
    def __init__(self, systemd_dir: Path):
        self.systemd_dir = systemd_dir
        self.commands = []
        self.enabled = {}
        self.active = {}

    def __call__(self, argv):
        self.commands.append(list(argv))
        operation = argv[2]
        if operation == "is-active":
            return _systemd_result(0 if self.active.get(argv[3], False) else 3, "active\n" if self.active.get(argv[3], False) else "inactive\n")
        if operation == "is-enabled":
            return _systemd_result(0 if self.enabled.get(argv[3], False) else 1, "enabled\n" if self.enabled.get(argv[3], False) else "disabled\n")
        if operation == "show":
            unit = self.systemd_dir / argv[3]
            text = unit.read_text(encoding="utf-8")
            return _systemd_result(
                stdout="\n".join(
                    [
                        next(line for line in text.splitlines() if line.startswith("ExecStart=")),
                        next(line for line in text.splitlines() if line.startswith("WorkingDirectory=")),
                        "Environment=" + " ".join(line.removeprefix("Environment=") for line in text.splitlines() if line.startswith("Environment=")),
                    ]
                )
                + "\n"
            )
        return _systemd_result()


def test_all_service_templates_use_current_code_root_and_mutable_runtime_roots():
    for path in sorted(Path("systemd").glob("*.service")):
        text = path.read_text(encoding="utf-8")
        assert f"WorkingDirectory={CURRENT}" in text, path
        assert f"Environment=CONTENT_PLATFORM_HOME={CURRENT}" in text, path
        lines = text.splitlines()
        assert f"WorkingDirectory={MUTABLE}" not in lines, path
        assert f"Environment=CONTENT_PLATFORM_HOME={MUTABLE}" not in lines, path
        assert f"Environment=PYTHONPATH={MUTABLE}" not in lines, path
        assert f"ExecStart=/bin/bash {MUTABLE}/scripts/" not in text, path
        assert f"ExecStart=/usr/bin/python3 {MUTABLE}/scripts/" not in text, path


def test_deploy_installs_units_disables_timers_before_switch_and_verifies_effective_paths(tmp_path, monkeypatch):
    from tests.test_deploy_release import _case, _fixture_evidence_runner

    source, config, report, rollback = _case(tmp_path)
    systemd_dir = tmp_path / "systemd-user"
    fake = FakeSystemd(systemd_dir)
    fake.enabled["hermes-content-platform.timer"] = True
    events = []
    original_activate = deploy_release_module._activate

    def record_activate(current, release):
        events.append("switch")
        fake.commands.append(["SWITCH"])
        return original_activate(current, release)

    monkeypatch.setattr(deploy_release_module, "_activate", record_activate)
    result = deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current",
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=tmp_path / "data",
        release_name="systemd-good",
        secrets_root=tmp_path / "secrets",
        evidence_runner=_fixture_evidence_runner,
        systemd_unit_dir=systemd_dir,
        systemd_runner=fake,
    )

    daemon_reload = next(i for i, command in enumerate(fake.commands) if command[2] == "daemon-reload")
    disabled = [i for i, command in enumerate(fake.commands) if command[2:4] == ["disable", "--now"]]
    switch = next(i for i, command in enumerate(fake.commands) if command == ["SWITCH"])
    assert disabled
    assert events
    assert max(disabled) < switch
    assert min(disabled) < daemon_reload
    assert (systemd_dir / "hermes-content-platform.service").is_file()
    assert result["systemd"]["verified"] is True
    assert any(len(command) > 2 and command[2] == "enable" for command in fake.commands)


def test_rollback_reverses_current_and_reverifies_units_without_touching_mutable_data(tmp_path):
    from tests.test_deploy_release import _case, _fixture_evidence_runner

    source, config, report, rollback = _case(tmp_path)
    data = tmp_path / "data"
    secrets = tmp_path / "secrets"
    current = tmp_path / ".ai-self-media-tools-current"
    systemd_dir = tmp_path / "systemd-user"
    fake = FakeSystemd(systemd_dir)
    deployed = deploy_release(
        source_root=source,
        releases_root=tmp_path / "releases",
        current_link=current,
        config_path=config,
        test_report_path=report,
        rollback_target=rollback,
        data_root=data,
        release_name="rollback-good",
        secrets_root=secrets,
        evidence_runner=_fixture_evidence_runner,
        systemd_unit_dir=systemd_dir,
        systemd_runner=fake,
    )
    protected = {
        data / "state.db": b"db",
        data / "cookies.json": b"cookies",
        data / "media" / "final.mp4": b"media",
    }
    for path, value in protected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    result = rollback_release(
        target_release=deployed["release_root"],
        current_link=current,
        data_root=data,
        secrets_root=secrets,
        systemd_unit_dir=systemd_dir,
        systemd_runner=fake,
    )

    assert result["systemd"]["verified"] is True
    assert current.resolve() == Path(deployed["release_root"]).resolve()
    assert {path: path.read_bytes() for path in protected} == protected
    assert any(command[2] == "show" for command in fake.commands)


def test_acceptance_queries_real_timer_state(monkeypatch):
    from scripts.task9_deployment_acceptance import query_timer_states

    def fake(argv):
        if argv[2] == "is-active":
            return _systemd_result(3, "inactive\n")
        assert argv[:3] == ["systemctl", "--user", "is-enabled"]
        enabled = argv[3] == "hermes-content-platform.timer"
        return _systemd_result(0 if enabled else 1, "enabled\n" if enabled else "disabled\n")

    states = query_timer_states(
        timer_names=["hermes-content-platform.timer", "hermes-content-platform-maintenance.timer"],
        systemd_runner=fake,
    )

    assert states["hermes-content-platform.timer"]["enabled"] is True
    assert states["hermes-content-platform-maintenance.timer"]["enabled"] is False


def test_deploy_restores_unit_files_symlink_states_and_data_after_fault(tmp_path):
    from tests.test_deploy_release import _case, _fixture_evidence_runner

    source, config, report, rollback = _case(tmp_path)
    systemd_dir = tmp_path / "systemd-user"
    systemd_dir.mkdir()
    old_service = b"[Service]\nExecStart=/old/service\n"
    old_timer = b"[Timer]\nOnCalendar=*-*-* 01:00:00\n"
    old_timer_target = tmp_path / "old-timer.target"
    old_timer_target.write_bytes(old_timer)
    (systemd_dir / "hermes-content-platform.service").write_bytes(old_service)
    (systemd_dir / "hermes-content-platform.timer").symlink_to(old_timer_target)
    old_release = tmp_path / "old-release"
    old_release.mkdir()
    current = tmp_path / ".ai-self-media-tools-current"
    current.symlink_to(old_release, target_is_directory=True)
    data = tmp_path / "data"
    protected = data / "state.db"
    protected.parent.mkdir(exist_ok=True)
    protected.write_bytes(b"mutable-state")

    fake = FakeSystemd(systemd_dir)
    fake.enabled["hermes-content-platform.service"] = True
    fake.enabled["hermes-content-platform.timer"] = True
    fake.active["hermes-content-platform.service"] = True

    def fail_on_effective_unit(argv):
        result = fake(argv)
        if argv[2] == "show":
            raise RuntimeError("injected effective-unit failure")
        return result

    with pytest.raises(RuntimeError, match="injected effective-unit failure"):
        deploy_release(
            source_root=source,
            releases_root=tmp_path / "releases",
            current_link=current,
            config_path=config,
            test_report_path=report,
            rollback_target=rollback,
            data_root=data,
            release_name="fault-injected",
            secrets_root=tmp_path / "secrets",
            evidence_runner=_fixture_evidence_runner,
            systemd_unit_dir=systemd_dir,
            systemd_runner=fail_on_effective_unit,
        )

    assert (systemd_dir / "hermes-content-platform.service").read_bytes() == old_service
    assert (systemd_dir / "hermes-content-platform.timer").is_symlink()
    assert (systemd_dir / "hermes-content-platform.timer").resolve() == old_timer_target.resolve()
    assert old_timer_target.read_bytes() == old_timer
    assert current.resolve() == old_release
    assert protected.read_bytes() == b"mutable-state"
    assert any(command[2] == "daemon-reload" for command in fake.commands)
    assert any(command[2:4] == ["enable", "--now"] for command in fake.commands)
