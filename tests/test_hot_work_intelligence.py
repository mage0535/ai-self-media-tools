import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_platform.hot_work_intelligence import (
    analyze_work,
    build_hot_work_parameter_pack,
    classify_logged_search_failure,
    logged_search_card_selector,
    enrich_bilibili_work,
    enrich_zhihu_work,
    load_samples,
    normalize_browser_cookies,
    parse_douyin_shipin_html,
    parse_bilibili_search_cards,
    parse_juejin_search_cards,
    parse_youtube_search_cards,
    parse_logged_short_video_search_text,
    parse_platform_search_evidence,
    parse_sogou_wechat_html,
    parse_tiktok_search_text,
    parse_twitter_search_cards,
    parse_xiaohongshu_search_text,
    should_use_regional_proxy,
    logged_search_artifact_stem,
    logged_search_url,
)


def test_bilibili_detail_enrichment_builds_strict_work_evidence():
    response = {
        "code": 0,
        "data": {
            "bvid": "BV17p3M6SEuo",
            "pubdate": 1788990000,
            "owner": {"mid": 12345},
            "stat": {"view": 5221, "like": 312, "danmaku": 44, "reply": 21, "favorite": 99, "share": 17},
        },
    }
    row = {
        "platform": "bilibili",
        "title": "AI工作流实测",
        "url": "https://www.bilibili.com/video/BV17p3M6SEuo/?spm_id_from=333",
        "query": "AI 工作流",
        "captured_at": "2026-09-10T12:22:12+00:00",
        "collector": "bilibili_logged_search",
    }

    enriched = enrich_bilibili_work(row, fetch_json=lambda _url: response)

    assert enriched["content_id"] == "BV17p3M6SEuo"
    assert enriched["canonical_url"] == "https://www.bilibili.com/video/BV17p3M6SEuo"
    assert enriched["account_lane"] == "AI 工作流"
    assert len(enriched["author_id_hash"]) == 64
    assert enriched["published_at"].endswith("+00:00")
    assert enriched["fetched_at"] == row["captured_at"]
    assert enriched["metric_observed_at"] == row["captured_at"]
    assert enriched["metrics"]["views"] == 5221
    assert enriched["metrics"]["favorites"] == 99
    assert len(enriched["raw_snapshot_sha256"]) == 64


def test_bilibili_visible_card_builds_strict_evidence_without_detail_api():
    rows = parse_bilibili_search_cards(
        [{
            "text": "AI自动化工作流实测",
            "href": "https://www.bilibili.com/video/BV17p3M6SEuo/?spm_id_from=333",
            "context": "AI自动化工作流实测\n示例作者\n· 5小时前\n5221\n12\n12:43",
        }],
        query="AI 自动化 工作流",
        captured_at="2026-09-10T12:22:12+00:00",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["content_id"] == "BV17p3M6SEuo"
    assert row["published_at"] == "2026-09-10T07:22:12+00:00"
    assert row["metrics"] == {"views": 5221, "danmaku": 12}
    assert row["detail_enrichment_status"] == "search_card_verified"
    assert len(row["author_id_hash"]) == 64
    assert len(row["raw_snapshot_sha256"]) == 64


def test_bilibili_detail_failure_preserves_complete_card_evidence():
    row = parse_bilibili_search_cards(
        [{
            "text": "AI自动化工作流实测",
            "href": "https://www.bilibili.com/video/BV17p3M6SEuo/",
            "context": "AI自动化工作流实测\n示例作者\n· 2026-09-10\n5221\n12\n12:43",
        }],
        query="AI 自动化 工作流",
        captured_at="2026-09-10T12:22:12+00:00",
    )[0]

    enriched = enrich_bilibili_work(row, fetch_json=lambda _url: (_ for _ in ()).throw(OSError("blocked")))

    assert enriched["content_id"] == "BV17p3M6SEuo"
    assert enriched["detail_enrichment_status"] == "search_card_verified_detail_unavailable"


def test_bilibili_login_navigation_does_not_turn_normal_search_into_login_wall():
    text = "登录\n登录后你可以\n综合排序\n最多播放\n最新发布\nAI工作流实测\n示例作者\n5小时前\n5221"

    assert classify_logged_search_failure(text, platform="bilibili") == "layout_changed_or_no_lane_results"
    assert classify_logged_search_failure("验证码 CAPTCHA", platform="bilibili") == "login_required_or_captcha"


def test_juejin_login_navigation_does_not_turn_normal_search_into_login_wall():
    text = "登录\n首页\n综合\n文章\n用户\n搜索结果\nAI自动化工作流"

    assert classify_logged_search_failure(text, platform="juejin") == "layout_changed_or_no_lane_results"
    assert classify_logged_search_failure("登录验证 CAPTCHA", platform="juejin") == "login_required_or_captcha"


def test_juejin_visible_card_builds_strict_recent_work_evidence():
    rows = parse_juejin_search_cards(
        [{
            "text": "AI Agent工作流实战",
            "href": "https://juejin.cn/post/7646622729529737256?searchId=abc",
            "context": "示例作者\n5天前\n人工智能\nAI Agent工作流实战\n本文介绍实际流程\n312\n21\n微博\n微信扫一扫",
        }],
        query="AI Agent 工作流",
        captured_at="2026-09-10T12:22:32+00:00",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["content_id"] == "7646622729529737256"
    assert row["canonical_url"] == "https://juejin.cn/post/7646622729529737256"
    assert row["published_at"] == "2026-09-05T12:22:32+00:00"
    assert row["metrics"] == {"engagement": 312}
    assert len(row["author_id_hash"]) == 64
    assert len(row["raw_snapshot_sha256"]) == 64


def test_juejin_visible_card_rejects_work_older_than_thirty_days():
    rows = parse_juejin_search_cards(
        [{
            "text": "AI Agent生态分析",
            "href": "https://juejin.cn/post/7646622729529737256",
            "context": "示例作者\n3月前\n人工智能\nAI Agent生态分析\n3\n微博\n微信扫一扫",
        }],
        query="AI Agent",
        captured_at="2026-09-10T12:22:32+00:00",
    )

    assert rows == []


def test_twitter_card_builds_strict_status_identity_time_and_metrics():
    rows = parse_twitter_search_cards(
        [{
            "href": "https://x.com/example_user/status/2097291801828942019",
            "context": "Example\n@example_user\nAI agents complete real workflow tasks\n5\n53\n117\n2.6万",
            "published_at": "2026-09-08T11:51:46.000Z",
            "metric_labels": ["5 Replies", "53 reposts", "117 Likes", "26K Views"],
        }],
        query="AI agents workflow",
        captured_at="2026-09-11T00:31:31+00:00",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["content_id"] == "2097291801828942019"
    assert row["canonical_url"] == "https://x.com/example_user/status/2097291801828942019"
    assert row["published_at"] == "2026-09-08T11:51:46+00:00"
    assert row["metrics"] == {"replies": 5, "reposts": 53, "likes": 117, "views": 26000}
    assert len(row["author_id_hash"]) == 64
    assert len(row["raw_snapshot_sha256"]) == 64


def test_twitter_card_parses_localized_combined_metric_label():
    rows = parse_twitter_search_cards(
        [{
            "href": "https://x.com/example_user/status/2097291801828942019",
            "context": "Example\n@example_user\nAI agents complete real workflow tasks",
            "published_at": "2026-09-08T11:51:46.000Z",
            "metric_labels": ["5 回复、53 次转帖、117 喜欢、9 书签、2.6万 次观看"],
        }],
        query="AI agents workflow",
        captured_at="2026-09-11T00:31:31+00:00",
    )

    assert rows[0]["metrics"] == {"replies": 5, "reposts": 53, "likes": 117, "views": 26000}


def test_zhihu_article_detail_builds_strict_recent_evidence():
    detail = '''
    <meta itemProp="datePublished" content="2026-09-05T08:10:13.000Z"/>
    <meta itemProp="commentCount" content="13"/>
    <script>{&quot;authorName&quot;:&quot;示例作者&quot;,&quot;voteupCount&quot;:103}</script>
    '''
    row = {
        "platform": "zhihu",
        "title": "AI Agent工作流实测",
        "url": "https://zhuanlan.zhihu.com/p/2066544914452543247",
        "query": "AI Agent 工作流",
        "captured_at": "2026-09-11T00:15:09+00:00",
        "collector": "zhihu_logged_search",
    }

    enriched = enrich_zhihu_work(row, fetch_text=lambda _url: detail)

    assert enriched["content_id"] == "2066544914452543247"
    assert enriched["published_at"] == "2026-09-05T08:10:13+00:00"
    assert enriched["metrics"] == {"votes": 103, "comments": 13}
    assert len(enriched["author_id_hash"]) == 64
    assert len(enriched["raw_snapshot_sha256"]) == 64


def test_zhihu_detail_failure_never_infers_date_from_content_id():
    row = {
        "platform": "zhihu",
        "title": "AI Agent回答",
        "url": "https://www.zhihu.com/question/1/answer/2078942166643107445",
        "query": "AI Agent",
        "captured_at": "2026-09-11T00:15:09+00:00",
        "collector": "zhihu_logged_search",
    }

    enriched = enrich_zhihu_work(row, fetch_text=lambda _url: (_ for _ in ()).throw(OSError("403")))

    assert enriched["detail_enrichment_status"] == "failed"
    assert "published_at" not in enriched


def test_logged_search_artifact_stem_keeps_distinct_chinese_queries_unique():
    first = logged_search_artifact_stem("xiaohongshu", "AI工作流")
    second = logged_search_artifact_stem("xiaohongshu", "AI效率工具")
    assert first != second
    assert first.startswith("xiaohongshu_AI_")


def test_juejin_search_uses_latest_sort_for_thirty_day_pool():
    url = logged_search_url("juejin", "AI Agent")

    assert "sort=1" in url
    assert "type=0" in url
    assert "query=AI%20Agent" in url


def test_youtube_search_uses_verified_this_month_filter():
    url = logged_search_url("youtube", "AI agent workflow")

    assert "sp=EgIIBA%253D%253D" in url


def test_youtube_dom_uses_full_video_renderer_as_card_container():
    selector = logged_search_card_selector("youtube")

    assert "ytd-video-renderer" in selector
    assert "ytd-rich-item-renderer" in selector
    assert '[class*="video"]' not in selector


def test_youtube_visible_card_builds_strict_month_work_evidence():
    rows = parse_youtube_search_cards(
        [{
            "text": "Build a Reliable AI Agent Workflow",
            "href": "https://www.youtube.com/watch?v=FwOTs4UxQS4&pp=abc",
            "context": "Build a Reliable AI Agent Workflow\nExample Channel\nExample Channel\n•\n•\n12K views\n6 days ago",
        }],
        query="AI agent workflow",
        captured_at="2026-09-11T08:00:00+00:00",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["content_id"] == "FwOTs4UxQS4"
    assert row["canonical_url"] == "https://www.youtube.com/watch?v=FwOTs4UxQS4"
    assert row["published_at"] == "2026-09-05T08:00:00+00:00"
    assert row["metrics"] == {"views": 12000}
    assert len(row["author_id_hash"]) == 64
    assert len(row["raw_snapshot_sha256"]) == 64


def test_youtube_real_card_order_and_login_navigation_are_supported():
    rows = parse_youtube_search_cards(
        [{
            "text": "How to Build an AI Assistant for Work",
            "href": "https://www.youtube.com/watch?v=Video12345A",
            "context": "How to Build an AI Assistant for Work\n2.4万次观看\n5天前\nExample Channel\nA practical workflow",
        }],
        query="AI Assistant Work",
        captured_at="2026-09-11T08:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["metrics"]["views"] == 24000
    assert classify_logged_search_failure(
        "登录\n首页\nShorts\n最近上传\n过滤\n5次观看\n1天前",
        platform="youtube",
    ) == "layout_changed_or_no_lane_results"


def test_save_collection_writes_latest_to_mutable_data_root(tmp_path, monkeypatch):
    from pathlib import Path
    from content_platform.hot_work_intelligence import save_collection

    mutable = tmp_path / "mutable"
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(mutable))
    paths = save_collection([], [], tmp_path / "run")

    assert Path(paths["latest"]) == mutable / "intel" / "hot_work_parameter_pack_latest.json"
    assert Path(paths["latest"]).is_file()


def test_save_collection_can_isolate_explicit_canary_output_without_overwriting_latest(tmp_path, monkeypatch):
    from content_platform.hot_work_intelligence import save_collection

    mutable = tmp_path / "production-data"
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(mutable))
    paths = save_collection([], [], tmp_path / "canary", publish_latest=False)

    assert paths["latest"] == ""
    assert not (mutable / "intel" / "hot_work_parameter_pack_latest.json").exists()


def test_normalize_browser_cookies_converts_extension_exports_to_playwright_state():
    cookies = [{
        "domain": ".tiktok.com",
        "expirationDate": 1785775116,
        "httpOnly": False,
        "name": "sessionid",
        "path": "/",
        "sameSite": "unspecified",
        "secure": True,
        "value": "secret",
    }]
    state = normalize_browser_cookies(cookies)
    assert state["cookies"][0]["expires"] == 1785775116
    assert "sameSite" not in state["cookies"][0]
    assert state["cookies"][0]["domain"] == ".tiktok.com"


def test_parse_sogou_wechat_html_extracts_titles_and_links():
    html = """<li><div class='txt-box'><h3><a href='http://mp.weixin.qq.com/s/abc'>Claude Code Skills 完全指南</a></h3><p class='txt-info'>先晒效果，再讲安装步骤</p><a account_name='x'>AI日报</a></div></li>"""
    rows = parse_sogou_wechat_html(html, query="Claude Code")
    assert rows[0]["platform"] == "wechat"
    assert "Claude Code" in rows[0]["title"]
    assert rows[0]["url"].startswith("http://mp.weixin.qq.com")
    assert rows[0]["analysis"]["hook_types"]


def test_parse_xiaohongshu_search_text_extracts_note_cards():
    text = """
首页
全部
图文
让Codex起飞的10个技巧，我用的很爽！
知野AI实践
06-07
1459
Claude Code vs Codex，用了3个月说真话
数据分析Chen
08-14
56
"""
    rows = parse_xiaohongshu_search_text(
        text,
        query="AI工具",
        anchors=[
            {"text": "让Codex起飞的10个技巧，我用的很爽！", "href": "https://www.xiaohongshu.com/explore/a1"},
            {"text": "Claude Code vs Codex，用了3个月说真话", "href": "https://www.xiaohongshu.com/explore/a2"},
        ],
    )
    assert len(rows) == 2
    assert rows[0]["engagement"] == "1459"
    assert rows[0]["evidence_strength"] == "strong_logged_search_result"
    assert rows[0]["url"] == "https://www.xiaohongshu.com/explore/a1"
    assert rows[0]["captured_at"]
    assert rows[0]["collector"] == "xiaohongshu_logged_search"


def test_parse_tiktok_search_text_extracts_video_cards():
    text = """
Top
Videos
1537
This is the exact roadmap I followed to go from zero to working as an AI automation consultant — no degree.
willautomated
6-14
24.9K
comment Claude Plugins Claude Code just leveled up with 5 must-have plugins
Miles Reeves
8-7
"""
    rows = parse_tiktok_search_text(text, query="AI workflow automation")
    assert len(rows) == 2
    assert rows[1]["engagement"] == "24.9K"
    assert rows[1]["platform"] == "tiktok"


def test_parse_douyin_shipin_html_extracts_related_recommendations_and_transcript():
    html = """<script>{"relatedRecommend":[{"awemeId":"764","itemId":"764","text":"ClaudeCode和Codex到底选哪个？ #AI","nickname":"Josh的AI笔记","diggCount":11604,"videoUrl":"https://www.douyin.com/video/764","duration":189834}]}</script><p class='Sq8uF5cI' data-e2e='ai-text'>为什么大家都放弃 Claude Code，开始用 Codex 了？</p>"""
    rows = parse_douyin_shipin_html(html, query="Claude Code Codex", platform="douyin_ai")
    titles = [row["title"] for row in rows]
    assert any("ClaudeCode" in title for title in titles)
    assert any(row["source"] == "douyin_shipin_ai_transcript" for row in rows)


def test_build_hot_work_parameter_pack_requires_strong_platform_samples():
    samples = [
        {"platform": "xiaohongshu", "title": "让Codex起飞的10个技巧", "author": "A", "engagement": "1459", "url": "https://www.xiaohongshu.com/explore/a", "captured_at": "2026-08-26T00:00:00+00:00", "collector": "xiaohongshu_logged_search", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("让Codex起飞的10个技巧")},
        {"platform": "xiaohongshu", "title": "AI工作流一图看懂", "author": "B", "engagement": "707", "url": "https://www.xiaohongshu.com/explore/b", "captured_at": "2026-08-26T00:00:00+00:00", "collector": "xiaohongshu_logged_search", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("AI工作流一图看懂")},
        {"platform": "xiaohongshu", "title": "Claude Code vs Codex", "author": "C", "engagement": "56", "url": "https://www.xiaohongshu.com/explore/c", "captured_at": "2026-08-26T00:00:00+00:00", "collector": "xiaohongshu_logged_search", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("Claude Code vs Codex")},
    ]
    pack = build_hot_work_parameter_pack(samples, platforms=["xiaohongshu"])
    assert pack["platforms"]["xiaohongshu"]["ready"] is True
    assert pack["platforms"]["xiaohongshu"]["recommended_patterns"]


def test_default_parameter_pack_covers_every_publishing_platform_from_registry():
    from content_platform.platform_intelligence_registry import publishing_platforms

    pack = build_hot_work_parameter_pack([])

    assert set(pack["platforms"]) == set(publishing_platforms())

    with_reference = build_hot_work_parameter_pack([{
        "platform": "weibo", "title": "AI 工作流", "identity_role": "cross_platform_reference",
        "url": "https://s.weibo.com/weibo?q=ai", "heat": 1000,
        "captured_at": "2026-09-08T00:00:00+00:00", "collector": "wewrite_aggregate",
    }])
    assert set(with_reference["platforms"]) == set(publishing_platforms())


def test_cross_platform_references_inform_but_never_make_target_ready():
    samples = [{
        "platform": "weibo",
        "title": "AI 工作流进入团队协作讨论",
        "source": "wewrite_aggregate:weibo",
        "url": "https://s.weibo.com/weibo?q=ai",
        "heat": 900000,
        "captured_at": "2026-09-08T00:00:00+00:00",
        "identity_role": "cross_platform_reference",
    }]

    pack = build_hot_work_parameter_pack(samples, platforms=["wechat"])

    assert pack["platforms"]["wechat"]["ready"] is False
    assert pack["platforms"]["wechat"]["strong_sample_count"] == 0
    assert pack["platforms"]["wechat"]["cross_platform_references"][0]["platform"] == "weibo"
    score = pack["platforms"]["wechat"]["cross_platform_references"][0]["intelligence_score"]
    assert score["target_ready_eligible"] is False
    assert score["dimensions"]["lane_fit"] > 0


def test_parameter_pack_does_not_mark_incomplete_labeled_rows_ready():
    samples = [
        {"platform": "zhihu", "title": f"AI 工作流 {index}", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("AI 工作流")}
        for index in range(3)
    ]
    pack = build_hot_work_parameter_pack(samples, platforms=["zhihu"])
    assert pack["platforms"]["zhihu"]["ready"] is False
    assert pack["platforms"]["zhihu"]["strong_sample_count"] == 0


def test_platform_anchor_parser_rejects_navigation_and_requires_real_url_and_metric():
    anchors = [
        {"text": "AI Works", "href": "https://www.zhihu.com/ai"},
        {"text": "狂烧 40 亿 tokens，公开我的 7 套 AI 工作流！", "href": "https://www.zhihu.com/question/1/answer/2"},
    ]
    text = "AI Works\n狂烧 40 亿 tokens，公开我的 7 套 AI 工作流！\n赞同 49\n3 条评论"
    rows = parse_platform_search_evidence(text, anchors=anchors, platform="zhihu", query="AI 工作流")
    assert [row["title"] for row in rows] == ["狂烧 40 亿 tokens，公开我的 7 套 AI 工作流！"]
    assert rows[0]["url"].endswith("/answer/2")
    assert rows[0]["engagement"] == "49"


def test_platform_anchor_parser_rejects_server_error_page():
    rows = parse_platform_search_evidence(
        "出错了\n抱歉，服务器出现问题，请重试。",
        anchors=[{"text": "AI workflow", "href": "https://www.tiktok.com/tag/ai"}],
        platform="tiktok",
        query="AI workflow",
    )
    assert rows == []


def test_hot_work_proxy_fallback_only_for_classified_platform_or_network_failure():
    assert should_use_regional_proxy({"status": "platform_error_or_rate_limited"}) is True
    assert should_use_regional_proxy({"status": "login_required_or_captcha"}) is False
    assert should_use_regional_proxy({"status": "layout_changed_or_no_lane_results"}) is False


def test_platform_anchor_parser_rejects_ads_profiles_and_year_as_metric():
    text = """
AI 办公助手效率起飞
9000
AI 工作流作者主页
397
ComfyUI AI 工作流实战
· 2024-04-22
播放 1888
"""
    rows = parse_platform_search_evidence(
        text,
        anchors=[
            {"text": "AI 办公助手效率起飞", "href": "https://cm.bilibili.com/cm/api/fees/pc/sync"},
            {"text": "AI 工作流作者主页", "href": "https://www.bilibili.com/12345"},
            {"text": "ComfyUI AI 工作流实战", "href": "https://www.bilibili.com/video/BV123"},
        ],
        platform="bilibili",
        query="AI 工作流",
    )
    assert [row["title"] for row in rows] == ["ComfyUI AI 工作流实战"]
    assert rows[0]["engagement"] == "1888"


def test_platform_anchor_parser_deduplicates_same_content_url():
    url = "https://juejin.cn/post/123?searchId=abc"
    text = "AI 工作流实战\n赞 140\nAI 工作流实战的详细摘要和实现步骤\n赞 140"
    rows = parse_platform_search_evidence(
        text,
        anchors=[
            {"text": "AI 工作流实战", "href": url},
            {"text": "AI 工作流实战的详细摘要和实现步骤", "href": url},
        ],
        platform="juejin",
        query="AI 工作流",
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "AI 工作流实战"


def test_platform_anchor_parser_does_not_extract_year_from_excerpt():
    rows = parse_platform_search_evidence(
        "AI 编程工作流实践\n根据 2025 年报告效率提高\n作者\n1年前\n前端 AI编程",
        anchors=[{"text": "AI 编程工作流实践", "href": "https://juejin.cn/post/123"}],
        platform="juejin",
        query="AI 工作流",
    )
    assert rows == []


def test_parameter_pack_only_exposes_contract_complete_top_samples():
    complete = {"platform": "youtube", "title": "AI workflow demo", "engagement": "100", "url": "https://www.youtube.com/watch?v=1", "captured_at": "2026-08-26T00:00:00+00:00", "collector": "youtube_logged_search", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("AI workflow demo")}
    incomplete = {"platform": "youtube", "title": "AI profile", "engagement": "999", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("AI profile")}
    pack = build_hot_work_parameter_pack([incomplete, complete], platforms=["youtube"], min_strong_samples=1)
    assert pack["platforms"]["youtube"]["sample_count"] == 2
    assert [row["title"] for row in pack["platforms"]["youtube"]["top_samples"]] == ["AI workflow demo"]


def test_load_samples_accepts_platform_grouped_logged_exports(tmp_path):
    path = tmp_path / "samples.json"
    path.write_text('{"xiaohongshu":[{"title":"AI效率卡片","evidence_strength":"strong_logged_search_result"}],"tiktok":[{"title":"AI workflow demo","platform":"tiktok"}]}', encoding="utf-8")
    rows = load_samples(path)
    assert len(rows) == 2
    assert rows[0]["platform"] == "xiaohongshu"
    assert rows[1]["platform"] == "tiktok"


def test_parse_logged_short_video_search_rejects_login_noise_and_keeps_lane_titles():
    text = """
登录即可享受更多精彩
服务器出错，请刷新重试
www.kuaishou.com 2026 @ All rights Reserved 京ICP备15023266号-136
举报邮箱： support@kuaishou.com
Claude Code 自动化工作流，普通人也能照着做
作者A
猫咪治愈短片：拆家前的三个信号
"""
    rows = parse_logged_short_video_search_text(text, platform="kuaishou", query="AI 自动化")
    assert [row["title"] for row in rows] == [
        "Claude Code 自动化工作流，普通人也能照着做",
        "猫咪治愈短片：拆家前的三个信号",
    ]


def test_shipinhao_parser_requires_official_content_url_and_visible_engagement():
    from content_platform import hot_work_intelligence as hot_work

    cards = [
        {
            "title": "3 个 AI 工作流让周报自动完成",
            "href": "https://channels.weixin.qq.com/web/pages/feed?object_id=123&nonce_id=abc",
            "visible_text": "3 个 AI 工作流让周报自动完成\n播放 12.8万\n点赞 3580\n评论 96",
        },
        {
            "title": "视频号创作平台",
            "href": "https://channels.weixin.qq.com/platform",
            "visible_text": "视频号创作平台\n数据中心",
        },
        {
            "title": "没有可见互动的 AI 教程",
            "href": "https://channels.weixin.qq.com/post/456",
            "visible_text": "没有可见互动的 AI 教程",
        },
    ]

    rows = hot_work.parse_shipinhao_hot_work_cards(cards, query="AI 工作流")

    assert len(rows) == 1
    assert rows[0]["platform"] == "shipinhao"
    assert rows[0]["url"].startswith("https://channels.weixin.qq.com/")
    assert rows[0]["engagement"] == "12.8万"
    assert rows[0]["visible_engagement"]["plays"] == "12.8万"
    assert rows[0]["visible_engagement"]["likes"] == "3580"


def test_shipinhao_evidence_is_fail_closed_for_login_only_page():
    from content_platform import hot_work_intelligence as hot_work

    rows, status = hot_work.finalize_shipinhao_hot_work_evidence(
        "视频号助手\n已登录\n内容管理\n发表视频",
        [],
        query="AI 工作流",
        page_url="https://channels.weixin.qq.com/platform",
        dom_snapshot_path="/private/run/shipinhao_search.html",
        screenshot_path="/private/run/shipinhao_search.png",
        captured_at="2026-08-27T01:02:03+00:00",
    )

    assert rows == []
    assert status["status"] == "layout_changed_or_no_real_hot_works"
    assert status["count"] == 0


def test_shipinhao_evidence_detects_login_redirect_from_final_url():
    from content_platform import hot_work_intelligence as hot_work

    rows, status = hot_work.finalize_shipinhao_hot_work_evidence(
        "视频号助手",
        [],
        query="AI 工作流",
        page_url="https://channels.weixin.qq.com/login.html",
        dom_snapshot_path="/private/run/shipinhao_login.html",
        screenshot_path="/private/run/shipinhao_login.png",
        captured_at="2026-09-06T04:19:25+00:00",
    )

    assert rows == []
    assert status["status"] == "login_required_or_captcha"


def test_shipinhao_evidence_attaches_dom_screenshot_and_collection_time():
    from content_platform import hot_work_intelligence as hot_work

    rows, status = hot_work.finalize_shipinhao_hot_work_evidence(
        "AI Agent 实战\n观看 8600\n点赞 321",
        [{
            "title": "AI Agent 实战",
            "href": "https://channels.weixin.qq.com/post/789",
            "visible_text": "AI Agent 实战\n观看 8600\n点赞 321",
        }],
        query="AI Agent",
        page_url="https://channels.weixin.qq.com/platform/content/discovery",
        dom_snapshot_path="/private/run/shipinhao_search.html",
        screenshot_path="/private/run/shipinhao_search.png",
        captured_at="2026-08-27T01:02:03+00:00",
    )

    assert status["status"] == "ok"
    assert status["count"] == 1
    assert rows[0]["dom_snapshot_path"] == status["dom_snapshot_path"]
    assert rows[0]["screenshot_path"] == status["screenshot_path"]
    assert rows[0]["captured_at"] == "2026-08-27T01:02:03+00:00"


def test_shipinhao_collector_resolves_existing_private_storage_state(tmp_path, monkeypatch):
    from scripts import shipinhao_hot_work_collector as collector

    social_root = tmp_path / "social-auto-upload"
    state = social_root / "cookies" / "tencent_uploader" / "main.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    monkeypatch.delenv("SHIPINHAO_STORAGE_STATE", raising=False)
    monkeypatch.setenv("SOCIAL_AUTO_UPLOAD_DIR", str(social_root))

    assert collector.resolve_state_file(None) == state


def test_shipinhao_collector_script_is_directly_executable():
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "shipinhao_hot_work_collector.py"), "--help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--state-file" in result.stdout


def test_default_hot_work_queries_follow_platform_lane():
    from content_platform.hot_work_intelligence import default_platform_queries

    assert any("AI" in query for query in default_platform_queries("bilibili"))
    assert any("AI" in query for query in default_platform_queries("xiaohongshu"))
    assert any("AI" in query for query in default_platform_queries("youtube"))
    assert any("AI" in query for query in default_platform_queries("shipinhao"))
    assert any("cat" in query.casefold() or "猫" in query for query in default_platform_queries("douyin_pet"))
    assert all("猫咪治愈" not in query for query in default_platform_queries("twitter"))


def test_logged_search_state_is_auto_discovered_and_converted(tmp_path, monkeypatch):
    from content_platform.hot_work_intelligence import resolve_logged_search_state

    cookie = tmp_path / "twitter_main.json"
    cookie.write_text('[{"name":"auth_token","value":"secret","domain":".x.com","path":"/"}]', encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_COOKIE_DIRS", str(tmp_path))

    result = resolve_logged_search_state("twitter", tmp_path / "private-states", cookie_dir=str(tmp_path))

    assert result["status"] == "ready"
    assert result["source_format"] == "cookie_list"
    state = Path(result["state_file"])
    assert state.is_file()
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["cookies"][0]["name"] == "auth_token"


def test_logged_search_state_reports_missing_without_writing(tmp_path, monkeypatch):
    from content_platform.hot_work_intelligence import resolve_logged_search_state
    from content_platform import auth_registry

    monkeypatch.setenv("CONTENT_PLATFORM_COOKIE_DIRS", str(tmp_path / "missing"))
    monkeypatch.setattr(auth_registry, "DEFAULT_SEARCH_DIRS", [])

    result = resolve_logged_search_state("xiaohongshu", tmp_path / "private-states", cookie_dir=str(tmp_path / "missing"))

    assert result == {"status": "unavailable", "reason": "valid_private_cookie_state_not_found", "state_file": ""}
    assert not (tmp_path / "private-states").exists()


def test_dynamic_page_wait_only_applies_to_unready_logged_search():
    from content_platform.hot_work_intelligence import needs_dynamic_content_wait

    assert needs_dynamic_content_wait("") is True
    assert needs_dynamic_content_wait("首页 搜索 通知 关注") is True
    assert needs_dynamic_content_wait("AI agent workflow\n12K views\nA complete result with enough visible detail") is False


def test_twitter_cards_use_article_context_and_canonical_status_url():
    from content_platform.hot_work_intelligence import parse_twitter_search_cards

    context = (
        "Lunar @LunarResearcher · 9月1日\n"
        "吴恩达发布完整 AI 智能体工作流课程，从提示扩展到多智能体循环\n"
        "22\n168\n836\n10万"
    )
    rows = parse_twitter_search_cards(
        [
            {"text": "9月1日", "href": "https://x.com/LunarResearcher/status/2094501861885649354", "context": context},
            {"text": "10万", "href": "https://x.com/LunarResearcher/status/2094501861885649354/analytics", "context": context},
        ],
        query="AI agents workflow",
    )

    assert len(rows) == 1
    assert rows[0]["title"].startswith("吴恩达发布完整 AI 智能体工作流课程")
    assert rows[0]["url"] == "https://x.com/LunarResearcher/status/2094501861885649354"
    assert rows[0]["engagement"] == "10万"


def test_xiaohongshu_ip_risk_is_a_proxy_eligible_platform_error():
    from content_platform.hot_work_intelligence import classify_logged_search_failure

    status = classify_logged_search_failure("安全限制\nIP存在风险，请切换可靠网络环境后重试\n300012")

    assert status == "platform_error_or_rate_limited"
    assert should_use_regional_proxy({"status": status}) is True


def test_tiktok_server_problem_is_retryable_then_proxy_eligible():
    from content_platform.hot_work_intelligence import classify_logged_search_failure, should_retry_logged_page

    text = "出错了\n抱歉，服务器出现问题，请重试。\n重试"
    status = classify_logged_search_failure(text)

    assert should_retry_logged_page(text) is True
    assert status == "platform_error_or_rate_limited"
    assert should_use_regional_proxy({"status": status}) is True


def test_kuaishou_result_two_is_classified_as_expired_auth_not_empty_layout():
    from content_platform.hot_work_intelligence import classify_logged_search_failure

    status = classify_logged_search_failure('{"result":2,"error_msg":null,"request_id":"123"}')

    assert status == "login_required_or_captcha"
    assert should_use_regional_proxy({"status": status}) is False


def test_tiktok_cards_bind_visible_metric_copy_and_video_url():
    from content_platform.hot_work_intelligence import parse_tiktok_search_cards

    rows = parse_tiktok_search_cards([{
        "text": "",
        "href": "https://www.tiktok.com/@elowen.hu/video/7664520654162627862",
        "context": "14.3K\nYour job just got an AI assistant. Here are the best AI productivity tools you can use today.\nElowen Hu\n7-20",
    }], query="AI tools workflow")

    assert len(rows) == 1
    assert rows[0]["engagement"] == "14.3K"
    assert rows[0]["title"].startswith("Your job just got an AI assistant")
    assert rows[0]["url"] == "https://www.tiktok.com/@elowen.hu/video/7664520654162627862"


def test_verified_logged_search_cache_round_trip_and_tamper_rejection(tmp_path):
    from content_platform.hot_work_intelligence import load_logged_search_cache, save_logged_search_cache

    text = tmp_path / "search.txt"
    screenshot = tmp_path / "search.png"
    text.write_text("visible TikTok AI workflow result", encoding="utf-8")
    screenshot.write_bytes(b"png-evidence")
    now = datetime(2026, 9, 6, 0, 30, tzinfo=timezone.utc)
    rows = [{
        "platform": "tiktok", "title": "AI workflow result", "url": "https://www.tiktok.com/@user/video/123",
        "engagement": "14.3K", "captured_at": now.isoformat(), "evidence_strength": "strong_logged_search_result",
    }]
    status = {"status": "ok", "text_path": str(text), "screenshot_path": str(screenshot), "route": "direct"}

    saved = save_logged_search_cache(tmp_path / "cache", "tiktok", "AI tools workflow", rows, status, now=now)
    loaded = load_logged_search_cache(tmp_path / "cache", "tiktok", "AI tools workflow", now=now + timedelta(hours=1))

    assert saved["saved"] is True
    assert loaded["status"] == "ready"
    assert loaded["rows"][0]["evidence_strength"] == "strong_cached_native_search"
    text.write_text("tampered", encoding="utf-8")
    assert load_logged_search_cache(tmp_path / "cache", "tiktok", "AI tools workflow", now=now + timedelta(hours=1))["status"] == "invalid"


def test_verified_logged_search_cache_expires(tmp_path):
    from content_platform.hot_work_intelligence import load_logged_search_cache, save_logged_search_cache

    text = tmp_path / "search.txt"
    screenshot = tmp_path / "search.png"
    text.write_text("visible X AI workflow result", encoding="utf-8")
    screenshot.write_bytes(b"png-evidence")
    now = datetime(2026, 9, 6, 0, 30, tzinfo=timezone.utc)
    rows = [{
        "platform": "twitter", "title": "AI workflow result", "url": "https://x.com/user/status/123",
        "engagement": "10K", "captured_at": now.isoformat(), "evidence_strength": "strong_logged_search_result",
    }]
    status = {"status": "ok", "text_path": str(text), "screenshot_path": str(screenshot), "route": "direct"}
    save_logged_search_cache(tmp_path / "cache", "twitter", "AI workflow", rows, status, now=now)

    loaded = load_logged_search_cache(tmp_path / "cache", "twitter", "AI workflow", max_age_hours=6, now=now + timedelta(hours=7))

    assert loaded["status"] == "expired"
    assert loaded["rows"] == []


def test_zhihu_cards_bind_title_votes_and_canonical_content_url():
    from content_platform.hot_work_intelligence import parse_zhihu_search_cards

    rows = parse_zhihu_search_cards([{
        "text": "2026年Agent工作流开发指南，轻松掌握核心技术",
        "href": "https://zhuanlan.zhihu.com/p/2066544914452543247?zpf=tracking",
        "context": "2026年Agent工作流开发指南，轻松掌握核心技术\nAI技能研究所\n赞同 79\n12 条评论\n08-10",
    }], query="AI工具 工作流")

    assert len(rows) == 1
    assert rows[0]["engagement"] == "79"
    assert rows[0]["url"] == "https://zhuanlan.zhihu.com/p/2066544914452543247"


def test_douyin_official_board_requires_specific_lane_fit():
    from content_platform.hot_work_intelligence import build_douyin_official_row, filter_douyin_official_board

    rows = [
        {"title": "AI展现不了安徽的美", "points": 9000000, "rank": 10, "url": "https://www.douyin.com/search/a"},
        {"title": "AI Agent效率工具实测", "points": 8000000, "rank": 12, "url": "https://www.douyin.com/search/b"},
        {"title": "小猫拆家现场", "points": 7000000, "rank": 15, "url": "https://www.douyin.com/search/c"},
    ]

    ai = filter_douyin_official_board(rows, "douyin_ai")
    pet = filter_douyin_official_board(rows, "douyin_pet")

    assert [row["title"] for row in ai] == ["AI Agent效率工具实测"]
    assert [row["title"] for row in pet] == ["小猫拆家现场"]
    contract = build_douyin_official_row(rows, "douyin_ai", captured_at=datetime(2026, 9, 6, tzinfo=timezone.utc))
    assert contract["signals"] == ["AI Agent效率工具实测"]
    assert contract["native_verified"] is False
    assert len(contract["evidence_sha256"]) == 64
