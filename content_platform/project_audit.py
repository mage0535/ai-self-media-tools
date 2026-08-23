import re
import os
import stat
import subprocess
from pathlib import Path


IGNORED_PARTS = {
    ".git",
    ".codex",
    ".codex-server-runtime",
    ".codex-tmp",
    "__codex_proxy_sync_tmp__",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "data",
    "secrets",
    "logs",
    "artifacts",
    "outbox",
    "cookies",
    "local-ops-lab",
    "tmp",
    "graphify-out",
}

IGNORED_EXACT = {
    "config.json",
    "installation-report.json",
}

FORBIDDEN_NAME_PATTERNS = [
    r"\.bak",
    r"\.env(?:\..+)?$",
    r"\.key$",
    r"\.pem$",
    r"\.p12$",
    r"cookie",
    r"token",
    r"secret",
]

FORBIDDEN_CONTENT_PATTERNS = [
    r"OPENAI_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}",
    r"sk-[A-Za-z0-9_\-]{20,}",
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----",
    r"SESSDATA=[A-Za-z0-9%_\-]{8,}",
    r"bili_jct=[A-Za-z0-9%_\-]{8,}",
    r"/root/",
    r"/root/\.hermes/",
]

PRIVATE_PATH_PATTERNS = [
    r"[A-Za-z]:\\Users\\",
    r"/Users/[^/\n]+/",
]


def audit_project(root):
    root = Path(root)
    issues = []
    scanned = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = [
            name for name in dirnames
            if name not in IGNORED_PARTS and not (directory_path / name).is_symlink()
        ]
        for filename in filenames:
            path = directory_path / filename
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if _is_ignored_runtime_path(relative) or path.name in IGNORED_EXACT:
                continue
            if _is_secure_gitignored_runtime_env(root, path, relative) or path.name == "project_audit.py":
                continue
            scanned += 1
            relative_text = relative.as_posix()
            lowered = relative_text.casefold()
            if len(relative.parts) == 1 and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".mp4", ".mov", ".webm"}:
                issues.append({"path": relative_text, "reason": "root_level_media_evidence"})
                continue
            if any(re.search(pattern, lowered) for pattern in FORBIDDEN_NAME_PATTERNS):
                issues.append({"path": relative_text, "reason": "forbidden_filename_pattern"})
                continue
            if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".mp4", ".mov", ".webm", ".db", ".sqlite", ".sqlite3", ".pyc"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for pattern in FORBIDDEN_CONTENT_PATTERNS + PRIVATE_PATH_PATTERNS:
                if re.search(pattern, text):
                    issues.append({"path": relative_text, "reason": f"forbidden_content_pattern:{pattern}"})
                    break
    return {"ok": not issues, "scanned_files": scanned, "issues": issues}


def _is_ignored_runtime_path(relative: Path) -> bool:
    """Exclude server-only evidence directories that are never publishable."""
    return any(
        part in IGNORED_PARTS or part == "refs" or part.startswith("local_ops_")
        for part in relative.parts
    )


def _is_secure_gitignored_runtime_env(root: Path, path: Path, relative: Path) -> bool:
    """Ignore only private runtime env files that Git will never publish.

    A broad `.env*` allow-list would hide accidental secrets. All three checks
    are required: env filename, active Git ignore rule, and owner-only mode.
    """
    if not (path.name == ".env" or path.name.startswith(".env.")):
        return False
    try:
        if not _owner_only_permissions(path):
            return False
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", relative.as_posix()],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=3,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _owner_only_permissions(path: Path) -> bool:
    # POSIX mode bits are authoritative on the production host. Windows ACLs
    # need a dedicated ACL check, so fail closed rather than infer from mode.
    return os.name != "nt" and not (stat.S_IMODE(path.stat().st_mode) & 0o077)
