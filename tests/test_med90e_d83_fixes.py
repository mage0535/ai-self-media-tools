"""MED90-e / d83 unit tests: Cloudflare 429 failover + circuit breaker, cover OCR corner brackets,
humanizer hook sync, Juejin 14-day anti-spam window, XHS hook-preserving title, and cross-platform benchmark tags."""
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

from content_platform import image_provider as ip
from content_platform import wechat_cover_render as wcr
from content_platform.formatters import _note_text, _note_title
from content_platform.generator import DraftGenerator
from content_platform.media import MediaBridge
from content_platform.pipeline import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_d83_cloudflare_429_quota_trips_utc_circuit_breaker_and_falls_back_to_codex(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_HOME", str(tmp_path))
    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("IMAGE_PROVIDER_CHAIN", "cloudflare,openai-codex")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-test")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok-test")
    monkeypatch.delenv("CF_WORKER_URL", raising=False)
    monkeypatch.delenv("CLOUDFLARE_IMAGE_WORKER_URL", raising=False)

    cf_calls = {"count": 0}
    codex_calls = {"count": 0}

    def fake_urlopen(req, timeout=60, attempts=1):
        cf_calls["count"] += 1
        err_body = b'{"errors":[{"message":"AiError: you have used up your daily free allocation of 10,000 neurons"}]}'
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(err_body))

    def fake_codex(prompt, output, model="", size="1024x1024", quality="low", input_image=None):
        codex_calls["count"] += 1
        Path(output).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 4096)
        return {"provider": "openai-codex", "model": "gpt-image-2", "mode": "generate"}

    with patch.object(ip, "_urlopen_retry", side_effect=fake_urlopen), patch.object(
        ip, "_codex_image", side_effect=fake_codex
    ):
        res1 = ip.generate_image("two cats by food bowl", tmp_path / "out1.png", provider="auto")
        assert res1["provider"] == "openai-codex"
        assert ip._cloudflare_quota_exhausted() is True
        first_cf_calls = cf_calls["count"]
        assert first_cf_calls >= 1

        # Second call in same UTC day must short-circuit Cloudflare without making another HTTP request.
        res2 = ip.generate_image("another cat scene", tmp_path / "out2.png", provider="auto")
        assert res2["provider"] == "openai-codex"
        assert cf_calls["count"] == first_cf_calls
        assert codex_calls["count"] == 2


def test_d83_media_bridge_never_pins_single_cloudflare_provider_on_douyin_pet_retry(tmp_path):
    bridge = MediaBridge(
        {"image": {"provider": "auto"}, "video": {"image_provider_chain": "stock,cloudflare,openai-codex"}},
        tmp_path,
    )
    calls = []

    class FakeProvider:
        def run(self, prompt, output, extra_args, **kwargs):
            env = kwargs.get("env") or {}
            chain = env.get("IMAGE_PROVIDER_CHAIN", "")
            prov = extra_args[extra_args.index("--provider") + 1]
            calls.append((prov, chain))
            if len(calls) == 1:
                # First draw succeeds with a stock photo.
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_bytes(b"img-A" * 600)
                return {"provider": "pexels", "mode": "search", "source_url": "https://pexels.com/1"}
            if len(calls) == 2:
                # Second scene repeats same photo checksum -> triggers duplicate retry.
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_bytes(b"img-A" * 600)
                return {"provider": "pexels", "mode": "search", "source_url": "https://pexels.com/1"}
            if len(calls) == 3:
                # First generated attempt raises (simulating Cloudflare 429).
                raise RuntimeError("Cloudflare 429 daily quota")
            # Next attempt must stay on --provider auto and include openai-codex.
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(b"img-B-unique" * 600)
            return {"provider": "openai-codex", "mode": "generate"}

    bridge.registry.choose_provider = lambda kind: FakeProvider()
    bridge._required_image_count = lambda job, cfg: 2
    bridge._image_prompts = lambda job, minimum: [
        {"role": "cover", "prompt": "cat 1"},
        {"role": "section", "section": "s1", "prompt": "cat 2"},
    ]
    bridge._visual_signature = lambda p: "0000000000000000" if b"img-A" in Path(p).read_bytes() else "ffffffffffffffff"
    bridge._semantic_review = lambda *a, **kw: {"score": 0.85, "reason": "good", "observed_subject": "cats"}
    bridge._persist_asset_provenance = lambda *a, **kw: None
    bridge._bound_section_image_map = lambda *a, **kw: []

    job = {"id": "j1", "platforms": ["douyin_pet"], "topic": "two cats", "brief": {}}
    result = bridge._generate_image(job, tmp_path / "art", {"provider": "auto"})
    assert len(result["images"]) == 2
    assert all(prov == "auto" for prov, _ in calls)
    assert "openai-codex" in calls[-1][1]


def test_d83_cover_ocr_folds_cjk_corner_brackets_while_keeping_alnum_and_cjk_strict():
    expected = wcr._normalized("AI审合同，警惕把「没找到」当成「没问题」")
    ocr_read = wcr._normalized("Al审合同,警惕把【没找到」当成【没问题")
    assert wcr._title_matches(expected, ocr_read) is True
    # Wrong Latin token or wrong CJK word must still fail strictly.
    assert wcr._title_matches(expected, wcr._normalized("ML审合同,警惕把没找到当成没问题")) is False
    assert wcr._title_matches(expected, wcr._normalized("AI审合同,警惕把找不到当成完全不同")) is False


def test_d83_pipeline_syncs_opening_hook_and_humanization_plan_after_rewrite():
    draft = {
        "title": "AI 合同审查",
        "body": "AI 把采购合同总结得挺清楚，法务还是要翻原文。一句没问题没说查过哪里，复核的人还是得自己找。\n\n## 一、怎么查\n具体步骤说明与回查清单。",
        "draft_meta": {
            "opening_hook": "旧的未改写开头钩子",
            "hook": "旧的未改写开头钩子",
            "humanization_plan": {"hook": "旧的未改写开头钩子", "voice": "human editor"},
            "cover_design": {"hook": "旧的未改写开头钩子"},
            "strategy_brief": {"topic_basis": "合同审查"},
        },
    }
    Pipeline._sync_draft_opening_metadata(draft, applied_patterns=["filler", "ai_vocabulary"])
    meta = draft["draft_meta"]
    assert meta["opening_hook"].startswith("AI 把采购合同总结得挺清楚")
    assert meta["humanization_plan"]["hook"] == meta["opening_hook"]
    assert meta["humanization_plan"]["synced_to_final_body"] is True
    assert meta["humanization_plan"]["applied_humanizer_patterns"] == ["ai_vocabulary", "filler"]
    assert meta["cover_design"]["hook"] == meta["opening_hook"]
    assert meta["hook"] == "AI 把采购合同总结得挺清楚，法务还是要翻原文。一句没问题没说查过哪里，复核的人还是得自己找。"
    # Formatting for Xiaohongshu must not prepend a duplicate opening paragraph.
    note = _note_text(meta["hook"], draft["body"])
    assert note.count("AI 把采购合同总结得挺清楚") == 1


def test_d83_juejin_anti_spam_14_days_and_same_lane_cross_platform_dedup():
    gen = DraftGenerator({})
    body = "## 背景\n第一段说明。\n\n## 方案\n第二段说明。\n\n## 边界\n第三段说明。"
    draft_meta = {"strategy": {"content_form": "technical_article", "primary_platforms": ["juejin"]}}
    gen._attach_article_packet_evidence(
        topic="AI 合同审查",
        brief={
            "platforms": ["juejin"],
            "audience": "工程师",
            "cross_platform_source": "zhihu",
            "viral_breakdown": {
                "samples": [
                    {"title": "样本A", "canonical_url": "https://example.com/a", "body": "正文A。"},
                    {"title": "样本A重复", "canonical_url": "https://example.com/a", "body": "正文A。"},
                    {"title": "样本B", "canonical_url": "https://example.com/b", "body": "正文B。"},
                ]
            },
        },
        body=body,
        context={},
        draft_meta=draft_meta,
    )
    asp = draft_meta["anti_spam_similarity_plan"]
    assert asp["dedup_window_days"] == 14
    assert asp["cross_channel_dedup_window_days"] == 7
    assert asp["anti_spam_lookback_days"] == 14
    same_lane = draft_meta["strategy_brief"]["same_lane_account_analysis"]
    assert same_lane["cross_platform_source"] == "zhihu"
    assert len(same_lane["samples"]) == 2


def test_d83_xhs_note_title_preserves_hook_over_bare_topic_label_and_rulebook_defines_readability():
    assert _note_title("Helix 高速分拣：包裹投进去了，怎么确认没投错？") == "包裹投进去了，怎么确认没投错？"
    assert _note_title("低代码平台选型避坑清单：先看这三条上线前必查红线") == "低代码平台选型避坑清单"
    assert len(_note_title("Helix 高速分拣：包裹投进去了，怎么确认没投错？")) <= 20

    req, _ = DraftGenerator._generation_requirements(
        {"strategy": {"content_form": "social_note", "primary_platforms": ["xiaohongshu"]}}
    )
    assert "20 Chinese characters" in req

    rb = json.loads((REPO_ROOT / "config" / "channel_content_rulebook.json").read_text(encoding="utf-8"))
    xhs_defs = rb["channel_rules"]["xiaohongshu"]["quality_gate_definitions"]
    assert "knowledge_card_readability" in xhs_defs
    assert "不要求 AI 生成正文图内绘制文字" in xhs_defs["knowledge_card_readability"]
