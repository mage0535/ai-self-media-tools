"""Authorized 72-hour outcome adapter.

This is intentionally a narrow projection boundary: it accepts database IDs only.
Receipt identity, quality evidence, timestamps and metrics come solely from
verifier-sealed records in ``OwnedLearningStore``.
"""
from __future__ import annotations

from .owned_learning import OwnedLearningStore


def ingest_authorized_outcome(
    store: OwnedLearningStore,
    *,
    authorization_grant_id: str,
    analytics_claim_id: str,
) -> dict:
    return store.record_outcome(
        authorization_grant_id=authorization_grant_id,
        analytics_claim_id=analytics_claim_id,
    )
