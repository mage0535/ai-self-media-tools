# Hermes Reddit Channel Integration Instructions

Use this note when asking Hermes or another operator agent to recognize and test Reddit as a managed channel in this project.

## Scope

Reddit is a managed international channel for:

- trend discovery and heat analysis
- post-format preview
- human-reviewed promotion drafts
- centralized status queries through MCP/Hermes
- Telegram/Hermes review notifications

Reddit is not configured for automated spam, voting, DMs, stealth browser operation, proxy rotation, or bypassing platform checks.

## Runtime Configuration

Set these values only in the runtime environment or ignored secret files:

```bash
export REDDIT_CLIENT_ID="<reddit-app-client-id>"
export REDDIT_CLIENT_SECRET="<reddit-app-client-secret>"
export REDDIT_REFRESH_TOKEN="<reddit-oauth-refresh-token>"
```

Enable Reddit trend collection in the local runtime `config.json`:

```json
{
  "trends": {
    "reddit": {
      "enabled": true,
      "client_id_env": "REDDIT_CLIENT_ID",
      "client_secret_env": "REDDIT_CLIENT_SECRET",
      "refresh_token_env": "REDDIT_REFRESH_TOKEN",
      "user_agent": "ai-self-media-tools/0.2 by configured-operator",
      "subreddits": ["SideProject", "ArtificialInteligence", "Entrepreneur"],
      "keywords": ["AI workflow", "automation", "content operations"],
      "limit_per_subreddit": 25,
      "sort": "hot",
      "time_filter": "week"
    }
  },
  "publishers": {
    "platforms": {
      "reddit": {
        "type": "reddit-draft",
        "outbox": "${CONTENT_PLATFORM_HOME}/data/outbox",
        "default_subreddit": "manual-selection"
      }
    }
  }
}
```

Do not commit real OAuth values, cookies, account names, or subreddit-private notes.

## Hermes Recognition Prompt

Send this to Hermes:

```text
Recognize Reddit as an available AI self-media channel in the current AI self-media tools project.

Rules:
- Treat Reddit as an international channel.
- Use it for trend discovery, heat analysis, and human-reviewed promotion drafts.
- Do not auto-post, auto-comment, vote, DM, rotate proxies, use stealth browser behavior, or bypass Reddit platform checks.
- Store credentials only in runtime env vars: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_REFRESH_TOKEN.
- Use the project MCP tool reddit_channel_status to inspect Reddit channel readiness.
- Use trends_query to confirm Reddit topics enter the trend pool after config enables trends.reddit.enabled=true.
- For generated content targeting Reddit, create jobs with platform reddit and keep delivery as review_required until a human approves.
- Telegram/Hermes notifications should show platforms=reddit, reddit delivery status, outbox draft path, and review-action commands.
```

## Commands For Hermes Or Operators

Check MCP exposure:

```bash
python -m content_platform.mcp_server --transport stdio
```

Expected MCP tool:

```text
reddit_channel_status
```

Query Reddit channel status through Hermes MCP:

```text
Call tool: reddit_channel_status
Expected: configured=true, publisher_type=reddit-draft, policy=human_review_draft_only
```

Check trends through CLI:

```bash
python -m content_platform --config "$CONTENT_PLATFORM_HOME/config.json" trends --refresh --limit 10
```

Create a Reddit-targeted draft:

```bash
python -m content_platform --config "$CONTENT_PLATFORM_HOME/config.json" create --topic "AI workflow launch checklist" --platform reddit
python -m content_platform --config "$CONTENT_PLATFORM_HOME/config.json" run <job_id>
```

Expected result:

```text
job state: review_required
delivery platform: reddit
delivery status: review_required
draft path: $CONTENT_PLATFORM_HOME/data/outbox/reddit/<job_id>.json
```

Approve only after human review:

```bash
python -m content_platform --config "$CONTENT_PLATFORM_HOME/config.json" review-token <job_id> --action approve
python -m content_platform --config "$CONTENT_PLATFORM_HOME/config.json" review-action <token> --action approve --actor REVIEWER
```

## Telegram/Hermes Notification Check

For a Reddit review-required job, the notification text should include:

```text
platforms=reddit
deliveries=reddit:review_required <outbox-path>
approve: content-platform review-action <token> --action approve --actor REVIEWER
reject: content-platform review-action <token> --action reject --actor REVIEWER
```

If these fields are missing, the Telegram/Hermes notification layer is not using the updated notifier code.

## Acceptance Criteria

- `reddit_channel_status` is available through MCP/Hermes.
- `reddit_channel_status` reports `policy=human_review_draft_only`.
- Reddit appears as a managed channel in platform catalog data.
- Reddit trends can be collected only after OAuth env vars and `trends.reddit.enabled=true` are configured.
- Reddit promotion produces a local review packet, not a live post.
- Telegram/Hermes review messages include platform, Reddit delivery status, draft path, and review commands.
