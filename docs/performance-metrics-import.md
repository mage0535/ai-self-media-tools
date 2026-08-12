# Performance Metrics Import

This project treats platform analytics as the input for the next operating strategy.
If a platform does not expose a stable API, export or copy the backend data into CSV/JSON and import it through the same command.

## Strategy Evidence Contract

The system separates audit observations from evidence that may change the next
content strategy. Public profile pages, creator-center totals, generic Hermes
scraper output, and metric files without a work identifier are retained as
`account_snapshot` records only. They never update a growth strategy.

Strategy-eligible data must contain a per-work `job_id`, `title`, or a stable
content identifier such as `video_id`, `post_id`, `article_id`, or `content_id`,
plus at least one measurable outcome. A CSV import with `title` already meets
this requirement. A JSON `metrics_file` must include one of these identifiers
on at least one row; an aggregate-only file is audit-only.

For a multi-account platform, each account needs its own backend export/API.
A shared platform cookie or account total cannot be reused across accounts.
For example, `douyin_pet` and `douyin_ai` require separate sources.

Check runtime readiness without reading or printing private credentials:

```bash
python3 -m content_platform.cli metrics-readiness \
  --collector-config /private/runtime/performance-collector.json
```

## CSV Template

```csv
platform,title,views,likes,comments,shares,saves,follows,completion_rate,three_second_view_rate,avg_watch_seconds,open_rate,finish_read_rate,share_rate,save_rate,coin_rate,danmaku_rate
wechat,Example article title,100,3,1,2,4,1,0,0,0,0.12,0.38,0.02,0.04,,
kuaishou,Example video title,200,8,3,2,5,1,0.42,0.55,23.1,,,,,
```

Required columns:
- `platform`
- `job_id` or `title`

Common metric columns:
- `views`
- `likes`
- `comments`
- `shares`
- `saves`
- `follows`
- `completion_rate`
- `three_second_view_rate`
- `avg_watch_seconds`

Any other numeric column is imported as a platform-specific metric.

## Supported Export Aliases

Platform aliases:
- `KWAI` -> `kuaishou`
- `wxSph` -> `shipinhao`
- `xhs` -> `xiaohongshu`
- `wxGzh` -> `wechat`

Metric aliases:
- `view_count`, `read_count`, `play_count`, `plays`, `impressions` -> `views`
- `like_count` -> `likes`
- `comment_count` -> `comments`
- `share_count` -> `shares`
- `collect_count`, `favorite_count`, `save_count` -> `saves`
- `new_follows`, `follower_gain` -> `follows`
- `finish_rate`, `completion` -> `completion_rate`
- `3s_rate`, `three_second_rate` -> `three_second_view_rate`
- `avg_play_seconds`, `avg_play_duration` -> `avg_watch_seconds`

Recommended platform-specific fields:
- WeChat: `open_rate`, `finish_read_rate`, `share_rate`, `save_rate`
- Kuaishou: `comment_rate`, `follow_conversion_rate`
- Shipinhao: `share_rate`, `save_rate`
- Bilibili: `coin_rate`, `danmaku_rate`, `favorite_rate`
- Xiaohongshu: `click_through_rate`, `save_rate`, `comment_rate`, `follow_conversion_rate`

## Commands

```bash
python3 -m content_platform.cli performance-collect \
  --platform youtube --platform bilibili --platform wechat --platform kuaishou \
  --platform douyin --platform shipinhao --platform xiaohongshu \
  --output /tmp/performance_collect.json

python3 -m content_platform.cli performance-collect \
  --platform youtube --platform bilibili --platform twitter --platform threads \
  --hermes-platform-scraper \
  --output /tmp/hermes_public_account_collect.json

python3 -m content_platform.cli performance-import /path/to/platform_metrics.csv
python3 -m content_platform.cli performance-review \
  --platform wechat --platform kuaishou --platform douyin --platform shipinhao \
  --platform bilibili --platform xiaohongshu --platform youtube --platform tiktok \
  --platform juejin --platform zhihu \
  --output /tmp/performance_review.json
```

If a platform has no metrics, the review report must show `metrics_missing`.
Do not treat an empty report as a successful review.

## Collection Modes

Public account snapshot:
- `youtube` can collect account-level public data when `channel_url` is provided in collector config.
- `bilibili` can collect account-level public data when `mid` is provided in collector config.
- Any backend-only platform can also use a low-confidence public profile fallback when `public_profile_url`, `profile_url`, `homepage_url`, `public_url`, or `public_urls` is configured. This is useful when creator-center login, Datacube, or platform APIs are unavailable.
- Public profile fallback only saves visible numeric signals such as followers, works, likes, views, saves, comments, and shares. It records `metric_source=public_page`, `metric_confidence=low`, and preserves the original backend failure as `backend_status` / `backend_reason`.
- Hermes runtime can reuse its local platform scraper by setting `HERMES_PLATFORM_SCRAPER` and running with `--hermes-platform-scraper`.

Authenticated backend export:
- `wechat`, `kuaishou`, `douyin`, `shipinhao`, `xiaohongshu`, `tiktok`, `juejin`, and `zhihu` currently require creator-center export or a platform-specific logged-in browser collector.
- If automatic backend collection is unavailable, export CSV and run `performance-import`.
- The system must report `backend_export_required`, not fake zero performance.

Authenticated collectors:
- `bilibili` can also collect through a private `cookie_file`. The collector supports Playwright cookie-list files and SAU `cookie_info` files. Reports must include only metrics and status, never cookie values.
- `wechat` can try Official Account Datacube when `wechat.datacube=true` is set and credentials are available from private runtime config or environment variables.
- If WeChat returns `48001 api unauthorized`, the collector must report `api_permission_blocked`. Recovery is to enable/re-authorize the Official Account statistics API, export backend data manually, or run a private browser collector with screenshot evidence.
- If Datacube cannot be enabled, use `scripts/wechat_mp_backend_collector.py` as the private browser collector. It stores the mp.weixin browser profile on the machine that runs it, exports only metrics JSON, and imports that JSON through `performance-import --allow-unknown-job`. Do not copy or print cookies.
- `douyin`, `shipinhao`, `xiaohongshu`, and `tiktok` account metrics require a verified logged-in creator-center session. A cookie file alone is not success evidence: missing file means `login_required`; present file without a working browser scrape means `browser_probe_required`.
- If a creator-center collector is blocked, configure a public profile URL before giving up. Public signals are retained for audit, but never refresh growth strategy; use a backend export/API for that.

TikTok reliable metrics source:
- Creator Center cookies are treated as a temporary probe only. If they expose only followers or works without views/likes/comments/shares/saves/rates, the cycle must record `metrics_insufficient` and must not refresh `growth_strategy:tiktok:latest` with that weak data.
- Long-term automation should use an approved TikTok metrics endpoint first. Configure it with `api_url` / `analytics_api_url` and keep the token in an environment variable such as `TIKTOK_METRICS_API_TOKEN`; never store the token in repository files.
- If no approved API is available, use `metrics_file` / `analytics_file` from a verified backend export. Public profile URL is only a low-confidence fallback.

Private config examples:

```json
{
  "bilibili": {
    "cookie_file": "/private/runtime/cookies/bilibili_main.json"
  },
  "wechat": {
    "datacube": true
  },
  "douyin": {
    "state_file": "/private/runtime/cookies/douyin_main_playwright.json",
    "public_profile_url": "https://example.com/your-public-douyin-profile"
  },
  "kuaishou": {
    "public_profile_url": "https://example.com/your-public-kuaishou-profile"
  },
  "shipinhao": {
    "public_profile_url": "https://example.com/your-public-shipinhao-profile"
  },
  "xiaohongshu": {
    "public_profile_url": "https://example.com/your-public-xiaohongshu-profile"
  },
  "tiktok": {
    "api_url": "https://your-approved-metrics-endpoint.example/tiktok",
    "api_token_env": "TIKTOK_METRICS_API_TOKEN",
    "state_file": "/private/runtime/cookies/tiktok_main.json",
    "public_profile_url": "https://www.tiktok.com/@your_handle"
  }
}
```

Hermes browser probe for login-state verification:

```bash
python3 scripts/platform_backend_metrics_probe.py \
  --platform douyin \
  --platform shipinhao \
  --platform xiaohongshu \
  --platform tiktok \
  --config data/private/performance/backend-probe-config.json \
  --out-dir /tmp/platform_backend_metrics_probe \
  --output /tmp/platform_backend_metrics_probe.json
```

The private probe config should reference storage-state paths only:

```json
{
  "douyin": {
    "state_file": "/private/runtime/cookies/douyin_main_playwright.json",
    "proxy_env": "CN_PROXY"
  },
  "shipinhao": {
    "state_file": "/private/runtime/cookies/tencent_main_playwright.json",
    "proxy_env": "CN_PROXY"
  },
  "xiaohongshu": {
    "state_file": "/private/runtime/cookies/xiaohongshu_main.json",
    "proxy_env": "CN_PROXY"
  },
  "tiktok": {
    "state_file": "/private/runtime/cookies/tiktok_main.json",
    "proxy_env": "US_PROXY"
  }
}
```

Probe statuses:
- `backend_loaded`: saved state reached a creator backend page and metric-like fields are visible.
- `login_required_or_verification`: the page redirected to login or shows verification/login text; refresh the persistent login state before collecting metrics.
- `loaded_but_metrics_not_visible`: the backend opened, but the configured page does not expose metrics; add a more specific analytics URL or export CSV.

### WeChat MP Private Browser Collector

Use this when the Official Account Datacube API cannot be enabled. The login
profile remains private on the collector machine. Hermes only receives sanitized
metric JSON.

One-time login on the machine that will collect data:

```bash
python scripts/wechat_mp_backend_collector.py login \
  --profile-dir ~/.ai-self-media-tools/wechat_mp_profile
```

Daily collection:

```bash
python scripts/wechat_mp_backend_collector.py collect \
  --profile-dir ~/.ai-self-media-tools/wechat_mp_profile \
  --output ~/.ai-self-media-tools/wechat_mp_metrics.json
```

Push the sanitized metrics into Hermes and refresh the growth strategy:

```bash
python scripts/wechat_mp_backend_collector.py push-hermes \
  --metrics-file ~/.ai-self-media-tools/wechat_mp_metrics.json \
  --ssh-target root@YOUR_HERMES_HOST \
  --ssh-key ~/.ssh/YOUR_KEY \
  --ssh-port 948 \
  --remote-project "$AI_SELF_MEDIA_HOME"
```

Hermes-only mode is possible only if the Hermes host can complete and keep a
valid mp.weixin login profile. If mp.weixin rejects server-side QR login with
"system error", do not keep regenerating QR codes; use a trusted collector
machine or refresh the Hermes browser profile from an accepted environment.

Metrics source coverage audit:

```bash
python3 scripts/audit_performance_sources.py \
  --config ~/.ai-self-media-tools/secrets/performance-collector.json \
  --platform wechat \
  --platform kuaishou \
  --platform douyin \
  --platform shipinhao \
  --platform xiaohongshu \
  --platform bilibili \
  --platform youtube \
  --output /tmp/performance_source_audit.json
```

Use this before the daily growth cycle. `backend_only` means the platform can still work when login/API is healthy, but there is no public profile fallback if login expires. `missing_source` means the platform has no configured metrics source and should not be treated as data-backed.

## Daily Growth Cycle

`performance-cycle` is the safe automation entrypoint for daily strategy optimization. It only collects analytics, writes `performance` rows, refreshes growth strategy snapshots, and writes a report. It does not publish or upload content.

```bash
content-platform \
  --config ~/.ai-self-media-tools/config.json \
  --db ~/.ai-self-media-tools/data/state.db \
  performance-cycle \
  --platform wechat \
  --platform kuaishou \
  --platform bilibili \
  --platform zhihu \
  --platform juejin \
  --platform douyin \
  --platform shipinhao \
  --platform xiaohongshu \
  --platform youtube \
  --platform tiktok \
  --platform x \
  --collector-config ~/.ai-self-media-tools/secrets/performance-collector.json \
  --output-dir ~/.ai-self-media-tools/data/performance/daily
```

What it does:
- Defaults to the current single-line growth workflow platforms when no `--platform` is provided: `wechat`, `kuaishou`, `bilibili`, `zhihu`, `juejin`, `douyin`, `shipinhao`, `xiaohongshu`, `youtube`, `tiktok`, and `x`.
- Runs collectors and writes raw output to `raw_collect.json`.
- Creates one analytics-only daily snapshot job per platform with real metrics.
- Writes usable metrics into the `performance` table.
- Runs `performance-review` logic and records missing/blocked platforms explicitly.
- Saves latest per-platform growth strategies in `tool_inventory` under `growth_strategy:<platform>:latest`.
- Saves the latest full cycle report under `tool_inventory` as `performance_cycle_latest`.

Activity checks:
- `activity.collector_ran=true`
- `activity.platform_count` equals the expected platform count
- `activity.metrics_saved` is greater than zero when at least one platform exposes data
- unavailable platforms have an explicit status such as `login_required`, `browser_probe_required`, or `api_permission_blocked`
- `performance_cycle_latest.payload.report_path` points to an existing report

The systemd timer template is `systemd/hermes-content-platform-growth-cycle.timer`. It is safe to enable because it calls only `performance-cycle`, not publishing commands.
