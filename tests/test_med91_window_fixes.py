import json
from types import SimpleNamespace

import pytest

from content_platform import asset_semantic_review as review
from content_platform.overnight_batch import _is_transient_failure

JOB = "dc3dc314c78641bd95882b512000936d"
FALLBACK = {"provider": "custom:sensenova", "model": "sensenova-lite"}
DEFAULT = {"provider": "custom:gateway", "model": "gemini-flash"}


def _layout(tmp_path, signed=FALLBACK, record_job=JOB, config_route=FALLBACK):
    jobs = tmp_path / "jobs"
    directory = jobs / JOB
    directory.mkdir(parents=True)
    config = directory / "media-batch-config.json"
    config.write_text(json.dumps({"generator": {"hermes_command": "/bin/hermes",
        "hermes_provider": config_route["provider"], "hermes_model": config_route["model"]}}), encoding="utf-8")
    (directory / "media-batch.json").write_text(json.dumps({"identity": {"job_id": record_job,
        "payload": {"run_date": "2026-11-15", "trigger": "timer", "text_route": signed}}}), encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    role = home / "node-role.json"
    role.write_text(json.dumps({"role": "worker", "job_id": JOB, "route": DEFAULT}), encoding="utf-8")
    return jobs, config, role


@pytest.fixture(autouse=True)
def _owned_by_root(monkeypatch):
    # Tests do not run as root; ownership and mode are checked on the server.
    monkeypatch.setattr(review, "_private_root_file", lambda path: path.is_file() and not path.is_symlink())


def test_signed_fallback_route_of_the_same_job_is_accepted(tmp_path, monkeypatch):
    jobs, config, role = _layout(tmp_path)
    monkeypatch.setattr(review, "MEDIA_BATCH_JOBS", jobs)
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(config))
    monkeypatch.setenv("HERMES_HOME", str(role.parent))
    _, _, route = review.route_config()
    assert (route["hermes_provider"], route["hermes_model"]) == (FALLBACK["provider"], FALLBACK["model"])


@pytest.mark.parametrize("change", ["unsigned_route", "other_job_record", "config_elsewhere"])
def test_route_mismatch_still_blocks_without_the_signed_record(tmp_path, monkeypatch, change):
    if change == "unsigned_route":
        jobs, config, role = _layout(tmp_path, signed=DEFAULT)
    elif change == "other_job_record":
        jobs, config, role = _layout(tmp_path, record_job="f" * 32)
    else:
        jobs, config, role = _layout(tmp_path)
        moved = tmp_path / "media-batch-config.json"
        moved.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")
        config = moved
    monkeypatch.setattr(review, "MEDIA_BATCH_JOBS", jobs)
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(config))
    monkeypatch.setenv("HERMES_HOME", str(role.parent))
    with pytest.raises(ValueError, match="task_profile_route_mismatch"):
        review.route_config()


def test_socket_timeout_text_is_transient_but_policy_blocks_are_not():
    assert _is_transient_failure(TimeoutError("timed out"))
    assert not _is_transient_failure(ValueError("topic duplicates or overlaps recent channel history"))


def test_a_job_that_never_generated_is_not_duplicate_history():
    from content_platform.pipeline import Pipeline

    topic = "智能旅行规划系统 LangChain RAG 实战项目"
    ghost = {"id": "ghost", "topic": topic, "title": "", "body": "", "state": "created", "platforms": ["zhihu"]}
    done = {"id": "done", "topic": topic, "title": topic, "body": "正文", "state": "review_required", "platforms": ["zhihu"]}
    events = []

    def run(rows):
        store = SimpleNamespace(content_candidates=lambda **kwargs: list(rows),
                                record_event=lambda *args: events.append(args))
        fake = SimpleNamespace(content_hygiene_cfg={}, store=store)
        return Pipeline._content_hygiene(fake, {"id": "retry", "topic": topic, "brief": {}})

    assert run([ghost])["status"] != "blocked"
    assert run([ghost, done])["status"] == "blocked"
