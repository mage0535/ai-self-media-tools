"""Evidence-backed factual claim validation before media generation."""

from __future__ import annotations

import re
from typing import Any


NUMERIC_CLAIM = re.compile(
    r"(?:\b20\d{2}\b|(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百千万亿几半]+)\s*(?:%|倍|小时|分钟|秒|天|周|个月|月|年|元|万|亿|ms|tokens?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)|(?:\d+(?:\.\d+)?|[二两三四五六七八九十百千万亿几]+)\s*(?:多|余|左右|以上|以下)?\s*(?:个|家|种|款|次))",
    re.I,
)
FIRST_PERSON_OPERATION = re.compile(
    r"(?:我[^。！？.!?\n]{0,8}(?:实测|测试|运行|用了|使用|部署|发布|修复|运营|订阅|付费|花了|省了|砍掉|切换)|\bI\s+(?:tested|ran|used|deployed|published|fixed|operated|subscribed|paid|saved|switched)\b)",
    re.I,
)
UNSUPPORTED_PROMOTIONAL_CLAIM = re.compile(
    r"(?:零成本|完全免费|免费(?:的|使用|试用|开放)|不收费|无需?注册|不需要特定\s*IDE\s*插件|不用写代码|无需写代码|零代码|全都有|一个平台全搞定|费用(?:砍掉|降低).{0,8}(?:一大半|一半|大半)|no[- ]cost|completely free|free to use|no code required)",
    re.I,
)
UNSUPPORTED_ANECDOTE = re.compile(
    r"(?:朋友|团队|客户|创作者|同行)[^。！？.!?\n]{0,36}(?:之前|曾经|每天|试了|用了|花了|省了|切换)",
    re.I,
)
VERIFIED_DOMAIN = re.compile(
    r"(?<![a-z0-9-])(?:[a-z0-9-]+\.)+(?:com|cn|org|net|io|ai|dev)(?![a-z0-9-])",
    re.I,
)
NAMED_EXTERNAL_PRODUCT = re.compile(
    r"(?:Claude\s+Code|Gemini(?:\s+CLI)?|ChatGPT|OpenAI|Anthropic|GitHub|Cursor|DeepSeek|DeepLearning\.AI|"
    r"抖音|快手|小红书|知乎|掘金|微信公众号|视频号)",
    re.I,
)
PLATFORM_TREND_CLAIM = re.compile(
    r"(?:抖音|快手|小红书|知乎|掘金|微信公众号|视频号|TikTok|YouTube|X)"
    r"[^。！？.!?\n]{0,28}(?:已经|已有|出现|热度|增长|攀升|热门|爆款)",
    re.I,
)
UNSUPPORTED_TECHNICAL_MECHANISM = re.compile(
    r"(?:Agent\s+Skills?[^。！？.!?\n]{0,48}(?:程序性记忆|跨会话(?:自动)?学习|不占上下文|持久化经验)|"
    r"(?:AI|Agent\s+Skills?|Skills?|SKILL\.md|\.agent/)[^。！？\n]{0,120}(?:每次启动|触发条件|自动加载|自动触发|自动注入|跨项目|项目根目录|\.agent/skills)|"
    r"Agent[^。！？\n]{0,120}(?:知道[^。！？\n]{0,32}调用|先看[^。！？\n]{0,32}(?:名称|描述)|判断[^。！？\n]{0,32}(?:加载|相关)|读取[^。！？\n]{0,32}(?:资源|脚本|参考))|"
    r"(?:系统|Agent|Skills?)[^。！？.!?\n]{0,36}(?:自动提炼(?:新)?\s*Skill|从执行结果中自动(?:学习|提炼)))",
    re.I,
)
UNSUPPORTED_TOOL_RECOMMENDATION = re.compile(
    r"(?:Skills?\.sh[^。！？.!?\n]{0,40}(?:排行榜|用户验证|热门|推荐)|"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+[^。！？.!?\n]{0,48}(?:质量(?:都)?不错|推荐|值得|好用)|"
    r"[A-Za-z0-9][A-Za-z0-9_-]{2,}[^。！？.!?\n]{0,36}(?:必装|会自动|自动(?:导航|检查|生成|填表)|一个\s*Skill\s*全搞定|踩坑概率低))",
    re.I,
)
UNSUPPORTED_INSTALL_COMMAND = re.compile(
    r"\b(?:npx|npm|pnpm|yarn|pipx?|uvx)\s+[^\n。！？]{0,80}\b(?:add|install)\b|"
    r"\b(?:npx|npm|pnpm|yarn|pipx?|uvx)\s+(?:add|install)\b",
    re.I,
)
EXTERNAL_ATTRIBUTION_ACTION = re.compile(
    r"(?:官方|发布(?!到|至|进)|推出|上线|集成|支持|兼容|开放|开源|插件市场|Marketplace|"
    r"(?:可以|可|能够|能)\s*直接(?:安装|使用|接入)|official(?:ly)?|released?|launched?|"
    r"integrat(?:e|ed|ion)|support(?:s|ed)?|compatible|open[- ]source)",
    re.I,
)
TECHNICAL_ANCHORS = {
    "agent_skill": re.compile(r"Agent\s+Skills?|\bSkills?\b", re.I),
    "skill_md": re.compile(r"SKILL\.md", re.I),
    "directory": re.compile(r"目录|文件夹|directory", re.I),
    "frontmatter": re.compile(r"frontmatter|YAML\s+元数据", re.I),
    "resources": re.compile(r"scripts?|references?|assets?|资源目录", re.I),
    "loading": re.compile(r"加载|读取|load(?:ing|ed)?|read", re.I),
    "routing": re.compile(r"路由|匹配|触发|判断.*相关|route|match|trigger", re.I),
    "workflow": re.compile(r"工作流|流程|workflow|playbook", re.I),
    "execution": re.compile(r"执行|调用|execute|invoke", re.I),
    "quality": re.compile(r"质量门禁|输出质量|最佳实践|quality gate|best practice", re.I),
    "command": re.compile(r"/(?:plan|build|test|review|webperf)\b|命令", re.I),
}
ADVICE_OR_HYPOTHETICAL = re.compile(
    r"^(?:#{1,6}\s*)?(?:建议|可以|可先|不妨|如果|假设|例如|比如|先|再|最后|以下|从|打开|运行|执行|检查|核对|确认|保存|复查|完成|使用|调用|写|把)"
)


def _has_external_attribution(sentence: str) -> bool:
    for product in NAMED_EXTERNAL_PRODUCT.finditer(sentence):
        action = EXTERNAL_ATTRIBUTION_ACTION.search(sentence, product.end())
        if action and action.start() - product.end() <= 40:
            return True
        before = sentence[max(0, product.start() - 48):product.start()]
        if EXTERNAL_ATTRIBUTION_ACTION.search(before):
            return True
    return False


def _is_structural_count(sentence: str, match: re.Match[str]) -> bool:
    if match.start() > 0 and sentence[match.start() - 1] == "第":
        return True
    following = sentence[match.end():match.end() + 8]
    return bool(re.match(r"(?:步骤|误区|要点|方法|原则|阶段|部分|检查项|问题|建议)", following))


def _sentences(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[。！？])|(?<=[.!?])(?=\s|$)|\n+", str(text or ""))
        if item.strip()
    ]


def _valid_evidence(row: dict[str, Any], *, first_person: bool) -> bool:
    source = str(row.get("source_url") or "").strip()
    evidence = str(row.get("evidence_path") or "").strip()
    if row.get("verified") is not True:
        return False
    if not (source.startswith("https://") or source.startswith("http://")):
        return False
    return bool(evidence) if first_person else True


def _covered(sentence: str, ledger: list[dict[str, Any]], *, first_person: bool) -> bool:
    normalized = re.sub(r"\s+", "", sentence).casefold()
    for row in ledger:
        claim = re.sub(r"\s+", "", str(row.get("claim") or "")).casefold()
        if claim and (claim in normalized or normalized in claim) and _valid_evidence(row, first_person=first_person):
            return True
    return False


def _technical_anchors(text: str) -> set[str]:
    return {name for name, pattern in TECHNICAL_ANCHORS.items() if pattern.search(str(text or ""))}


def _covered_technical_fact(sentence: str, ledger: list[dict[str, Any]]) -> bool:
    anchors = _technical_anchors(sentence)
    for row in ledger:
        if not _valid_evidence(row, first_person=False):
            continue
        claim_anchors = _technical_anchors(str(row.get("claim") or ""))
        overlap = anchors.intersection(claim_anchors)
        if len(overlap) >= 2 and len(overlap) / max(1, len(anchors)) >= 0.5:
            return True
    return False


def validate_claims(text: str, ledger: list[dict[str, Any]] | None) -> dict[str, Any]:
    ledger = [row for row in (ledger or []) if isinstance(row, dict)]
    failures: list[str] = []
    findings: list[dict[str, Any]] = []
    if str(text or "").count("```") % 2:
        failures.append("malformed_code_fence")
    for sentence in _sentences(text):
        numeric_matches = list(NUMERIC_CLAIM.finditer(sentence))
        if any(not _is_structural_count(sentence, match) for match in numeric_matches):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "numeric", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_numeric_claim")
        if FIRST_PERSON_OPERATION.search(sentence):
            covered = _covered(sentence, ledger, first_person=True)
            findings.append({"type": "first_person_operation", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_first_person_operation")
        if UNSUPPORTED_PROMOTIONAL_CLAIM.search(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "promotional", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_promotional_claim")
        if UNSUPPORTED_ANECDOTE.search(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "anecdote", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_anecdote")
        if _has_external_attribution(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "external_attribution", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_external_attribution")
        if PLATFORM_TREND_CLAIM.search(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "platform_trend", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_platform_trend_claim")
        if UNSUPPORTED_TECHNICAL_MECHANISM.search(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "technical_mechanism", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_technical_mechanism_claim")
        if UNSUPPORTED_TOOL_RECOMMENDATION.search(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "tool_recommendation", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_tool_recommendation_claim")
        if UNSUPPORTED_INSTALL_COMMAND.search(sentence):
            covered = _covered(sentence, ledger, first_person=False)
            findings.append({"type": "install_command", "text": sentence, "covered": covered})
            if not covered:
                failures.append("unsourced_install_command_claim")
        anchors = _technical_anchors(sentence)
        technical_assertion = (
            len(anchors) >= 2
            and not sentence.lstrip().startswith(("- [", "http://", "https://"))
            and not sentence.rstrip().endswith(("?", "？"))
            and not ADVICE_OR_HYPOTHETICAL.search(sentence.strip())
        )
        if technical_assertion:
            covered = _covered_technical_fact(sentence, ledger)
            findings.append({"type": "technical_fact", "text": sentence, "covered": covered, "anchors": sorted(anchors)})
            if not covered:
                failures.append("unsourced_technical_fact_claim")
    return {
        "passed": not failures,
        "failures": sorted(set(failures)),
        "findings": findings,
        "ledger_count": len(ledger),
    }


def compile_verified_claim_ledger(brief: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Merge explicit claims with independently verified source text."""
    brief = brief if isinstance(brief, dict) else {}
    rows = [dict(row) for row in (brief.get("claim_ledger") or []) if isinstance(row, dict)]
    hotspot = brief.get("associated_hotspot") if isinstance(brief.get("associated_hotspot"), dict) else {}
    source_url = str(hotspot.get("source_url") or "").strip()
    claim = str(hotspot.get("observed_title") or "").strip()
    evidence_path = str(hotspot.get("snapshot_path") or "").strip()
    provenance = str(hotspot.get("provenance_hash") or hotspot.get("source_hash") or "").strip()
    if (
        hotspot.get("evidence_verified") is True
        and source_url.startswith(("https://", "http://"))
        and claim
        and evidence_path
        and len(provenance) >= 32
    ):
        rows.append({
            "claim": claim,
            "source_url": source_url,
            "evidence_path": evidence_path,
            "verified": True,
            "provenance_hash": provenance,
            "source_type": str(hotspot.get("evidence_type") or "verified_platform_evidence"),
        })
    unique = []
    seen = set()
    for row in rows:
        key = (str(row.get("claim") or ""), str(row.get("source_url") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def restore_verified_domains(text: str, ledger: list[dict[str, Any]] | None) -> str:
    """Restore only domain suffixes proven by a verified claim source."""
    domains = set()
    for row in ledger or []:
        if not isinstance(row, dict) or row.get("verified") is not True:
            continue
        if not str(row.get("source_url") or "").startswith(("https://", "http://")):
            continue
        domains.update(match.group(0).casefold() for match in VERIFIED_DOMAIN.finditer(str(row.get("claim") or "")))
        domains.update(match.group(0).casefold() for match in VERIFIED_DOMAIN.finditer(str(row.get("source_url") or "")))
    repaired = str(text or "")
    for domain in sorted(domains, key=len, reverse=True):
        prefix = domain.rsplit(".", 1)[0] + "."
        repaired = re.sub(re.escape(prefix) + r"(?![A-Za-z0-9-])", domain, repaired, flags=re.I)
    return repaired


def sanitize_unsupported_claims(text: str, findings: list[dict[str, Any]] | None) -> str:
    cleaned = str(text or "")
    unsupported = [str(row.get("text") or "") for row in (findings or []) if isinstance(row, dict) and not row.get("covered")]
    for sentence in sorted((item for item in unsupported if item), key=len, reverse=True):
        cleaned = cleaned.replace(sentence, "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def append_verified_sources(text: str, ledger: list[dict[str, Any]] | None) -> str:
    """Append a compact Markdown source list from verified public URLs."""
    value = str(text or "").rstrip()
    if re.search(r"(?m)^##\s+(?:参考来源|References?)\s*$", value, flags=re.I):
        return value
    rows = []
    seen = set()
    source_labels = {
        "verified_primary_source": "官方技术规范",
        "same_lane_hot_work": "本平台同赛道参考作品",
        "official_activity": "平台官方活动",
        "official_keyword": "平台官方关键词",
        "native": "平台原生热点",
    }
    for row in ledger or []:
        if not isinstance(row, dict) or row.get("verified") is not True:
            continue
        url = str(row.get("source_url") or "").strip()
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        source_type = str(row.get("source_type") or "").strip()
        label = str(row.get("source_title") or source_labels.get(source_type) or row.get("claim") or "来源").strip()
        label = re.sub(r"[\[\]\n\r]+", " ", label)[:48].strip() or "来源"
        rows.append(f"- [{label}]({url})")
    if not rows:
        return value
    return value + "\n\n## 参考来源\n\n" + "\n".join(rows)


def build_grounded_technical_article(topic: str, ledger: list[dict[str, Any]] | None) -> dict[str, str]:
    """Build a conservative long-form fallback from verified primary claims."""
    claims = [
        str(row.get("claim") or "").strip()
        for row in ledger or []
        if isinstance(row, dict)
        and row.get("verified") is True
        and str(row.get("source_type") or "") == "verified_primary_source"
        and str(row.get("claim") or "").strip()
        and str(row.get("source_url") or "").startswith(("https://", "http://"))
    ]
    claims = list(dict.fromkeys(claims))
    if len(claims) < 3:
        raise ValueError("grounded technical article requires at least three primary claims")
    groups = [claims[:2], claims[2:3], claims[3:]]
    sections = (
        ("先确认核心定义", groups[0]),
        ("再核对文件结构", groups[1]),
        ("理解按需加载", groups[2]),
    )
    blocks = [
        "想弄清这个主题，先别从未经核对的命令、案例或效果承诺开始。",
        "下面只使用已经绑定来源的事实，再给出明确标注的操作建议，便于读者自行核对。",
    ]
    for heading, facts in sections:
        if not facts:
            continue
        blocks.append(f"## {heading}")
        blocks.extend(facts)
        blocks.append("建议先核对这部分事实，再决定它是否适合当前任务；不要把未验证的实现细节补进结论。")
    blocks.extend([
        "## 用检查清单落地",
        "建议按下面的顺序处理自己的任务：",
        "- 先写清楚要解决的问题、输入和预期输出。",
        "- 再对照已验证资料，区分固定规范与个人建议。",
        "- 然后只保留当前任务真正需要的文件、脚本或参考资料。",
        "- 最后检查每条事实是否能回到公开来源，无法核对的内容先删除或标为待验证。",
        "这套做法不会替你证明某个工具一定有效，但可以把事实、建议和待验证内容分开。",
        "你最想先整理哪一类重复任务？可以从一个边界清楚的小任务开始。",
    ])
    return {"title": str(topic or "技术主题入门").strip(), "body": "\n\n".join(blocks)}
