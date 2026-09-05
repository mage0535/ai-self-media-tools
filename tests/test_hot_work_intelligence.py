import json
from pathlib import Path

from content_platform.hot_work_intelligence import (
    analyze_work,
    build_hot_work_parameter_pack,
    load_samples,
    normalize_browser_cookies,
    parse_douyin_shipin_html,
    parse_logged_short_video_search_text,
    parse_platform_search_evidence,
    parse_sogou_wechat_html,
    parse_tiktok_search_text,
    parse_xiaohongshu_search_text,
    should_use_regional_proxy,
    logged_search_artifact_stem,
)


def test_logged_search_artifact_stem_keeps_distinct_chinese_queries_unique():
    first = logged_search_artifact_stem("xiaohongshu", "AI工作流")
    second = logged_search_artifact_stem("xiaohongshu", "AI效率工具")
    assert first != second
    assert first.startswith("xiaohongshu_AI_")


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

    monkeypatch.setenv("CONTENT_PLATFORM_COOKIE_DIRS", str(tmp_path / "missing"))

    result = resolve_logged_search_state("xiaohongshu", tmp_path / "private-states", cookie_dir=str(tmp_path / "missing"))

    assert result == {"status": "unavailable", "reason": "valid_private_cookie_state_not_found", "state_file": ""}
    assert not (tmp_path / "private-states").exists()
