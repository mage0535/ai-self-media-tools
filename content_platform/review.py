import base64
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class ReviewTokens:
    def __init__(self, key_path):
        self.key_path = Path(key_path)

    def _key(self):
        if not self.key_path.exists():
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(os.urandom(32))
        return self.key_path.read_bytes()

    def issue(self, job_id, action, ttl=86400, now=None, *, continuation_sha256=None):
        if action == "original_knowledge":
            if (getattr(os, "geteuid", lambda: -1)() != 0 or not re.fullmatch("[0-9a-f]{16}", str(job_id))
                    or job_id in {"7b12e9aae980484b", "f8bb617683914cbe"} or not 0 < int(ttl) <= 1800
                    or not re.fullmatch("[0-9a-f]{64}", str(continuation_sha256 or ""))):
                raise PermissionError("root_original_knowledge_scope_or_budget_invalid")
        elif action == "internal_make":
            if os.geteuid() != 0 or job_id != "f8bb617683914cbe" or not 0 < int(ttl) <= 1800:
                raise PermissionError("fixed_root_internal_make_scope_or_budget_invalid")
        elif action not in {"approve", "reject"}:
            raise ValueError("unsupported review action")
        timestamp = int(time.time() if now is None else now)
        if action in {"internal_make", "original_knowledge"} and not 0 < timestamp + int(ttl) - time.time() <= 1800:
            raise PermissionError("internal_make_actual_lifetime_invalid")
        payload = {"job_id": job_id, "action": action, "exp": timestamp + int(ttl)}
        if continuation_sha256 is not None:
            if action not in {"internal_make", "original_knowledge"} or not isinstance(continuation_sha256, str) or len(continuation_sha256) != 64 or any(c not in "0123456789abcdef" for c in continuation_sha256):
                raise PermissionError("fixed_internal_make_continuation_sha_required")
            payload["continuation_sha256"] = continuation_sha256
        if action in {"internal_make", "original_knowledge"}:
            payload["nonce"] = os.urandom(16).hex()
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        signature = _b64(hmac.new(self._key(), body.encode(), hashlib.sha256).digest())
        return body + "." + signature

    def verify(self, token, expected_action, now=None):
        try:
            body, signature = token.split(".", 1)
            expected = _b64(hmac.new(self._key(), body.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise ValueError("invalid review token signature")
            payload = json.loads(_unb64(body))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid review token") from exc
        timestamp = int(time.time() if now is None else now)
        if payload.get("action") != expected_action:
            raise ValueError("review token action mismatch")
        if int(payload.get("exp", 0)) < timestamp:
            raise ValueError("review token expired")
        if expected_action in {"internal_make", "original_knowledge"} and not 0 < int(payload.get("exp", 0)) - time.time() <= 1800:
            raise ValueError("internal_make_actual_lifetime_invalid")
        return payload

