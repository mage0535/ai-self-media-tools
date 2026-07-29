"""P0 secret and sensitive-payload checks for generated content and delivery payloads."""

from __future__ import annotations

import re
from typing import Any

from .models import GateFailure, GateResult


SECRET_PATTERNS = [
    ("OPENAI_API_KEY", r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    ("COOKIE", r"(?i)\b(cookie|sessionid|session|sessdata)\s*[:=]\s*['\"]?[^'\"\s;]{12,}"),
    ("BEARER_TOKEN", r"(?i)\bauthorization\s*[:=]\s*bearer\s+[A-Za-z0-9_\-.=]{20,}"),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ("TOKEN", r"(?i)\b(access_token|refresh_token|api[_-]?key|authorization)\s*[:=]\s*['\"]?[^'\"\s]{12,}"),
    ("PRIVATE_KEY", r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    ("WINDOWS_PRIVATE_PATH", r"[A-Za-z]:\\Users\\[^\\\n]+\\"),
    ("HERMES_PRIVATE_PATH", r"/root/\.hermes/"),
]


def redact_sensitive_value(value: str, keep_prefix: int = 4, keep_suffix: int = 4) -> str:
    value = str(value)
    if len(value) <= keep_prefix + keep_suffix:
        return "*" * len(value)
    return f"{value[:keep_prefix]}{'*' * 8}{value[-keep_suffix:]}"


def scan_text_for_secrets(text: str, rule_ref: str = "SEC1") -> GateResult:
    failures: list[GateFailure] = []
    for code, pattern in SECRET_PATTERNS:
        if re.search(pattern, str(text or "")):
            failures.append(
                GateFailure(
                    code=f"SECRET_{code}",
                    rule_ref=rule_ref,
                    severity="blocking",
                    message=f"Generated or delivery payload contains a {code.lower()}-like value.",
                    remediation="Remove or redact the sensitive value before draft, upload, or publish.",
                )
            )
    return GateResult("security_gate", "failed" if failures else "passed", failures)


def scan_publish_payload(payload: dict[str, Any]) -> GateResult:
    fields = []
    for key in ("title", "body", "summary", "description", "script", "subtitle", "platform_payload"):
        value = payload.get(key)
        if isinstance(value, dict):
            fields.append(str(value))
        elif value:
            fields.append(str(value))
    return scan_text_for_secrets("\n".join(fields))
