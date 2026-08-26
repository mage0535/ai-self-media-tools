"""Cross-platform validation for config/channel_content_rulebook.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RULEBOOK_PATH = ROOT / "config" / "channel_content_rulebook.json"
GROWTH_POLICY_PATH = ROOT / "config" / "growth_quality_policy.json"
OPERATIONS_POLICY_PATH = ROOT / "config" / "operations_policy_facts.json"
OPERATIONS_CONTRACT_PATH = ROOT / "docs" / "OPERATIONS_POLICY_CONTRACT.md"

REQUIRED_SEQUENCE = {
    "load_channel_rulebook",
    "load_hermes_operating_strategy",
    "check_account_lane_fit",
    "generate_channel_specific_strategy_brief",
    "analyze_available_tools_and_select_content_stack",
    "run_quality_gate",
    "run_delivery_health_gate",
    "postcheck_platform_state",
    "write_metrics_review_row",
}

CORE_REQUIRED_CHANNELS = [
    "douyin",
    "kuaishou",
    "shipinhao",
    "wechat",
    "xiaohongshu",
    "juejin",
    "zhihu",
    "bilibili",
    "tiktok",
    "youtube",
    "twitter",
]

REQUIRED_CHANNEL_FIELDS = {"lane", "primary_types", "publish_policy", "must_use_tools", "quality_gates", "postcheck"}
FULL_OPS_CHANNELS = ["xiaohongshu", "juejin", "zhihu"]
FULL_OPS_REQUIRED_TOOLS = {
    "hermes_operating_strategy",
    "account_data_analysis",
    "same_lane_account_analysis",
    "bilibili_hot_analysis",
    "wechat_hot_article_analysis",
    "xiaohongshu_hot_note_analysis",
    "youtube_topic_analysis",
    "external_hot_trend_analysis",
}
FULL_OPS_REQUIRED_INPUTS = {
    "account_analysis",
    "same_lane_account_analysis",
    "cross_platform_trend_analysis",
    "topic_selection",
    "quantity_plan",
    "content_brief",
}
FULL_OPS_REQUIRED_SOURCES = {
    "account_history",
    "same_lane_accounts",
    "bilibili",
    "wechat",
    "xiaohongshu",
    "youtube",
    "external_hot_platforms",
}
FULL_OPS_CONTENT_HANDOFF = {
    "selected_topic",
    "quantity_plan",
    "copy_plan",
    "script_plan",
    "seo_geo_plan",
    "topic_tags",
    "asset_mix_plan",
    "humanization_plan",
}
FULL_OPS_GATES = {
    "full_ops_workflow",
    "account_data_analysis",
    "same_lane_account_benchmark",
    "cross_platform_hot_trend_analysis",
    "topic_quantity_decision",
    "content_workflow_inputs",
    "asset_mix_plan",
    "humanization_plan",
}
GROWTH_CHANNELS = {"douyin", "kuaishou", "wechat", "bilibili", "shipinhao", "xiaohongshu", "zhihu", "juejin", "youtube", "tiktok", "twitter"}
GROWTH_REQUIRED_FIELDS = {
    "account_performance_snapshot_or_unavailable_reason",
    "same_lane_hot_content_analysis",
    "target_user_action",
    "hook_plan",
    "retention_plan",
    "interaction_plan",
    "packaging_plan",
    "post_publish_review_plan",
    "data_driven_improvement_plan",
}
GROWTH_METRICS_V2 = {
    "views",
    "likes",
    "comments",
    "shares",
    "saves",
    "clicks",
    "impressions",
    "completion_rate",
    "avg_watch_seconds",
    "three_second_view_rate",
    "follows",
    "platform_specific_metrics",
}
DOUYIN_ACCOUNT_KEYS = {"douyin_pet", "douyin_ai"}
DOUYIN_ACCOUNT_ISOLATION_FIELDS = {
    "cookie_state_profile",
    "historical_feedback",
    "performance_metrics",
    "growth_strategy",
    "platform_source_matrix",
    "tools_capability_analysis",
    "tool_selection_plan",
    "visual_recipe",
    "tool_invocation_manifest",
    "handoff_package",
    "output_dir",
}
DOUYIN_FORBIDDEN_REUSE_MARKERS = {"final.mp4", "template", "bgm", "title", "script", "source_material"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def operations_policy_audit() -> dict:
    from scripts.audit_strategy_skill_conflicts import audit

    return audit(OPERATIONS_POLICY_PATH, [OPERATIONS_CONTRACT_PATH])


def main() -> None:
    rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))
    sequence = set(rulebook.get("mandatory_sequence") or [])
    for step in REQUIRED_SEQUENCE:
        require(step in sequence, f"missing mandatory sequence step: {step}")

    channel_rules = rulebook.get("channel_rules") or {}
    for channel in CORE_REQUIRED_CHANNELS:
        require(channel in channel_rules, f"missing channel rule: {channel}")
    for channel in channel_rules:
        missing = REQUIRED_CHANNEL_FIELDS - set(channel_rules[channel])
        require(not missing, f"missing field for {channel}: {sorted(missing)}")

    hard_gates = rulebook.get("global_hard_gates") or {}
    require(hard_gates.get("metrics_review_required") is True, "metrics review must be required")
    require(hard_gates.get("proxy_required_for_hermes_channel_access") is False, "domestic channel access must be direct-first")
    require(hard_gates.get("anti_platform_spam_similarity") is True, "anti platform spam similarity gate must be required")
    anti_spam = rulebook.get("anti_spam_similarity_policy") or {}
    require(anti_spam.get("policy_id") == "anti_spam_similarity_v1", "anti spam similarity policy id mismatch")
    require((anti_spam.get("lookback_days_default") or 0) >= 14, "anti spam similarity lookback must be >=14 days")
    anti_spam_rules = " ".join(anti_spam.get("rules") or [])
    for marker in ["near_duplicate", "short_form_promotions", "platform_limits_visibility"]:
        require(marker in anti_spam_rules, f"anti spam similarity policy missing marker: {marker}")

    require(GROWTH_POLICY_PATH.is_file(), "growth quality policy config is missing")
    growth_policy = rulebook.get("growth_quality_policy") or {}
    require(growth_policy.get("policy_id") == "growth_quality_policy_v1", "growth policy id mismatch")
    require(GROWTH_CHANNELS.issubset(set(growth_policy.get("applies_to") or [])), "growth policy does not cover all real-use channels")
    missing_growth_fields = GROWTH_REQUIRED_FIELDS - set(growth_policy.get("required_before_generation") or [])
    require(not missing_growth_fields, f"growth policy required fields missing: {sorted(missing_growth_fields)}")
    missing_growth_metrics = GROWTH_METRICS_V2 - set(growth_policy.get("post_publish_metrics_v2") or [])
    require(not missing_growth_metrics, f"growth policy metrics missing: {sorted(missing_growth_metrics)}")
    growth_config = json.loads(GROWTH_POLICY_PATH.read_text(encoding="utf-8"))
    require(growth_config.get("policy_id") == "growth_quality_policy_v1", "growth quality config policy id mismatch")
    require(GROWTH_CHANNELS.issubset(set(growth_config.get("applies_to") or [])), "growth quality config must cover real-use channels")

    proxy_policy = rulebook.get("proxy_policy") or {}
    for field in ["domestic_proxy_env", "international_proxy_env", "domestic_channels", "international_channels", "rules"]:
        require(field in proxy_policy, f"missing proxy_policy field: {field}")
    require(proxy_policy["domestic_proxy_env"] == "CN_PROXY", "domestic channels must use CN_PROXY")
    require(proxy_policy["international_proxy_env"] == "US_PROXY", "international channels must use US_PROXY")
    require(proxy_policy.get("domestic_route_order") == ["direct", "CN_PROXY"], "domestic route order must be direct then CN_PROXY")
    require(proxy_policy.get("international_route_order") == ["direct", "US_PROXY"], "international route order must be direct then US_PROXY")

    domestic = set(proxy_policy.get("domestic_channels") or [])
    international = set(proxy_policy.get("international_channels") or [])
    overlap = domestic & international
    require(not overlap, f"channel appears in both proxy policies: {sorted(overlap)}")
    covered = domestic | international
    for channel in channel_rules:
        require(channel in covered, f"channel missing from proxy policy: {channel}")

    shipinhao = channel_rules["shipinhao"]
    shipinhao_postcheck = shipinhao.get("postcheck_contract") or {}
    require(shipinhao_postcheck.get("tool") == "scripts/shipinhao_postcheck.py", "shipinhao postcheck tool must be documented")
    shipinhao_routes = " ".join(shipinhao_postcheck.get("primary_routes") or [])
    require("all_video_post_list" in shipinhao_routes, "shipinhao postcheck must include the all-video management route")
    shipinhao_status = shipinhao_postcheck.get("status_mapping") or {}
    require(
        shipinhao_status.get("user_confirmed_backend_submission_success_but_management_list_not_yet_synced") == "handoff_pending",
        "shipinhao user-verified submission without list sync must remain handoff_pending",
    )
    require(
        "duplicate" in str(shipinhao_postcheck.get("anti_duplicate_rule", "")),
        "shipinhao postcheck must block duplicate reupload after submit evidence",
    )
    shipinhao_gates = set(shipinhao.get("quality_gates") or [])
    for gate in ["wechat_qr_ending_card", "ending_card_title_16_chars_or_less", "ending_card_visual_probe"]:
        require(gate in shipinhao_gates, f"shipinhao quality gate missing: {gate}")
    ending_card = shipinhao.get("ending_card_requirements") or {}
    require(ending_card.get("required") is True, "shipinhao ending card requirements must be required")
    require((ending_card.get("title_max_chars") or 0) <= 16, "shipinhao ending card title limit must be <=16 chars")
    for field in ["wechat_official_account_qr", "wechat_ecosystem_cta", "safe_area_qr_position", "ending_card_probe"]:
        require(field in (ending_card.get("must_include") or []), f"shipinhao ending card must_include missing: {field}")
    for field in ["frame_path", "qr_detected", "qr_visible", "qr_contrast_ok", "safe_area_ok", "overlay_opacity_max <= 0.65"]:
        require(field in (ending_card.get("visual_probe_required") or []), f"shipinhao ending card visual probe missing: {field}")

    wechat = channel_rules["wechat"]
    wechat_tools = set(wechat.get("must_use_tools") or [])
    for tool in [
        "wechat_account_data_analysis",
        "wechat_same_lane_account_analysis",
        "github_trending_collector",
        "wechat_and_external_hot_trend_analysis",
        "image_text_card_recipe",
        "scripts/validate_image_text_card_recipe.py",
        "scripts/validate_wechat_auto_packet.py",
        "scripts/validate_wechat_image_post_packet.py",
        "draft_batchget_postcheck",
    ]:
        require(tool in wechat_tools, f"wechat must_use_tools missing: {tool}")
    require((ROOT / "scripts" / "validate_wechat_auto_packet.py").is_file(), "wechat validator script is missing")
    require((ROOT / "scripts" / "validate_wechat_image_post_packet.py").is_file(), "wechat image-post validator script is missing")
    require((ROOT / "scripts" / "validate_image_text_card_recipe.py").is_file(), "image text card recipe validator script is missing")
    require((ROOT / "config" / "image_text_card_modules.json").is_file(), "image text card module registry is missing")
    for gate in ["wechat_image_post_cards_required", "image_text_card_recipe_required", "image_text_card_recipe_cli_gate", "wechat_image_post_real_scene_backgrounds", "wechat_image_post_layout_diversity"]:
        require(gate in (wechat.get("quality_gates") or []), f"wechat quality gate missing: {gate}")
    wechat_channels = wechat.get("content_channels") or {}
    require(
        wechat_channels.get("github_selection") == "weekly_bundle_one_ai_project_plus_one_non_ai_project",
        "wechat github_selection must require a weekly AI + non-AI GitHub project bundle",
    )
    require(wechat_channels.get("hot_content_generation"), "wechat hot_content_generation channel is required")
    growth_strategy = wechat.get("growth_optimization_strategy") or {}
    frequency = growth_strategy.get("publishing_frequency") or {}
    recovery_policy = growth_strategy.get("recovery_topic_policy") or {}
    require(growth_strategy.get("mode") == "wechat_14_day_recovery", "wechat must be in 14-day recovery mode")
    require(str(frequency.get("recommended_articles_per_week") or "") == "3", "wechat recovery frequency must be 3 articles/week")
    require((frequency.get("max_articles_per_week_recovery") or 99) <= 3, "wechat recovery weekly cap must be <=3")
    require((frequency.get("min_gap_hours_between_articles") or 0) >= 48, "wechat recovery articles must be separated by at least 48 hours")
    require(frequency.get("max_articles_per_day") == 1, "wechat max articles per day must be 1")
    require(frequency.get("avoid_daily_updates") is True, "wechat must forbid daily updates during recovery")
    require(frequency.get("avoid_three_articles_per_day_batching") is True, "wechat must forbid three-article daily batching")
    require((recovery_policy.get("topic_dedup_window_days") or 0) >= 14, "wechat topic dedup window must be >=14 days")
    require((recovery_policy.get("max_fatigue_terms_per_title") or 99) <= 1, "wechat title fatigue terms must be capped at 1")
    require(len(growth_strategy.get("columns") or []) >= 4, "wechat growth strategy must define four columns")
    title_rules = growth_strategy.get("title_rules") or {}
    require((title_rules.get("max_chars") or 99) <= 24, "wechat title max chars must be <=24 during recovery")
    require((title_rules.get("keyword_first_chars") or 99) <= 15, "wechat title keyword must appear in first 15 chars")
    article_structure = growth_strategy.get("article_structure") or {}
    require((article_structure.get("retention_hook_interval_chars") or 999) <= 350, "wechat retention hook interval must be <=350 chars")
    require((growth_strategy.get("interaction_conversion") or {}).get("backend_reply_keywords"), "wechat backend reply keywords are required")
    require((growth_strategy.get("seo_geo") or {}).get("primary_keywords"), "wechat SEO/GEO keywords are required")
    wechat_strategy = wechat.get("strategy_requirements") or {}
    for field in ["account_analysis", "same_lane_account_analysis", "cross_platform_trend_analysis", "topic_selection"]:
        require(field in (wechat_strategy.get("required_inputs_before_content_generation") or []), f"wechat strategy input missing: {field}")
    for field in ["github_ai_projects", "github_non_ai_projects", "weekly_bundle_reason_or_ops_override"]:
        require(field in (wechat_strategy.get("github_selection_required") or []), f"wechat github selection field missing: {field}")
    for field in [
        "growth_optimization_strategy",
        "content_mix_plan",
        "column_plan",
        "frequency_plan",
        "title_seo_plan",
        "interaction_conversion_plan",
        "post_publish_metric_plan",
    ]:
        require(field in (wechat_strategy.get("content_workflow_must_receive") or []), f"wechat content workflow handoff missing: {field}")
    for gate in [
        "account_data_analysis",
        "same_lane_account_benchmark",
        "cross_platform_trend_analysis",
        "content_workflow_inputs",
        "dual_content_channels",
        "wechat_editorial_frequency_control",
        "wechat_column_mix_plan",
        "wechat_title_fatigue_gate",
        "wechat_first_200_chars_payoff",
        "wechat_retention_hook_every_350_chars",
        "wechat_comment_backend_reply_cta",
        "wechat_search_seo_layout",
        "wechat_manual_data_review_plan",
    ]:
        require(gate in (wechat.get("quality_gates") or []), f"wechat quality gate missing: {gate}")

    kuaishou = channel_rules["kuaishou"]
    kuaishou_tools = set(kuaishou.get("must_use_tools") or [])
    for tool in ["hermes_operating_strategy", "same_lane_hot_video_analysis", "cross_pipeline_v5", "scripts/validate_kuaishou_auto_packet.py", "scripts/kuaishou_postcheck_manifest.py", "sau_kuaishou_uploader", "management_page_postcheck"]:
        require(tool in kuaishou_tools, f"kuaishou must_use_tools missing: {tool}")
    require((ROOT / "scripts" / "validate_kuaishou_auto_packet.py").is_file(), "kuaishou validator script is missing")
    require((ROOT / "scripts" / "kuaishou_postcheck_manifest.py").is_file(), "kuaishou postcheck script is missing")
    for gate in ["strategy_before_generation", "kuaishou_trend_evidence", "six_distinct_knowledge_card_layouts", "no_local_soundhelix_or_synthetic_bgm_without_explicit_exception"]:
        require(gate in (kuaishou.get("quality_gates") or []), f"kuaishou quality gate missing: {gate}")
    require(kuaishou.get("postcheck") == "kuaishou_management_pending_list_with_exact_schedule_time", "kuaishou postcheck must require exact schedule management-page evidence")

    bilibili = channel_rules["bilibili"]
    require(bilibili.get("publish_policy") == "manual_handoff_only_generate_video_package_user_manual_publish", "bilibili must be manual-handoff only")
    for gate in ["manual_handoff_only", "platform_render_identity", "media_delivery_contract", "unique_render_not_cross_platform_reuse"]:
        require(gate in (bilibili.get("quality_gates") or []), f"bilibili quality gate missing: {gate}")
    require(bilibili.get("postcheck") == "local_review_package_ready_user_manual_publish", "bilibili postcheck must be local review package")

    for platform in ["youtube", "tiktok"]:
        rule = channel_rules[platform]
        require(rule.get("publish_policy") == "manual_handoff_only_generate_video_package_no_aitoearn", f"{platform} must be manual handoff and no AiToEarn")
        for gate in ["manual_handoff_only", "platform_render_identity", "media_delivery_contract", "unique_render_not_cross_platform_reuse", "anti_spam_similarity_plan"]:
            require(gate in (rule.get("quality_gates") or []), f"{platform} quality gate missing: {gate}")
        handoff = rule.get("handoff_policy") or {}
        require(handoff.get("status") == "handoff_pending_only", f"{platform} handoff status must remain handoff_pending_only")
        forbidden = " ".join(handoff.get("forbidden") or [])
        require("automatic_upload" in forbidden and "cross_platform_final_mp4_reuse" in forbidden, f"{platform} handoff forbidden list incomplete")

    twitter = channel_rules["twitter"]
    twitter_short = twitter.get("short_form_policy") or {}
    require((twitter_short.get("max_posts_per_run") or 0) <= 1, "twitter must cap posts per run at 1")
    require((twitter_short.get("min_gap_hours_between_similar_posts") or 0) >= 24, "twitter similar post gap must be >=24 hours")
    for gate in ["anti_spam_similarity_plan", "no_repeated_hook_or_link_dump", "specific_reply_prompt"]:
        require(gate in (twitter.get("quality_gates") or []), f"twitter quality gate missing: {gate}")

    for channel in FULL_OPS_CHANNELS:
        rule = channel_rules[channel]
        tools = set(rule.get("must_use_tools") or [])
        missing_tools = FULL_OPS_REQUIRED_TOOLS - tools
        require(not missing_tools, f"{channel} full ops tools missing: {sorted(missing_tools)}")
        strategy = rule.get("strategy_requirements") or {}
        missing_inputs = FULL_OPS_REQUIRED_INPUTS - set(strategy.get("required_inputs_before_content_generation") or [])
        require(not missing_inputs, f"{channel} full ops inputs missing: {sorted(missing_inputs)}")
        missing_sources = FULL_OPS_REQUIRED_SOURCES - set(strategy.get("cross_platform_sources_required") or [])
        require(not missing_sources, f"{channel} cross-platform sources missing: {sorted(missing_sources)}")
        missing_handoff = FULL_OPS_CONTENT_HANDOFF - set(strategy.get("content_workflow_must_receive") or [])
        require(not missing_handoff, f"{channel} content workflow handoff missing: {sorted(missing_handoff)}")
        missing_gates = FULL_OPS_GATES - set(rule.get("quality_gates") or [])
        require(not missing_gates, f"{channel} full ops quality gates missing: {sorted(missing_gates)}")

    zhihu = channel_rules["zhihu"]
    zhihu_short = zhihu.get("short_form_policy") or {}
    require(zhihu.get("visibility_risk_status", {}).get("recovery_mode") == "zhihu_similarity_recovery", "zhihu similarity recovery mode must be recorded")
    require(zhihu_short.get("pin_publish_default") == "review_only_unless_validation_passes_and_visible_article_url_exists", "zhihu pin publish default must be review-gated")
    require(float(zhihu_short.get("max_pin_article_overlap") or 1) <= 0.22, "zhihu pin article overlap threshold too loose")
    require(float(zhihu_short.get("max_pin_title_overlap") or 1) <= 0.55, "zhihu pin title overlap threshold too loose")
    require(zhihu_short.get("one_pin_per_article") is True, "zhihu one_pin_per_article must be true")
    require((zhihu_short.get("min_gap_hours_between_pins") or 0) >= 48, "zhihu pin gap must be >=48 hours")
    for field in ["new_commentary_angle", "specific_discussion_question", "visible_article_url_when_publishing", "anti_spam_similarity_validation"]:
        require(field in (zhihu_short.get("must_include") or []), f"zhihu short-form policy missing must_include: {field}")
    for gate in ["zhihu_pin_anti_spam_similarity", "answer_article_pin_differentiation", "no_article_excerpt_as_pin"]:
        require(gate in (zhihu.get("quality_gates") or []), f"zhihu quality gate missing: {gate}")
    for tool in ["scripts/zhihu_pin_promotion.py", "content_platform.zhihu_promotion.validate_pin_payload"]:
        require(tool in (zhihu.get("must_use_tools") or []), f"zhihu must_use_tools missing: {tool}")

    douyin = channel_rules["douyin"]
    weekly = douyin.get("weekly_mix") or {}
    require(weekly.get("cat_knowledge_or_original") == 3, "douyin weekly_mix.cat_knowledge_or_original must be 3")  # 08-16 每日版
    require(weekly.get("tiktok_hot_localized_reposts") == 4, "douyin weekly_mix.tiktok_hot_localized_reposts must be 4")  # 08-16 每日版
    account_variants = (rulebook.get("platform_account_variants") or {}).get("douyin") or {}
    require(account_variants.get("base_platform") == "douyin", "douyin account variants must declare base_platform=douyin")
    require(account_variants.get("required") is True, "douyin account variants must be required")
    require(set(account_variants.get("execution_order") or []) == DOUYIN_ACCOUNT_KEYS, "douyin execution_order must contain douyin_pet and douyin_ai")
    missing_isolation = DOUYIN_ACCOUNT_ISOLATION_FIELDS - set(account_variants.get("isolation_required") or [])
    require(not missing_isolation, f"douyin account isolation fields missing: {sorted(missing_isolation)}")
    reuse_text = " ".join(account_variants.get("forbidden_cross_account_reuse") or [])
    for marker in DOUYIN_FORBIDDEN_REUSE_MARKERS:
        require(marker in reuse_text, f"douyin cross-account reuse marker missing: {marker}")
    require(account_variants.get("blocked_status") == "douyin_account_binding_missing", "douyin account binding missing status mismatch")
    douyin_accounts = account_variants.get("accounts") or {}
    require(set(douyin_accounts) == DOUYIN_ACCOUNT_KEYS, "douyin account variants must define douyin_pet and douyin_ai accounts")
    pet_account = douyin_accounts["douyin_pet"]
    ai_account = douyin_accounts["douyin_ai"]
    for key, account in douyin_accounts.items():
        require(account.get("base_platform") == "douyin", f"{key} base_platform must be douyin")
        require(account.get("account_key") == key, f"{key} account_key mismatch")
        require(account.get("cookie_account") == key, f"{key} cookie_account must match account_key")
        require(account.get("profile") == key, f"{key} profile must match account_key")
        require(account.get("growth_strategy_key") == f"growth_strategy:{key}:latest", f"{key} growth strategy key mismatch")
        require(account.get("publish_boundary") == "manual_handoff_only", f"{key} must be manual handoff only")
        require(key in str(account.get("output_dir_pattern", "")), f"{key} output directory must include account key")
    require(pet_account.get("lane") == "pet_healing", "douyin_pet lane must be pet_healing")
    require(ai_account.get("lane") == "ai_efficiency_open_source", "douyin_ai lane must be ai_efficiency_open_source")
    pet_weekly = pet_account.get("weekly_mix") or {}
    require(pet_weekly.get("cat_knowledge_or_original") == 3, "douyin_pet weekly cat knowledge quota must be 3")  # 08-16 每日版
    require(pet_weekly.get("tiktok_hot_localized_reposts") == 4, "douyin_pet weekly TikTok repost quota must be 4")  # 08-16 每日版
    require("tiktok_hot_localized_repost" in (pet_account.get("required_content_lines") or []), "douyin_pet must include TikTok localized repost line")
    require("ai_tool_microcase" in (ai_account.get("required_content_lines") or []), "douyin_ai must include AI tool microcase line")
    require("cat_knowledge_or_original" in (ai_account.get("forbidden_content_lines") or []), "douyin_ai must forbid cat knowledge line")
    require("douyin_ai" in (pet_account.get("must_not_use_rules_from") or []), "douyin_pet must not use douyin_ai rules")
    require("douyin_pet" in (ai_account.get("must_not_use_rules_from") or []), "douyin_ai must not use douyin_pet rules")
    tiktok_repost = douyin.get("tiktok_repost_strategy_required") or {}
    require(tiktok_repost.get("strategy_artifact"), "douyin tiktok repost strategy artifact is required")
    require(tiktok_repost.get("lane") == "pet_healing", "douyin tiktok repost strategy lane must be pet_healing")
    require(tiktok_repost.get("content_line") == "tiktok_hot_localized_repost", "douyin tiktok repost content line must be tiktok_hot_localized_repost")
    intent = str(tiktok_repost.get("content_intent", ""))
    require("preserve_source_entertainment_or_story_meaning" in intent, "douyin tiktok repost must preserve source entertainment or story meaning")
    forbidden_conversion = " ".join(tiktok_repost.get("forbidden_conversion") or [])
    require("do_not_turn_tiktok_hot_localized_reposts_into_cat_knowledge_explainers" in forbidden_conversion, "douyin tiktok repost must not be converted into cat knowledge explainers")
    required_strategy_fields = set(tiktok_repost.get("required_fields") or [])
    for field in ["trend_basis", "keyword_plan", "source_screening", "content_generation_inputs", "quality_gate"]:
        require(field in required_strategy_fields, f"douyin tiktok repost strategy missing required field: {field}")
    source_rules = " ".join(tiktok_repost.get("source_screening_rules") or [])
    for marker in ["US_PROXY", "captcha", "contact_sheet", "non_cat"]:
        require(marker in source_rules, f"douyin tiktok source screening must mention {marker}")
    audio_rules = " ".join(tiktok_repost.get("audio_adaptation_rules") or [])
    for marker in [
        "voiceover_must_match_source_entertainment_or_story_tone",
        "background_music",
        "background_music_must_be_selected_per_work",
        "online_real_instrument_bgm_required",
        "local_bgm_library_and_procedural_bgm_are_forbidden",
        "same_batch_reusing_same_bgm_requires_current_ops_reason",
        "audio_stream_duration_must_equal_video_duration",
        "dry_voiceover_only",
    ]:
        require(marker in audio_rules, f"douyin tiktok audio adaptation must mention {marker}")
    operations_audit = operations_policy_audit()
    require(operations_audit.get("passed") is True, f"operations policy/contract conflict: {operations_audit.get('conflicts')}")
    print(f"channel rulebook ok: {len(channel_rules)} channels")


if __name__ == "__main__":
    main()
