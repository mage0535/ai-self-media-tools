"""Cross-platform validation for config/channel_content_rulebook.json."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_PATH = ROOT / "config" / "channel_content_rulebook.json"
GROWTH_POLICY_PATH = ROOT / "config" / "growth_quality_policy.json"

REQUIRED_SEQUENCE = {
    "load_channel_rulebook",
    "load_hermes_operating_strategy",
    "check_account_lane_fit",
    "generate_channel_specific_strategy_brief",
    "run_quality_gate",
    "run_delivery_health_gate",
    "postcheck_platform_state",
    "write_metrics_review_row",
}

REQUIRED_CHANNELS = [
    "douyin",
    "kuaishou",
    "shipinhao",
    "wechat",
    "xiaohongshu",
    "toutiao",
    "juejin",
    "zhihu",
    "csdn",
    "bilibili",
    "weibo",
    "segmentfault",
    "tiktok",
    "youtube",
]

REQUIRED_CHANNEL_FIELDS = {"lane", "primary_types", "publish_policy", "must_use_tools", "quality_gates", "postcheck"}
FULL_OPS_CHANNELS = ["xiaohongshu", "toutiao", "juejin", "zhihu"]
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
GROWTH_CHANNELS = {"douyin", "kuaishou", "wechat", "bilibili", "shipinhao", "xiaohongshu"}
GROWTH_REQUIRED_FIELDS = {
    "account_performance_snapshot_or_unavailable_reason",
    "same_lane_hot_content_analysis",
    "target_user_action",
    "hook_plan",
    "retention_plan",
    "interaction_plan",
    "packaging_plan",
    "post_publish_review_plan",
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))
    sequence = set(rulebook.get("mandatory_sequence") or [])
    for step in REQUIRED_SEQUENCE:
        require(step in sequence, f"missing mandatory sequence step: {step}")

    channel_rules = rulebook.get("channel_rules") or {}
    for channel in REQUIRED_CHANNELS:
        require(channel in channel_rules, f"missing channel rule: {channel}")
        missing = REQUIRED_CHANNEL_FIELDS - set(channel_rules[channel])
        require(not missing, f"missing field for {channel}: {sorted(missing)}")

    hard_gates = rulebook.get("global_hard_gates") or {}
    require(hard_gates.get("metrics_review_required") is True, "metrics review must be required")
    require(hard_gates.get("proxy_required_for_hermes_channel_access") is True, "Hermes channel access must require an explicit proxy")

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

    domestic = set(proxy_policy.get("domestic_channels") or [])
    international = set(proxy_policy.get("international_channels") or [])
    overlap = domestic & international
    require(not overlap, f"channel appears in both proxy policies: {sorted(overlap)}")
    covered = domestic | international
    for channel in REQUIRED_CHANNELS:
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
        "scripts/validate_wechat_auto_packet.py",
        "draft_batchget_postcheck",
    ]:
        require(tool in wechat_tools, f"wechat must_use_tools missing: {tool}")
    require((ROOT / "scripts" / "validate_wechat_auto_packet.py").is_file(), "wechat validator script is missing")
    wechat_channels = wechat.get("content_channels") or {}
    require(
        wechat_channels.get("daily_github_selection") == "one_ai_project_plus_one_non_ai_project_per_day",
        "wechat daily_github_selection must require one AI and one non-AI GitHub project",
    )
    require(wechat_channels.get("hot_content_generation"), "wechat hot_content_generation channel is required")
    wechat_strategy = wechat.get("strategy_requirements") or {}
    for field in ["account_analysis", "same_lane_account_analysis", "cross_platform_trend_analysis", "topic_selection"]:
        require(field in (wechat_strategy.get("required_inputs_before_content_generation") or []), f"wechat strategy input missing: {field}")
    for field in ["github_ai_projects", "github_non_ai_projects"]:
        require(field in (wechat_strategy.get("daily_github_selection_required") or []), f"wechat daily github field missing: {field}")
    for gate in ["account_data_analysis", "same_lane_account_benchmark", "cross_platform_trend_analysis", "content_workflow_inputs", "dual_content_channels"]:
        require(gate in (wechat.get("quality_gates") or []), f"wechat quality gate missing: {gate}")

    kuaishou = channel_rules["kuaishou"]
    kuaishou_tools = set(kuaishou.get("must_use_tools") or [])
    for tool in ["hermes_operating_strategy", "same_lane_hot_video_analysis", "cross_pipeline_v5", "scripts/validate_kuaishou_auto_packet.py", "scripts/kuaishou_postcheck_manifest.py", "sau_kuaishou_uploader", "management_page_postcheck"]:
        require(tool in kuaishou_tools, f"kuaishou must_use_tools missing: {tool}")
    require((ROOT / "scripts" / "validate_kuaishou_auto_packet.py").is_file(), "kuaishou validator script is missing")
    require((ROOT / "scripts" / "kuaishou_postcheck_manifest.py").is_file(), "kuaishou postcheck script is missing")
    for gate in ["strategy_before_generation", "kuaishou_trend_evidence", "six_distinct_knowledge_card_layouts", "no_soundhelix_or_synthetic_bgm_without_explicit_exception"]:
        require(gate in (kuaishou.get("quality_gates") or []), f"kuaishou quality gate missing: {gate}")
    require(kuaishou.get("postcheck") == "kuaishou_management_pending_list_with_exact_schedule_time", "kuaishou postcheck must require exact schedule management-page evidence")

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

    douyin = channel_rules["douyin"]
    weekly = douyin.get("weekly_mix") or {}
    require(weekly.get("cat_knowledge_or_original") == 2, "douyin weekly_mix.cat_knowledge_or_original must be 2")
    require(weekly.get("tiktok_hot_localized_reposts") == 5, "douyin weekly_mix.tiktok_hot_localized_reposts must be 5")
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
        "prefer_licensed_stock_music",
        "procedural_bgm_is_fallback_only",
        "same_batch_reusing_same_bgm_requires_current_ops_reason",
        "audio_stream_duration_must_equal_video_duration",
        "dry_voiceover_only",
    ]:
        require(marker in audio_rules, f"douyin tiktok audio adaptation must mention {marker}")
    print(f"channel rulebook ok: {len(REQUIRED_CHANNELS)} channels")


if __name__ == "__main__":
    main()
