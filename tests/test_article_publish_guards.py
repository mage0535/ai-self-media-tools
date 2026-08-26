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
    create = {"err_no": 0, "data": {"id": "draft-1"}}
    detail = {
            "err_no": 0,
            "data": {
                "id": "draft-1",
                "editor_visible": True,
                "inline_image_urls": [f"https://cdn.example/inline-{i}.jpg" for i in range(3)],
                "mapping_count": 3,
            },
        }
    with patch.object(publisher, "_cookie_and_csrf", return_value=("sessionid=x", "csrf", [])), patch.object(
        publisher, "_api", side_effect=[create, detail]
    ) as api:
        result = publisher.deliver(_article_job(tmp_path, public_images=True), "juejin")

    assert result.ok is True
    assert result.status == "drafted"


def test_juejin_uploads_local_assets_to_platform_before_draft(tmp_path):
    publisher = JuejinPublisher()
    job = _article_job(tmp_path, public_images=False)
    uploaded = ["https://p3-juejin.byteimg.com/cover.jpg", *[f"https://p3-juejin.byteimg.com/inline-{i}.jpg" for i in range(3)]]
    with patch.object(publisher, "_cookie_and_csrf", return_value=("sessionid=x", "csrf", [])), patch.object(
        publisher, "_upload_images", return_value=uploaded
    ) as upload, patch.object(
        publisher, "_api", side_effect=[
            {"err_no": 0, "data": {"id": "draft-local"}},
            {"err_no": 0, "data": {"mark_content": "\n".join(uploaded[1:]), "cover_image": uploaded[0]}},
        ]
    ):
        result = publisher.deliver(job, "juejin")
    assert result.ok is True
    assert result.status == "drafted"
    assert upload.call_count == 1


def test_juejin_blocks_partial_platform_image_upload_before_draft(tmp_path):
    publisher = JuejinPublisher()
    with patch.object(publisher, "_cookie_and_csrf", return_value=("sessionid=x", "csrf", [])), patch.object(
        publisher, "_upload_images", return_value=["https://cdn.example/cover.jpg", "", "https://cdn.example/two.jpg", "https://cdn.example/three.jpg"]
    ), patch.object(publisher, "_api") as api:
        result = publisher.deliver(_article_job(tmp_path, public_images=False), "juejin")
    assert result.ok is False
    assert result.status == "blocked"
    assert "3/4" in result.error
    api.assert_not_called()


def test_juejin_rejects_duplicate_local_media_before_upload(tmp_path):
    publisher = JuejinPublisher()
    job = _article_job(tmp_path, public_images=False)
    job["artifacts"][-1]["path"] = job["artifacts"][-2]["path"]
    with patch.object(publisher, "_upload_images") as upload:
        result = publisher.deliver(job, "juejin")
    assert result.ok is False
    assert "duplicate" in result.error
    upload.assert_not_called()


def test_juejin_writes_platform_cdn_and_renderer_evidence_to_contract(tmp_path):
    publisher = JuejinPublisher()
    job = _article_job(tmp_path, public_images=False)
    contract = tmp_path / "article_media_contract.json"
    contract.write_text(json.dumps({"handoff_contract": {"artifacts": [{"role": "cover"}, *[{"role": "section"} for _ in range(3)]]}}), encoding="utf-8")
    job["artifacts"].append({"kind": "article_media_contract", "path": str(contract)})
    uploaded = ["https://cdn.example/cover.jpg", *[f"https://cdn.example/inline-{i}.jpg" for i in range(3)]]
    with patch.object(publisher, "_cookie_and_csrf", return_value=("sessionid=x", "csrf", [])), patch.object(
        publisher, "_upload_images", return_value=uploaded
    ), patch.object(publisher, "_api", side_effect=[
        {"err_no": 0, "data": {"id": "draft-evidence"}},
        {"err_no": 0, "data": {"mark_content": "\n".join(uploaded[1:]), "cover_image": uploaded[0]}},
    ]):
        result = publisher.deliver(job, "juejin")
    saved = json.loads(contract.read_text(encoding="utf-8"))["handoff_contract"]
    assert result.ok is True
    assert saved["state"] == "handoff_ready"
    assert saved["platform_cdn_evidence"]["passed"] is True
    assert saved["target_renderer_evidence"]["verified"] is True


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
