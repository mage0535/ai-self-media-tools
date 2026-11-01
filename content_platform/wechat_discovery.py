"""Free WeChat same-lane discovery for draft-box delivery (owner 11-01: no paid data).

Sogou WeChat search is public and shows titles, accounts and publish times but no
reads or likes, so these samples are discovery-only (G1): they may name peer accounts
and observed title patterns, never performance or viral claims.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from .real_world_ai_policy import classify_discovery_text
from .same_lane_intelligence import _top_accounts

SEARCH_URL = "https://weixin.sogou.com/weixin?"
MAX_QUERIES = 2
MIN_ACCOUNTS = 3
CLAIM_BOUNDARY = "discovery_only_no_performance_claim"
TITLE_PATTERNS = (
    ("案例/实战/复盘式标题", re.compile(r"案例|实战|复盘|实测|落地")),
    ("方法/教程式标题", re.compile(r"如何|怎么|教程|步骤|指南|手把手")),
    ("具体数字/清单式标题", re.compile(r"\d")),
    ("问题式标题", re.compile(r"[?？]")),
    ("主副标题结构", re.compile(r"[：:｜|]")),
)


def _fetch(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                                                    "Accept-Language": "zh-CN"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2 * 1024 * 1024)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def parse_search_page(raw: bytes, observed_at: str) -> list[dict[str, Any]]:
    page = raw.decode("utf-8", errors="ignore")
    if "antispider" in page:
        # A verification page is a stop signal, not something to work around.
        raise ValueError("wechat_discovery_verification_required")
    digest = hashlib.sha256(raw).hexdigest()
    samples = []
    for block in re.findall(r'<li id="sogou_vr_[^"]*"[\s\S]*?</li>', page):
        link = re.search(r'<h3>\s*<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', block)
        account = re.search(r'class="all-time-y2"[^>]*>([^<]+)<', block)
        if not link or not account:
            continue
        stamp = re.search(r"timeConvert\('(\d{9,11})'\)", block)
        summary = re.search(r'<p class="txt-info"[^>]*>([\s\S]*?)</p>', block)
        samples.append({
            "platform": "wechat", "source_kind": "sogou_wechat_search", "observation_status": "discovery_only",
            "title": _text(link.group(2)), "account": _text(account.group(1)),
            "summary": _text(summary.group(1)) if summary else "",
            "url": urllib.parse.urljoin("https://weixin.sogou.com/", html_lib.unescape(link.group(1))),
            "published_at": datetime.fromtimestamp(int(stamp.group(1)), timezone.utc).isoformat() if stamp else "",
            "observed_at": observed_at, "raw_response_hash": digest,
        })
    return samples


def collect_wechat_discovery(queries: list[str], *, timeout: int = 15,
                             fetch: Callable[[str, int], bytes] = _fetch) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for query in [str(item).strip() for item in queries if str(item).strip()][:MAX_QUERIES]:
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw = fetch(SEARCH_URL + urllib.parse.urlencode({"type": 2, "query": query}), timeout)
        samples.extend(parse_search_page(raw, observed_at))
    return samples


def discovery_reference(same_lane: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Labelled same-lane reference from >=3 in-lane peer accounts; unchanged when there are fewer."""
    seen, accepted = set(), []
    for row in samples:
        key = (row.get("account"), row.get("title"))
        if not row.get("account") or not row.get("title") or key in seen:
            continue
        if not classify_discovery_text(row["title"], row.get("summary", ""))["accepted"]:
            continue
        seen.add(key)
        accepted.append(row)
    if len({row["account"] for row in accepted}) < MIN_ACCOUNTS:
        return same_lane
    titles = [row["title"] for row in accepted]
    patterns = [f"{name}（{count}/{len(titles)} 个同赛道样本）"
                for name, rule in TITLE_PATTERNS if (count := sum(bool(rule.search(title)) for title in titles))]
    return dict(
        same_lane,
        generation_status="discovery_reference",
        strategy_claim_boundary=CLAIM_BOUNDARY,
        discovery_sample_count=len(accepted),
        top_accounts=_top_accounts(accepted, limit=5),
        discovery_works=[{key: row[key] for key in ("title", "url", "account", "published_at")} for row in accepted[:10]],
        structure_patterns=patterns,
        generation_rules=list(same_lane.get("generation_rules") or []) + [
            "same-lane samples are public discovery only (no reads/likes): learn topics and title forms, "
            "never claim performance, virality or rankings"],
    )
