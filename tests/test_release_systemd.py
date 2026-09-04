import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import deploy_release as deploy_release_module
from scripts.deploy_release import _systemd_run, default_systemd_unit_dir, deploy_release, query_systemd_unit_states, rollback_release


CURRENT = "%h/.ai-self-media-tools-current"
MUTABLE = "%h/.ai-self-media-tools"


def _systemd_result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_system_scope_omits_user_bus_flag():
    calls = []

    def runner(argv):
        calls.append(argv)
        return _systemd_result()

    _systemd_run(["daemon-reload"], runner, scope="system")
    assert calls == [["systemctl", "daemon-reload"]]


def test_default_unit_directory_matches_scope():
    assert default_systemd_unit_dir("system") == Path("/etc/systemd/system")
    assert default_systemd_unit_dir("user") == Path.home() / ".config" / "systemd" / "user"
    with pytest.raises(Exception, match="scope"):
        default_systemd_unit_dir("global")


def test_invalid_systemd_scope_fails_before_runner():
    calls = []
    with pytest.raises(Exception, match="scope"):
        query_systemd_unit_states(["worker.service"], runner=lambda argv: calls.append(argv), scope="global")
    assert calls == []


def test_acceptance_queries_system_scope_without_user_flag():
    from scripts.task9_deployment_acceptance import query_timer_states

    calls = []

    def runner(argv):
        calls.append(argv)
        operation = argv[1]
        return _systemd_result(1 if operation == "is-enabled" else 3, "disabled\n" if operation == "is-enabled" else "inactive\n")

    states = query_timer_states(["hermes-content-platform.timer"], systemd_runner=runner, systemd_scope="system")
    assert states["hermes-content-platform.timer"]["enabled"] is False
    assert all(command[:2] != ["systemctl", "--user"] for command in calls)


def test_deploy_and_rollback_propagate_system_scope_to_every_command(tmp_path):
    from tests.test_deploy_release import _case, _fixture_evidence_runner

    source, config, report, rollback = _case(tmp_path)
    systemd_dir = tmp_path / "systemd-system"
    fake = FakeSystemd(systemd_dir)
    commands = []

    def system_runner(argv):
        commands.append(list(argv))
        assert argv[0] == "systemctl"
        assert "--user" not in argv
        return fake([argv[0], "--user", *argv[1:]])

    deployed = deploy_release(
        source_root=source, releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current", config_path=config,
        test_report_path=report, rollback_target=rollback, data_root=tmp_path / "data",
        release_name="system-scope", secrets_root=tmp_path / "secrets",
        evidence_runner=_fixture_evidence_runner, systemd_unit_dir=systemd_dir,
        systemd_runner=system_runner, systemd_scope="system",
    )
    rollback_release(
        target_release=deployed["release_root"], current_link=tmp_path / ".ai-self-media-tools-current",
        data_root=tmp_path / "data", secrets_root=tmp_path / "secrets",
        systemd_unit_dir=systemd_dir, systemd_runner=system_runner, systemd_scope="system",
    )
    assert commands
    assert all("--user" not in command for command in commands)


def test_gateway_runtime_dropin_is_installed_verified_and_preserves_other_dropins(tmp_path):
    release = tmp_path / "release"
    shutil.copytree(Path("systemd"), release / "systemd")
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    unrelated = unit_dir / "hermes-gateway.service.d" / "proxy.conf"
    unrelated.parent.mkdir()
    unrelated.write_text("[Service]\nEnvironment=HTTPS_PROXY=existing\n", encoding="utf-8")
    fake = FakeSystemd(unit_dir)
    fake.active["hermes-gateway.service"] = True

    result = deploy_release_module._systemd_switch(release, unit_dir, fake, scope="user")

    managed = unrelated.parent / "ai-self-media-runtime.conf"
    assert managed.is_file()
    assert "CONTENT_PLATFORM_RUNTIME_MODE=production" in managed.read_text(encoding="utf-8")
    assert unrelated.read_text(encoding="utf-8").endswith("existing\n")
    assert any(command[2:4] == ["restart", "hermes-gateway.service"] for command in fake.commands)
    assert result["gateway_dropin"] == str(managed)


def test_gateway_dropin_and_current_are_restored_after_effective_check_failure(tmp_path):
    release = tmp_path / "release"
    shutil.copytree(Path("systemd"), release / "systemd")
    unit_dir = tmp_path / "units"
    dropin = unit_dir / "hermes-gateway.service.d" / "ai-self-media-runtime.conf"
    dropin.parent.mkdir(parents=True)
    old = b"[Service]\nEnvironment=OLD=1\n"
    dropin.write_bytes(old)
    old_release = tmp_path / "old-release"
    old_release.mkdir()
    current = tmp_path / ".ai-self-media-tools-current"
    current.symlink_to(old_release, target_is_directory=True)
    fake = FakeSystemd(unit_dir)
    fake.active["hermes-gateway.service"] = True

    def fail_gateway_show(argv):
        result = fake(argv)
        if argv[2] == "show" and argv[3] == "hermes-gateway.service":
            home = Path.home().as_posix()
            result.stdout = f"WorkingDirectory={home}/.hermes\nEnvironment=HOME={home}\n"
        return result

    with pytest.raises(Exception, match="gateway|CONTENT_PLATFORM"):
        deploy_release_module._systemd_switch(
            release, unit_dir, fail_gateway_show, activate=deploy_release_module._activate,
            current=current, scope="user",
        )
    assert dropin.read_bytes() == old
    assert current.resolve() == old_release.resolve()


def test_deploy_promotes_candidate_config_before_gateway_restart(tmp_path):
    from tests.test_deploy_release import _case, _fixture_evidence_runner

    source, _, report, rollback = _case(tmp_path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text('{"mode":"candidate"}\n', encoding="utf-8")
    candidate.chmod(0o600)
    active = tmp_path / "runtime" / "config.json"
    active.parent.mkdir()
    active.write_text('{"mode":"old"}\n', encoding="utf-8")
    systemd_dir = tmp_path / "units"
    fake = FakeSystemd(systemd_dir)
    fake.active["hermes-gateway.service"] = True

    def observe(argv):
        if argv[2:4] == ["restart", "hermes-gateway.service"]:
            assert active.read_bytes() == candidate.read_bytes()
        return fake(argv)

    deploy_release(
        source_root=source, releases_root=tmp_path / "releases",
        current_link=tmp_path / ".ai-self-media-tools-current", config_path=candidate,
        active_config_path=active, test_report_path=report, rollback_target=rollback,
        data_root=tmp_path / "data", release_name="promote-config",
        secrets_root=tmp_path / "secrets", evidence_runner=_fixture_evidence_runner,
        systemd_unit_dir=systemd_dir, systemd_runner=observe,
    )
    assert active.read_bytes() == candidate.read_bytes()
    if os.name != "nt":
        assert active.stat().st_mode & 0o777 == 0o600


def test_deploy_restores_active_config_after_gateway_failure(tmp_path):
    from tests.test_deploy_release import _case, _fixture_evidence_runner

    source, _, report, rollback = _case(tmp_path)
    candidate = tmp_path / "candidate.json"
    candidate.write_text('{"mode":"candidate"}\n', encoding="utf-8")
    active = tmp_path / "runtime" / "config.json"
    active.parent.mkdir()
    original = b'{"mode":"old"}\n'
    active.write_bytes(original)
    active.chmod(0o640)
    systemd_dir = tmp_path / "units"
    fake = FakeSystemd(systemd_dir)
    fake.active["hermes-gateway.service"] = True

    def fail_restart(argv):
        if argv[2:4] == ["restart", "hermes-gateway.service"]:
            return _systemd_result(1)
        return fake(argv)

    with pytest.raises(Exception, match="systemd|gateway"):
        deploy_release(
            source_root=source, releases_root=tmp_path / "releases",
            current_link=tmp_path / ".ai-self-media-tools-current", config_path=candidate,
            active_config_path=active, test_report_path=report, rollback_target=rollback,
            data_root=tmp_path / "data", release_name="restore-config",
            secrets_root=tmp_path / "secrets", evidence_runner=_fixture_evidence_runner,
            systemd_unit_dir=systemd_dir, systemd_runner=fail_restart,
        )
    assert active.read_bytes() == original
    if os.name != "nt":
        assert active.stat().st_mode & 0o777 == 0o640


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
            if argv[3] == "hermes-gateway.service":
                dropin = self.systemd_dir / "hermes-gateway.service.d" / "ai-self-media-runtime.conf"
                text = dropin.read_text(encoding="utf-8")
                return _systemd_result(
                    stdout=("Environment=" + " ".join(
                        line.removeprefix("Environment=") for line in text.splitlines() if line.startswith("Environment=")
                    )).replace("%h", Path.home().as_posix()) + "\n"
                )
            unit = self.systemd_dir / argv[3]
            text = unit.read_text(encoding="utf-8")
            return _systemd_result(
                stdout="\n".join(
                    [
                        next(line for line in text.splitlines() if line.startswith("ExecStart=")),
                        next(line for line in text.splitlines() if line.startswith("WorkingDirectory=")),
                        "Environment=" + " ".join(line.removeprefix("Environment=") for line in text.splitlines() if line.startswith("Environment=")),
                    ]
                ).replace("%h", Path.home().as_posix())
                + "\n"
            )
        return _systemd_result()


@pytest.mark.parametrize("bad_field", [None, "CONTENT_PLATFORM_DATA_DIR", "CONTENT_PLATFORM_SECRETS_DIR", "PYTHONPATH", "CONTENT_PLATFORM_CONFIG"])
def test_effective_expanded_paths_require_exact_runtime_roots(tmp_path, bad_field):
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    name = "hermes-content-platform.service"
    template = (Path("systemd") / name).read_text(encoding="utf-8")
    (unit_dir / name).write_text(template, encoding="utf-8")
    home = Path.home().as_posix()
    fake = FakeSystemd(unit_dir)

    def expanded(argv):
        result = fake(argv)
        result.stdout = result.stdout.replace("%h", home)
        if bad_field:
            import re
            result.stdout = re.sub(rf"{bad_field}=([^\s]+)", rf"{bad_field}=\1-stale", result.stdout)
        return result

    if bad_field:
        with pytest.raises(deploy_release_module.ReleaseAuditError, match=bad_field):
            deploy_release_module._verify_effective_systemd_units(tmp_path, unit_dir, [name], expanded)
    else:
        deploy_release_module._verify_effective_systemd_units(tmp_path, unit_dir, [name], expanded)


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
