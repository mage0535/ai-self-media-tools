"""Tests for the zhihu-cli adapter."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from content_platform.zhihu_cli_adapter import ZhihuCliAdapter, ZhihuCliError, _to_int

HOT_PAYLOAD = [
    {
        "question": {
            "title": "为什么说闲鱼是国内暗网？",
            "url": "https://www.zhihu.com/question/2042557235679720474",
            "id": "2042557235679720474",
        },
        "reaction": {
            "new_pv": 50595,
            "new_pv_7_days": 1200,
            "new_answer_num": 2,
            "new_follow_num": 19,
        },
    },
    {
        "question": {"title": "如何评价人民网上线 Token 还是词元？", "url": "https://www.zhihu.com/question/2", "id": "2"},
        "reaction": {"new_pv": 18561, "new_pv_7_days": 0, "new_answer_num": 21, "new_follow_num": 6},
    },
]

SEARCH_PAYLOAD = {
    "data": [
        {
            "type": "article",
            "object": {
                "type": "article",
                "title": "做销售，如何用 AI CRM 提升效率？",
                "url": "https://api.zhihu.com/articles/2016832800469320768",
                "voteup_count": 3,
                "comment_count": 2,
                "author": {"name": "EC CRM"},
            },
        }
    ]
}


def _fake_binary(path: Path) -> str:
    exe = path / "fake_zhihu.py"
    exe.write_text("print('ok')\n", encoding="utf-8")
    return str(exe)


class TestZhihuCliAdapter:
    def test_fetch_hot_normalizes_items(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run_json", return_value=HOT_PAYLOAD):
            items = adapter.fetch_hot(limit=10)

        assert len(items) == 2
        assert items[0]["title"] == "为什么说闲鱼是国内暗网？"
        assert items[0]["source"] == "zhihu"
        assert items[0]["points"] == 50595
        assert items[0]["metric"]["new_answers"] == 2
        assert items[0]["metric"]["new_follows"] == 19

    def test_fetch_hot_handles_dict_wrapper(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run_json", return_value={"data": HOT_PAYLOAD}):
            items = adapter.fetch_hot(limit=5)
        assert len(items) == 2

    def test_fetch_hot_honors_limit(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run_json", return_value=HOT_PAYLOAD):
            items = adapter.fetch_hot(limit=1)
        assert len(items) == 1

    def test_search_normalizes_items(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run_json", return_value=SEARCH_PAYLOAD):
            items = adapter.search("AI 效率", limit=5)

        assert len(items) == 1
        assert items[0]["type"] == "article"
        assert items[0]["author"] == "EC CRM"
        assert items[0]["points"] == 3

    def test_binary_missing_raises(self):
        adapter = ZhihuCliAdapter(binary="/nonexistent/zhihu")
        try:
            adapter.fetch_hot()
        except ZhihuCliError as exc:
            assert "zhihu CLI not found" in str(exc)
        else:
            raise AssertionError("expected ZhihuCliError")

    def test_publish_pin_parses_id_and_url(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        stdout = "Pin published!  ID: 2069180398110765889\n  https://www.zhihu.com/pin/2069180398110765889\n"
        with patch.object(adapter, "_run", return_value=stdout):
            result = adapter.publish_pin("测试想法", content="正文")
        assert result["id"] == "2069180398110765889"
        assert "zhihu.com/pin" in result["url"]

    def test_delete_pin_runs_with_yes_flag(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run", return_value="Pin deleted") as run:
            assert adapter.delete_pin("123") is True
        run.assert_called_once_with(["delete-pin", "123", "-y"])

    def test_publish_ask_appends_question_mark_when_missing(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        stdout = "Question created!  ID: 123\n  https://www.zhihu.com/question/123\n"
        with patch.object(adapter, "_run", return_value=stdout) as run:
            adapter.publish_ask("如何学习 Python")
        assert run.call_args[0][0][1] == "如何学习 Python？"

    def test_publish_ask_keeps_existing_question_mark(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        stdout = "Question created!  ID: 123\n  https://www.zhihu.com/question/123\n"
        with patch.object(adapter, "_run", return_value=stdout) as run:
            adapter.publish_ask("如何学习 Python？")
        assert run.call_args[0][0][1] == "如何学习 Python？"

    def test_to_int_handles_variants(self):
        assert _to_int(None) == 0
        assert _to_int("50,595") == 50595
        assert _to_int(42) == 42
        assert _to_int("12.9") == 12
        assert _to_int("garbage") == 0
        assert _to_int(0) == 0

    def test_fetch_hot_rejects_non_list_data(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run_json", return_value={"data": {"count": 46}}):
            try:
                adapter.fetch_hot(limit=5)
            except ZhihuCliError as exc:
                assert "unexpected structure" in str(exc)
            else:
                raise AssertionError("expected ZhihuCliError for dict data")

    def test_search_rejects_non_list_data(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run_json", return_value={"data": {"total": 100}}):
            try:
                adapter.search("AI")
            except ZhihuCliError as exc:
                assert "unexpected structure" in str(exc)
            else:
                raise AssertionError("expected ZhihuCliError for dict data")

    def test_timeout_raises_zhihu_cli_error(self, tmp_path):
        adapter = ZhihuCliAdapter(binary=_fake_binary(tmp_path), timeout=1)
        with patch("content_platform.zhihu_cli_adapter.subprocess.run", side_effect=subprocess.TimeoutExpired("zhihu", 1)):
            try:
                adapter._run(["status"])
            except ZhihuCliError as exc:
                assert "timed out" in str(exc)
            else:
                raise AssertionError("expected ZhihuCliError on timeout")

    def test_login_with_cookie_no_check_auth_kwarg(self):
        adapter = ZhihuCliAdapter(binary="/fake/zhihu")
        with patch.object(adapter, "_run", return_value="Cookie saved") as run:
            assert adapter.login_with_cookie("z_c0=abc; _xsrf=def") is True
        run.assert_called_once_with(["login", "--cookie", "z_c0=abc; _xsrf=def"])
