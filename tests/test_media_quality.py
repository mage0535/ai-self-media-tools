import json
import subprocess
import sys
from pathlib import Path

from content_platform.media_quality import (
    _platform_source_matrix_gate,
    validate_article_packet,
    validate_delivery_result,
    validate_douyin_tiktok_repost_packet,
    validate_growth_package,
    validate_kuaishou_auto_packet,
    validate_platform_article_packet,
    validate_shipinhao_auto_packet,
    validate_video_packet,
    validate_wechat_auto_packet,
    validate_wechat_image_post_packet,
    validate_xiaohongshu_auto_packet,
)
from content_platform.content_recipe import (
    build_article_recipe,
    build_image_text_card_recipe,
    build_knowledge_card_recipe,
    build_tool_invocation_manifest,
    validate_image_text_card_recipe,
)
from content_platform.tool_selection import build_tool_selection_evidence
from content_platform.growth_policy import build_growth_strategy
from content_platform.preflight_manifest import validate_preflight_manifest
from content_platform.visual_content_policy import visual_content_policy


def complete_preflight_manifest(platform: str, content_type: str = "long_article"):
    skills = [
        "meta/content-preflight",
        "content/content-strategy-workflow",
    ]
    if platform in {"wechat", "weixin", "wechat_official"}:
        skills.append("content/wechat-operational-strategy")
        skills.extend(["content/wechat-full-workflow", "no-ai-slop", "wewrite"])
    if platform in {"wechat", "weixin", "wechat_official", "kuaishou", "douyin", "shipinhao", "bilibili", "xiaohongshu", "rednote", "toutiao", "juejin", "zhihu"} or "knowledge_card" in content_type:
        skills.append("content/knowledge-card-designer")
    skills.append("content/visual-quality-standards")
    return {
        "version": "content_preflight_manifest_v1",
        "channel": platform,
        "content_type": content_type,
        "rulebook": {
            "loaded": True,
            "path": "config/channel_content_rulebook.json",
            "channel_rules_loaded": True,
        },
        "strategy": {
            "source": "hermes_operating_strategy",
            "result_path": "/ignored-runtime/ops_strategy.json",
            "summary": "strategy selected the topic and content form from account and trend data",
        },
        "skills_loaded": skills,
        "visual_policy": {
            "loaded": True,
            "policy_id": "visual_content_design_policy_v1",
        },
        "topic_plan": {
            "selected_topic": "workflow evidence before publishing",
            "selection_reason": "matches channel lane and current trend evidence",
            "content_angle": "case-first checklist with concrete operating value",
        },
        "asset_requirements": {
            "required_assets": ["cover", "inline_images", "voiceover", "background_music"],
            "source_policy": "licensed_or_verified_runtime_assets",
        },
        "quality_gates": ["content_quality", "visual_quality", "asset_license", "publish_postcheck"],
        "publish_constraints": {
            "delivery_health_required": True,
            "postcheck_required": True,
            "schedule_required": True,
        },
    }


def complete_video_plan():
    return {
        "theme": "publishing failure triage",
        "target_audience": "self-media operators",
        "user_pain": "uploads fail without a clear next action",
        "opening_hook": "stop retrying before knowing the failure class",
        "core_message": "classify the failure before acting",
        "storyboard": ["hook", "login", "assets", "review", "schedule", "evidence", "decision", "postcheck"],
        "voiceover": "segmented narration by beat",
        "subtitle_plan": "lower-third captions",
        "music_plan": "low-volume background bed",
        "ending_cta": "save the checklist before the next upload",
        "visual_alignment_plan": "each scene maps to one operational step",
    }


def complete_visual_recipe(template_family: str = "knowledge_card_motion_case"):
    return {
        "version": "visual_recipe_v1",
        "template_family": template_family,
        "modules": [
            "template_theme",
            "knowledge_card_designer",
            "cinema_color_css",
            "shotcraft_motion_css",
            "lower_third_subtitles",
            "licensed_bgm_mix",
        ],
        "style_variants": {
            "color_mood": "content_matched",
            "motion_density": "medium",
            "text_layout": "headline_plus_lower_third",
            "scene_change_interval_sec": 4,
        },
        "asset_strategy": {
            "primary": "verified_visual_assets",
            "fallback": "html_css_knowledge_card_fallback",
            "forbidden": ["random_unmatched_background", "single_static_background_loop"],
        },
        "selection_reason": "selected from strategy, topic, platform, and available assets",
        "differentiation_reason": "module combination differs from recent same-platform renders",
        "scene_asset_match": [
            {"scene": i, "script_beat": f"beat-{i}", "visual_source": f"asset-{i}.png", "match_reason": "matches narrated beat"}
            for i in range(1, 4)
        ],
        "avoid": ["same_recipe_fingerprint", "same_bgm_fingerprint", "cross_platform_final_reuse"],
        "fingerprint": "sha256:test-visual-recipe",
    }


def complete_growth_strategy(platform: str = "wechat", content_type: str = "long_article"):
    if platform == "wechat":
        return build_growth_strategy([platform], content_type)
    is_video = content_type in {"knowledge_card_video", "short_video", "edited_short_video", "microcase_video"}
    return {
        "policy_id": "growth_quality_policy_v1",
        "platform": platform,
        "content_type": content_type,
        "primary_metric": "completion_rate" if is_video else "click_through_rate",
        "secondary_metrics": ["save_rate", "comment_rate", "follow_conversion_rate"],
        "target_user_action": "save" if is_video else "open_and_save",
        "hook_plan": {
            "type": "conflict_or_payoff",
            "first_screen_promise": "show the useful outcome before asking for attention",
            "curiosity_gap": "what most creators miss before publishing",
        },
        "retention_plan": {
            "first_3_seconds": "result or conflict first",
            "scene_change_interval_seconds": 4 if is_video else 0,
            "midpoint_payoff": "a usable checklist appears before the middle",
        },
        "interaction_plan": {
            "comment_prompt": "ask the user to name the failure they hit",
            "save_reason": "checklist can be reused before publishing",
            "share_reason": "helps another creator avoid a repeat failure",
        },
        "packaging_plan": {
            "title_angle": "mistake to avoid",
            "cover_angle": "proof plus benefit",
            "keyword_intent": "workflow evidence",
        },
        "platform_growth_rules": ["optimize_for_open_rate", "optimize_for_save_rate"],
        "post_publish_review_plan": {
            "review_points_hours": [1, 24, 72],
            "diagnosis_dimensions": ["ctr", "completion", "save", "comment", "follow"],
        },
        "quality_targets": {
            "hook_score": 0.8,
            "first_frame_score": 0.78,
            "save_value_score": 0.76,
            "comment_prompt_score": 0.7,
            "template_fatigue_risk": 0.2,
        },
    }


def complete_video_metadata(platform: str = "kuaishou"):
    adaptation = {"required_fields_checked": True}
    if platform == "kuaishou":
        adaptation.update({"topic_tag_count": 2, "description_hashtag_count": 0})
    tool_manifest = complete_tool_invocation_manifest("video")
    return {
        "platform": platform,
        "preflight_manifest": complete_preflight_manifest(platform, "knowledge_card_video"),
        "visual_content_policy": visual_content_policy([platform], "short_video"),
        "video_plan": complete_video_plan(),
        "visual_recipe": complete_visual_recipe(),
        "tool_invocation_manifest": tool_manifest,
        **build_tool_selection_evidence(
            platform=platform,
            content_type="knowledge_card_video",
            content_goal="increase video retention with matched scenes, motion, voice, subtitles, and BGM",
            planned_manifest=tool_manifest,
        ),
        "real_scene_background_plan": complete_real_scene_background_plan(8),
        "bgm_source": {
            "source": "licensed_music_manifest",
            "license": "cc-by",
            "fit_reason": "low-volume bed selected to support narration",
        },
        "first_three_second_value": "the opening states the mistake to avoid before the user scrolls away",
        "differentiation_dimensions": ["diagnostic structure", "checklist visuals", "warning-first opening"],
        "platform_adaptation": adaptation,
        "growth_strategy": complete_growth_strategy(platform, "knowledge_card_video"),
        "platform_render_identity": {
            "output_path": f"/tmp/current-run/{platform}/final.mp4",
            "script_hash": f"sha256:{platform}-script",
            "visual_hash": f"sha256:{platform}-visual",
            "bgm_fingerprint": f"sha256:{platform}-bgm",
            "same_topic_platforms": ["kuaishou", "shipinhao", "youtube"],
            "not_reused_from_other_platform": True,
            "current_platform": platform,
            "rendered_for_platform": platform,
        },
        "media_delivery": {
            "mode": "independent_media_message",
            "message_kind": "MEDIA",
            "sent_as_separate_message": True,
            "abs_paths": [f"/tmp/current-run/{platform}/final.mp4", f"/tmp/current-run/{platform}/cover.jpg"],
            "text_report_separate": True,
        },
    }


def complete_knowledge_card_plan(platform: str = "wechat"):
    return {
        "skill": "hermes_skill:content/knowledge-card-designer",
        "card_type": "knowledge_summary",
        "platform": platform,
        "audience": "self-media operators",
        "visual_scheme": "cold_brew_professional",
        "typography_hierarchy": "4:2:1",
        "self_check": ["readability", "attraction", "information_density", "share_or_save_value", "visual_match", "mobile_safe_boundaries"],
    }


def complete_wechat_image_post_packet():
    cards = [
        {
            "index": i,
            "role": role,
            "title": f"Card {i} clear point",
            "one_idea": True,
            "layout": layout,
            "palette": palette,
            "image_path": f"/tmp/wechat/cards/card_{i:02d}.png",
            "width": 1080,
            "height": 1440,
            "bytes": 450000 + i,
            "background": {
                "kind": "real_scene_photo",
                "source": "pexels",
                "source_url": f"https://www.pexels.com/photo/{i}/",
                "license": "Pexels License",
                "query": "ai productivity desk",
                "match_reason": "matches the card's productivity workflow point",
                "not_gradient_fallback": True,
            },
            "typography": {
                "title_px": 72,
                "body_px": 38,
                "line_height": 1.65,
                "safe_area_ok": True,
                "overflow": False,
            },
            "engagement": {
                "hook_or_payoff": "shows a concrete benefit",
                "save_reason": "usable checklist",
            },
        }
        for i, (role, layout, palette) in enumerate(
            [
                ("cover", "hero", "cold"),
                ("content", "split", "warm"),
                ("content", "side", "minimal"),
                ("content", "stack", "dark"),
                ("content", "timeline", "fresh"),
                ("content", "quote", "cold"),
                ("content", "checklist", "warm"),
                ("cta", "summary_cta", "minimal"),
            ],
            1,
        )
    ]
    return {
        "platform": "wechat",
        "content_type": "wechat_image_post",
        "title": "我把11个平台交给AI后",
        "desc": "8张图讲清一个AI自动化真实复盘。",
        "card_count": len(cards),
        "cards": cards,
        "design_strategy": {
            "story_arc": ["hook", "problem", "turning_point", "method", "mistake", "checklist", "result", "cta"],
            "visual_consistency": True,
            "layout_diversity": True,
            "source_guidance": ["wechat cover practices", "carousel one idea per slide"],
        },
        "image_text_card_recipe": build_image_text_card_recipe(
            platform="wechat",
            content_type="wechat_image_post",
            title="Operator checklist",
            cards=cards,
            sections=[{"id": f"section_{i}", "role": "content"} for i in range(1, len(cards) + 1)],
            content_goal="increase full reads, saves, shares, comments, and follow conversion",
        ),
        "tool_invocation_manifest": complete_tool_invocation_manifest("article"),
        "publishing_plan": {
            "article_type": "newspic",
            "draft_postcheck": "wechat_image_draft_batchget",
            "publish_mode": "draft",
        },
        "postcheck": {
            "required": True,
            "batchget_verified": True,
            "article_type": "newspic",
            "title_present": True,
            "image_count_matched": True,
        },
    }


def complete_tool_invocation_manifest(content_type: str = "article"):
    if content_type == "video":
        planned = {
            "video_toolchain_runner": "scripts/video_toolchain_runner.py",
            "visual_recipe": "content_platform.video_recipe",
            "shotcraft_moves": "scripts/shotcraft_moves.py",
            "cinema_composition": "scripts/cinema_composition.py",
            "voice_engine": "scripts/voice_engine.py",
            "lower_third_subtitles": "hermes_tool:lower_third_subtitle_renderer",
            "mix_bgm_with_gate": "scripts/mix_bgm_with_gate.py",
            "visual_gate": "scripts/visual_gate.py",
        }
    else:
        planned = {
            "generator_normalize": "content_platform.generator",
            "preflight_manifest": "content_platform.preflight_manifest",
            "visual_policy": "content_platform.visual_content_policy",
            "knowledge_card_designer": "hermes_skill:content/knowledge-card-designer",
        }
    return build_tool_invocation_manifest(
        planned_tools=planned,
        invocations={name: {"status": "ok", "output": ref} for name, ref in planned.items()},
    )


def test_wechat_image_post_packet_requires_real_scene_cards_and_hard_postcheck():
    packet = complete_wechat_image_post_packet()
    result = validate_wechat_image_post_packet(packet)
    assert result["passed"], result

    bad = json.loads(json.dumps(packet))
    bad["cards"][1]["background"]["kind"] = "css_gradient"
    bad["cards"][1]["background"]["not_gradient_fallback"] = False
    result = validate_wechat_image_post_packet(bad)
    assert not result["passed"]
    assert "real_scene_backgrounds" in result["failed_dimensions"]

    bad = json.loads(json.dumps(packet))
    bad["postcheck"]["batchget_verified"] = False
    result = validate_wechat_image_post_packet(bad)
    assert not result["passed"]
    assert "draft_postcheck" in result["failed_dimensions"]


def test_image_text_card_recipe_requires_style_matrix_and_asset_binding():
    packet = complete_wechat_image_post_packet()
    recipe = packet["image_text_card_recipe"]
    result = validate_image_text_card_recipe(recipe)
    assert result["passed"], result

    bad = json.loads(json.dumps(recipe))
    bad["layout_matrix"]["background_effects"] = []
    result = validate_image_text_card_recipe(bad)
    assert not result["passed"]
    assert "content_recipe" in result["failed_dimensions"]

    bad = json.loads(json.dumps(packet))
    bad.pop("image_text_card_recipe")
    result = validate_wechat_image_post_packet(bad)
    assert not result["passed"]
    assert "image_text_card_recipe" in result["failed_dimensions"]


def test_image_text_card_recipe_cli_accepts_full_packet(tmp_path):
    packet_path = tmp_path / "wechat_image_post_packet.json"
    packet_path.write_text(json.dumps(complete_wechat_image_post_packet()), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "validate_image_text_card_recipe.py"), str(packet_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def complete_tool_selection_evidence(platform: str = "wechat", content_type: str = "article"):
    return build_tool_selection_evidence(
        platform=platform,
        content_type=content_type,
        content_goal="increase retention, saves, and follow conversion with topic-matched assets",
        planned_manifest=complete_tool_invocation_manifest("video" if "video" in content_type else "article"),
    )


def complete_knowledge_cards(prefix: str = "card", count: int = 3):
    return [
        {
            "section": f"section-{i}",
            "script_beat": f"beat-{i}",
            "card_type": "step_tutorial",
            "layout": "timeline" if i % 2 else "visual_anchor",
            "visual_subject": f"{prefix}-{i} matched visual",
            "information_value": "explains the adjacent point instead of decorating",
            "self_check": ["readability", "attraction", "information_density", "visual_match", "mobile_safe_boundaries"],
        }
        for i in range(count)
    ]


def complete_real_scene_background_plan(count: int = 3):
    common_sections = ["problem", "case", "method", "why", "fit", "test", "hook", "checklist"]
    return {
        "required": True,
        "source_policy": "licensed_or_verified_real_scene_assets",
        "primary_background_kind": "real_scene_photo",
        "no_css_gradient_primary": True,
        "forbidden_backgrounds": ["css_gradient", "solid_color", "abstract_shape", "design_card"],
        "per_slide_backgrounds": [
            {
                "asset_id": f"real-bg-{i}",
                "asset_type": "photo",
                "background_kind": "real_scene_photo",
                "source": f"https://licensed.example/real-bg-{i}.jpg",
                "rights_cleared": True,
                "real_scene": True,
                "match_reason": "matches the adjacent content beat",
                "card_id": f"card-{i}",
                "section": common_sections[i - 1] if i <= len(common_sections) else f"section-{i}",
                "sections": [f"section-{i}", common_sections[i - 1] if i <= len(common_sections) else f"section-{i}"],
                "beat": f"beat {i - 1}",
                "script_beat": f"beat {i - 1}",
                "visual_asset": f"clip-{i - 1}.mp4",
                "visual_assets": [f"clip-{i - 1}.mp4", f"clip-{i}.mp4", f"card-{i - 1}.png", f"card-{i}.png"],
                "image": f"{i:02d}.png",
            }
            for i in range(1, count + 1)
        ],
    }


def complete_full_ops_evidence(platform: str):
    sources = [
        "account_history",
        "same_lane_accounts",
        "bilibili",
        "wechat",
        "xiaohongshu",
        "youtube",
        "external_hot_platforms",
    ]
    inputs = [
        "account_analysis",
        "same_lane_account_analysis",
        "cross_platform_trend_analysis",
        "topic_selection",
        "quantity_plan",
        "content_brief",
    ]
    return {
        "platform_source_matrix": {
            "platform": platform,
            "attempted_sources": [
                {"source": f"{platform}_internal_search", "status": "success", "sample_count": 3, "collected_at": "2026-08-16T00:00:00+00:00"},
                {"source": "account_history", "status": "success", "sample_count": 6, "collected_at": "2026-08-16T00:00:00+00:00"},
                {"source": "same_lane_accounts", "status": "success", "sample_count": 3, "collected_at": "2026-08-16T00:00:00+00:00"},
                {"source": "bilibili", "status": "success", "sample_count": 2, "collected_at": "2026-08-16T00:00:00+00:00"},
                {"source": "wechat", "status": "failed", "reason": "no same-day public rank"},
            ],
            "successful_source_count": 4,
            "platform_internal_verified": True,
            "real_platform_collection_verified": True,
            "current_platform_specific_topic": True,
            "shared_trend_only": False,
            "report_path": f"/tmp/current-run/{platform}/source_matrix.json",
            "trend_evidence": {"source": f"{platform}_internal_search", "collected_at": "2026-08-16T00:00:00+00:00", "samples": [{"title": "real collected sample"}]},
        },
        "operations_workflow": {
            "required": True,
            "platforms": [platform],
            "cross_platform_sources": sources,
        },
        "account_analysis": {
            "source": "hermes_operating_strategy",
            "account_lane": "AI efficiency and open-source tools",
            "current_content_data": {"recent_items": 12, "strong_topics": ["workflow", "tools"]},
            "audience_profile": "operators and builders who need practical workflow evidence",
        },
        "same_lane_account_analysis": {
            "source": "same_lane_account_benchmark",
            "samples": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "borrowable_patterns": ["case-first hook", "saveable checklist", "visual proof"],
        },
        "cross_platform_trend_analysis": {
            "source": "cross_platform_hot_trend_collection",
            "required_sources": sources,
            "topic_clusters": [{"label": "automation workflow", "score": 0.8}],
            "hot_topics": ["agent workflow", "open-source tools", "content automation"],
        },
        "quantity_plan": {
            "source": "hermes_operating_strategy",
            "base_count": 1,
            "extra_count": 2,
            "final_count": 3,
            "decision_reason": "account capacity and current trend confidence support three review candidates",
        },
        "topic_selection": {
            "selected_topic": "workflow evidence before publishing",
            "selection_reason": "matches account history and cross-platform trend signals",
            "content_angle": "case-first operating checklist",
        },
        "content_generation_brief": {
            "provided_to_content_workflow": True,
            "source_inputs": inputs,
            "copy_plan": {"opening_hook": "show the conflict first", "reader_payoff": "reader knows what to change"},
            "script_plan": {"required": True, "human_voice": "natural pacing"},
            "seo_geo_plan": {"title": "searchable title", "digest": "short payoff", "keywords": ["workflow"]},
            "topic_tags": ["#AI工具", "#内容运营"],
            "asset_mix_plan": {
                "ai_generated": "knowledge-card visuals",
                "real_material_retrieval": "screenshots and process evidence",
                "ai_edit_real_material": "crop and overlay cards",
            },
            "humanization_plan": {"hook": "conflict first", "body": "concrete case", "voice": "natural pacing"},
        },
        "content_workflow_inputs": {
            "source_inputs": inputs,
            "copy_plan_required": True,
            "script_plan_required": True,
            "seo_geo_plan_required": True,
            "topic_tags_required": True,
            "asset_mix_plan_required": True,
            "humanization_plan_required": True,
        },
    }


def complete_wechat_auto_packet():
    body = "\n\n".join([
        "<h2>Why this GitHub project matters</h2><p>" + "practical operating paragraph " * 12 + "</p><img src=\"https://cdn.example/1.jpg\">",
        "<h2>Where it fits</h2><p>" + "practical operating paragraph " * 12 + "</p><img src=\"https://cdn.example/2.jpg\">",
        "<h2>How to test it</h2><p>" + "practical operating paragraph " * 12 + "</p><img src=\"https://cdn.example/3.jpg\">",
        "<h2>Limits</h2><p>" + "practical operating paragraph " * 8 + "</p>",
        "<h2>Checklist</h2><p>" + "practical operating paragraph " * 8 + "</p>",
    ])
    tool_manifest = complete_tool_invocation_manifest("article")
    return {
        "platform": "wechat",
        "preflight_manifest": complete_preflight_manifest("wechat", "long_article"),
        "title": "GitHub project selection for content operators",
        "body": body,
        "digest": "Two GitHub projects worth testing this week",
        "visual_content_policy": visual_content_policy(["wechat"], "long_article"),
        "growth_strategy": complete_growth_strategy("wechat", "long_article"),
        "opening_hook": "A GitHub project can look popular and still waste your publishing day if the use case is wrong.",
        "hook_type": "conflict_case",
        "sections": ["why", "fit", "test", "limits", "checklist"],
        "visual_template_selection": {
            "selected": "github_project_casebook",
            "ranked_scores": [{"template": "github_project_casebook", "score": 90}],
            "recent_same_platform_templates": ["blue_pro"],
            "penalties": {"blue_pro": 30},
        },
        "strategy_brief": {
            "target_user": "AI content operators",
            "channel_lane": "GitHub project selection",
            "topic_basis": "GitHub Trending and curated repo sources",
            "click_reason": "choose a tool before competitors copy the topic",
            "reader_payoff": "two repos and a test checklist",
            "chosen_structure": "project-case-checklist",
            "content_form": "longform article",
            "content_direction": "github_project_selection",
            "selected_theme_reason": "developer project article needs a casebook layout",
            "seo_digest": "Two GitHub projects worth testing this week",
        },
        "account_analysis": {
            "account_lane": "AI efficiency and open-source tools",
            "current_content_data": {"recent_articles": 12, "strong_topics": ["workflow", "GitHub tools"]},
            "audience_profile": "operators and builders who save practical tool walkthroughs",
        },
        "same_lane_account_analysis": {
            "source": "wechat_same_lane_hot_account_probe",
            "accounts": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "borrowable_patterns": ["case-first hook", "tool decision checklist", "saveable ending"],
        },
        "cross_platform_trend_analysis": {
            "source": "wechat_plus_external_same_lane_trends",
            "wechat_same_lane_samples": [{"title": "w1"}, {"title": "w2"}, {"title": "w3"}],
            "external_platform_samples": [{"title": "x1"}, {"title": "x2"}, {"title": "x3"}],
            "hot_topics": ["agent workflow", "GitHub automation", "ROI proof"],
        },
        "topic_selection": {
            "selected_topic": "A GitHub automation project worth testing today",
            "selection_reason": "matches account lane, external heat, and reader save intent",
            "article_angle": "case-first evaluation with a practical adoption checklist",
        },
        "content_generation_brief": {
            "provided_to_content_workflow": True,
            "source_inputs": [
                "account_analysis",
                "same_lane_account_analysis",
                "cross_platform_trend_analysis",
                "topic_selection",
            ],
            "headline_hook": "Most AI tool articles miss the one test that decides whether a repo is worth using.",
            "article_plan": ["hook", "project value", "fit matrix", "hands-on check", "next action"],
        },
        "content_channels": {
            "github_selection": True,
            "hot_content_generation": True,
        },
        "source_data": {
            "github_projects": [{"repo": "owner/repo", "url": "https://github.com/owner/repo"}],
            "github_ai_projects": [{"repo": "owner/ai-repo", "url": "https://github.com/owner/ai-repo"}],
            "github_non_ai_projects": [{"repo": "owner/non-ai-repo", "url": "https://github.com/owner/non-ai-repo"}],
            "hot_content_items": [{"title": "h1"}, {"title": "h2"}, {"title": "h3"}],
        },
        "selected_project": {
            "repo": "owner/repo",
            "url": "https://github.com/owner/repo",
            "screenshot_url": "https://cdn.example/github-owner-repo.png",
        },
        "batch_plan": {"expected_count": 2, "item_index": 1},
        "section_image_map": [
            {"section": "why", "image": "01.png", "purpose": "show repository value", "adjacent_to_text": True},
            {"section": "fit", "image": "02.png", "purpose": "map use case", "adjacent_to_text": True},
            {"section": "test", "image": "03.png", "purpose": "show test checklist", "adjacent_to_text": True},
        ],
        "real_scene_background_plan": complete_real_scene_background_plan(3),
        "knowledge_card_plan": complete_knowledge_card_plan("wechat"),
        "embedded_knowledge_cards": complete_knowledge_cards("wechat"),
        "article_recipe": build_article_recipe(
            platform="wechat",
            content_type="long_article",
            title="GitHub project selection for content operators",
            body=body,
            sections=["why", "fit", "test", "limits", "checklist"],
            section_image_map=[
                {"section": "why", "image": "01.png", "purpose": "show repository value", "adjacent_to_text": True},
                {"section": "fit", "image": "02.png", "purpose": "map use case", "adjacent_to_text": True},
                {"section": "test", "image": "03.png", "purpose": "show test checklist", "adjacent_to_text": True},
            ],
            embedded_knowledge_cards=complete_knowledge_cards("wechat"),
            visual_template_selection={
                "selected": "github_project_casebook",
                "ranked_scores": [{"template": "github_project_casebook", "score": 90}, {"template": "magazine_grid", "score": 76}],
            },
        ),
        "knowledge_card_recipe": build_knowledge_card_recipe(
            platform="wechat",
            cards=complete_knowledge_cards("wechat"),
            content_type="long_article",
        ),
        "tool_invocation_manifest": tool_manifest,
        **build_tool_selection_evidence(
            platform="wechat",
            content_type="long_article",
            content_goal="increase article opens, saves, and follow conversion with matched cards and inline visuals",
            planned_manifest=tool_manifest,
        ),
        "cover_design": {
            "visual_subject": "GitHub repository decision board",
            "topic_alignment": "matches the selected project",
            "mobile_readable": True,
            "visual_hierarchy": "repo, use case, checklist",
            "template_family": "github_project_casebook",
            "cdn_url": "https://cdn.example/cover.jpg",
        },
        "differentiation_dimensions": ["github source", "casebook theme", "operator checklist"],
        "reader_payoff": "reader can test the repo today",
        "concrete_case": "evaluating one GitHub repo for content workflow use",
        "actionable_checklist": ["check license", "run demo", "map content angle"],
        "publishing_plan": {"postcheck": "wechat_draft_batchget"},
        "article_artifact_probe": {
            "word_count": 1580,
            "inline_image_count": 3,
            "adjacent_inline_image_count": 3,
            "theme_css_inlined": True,
            "cover_uploaded": True,
            "body_font_px": 16,
            "draft_batchget_planned": True,
        },
    }


def complete_kuaishou_auto_packet():
    packet = {
        **complete_video_metadata("kuaishou"),
        "content_form": "knowledge_card_video",
        "audio_probe": {"stream_count": 1, "duration": 58},
        "subtitle": {"cue_count": 10},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": 16,
            "max_lines": 2,
            "margin_v": 200,
        },
        "visual_probe": {"occupied_frame_ratio": 0.94, "distinct_scene_count": 8, "unique_source_count": 4},
        "knowledge_card_sequence": [
            {
                "card_type": "step_tutorial",
                "layout": layout,
                "visual_subject": f"{layout} operation card",
                "information_value": "explains one workflow beat",
                "script_beat": f"beat-{idx}",
                "self_check": ["readability", "attraction", "information_density", "visual_match", "mobile_safe_boundaries"],
            }
            for idx, layout in enumerate(["big_text_contrast", "split_left_right", "timeline", "card_stack", "big_number", "diagonal"], 1)
        ],
        "source_assets": [
            {"rights_cleared": True, "behavior_match": True, "real_scene": True, "source": f"https://licensed.example/clip-{i}.mp4"}
            for i in range(4)
        ],
        "real_scene_background_plan": complete_real_scene_background_plan(8),
        "first_second_hook": "Stop posting before your draft has postcheck evidence.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {
            "provider": "edge_tts_segmented_natural",
            "segment_count": 8,
            "pause_plan": [0.42, 0.35, 0.5, 0.3],
            "emotion_cues": ["hook", "warning", "resolution"],
            "human_pacing": True,
        },
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"clip-{i}.mp4", "match_reason": "matches the narrated step"}
            for i in range(8)
        ],
        "strategy_brief": {
            "target_user": "Kuaishou self-media operators",
            "channel_lane": "ops microcase",
            "topic_basis": "current Kuaishou same-lane hot samples",
            "content_form": "knowledge_card_video",
        },
        "trend_evidence": {
            "source": "kuaishou_hot_same_lane_probe",
            "collected_at": "2026-07-21T10:00:00+08:00",
            "samples": [{"title": "a"}, {"title": "b"}, {"title": "c"}],
        },
        "workflow_evidence": {
            "completed_steps": [
                "strategy",
                "trend_analysis",
                "content_generation",
                "quality_gate",
                "scheduled_upload",
                "management_postcheck",
            ]
        },
        "bgm": {
            "source": "jamendo",
            "source_url": "https://jamendo.example/track/123",
            "license": "cc-by",
            "fit_reason": "acoustic bed does not mask the narration",
            "manifest": {
                "source_url": "https://jamendo.example/track/123",
                "license": "cc-by",
                "fingerprint": "sha256:test-bgm",
            },
        },
        "bgm_history_check": {
            "registry_path": "~/.hermes/data/bgm_fingerprint.json",
            "current_fingerprint": "sha256:test-bgm",
            "current_title": "Independent acoustic bed",
            "current_source_url": "https://jamendo.example/track/123",
            "recent_fingerprints": ["sha256:older-bgm"],
            "same_batch_fingerprints": ["sha256:other-video-bgm"],
            "duplicate_found": False,
            "checked": True,
        },
        "publishing_plan": {
            "schedule_at": "2026-07-21 19:30",
            "postcheck": "kuaishou_management_pending_list_with_exact_schedule_time",
        },
        "video_artifact_probe": {
            "file_exists": True,
            "duration_seconds": 58.0,
            "audio_stream_count": 1,
            "mean_volume_db": -18.0,
            "subtitle_position": "lower_third",
            "distinct_scene_count": 8,
            "unique_source_count": 4,
            "resolution": "1080x1920",
        },
    }
    return packet


def complete_shipinhao_auto_packet():
    packet = complete_kuaishou_auto_packet()
    packet.update(
        {
            **complete_video_metadata("shipinhao"),
            "platform": "shipinhao",
            "content_form": "knowledge_card_video",
            "strategy_brief": {
                "target_user": "Video Channels self-media operators",
                "channel_lane": "WeChat ecosystem operations",
                "topic_basis": "current Video Channels retention and share evidence",
                "content_form": "knowledge_card_video",
                "wechat_ecosystem_context": "connect short video proof to official account follow-up reading",
                "target_share_or_save_reason": "the ending card gives a reusable checklist and QR path",
                "retention_problem_addressed": "low completion caused by weak ending payoff",
                "same_day_kuaishou_dedupe_result": "independent topic, visual family, and CTA from Kuaishou batch",
            },
            "platform_adaptation": {
                "required_fields_checked": True,
                "wechat_ecosystem_context": "official account QR is part of the manual review package",
            },
            "ending_card": {
                "required": True,
                "card_index": 8,
                "title": "扫码看完整清单",
                "cta_type": "wechat_official_account_followup",
                "cta_text": "关注公众号，拿完整发布前检查表",
                "wechat_qr_asset": "assets/wechat_official_qr.png",
                "qr_visible": True,
                "qr_position": "lower_right",
                "qr_source": "verified_official_account_qr",
                "title_max_chars": 16,
                "wechat_ecosystem_reason": "Video Channels sends interested viewers to deeper WeChat article context",
            },
            "ending_card_probe": {
                "frame_path": "/ignored-runtime/shipinhao/ending_card_probe.png",
                "qr_detected": True,
                "qr_visible": True,
                "qr_contrast_ok": True,
                "overlay_opacity_max": 0.55,
                "safe_area_ok": True,
                "title_chars": 8,
            },
        }
    )
    packet["publishing_plan"] = {"candidate_review_only": True, "postcheck": "local_review_package_ready_user_manual_publish"}
    return packet


def complete_xiaohongshu_auto_packet():
    tool_manifest = complete_tool_invocation_manifest("article")
    return {
        **complete_full_ops_evidence("xiaohongshu"),
        "platform": "xiaohongshu",
        "content_type": "image_text_knowledge_card_short_video_mix",
        "content_form": "image_text_knowledge_card_short_video_mix",
        "preflight_manifest": complete_preflight_manifest("xiaohongshu", "image_text_knowledge_card_short_video_mix"),
        "visual_content_policy": visual_content_policy(["xiaohongshu"], "note"),
        "growth_strategy": complete_growth_strategy("xiaohongshu", "image_text_knowledge_card_short_video_mix"),
        "title": "别再把自动化当成万能发布按钮",
        "body": "这条笔记给正在做内容自动化的人一个真实提醒：" + "流程能自动跑，不代表内容就值得发。" * 35 + "AI辅助创作，已人工复核。",
        "caption": "AI辅助创作，人工复核后发布。",
        "knowledge_card_sequence": complete_knowledge_cards("xiaohongshu"),
        "knowledge_card_recipe": build_knowledge_card_recipe(
            platform="xiaohongshu",
            cards=complete_knowledge_cards("xiaohongshu"),
            content_type="image_text_knowledge_card_short_video_mix",
        ),
        "tool_invocation_manifest": tool_manifest,
        **build_tool_selection_evidence(
            platform="xiaohongshu",
            content_type="note",
            content_goal="increase saves and follows with matched note cards, real-scene assets, and manual handoff",
            planned_manifest=tool_manifest,
        ),
        "section_image_map": [
            {"section": "hook", "image": "01.png", "purpose": "show the failed publish checkpoint"},
            {"section": "case", "image": "02.png", "purpose": "show the real review process"},
            {"section": "checklist", "image": "03.png", "purpose": "show the manual publish checklist"},
        ],
        "cover_design": {
            "visual_subject": "manual content review desk",
            "topic_alignment": "matches Xiaohongshu manual review workflow",
            "mobile_readable": True,
            "visual_hierarchy": "hook, warning, checklist",
            "template_family": "field_note_cards",
        },
        "source_assets": [
            {"source": "runtime screenshot", "authentic": True, "rights_cleared": True, "real_scene": True},
            {"source": "process photo", "authentic": True, "rights_cleared": True, "real_scene": True},
            {"source": "manual checklist", "authentic": True, "rights_cleared": True, "real_scene": True},
        ],
        "real_scene_background_plan": complete_real_scene_background_plan(3),
        "video_plan": {
            "theme": "manual handoff review",
            "opening_hook": "先别急着发布，先看这三个证据。",
            "visual_alignment_plan": "each card maps to one review step",
        },
        "publishing_plan": {"manual_review_required": True},
        "manual_publish_package": {"live_publish_allowed": False},
    }


def test_article_packet_requires_hook_length_template_and_mapped_images():
    tool_manifest = complete_tool_invocation_manifest("article")
    packet = {
        "platform": "wechat",
        "preflight_manifest": complete_preflight_manifest("wechat", "long_article"),
        "visual_content_policy": visual_content_policy(["wechat"], "long_article"),
        "growth_strategy": complete_growth_strategy("wechat", "long_article"),
        "body": "practical operating paragraph " * 80,
        "opening_hook": "A workflow that looks complete can still fail readers when the first real case is missing.",
        "hook_type": "conflict_case",
        "sections": ["problem", "case", "why old way fails", "method", "checklist"],
        "visual_template_selection": {
            "selected": "case_story_v1",
            "ranked_scores": [{"template": "case_story_v1", "score": 80}],
            "recent_same_platform_templates": ["checklist_v1"],
            "penalties": {"checklist_v1": 20},
        },
        "strategy_brief": {
            "target_user": "operators",
            "channel_lane": "AI operations",
            "topic_basis": "recent delivery failures",
            "click_reason": "avoid repeating a costly publishing mistake",
            "reader_payoff": "a checklist they can reuse",
            "chosen_structure": "case-breakdown-method",
            "content_form": "longform article",
        },
        "section_image_map": [
            {"section": "problem", "image": "01.png", "purpose": "open the pain point", "adjacent_to_text": True},
            {"section": "case", "image": "02.png", "purpose": "show the specific case", "adjacent_to_text": True},
            {"section": "method", "image": "03.png", "purpose": "explain the steps", "adjacent_to_text": True},
        ],
        "real_scene_background_plan": complete_real_scene_background_plan(3),
        "knowledge_card_plan": complete_knowledge_card_plan(),
        "embedded_knowledge_cards": complete_knowledge_cards("article"),
        "article_recipe": build_article_recipe(
            platform="wechat",
            content_type="long_article",
            title="workflow quality gate case",
            body="practical operating paragraph " * 80,
            sections=["problem", "case", "why old way fails", "method", "checklist"],
            section_image_map=[
                {"section": "problem", "image": "01.png", "purpose": "open the pain point", "adjacent_to_text": True},
                {"section": "case", "image": "02.png", "purpose": "show the specific case", "adjacent_to_text": True},
                {"section": "method", "image": "03.png", "purpose": "explain the steps", "adjacent_to_text": True},
            ],
            embedded_knowledge_cards=complete_knowledge_cards("article"),
            visual_template_selection={
                "selected": "case_story_v1",
                "ranked_scores": [{"template": "case_story_v1", "score": 80}, {"template": "field_note", "score": 70}],
            },
        ),
        "knowledge_card_recipe": build_knowledge_card_recipe(platform="wechat", cards=complete_knowledge_cards("article"), content_type="long_article"),
        "tool_invocation_manifest": tool_manifest,
        **build_tool_selection_evidence(
            platform="wechat",
            content_type="long_article",
            content_goal="increase article completion and saves with case-led structure and matched visuals",
            planned_manifest=tool_manifest,
        ),
        "cover_design": {
            "visual_subject": "failed schedule checklist",
            "topic_alignment": "matches the article promise",
            "mobile_readable": True,
            "visual_hierarchy": "title, warning mark, checklist",
            "template_family": "casebook",
        },
        "differentiation_dimensions": ["case-led opening", "checklist structure", "warm warning tone"],
        "reader_payoff": "reader can apply a checklist today",
        "concrete_case": "failed scheduled publication diagnosis",
        "actionable_checklist": ["check title", "check cover", "check postcheck"],
    }
    assert validate_article_packet(packet)["passed"] is True


def test_content_recipe_core_fingerprint_ignores_platform_for_cross_platform_reuse():
    cards = complete_knowledge_cards("reuse")
    base = build_knowledge_card_recipe(platform="douyin", cards=cards, content_type="knowledge_card_video")
    cross = build_knowledge_card_recipe(platform="youtube", cards=cards, content_type="knowledge_card_video")

    assert base["core_fingerprint"] == cross["core_fingerprint"]
    assert base["fingerprint"] != cross["fingerprint"]

    article_a = build_article_recipe(
        platform="wechat",
        content_type="long_article",
        title="A",
        body="same article body " * 80,
        sections=["hook", "case", "method"],
        section_image_map=[
            {"section": "hook", "image": "01.png", "purpose": "open"},
            {"section": "case", "image": "02.png", "purpose": "prove"},
            {"section": "method", "image": "03.png", "purpose": "teach"},
        ],
        embedded_knowledge_cards=cards,
        visual_template_selection={"selected": "casebook", "ranked_scores": [{"template": "casebook", "score": 90}, {"template": "field", "score": 70}]},
    )
    article_b = {**article_a, "platform": "zhihu"}
    article_b["core_fingerprint"] = build_article_recipe(
        platform="zhihu",
        content_type="long_article",
        title="B",
        body="same article body " * 80,
        sections=["hook", "case", "method"],
        section_image_map=[
            {"section": "hook", "image": "01.png", "purpose": "open"},
            {"section": "case", "image": "02.png", "purpose": "prove"},
            {"section": "method", "image": "03.png", "purpose": "teach"},
        ],
        embedded_knowledge_cards=cards,
        visual_template_selection={"selected": "casebook", "ranked_scores": [{"template": "casebook", "score": 90}, {"template": "field", "score": 70}]},
    )["core_fingerprint"]

    assert article_a["core_fingerprint"] == article_b["core_fingerprint"]


def test_article_packet_rejects_css_gradient_backgrounds():
    packet = complete_wechat_auto_packet()
    packet["real_scene_background_plan"] = {
        "required": True,
        "source_policy": "licensed_or_verified_real_scene_assets",
        "primary_background_kind": "css_gradient",
        "no_css_gradient_primary": False,
        "per_slide_backgrounds": [
            {"asset_id": "g1", "asset_type": "css_gradient", "source": "css", "rights_cleared": True, "real_scene": False, "match_reason": "decorative"}
        ],
    }

    result = validate_article_packet(packet)

    assert result["passed"] is False
    assert "real_scene_backgrounds" in result["failed_dimensions"]


def test_growth_package_rejects_missing_hook_retention_and_review_plan():
    packet = {"platform": "wechat", "content_type": "long_article", "growth_strategy": {"policy_id": "growth_quality_policy_v1"}}

    result = validate_growth_package(packet)

    assert result["passed"] is False
    assert "growth_strategy" in result["failed_dimensions"]
    assert "growth_quality_targets" in result["failed_dimensions"]


def test_growth_package_accepts_complete_platform_plan():
    packet = {
        "platform": "kuaishou",
        "content_type": "knowledge_card_video",
        "growth_strategy": complete_growth_strategy("kuaishou", "knowledge_card_video"),
    }

    result = validate_growth_package(packet)

    assert result["passed"] is True


def test_article_packet_requires_preflight_manifest():
    packet = complete_wechat_auto_packet()
    packet.pop("preflight_manifest")

    result = validate_wechat_auto_packet(packet)

    assert result["passed"] is False
    assert "base_article_quality" in result["failed_dimensions"]
    assert "preflight_manifest" in result["gates"]["base_article_quality"]["failed"]


def test_preflight_manifest_requires_visual_quality_standards_skill():
    packet = {
        "platform": "kuaishou",
        "content_form": "knowledge_card_video",
        "knowledge_card_sequence": complete_knowledge_cards("skill-check"),
        "preflight_manifest": complete_preflight_manifest("kuaishou", "knowledge_card_video"),
    }
    packet["preflight_manifest"]["skills_loaded"] = [
        skill for skill in packet["preflight_manifest"]["skills_loaded"] if skill != "content/visual-quality-standards"
    ]

    result = validate_preflight_manifest(packet, "kuaishou")

    assert result["passed"] is False
    assert "preflight_manifest.skills_missing:content/visual-quality-standards" in result["failed_dimensions"]


def test_wechat_auto_packet_requires_github_source_and_inline_images():
    packet = complete_wechat_auto_packet()
    assert validate_wechat_auto_packet(packet)["passed"] is True
    packet["source_data"] = {"github_projects": []}
    result = validate_wechat_auto_packet(packet)
    assert result["passed"] is False
    assert "github_project_source" in result["failed_dimensions"]


def test_wechat_auto_packet_requires_github_project_link_and_visual():
    packet = complete_wechat_auto_packet()
    packet["selected_project"] = {"repo": "owner/repo", "url": "https://github.com/owner/repo"}

    result = validate_wechat_auto_packet(packet)

    assert result["passed"] is False
    assert "github_project_source" in result["failed_dimensions"]


def test_wechat_auto_packet_requires_operations_context_before_content_workflow():
    packet = complete_wechat_auto_packet()
    assert validate_wechat_auto_packet(packet)["passed"] is True
    packet["account_analysis"] = {}
    packet["content_generation_brief"]["source_inputs"] = ["topic_selection"]

    result = validate_wechat_auto_packet(packet)

    assert result["passed"] is False
    assert "account_data_analysis" in result["failed_dimensions"]
    assert "content_workflow_inputs" in result["failed_dimensions"]


def test_wechat_auto_packet_requires_dual_github_and_hot_content_channels():
    packet = complete_wechat_auto_packet()
    assert validate_wechat_auto_packet(packet)["passed"] is True
    packet["source_data"]["github_non_ai_projects"] = []
    packet["source_data"]["hot_content_items"] = [{"title": "only one"}]

    result = validate_wechat_auto_packet(packet)

    assert result["passed"] is False
    assert "dual_content_channels" in result["failed_dimensions"]


def test_wechat_auto_packet_requires_artifact_probe_not_only_declared_fields():
    packet = complete_wechat_auto_packet()
    assert validate_wechat_auto_packet(packet)["passed"] is True
    packet["article_artifact_probe"] = {
        "word_count": 900,
        "inline_image_count": 3,
        "adjacent_inline_image_count": 1,
        "theme_css_inlined": False,
        "cover_uploaded": True,
        "body_font_px": 14,
        "draft_batchget_planned": True,
    }

    result = validate_wechat_auto_packet(packet)

    assert result["passed"] is False
    assert "article_artifact_probe" in result["failed_dimensions"]


def test_auto_packet_cli_reports_missing_file_without_traceback():
    root = Path(__file__).resolve().parents[1]

    for script_name in ("validate_wechat_auto_packet.py", "validate_kuaishou_auto_packet.py"):
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / script_name), str(root / ".codex-tmp" / "missing-packet.json")],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 2
        assert "packet_file_missing" in result.stdout
        assert "Traceback" not in result.stderr


def test_build_preflight_manifest_cli_outputs_valid_manifest(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "preflight_manifest.json"

    build = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "build_preflight_manifest.py"),
            "--channel",
            "kuaishou",
            "--content-type",
            "knowledge_card_video",
            "--strategy-source",
            "hermes_operating_strategy",
            "--strategy-result-path",
            "/ignored-runtime/kuaishou_strategy.json",
            "--strategy-summary",
            "Kuaishou strategy, trend, and topic decision loaded",
            "--selected-topic",
            "workflow evidence before upload",
            "--selection-reason",
            "matches same-lane trend and account need",
            "--content-angle",
            "operator microcase video",
            "--required-asset",
            "voiceover",
            "--required-asset",
            "background_music",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0

    packet = {"platform": "kuaishou", "preflight_manifest": json.loads(output.read_text(encoding="utf-8"))}
    validate = subprocess.run(
        [sys.executable, str(root / "scripts" / "validate_preflight_manifest.py"), str(tmp_path / "packet.json"), "--channel", "kuaishou"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 2
    (tmp_path / "packet.json").write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
    validate = subprocess.run(
        [sys.executable, str(root / "scripts" / "validate_preflight_manifest.py"), str(tmp_path / "packet.json"), "--channel", "kuaishou"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert validate.returncode == 0


def test_wechat_auto_packet_rejects_malformed_batch_without_traceback():
    packet = complete_wechat_auto_packet()
    packet["batch_plan"] = {"expected_count": "two", "item_index": "first"}

    result = validate_wechat_auto_packet(packet)

    assert result["passed"] is False
    assert "batch_quantity_contract" in result["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_soundhelix_and_repeated_layouts():
    packet = complete_kuaishou_auto_packet()
    assert validate_kuaishou_auto_packet(packet)["passed"] is True
    packet["bgm"] = {"source": "soundhelix", "license": "cc-by", "fit_reason": "fallback"}
    for card in packet["knowledge_card_sequence"]:
        card["layout"] = "same"
    result = validate_kuaishou_auto_packet(packet)
    assert result["passed"] is False
    assert "real_music_source" in result["failed_dimensions"]
    assert "card_layout_diversity" in result["failed_dimensions"]


def test_kuaishou_auto_packet_requires_bgm_license_manifest():
    packet = complete_kuaishou_auto_packet()
    packet["bgm"].pop("manifest")

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "bgm_license_manifest" in result["failed_dimensions"]


def test_kuaishou_auto_packet_requires_bgm_source_url_in_manifest():
    packet = complete_kuaishou_auto_packet()
    packet["bgm"]["manifest"] = {
        "asset_id": "jamendo-123",
        "license": "cc-by",
        "fingerprint": "sha256:test-bgm",
    }

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "bgm_license_manifest" in result["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_any_bgm_fallback_even_with_reason():
    packet = complete_kuaishou_auto_packet()
    packet["bgm"]["fallback_used"] = True
    packet["bgm"]["fallback_exception_reason"] = "all online sources timed out"

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "no_silent_bgm_fallback" in result["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_bad_subtitle_layout():
    packet = complete_kuaishou_auto_packet()
    packet["burned_captions"]["margin_v"] = 60
    packet["burned_captions"]["max_chars_per_line"] = 30

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "subtitle_layout" in result["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_generated_synthetic_bgm_source():
    packet = complete_kuaishou_auto_packet()
    packet["bgm"] = {
        "source": "generated_synthetic_bgm",
        "license": "operator_provided",
        "fit_reason": "fallback",
        "manifest": {"asset_id": "synthetic", "license": "operator_provided", "fingerprint": "x"},
    }

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "real_music_source" in result["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_local_bgm_library_source():
    packet = complete_kuaishou_auto_packet()
    packet["bgm"] = {
        "source": "local_instrument_bgm_library",
        "license": "operator_provided",
        "fit_reason": "local fallback",
        "manifest": {"asset_id": "local", "license": "operator_provided", "fingerprint": "x"},
    }

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "real_music_source" in result["failed_dimensions"]


def test_kuaishou_auto_packet_requires_real_video_artifact_probe():
    packet = complete_kuaishou_auto_packet()
    assert validate_kuaishou_auto_packet(packet)["passed"] is True
    packet["video_artifact_probe"] = {
        "file_exists": True,
        "duration_seconds": 28.0,
        "audio_stream_count": 0,
        "mean_volume_db": -45.0,
        "subtitle_position": "middle",
        "distinct_scene_count": 2,
        "unique_source_count": 1,
        "resolution": "720x1280",
    }

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "video_artifact_probe" in result["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_horizontal_video_resolution():
    packet = complete_kuaishou_auto_packet()
    packet["video_artifact_probe"]["resolution"] = "1280x720"

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "video_artifact_probe" in result["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_reused_bgm_fingerprint():
    packet = complete_kuaishou_auto_packet()
    packet["bgm_history_check"]["recent_fingerprints"].append("sha256:test-bgm")
    packet["bgm_history_check"]["duplicate_found"] = True

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "bgm_fingerprint_history" in result["failed_dimensions"]


def test_kuaishou_preflight_does_not_require_future_postcheck_steps():
    packet = complete_kuaishou_auto_packet()
    packet["workflow_evidence"]["completed_steps"] = ["strategy", "trend_analysis", "content_generation", "quality_gate"]

    preflight = validate_kuaishou_auto_packet(packet, phase="preflight")
    postcheck = validate_kuaishou_auto_packet(packet, phase="postcheck")

    assert preflight["passed"] is True
    assert postcheck["passed"] is False
    assert "workflow_steps" in postcheck["failed_dimensions"]


def test_kuaishou_auto_packet_rejects_invalid_card_sequence_without_crashing():
    packet = complete_kuaishou_auto_packet()
    packet["knowledge_card_sequence"] = ["not-a-card"] * 6

    result = validate_kuaishou_auto_packet(packet)

    assert result["passed"] is False
    assert "base_video_quality" in result["failed_dimensions"]
    assert "card_layout_diversity" in result["failed_dimensions"]


def test_shipinhao_auto_packet_requires_wechat_qr_ending_card():
    packet = complete_shipinhao_auto_packet()
    assert validate_shipinhao_auto_packet(packet)["passed"] is True
    packet["ending_card"].pop("wechat_qr_asset")

    result = validate_shipinhao_auto_packet(packet)

    assert result["passed"] is False
    assert "wechat_qr_ending_card" in result["failed_dimensions"]


def test_shipinhao_auto_packet_requires_ending_card_probe():
    packet = complete_shipinhao_auto_packet()
    packet["ending_card_probe"]["qr_detected"] = False

    result = validate_shipinhao_auto_packet(packet)

    assert result["passed"] is False
    assert "ending_card_visual_probe" in result["failed_dimensions"]


def test_shipinhao_auto_packet_rejects_reused_cross_platform_render():
    packet = complete_shipinhao_auto_packet()
    packet["platform_render_identity"]["output_path"] = "/tmp/current-run/kuaishou/final.mp4"
    packet["platform_render_identity"]["rendered_for_platform"] = "kuaishou"
    packet["platform_render_identity"]["not_reused_from_other_platform"] = False

    result = validate_shipinhao_auto_packet(packet)

    assert result["passed"] is False
    assert "platform_render_identity" in result["failed_dimensions"]


def test_shipinhao_auto_packet_requires_independent_media_delivery_message():
    packet = complete_shipinhao_auto_packet()
    packet["media_delivery"]["sent_as_separate_message"] = False
    packet["media_delivery"]["message_kind"] = "TEXT_WITH_MEDIA_TAIL"

    result = validate_shipinhao_auto_packet(packet)

    assert result["passed"] is False
    assert "media_delivery_contract" in result["failed_dimensions"]


def test_shipinhao_auto_packet_rejects_overlong_ending_title():
    packet = complete_shipinhao_auto_packet()
    packet["ending_card"]["title"] = "这个标题太长会让最后一张二维码卡片显得拥挤"
    packet["ending_card_probe"]["title_chars"] = len(packet["ending_card"]["title"])

    result = validate_shipinhao_auto_packet(packet)

    assert result["passed"] is False
    assert "ending_card_title" in result["failed_dimensions"]


def test_xiaohongshu_auto_packet_requires_mixed_assets_and_disclosure():
    packet = complete_xiaohongshu_auto_packet()
    assert validate_xiaohongshu_auto_packet(packet)["passed"] is True
    packet["source_assets"] = []
    packet["caption"] = "manual note without disclosure"
    packet["body"] = "manual note without disclosure " * 30

    result = validate_xiaohongshu_auto_packet(packet)

    assert result["passed"] is False
    assert "authentic_source_evidence" in result["failed_dimensions"]
    assert "ai_assisted_disclosure" in result["failed_dimensions"]


def test_xiaohongshu_auto_packet_rejects_design_cards_without_real_scene_backgrounds():
    packet = complete_xiaohongshu_auto_packet()
    packet["real_scene_background_plan"] = {
        "required": True,
        "source_policy": "licensed_or_verified_real_scene_assets",
        "primary_background_kind": "design_card",
        "no_css_gradient_primary": False,
        "per_slide_backgrounds": [
            {"asset_id": "card-only", "asset_type": "design_card", "source": "generated", "rights_cleared": True, "real_scene": False, "match_reason": "looks clean"}
        ],
    }

    result = validate_xiaohongshu_auto_packet(packet)

    assert result["passed"] is False
    assert "real_scene_backgrounds" in result["failed_dimensions"]


def test_xiaohongshu_auto_packet_rejects_invalid_source_asset_items():
    packet = complete_xiaohongshu_auto_packet()
    packet["source_assets"] = [
        "not-a-real-asset",
        {"asset_id": "xhs-real-1", "source": "licensed-source", "rights_cleared": True, "real_scene": True},
        {"asset_id": "xhs-real-2", "source": "licensed-source", "rights_cleared": True, "real_scene": True},
    ]

    result = validate_xiaohongshu_auto_packet(packet)

    assert result["passed"] is False
    assert "authentic_source_evidence" in result["failed_dimensions"]


def test_xiaohongshu_auto_packet_rejects_shared_trend_only_source_matrix():
    packet = complete_xiaohongshu_auto_packet()
    packet["platform_source_matrix"]["successful_source_count"] = 2
    packet["platform_source_matrix"]["platform_internal_verified"] = False
    packet["platform_source_matrix"]["shared_trend_only"] = True

    result = validate_xiaohongshu_auto_packet(packet)

    assert result["passed"] is False
    assert "platform_independent_source_matrix" in result["failed_dimensions"]


def test_platform_source_gate_rejects_fresh_platform_strategy_without_collection():
    matrix = {
        "platform": "twitter",
        "attempted_sources": [
            {"source": "hackernews", "status": "ok"},
            {"source": "zhihu", "status": "ok"},
            {"source": "bilibili", "status": "ok"},
            {"source": "wewrite_hotspots", "status": "ok"},
            {"source": "twitter:fresh_growth_strategy", "status": "ok"},
        ],
        "successful_source_count": 5,
        "platform_internal_verified": True,
        "current_platform_specific_topic": False,
        "platform_strategy_verified": True,
        "shared_trend_only": False,
        "report_path": "runtime:trend_snapshot",
    }

    assert _platform_source_matrix_gate(matrix, "twitter")["passed"] is False


def test_pre_onboarding_article_platforms_use_explicit_article_gate():
    packet = complete_wechat_auto_packet()
    for platform in ["toutiao", "juejin", "zhihu"]:
        manifest = complete_preflight_manifest(platform, "long_article")
        manifest["skills_loaded"].append("content/knowledge-card-designer")
        candidate = {
            **packet,
                **complete_full_ops_evidence(platform),
                "platform": platform,
                "preflight_manifest": manifest,
                "growth_strategy": complete_growth_strategy(platform, "long_article"),
                "safe_handoff_route": True,
                "platform_adaptation": {"required_fields_checked": True, "safe_handoff_route": True},
            }
        assert validate_platform_article_packet(candidate, platform)["passed"] is True
        candidate["body"] = "too short"
        result = validate_platform_article_packet(candidate, platform)
        assert result["passed"] is False
        assert "base_article_quality" in result["failed_dimensions"]


def test_article_packet_rejects_missing_strategy_and_bottom_stacked_images():
    packet = {
        "platform": "wechat",
        "visual_content_policy": visual_content_policy(["wechat"], "long_article"),
        "body": "practical operating paragraph " * 80,
        "opening_hook": "A useful article needs a real promise before it asks readers to spend attention.",
        "hook_type": "reader_payoff",
        "sections": ["problem", "case", "method", "proof", "checklist"],
        "visual_template_selection": {
            "selected": "case_story_v1",
            "ranked_scores": [{"template": "case_story_v1", "score": 80}],
            "recent_same_platform_templates": [],
            "penalties": {},
        },
        "section_image_map": [
            {"section": "problem", "image": "01.png", "purpose": "decorate the article"},
            {"section": "case", "image": "02.png", "purpose": "decorate the article"},
            {"section": "method", "image": "03.png", "purpose": "decorate the article"},
        ],
        "reader_payoff": "reader can apply a checklist today",
        "concrete_case": "failed scheduled publication diagnosis",
        "actionable_checklist": ["check title", "check cover", "check postcheck"],
    }
    result = validate_article_packet(packet)
    assert result["passed"] is False
    assert "strategy_brief" in result["failed_dimensions"]
    assert "section_images" in result["failed_dimensions"]
    assert "knowledge_card_plan" in result["failed_dimensions"]
    assert "article_recipe" in result["failed_dimensions"]
    assert "knowledge_card_recipe" in result["failed_dimensions"]
    assert "tool_invocation_manifest" in result["failed_dimensions"]
    assert "embedded_knowledge_cards" in result["failed_dimensions"]


def test_article_packet_rejects_invalid_section_image_mapping_item():
    packet = complete_wechat_auto_packet()
    packet["section_image_map"] = [
        "not-a-mapping",
        {"section": "problem", "image": "01.png", "purpose": "show pain", "adjacent_to_text": True},
        {"section": "method", "image": "02.png", "purpose": "show method", "adjacent_to_text": True},
    ]

    result = validate_article_packet(packet)

    assert result["passed"] is False
    assert "section_images" in result["failed_dimensions"]
    assert "section_real_scene_mapping" in result["failed_dimensions"]


def test_video_packet_rejects_silent_static_or_unverified_assets():
    packet = {
        "audio_probe": {"stream_count": 0, "duration": 0},
        "subtitle": {"cue_count": 0},
        "burned_captions": {"position": "middle", "burned_in": False},
        "visual_probe": {"occupied_frame_ratio": 0.4, "distinct_scene_count": 1, "unique_source_count": 1},
        "source_assets": [],
        "knowledge_card_sequence": [],
        "first_second_hook": "",
        "background_music_present": False,
        "scene_visual_alignment": [],
    }
    result = validate_video_packet(packet)
    assert result["passed"] is False
    assert set(result["failed_dimensions"]) == {
        "preflight_manifest",
        "visual_content_policy",
        "duration",
            "video_plan",
            "visual_recipe",
            "tool_selection",
            "tool_invocation_manifest",
        "audio_stream",
        "audio_composition",
        "background_music_source",
        "natural_voice",
        "subtitle_or_readable_cards",
        "lower_third_captions",
        "full_frame_visuals",
        "knowledge_card_sequence",
            "rights_cleared_source_assets",
            "real_scene_backgrounds",
            "hook",
        "first_three_seconds",
        "scene_visual_alignment",
            "scene_real_scene_mapping",
            "same_batch_differentiation",
            "platform_render_identity",
            "platform_adaptation",
            "growth_plan",
        }


def test_douyin_tiktok_repost_packet_rejects_generic_knowledge_conversion():
    packet = {
        "content_line": "tiktok_hot_localized_repost",
        "title": "猫咪日常",
        "script": "你有没有发现，猫咪摇尾巴其实是一种行为信号，这说明它很放松。",
    }
    failures = validate_douyin_tiktok_repost_packet(packet)
    assert "missing required TikTok repost field: source_url" in failures
    assert "generic Douyin title is not allowed for TikTok repost lane" in failures
    assert "TikTok repost script looks like cat knowledge explainer" in failures


def test_douyin_tiktok_repost_packet_requires_visual_review_when_caption_missing():
    packet = {
        "content_line": "tiktok_hot_localized_repost",
        "source_url": "https://www.tiktok.com/@cat/video/123",
        "video_id": "123",
        "keyword": "catsoftiktok",
        "trend_reason": "fresh cat trend",
        "source_caption_or_overlay": "TikTok #catsoftiktok candidate; caption unavailable",
        "source_evidence": [{"kind": "tag_page_anchor", "context": "#catsoftiktok", "pet_positive": True}],
        "source_decision_reason": "tag_anchor_pet_positive_video_caption_unstable",
        "source_entertainment_or_story_intent": "preserve the original TikTok pet entertainment beat",
        "localization_angle": "localize source story",
        "translation_rewrite_plan": "rewrite as human Chinese narration",
        "scene_to_script_mapping": [{"scene": "cat jumps", "line": "它突然跳起来"}],
        "visual_review": "pending",
    }
    failures = validate_douyin_tiktok_repost_packet(packet)
    assert "source caption unavailable requires passed visual review before content generation" in failures


def test_douyin_tiktok_repost_packet_requires_pet_positive_source_evidence():
    packet = {
        "content_line": "tiktok_hot_localized_repost",
        "source_url": "https://www.tiktok.com/@cat/video/123",
        "video_id": "123",
        "keyword": "catsoftiktok",
        "trend_reason": "fresh cat trend",
        "source_caption_or_overlay": "cat jumps at camera",
        "source_evidence": [{"kind": "video_page_caption", "caption": "unrelated routine", "pet_positive": False}],
        "source_decision_reason": "video_caption_non_pet_after_retries",
        "source_entertainment_or_story_intent": "preserve the original TikTok pet entertainment beat",
        "localization_angle": "localize source story",
        "translation_rewrite_plan": "rewrite as human Chinese narration",
        "scene_to_script_mapping": [{"scene": "cat jumps", "line": "它突然跳起来"}],
        "visual_review": "verified",
    }
    failures = validate_douyin_tiktok_repost_packet(packet, require_visual_review=True)
    assert "source_evidence must include at least one pet-positive evidence item" in failures


def test_video_packet_accepts_complete_narrated_real_footage_cut():
    packet = {
        **complete_video_metadata(),
        "audio_probe": {"stream_count": 1, "duration": 52},
        "subtitle": {"cue_count": 10},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": 16,
            "max_lines": 2,
        },
        "visual_probe": {"occupied_frame_ratio": 0.94, "distinct_scene_count": 8, "unique_source_count": 4},
        "knowledge_card_sequence": complete_knowledge_cards("video"),
        "source_assets": [
            {"rights_cleared": True, "behavior_match": True},
            {"rights_cleared": True, "behavior_match": True},
            {"rights_cleared": True, "behavior_match": True},
            {"rights_cleared": True, "behavior_match": True},
        ],
        "first_second_hook": "This first shot proves the behavior before the narration explains it.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {
            "provider": "edge_tts_segmented_natural",
            "segment_count": 8,
            "pause_plan": [0.42, 0.35, 0.5, 0.3],
            "emotion_cues": ["hook", "explain", "resolve"],
            "human_pacing": True,
        },
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"clip-{i}.mp4", "match_reason": "matches the narrated behavior"}
            for i in range(8)
        ],
    }
    assert validate_video_packet(packet)["passed"] is True


def test_video_packet_requires_real_scene_background_for_every_scene():
    packet = {
        **complete_video_metadata(),
        "audio_probe": {"stream_count": 1, "duration": 52},
        "subtitle": {"cue_count": 10},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": 16,
            "max_lines": 2,
        },
        "visual_probe": {"occupied_frame_ratio": 0.94, "distinct_scene_count": 8, "unique_source_count": 4},
        "knowledge_card_sequence": complete_knowledge_cards("video"),
        "source_assets": [
            {"rights_cleared": True, "behavior_match": True, "real_scene": True, "source": f"https://licensed.example/clip-{i}.mp4"}
            for i in range(4)
        ],
        "real_scene_background_plan": complete_real_scene_background_plan(4),
        "first_second_hook": "This first shot proves the behavior before the narration explains it.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {
            "provider": "edge_tts_segmented_natural",
            "segment_count": 8,
            "pause_plan": [0.42, 0.35, 0.5, 0.3],
            "emotion_cues": ["hook", "explain", "resolve"],
            "human_pacing": True,
        },
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"clip-{i}.mp4", "match_reason": "matches the narrated behavior"}
            for i in range(8)
        ],
    }

    result = validate_video_packet(packet)

    assert result["passed"] is False
    assert "real_scene_backgrounds" in result["failed_dimensions"]


def test_video_packet_rejects_invalid_scene_mapping_item():
    packet = {
        **complete_video_metadata(),
        "audio_probe": {"stream_count": 1, "duration": 52},
        "subtitle": {"cue_count": 10},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": 16,
            "max_lines": 2,
        },
        "visual_probe": {"occupied_frame_ratio": 0.94, "distinct_scene_count": 8, "unique_source_count": 4},
        "knowledge_card_sequence": complete_knowledge_cards("video"),
        "source_assets": [
            {"rights_cleared": True, "behavior_match": True, "real_scene": True, "source": f"https://licensed.example/clip-{i}.mp4"}
            for i in range(4)
        ],
        "real_scene_background_plan": complete_real_scene_background_plan(8),
        "first_second_hook": "This first shot proves the behavior before the narration explains it.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {
            "provider": "edge_tts_segmented_natural",
            "segment_count": 8,
            "pause_plan": [0.42, 0.35, 0.5, 0.3],
            "emotion_cues": ["hook", "explain", "resolve"],
            "human_pacing": True,
        },
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"clip-{i}.mp4", "match_reason": "matches the narrated behavior"}
            for i in range(7)
        ]
        + ["not-a-scene"],
    }

    result = validate_video_packet(packet)

    assert result["passed"] is False
    assert "scene_visual_alignment" in result["failed_dimensions"]
    assert "scene_real_scene_mapping" in result["failed_dimensions"]


def test_article_packet_rejects_missing_unified_visual_policy():
    packet = {
        "platform": "wechat",
        "body": "practical operating paragraph " * 80,
        "opening_hook": "A useful article needs a real promise before it asks readers to spend attention.",
        "hook_type": "reader_payoff",
        "sections": ["problem", "case", "why old way fails", "method", "checklist"],
        "visual_template_selection": {
            "selected": "case_story_v1",
            "ranked_scores": [{"template": "case_story_v1", "score": 80}],
            "recent_same_platform_templates": [],
            "penalties": {},
        },
        "strategy_brief": {
            "target_user": "operators",
            "channel_lane": "AI operations",
            "topic_basis": "recent delivery failures",
            "click_reason": "avoid repeating a costly publishing mistake",
            "reader_payoff": "a checklist they can reuse",
            "chosen_structure": "case-breakdown-method",
            "content_form": "longform article",
        },
        "section_image_map": [
            {"section": "problem", "image": "01.png", "purpose": "open the pain point", "adjacent_to_text": True},
            {"section": "case", "image": "02.png", "purpose": "show the specific case", "adjacent_to_text": True},
            {"section": "method", "image": "03.png", "purpose": "explain the steps", "adjacent_to_text": True},
        ],
        "knowledge_card_plan": complete_knowledge_card_plan("wechat"),
        "embedded_knowledge_cards": complete_knowledge_cards("article"),
        "cover_design": {
            "visual_subject": "failed schedule checklist",
            "topic_alignment": "matches the article promise",
            "mobile_readable": True,
            "visual_hierarchy": "title, warning mark, checklist",
            "template_family": "casebook",
        },
        "differentiation_dimensions": ["case-led opening", "checklist structure", "warm warning tone"],
        "reader_payoff": "reader can apply a checklist today",
        "concrete_case": "failed scheduled publication diagnosis",
        "actionable_checklist": ["check title", "check cover", "check postcheck"],
    }
    result = validate_article_packet(packet)
    assert result["passed"] is False
    assert "visual_content_policy" in result["failed_dimensions"]


def test_knowledge_image_video_can_use_readable_cards_without_subtitles():
    packet = {
        **complete_video_metadata(),
        "content_form": "knowledge_image_video",
        "audio_probe": {"stream_count": 1, "duration": 48},
        "subtitle": {"cue_count": 0},
        "burned_captions": {"position": "", "burned_in": False},
        "visual_probe": {
            "occupied_frame_ratio": 0.94,
            "distinct_scene_count": 8,
            "unique_source_count": 4,
            "readable_on_card_text": True,
            "card_text_min_font_size": 54,
        },
        "knowledge_card_sequence": complete_knowledge_cards("image-video"),
        "source_assets": [{"rights_cleared": True, "behavior_match": True} for _ in range(4)],
        "first_second_hook": "The first card states the useful promise immediately.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {
            "provider": "edge_tts_segmented_natural",
            "segment_count": 8,
            "pause_plan": [0.42, 0.35, 0.5, 0.3],
            "emotion_cues": ["hook", "explain", "resolve"],
            "human_pacing": True,
        },
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"card-{i}.png", "match_reason": "card explains the beat"}
            for i in range(8)
        ],
    }
    assert validate_video_packet(packet)["passed"] is True


def test_video_packet_allows_over_100_seconds_only_with_strategy_reason():
    packet = {
        **complete_video_metadata(),
        "audio_probe": {"stream_count": 1, "duration": 112},
        "subtitle": {"cue_count": 14},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": 16,
            "max_lines": 2,
        },
        "visual_probe": {"occupied_frame_ratio": 0.94, "distinct_scene_count": 8, "unique_source_count": 4},
        "knowledge_card_sequence": complete_knowledge_cards("long-video"),
        "source_assets": [{"rights_cleared": True, "behavior_match": True} for _ in range(4)],
        "first_second_hook": "The longer runtime is justified by the tutorial structure.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {
            "provider": "edge_tts_segmented_natural",
            "segment_count": 8,
            "pause_plan": [0.42, 0.35, 0.5, 0.3],
            "emotion_cues": ["hook", "explain", "resolve"],
            "human_pacing": True,
        },
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"clip-{i}.mp4", "match_reason": "matches the narrated step"}
            for i in range(8)
        ],
    }
    assert validate_video_packet(packet)["passed"] is False
    packet["duration_strategy_reason"] = "tutorial format needs eight explained steps for Kuaishou retention"
    assert validate_video_packet(packet)["passed"] is True


def test_video_packet_rejects_robotic_single_take_voiceover():
    packet = {
        **complete_video_metadata(),
        "audio_probe": {"stream_count": 1, "duration": 55},
        "subtitle": {"cue_count": 10},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": 16,
            "max_lines": 2,
        },
        "visual_probe": {"occupied_frame_ratio": 0.94, "distinct_scene_count": 8, "unique_source_count": 4},
        "knowledge_card_sequence": complete_knowledge_cards("robotic"),
        "source_assets": [{"rights_cleared": True, "behavior_match": True} for _ in range(4)],
        "first_second_hook": "The first shot proves the behavior before the narration explains it.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {"provider": "edge_tts", "segment_count": 1, "pause_plan": [], "human_pacing": False},
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"clip-{i}.mp4", "match_reason": "matches the narrated behavior"}
            for i in range(8)
        ],
    }
    result = validate_video_packet(packet)
    assert result["passed"] is False
    assert "natural_voice" in result["failed_dimensions"]


def test_kuaishou_packet_rejects_hashtag_limit_violation():
    packet = {
        **complete_video_metadata(platform="kuaishou"),
        "audio_probe": {"stream_count": 1, "duration": 55},
        "subtitle": {"cue_count": 10},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": 16,
            "max_lines": 2,
        },
        "visual_probe": {"occupied_frame_ratio": 0.94, "distinct_scene_count": 8, "unique_source_count": 4},
        "knowledge_card_sequence": complete_knowledge_cards("kuaishou"),
        "source_assets": [{"rights_cleared": True, "behavior_match": True} for _ in range(4)],
        "first_second_hook": "The first shot proves the behavior before the narration explains it.",
        "voiceover_present": True,
        "background_music_present": True,
        "voice_style": {
            "provider": "edge_tts_segmented_natural",
            "segment_count": 8,
            "pause_plan": [0.42, 0.35, 0.5, 0.3],
            "emotion_cues": ["hook", "explain", "resolve"],
            "human_pacing": True,
        },
        "scene_visual_alignment": [
            {"script_beat": f"beat {i}", "visual_asset": f"clip-{i}.mp4", "match_reason": "matches the narrated behavior"}
            for i in range(8)
        ],
    }
    packet["platform_adaptation"] = {
        "required_fields_checked": True,
        "topic_tag_count": 4,
        "description_hashtag_count": 3,
    }
    result = validate_video_packet(packet)
    assert result["passed"] is False
    assert "platform_adaptation" in result["failed_dimensions"]


def test_delivery_result_cannot_treat_local_preparation_as_platform_delivery():
    prepared = {"status": "staged", "remote_submitted": False, "postcheck": {}}
    assert validate_delivery_result(prepared)["passed"] is False

    delivered = {
        "status": "drafted",
        "remote_submitted": True,
        "postcheck": {"passed": True, "evidence_path": ".codex-server-runtime/private/evidence.png"},
    }
    assert validate_delivery_result(delivered)["passed"] is True
