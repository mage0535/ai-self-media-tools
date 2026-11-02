import json
import subprocess

import pytest

from content_platform import mediacrawler_collector as mc


def _row(content_id, votes, text_len=400, **extra):
    return {"content_id": content_id, "content_url": f"https://zhuanlan.zhihu.com/p/{content_id}", "title": f"t{content_id}",
            "user_nickname": "a", "content_text": "字" * text_len, "voteup_count": votes, "comment_count": 2,
            "created_time": 1793585071, "content_type": "article", "raw_response_path": "/x.json", "raw_response_hash": "h",
            **extra}


def test_zhihu_samples_keep_full_text_works_most_upvoted_first(monkeypatch):
    monkeypatch.setattr("content_platform.real_world_ai_policy.classify_discovery_text", lambda *a: {"accepted": True})
    rows = [_row(1, 3), _row(2, 555), _row(3, 900, text_len=50), _row(4, 10)]

    samples = mc.zhihu_samples(rows, limit=2)

    assert [s["content_id"] for s in samples] == ["2", "4"]
    assert samples[0]["metrics"] == {"like": 555, "comment": 2}
    assert samples[0]["platform"] == "zhihu" and samples[0]["body"] == "字" * 400
    assert samples[0]["raw_response_hash"] == "h" and samples[0]["published_at"].startswith("2026-")


@pytest.mark.parametrize("code,reason", [(3, "mediacrawler_login_required"), (4, "mediacrawler_verification_required"),
                                         (1, "mediacrawler_failed:rc=1")])
def test_search_stops_on_login_or_captcha_without_quoting_the_log(tmp_path, monkeypatch, code, reason):
    monkeypatch.setitem(mc.COOKIE_FILES, "zhihu", tmp_path / "missing.json")
    run = lambda command, **kwargs: subprocess.CompletedProcess(command, code, "z_c0=secret", "z_c0=secret")

    with pytest.raises(ValueError) as error:
        mc.search("zhihu", tmp_path / "out", run=run)

    assert str(error.value) == reason


def test_search_passes_the_cookie_file_by_environment_and_reads_stored_rows(tmp_path, monkeypatch):
    cookies = tmp_path / "zhihu.json"
    cookies.write_text("{}")
    monkeypatch.setitem(mc.COOKIE_FILES, "zhihu", cookies)
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, env=kwargs["env"])
        stored = tmp_path / "out" / "zhihu" / "json"
        stored.mkdir(parents=True)
        (stored / "search_contents_2026-11-02.json").write_text(json.dumps([_row(1, 5)]))
        return subprocess.CompletedProcess(command, 0, "", "")

    rows = mc.search("zhihu", tmp_path / "out", run=run)

    assert seen["env"]["MC_COOKIE_FILE"] == str(cookies) and seen["env"]["MC_UNATTENDED"] == "1"
    assert seen["command"][seen["command"].index("--lt") + 1] == "cookie"
    assert "--get_comment" in seen["command"] and seen["command"][seen["command"].index("--get_comment") + 1] == "no"
    assert len(rows) == 1 and len(rows[0]["raw_response_hash"]) == 64


def test_verify_sample_matches_the_stored_row_exactly():
    raw = json.dumps([_row(7, 40, text_len=400)]).encode()
    row = {"content_id": "7", "body": "字" * 400, "canonical_url": "https://zhuanlan.zhihu.com/p/7", "title": "t7",
           "author": "a", "metrics": {"like": 40, "comment": 2}}

    assert mc.verify_sample(row, raw)
    assert not mc.verify_sample(dict(row, metrics={"like": 41, "comment": 2}), raw)
    assert not mc.verify_sample(dict(row, body="改"), raw)


def test_zhihu_samples_drop_works_outside_the_real_world_ai_genre(monkeypatch):
    monkeypatch.setattr("content_platform.real_world_ai_policy.classify_discovery_text",
                        lambda title, text: {"accepted": title != "t2"})

    assert [s["content_id"] for s in mc.zhihu_samples([_row(1, 3), _row(2, 555)])] == ["1"]
