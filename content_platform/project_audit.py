import re
from pathlib import Path


FORBIDDEN_NAME_PATTERNS = [
    r"\.env$",
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
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == "project_audit.py":
            continue
        scanned += 1
        relative = path.relative_to(root).as_posix()
        lowered = relative.casefold()
        if any(re.search(pattern, lowered) for pattern in FORBIDDEN_NAME_PATTERNS):
            issues.append({"path": relative, "reason": "forbidden_filename_pattern"})
            continue
        if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".mp4", ".db", ".sqlite", ".sqlite3", ".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern in FORBIDDEN_CONTENT_PATTERNS + PRIVATE_PATH_PATTERNS:
            if re.search(pattern, text):
                issues.append({"path": relative, "reason": f"forbidden_content_pattern:{pattern}"})
                break
    return {"ok": not issues, "scanned_files": scanned, "issues": issues}
