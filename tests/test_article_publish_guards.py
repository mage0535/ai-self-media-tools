import json
from pathlib import Path
from unittest.mock import patch

from content_platform.juejin_publisher import JuejinPublisher
from content_platform.zhihu_publisher import ZhihuPublisher


def _article_job(tmp_path: Path, *, public_images: bool = True):
    artifacts = []
    if public_images:
        artifacts.append({"kind": "cover", "url": "https://cdn.example/cover.jpg"})
        artifacts.extend({"kind": "image", "url": f"https://cdn.example/inline-{i}.jpg"} for i in range(3))
    else:
        cover = tmp_path / "cover.jpg"
        cover.write_bytes(b"\xff\xd8" + b"x" * 2048)
        artifacts.append({"kind": "cover", "path": str(cover)})
        for i in range(3):
            path = tmp_path / f"inline-{i}.jpg"
            path.write_bytes(b"\xff\xd8" + b"x" * 2048)
            artifacts.append({"kind": "image", "path": str(path)})
    return {
        "id": "article-1",
        "title": "AI 工具越用越乱时，先整理流程再添加工具",
        "body": (
            "problem\n\n![problem]()\n\n"
            "case\n\n![case]()\n\n"
            "method\n\n![method]()\n\n"
            + "This case explains a real self-media workflow repair with concrete decisions and channel-specific visual evidence. " * 120
        ),
        "artifacts": artifacts,
        "draft_meta": {
            "section_image_map": [
                {"section": "problem", "image": "inline-0.jpg", "purpose": "show problem", "adjacent_to_text": True},
                {"section": "case", "image": "inline-1.jpg", "purpose": "show case", "adjacent_to_text": True},
                {"section": "method", "image": "inline-2.jpg", "purpose": "show method", "adjacent_to_text": True},
            ],
            "visual_template_selection": {"selected": "case_story_v1"},
        },
    }


def test_juejin_blocks_incomplete_article_before_api_call():
    publisher = JuejinPublisher()
    with patch.object(publisher, "_api") as api:
        result = publisher.deliver({"id": "j1", "title": "只有标题", "body": "", "artifacts": []}, "juejin")

    assert result.ok is False
    assert result.status == "blocked"
    assert "juejin article package incomplete" in result.error
    api.assert_not_called()


def test_juejin_accepts_complete_public_image_package_to_draft(tmp_path):
    publisher = JuejinPublisher()
    with patch.object(publisher, "_cookie_and_csrf", return_value=("sessionid=x", "csrf", [])), patch.object(
        publisher, "_api", return_value={
            "err_no": 0,
            "data": {
                "id": "draft-1",
                "editor_visible": True,
                "inline_image_urls": [f"https://cdn.example/inline-{i}.jpg" for i in range(3)],
                "mapping_count": 3,
            },
        }
    ) as api:
        result = publisher.deliver(_article_job(tmp_path, public_images=True), "juejin")

    assert result.ok is True
    assert result.status == "drafted"
    api.assert_called_once()


def test_zhihu_blocks_incomplete_article_before_cookie_lookup():
    publisher = ZhihuPublisher()
    with patch("content_platform.zhihu_publisher.resolve_cookie_file") as resolve:
        result = publisher.deliver({"id": "z1", "title": "只有标题", "body": "", "artifacts": []}, "zhihu")

    assert result.ok is False
    assert result.status == "blocked"
    assert "zhihu article package incomplete" in result.error
    resolve.assert_not_called()


def test_zhihu_local_image_package_passes_article_guard_then_checks_cookie(tmp_path):
    publisher = ZhihuPublisher(cookie_dir=str(tmp_path / "cookies"))
    with patch("content_platform.zhihu_publisher.resolve_cookie_file", return_value=tmp_path / "missing_cookie.json"):
        result = publisher.deliver(_article_job(tmp_path, public_images=False), "zhihu")

    assert result.ok is False
    assert result.status == "blocked"
    assert "cookie not found" in result.error
