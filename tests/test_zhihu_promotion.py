"""Tests for zhihu pin promotion text building (no network)."""
from content_platform.zhihu_promotion import build_pin_text


class TestBuildPinText:
    def test_builds_title_and_content(self):
        job = {"title": "我用AI自动写测试30天：从怀疑到离不开", "body": "上个月我把测试全部交给AI。\n\n结果第一周就踩了坑。"}
        payload = build_pin_text(job, article_url="https://zhuanlan.zhihu.com/p/123")

        assert payload["title"] == "我用AI自动写测试30天：从怀疑到离不开"
        assert "上个月我把测试全部交给AI" in payload["content"]
        assert "完整拆解在专栏文章" in payload["content"]
        assert "https://zhuanlan.zhihu.com/p/123" in payload["content"]

    def test_handles_empty_body(self):
        payload = build_pin_text({"title": "标题"}, article_url="https://zhuanlan.zhihu.com/p/1")
        assert "完整拆解在专栏文章《标题》里" in payload["content"]
        assert "上个月" not in payload["content"]

    def test_appends_extra(self):
        payload = build_pin_text({"title": "T"}, extra="评论区聊聊你的看法")
        assert "评论区聊聊你的看法" in payload["content"]

    def test_whitespace_normalized(self):
        job = {"title": " 标题 ", "body": "第一段。\n\n\n第二段。"}
        payload = build_pin_text(job)
        assert payload["title"] == "标题"
        assert "第一段。 第二段。" in payload["content"]

    def test_strips_leading_md_title_from_body(self):
        job = {"title": "标题", "body": "# 标题\n\n正文从这里开始。"}
        payload = build_pin_text(job)
        assert "# 标题" not in payload["content"]
        assert "正文从这里开始" in payload["content"]

    def test_hook_clips_at_sentence_boundary(self):
        long_body = "第一句完。第二句也完。第三句是长句子没有任何标点符号只有内容一直延续超过一百二十字限制因此必须截断处理"
        job = {"title": "T", "body": long_body}
        payload = build_pin_text(job)
        assert "第一句完。" in payload["content"]

    def test_empty_title_does_not_produce_empty_brackets(self):
        payload = build_pin_text({"body": "正文内容。", "url": "x"}, article_url="https://zhuanlan.zhihu.com/p/9")
        assert "《》" not in payload["content"]
        assert "完整拆解在专栏文章里" in payload["content"]
