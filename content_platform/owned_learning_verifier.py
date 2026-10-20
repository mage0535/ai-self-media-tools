"""Verifier boundary for owned-learning evidence claims.

The application never treats a Python dict as authority.  A separately operated
postcheck/analytics verifier signs canonical claims with a secret unavailable to
the content-generation worker.  If no verifier key is configured, verification
fails closed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any


def canonical_claim(claim: dict[str, Any]) -> bytes:
    payload = {k: v for k, v in dict(claim or {}).items() if k != "signature"}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def claim_digest(claim: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_claim(claim)).hexdigest()


def sign_claim_for_verifier(claim: dict[str, Any], secret: bytes) -> dict[str, Any]:
    """Verifier-side helper. Do not call from content or publisher workers."""
    if not secret:
        raise ValueError("verifier_secret_missing")
    result = dict(claim or {})
    result["signature"] = hmac.new(secret, canonical_claim(result), hashlib.sha256).hexdigest()
    return result


def verify_claim(claim: dict[str, Any], *, expected_kind: str, secret_env: str = "OWNED_LEARNING_VERIFIER_SECRET") -> dict[str, Any]:
    secret = os.environ.get(secret_env, "").encode("utf-8")
    payload = dict(claim or {})
    signature = str(payload.get("signature") or "")
    if not secret or payload.get("kind") != expected_kind or not signature:
        raise ValueError("trusted_verifier_unavailable")
    expected = hmac.new(secret, canonical_claim(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("trusted_claim_signature_invalid")
    expires_at = str(payload.get("expires_at") or "")
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("trusted_claim_expiry_invalid") from exc
    if expires <= datetime.now(timezone.utc):
        raise ValueError("trusted_claim_expired")
    if not str(payload.get("issuer") or "").strip() or not str(payload.get("nonce") or "").strip():
        raise ValueError("trusted_claim_identity_invalid")
    return payload
