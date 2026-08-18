import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def _completed(payload):
    return type("Completed", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()


def test_zhihu_open_adapter_normalizes_trending_and_search(tmp_path: Path):
    from content_platform.zhihu_open_adapter import ZhihuOpenAdapter

    binary = tmp_path / "zhihu-search"
    binary.write_text("# fixture", encoding="utf-8")
    responses = [
        _completed({"data": {"Items": [{"Title": "知乎热榜话题", "Url": "https://zhihu.com/hot", "Heat": "123", "Rank": 2}]}}),
        _completed(
            {
                "data": {
                    "Items": [
                        {
                            "Title": "AI 工作流回答",
                            "Url": "https://zhihu.com/question/1/answer/2",
                            "VoteUpCount": "45",
                            "CommentCount": "6",
                            "ContentType": "Answer",
                            "AuthorName": "作者",
                            "ContentText": "正文摘要",
                        }
                    ]
                }
            }
        ),
    ]

    with patch("content_platform.zhihu_open_adapter.subprocess.run", side_effect=responses) as run:
        adapter = ZhihuOpenAdapter(binary=str(binary), timeout=9)
        hot = adapter.trending(limit=3, retries=0)
        search = adapter.search("AI 工作流", limit=5, scope="zhihu")

    assert hot == [{"title": "知乎热榜话题", "source": "zhihu", "url": "https://zhihu.com/hot", "points": 123, "metric": {"rank": 2}}]
    assert search[0]["source"] == "zhihu_open"
    assert search[0]["points"] == 45
    assert search[0]["comment_count"] == 6
    assert run.call_args_list[0].args[0][1:] == ["trending", "--limit", "3", "--format", "json"]
    assert run.call_args_list[1].args[0][1:] == ["search", "AI 工作流", "--scope", "zhihu", "--count", "5", "--format", "json"]


def test_zhihu_open_adapter_reports_cli_errors(tmp_path: Path):
    from content_platform.zhihu_open_adapter import ZhihuOpenAdapter, ZhihuOpenError

    binary = tmp_path / "zhihu-search"
    binary.write_text("# fixture", encoding="utf-8")
    completed = type("Completed", (), {"returncode": 2, "stdout": "", "stderr": "rate limit exceeded"})()

    with patch("content_platform.zhihu_open_adapter.subprocess.run", return_value=completed):
        with pytest.raises(ZhihuOpenError, match="rate limit"):
            ZhihuOpenAdapter(binary=str(binary), timeout=1).trending(limit=1, retries=0)


def test_zhihu_direct_source_prefers_open_adapter_before_cookie_cli():
    from content_platform.trends import DirectTrendSource

    with patch("content_platform.zhihu_open_adapter.ZhihuOpenAdapter.trending", return_value=[{"title": "Open topic", "source": "zhihu", "points": 9}]) as open_hot:
        with patch("content_platform.zhihu_cli_adapter.ZhihuCliAdapter.fetch_hot") as cookie_hot:
            items = DirectTrendSource("zhihu", {"limit": 5}).collect()

    assert items[0]["title"] == "Open topic"
    assert open_hot.called
    assert not cookie_hot.called


def test_zhihu_direct_source_falls_back_to_cookie_cli_when_open_adapter_fails():
    from content_platform.trends import DirectTrendSource

    with patch("content_platform.zhihu_open_adapter.ZhihuOpenAdapter.trending", side_effect=RuntimeError("open unavailable")):
        with patch("content_platform.zhihu_cli_adapter.ZhihuCliAdapter.fetch_hot", return_value=[{"title": "Cookie topic", "source": "zhihu", "points": 3}]):
            items = DirectTrendSource("zhihu", {"limit": 5}).collect()

    assert items[0]["title"] == "Cookie topic"


def test_zhihu_markdown_requires_cdn_url_for_every_section_image():
    from content_platform.zhihu_publisher import build_markdown_with_cdn

    body = "## One\n\n![one]()\n\n## Two\n\n![two]()"
    section_map = [
        {"section": "One", "purpose": "first"},
        {"section": "Two", "purpose": "second"},
    ]

    with pytest.raises(ValueError, match="cdn upload incomplete"):
        build_markdown_with_cdn(body, section_map, ["https://cdn.example/cover.jpg", "https://cdn.example/one.jpg"])


def test_zhihu_markdown_replaces_all_empty_image_markers():
    from content_platform.zhihu_publisher import build_markdown_with_cdn

    body = "## One\n\n![one]()\n\n## Two\n\n![two]()"
    section_map = [
        {"section": "One", "purpose": "first"},
        {"section": "Two", "purpose": "second"},
    ]

    markdown = build_markdown_with_cdn(
        body,
        section_map,
        ["https://cdn.example/cover.jpg", "https://cdn.example/one.jpg", "https://cdn.example/two.jpg"],
    )

    assert markdown.count("https://cdn.example/") == 3
    assert "![]()" not in markdown
