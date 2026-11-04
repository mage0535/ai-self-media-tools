import tempfile
from pathlib import Path

from content_platform.pipeline import Pipeline
from content_platform.store import Store


def _pipeline(root: Path) -> Pipeline:
    store = Store(root / "state.db")
    store.init()
    return Pipeline(store, {
        "data_dir": str(root),
        "generator": {"allow_fallback": True, "api_key_env": "__TEST_MISSING_KEY__"},
        "publishers": {"default": {"type": "file"}, "platforms": {"kuaishou": {"type": "file", "account": "acct"}}},
        "notifications": {"log_path": str(root / "notifications.jsonl")},
    })


def test_explicit_content_lane_survives_account_binding():
    """MED34: the overnight brief lane tags the reference samples; the rulebook id stays the account lane."""
    with tempfile.TemporaryDirectory() as tmp:
        job = _pipeline(Path(tmp)).create("AI 办公 落地", ["kuaishou"], {"lane": "real_world_ai_implementation"})
    assert job["brief"]["lane"] == "real_world_ai_implementation"
    assert job["brief"]["account_lane"] == "real_world_ai_implementation_v1"


def test_rulebook_lane_is_the_default_without_a_brief_lane():
    with tempfile.TemporaryDirectory() as tmp:
        job = _pipeline(Path(tmp)).create("AI 办公 落地", ["kuaishou"], {})
    assert job["brief"]["lane"] == "real_world_ai_implementation_v1"


def test_a_different_brief_lane_is_still_replaced_by_the_rulebook_lane():
    with tempfile.TemporaryDirectory() as tmp:
        job = _pipeline(Path(tmp)).create("AI 办公 落地", ["kuaishou"], {"lane": "pet_healing"})
    assert job["brief"]["lane"] == "real_world_ai_implementation_v1"
