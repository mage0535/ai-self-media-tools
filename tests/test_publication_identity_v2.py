from types import SimpleNamespace

from content_platform.publication_ledger import identity_from_delivery


def test_delivery_without_verified_postcheck_does_not_create_identity():
    result = SimpleNamespace(status="published", external_id="https://example.test/post/1", error="")
    assert identity_from_delivery("x", result) is None


def test_verified_delivery_creates_identity():
    result = SimpleNamespace(status="published", external_id="post-1", canonical_url="https://example.test/post/1", verification_level="postcheck_verified", error="")
    identity = identity_from_delivery("x", result, account_alias="x_main")
    assert identity["verification_level"] == "postcheck_verified"
