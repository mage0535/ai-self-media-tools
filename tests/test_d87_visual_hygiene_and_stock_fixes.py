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
        {"score": 0.12, "requirement_match": False, "observed_subject": "camera rig", "reason": "no dog"},
        {"score": 0.88, "requirement_match": True, "observed_subject": "dog watching tv", "reason": "exact match"},
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
