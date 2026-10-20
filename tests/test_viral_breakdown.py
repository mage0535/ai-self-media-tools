import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from content_platform.viral_breakdown import (
    build_breakdown_report,
    cache_is_fresh,
    validate_breakdown_report,
)
from content_platform.same_lane_intelligence import load_samples_file


UTC = timezone.utc


def _sample(**overrides):
    sample = {
        "platform": "juejin",
        "title": "AI Skills：前端新的效率神器！",
        "url": "https://juejin.cn/post/123",
        "views": 71573,
        "likes": 746,
        "comments": 77,
        "collected_at": "2026-09-12T10:00:00+00:00",
        "content_form": "technical_longform",
        "copy_structure": ["反常识开场", "代码实战", "边界说明", "CTA"],
        "topic_direction": "AI Skills / Agent tooling",
        "asset_analysis": {
            "type": "code_screenshot_and_diagram",
            "count": 3,
            "semantic_match": True,
        },
        "theme_template": {
            "template_id": "dark_code_editor",
            "reason": "developer technical article",
        },
        "motion_combination": {
            "status": "not_applicable",
            "reason": "静态技术文章，无视频动效",
        },
        "visual_evidence": ["https://juejin.cn/post/123"],
    }
    sample.update(overrides)
    return sample


def test_full_media_breakdown_requires_copy_style_voice_and_transitions():
    sample = _sample(
        copy_or_script="先给结果，再展示三步操作，最后开放评论问题。",
        writing_style="口语化、短句、具体数字、实测口吻",
        content_structure=["结果钩子", "痛点", "演示", "边界", "CTA"],
        voiceover={"status": "not_applicable", "reason": "静态技术文章，无配音"},
        transition_combination={"status": "not_applicable", "reason": "静态技术文章，无视频转场"},
    )
    report = build_breakdown_report(
        "juejin",
        [sample],
        collected_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    assert report["status"] == "ready"
    assert "copy_or_script" in report["required_dimensions"]
    assert "writing_style" in report["required_dimensions"]
    assert "voiceover" in report["required_dimensions"]
    assert "transition_combination" in report["required_dimensions"]


def test_breakdown_requires_all_reference_dimensions():
    report = build_breakdown_report(
        "juejin",
        [_sample()],
        collected_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["summary"]["accepted_samples"] == 0
    assert "copy_or_script_missing" in report["failures"]
    assert "writing_style_missing" in report["failures"]
    assert "voiceover_missing" in report["failures"]
    assert report["samples"][0]["motion_combination"]["status"] == "not_applicable"


def test_video_breakdown_blocks_without_real_visual_evidence():
    sample = _sample(
        platform="kuaishou",
        content_form="vertical_video",
        motion_combination={"status": "planned", "moves": ["fade"]},
        asset_analysis={"type": "video", "count": 1},
        visual_evidence=[],
    )
    report = build_breakdown_report(
        "kuaishou",
        [sample],
        collected_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert "visual_evidence_missing" in report["failures"]
    assert "motion_evidence_not_verified" in report["failures"]


def test_missing_dimensions_are_blocking_not_inferred_from_title():
    sample = _sample()
    sample.pop("copy_structure")
    sample.pop("theme_template")
    report = build_breakdown_report(
        "juejin",
        [sample],
        collected_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert "copy_or_script_missing" in report["failures"]
    assert "writing_style_missing" in report["failures"]
    assert "content_structure_missing" in report["failures"]


def test_cache_ttl_is_explicit_and_expired_cache_is_not_reused():
    generated = datetime(2026, 9, 1, tzinfo=UTC)
    report = build_breakdown_report(
        "juejin",
        [_sample(
            copy_or_script="结果→步骤→CTA",
            writing_style="口语实测",
            content_structure=["hook", "proof", "cta"],
            voiceover={"status": "not_applicable", "reason": "静态图文"},
            transition_combination={"status": "not_applicable", "reason": "静态图文"},
        )],
        collected_at=generated,
        ttl_days=7,
    )

    assert cache_is_fresh(report, generated + timedelta(days=6, hours=23))
    assert not cache_is_fresh(report, generated + timedelta(days=7))
    assert report["cache"]["ttl_days"] == 7


def test_platform_grouped_sample_files_are_loaded_for_cli_integration(tmp_path):
    path = tmp_path / "samples.json"
    path.write_text(json.dumps({"platforms": {"juejin": [_sample()]}}, ensure_ascii=False), encoding="utf-8")

    loaded = load_samples_file(path)

    assert len(loaded["juejin"]) == 1
    assert loaded["juejin"][0]["title"] == "AI Skills：前端新的效率神器！"


def test_today_topic_gate_requires_ready_viral_breakdown(tmp_path):
    from scripts.check_platform_topic_independence import check

    platform_dir = tmp_path / "data" / "local_ops_gzh"
    platform_dir.mkdir(parents=True)
    matrix = {
        "selected_topic": "AI工作流验收实测",
        "platform_source_matrix": {
            "collected_at": "2026-09-12T10:00:00+00:00",
            "attempted_sources": ["a", "b", "c", "d", "e"],
            "successful_sources": ["a", "b", "c"],
            "platform_internal_verified": True,
            "platform_internal_samples": [{"title": "native work"}],
            "trend_evidence": {"samples": [{"source": "a"}, {"source": "b"}, {"source": "c"}]},
            "viral_breakdown": {"status": "ready", "summary": {"accepted_samples": 1}, "samples": [{"title": "reference"}]},
            "shared_trend_only": False,
        },
    }
    path = platform_dir / "platform_source_matrix_20260912.json"
    path.write_text(json.dumps(matrix, ensure_ascii=False), encoding="utf-8")

    ready = check("20260912", ["wechat"], root=tmp_path)
    assert ready["passed"] is True

    matrix["platform_source_matrix"]["viral_breakdown"] = {"status": "blocked"}
    path.write_text(json.dumps(matrix, ensure_ascii=False), encoding="utf-8")
    blocked = check("20260912", ["wechat"], root=tmp_path)
    assert blocked["passed"] is False
    assert "viral_breakdown_missing_or_not_ready" in blocked["failures"][0]["failed_dimensions"]


def test_validation_round_trip_is_machine_readable():
    report = build_breakdown_report(
        "juejin",
        [_sample(
            copy_or_script="结果→步骤→CTA",
            writing_style="口语实测",
            content_structure=["hook", "proof", "cta"],
            voiceover={"status": "not_applicable", "reason": "静态图文"},
            transition_combination={"status": "not_applicable", "reason": "静态图文"},
        )],
        collected_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    result = validate_breakdown_report(report)
    assert result["passed"] is True
    json.dumps(report, ensure_ascii=False)
