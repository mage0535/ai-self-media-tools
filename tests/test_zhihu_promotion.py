"""Tests for Zhihu companion pin generation and validation."""

import pytest

from content_platform.zhihu_promotion import (
    ZhihuPinValidationError,
    build_pin_text,
    publish_article_pin,
    validate_pin_payload,
)


def _job():
    return {
        "title": "I used AI to write tests for 30 days: four real traps",
        "topic": "AI test automation",
        "body": (
            "# I used AI to write tests for 30 days\n\n"
            "Thirty days ago I still wrote every unit test by hand. "
            "After I gave the first draft to AI, the first week failed because "
            "nobody had written acceptance criteria, review boundaries, or a "
            "fallback plan for flaky cases."
        ),
        "strategy_brief": {
            "reader_payoff": "a practical checklist for deciding which test work can be automated"
        },
    }


def test_build_pin_text_does_not_copy_article_opening():
    payload = build_pin_text(_job(), article_url="https://zhuanlan.zhihu.com/p/123")

    assert payload["title"] != _job()["title"]
    assert "Thirty days ago I still wrote every unit test by hand" not in payload["content"]
    assert "https://zhuanlan.zhihu.com/p/123" in payload["content"]
    assert payload["validation"]["passed"] is True
    assert payload["validation"]["metrics"]["source_overlap"] <= 0.22


def test_validate_pin_payload_rejects_article_excerpt():
    job = _job()
    payload = {
        "title": job["title"],
        "content": (
            "Thirty days ago I still wrote every unit test by hand. "
            "After I gave the first draft to AI, the first week failed because nobody had written acceptance criteria."
        ),
    }

    result = validate_pin_payload(job, payload, article_url="https://zhuanlan.zhihu.com/p/123")

    assert result["passed"] is False
    assert "pin_title_reuses_article_title" in result["failures"]
    assert "pin_content_too_similar_to_article" in result["failures"]
    assert "pin_contains_copied_article_fragment" in result["failures"]


def test_publish_requires_visible_article_url(monkeypatch):
    calls = []

    class FakeAdapter:
        def __init__(self, timeout=60):
            self.timeout = timeout

        def publish_pin(self, title, content="", images=None):
            calls.append((title, content, images))
            return {"id": "p1", "url": "https://www.zhihu.com/pin/p1"}

    monkeypatch.setattr("content_platform.zhihu_promotion.ZhihuCliAdapter", FakeAdapter)

    with pytest.raises(ZhihuPinValidationError):
        publish_article_pin(_job(), article_url="")

    assert calls == []


def test_publish_passes_validation_before_adapter(monkeypatch):
    calls = []

    class FakeAdapter:
        def __init__(self, timeout=60):
            self.timeout = timeout

        def publish_pin(self, title, content="", images=None):
            calls.append((title, content, images))
            return {"id": "p1", "url": "https://www.zhihu.com/pin/p1"}

    monkeypatch.setattr("content_platform.zhihu_promotion.ZhihuCliAdapter", FakeAdapter)

    result = publish_article_pin(_job(), article_url="https://zhuanlan.zhihu.com/p/123")

    assert result["id"] == "p1"
    assert result["validation"]["passed"] is True
    assert len(calls) == 1
