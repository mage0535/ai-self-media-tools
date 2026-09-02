from content_platform.adapter_executor import execute_capability
from content_platform.capability_router import load_registry


def _capability():
    return next(item for item in load_registry()["capabilities"] if item["id"] == "postcheck")


def test_postcheck_capability_executes_for_verified_publication():
    result = execute_capability(
        _capability(),
        {
            "delivery_result": {"status": "published", "external_id": "post-1"},
            "publication_identity": {
                "passed": True, "platform_content_id": "post-1",
                "published_at": "2026-09-02T12:00:00+08:00",
            },
        },
    )

    assert result["status"] == "executed"
    assert result["contract_valid"] is True


def test_postcheck_capability_skips_draft_without_claiming_publication():
    result = execute_capability(_capability(), {"delivery_result": {"status": "drafted", "external_id": "draft-1"}})

    assert result["status"] == "skipped"
    assert result["reason"] == "non_publication_status:drafted"


def test_postcheck_capability_rejects_published_without_verified_identity():
    result = execute_capability(
        _capability(),
        {"delivery_result": {"status": "published", "external_id": "task-id"}, "publication_identity": {}},
    )

    assert result["status"] == "failed"
    assert "publication_identity_not_verified" in result["output"]["reason"]
