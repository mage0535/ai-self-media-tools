import pytest
from typing import cast

from content_platform.owned_learning import OwnedLearningStore
from content_platform.owned_learning_outcomes import ingest_authorized_outcome


def test_outcome_adapter_accepts_only_sealed_record_ids():
    class Store:
        def record_outcome(self, **kwargs):
            return kwargs

    assert ingest_authorized_outcome(cast(OwnedLearningStore, Store()), authorization_grant_id="grant:1", analytics_claim_id="analytics:1") == {"authorization_grant_id": "grant:1", "analytics_claim_id": "analytics:1"}


def test_outcome_adapter_cannot_accept_caller_constructed_receipt():
    with pytest.raises(TypeError):
        getattr(ingest_authorized_outcome, "__call__")(None, authorization_grant_id="grant:1", analytics_claim_id="analytics:1", receipt={"postcheck_verified": True})
