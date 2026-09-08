from content_platform.claim_ledger import (
    append_verified_sources,
    build_grounded_technical_article,
    compile_verified_claim_ledger,
    restore_verified_domains,
    sanitize_unsupported_claims,
    validate_claims,
)


def test_claim_gate_rejects_unsourced_numeric_and_first_person_operations() -> None:
    result = validate_claims("我实测运行了 8 个月，成功率达到 99%。", [])
    assert result["passed"] is False
    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_first_person_operation" in result["failures"]


def test_claim_gate_accepts_claims_with_verifiable_evidence() -> None:
    text = "我实测运行了 8 个月，成功率达到 99%。"
    ledger = [{
        "claim": text,
        "source_url": "https://example.test/report",
        "evidence_path": "evidence/report.json",
        "verified": True,
    }]
    assert validate_claims(text, ledger)["passed"] is True


def test_claim_gate_rejects_malformed_code_fence() -> None:
    result = validate_claims("Run this:\n```python\nprint('x')", [])
    assert result["passed"] is False
    assert "malformed_code_fence" in result["failures"]


def test_claim_gate_allows_unsourced_advice_without_factual_claims() -> None:
    result = validate_claims("先确认负责人，再记录下一步。不要让工具替你猜。", [])
    assert result["passed"] is True


def test_claim_gate_rejects_unsourced_chinese_numbers_and_free_claims() -> None:
    result = validate_claims("三分钟通过审核。沙箱可以零成本试错。一个月省下两万元。", [])
    assert result["passed"] is False
    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_promotional_claim" in result["failures"]


def test_claim_gate_rejects_vague_personal_savings_and_no_code_claims() -> None:
    result = validate_claims("我之前订阅了七八个工具。费用砍掉一大半。这个平台不用写代码，一个平台全搞定。", [])
    assert result["passed"] is False
    assert "unsourced_first_person_operation" in result["failures"]
    assert "unsourced_promotional_claim" in result["failures"]


def test_claim_gate_rejects_approximate_counts_half_hours_and_friend_anecdotes() -> None:
    result = validate_claims("手机里装了十几个工具，每天浪费半小时。朋友之前试了四五个平台。这个功能是免费的。", [])
    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_anecdote" in result["failures"]
    assert "unsourced_promotional_claim" in result["failures"]


def test_claim_gate_allows_non_quantitative_single_item_instructions() -> None:
    result = validate_claims("注册一个账号。选择一个入口。逐个检查接口。", [])
    assert result["passed"] is True


def test_claim_gate_allows_structural_counts_ordinals_and_step_ranges() -> None:
    text = (
        "常见的三个误区：第一个误区是把技能当成提示词。"
        "第二个误区是堆叠工具。第三个误区是跳过验证。"
        "把这个工作拆成3到7个步骤，再逐项检查。"
    )

    assert validate_claims(text, [])["passed"] is True


def test_claim_gate_still_rejects_year_trend_tool_volume_and_time_savings() -> None:
    result = validate_claims(
        "2026年它会改变行业。很多人堆了几十个技能。这个流程每周节省3小时。",
        [],
    )

    assert result["passed"] is False
    assert "unsourced_numeric_claim" in result["failures"]


def test_claim_gate_rejects_unsourced_multiplier_and_named_platform_trend_claims() -> None:
    result = validate_claims(
        "Agent Skills 让效率翻 5 倍。DeepLearning.AI 上线了专门课程。"
        "掘金上已经出现多篇深度解析，热度正在攀升。",
        [],
    )

    assert result["passed"] is False
    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_external_attribution" in result["failures"]
    assert "unsourced_platform_trend_claim" in result["failures"]


def test_claim_gate_rejects_unsourced_bare_year_in_clickbait_title() -> None:
    result = validate_claims("2026 最火的 Agent Skills，从零搞懂只需这篇", [])

    assert result["passed"] is False
    assert "unsourced_numeric_claim" in result["failures"]


def test_claim_gate_rejects_unsourced_agent_skills_mechanism_claims() -> None:
    result = validate_claims(
        "Agent Skills 让 AI 拥有程序性记忆，跨会话自动学习，而且不占上下文。"
        "系统会从每次执行结果中自动提炼新 Skill。",
        [],
    )

    assert result["passed"] is False
    assert "unsourced_technical_mechanism_claim" in result["failures"]


def test_claim_gate_rejects_unsourced_tool_recommendations_and_install_commands() -> None:
    result = validate_claims(
        "Skills.sh 排行榜前几名都经过大量用户验证。"
        "vercel-react-best-practices 是 React 开发必装。"
        "agent-browser 会自动导航、填表和截图。"
        "运行 npx skills add vendor/repository 就能安装。",
        [],
    )

    assert result["passed"] is False
    assert "unsourced_tool_recommendation_claim" in result["failures"]
    assert "unsourced_install_command_claim" in result["failures"]


def test_claim_gate_rejects_unsourced_repo_endorsements_and_skill_loading_mechanisms() -> None:
    result = validate_claims(
        "vercel-labs/agent-skills 和 nextlevelbuilder/ui-ux-pro-max-skill 质量都不错。\n"
        "Agent Skills 就是把工作流写成一个 SKILL.md 文件，AI 在每次启动时自动加载。\n"
        "在项目根目录创建 .agent/skills/api-review/SKILL.md。",
        [],
    )

    assert "unsourced_tool_recommendation_claim" in result["failures"]
    assert "unsourced_technical_mechanism_claim" in result["failures"]


def test_claim_gate_rejects_unsourced_agent_routing_behavior() -> None:
    result = validate_claims(
        "Agent 读到 SKILL.md，就知道后续该调用哪些资源。"
        "任务开始时，Agent 会先看所有 Skill 的名称和描述，再判断是否加载。",
        [],
    )

    assert "unsourced_technical_mechanism_claim" in result["failures"]


def test_claim_gate_rejects_v30_token_counts_client_lists_and_free_promises() -> None:
    result = validate_claims(
        "metadata 只占约 100 tokens，正文控制在 5000 tokens 以内。"
        "官方客户端列表已经包括 Cursor、Claude Code、Hermes Agent 等 20 多个工具。"
        "Agent Skills 不收费、不注册、不需要特定 IDE 插件。",
        [],
    )

    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_external_attribution" in result["failures"]
    assert "unsourced_promotional_claim" in result["failures"]


def test_claim_gate_rejects_unsourced_technical_assertions_but_allows_grounded_paraphrase_and_advice() -> None:
    ledger = [{
        "claim": "Agent Skill 是一个目录，至少包含一个 SKILL.md 文件。",
        "source_url": "https://agentskills.io/specification",
        "evidence_path": "sources/specification.md",
        "verified": True,
    }]
    grounded = validate_claims("Agent Skill 本质上是一个目录，里面至少有一个 SKILL.md 文件。", ledger)
    advice = validate_claims("建议先给 Skill 写清输入和输出，再检查目录结构。", ledger)
    unsupported = validate_claims(
        "Agent Skills 把高级工程师的工作流塞进代码助手，输出质量直接跨一个档次。"
        "spec-driven-development Skill 会自动执行六阶段工程流程。",
        ledger,
    )

    assert grounded["passed"] is True
    assert advice["passed"] is True
    assert "unsourced_technical_fact_claim" in unsupported["failures"]


def test_grounded_technical_article_uses_only_primary_claims_and_passes_claim_gate() -> None:
    ledger = [
        {"claim": claim, "source_url": "https://agentskills.io/specification", "evidence_path": "sources/spec.md", "verified": True, "source_type": "verified_primary_source"}
        for claim in (
            "Agent Skill 是一个目录，至少包含一个 SKILL.md 文件。",
            "SKILL.md 必须包含 YAML frontmatter，后面接 Markdown 正文。",
            "Skill 目录可以包含 scripts、references 和 assets 等可选资源目录。",
            "Agent 会渐进式加载 Skill，只在任务需要时拉取更多细节。",
            "Skill 激活后会加载完整的 SKILL.md 正文，其他资源按需加载。",
        )
    ]
    ledger.append({"claim": "未经验证的热门标题", "source_url": "https://example.test/hot", "evidence_path": "hot.txt", "verified": True, "source_type": "same_lane_hot_work"})

    draft = build_grounded_technical_article("Agent Skills 入门", ledger)
    gate = validate_claims(draft["title"] + "\n" + draft["body"], ledger)

    assert gate["passed"] is True
    assert draft["body"].count("\n## ") >= 4
    assert "未经验证的热门标题" not in draft["body"]
    assert "安装命令" not in draft["body"]


def test_claim_gate_rejects_unsourced_named_product_attributions() -> None:
    text = "Claude Code 的官方插件市场直接集成了 Skills。Gemini CLI 用户也可以直接安装。"

    result = validate_claims(text, [])

    assert result["passed"] is False
    assert "unsourced_external_attribution" in result["failures"]
    assert [row["type"] for row in result["findings"]] == [
        "external_attribution",
        "external_attribution",
    ]


def test_claim_gate_allows_product_named_operational_advice() -> None:
    result = validate_claims("先为 Claude Code 写一份操作手册，再把成片发布到抖音草稿箱。", [])

    assert result["passed"] is True


def test_verified_source_appendix_is_deduplicated_and_geo_readable() -> None:
    body = "## 核心结论\n先确认来源，再执行任务。"
    ledger = [
        {"claim": "规范事实 A", "source_url": "https://agentskills.io/specification", "verified": True},
        {"claim": "规范事实 B", "source_url": "https://agentskills.io/specification", "verified": True},
        {"claim": "热门作品", "source_url": "https://juejin.cn/post/123", "verified": True},
        {"claim": "无效来源", "source_url": "file:///tmp/private", "verified": True},
    ]

    result = append_verified_sources(body, ledger)

    assert result.count("https://agentskills.io/specification") == 1
    assert result.count("https://juejin.cn/post/123") == 1
    assert "file:///" not in result
    assert "## 参考来源" in result
    assert result.count("\n- [") == 2


def test_verified_source_appendix_uses_reader_facing_labels_for_known_sources() -> None:
    result = append_verified_sources("正文。", [
        {"claim": "规范", "source_url": "https://agentskills.io/specification", "source_type": "verified_primary_source", "verified": True},
        {"claim": "热门作品", "source_url": "https://juejin.cn/post/123", "source_type": "same_lane_hot_work", "verified": True},
    ])

    assert "[官方技术规范]" in result
    assert "[本平台同赛道参考作品]" in result
    assert "verified_primary_source" not in result


def test_verified_hotspot_text_compiles_to_claim_ledger_but_incomplete_evidence_does_not() -> None:
    hotspot = {
        "observed_title": "做内容还要在几十个AI工具之间来回切？",
        "source_url": "https://cp.kuaishou.com/profile",
        "snapshot_path": "hotspots/kuaishou.txt",
        "provenance_hash": "a" * 64,
        "evidence_type": "native",
        "evidence_verified": True,
    }
    ledger = compile_verified_claim_ledger({"associated_hotspot": hotspot})
    assert validate_claims(hotspot["observed_title"], ledger)["passed"] is True
    assert compile_verified_claim_ledger({"associated_hotspot": {**hotspot, "evidence_verified": False}}) == []


def test_claim_sanitizer_removes_only_unsupported_sentences() -> None:
    text = "This checklist is practical. Success rose 99% in 8 months. Verify the owner before acting."
    gate = validate_claims(text, [])
    cleaned = sanitize_unsupported_claims(text, gate["findings"])
    assert "99%" not in cleaned
    assert "Verify the owner" in cleaned


def test_verified_domain_is_restored_when_model_drops_only_the_tld() -> None:
    ledger = [{
        "claim": "打开 ai.kuaishou.com 注册开发者账号。",
        "source_url": "https://cp.kuaishou.com/profile",
        "evidence_path": "hotspots/kuaishou.txt",
        "verified": True,
    }]

    repaired = restore_verified_domains("第一步，打开 ai.kuaishou.\n\n第二步，检查接口。", ledger)

    assert "ai.kuaishou.com" in repaired


def test_verified_domain_can_be_restored_from_source_url() -> None:
    ledger = [{
        "claim": "查看官方规范。",
        "source_url": "https://agentskills.io/specification",
        "evidence_path": "sources/specification.md",
        "verified": True,
    }]

    repaired = restore_verified_domains("下一步打开 agentskills.\nio 查看规范。", ledger)

    assert "agentskills.io" in repaired
