from pathlib import Path

import pytest

from content_platform.juejin_native_article import collect_samples, parse_article_html, verify_sample

PAGE = (
    '<html><head><meta itemprop="headline" content="终于 Token 自由了">'
    '<meta itemprop="datePublished" content="2026-10-26T06:34:22.000Z">'
    '<meta itemprop="name" content="作者甲"><meta itemprop="name" content="掘金"></head><body>'
    '<article><div class="markdown-body cache"><style>.x{}</style><p>第一段&amp;正文</p><pre>code</pre></div></article>'
    '</body></html>'
).encode()


def test_parse_article_html_reads_meta_and_body():
    parsed = parse_article_html(PAGE)

    assert parsed == {"title": "终于 Token 自由了", "author": "作者甲",
                      "published_at": "2026-10-26T06:34:22+00:00", "body": "第一段&正文 code"}


def test_parse_article_html_rejects_a_page_without_body():
    with pytest.raises(ValueError, match="juejin_article_body_missing"):
        parse_article_html(b'<meta itemprop="headline" content="x">')


def test_collect_samples_keeps_raw_bytes_and_skips_bad_pages(tmp_path: Path):
    pages = {"https://juejin.cn/post/1": PAGE, "https://juejin.cn/post/2": b"<html></html>"}
    items = [{"url": url, "points": 9} for url in pages] + [{"url": "https://example.com/p/3"}]

    rows = collect_samples(items, tmp_path, fetch=pages.__getitem__)

    assert [row["content_id"] for row in rows] == ["1"]
    assert Path(rows[0]["raw_response_path"]).read_bytes() == PAGE
    assert verify_sample(rows[0], PAGE)
    assert not verify_sample(dict(rows[0], body="changed"), PAGE)
