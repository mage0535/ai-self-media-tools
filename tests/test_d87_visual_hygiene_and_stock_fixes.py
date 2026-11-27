"""Regression tests for d87 fixes:
1) _stock_query pet priority & word-boundary 'ai' matching (no Pexels office/camera photos on pet beats).
2) Article image prompts & semantic retry visual-hygiene override (preventing 0.55 fake-UI/pseudo-text cap).
3) Off-topic stock fallback escalation on repeated <0.45 stock draws while keeping retry #0 on stock (MED39).
4) Xiaohongshu _note_text atomic heading+body pairing (zero orphaned empty headings).
"""

import random
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from content_platform.formatters import _note_text
from content_platform.image_provider import _stock_query
from content_platform.media import MediaBridge


def test_stock_query_pet_video_never_falls_into_camera_or_ai_workspace():
    cover_q = _stock_query(
        "【搬运】给狗狗看的电视｜TV for Dogs ! Videos for Dogs To Watch | Cats and Dogs. "
        "Topic context: 【搬运】给狗狗看的电视｜TV for Dogs. Clear subject, explain detail."
    )
    assert any(w in cover_q for w in ("dog", "cat", "pet"))
    assert "camera" not in cover_q
    assert "artificial intelligence" not in cover_q

    beat_q = _stock_query(
        "Video topic: 【搬运】给狗狗看的电视｜TV for Dogs | Cats and Dogs\n"
        "Scene to show: 电视里的猫一动，你家狗狗要是马上转头，是不是就说明它爱看？\n"
        "Depict the concrete objects, explain details."
    )
    assert "dog" in beat_q or "cat" in beat_q
    assert "artificial intelligence" not in beat_q
    assert "camera" not in beat_q

    # "explain" / "detail" / "daily" must never trigger bare "ai" substring match.
    sec_q = _stock_query(
        "Section illustration for: 陪它看时，有个容易踩的坑：它刚瞄了一眼，你就以为它想接着看。"
        "Topic context: 给狗狗看的电视. explain daily detail."
    )
    assert "artificial intelligence" not in sec_q
    assert any(w in sec_q for w in ("dog", "pet", "cat"))


def test_article_prompts_enforce_photorealistic_no_screen_no_ui_hygiene():
    job = {
        "id": "j-hygiene",
        "topic": "合同审查、简历筛选，AI能帮我们做到什么程度？",
        "title": "AI 审采购合同：引文找得到，合同就能放行吗？",
        "platforms": ["juejin"],
        "brief": {"run_contract": {"version": "v1"}},
        "body": "## 第一节 核对附件\n\n核对正文和附件是否齐全。\n\n## 第二节 查引文\n\n把引文回到原页核验。\n\n## 第三节 人工放行\n\n法务复核后再放行。",
    }
    prompts = MediaBridge._image_prompts(job, 4)
    for item in prompts:
        p = item["prompt"]
        assert "editorial illustration" not in p.casefold()
        assert "NO computer/phone/tablet screens" in p
        assert "cartoon/vector infographic" in p


def test_semantic_retry_injects_visual_hygiene_fix_and_escalates_off_topic_pet_stock(tmp_path):
    bridge = MediaBridge({}, tmp_path)
    # 1) Juejin 0.55 fake-UI cap triggers CRITICAL VISUAL HYGIENE FIX on retry
    juejin_job = {
        "id": "j-retry-hygiene",
        "topic": "扣子机器人售后调优",
        "title": "扣子售后机器人总回套话？",
        "platforms": ["zhihu"],
        "brief": {"run_contract": {"version": "v1"}},
        "body": "## 一、人设\n\n明确权限边界。\n\n## 二、召回\n\n检查条款命中。\n\n## 三、记忆\n\n保留关键事实。",
    }
    seen_prompts = []

    class FakeProvider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen_prompts.append(prompt)
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(len(seen_prompts)).randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "openai-codex", "source_url": "generated:openai-codex"}

    reviews = iter([
        {"score": 0.55, "status": "evaluated", "observed_subject": "mock chat panel", "reason": "屏幕上有模拟界面和占位文字条，按视觉规范封顶 0.55"},
        {"score": 0.90, "status": "evaluated", "observed_subject": "real desk and tools", "reason": "clean photo"},
    ])
    with patch.object(bridge.registry, "choose_provider", return_value=FakeProvider()), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: next(reviews)), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_persist_asset_provenance", return_value=None), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]):
        bridge._generate_image(juejin_job, tmp_path / "zhihu_out", {"provider": "auto", "min_count": 1})
    assert len(seen_prompts) == 2
    assert "CRITICAL VISUAL HYGIENE FIX" in seen_prompts[1]

    # 2) douyin_pet keeps stock on retry #0 (MED39), then escalates to photorealistic generation on retry #1 if score < 0.45
    pet_job = {"id": "j-pet-esc", "title": "给狗狗看的电视", "body": "正文", "platforms": ["douyin_pet"], "brief": {}}
    seen_chains = []

    class PetProvider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen_chains.append((env or {}).get("IMAGE_PROVIDER_CHAIN", ""))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(100 + len(seen_chains)).randrange(256) for _ in range(64 * 64))).save(output)
            prov = "pexels" if "stock" in seen_chains[-1] else "openai-codex"
            return {"provider": prov, "source_url": f"https://www.pexels.com/photo/{len(seen_chains)}/" if prov == "pexels" else "generated:openai-codex"}

    pet_reqs = [{"intent": {"beat_id": "s01", "claim": "狗狗看电视转头", "content_match_reason": "illustrate"}, "sha256": "1"}]
    pet_reviews = iter([
        {"score": 0.08, "requirement_match": False, "observed_subject": "empty office", "reason": "no dog"},
        {"score": 0.45, "requirement_match": False, "observed_subject": "dog close-up", "reason": "no RV sightseeing context"},
        {"score": 0.88, "requirement_match": True, "observed_subject": "dog looking out RV window", "reason": "exact match"},
    ])
    with patch.object(bridge.registry, "choose_provider", return_value=PetProvider()), \
            patch("content_platform.video_asset_semantics.validate_requirement", side_effect=lambda r: r), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: next(pet_reviews)), \
            patch.object(MediaBridge, "_persist_asset_provenance", return_value=None):
        bridge._generate_image(pet_job, tmp_path / "pet_out", {"provider": "auto", "provider_chain": "cloudflare,openai-codex"}, semantic_requirements=pet_reqs)
    assert seen_chains[0] == "stock,cloudflare,openai-codex"
    assert seen_chains[1] == "stock,cloudflare,openai-codex"
    assert seen_chains[2] == "cloudflare,openai-codex"


def test_xhs_note_text_never_emits_orphaned_empty_headings():
    body = "\n\n".join([
        "为什么看完 Helix 高速分拣演示，还是答不上来：刚才那个包裹到底放对了没有？",
        "## 先找对片段，再认准来件",
        "在哔哩哔哩回看时先确认原发、转载还是剪辑，再记下链接和起止位置。" * 6,
        "## 逐件盯完抓取、转移和释放",
        "抓取看离开支撑面，转移看有没有跟丢，释放看实际去向，不要只看手快。" * 6,
        "## 落点看清了，为什么还不能判对？",
        "分拣工位上放下了和分对了要分开记，还要核对目标格口依据。" * 5,
        "## 别把演示里的「快」写成工位效率",
        "没有连续记录就不能倒推吞吐量和错分率。" * 5,
        "## 回看结束，只交能复核的结论",
        "把记录分成动作可见、异常可见和有环节无法判断。" * 5,
        "如果只能让演示多交代一项，你会选哪一项？",
    ])
    note = _note_text("为什么看完 Helix 高速分拣演示，还是答不上来", body)
    assert len(note) <= 950
    assert "如果只能让演示多交代一项，你会选哪一项？" in note
    # None of the skipped sections' headings may appear as orphaned empty headings!
    blocks = note.split("\n\n")
    for heading in ("落点看清了，为什么还不能判对？", "别把演示里的「快」写成工位效率", "回看结束，只交能复核的结论"):
        if heading in blocks:
            pos = blocks.index(heading)
            # If the heading is present, its immediately following block must NOT be another heading or the closing CTA!
            assert pos + 1 < len(blocks) - 2
            assert blocks[pos + 1] not in ("落点看清了，为什么还不能判对？", "别把演示里的「快」写成工位效率", "回看结束，只交能复核的结论")


def test_d88_xhs_topic_rule_and_visual_policy_remove_contradictions():
    import json
    from content_platform.overnight_topic_analysis import build_prompt
    from content_platform.visual_content_policy import visual_content_policy

    prompt = build_prompt("xiaohongshu", {"title": "机器人分拣演示"}, {})
    assert "PHOTO RULE" in prompt
    assert "even in a physical industry" in prompt
    assert "only licensed real photographs" not in prompt
    assert "仅用实拍" in prompt and "never write" in prompt

    carousel_policy = visual_content_policy(["xiaohongshu"], content_form="manual_carousel")
    xhs_override = carousel_policy["platform_overrides"]["xiaohongshu"]
    assert "short_video" not in xhs_override["must_include"]
    assert xhs_override["short_video_required"] is False

    video_policy = visual_content_policy(["xiaohongshu"], content_form="short_video")
    assert "short_video" in video_policy["platform_overrides"]["xiaohongshu"]["must_include"]

    rulebook = json.loads((Path(__file__).resolve().parents[1] / "config" / "channel_content_rulebook.json").read_text(encoding="utf-8"))
    xhs_defs = rulebook["channel_rules"]["xiaohongshu"]["quality_gate_definitions"]
    assert "short_video_present_when_strategy_requires" in xhs_defs
    assert "xiaohongshu_recovery_strategy_gate" in xhs_defs
    assert "viral_breakdown_not_executable" in xhs_defs["full_ops_workflow"]
    assert "viral_breakdown_not_executable" in rulebook["channel_rules"]["juejin"]["quality_gate_definitions"]["full_ops_workflow"]
    assert "viral_breakdown_not_executable" in rulebook["channel_rules"]["zhihu"]["quality_gate_definitions"]["full_ops_workflow"]


def test_d89_hook_strength_and_all_11_platforms_rulebook_and_image_rubric():
    import json
    from content_platform.humanize import _score
    from content_platform.media import _VISUAL_HYGIENE_PHOTO_RULE, _VISUAL_HYGIENE_DEFECT_TOKENS

    # 1) Concrete Chinese scene-conflict hook from live Juejin job 6ba68134 must pass G3 (>= 0.60)
    real_juejin_opening = (
        "业务刚把采购服务合同发过来，AI 倒是很快给了意见，可你翻回原件，连它批的是哪一段都找不到。\n"
        "这样的初审，不是给法务省事，是让法务再做一遍定位。\n\n"
        "下面是一套待试点的轻量方案。"
    )
    scores = _score(real_juejin_opening, {"style": {}, "strategy": {"content_form": "long_article"}})
    assert scores["hook_strength"] >= 0.60, scores

    # Generic bland opening must still stay below 0.60
    weak_opening = "本文介绍了 AI 工具的基本用法。首先我们需要了解什么是 AI。"
    assert _score(weak_opening, {"style": {}, "strategy": {"content_form": "long_article"}})["hook_strength"] < 0.60

    # 2) Visual hygiene prompt forbids open printed pages & corner 4-point star marks
    assert "open printed pages" in _VISUAL_HYGIENE_PHOTO_RULE
    assert "4-point star" in _VISUAL_HYGIENE_PHOTO_RULE
    assert "拟文字" in _VISUAL_HYGIENE_DEFECT_TOKENS and "星形" in _VISUAL_HYGIENE_DEFECT_TOKENS

    # 3) All 12 operating accounts across 11 platforms have quality_gate_definitions & D24 twitter policy
    rulebook = json.loads((Path(__file__).resolve().parents[1] / "config" / "channel_content_rulebook.json").read_text(encoding="utf-8"))
    for plat in ("juejin", "zhihu", "xiaohongshu", "wechat", "kuaishou", "douyin", "douyin_ai", "shipinhao", "bilibili", "tiktok", "youtube", "twitter"):
        defs = rulebook["channel_rules"][plat].get("quality_gate_definitions") or {}
        assert len(defs) >= 5, f"{plat} missing quality_gate_definitions"
    assert "manual_handoff" in rulebook["channel_rules"]["twitter"]["publish_policy"]
    assert "/srv/" not in json.dumps(rulebook, ensure_ascii=False)

    # 4) All 12 operating accounts have LANE_COLLECTORS and all 7 video lanes have multi-source REFERENCE_COLLECTORS
    from content_platform.overnight_benchmarks import LANE_COLLECTORS, REFERENCE_COLLECTORS
    for plat in ("juejin", "zhihu", "xiaohongshu", "wechat", "kuaishou", "douyin_pet", "douyin_ai", "shipinhao", "bilibili", "tiktok", "youtube", "twitter"):
        assert plat in LANE_COLLECTORS, f"{plat} missing LANE_COLLECTORS"
    for vplat in ("douyin_pet", "douyin_ai", "kuaishou", "shipinhao", "bilibili", "youtube", "tiktok"):
        assert len(REFERENCE_COLLECTORS.get(vplat) or ()) >= 2, f"{vplat} needs >=2 REFERENCE_COLLECTORS"


def test_d90_xhs_note_preserves_all_section_headings_and_strips_dividers():
    body = "\n\n".join([
        "屏幕上的缺陷框没画错，带划痕的零件却放过去了，问题往往出在试跑验收没闭环。",
        "## 先定必检面与边界样件",
        "把关键划痕面和边界样件逐件编号，训练样本与验收样本按实物严格分开，防止高估模型命中率。" * 3,
        "—",
        "## 把取像到分流链路拉通计时",
        "从相机触发取像、算法推理输出到剔除机构动作逐件记录耗时，把原图、件号、判定与去向一一对应。" * 3,
        "---",
        "## 试跑验收清单与人工接管",
        "同批样件做独立人工判定，逐件登记漏检、过检与中断记录；异常件直接留件复核，未达现场验收线不放行。" * 3,
        "你们产线最容易卡在取像、判定还是剔除哪一环？",
    ])
    note = _note_text("", body)
    assert len(note) <= 950
    # All 3 headings MUST appear verbatim so section_image_map heading_found_in_publication_copy is 3/3 True!
    assert "先定必检面与边界样件" in note
    assert "把取像到分流链路拉通计时" in note
    assert "试跑验收清单与人工接管" in note
    # Closing checklist/handoff content preserved
    assert "漏检" in note or "留件复核" in note
    # Closing CTA preserved
    assert "你们产线最容易卡在取像、判定还是剔除哪一环？" in note
    # No standalone divider lines ('—' or '---')
    for line in note.splitlines():
        assert line.strip() not in {"—", "---", "———"}


def test_d90_twitter_in_manual_handoff_and_cross_platform_evidence():
    from content_platform.overnight_batch import (
        CROSS_PLATFORM_EVIDENCE,
        MANUAL_HANDOFF_PLATFORMS,
        MAX_TOPIC_ANALYSES,
    )

    assert MAX_TOPIC_ANALYSES >= 20
    assert "twitter" in MANUAL_HANDOFF_PLATFORMS and "x" in MANUAL_HANDOFF_PLATFORMS
    assert "twitter" in CROSS_PLATFORM_EVIDENCE and "youtube" in CROSS_PLATFORM_EVIDENCE["twitter"]


def test_d91_humanize_dividers_cli_flags_wechat_and_bold_headings():
    from content_platform.humanize import naturalize_copy
    from content_platform.media import MediaBridge
    from content_platform.overnight_batch import SOURCE_COLLECTED_PLATFORMS

    # 1) humanize.py strips standalone '---' / '—' lines and preserves CLI flags & inline filenames
    raw = (
        "先用 `python3 app.py --model gpt-6.2-sol` 跑一次最小验证。\n\n"
        "---\n\n"
        "如果日志里出现 0.72 阈值告警，不要盲目跳过。\n\n"
        "```bash\npython3 run.py --config config.json\n```"
    )
    out = naturalize_copy(raw, {"style": {}, "strategy": {"content_form": "long_article"}})["body"]
    assert "`python3 app.py --model gpt-6.2-sol`" in out
    assert "--config config.json" in out
    assert "0.72" in out
    for ln in out.splitlines():
        assert ln.strip() not in {"—", "---", "———"}

    # 2) WeChat no longer blocks in SOURCE_COLLECTED_PLATFORMS on NEW errcode 40164
    assert "wechat" not in SOURCE_COLLECTED_PLATFORMS

    # 3) media._article_image_sections strips Markdown bold markers so XHS anchors match 3/3
    secs = MediaBridge._article_image_sections({"body": "## **先定必检面**\n正文内容\n\n## **验证清单**\n更多内容"})
    assert [s["section"] for s in secs] == ["先定必检面", "验证清单"]

    # 4) XHS formatter never leaves "以下是待填模板：" with zero template lines
    body = "\n\n".join([
        "开场冲突句，说明为什么要做同批对照。",
        "## **第一步：样本分组**",
        "把边界样件逐件编号并与训练样本隔离。" * 4,
        "## **第二步：待填验证模板**",
        "以下是待填模板：\n\n| 字段 | 填写内容 |\n|---|---|\n| 样件编号 | 现场逐件登记 |\n| 人工判定 | 质检员独立复核 |\n| 处置动作 | 异常留件隔离 |",
        "## **第三步：人工接管**",
        "发现漏检或中断立即停线留件，由质检班组长复核确认后方可放行。" * 3,
        "你们产线最先想验证哪一项？",
    ])
    note = _note_text("", body)
    assert "第二步：待填验证模板" in note
    assert "· " in note and "样件编号" in note
    assert not any(ln.strip().endswith("以下是待填模板：") and i == len(note.splitlines()) - 1 for i, ln in enumerate(note.splitlines()))


def test_d91c_rendered_asset_mix_sections_xhs_table_and_keywords(tmp_path):
    import json
    from datetime import datetime, timezone
    from content_platform.generator import DraftGenerator
    from content_platform.pipeline import Pipeline
    from content_platform.prompt_compiler import _topic_terms

    # 1) _rendered_asset_mix remains callable as staticmethod with or without data_dir and records CF breaker
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (tmp_path / "cloudflare_quota_state.json").write_text(
        json.dumps({"exhausted": True, "utc_day": today_utc, "reason": "daily neuron quota 429"}),
        encoding="utf-8",
    )
    assets = [{"scene_id": "cover", "origin": "ai_generated", "source_url": "gen"}]
    mix_no_dir = Pipeline._rendered_asset_mix(assets, {"draft_meta": {}})
    assert mix_no_dir["source"] == "asset_provenance" and "cloudflare_fallback_reason" not in mix_no_dir
    mix_cf = Pipeline._rendered_asset_mix(assets, {"draft_meta": {}}, data_dir=tmp_path)
    assert "cloudflare daily 429" in mix_cf.get("cloudflare_fallback_reason", "")
    assert "cloudflare daily 429" in mix_cf.get("real_material_retrieval", "")

    # 2) DraftGenerator._article_sections prefers Markdown headings over opening prose sentences
    body = "开场第一句很长的话用来引出问题。\n\n## **先定检查时点**\n正文...\n\n## 别把零件在当成装得对\n正文...\n\n## 异常复核怎么闭环\n正文..."
    secs = DraftGenerator._article_sections(body, "装配漏装怎么查")
    assert [s["title"] for s in secs[:3]] == ["先定检查时点", "别把零件在当成装得对", "异常复核怎么闭环"]

    # 3) XHS _note_text preserves verification table rows even after a long prose intro in the same section
    long_xhs = (
        "如果零件装完就会被遮住，你把相机放在终检，还能查出漏装吗？这是一段较长的开场说明，先讲清问题背景。\n\n"
        "## 第一步：找到零件可见时点\n" + "沿着工艺路线核对装配顺序，确认上盖合拢之前最后还能看到目标零件的工位位置。" * 4 + "\n\n"
        "## 第二步：单工位验证表模板\n"
        + "先用下面这张表做小样本对照记录，每次采集单独记一条，复核时才能找到系统当时看到的那张图。下面是验证表模板：\n\n"
        "| 核对项 | 完整件预期 | 漏装试样预期 | 复核人 |\n| --- | --- | --- | --- |\n"
        "| 上盖前工位 | 判定完整 | 标出漏装 | 质检员 |\n"
        "| 异常处置 | 记录归档 | 人工复核 | 班组长 |\n\n"
        "## 第三步：别把零件在当成装得对\n" + "画面里看到零件只证明未漏装，不代表锁紧力达标，关键工艺仍按原标准复核。" * 4 + "\n\n"
        "拿着表到工位先对 SOP，再决定要不要试。"
    )
    note = _note_text("装配漏装怎么查", long_xhs)
    assert len(note) <= 950
    assert "· 上盖前工位｜判定完整｜标出漏装｜质检员" in note
    assert "· 异常处置｜记录归档｜人工复核｜班组长" in note

    # 4) _topic_terms expands topic + scenario into structured capability/scenario/verification terms
    terms = _topic_terms(
        "用 LangGraph 搭一个单日旅行规划师：先排草案，再核对",
        {
            "actor": {"role": "研发工程师", "context": "单日行程编排"},
            "inputs": [{"type": "用户行程约束JSON"}],
            "process": {"steps": [{"ai_function": "状态机拆解与天气过滤"}]},
            "outcome": {"deliverable": "可核对行程草案", "measurement_method": "人工逐项核验清单"},
        },
    )
    assert len(terms) >= 5 and "可核对行程草案" in terms and "状态机拆解与天气过滤" in terms


    # 5) English native video feeds (youtube, tiktok) enabled by default in TrendCollector for twitter/youtube/tiktok lanes
    from content_platform.trends import TrendCollector
    direct = TrendCollector({})._direct_sources()
    assert direct["youtube"]["enabled"] is True
    assert direct["tiktok"]["enabled"] is True
