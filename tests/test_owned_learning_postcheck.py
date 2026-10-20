from content_platform.models import DeliveryResult
from content_platform.pipeline import Pipeline
from content_platform.store import Store


def test_publisher_success_is_not_postcheck_and_cannot_schedule_owned_outcome(tmp_path):
    store = Store(tmp_path / "state.db")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "feature_flags": {"content_package_v1": True}})
    job = store.create_job("x", ["youtube"])
    package = store.save_content_package({"content_package_id": "cp-test", "platform": "youtube", "account_id": "owned:acct", "content_type": "short", "topic": "x", "title": "x"}, job_id=job["id"])
    pipeline._save_delivery_result(job["id"], "youtube", DeliveryResult(ok=True, status="published", external_id="native-1"))
    receipt = store.publish_receipts(content_package_id=package["content_package_id"], platform="youtube")[0]
    assert receipt["payload"]["postcheck_verified"] is False
