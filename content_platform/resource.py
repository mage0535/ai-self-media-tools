import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path


def system_probe(path):
    available_mb = 0
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            values[key] = int(value.strip().split()[0])
        available_mb = values.get("MemAvailable", 0) // 1024
    else:
        available_mb = 4096
    disk = shutil.disk_usage(path)
    return {"available_mb": available_mb, "disk_used_percent": round((disk.used / disk.total) * 100, 2)}


class ResourceGuard:
    def __init__(self, data_dir, config=None, probe=None):
        self.data_dir = Path(data_dir)
        self.config = config or {}
        self.probe = probe or (lambda: system_probe(self.data_dir))

    def check(self, kind):
        snapshot = self.probe()
        min_memory = int(self.config.get("min_available_mb", 768 if kind == "video" else 256))
        max_disk = float(self.config.get("max_disk_used_percent", 88))
        if snapshot["available_mb"] < min_memory:
            raise RuntimeError(f"resource_guard: available memory {snapshot['available_mb']}MB below {min_memory}MB")
        if snapshot["disk_used_percent"] >= max_disk:
            raise RuntimeError(f"resource_guard: disk usage {snapshot['disk_used_percent']}% reached {max_disk}%")
        return snapshot

    @contextmanager
    def video_lock(self):
        lock = self.data_dir / "locks" / "video.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("another video worker holds the lock") from exc
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def cleanup(self, protected_paths, retention_days=14):
        cutoff = time.time() - int(retention_days) * 86400
        protected = {str(Path(path).resolve()) for path in protected_paths}
        removed, bytes_removed = 0, 0
        for base_name in ("artifacts", "tmp"):
            base = self.data_dir / base_name
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or str(path.resolve()) in protected or path.stat().st_mtime >= cutoff:
                    continue
                bytes_removed += path.stat().st_size
                path.unlink()
                removed += 1
        return {"removed": removed, "bytes_removed": bytes_removed}

