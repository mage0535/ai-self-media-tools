from content_platform.hot_work_intelligence import (
    analyze_work,
    build_hot_work_parameter_pack,
    load_samples,
    normalize_browser_cookies,
    parse_douyin_shipin_html,
    parse_logged_short_video_search_text,
    parse_sogou_wechat_html,
    parse_tiktok_search_text,
    parse_xiaohongshu_search_text,
)


def test_save_collection_writes_latest_to_mutable_data_root(tmp_path, monkeypatch):
    from pathlib import Path
    from content_platform.hot_work_intelligence import save_collection

    mutable = tmp_path / "mutable"
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(mutable))
    paths = save_collection([], [], tmp_path / "run")

    assert Path(paths["latest"]) == mutable / "intel" / "hot_work_parameter_pack_latest.json"
    assert Path(paths["latest"]).is_file()


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
    rows = parse_xiaohongshu_search_text(text, query="AI工具")
    assert len(rows) == 2
    assert rows[0]["engagement"] == "1459"
    assert rows[0]["evidence_strength"] == "strong_logged_search_result"


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
        {"platform": "xiaohongshu", "title": "让Codex起飞的10个技巧", "author": "A", "engagement": "1459", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("让Codex起飞的10个技巧")},
        {"platform": "xiaohongshu", "title": "AI工作流一图看懂", "author": "B", "engagement": "707", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("AI工作流一图看懂")},
        {"platform": "xiaohongshu", "title": "Claude Code vs Codex", "author": "C", "engagement": "56", "evidence_strength": "strong_logged_search_result", "analysis": analyze_work("Claude Code vs Codex")},
    ]
    pack = build_hot_work_parameter_pack(samples, platforms=["xiaohongshu"])
    assert pack["platforms"]["xiaohongshu"]["ready"] is True
    assert pack["platforms"]["xiaohongshu"]["recommended_patterns"]


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
