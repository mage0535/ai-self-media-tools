$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$rulebookPath = Join-Path $root "config/channel_content_rulebook.json"
$rulebook = Get-Content -LiteralPath $rulebookPath -Raw -Encoding UTF8 | ConvertFrom-Json

$requiredSequence = @(
  "load_channel_rulebook",
  "load_hermes_operating_strategy",
  "check_account_lane_fit",
  "generate_channel_specific_strategy_brief",
  "analyze_available_tools_and_select_content_stack",
  "run_quality_gate",
  "run_delivery_health_gate",
  "postcheck_platform_state",
  "write_metrics_review_row"
)

foreach ($step in $requiredSequence) {
  if ($rulebook.mandatory_sequence -notcontains $step) {
    throw "missing mandatory sequence step: $step"
  }
}

$coreRequiredChannels = @(
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
  "twitter"
)

$channels = $rulebook.channel_rules.PSObject.Properties.Name
foreach ($channel in $coreRequiredChannels) {
  if ($channels -notcontains $channel) {
    throw "missing channel rule: $channel"
  }
}
foreach ($channel in $channels) {
  $rule = $rulebook.channel_rules.$channel
  foreach ($field in @("lane", "primary_types", "publish_policy", "must_use_tools", "quality_gates", "postcheck")) {
    if (-not $rule.PSObject.Properties.Name.Contains($field)) {
      throw "missing field for ${channel}: $field"
    }
  }
}

if (-not $rulebook.global_hard_gates.metrics_review_required) {
  throw "metrics review must be required"
}
if ($rulebook.global_hard_gates.proxy_required_for_hermes_channel_access) {
  throw "domestic channel access must be direct-first"
}
if (-not $rulebook.proxy_policy) {
  throw "proxy_policy is required"
}
foreach ($field in @("domestic_proxy_env", "international_proxy_env", "domestic_channels", "international_channels", "rules")) {
  if (-not $rulebook.proxy_policy.PSObject.Properties.Name.Contains($field)) {
    throw "missing proxy_policy field: $field"
  }
}
if ($rulebook.proxy_policy.domestic_proxy_env -ne "CN_PROXY") {
  throw "domestic channels must use CN_PROXY"
}
if ($rulebook.proxy_policy.international_proxy_env -ne "US_PROXY") {
  throw "international channels must use US_PROXY"
}
if (($rulebook.proxy_policy.domestic_route_order -join ",") -ne "direct,CN_PROXY") {
  throw "domestic route order must be direct then CN_PROXY"
}
if (($rulebook.proxy_policy.international_route_order -join ",") -ne "direct,US_PROXY") {
  throw "international route order must be direct then US_PROXY"
}
$proxyCovered = @($rulebook.proxy_policy.domestic_channels) + @($rulebook.proxy_policy.international_channels)
foreach ($channel in $channels) {
  if ($proxyCovered -notcontains $channel) {
    throw "channel missing from proxy policy: $channel"
  }
}
foreach ($channel in @($rulebook.proxy_policy.domestic_channels)) {
  if ($rulebook.proxy_policy.international_channels -contains $channel) {
    throw "channel appears in both domestic and international proxy policies: $channel"
  }
}

$wechat = $rulebook.channel_rules.wechat
foreach ($tool in @(
    "wechat_account_data_analysis",
    "wechat_same_lane_account_analysis",
    "github_trending_collector",
    "wechat_and_external_hot_trend_analysis",
    "scripts/validate_wechat_auto_packet.py",
    "draft_batchget_postcheck"
  )) {
  if ($wechat.must_use_tools -notcontains $tool) {
    throw "wechat must_use_tools missing: $tool"
  }
}
if (-not (Test-Path -LiteralPath (Join-Path $root "scripts/validate_wechat_auto_packet.py"))) {
  throw "wechat validator script is missing"
}
if ($wechat.content_channels.github_selection -ne "weekly_bundle_one_ai_project_plus_one_non_ai_project") {
  throw "wechat github_selection must require a weekly AI + non-AI GitHub project bundle"
}
if (-not $wechat.content_channels.hot_content_generation) {
  throw "wechat hot_content_generation channel is required"
}
foreach ($field in @("account_analysis", "same_lane_account_analysis", "cross_platform_trend_analysis", "topic_selection")) {
  if ($wechat.strategy_requirements.required_inputs_before_content_generation -notcontains $field) {
    throw "wechat strategy input missing: $field"
  }
}
foreach ($field in @("github_ai_projects", "github_non_ai_projects", "weekly_bundle_reason_or_ops_override")) {
  if ($wechat.strategy_requirements.github_selection_required -notcontains $field) {
    throw "wechat github selection field missing: $field"
  }
}
foreach ($gate in @("account_data_analysis", "same_lane_account_benchmark", "cross_platform_trend_analysis", "content_workflow_inputs", "dual_content_channels")) {
  if ($wechat.quality_gates -notcontains $gate) {
    throw "wechat quality gate missing: $gate"
  }
}

$kuaishou = $rulebook.channel_rules.kuaishou
foreach ($tool in @("hermes_operating_strategy", "same_lane_hot_video_analysis", "cross_pipeline_v5", "scripts/validate_kuaishou_auto_packet.py", "scripts/kuaishou_postcheck_manifest.py", "sau_kuaishou_uploader", "management_page_postcheck")) {
  if ($kuaishou.must_use_tools -notcontains $tool) {
    throw "kuaishou must_use_tools missing: $tool"
  }
}
if (-not (Test-Path -LiteralPath (Join-Path $root "scripts/validate_kuaishou_auto_packet.py"))) {
  throw "kuaishou validator script is missing"
}
if (-not (Test-Path -LiteralPath (Join-Path $root "scripts/kuaishou_postcheck_manifest.py"))) {
  throw "kuaishou postcheck script is missing"
}
foreach ($gate in @("strategy_before_generation", "kuaishou_trend_evidence", "six_distinct_knowledge_card_layouts", "no_local_soundhelix_or_synthetic_bgm_without_explicit_exception")) {
  if ($kuaishou.quality_gates -notcontains $gate) {
    throw "kuaishou quality gate missing: $gate"
  }
}
if ($kuaishou.postcheck -ne "kuaishou_management_pending_list_with_exact_schedule_time") {
  throw "kuaishou postcheck must require exact schedule management-page evidence"
}

$douyin = $rulebook.channel_rules.douyin
if (-not $douyin.PSObject.Properties.Name.Contains("weekly_mix")) {
  throw "douyin weekly_mix is required"
}
if ([int]$douyin.weekly_mix.cat_knowledge_or_original -ne 2) {
  throw "douyin weekly_mix.cat_knowledge_or_original must be 2"
}
if ([int]$douyin.weekly_mix.tiktok_hot_localized_reposts -ne 5) {
  throw "douyin weekly_mix.tiktok_hot_localized_reposts must be 5"
}
$douyinVariants = $rulebook.platform_account_variants.douyin
if (-not $douyinVariants) {
  throw "douyin account variants are required"
}
if ($douyinVariants.base_platform -ne "douyin") {
  throw "douyin account variants must declare base_platform=douyin"
}
if (-not $douyinVariants.required) {
  throw "douyin account variants must be required"
}
$douyinExecutionOrder = @($douyinVariants.execution_order)
foreach ($accountKey in @("douyin_pet", "douyin_ai")) {
  if ($douyinExecutionOrder -notcontains $accountKey) {
    throw "douyin execution_order missing: $accountKey"
  }
  if (-not $douyinVariants.accounts.PSObject.Properties.Name.Contains($accountKey)) {
    throw "douyin account variant missing: $accountKey"
  }
}
foreach ($field in @("cookie_state_profile", "historical_feedback", "performance_metrics", "growth_strategy", "platform_source_matrix", "tools_capability_analysis", "tool_selection_plan", "visual_recipe", "tool_invocation_manifest", "handoff_package", "output_dir")) {
  if ($douyinVariants.isolation_required -notcontains $field) {
    throw "douyin account isolation field missing: $field"
  }
}
$douyinForbiddenReuse = [string]::Join(" ", @($douyinVariants.forbidden_cross_account_reuse))
foreach ($marker in @("final.mp4", "template", "bgm", "title", "script", "source_material")) {
  if (-not $douyinForbiddenReuse.Contains($marker)) {
    throw "douyin cross-account reuse marker missing: $marker"
  }
}
if ($douyinVariants.blocked_status -ne "douyin_account_binding_missing") {
  throw "douyin account binding missing status mismatch"
}
$douyinPet = $douyinVariants.accounts.douyin_pet
$douyinAi = $douyinVariants.accounts.douyin_ai
foreach ($entry in @(@("douyin_pet", $douyinPet), @("douyin_ai", $douyinAi))) {
  $key = $entry[0]
  $account = $entry[1]
  if ($account.base_platform -ne "douyin") {
    throw "$key base_platform must be douyin"
  }
  if ($account.account_key -ne $key) {
    throw "$key account_key mismatch"
  }
  if ($account.cookie_account -ne $key) {
    throw "$key cookie_account must match account_key"
  }
  if ($account.profile -ne $key) {
    throw "$key profile must match account_key"
  }
  if ($account.growth_strategy_key -ne "growth_strategy:${key}:latest") {
    throw "$key growth strategy key mismatch"
  }
  if ($account.publish_boundary -ne "manual_handoff_only") {
    throw "$key must be manual handoff only"
  }
  if (-not ([string]$account.output_dir_pattern).Contains($key)) {
    throw "$key output directory must include account key"
  }
}
if ($douyinPet.lane -ne "pet_healing") {
  throw "douyin_pet lane must be pet_healing"
}
if ($douyinAi.lane -ne "ai_efficiency_open_source") {
  throw "douyin_ai lane must be ai_efficiency_open_source"
}
if ([int]$douyinPet.weekly_mix.cat_knowledge_or_original -ne 2) {
  throw "douyin_pet weekly cat knowledge quota must be 2"
}
if ([int]$douyinPet.weekly_mix.tiktok_hot_localized_reposts -ne 5) {
  throw "douyin_pet weekly TikTok repost quota must be 5"
}
if ($douyinPet.required_content_lines -notcontains "tiktok_hot_localized_repost") {
  throw "douyin_pet must include TikTok localized repost line"
}
if ($douyinAi.required_content_lines -notcontains "ai_tool_microcase") {
  throw "douyin_ai must include AI tool microcase line"
}
if ($douyinAi.forbidden_content_lines -notcontains "cat_knowledge_or_original") {
  throw "douyin_ai must forbid cat knowledge line"
}
$tiktokRepost = $douyin.tiktok_repost_strategy_required
if (-not $tiktokRepost) {
  throw "douyin tiktok_repost_strategy_required is required"
}
if (-not $tiktokRepost.strategy_artifact) {
  throw "douyin tiktok repost strategy artifact is required"
}
if ($tiktokRepost.lane -ne "pet_healing") {
  throw "douyin tiktok repost strategy lane must be pet_healing"
}
if ($tiktokRepost.content_line -ne "tiktok_hot_localized_repost") {
  throw "douyin tiktok repost content line must be tiktok_hot_localized_repost"
}
if (-not ([string]$tiktokRepost.content_intent).Contains("preserve_source_entertainment_or_story_meaning")) {
  throw "douyin tiktok repost must preserve source entertainment or story meaning"
}
$forbiddenConversion = [string]::Join(" ", @($tiktokRepost.forbidden_conversion))
if (-not $forbiddenConversion.Contains("do_not_turn_tiktok_hot_localized_reposts_into_cat_knowledge_explainers")) {
  throw "douyin tiktok repost must not be converted into cat knowledge explainers"
}
foreach ($field in @("trend_basis", "keyword_plan", "source_screening", "content_generation_inputs", "quality_gate")) {
  if ($tiktokRepost.required_fields -notcontains $field) {
    throw "douyin tiktok repost strategy missing required field: $field"
  }
}
$sourceRules = [string]::Join(" ", @($tiktokRepost.source_screening_rules))
foreach ($marker in @("US_PROXY", "captcha", "contact_sheet", "non_cat")) {
  if (-not $sourceRules.Contains($marker)) {
    throw "douyin tiktok source screening must mention $marker"
  }
}
$audioRules = [string]::Join(" ", @($tiktokRepost.audio_adaptation_rules))
foreach ($marker in @(
    "voiceover_must_match_source_entertainment_or_story_tone",
    "background_music",
    "background_music_must_be_selected_per_work",
    "online_real_instrument_bgm_required",
    "local_bgm_library_and_procedural_bgm_are_forbidden",
    "same_batch_reusing_same_bgm_requires_current_ops_reason",
    "audio_stream_duration_must_equal_video_duration",
    "dry_voiceover_only"
  )) {
  if (-not $audioRules.Contains($marker)) {
    throw "douyin tiktok audio adaptation must mention $marker"
  }
}

Write-Output "channel rulebook ok: $($channels.Count) channels"
