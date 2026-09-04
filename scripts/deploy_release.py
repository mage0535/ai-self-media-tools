"""Build, attest, freeze, and atomically activate a versioned runtime release."""

import argparse
import contextlib
import datetime as dt
import json
import hashlib
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime_release_audit import (
    ReleaseAuditError,
    _create_signing_key,
    _git,
    _release_digest,
    _sha256,
    _assert_project_audit,
    _validate_raw_path,
    audit_release,
    verify_metadata,
    write_metadata,
)
from content_platform.cli import load_config
from content_platform.content_policy import validate_delivery_policy_config

CURRENT_LINK_NAME = ".ai-self-media-tools-current"
SYSTEMD_CURRENT_ROOT = "%h/.ai-self-media-tools-current"
SYSTEMD_MUTABLE_ROOT = "%h/.ai-self-media-tools"
SYSTEMD_DATA_ROOT = "%h/.ai-self-media-tools/data"
SYSTEMD_SECRETS_ROOT = "%h/.ai-self-media-tools/secrets"
SYSTEMD_UNIT_PREFIXES = ("ai-self-media", "hermes-content-platform")
GATEWAY_UNIT = "hermes-gateway.service"
GATEWAY_DROPIN_SOURCE = "hermes-gateway-ai-self-media.conf"
GATEWAY_DROPIN_NAME = "ai-self-media-runtime.conf"
MANAGED_RUNTIME_ENVIRONMENT = {
    "CONTENT_PLATFORM_HOME", "CONTENT_PLATFORM_CODE_ROOT", "PYTHONPATH",
    "CONTENT_PLATFORM_DATA_DIR", "CONTENT_PLATFORM_SECRETS_DIR",
    "CONTENT_PLATFORM_CONFIG", "CONTENT_PLATFORM_RUNTIME_MODE",
}


def default_systemd_unit_dir(scope: str = "user") -> Path:
    if scope == "system":
        return Path("/etc/systemd/system")
    if scope == "user":
        return Path.home() / ".config" / "systemd" / "user"
    raise ReleaseAuditError("systemd scope must be 'user' or 'system'")


@contextlib.contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _tracked_paths(source_root: Path) -> list[Path]:
    output = _git(source_root, "ls-files", "-z")
    return [Path(item) for item in output.split("\0") if item]


def _tracked_modes(source_root: Path) -> dict[str, str]:
    output = _git(source_root, "ls-files", "--stage", "-z")
    modes = {}
    for record in output.split("\0"):
        if not record:
            continue
        header, relative = record.split("\t", 1)
        modes[relative] = header.split()[0]
    return modes


def _freeze_release(release_root: Path) -> None:
    for path in sorted(release_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o555)
        elif path.is_file():
            mode = path.stat().st_mode & 0o777
            path.chmod(0o555 if mode & 0o111 else 0o444)
    release_root.chmod(0o555)


def _current_path(current_link: Path | str | None) -> Path:
    current = Path(current_link).expanduser() if current_link is not None else Path.home() / CURRENT_LINK_NAME
    if current.name != CURRENT_LINK_NAME:
        raise ReleaseAuditError(f"current_link must use the systemd runtime root name: {CURRENT_LINK_NAME}")
    return current


def _activate(current_link: Path, release_root: Path) -> None:
    current_link.parent.mkdir(parents=True, exist_ok=True)
    temporary = current_link.parent / f".{current_link.name}.{uuid.uuid4().hex}.tmp"
    try:
        os.symlink(str(release_root), str(temporary), target_is_directory=True)
        try:
            os.replace(temporary, current_link)
        except PermissionError:
            if os.name != "nt" or not current_link.is_symlink():
                raise
            # Windows cannot atomically replace an existing directory symlink.
            current_link.unlink()
            os.replace(temporary, current_link)
    finally:
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()


def _systemd_run(argv: list[str], runner=None, *, allow_failure: bool = False, scope: str = "user"):
    if scope not in {"user", "system"}:
        raise ReleaseAuditError("systemd scope must be 'user' or 'system'")
    command = ["systemctl", *(["--user"] if scope == "user" else []), *argv]
    result = runner(command) if runner is not None else subprocess.run(command, capture_output=True, text=True)
    if result.returncode and not allow_failure:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "")).strip()
        raise ReleaseAuditError(f"systemd command failed ({' '.join(command)}): {detail}")
    return result


def _systemd_unit_paths(release_root: Path) -> tuple[list[Path], list[Path]]:
    unit_root = release_root / "systemd"
    if not unit_root.is_dir():
        raise ReleaseAuditError(f"release systemd directory does not exist: {unit_root}")
    services = sorted(
        path for path in unit_root.glob("*.service") if path.stem.startswith(SYSTEMD_UNIT_PREFIXES)
    )
    timers = sorted(
        path for path in unit_root.glob("*.timer") if path.stem.startswith(SYSTEMD_UNIT_PREFIXES)
    )
    if not services or not timers:
        raise ReleaseAuditError("release systemd units must include at least one service and timer")
    return services, timers


def _validate_systemd_unit(path: Path, text: str) -> None:
    required = (
        f"WorkingDirectory={SYSTEMD_CURRENT_ROOT}",
        f"Environment=CONTENT_PLATFORM_HOME={SYSTEMD_CURRENT_ROOT}",
        f"Environment=CONTENT_PLATFORM_CODE_ROOT={SYSTEMD_CURRENT_ROOT}",
        f"Environment=PYTHONPATH={SYSTEMD_CURRENT_ROOT}",
        f"Environment=CONTENT_PLATFORM_DATA_DIR={SYSTEMD_DATA_ROOT}",
        f"Environment=CONTENT_PLATFORM_SECRETS_DIR={SYSTEMD_SECRETS_ROOT}",
        f"Environment=CONTENT_PLATFORM_CONFIG={SYSTEMD_MUTABLE_ROOT}/config.json",
        "Environment=CONTENT_PLATFORM_RUNTIME_MODE=production",
    )
    missing = [value for value in required if value not in text]
    if missing:
        raise ReleaseAuditError(f"systemd unit {path.name} is missing current release paths: {', '.join(missing)}")
    lines = text.splitlines()
    forbidden = {
        f"WorkingDirectory={SYSTEMD_MUTABLE_ROOT}",
        f"Environment=CONTENT_PLATFORM_HOME={SYSTEMD_MUTABLE_ROOT}",
        f"Environment=PYTHONPATH={SYSTEMD_MUTABLE_ROOT}",
    }
    if any(line in forbidden for line in lines):
        raise ReleaseAuditError(f"systemd unit {path.name} still points code at the mutable runtime root")
    if any(line.startswith("ExecStart=") and f"{SYSTEMD_MUTABLE_ROOT}/scripts/" in line for line in lines):
        raise ReleaseAuditError(f"systemd unit {path.name} still points a script at the mutable runtime root")
    for line in lines:
        if line.startswith("Environment=CONTENT_PLATFORM_DATA_DIR=") or line.startswith("Environment=CONTENT_PLATFORM_SECRETS_DIR="):
            if SYSTEMD_CURRENT_ROOT in line:
                raise ReleaseAuditError(f"systemd unit {path.name} points mutable runtime data at the release root")


def _install_systemd_units(release_root: Path, unit_dir: Path, runner=None, *, scope: str = "user") -> tuple[list[str], list[str]]:
    services, timers = _systemd_unit_paths(release_root)
    unit_dir.mkdir(parents=True, exist_ok=True)
    release_names = {path.name for path in [*services, *timers]}
    for installed in _installed_related_unit_paths(unit_dir):
        if installed.name not in release_names:
            _remove_path(installed)
    for path in [*services, *timers]:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".service":
            _validate_systemd_unit(path, text)
        destination = unit_dir / path.name
        if destination.exists() or destination.is_symlink():
            _remove_path(destination)
        shutil.copy2(path, destination)
        destination.chmod(0o644)
    _systemd_run(["daemon-reload"], runner, scope=scope)
    return [path.name for path in services], [path.name for path in timers]


def _timer_enabled(timer: str, runner=None, *, scope: str = "user") -> bool:
    result = _systemd_run(["is-enabled", timer], runner, allow_failure=True, scope=scope)
    if result.returncode not in (0, 1, 3):
        raise ReleaseAuditError(f"could not inspect systemd timer state: {timer}")
    return result.returncode == 0


def _installed_related_unit_paths(unit_dir: Path) -> list[Path]:
    if not unit_dir.is_dir():
        return []
    return sorted(
        path
        for path in unit_dir.iterdir()
        if (path.is_file() or path.is_symlink())
        and path.suffix in {".service", ".timer"}
        and path.stem.startswith(SYSTEMD_UNIT_PREFIXES)
    )


def _dropin_overrides_runtime(text: str) -> bool:
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(("WorkingDirectory=", "ExecStart=")):
            return True
        if line.startswith("Environment="):
            assignment = line.removeprefix("Environment=").strip().strip('"')
            if assignment.split("=", 1)[0] in MANAGED_RUNTIME_ENVIRONMENT:
                return True
    return False


def _conflicting_project_dropins(unit_dir: Path, service_names: list[str]) -> list[Path]:
    conflicts = []
    for name in service_names:
        root = unit_dir / f"{name}.d"
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.conf")):
            if (path.is_file() or path.is_symlink()) and _dropin_overrides_runtime(path.read_text(encoding="utf-8")):
                conflicts.append(path)
    return conflicts


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _snapshot_unit_file(path: Path) -> dict[str, object]:
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path)}
    if path.is_file():
        return {"kind": "file", "bytes": path.read_bytes(), "mode": path.stat().st_mode & 0o777}
    if path.exists():
        raise ReleaseAuditError(f"related systemd unit is not a file or symlink: {path}")
    return {"kind": "missing"}


def _snapshot_current_link(current: Path | None) -> dict[str, object]:
    if current is None:
        return {"kind": "missing"}
    if current.is_symlink():
        return {"kind": "symlink", "target": os.readlink(current)}
    if current.exists():
        raise ReleaseAuditError(f"current_link is not a symlink: {current}")
    return {"kind": "missing"}


def _snapshot_systemd_transaction(unit_dir: Path, unit_names: list[str], current: Path | None, runner=None, *, scope: str = "user") -> dict:
    unit_dir_exists = unit_dir.is_dir()
    paths = {name: _snapshot_unit_file(unit_dir / name) for name in unit_names}
    return {
        "unit_dir_exists": unit_dir_exists,
        "files": paths,
        "states": query_systemd_unit_states(unit_names, runner=runner, scope=scope),
        "current_link": _snapshot_current_link(current),
    }


def query_systemd_unit_states(unit_names: list[str], runner=None, *, scope: str = "user") -> dict[str, dict[str, object]]:
    states = {}
    for unit in unit_names:
        enabled_result = _systemd_run(["is-enabled", unit], runner, allow_failure=True, scope=scope)
        active_result = _systemd_run(["is-active", unit], runner, allow_failure=True, scope=scope)
        if enabled_result.returncode not in (0, 1, 3, 5) or active_result.returncode not in (0, 1, 3, 5):
            raise ReleaseAuditError(f"could not inspect systemd unit state: {unit}")
        states[unit] = {
            # `systemctl is-enabled` also exits 0 for static/alias units. Only
            # states that represent an explicit enablement may be restored via
            # `systemctl enable`; static services are restored by active state.
            "enabled": (getattr(enabled_result, "stdout", "") or "").strip() in {"enabled", "enabled-runtime"},
            "active": active_result.returncode == 0,
            "enabled_state": (getattr(enabled_result, "stdout", "") or "").strip() or "unknown",
            "active_state": (getattr(active_result, "stdout", "") or "").strip() or "unknown",
        }
    return states


def query_systemd_timer_states(timer_names: list[str], runner=None, *, scope: str = "user") -> dict[str, dict[str, object]]:
    return query_systemd_unit_states(timer_names, runner=runner, scope=scope)


def _disable_systemd_timers(timer_names: list[str], runner=None, *, scope: str = "user") -> None:
    if timer_names:
        _systemd_run(["disable", "--now", *timer_names], runner, scope=scope)


def _restore_systemd_timers(timer_states: dict[str, dict[str, object]], runner=None, *, scope: str = "user") -> None:
    _restore_systemd_states(timer_states, runner=runner, scope=scope)


def _stop_systemd_units(unit_names: list[str], runner=None, *, scope: str = "user") -> None:
    for unit in unit_names:
        _systemd_run(["stop", unit], runner, allow_failure=True, scope=scope)


def _run_state_command(argv: list[str], runner=None, *, allow_missing: bool = False, scope: str = "user") -> None:
    result = _systemd_run(argv, runner, allow_failure=True, scope=scope)
    if result.returncode == 0:
        return
    if allow_missing and result.returncode in (1, 3, 5):
        return
    detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "")).strip()
    raise ReleaseAuditError(f"systemd state restore failed ({' '.join(argv)}): {detail}")


def _restore_systemd_states(states: dict[str, dict[str, object]], runner=None, *, scope: str = "user") -> None:
    for unit in states:
        _run_state_command(["stop", unit], runner, allow_missing=True, scope=scope)
    for unit, state in states.items():
        enabled = bool(state["enabled"])
        active = bool(state["active"])
        if enabled and active:
            _run_state_command(["enable", "--now", unit], runner, scope=scope)
        elif enabled:
            _run_state_command(["enable", unit], runner, scope=scope)
        elif active:
            _run_state_command(["disable", unit], runner, allow_missing=True, scope=scope)
            _run_state_command(["start", unit], runner, scope=scope)
        else:
            _run_state_command(["disable", unit], runner, allow_missing=True, scope=scope)


def _restore_unit_files(unit_dir: Path, snapshot: dict[str, object]) -> None:
    files = snapshot["files"]
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, record in files.items():
        destination = unit_dir / name
        if destination.exists() or destination.is_symlink():
            _remove_path(destination)
        kind = record["kind"]
        if kind == "file":
            temporary = unit_dir / f".{name}.{uuid.uuid4().hex}.restore"
            temporary.write_bytes(record["bytes"])
            temporary.chmod(record["mode"])
            os.replace(temporary, destination)
        elif kind == "symlink":
            temporary = unit_dir / f".{name}.{uuid.uuid4().hex}.restore"
            os.symlink(record["target"], temporary)
            os.replace(temporary, destination)


def _restore_snapshot_path(destination: Path, record: dict[str, object]) -> None:
    if destination.exists() or destination.is_symlink():
        _remove_path(destination)
    if record["kind"] == "missing":
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.restore"
    if record["kind"] == "file":
        temporary.write_bytes(record["bytes"])
        temporary.chmod(record["mode"])
    elif record["kind"] == "symlink":
        os.symlink(record["target"], temporary)
    os.replace(temporary, destination)


def _promote_private_config(candidate: Path, destination: Path) -> None:
    if candidate.resolve() == destination.resolve():
        return
    if not candidate.is_file() or candidate.is_symlink():
        raise ReleaseAuditError("candidate runtime config must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copyfile(candidate, temporary)
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _create_private_config_snapshot(candidate: Path, destination: Path) -> tuple[int, int]:
    if not candidate.is_file() or candidate.is_symlink():
        raise ReleaseAuditError("candidate runtime config must be a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = None
    try:
        descriptor = os.open(destination, flags, 0o600)
        payload = memoryview(candidate.read_bytes())
        while payload:
            written = os.write(descriptor, payload)
            if written <= 0:
                raise OSError("release config snapshot write made no progress")
            payload = payload[written:]
        os.fsync(descriptor)
    except FileExistsError as exc:
        raise ReleaseAuditError(f"release config snapshot already exists: {destination}") from exc
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        if destination.is_file() and not destination.is_symlink():
            destination.unlink()
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
    destination.chmod(0o600)
    stat = destination.stat()
    return stat.st_dev, stat.st_ino


def _remove_owned_file(path: Path, ownership: tuple[int, int] | None) -> None:
    if ownership is None or not path.is_file() or path.is_symlink():
        return
    stat = path.stat()
    if (stat.st_dev, stat.st_ino) == ownership:
        path.unlink()


def _write_release_failure(data_root: Path, release_name: str, operation: str, error: Exception) -> Path:
    destination = data_root / "release-failures" / f"{release_name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    payload = {
        "schema": "release_failure_v1",
        "operation": operation,
        "release_name": release_name,
        "error_type": type(error).__name__,
        "error": str(error),
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, destination)
    return destination


def _runtime_environment_expected() -> dict[str, str]:
    home = Path.home().as_posix()
    return {
        "CONTENT_PLATFORM_HOME": SYSTEMD_CURRENT_ROOT.replace("%h", home),
        "CONTENT_PLATFORM_CODE_ROOT": SYSTEMD_CURRENT_ROOT.replace("%h", home),
        "PYTHONPATH": SYSTEMD_CURRENT_ROOT.replace("%h", home),
        "CONTENT_PLATFORM_CONFIG": f"{SYSTEMD_MUTABLE_ROOT.replace('%h', home)}/config.json",
        "CONTENT_PLATFORM_DATA_DIR": SYSTEMD_DATA_ROOT.replace("%h", home),
        "CONTENT_PLATFORM_SECRETS_DIR": SYSTEMD_SECRETS_ROOT.replace("%h", home),
        "CONTENT_PLATFORM_RUNTIME_MODE": "production",
    }


def _parse_effective_environment(value: str, unit: str) -> dict[str, str]:
    try:
        return dict(item.split("=", 1) for item in shlex.split(value))
    except (ValueError, TypeError) as exc:
        raise ReleaseAuditError(f"systemd unit {unit} has malformed effective Environment") from exc


def _install_gateway_dropin(release_root: Path, unit_dir: Path) -> Path:
    source = release_root / "systemd" / GATEWAY_DROPIN_SOURCE
    if not source.is_file() or source.is_symlink():
        raise ReleaseAuditError("release is missing the managed Hermes gateway runtime drop-in")
    text = source.read_text(encoding="utf-8")
    for key, value in _runtime_environment_expected().items():
        template_value = value.replace(Path.home().as_posix(), "%h", 1)
        if f"Environment={key}={template_value}" not in text:
            raise ReleaseAuditError(f"gateway runtime drop-in is missing {key}")
    destination = unit_dir / f"{GATEWAY_UNIT}.d" / GATEWAY_DROPIN_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.chmod(0o644)
    os.replace(temporary, destination)
    return destination


def _verify_gateway_runtime_environment(runner=None, *, scope: str = "user") -> None:
    result = _systemd_run(["show", GATEWAY_UNIT, "--property=Environment"], runner, scope=scope)
    values = {}
    for line in (getattr(result, "stdout", "") or "").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    environment = _parse_effective_environment(values.get("Environment", ""), GATEWAY_UNIT)
    for key, expected in _runtime_environment_expected().items():
        if environment.get(key) != expected:
            raise ReleaseAuditError(f"Hermes gateway has the wrong effective {key}")


def _restore_current_link(current: Path | None, snapshot: dict[str, object]) -> None:
    if current is None:
        return
    if current.exists() or current.is_symlink():
        _remove_path(current)
    if snapshot["kind"] == "symlink":
        current.parent.mkdir(parents=True, exist_ok=True)
        temporary = current.parent / f".{current.name}.{uuid.uuid4().hex}.restore"
        os.symlink(snapshot["target"], temporary, target_is_directory=True)
        os.replace(temporary, current)


def _verify_effective_systemd_units(
    release_root: Path,
    unit_dir: Path,
    service_names: list[str],
    runner=None,
    *,
    scope: str = "user",
) -> None:
    for name in service_names:
        path = unit_dir / name
        text = path.read_text(encoding="utf-8")
        _validate_systemd_unit(path, text)
        result = _systemd_run(
            ["show", name, "--property=ExecStart", "--property=WorkingDirectory", "--property=Environment"],
            runner, scope=scope,
        )
        values = {}
        for line in (getattr(result, "stdout", "") or "").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        expected = _runtime_environment_expected()
        current_root = expected["CONTENT_PLATFORM_HOME"]
        mutable_root = str(Path(expected["CONTENT_PLATFORM_CONFIG"]).parent)
        if values.get("WorkingDirectory") != current_root:
            raise ReleaseAuditError(f"systemd unit {name} has the wrong effective WorkingDirectory")
        environment = _parse_effective_environment(values.get("Environment", ""), name)
        for key, value in expected.items():
            if environment.get(key) != value:
                raise ReleaseAuditError(f"systemd unit {name} has the wrong effective {key}")
        if f"{mutable_root}/scripts/" in values.get("ExecStart", ""):
            raise ReleaseAuditError(f"systemd unit {name} has a stale effective script path")
        starts_release_script = any(
            line.startswith("ExecStart=") and f"{SYSTEMD_CURRENT_ROOT}/scripts/" in line
            for line in text.splitlines()
        )
        if starts_release_script and f"{current_root}/scripts/" not in values.get("ExecStart", ""):
            raise ReleaseAuditError(f"systemd unit {name} did not resolve its script from the current release")


def _prepare_systemd_switch(
    release_root: Path,
    unit_dir: Path,
    runner=None,
    *,
    scope: str = "user",
) -> tuple[list[str], list[str], dict[str, dict[str, object]]]:
    services, timers = _install_systemd_units(release_root, unit_dir, runner, scope=scope)
    timer_states = query_systemd_timer_states(timers, runner, scope=scope)
    _disable_systemd_timers(timers, runner, scope=scope)
    return services, timers, timer_states


def _finish_systemd_switch(
    release_root: Path,
    unit_dir: Path,
    service_names: list[str],
    timer_states: dict[str, dict[str, object]],
    runner=None,
    *,
    scope: str = "user",
) -> None:
    _systemd_run(["daemon-reload"], runner, scope=scope)
    _verify_effective_systemd_units(release_root, unit_dir, service_names, runner, scope=scope)
    _restore_systemd_timers(timer_states, runner, scope=scope)


def _systemd_switch(
    release_root: Path,
    unit_dir: Path | str | None,
    runner=None,
    activate=None,
    current: Path | None = None,
    previous_release: Path | None = None,
    scope: str = "user",
    restore_runtime_config=None,
) -> dict:
    if scope not in {"user", "system"}:
        raise ReleaseAuditError("systemd scope must be 'user' or 'system'")
    if unit_dir is None:
        if activate is not None:
            activate(current, release_root)
        return {"verified": False, "skipped": True}
    unit_path = Path(unit_dir).expanduser().resolve()
    services, timers = _systemd_unit_paths(release_root)
    release_names = [path.name for path in [*services, *timers]]
    installed_names = [path.name for path in _installed_related_unit_paths(unit_path)]
    related_names = sorted(set(installed_names) | set(release_names))
    snapshot = _snapshot_systemd_transaction(unit_path, related_names, current, runner, scope=scope)
    gateway_dropin = unit_path / f"{GATEWAY_UNIT}.d" / GATEWAY_DROPIN_NAME
    gateway_dropin_snapshot = _snapshot_unit_file(gateway_dropin)
    gateway_state = query_systemd_unit_states([GATEWAY_UNIT], runner=runner, scope=scope)
    conflicting_dropins = _conflicting_project_dropins(unit_path, [path.name for path in services])
    conflicting_snapshots = {path: _snapshot_unit_file(path) for path in conflicting_dropins}
    timer_states = {name: snapshot["states"][name] for name in related_names if name.endswith(".timer")}
    mutated = False
    try:
        mutated = True
        existing_timers = [
            name for name in installed_names
            if name.endswith(".timer") and snapshot["files"][name]["kind"] != "missing"
        ]
        existing_timers.extend(
            name for name in release_names
            if name.endswith(".timer") and snapshot["states"].get(name, {}).get("enabled")
            and name not in existing_timers
        )
        _disable_systemd_timers(existing_timers, runner, scope=scope)
        for path in conflicting_dropins:
            _remove_path(path)
        _install_systemd_units(release_root, unit_path, runner, scope=scope)
        _install_gateway_dropin(release_root, unit_path)
        _disable_systemd_timers(timers, runner, scope=scope)
        if activate is not None:
            activate(current, release_root)
        _verify_effective_systemd_units(release_root, unit_path, [path.name for path in services], runner, scope=scope)
        _systemd_run(["daemon-reload"], runner, scope=scope)
        if gateway_state[GATEWAY_UNIT]["active"]:
            _systemd_run(["restart", GATEWAY_UNIT], runner, scope=scope)
        _verify_gateway_runtime_environment(runner, scope=scope)
        _restore_systemd_states(
            {name: snapshot["states"][name] for name in release_names},
            runner=runner, scope=scope,
        )
    except Exception as exc:
        rollback_errors = []
        try:
            _stop_systemd_units([*related_names, GATEWAY_UNIT], runner, scope=scope)
        except Exception as rollback_error:
            rollback_errors.append(rollback_error)
        try:
            _restore_unit_files(unit_path, snapshot)
            for path, record in conflicting_snapshots.items():
                _restore_snapshot_path(path, record)
            _restore_snapshot_path(gateway_dropin, gateway_dropin_snapshot)
            _systemd_run(["daemon-reload"], runner, scope=scope)
            _restore_current_link(current, snapshot["current_link"])
            if restore_runtime_config is not None:
                restore_runtime_config()
            _restore_systemd_states(snapshot["states"], runner=runner, scope=scope)
            _restore_systemd_states(gateway_state, runner=runner, scope=scope)
        except Exception as rollback_error:
            rollback_errors.append(rollback_error)
        if rollback_errors:
            raise ReleaseAuditError(
                "systemd transaction failed and rollback failed: "
                + "; ".join(str(error) for error in rollback_errors)
            ) from exc
        raise
    return {"verified": True, "services": services, "timers": timers, "timer_states": timer_states, "gateway_dropin": str(gateway_dropin)}


def preflight_runtime_config(config_path: Path, source_root: Path, data_root: Path, secrets_root: Path) -> None:
    """Reject incompatible config before building; keep caller environment intact."""
    roots = {
        "CONTENT_PLATFORM_CODE_ROOT": str(source_root),
        "CONTENT_PLATFORM_DATA_DIR": str(data_root),
        "CONTENT_PLATFORM_SECRETS_DIR": str(secrets_root),
    }
    previous = {key: os.environ.get(key) for key in roots}
    try:
        os.environ.update(roots)
        _validate_runtime_config(config_path, source_root, data_root, secrets_root)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _validate_runtime_config(config_path: Path, release_root: Path, data_root: Path, secrets_root: Path) -> None:
    if not config_path.is_file():
        raise ReleaseAuditError(f"runtime config does not exist: {config_path}")
    loaded = load_config(str(config_path), str(data_root / "state.db"))
    if Path(loaded.get("data_dir", "")).expanduser().resolve() != data_root.resolve():
        raise ReleaseAuditError("runtime config data_dir is not the stable data root")
    try:
        raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseAuditError("runtime config is not valid JSON") from exc
    # Legacy bootstrap fixtures may contain no publisher section. Whenever a
    # mutable publisher policy is present, it must match the immutable matrix.
    if isinstance(raw_config.get("publishers"), dict):
        delivery_policy = validate_delivery_policy_config(loaded)
        if not delivery_policy["passed"]:
            raise ReleaseAuditError("runtime delivery policy mismatch: " + ";".join(delivery_policy["failures"]))

    dependency_block = raw_config.get("external_runtime_dependencies") or {}
    if dependency_block and dependency_block.get("schema") != "external_runtime_dependencies_v1":
        raise ReleaseAuditError("external runtime dependency schema is invalid")
    records = dependency_block.get("items", []) if isinstance(dependency_block, dict) else []
    if not isinstance(records, list):
        raise ReleaseAuditError("external runtime dependency items must be a list")
    external_by_key = {}
    seen_ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise ReleaseAuditError("external runtime dependency record must be an object")
        required = {"id", "kind", "config_key", "path", "sha256"}
        if set(record) != required or record.get("kind") != "hermes_bridge":
            raise ReleaseAuditError("external runtime dependency contract is invalid")
        dependency_id = str(record["id"]).strip()
        config_key = str(record["config_key"]).strip()
        digest = str(record["sha256"]).strip().lower()
        if not dependency_id or dependency_id in seen_ids or not config_key or config_key in external_by_key:
            raise ReleaseAuditError("external runtime dependency identity is invalid or duplicated")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ReleaseAuditError(f"external runtime dependency hash is invalid: {dependency_id}")
        seen_ids.add(dependency_id)
        external_by_key[config_key] = record
    used_external = set()
    hermes_root = Path(os.environ.get("HERMES_HOME", "").strip() or Path.home() / ".hermes").expanduser().resolve()

    def visit(value, key: str = ""):
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                child_path = f"{key}.{child_key}" if key else str(child_key)
                if child_path == "external_runtime_dependencies":
                    continue
                visit(child_value, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{key}.{index}")
        elif isinstance(value, str) and value.lower().endswith((".py", ".sh")):
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = release_root / candidate
            resolved = candidate.resolve()
            try:
                resolved.relative_to(release_root.resolve())
            except ValueError:
                record = external_by_key.get(key)
                if record is None or Path(str(record["path"])).expanduser().resolve() != resolved:
                    raise ReleaseAuditError(f"configured {key} script is outside release without matching external contract: {value}")
                _validate_raw_path(value, f"external dependency {record['id']}")
                try:
                    resolved.relative_to(hermes_root)
                except ValueError as exc:
                    raise ReleaseAuditError(f"external bridge is outside Hermes root: {record['id']}") from exc
                if not resolved.is_file() or resolved.is_symlink():
                    raise ReleaseAuditError(f"external bridge is missing or symlinked: {record['id']}")
                if _sha256(resolved) != record["sha256"]:
                    raise ReleaseAuditError(f"external bridge hash mismatch: {record['id']}")
                used_external.add(key)
                return
            if not resolved.is_file():
                raise ReleaseAuditError(f"configured {key} script does not exist in release: {value}")

    visit(loaded)
    unused = sorted(set(external_by_key) - used_external)
    if unused:
        raise ReleaseAuditError("external runtime dependencies are not bound to configured scripts: " + ",".join(unused))


def _validate_signing_key_boundary(
    signing_key: Path,
    secrets_root: Path,
    data_root: Path,
    releases_root: Path,
    current_link: Path,
    release_root: Path | None = None,
) -> None:
    key = signing_key.resolve()
    secrets = secrets_root.resolve()
    if secrets != data_root.resolve().parent / "secrets" or key.parent != secrets:
        raise ReleaseAuditError("signing key must be directly under the stable secrets boundary")
    for label, boundary in (("data root", data_root), ("releases root", releases_root), ("current root", current_link)):
        try:
            key.relative_to(boundary.resolve())
        except ValueError:
            continue
        raise ReleaseAuditError(f"signing key must not be inside {label}")
    if release_root is not None:
        try:
            key.relative_to(release_root.resolve())
        except ValueError:
            return
        raise ReleaseAuditError("signing key must not be inside release")


def init_signing_key(secrets_root: Path | str) -> Path:
    secrets = Path(secrets_root).expanduser().resolve()
    _validate_raw_path(secrets, "secrets_root")
    if secrets.name != "secrets":
        raise ReleaseAuditError("secrets_root must be the stable secrets directory")
    return _create_signing_key(secrets / "release-signing.key")


def _signed_rollback_dry_run(target: Path, key: Path, secrets: Path) -> dict:
    previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
    previous_secrets = os.environ.get("CONTENT_PLATFORM_SECRETS_DIR")
    os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(target)
    os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = str(secrets)
    try:
        verify_metadata(
            target / "release-metadata.json",
            current_release_root=target,
            signing_key_path=key,
            trusted_secrets_root=secrets,
        )
        return {"target_release": str(target), "release_digest": _release_digest(target), "passed": True}
    finally:
        if previous_root is None:
            os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
        else:
            os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
        if previous_secrets is None:
            os.environ.pop("CONTENT_PLATFORM_SECRETS_DIR", None)
        else:
            os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = previous_secrets


def _run_real_evidence(argv, cwd: Path, stdout_path: Path):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if argv[2] == "content_platform":
        stdout_path.write_text(result.stdout, encoding="utf-8")
    return result


def _generate_evidence(source: Path, data: Path, name: str, commit: str, runner=None) -> dict:
    evidence_root = data / "release-evidence" / name
    if evidence_root.exists():
        raise ReleaseAuditError(f"release evidence already exists: {evidence_root}")
    evidence_root.mkdir(parents=True)
    junit_path = evidence_root / "junit.xml"
    project_path = evidence_root / "project-audit.json"
    commands = [
        ("junit", [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit_path}"], junit_path),
        ("project_audit", [sys.executable, "-m", "content_platform", "project-audit"], project_path),
    ]
    records = []
    for kind, argv, output_path in commands:
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        result = (runner or _run_real_evidence)(argv, source, output_path)
        finished = dt.datetime.now(dt.timezone.utc).isoformat()
        records.append({
            "kind": kind,
            "argv": argv,
            "cwd": str(source),
            "started_at": started,
            "finished_at": finished,
            "returncode": result.returncode,
            "path": str(output_path),
            "sha256": _sha256(output_path) if output_path.is_file() else "",
        })
        if _git(source, "status", "--porcelain").strip():
            raise ReleaseAuditError("staging worktree is dirty or has uncommitted changes")
    manifest = {"commit": commit, "evidence": records}
    manifest_path = evidence_root / "evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if any(record["returncode"] != 0 or not record["sha256"] for record in records):
        raise ReleaseAuditError(f"release evidence command failed: {manifest_path}")
    return {"manifest": manifest_path, "junit": junit_path, "project_audit": project_path}


def attest_existing_release(
    *,
    source_root: Path | str,
    target_release: Path | str,
    current_link: Path | str | None = None,
    config_path: Path | str,
    data_root: Path | str,
    secrets_root: Path | str | None = None,
    signing_key: Path | str | None = None,
    min_tests: int = 900,
    evidence_runner=None,
) -> dict:
    """Adopt the current unmetadataed release as a signed bootstrap release."""
    _validate_raw_path(source_root, "source_root")
    _validate_raw_path(target_release, "target_release")
    _validate_raw_path(config_path, "config_path")
    _validate_raw_path(data_root, "data_root")
    source = Path(source_root).expanduser().resolve()
    target = Path(target_release).expanduser().resolve()
    current = _current_path(current_link)
    config = Path(config_path).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if signing_key is not None:
        key = Path(signing_key).expanduser().resolve()
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else key.parent
    else:
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else data.parent / "secrets"
        key = secrets / "release-signing.key"
    _validate_signing_key_boundary(key, secrets, data, target.parent, current, target)
    metadata_path = target / "release-metadata.json"
    attestation = data / "release-attestations" / f"{target.name}.sha256"
    lock_path = data / "runtime-release.lock"

    with _exclusive_lock(lock_path):
        if not source.is_dir() or not target.is_dir():
            raise ReleaseAuditError("source and target release must be directories")
        if not current.is_symlink() or current.resolve() != target:
            raise ReleaseAuditError("target release must be the current_link resolved target")
        if metadata_path.exists() or metadata_path.is_symlink():
            raise ReleaseAuditError(f"release metadata already exists: {metadata_path}")
        existing_attestations = list(attestation.parent.glob("*.sha256")) if attestation.parent.exists() else []
        if existing_attestations:
            raise ReleaseAuditError("attestation directory already contains a signed release")
        if _git(source, "status", "--porcelain").strip():
            raise ReleaseAuditError("source root is dirty or has uncommitted changes")
        commit = _git(source, "rev-parse", "HEAD").strip()
        staging = source.parent / f"{source.name}-release-staging-{uuid.uuid4().hex}"
        try:
            _git(source, "worktree", "add", "--detach", str(staging), commit)
            evidence = _generate_evidence(staging, data, target.name, commit, runner=evidence_runner)
            source_hashes = {}
            staging_hashes = {}
            for root, hashes in ((source, source_hashes), (staging, staging_hashes)):
                for relative in _tracked_paths(root):
                    path = root / relative
                    if path.is_symlink() or not path.is_file():
                        raise ReleaseAuditError(f"tracked source file is not a regular file: {relative}")
                    hashes[relative.as_posix()] = _sha256(path)
            if source_hashes != staging_hashes:
                raise ReleaseAuditError("source and detached staging tracked file hashes do not match")
            for root, directories, files in os.walk(target, followlinks=False):
                for name in (*directories, *files):
                    candidate = Path(root) / name
                    if candidate.is_symlink():
                        raise ReleaseAuditError(f"existing release contains forbidden symlink: {candidate.relative_to(target)}")
            for relative, expected in source_hashes.items():
                candidate = target / relative
                if not candidate.is_file() or candidate.is_symlink() or _sha256(candidate) != expected:
                    raise ReleaseAuditError(f"existing release content hash mismatch: {relative}")
            allowed = set(source_hashes) | {"release-metadata.json"}
            for path in target.rglob("*"):
                if path.is_file() and path.relative_to(target).as_posix() not in allowed:
                    raise ReleaseAuditError(f"existing release contains extra code: {path.relative_to(target)}")
            previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
            previous_data = os.environ.get("CONTENT_PLATFORM_DATA_DIR")
            previous_secrets = os.environ.get("CONTENT_PLATFORM_SECRETS_DIR")
            os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(target)
            os.environ["CONTENT_PLATFORM_DATA_DIR"] = str(data)
            os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = str(secrets)
            try:
                _validate_runtime_config(config, target, data, secrets)
                metadata = audit_release(
                    source_root=staging,
                    release_root=target,
                    configured_script_root=target / "scripts",
                    config_path=config,
                    test_report_path=evidence["junit"],
                    rollback_target="",
                    attestation_path=attestation,
                    signing_key_path=key,
                    trusted_secrets_root=secrets,
                    project_audit_report_path=evidence["project_audit"],
                    evidence_manifest_path=evidence["manifest"],
                    expected_commit=commit,
                    min_tests=min_tests,
                    bootstrap=True,
                )
                write_metadata(metadata, metadata_path, signing_key_path=key)
            finally:
                if previous_root is None:
                    os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
                else:
                    os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
                if previous_data is None:
                    os.environ.pop("CONTENT_PLATFORM_DATA_DIR", None)
                else:
                    os.environ["CONTENT_PLATFORM_DATA_DIR"] = previous_data
                if previous_secrets is None:
                    os.environ.pop("CONTENT_PLATFORM_SECRETS_DIR", None)
                else:
                    os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = previous_secrets
            _freeze_release(target)
            return {
                "ok": True,
                "operation": "attest-existing",
                "release_root": str(target),
                "metadata_path": str(metadata_path),
                "attestation_path": str(attestation),
                "signing_key_path": str(key),
                "commit": commit,
            }
        finally:
            if staging.exists() or staging.is_symlink():
                _git(source, "worktree", "remove", "--force", str(staging))
            _git(source, "worktree", "prune")


def prepare_bootstrap_release(
    *,
    source_root: Path | str,
    releases_root: Path | str,
    current_link: Path | str | None = None,
    config_path: Path | str,
    data_root: Path | str,
    release_name: str,
    secrets_root: Path | str | None = None,
    signing_key: Path | str | None = None,
    min_tests: int = 900,
    evidence_runner=None,
) -> dict:
    """Build and sign a clean bootstrap rollback release without activating it."""
    name = str(release_name or "").strip()
    if not name or name in {".", ".."} or any(char in name for char in "/\\:\0") or Path(name).name != name:
        raise ReleaseAuditError("release_name must be a single non-empty path component")
    for value, label in (
        (source_root, "source_root"), (releases_root, "releases_root"),
        (config_path, "config_path"), (data_root, "data_root"),
        (secrets_root, "secrets_root"), (signing_key, "signing_key"),
    ):
        if value is not None:
            _validate_raw_path(value, label)
    source = Path(source_root).expanduser().resolve()
    releases = Path(releases_root).expanduser().resolve()
    current = _current_path(current_link)
    config = Path(config_path).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else data.parent / "secrets"
    key = Path(signing_key).expanduser().resolve() if signing_key is not None else secrets / "release-signing.key"
    _validate_signing_key_boundary(key, secrets, data, releases, current)
    if signing_key is not None and not key.is_file():
        raise ReleaseAuditError("explicit signing key does not exist")
    release = releases / name
    with _exclusive_lock(data / "runtime-release.lock"):
        if _git(source, "status", "--porcelain").strip():
            raise ReleaseAuditError("source root is dirty or has uncommitted changes")
        if release.exists() or release.is_symlink():
            raise ReleaseAuditError(f"release already exists: {release}")
        attestation = data / "release-attestations" / f"{name}.sha256"
        config_snapshot = data / "release-configs" / f"{name}.json"
        _validate_raw_path(attestation, "attestation_path")
        _validate_raw_path(config_snapshot, "release_config_snapshot")
        if attestation.exists() or config_snapshot.exists() or config_snapshot.is_symlink():
            raise ReleaseAuditError("release attestation or config snapshot already exists")
        preflight_runtime_config(config, source, data, secrets)
        if not key.is_file():
            init_signing_key(secrets)
        commit = _git(source, "rev-parse", "HEAD").strip()
        releases.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=str(releases)))
        staging = source.parent / f"{source.name}-release-staging-{uuid.uuid4().hex}"
        owned_release = None
        owned_config_snapshot = None
        try:
            _git(source, "worktree", "add", "--detach", str(staging), commit)
            evidence = _generate_evidence(staging, data, name, commit, runner=evidence_runner)
            tracked_modes = _tracked_modes(staging)
            for relative in _tracked_paths(staging):
                source_path = staging / relative
                if source_path.is_symlink() or not source_path.is_file():
                    raise ReleaseAuditError(f"tracked source file is not a regular file: {relative}")
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
                destination.chmod(0o755 if tracked_modes.get(relative.as_posix()) == "100755" else 0o644)
            # Reserve the inactive candidate exclusively; never replace another
            # builder's directory, including an empty one on POSIX.
            release.mkdir()
            owned_stat = release.stat()
            owned_release = (owned_stat.st_dev, owned_stat.st_ino)
            for child in temporary.iterdir():
                os.replace(child, release / child.name)
            owned_config_snapshot = _create_private_config_snapshot(config, config_snapshot)
            previous = {
                key_name: os.environ.get(key_name)
                for key_name in ("CONTENT_PLATFORM_CODE_ROOT", "CONTENT_PLATFORM_DATA_DIR", "CONTENT_PLATFORM_SECRETS_DIR")
            }
            os.environ.update({
                "CONTENT_PLATFORM_CODE_ROOT": str(release),
                "CONTENT_PLATFORM_DATA_DIR": str(data),
                "CONTENT_PLATFORM_SECRETS_DIR": str(secrets),
            })
            try:
                _validate_runtime_config(config_snapshot, release, data, secrets)
                metadata = audit_release(
                    source_root=staging, release_root=release, configured_script_root=release / "scripts",
                    config_path=config_snapshot, test_report_path=evidence["junit"], rollback_target="",
                    attestation_path=attestation, signing_key_path=key, trusted_secrets_root=secrets,
                    project_audit_report_path=evidence["project_audit"], evidence_manifest_path=evidence["manifest"],
                    expected_commit=commit, min_tests=min_tests, bootstrap=True,
                )
                write_metadata(metadata, release / "release-metadata.json", signing_key_path=key)
            finally:
                for key_name, value in previous.items():
                    if value is None:
                        os.environ.pop(key_name, None)
                    else:
                        os.environ[key_name] = value
            _freeze_release(release)
            return {
                "ok": True, "prepared": True, "activated": False, "release_root": str(release),
                "metadata_path": str(release / "release-metadata.json"), "attestation_path": str(attestation),
                "signing_key_path": str(key), "commit": commit,
            }
        except Exception:
            _remove_owned_file(config_snapshot, owned_config_snapshot)
            if owned_release is not None and attestation.is_file() and not attestation.is_symlink():
                attestation.unlink()
            if owned_release is not None and release.is_dir() and not release.is_symlink() and (release.stat().st_dev, release.stat().st_ino) == owned_release:
                release.chmod(0o755)
                for path in release.rglob("*"):
                    if path.is_symlink():
                        continue
                    if path.is_file():
                        path.chmod(0o644)
                    elif path.is_dir():
                        path.chmod(0o755)
                shutil.rmtree(release)
            raise
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)
            if staging.exists() or staging.is_symlink():
                _git(source, "worktree", "remove", "--force", str(staging))
            _git(source, "worktree", "prune")


def deploy_release(
    *,
    source_root: Path | str,
    releases_root: Path | str,
    current_link: Path | str | None = None,
    config_path: Path | str,
    test_report_path: Path | str | None = None,
    rollback_target: Path | str,
    data_root: Path | str,
    release_name: str | None = None,
    secrets_root: Path | str | None = None,
    signing_key: Path | str | None = None,
    project_audit_report: Path | str | None = None,
    min_tests: int = 900,
    evidence_runner=None,
    systemd_unit_dir: Path | str | None = None,
    systemd_runner=None,
    systemd_scope: str = "user",
    active_config_path: Path | str | None = None,
) -> dict:
    """Deploy one clean source revision while holding the runtime release lock."""
    _validate_raw_path(source_root, "source_root")
    _validate_raw_path(releases_root, "releases_root")
    _validate_raw_path(config_path, "config_path")
    _validate_raw_path(rollback_target, "rollback_target")
    _validate_raw_path(data_root, "data_root")
    if active_config_path is not None:
        _validate_raw_path(active_config_path, "active_config_path")
    source = Path(source_root).expanduser().resolve()
    releases = Path(releases_root).expanduser().resolve()
    current = _current_path(current_link)
    config = Path(config_path).expanduser().resolve()
    active_config = Path(active_config_path).expanduser().resolve() if active_config_path is not None else config
    rollback = Path(rollback_target).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if signing_key is not None:
        signing_key_path = Path(signing_key).expanduser().resolve()
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else signing_key_path.parent
    else:
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else data.parent / "secrets"
        signing_key_path = secrets / "release-signing.key"
    _validate_signing_key_boundary(signing_key_path, secrets, data, releases, current)
    lock_path = data / "runtime-release.lock"

    with _exclusive_lock(lock_path):
        if _git(source, "status", "--porcelain").strip():
            raise ReleaseAuditError("source root is dirty or has uncommitted changes")
        commit = _git(source, "rev-parse", "HEAD").strip()
        rollback_rehearsal = _signed_rollback_dry_run(rollback, signing_key_path, secrets)
        preflight_runtime_config(config, source, data, secrets)
        name = release_name or commit[:12]
        if not name or name in {".", ".."} or Path(name).name != name:
            raise ReleaseAuditError("release_name must be a single non-empty path component")
        release = releases / name
        if release.exists() or release.is_symlink():
            raise ReleaseAuditError(f"release already exists: {release}")
        attestation = data / "release-attestations" / f"{name}.sha256"
        release_config = data / "release-configs" / f"{name}.json"
        if attestation.exists() or release_config.exists() or release_config.is_symlink():
            raise ReleaseAuditError("release attestation or config snapshot already exists")
        releases.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=str(releases)))
        staging = source.parent / f"{source.name}-release-staging-{uuid.uuid4().hex}"
        active_config_snapshot = None
        config_promoted = False
        owned_release_config = None
        owned_attestation_hash = None
        try:
            temporary.rmdir()
            _git(source, "worktree", "add", "--detach", str(staging), commit)
            evidence = _generate_evidence(staging, data, name, commit, runner=evidence_runner)
            report = evidence["junit"]
            project_audit_report_path = evidence["project_audit"]
            evidence_manifest_path = evidence["manifest"]
            tracked_paths = _tracked_paths(staging)
            tracked_modes = _tracked_modes(staging)
            for relative in tracked_paths:
                source_path = staging / relative
                if source_path.is_symlink() or not source_path.is_file():
                    raise ReleaseAuditError(f"tracked source file is not a regular file: {relative}")
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
                destination.chmod(0o755 if tracked_modes.get(relative.as_posix()) == "100755" else 0o644)
            os.replace(temporary, release)
            temporary = None
            owned_release_config = _create_private_config_snapshot(config, release_config)
            previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
            previous_data = os.environ.get("CONTENT_PLATFORM_DATA_DIR")
            previous_secrets = os.environ.get("CONTENT_PLATFORM_SECRETS_DIR")
            os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(release)
            os.environ["CONTENT_PLATFORM_DATA_DIR"] = str(data)
            os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = str(secrets)
            try:
                _validate_runtime_config(release_config, release, data, secrets)
                metadata = audit_release(
                    source_root=staging,
                    release_root=release,
                    configured_script_root=release / "scripts",
                    config_path=release_config,
                    test_report_path=report,
                    rollback_target=rollback,
                    attestation_path=attestation,
                    signing_key_path=signing_key_path,
                    trusted_secrets_root=secrets,
                    project_audit_report_path=project_audit_report_path,
                    evidence_manifest_path=evidence_manifest_path,
                    expected_commit=commit,
                    min_tests=min_tests,
                )
                metadata["rollback_rehearsal"] = rollback_rehearsal
                write_metadata(metadata, release / "release-metadata.json", signing_key_path=signing_key_path)
                owned_attestation_hash = _sha256(attestation)
            finally:
                if previous_root is None:
                    os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
                else:
                    os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
                if previous_data is None:
                    os.environ.pop("CONTENT_PLATFORM_DATA_DIR", None)
                else:
                    os.environ["CONTENT_PLATFORM_DATA_DIR"] = previous_data
                if previous_secrets is None:
                    os.environ.pop("CONTENT_PLATFORM_SECRETS_DIR", None)
                else:
                    os.environ["CONTENT_PLATFORM_SECRETS_DIR"] = previous_secrets
            _freeze_release(release)
            if active_config_path is not None and active_config != release_config:
                active_config_snapshot = _snapshot_unit_file(active_config)
                _promote_private_config(release_config, active_config)
                config_promoted = True

            def restore_runtime_config():
                nonlocal config_promoted
                if config_promoted and active_config_snapshot is not None:
                    _restore_snapshot_path(active_config, active_config_snapshot)
                    config_promoted = False

            previous_release = current.resolve() if current.is_symlink() else None
            systemd = _systemd_switch(
                release,
                systemd_unit_dir,
                systemd_runner,
                activate=_activate,
                current=current,
                previous_release=previous_release,
                scope=systemd_scope,
                restore_runtime_config=restore_runtime_config,
            )
            return {
                "ok": True,
                "release_root": str(release),
                "metadata_path": str(release / "release-metadata.json"),
                "attestation_path": str(attestation),
                "signing_key_path": str(signing_key_path),
                "commit": commit,
                "systemd": systemd,
            }
        except Exception as exc:
            config_rollback_error = None
            if config_promoted and active_config_snapshot is not None:
                try:
                    _restore_snapshot_path(active_config, active_config_snapshot)
                except Exception as rollback_error:
                    config_rollback_error = rollback_error
            if release.exists() and not release.is_symlink():
                for path in sorted(release.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                    if path.is_file():
                        path.chmod(0o644)
                    elif path.is_dir() and not path.is_symlink():
                        path.chmod(0o755)
                release.chmod(0o755)
                shutil.rmtree(release)
            if owned_attestation_hash is not None and attestation.is_file() and not attestation.is_symlink() and _sha256(attestation) == owned_attestation_hash:
                attestation.unlink()
            _remove_owned_file(release_config, owned_release_config)
            try:
                _write_release_failure(data, name, "deploy", exc)
            except Exception:
                pass
            if config_rollback_error is not None:
                raise ReleaseAuditError(f"deployment failed and active config rollback failed: {config_rollback_error}") from exc
            raise
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)
            if staging.exists() or staging.is_symlink():
                _git(source, "worktree", "remove", "--force", str(staging))
            _git(source, "worktree", "prune")


def rollback_release(
    *,
    target_release: Path | str,
    current_link: Path | str | None = None,
    data_root: Path | str,
    signing_key: Path | str | None = None,
    secrets_root: Path | str | None = None,
    systemd_unit_dir: Path | str | None = None,
    systemd_runner=None,
    systemd_scope: str = "user",
    active_config_path: Path | str | None = None,
) -> dict:
    """Verify an audited frozen release and atomically activate it as current."""
    _validate_raw_path(target_release, "target_release")
    _validate_raw_path(data_root, "data_root")
    if active_config_path is not None:
        _validate_raw_path(active_config_path, "active_config_path")
    target = Path(target_release).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    current = _current_path(current_link)
    active_config = Path(active_config_path).expanduser().resolve() if active_config_path is not None else None
    if signing_key is not None:
        key = Path(signing_key).expanduser().resolve()
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else key.parent
    else:
        secrets = Path(secrets_root).expanduser().resolve() if secrets_root is not None else data.parent / "secrets"
        key = secrets / "release-signing.key"
    _validate_signing_key_boundary(key, secrets, data, target.parent, current, target)
    with _exclusive_lock(data / "runtime-release.lock"):
        metadata_path = target / "release-metadata.json"
        previous_root = os.environ.get("CONTENT_PLATFORM_CODE_ROOT")
        os.environ["CONTENT_PLATFORM_CODE_ROOT"] = str(target)
        try:
            metadata = verify_metadata(
                metadata_path,
                current_release_root=target,
                signing_key_path=key,
                trusted_secrets_root=secrets,
            )
        finally:
            if previous_root is None:
                os.environ.pop("CONTENT_PLATFORM_CODE_ROOT", None)
            else:
                os.environ["CONTENT_PLATFORM_CODE_ROOT"] = previous_root
        release_config = Path(metadata["config_path"]).expanduser().resolve()
        if active_config is not None:
            try:
                release_config.relative_to((data / "release-configs").resolve())
            except ValueError as exc:
                raise ReleaseAuditError("rollback release config is outside the durable snapshot root") from exc
        active_snapshot = _snapshot_unit_file(active_config) if active_config is not None else None
        config_promoted = False

        def restore_runtime_config():
            nonlocal config_promoted
            if config_promoted and active_config is not None and active_snapshot is not None:
                _restore_snapshot_path(active_config, active_snapshot)
                config_promoted = False

        try:
            if active_config is not None:
                _promote_private_config(release_config, active_config)
                config_promoted = True
            previous_release = current.resolve() if current.is_symlink() else None
            systemd = _systemd_switch(
                target,
                systemd_unit_dir,
                systemd_runner,
                activate=_activate,
                current=current,
                previous_release=previous_release,
                scope=systemd_scope,
                restore_runtime_config=restore_runtime_config,
            )
        except Exception:
            restore_runtime_config()
            raise
        return {
            "ok": True,
            "operation": "rollback",
            "release_root": str(target),
            "metadata_path": str(metadata_path),
            "attestation_path": metadata["attestation_path"],
            "commit": metadata["commit"],
            "systemd": systemd,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", nargs="?", choices=("deploy", "rollback", "attest-existing", "init-signing-key"), default="deploy")
    parser.add_argument("--source-root")
    parser.add_argument("--releases-root")
    parser.add_argument("--current-link")
    parser.add_argument("--config-path")
    parser.add_argument("--active-config-path")
    parser.add_argument("--test-report-path")
    parser.add_argument("--rollback-target")
    parser.add_argument("--target-release")
    parser.add_argument("--data-root")
    parser.add_argument("--release-name")
    parser.add_argument("--secrets-root")
    parser.add_argument("--signing-key")
    parser.add_argument("--project-audit-report")
    parser.add_argument("--min-tests", type=int, default=900)
    parser.add_argument("--systemd-unit-dir")
    parser.add_argument("--systemd-scope", choices=("user", "system"), default="user")
    args = parser.parse_args()
    systemd_unit_dir = (
        args.systemd_unit_dir
        if args.systemd_unit_dir is not None
        else str(default_systemd_unit_dir(args.systemd_scope))
    )
    if args.operation == "init-signing-key":
        if not args.secrets_root:
            parser.error("init-signing-key requires --secrets-root")
        print(init_signing_key(args.secrets_root))
        return 0
    if not args.data_root:
        parser.error("deploy/rollback/attest-existing requires --data-root")
    if args.operation == "rollback":
        if not args.target_release:
            parser.error("rollback requires --target-release")
        if not args.signing_key and not args.secrets_root:
            parser.error("rollback requires --signing-key or --secrets-root")
        result = rollback_release(
            target_release=args.target_release,
            current_link=args.current_link,
            data_root=args.data_root,
            signing_key=args.signing_key,
            secrets_root=args.secrets_root,
            active_config_path=args.active_config_path,
            systemd_unit_dir=systemd_unit_dir or None,
            systemd_scope=args.systemd_scope,
        )
    elif args.operation == "attest-existing":
        required = {
            "source_root": args.source_root,
            "target_release": args.target_release,
            "config_path": args.config_path,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error(f"attest-existing requires: {', '.join(missing)}")
        if not args.signing_key and not args.secrets_root:
            parser.error("attest-existing requires --signing-key or --secrets-root")
        result = attest_existing_release(
            source_root=args.source_root,
            target_release=args.target_release,
            current_link=args.current_link,
            config_path=args.config_path,
            data_root=args.data_root,
            secrets_root=args.secrets_root,
            signing_key=args.signing_key,
            min_tests=args.min_tests,
        )
    else:
        required = {
            "source_root": args.source_root,
            "releases_root": args.releases_root,
            "config_path": args.config_path,
            "rollback_target": args.rollback_target,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error(f"deploy requires: {', '.join(missing)}")
        if not args.signing_key and not args.secrets_root:
            parser.error("deploy requires --signing-key or --secrets-root")
        result = deploy_release(
            source_root=args.source_root,
            releases_root=args.releases_root,
            current_link=args.current_link,
            config_path=args.config_path,
            active_config_path=args.active_config_path,
            test_report_path=None,
            rollback_target=args.rollback_target,
            data_root=args.data_root,
            release_name=args.release_name,
            secrets_root=args.secrets_root,
            signing_key=args.signing_key,
            project_audit_report=args.project_audit_report,
            min_tests=args.min_tests,
            systemd_unit_dir=systemd_unit_dir or None,
            systemd_scope=args.systemd_scope,
        )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
