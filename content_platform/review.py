import base64
import hashlib
import hmac
import json
import os
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

    def issue(self, job_id, action, ttl=86400, now=None):
        if action not in {"approve", "reject"}:
            raise ValueError("unsupported review action")
        timestamp = int(time.time() if now is None else now)
        body = _b64(json.dumps({"job_id": job_id, "action": action, "exp": timestamp + int(ttl)}, separators=(",", ":")).encode())
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
        return payload

