from content_platform.wechat_discovery import CLAIM_BOUNDARY, collect_wechat_discovery, discovery_reference, parse_search_page
import pytest

ROW = ('<li id="sogou_vr_11002601_box_{i}"><h3><a target="_blank" href="/link?url=abc{i}&amp;type=2">'
       '{title}</a></h3><p class="txt-info">{summary}</p><div class="s-p"><span class="all-time-y2">{account}</span>'
       '<span class="s2"><script>document.write(timeConvert(\'1761900000\'))</script></span></div></li>')


def _page(rows):
    return ("<html><ul>" + "".join(ROW.format(i=i, **row) for i, row in enumerate(rows)) + "</ul></html>").encode()


ROWS = [
    {"title": "实战复盘：用AI整理会议纪要，行动项交给人工复核", "summary": "AI 会议纪要 落地 案例", "account": "办公效率实验室"},
    {"title": "工厂工业质检用AI缺陷检测落地的3个步骤", "summary": "AI 工业质检 缺陷检测 落地 案例", "account": "智造观察"},
    {"title": "AI合同审查落地案例：法务如何人工复核", "summary": "AI 合同审查 落地 人工复核", "account": "法务数字化"},
]


def test_parse_keeps_account_title_time_and_snapshot_hash():
    samples = parse_search_page(_page(ROWS), "2026-11-01T00:00:00+00:00")
    assert [row["account"] for row in samples] == ["办公效率实验室", "智造观察", "法务数字化"]
    assert samples[0]["url"] == "https://weixin.sogou.com/link?url=abc0&type=2"
    assert samples[0]["published_at"].startswith("2025-10-31") and len(samples[0]["raw_response_hash"]) == 64
    assert all(row["observation_status"] == "discovery_only" and "views" not in row for row in samples)


def test_verification_page_stops_instead_of_working_around_it():
    with pytest.raises(ValueError, match="verification_required"):
        parse_search_page(b"<html>antispider</html>", "2026-11-01T00:00:00+00:00")
    calls = []
    collect_wechat_discovery(["a", "b", "c"], fetch=lambda url, timeout: calls.append(url) or _page(ROWS))
    assert len(calls) == 2


def test_reference_needs_three_in_lane_accounts_and_never_claims_performance():
    base = {"generation_status": "research_required", "top_accounts": [], "generation_rules": ["x"]}
    samples = parse_search_page(_page(ROWS), "2026-11-01T00:00:00+00:00")
    reference = discovery_reference(base, samples)
    assert reference["generation_status"] == "discovery_reference"
    assert reference["strategy_claim_boundary"] == CLAIM_BOUNDARY and len(reference["top_accounts"]) == 3
    assert reference["structure_patterns"] and all("同赛道样本" in item for item in reference["structure_patterns"])
    assert "never claim performance" in reference["generation_rules"][-1]
    assert discovery_reference(base, samples[:2]) is base


def test_verification_stops_further_queries_and_timeout_skips_one(tmp_path):
    calls = []

    def blocked(url, timeout):
        calls.append(url)
        return b"<html>antispider</html>"
    with pytest.raises(ValueError, match="verification_required"):
        collect_wechat_discovery(["a", "b"], fetch=blocked)
    assert len(calls) == 1

    def first_times_out(url, timeout):
        calls.append(url)
        if len(calls) == 2:
            raise TimeoutError("timed out")
        return _page(ROWS)
    assert len(collect_wechat_discovery(["a", "b"], fetch=first_times_out)) == 3


def test_day_old_answer_is_reused_instead_of_requesting_again(tmp_path):
    calls = []
    fetch = lambda url, timeout: calls.append(url) or _page(ROWS)
    first = collect_wechat_discovery(["AI 落地 案例"], cache_dir=tmp_path, fetch=fetch)
    again = collect_wechat_discovery(["AI 落地 案例"], cache_dir=tmp_path, fetch=fetch)
    assert len(calls) == 1 and again == first


def test_verification_page_pauses_the_site_for_six_hours(tmp_path):
    calls = []
    with pytest.raises(ValueError, match="verification_required"):
        collect_wechat_discovery(["a"], cache_dir=tmp_path, fetch=lambda url, timeout: calls.append(url) or b"antispider")
    with pytest.raises(ValueError, match="paused_after_verification"):
        collect_wechat_discovery(["b"], cache_dir=tmp_path, fetch=lambda url, timeout: calls.append(url) or _page(ROWS))
    assert len(calls) == 1
