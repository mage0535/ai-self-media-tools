# 官方作品级指标导入契约

目的：将**自有或明确授权账号**的官方后台 CSV / JSON / JSONL 导出，安全导入内容绩效库；不接收竞品 Cookie、签名接口、验证码绕过或账号总览截图。

## 导入命令

```bash
cd /root/.ai-self-media-tools
PYTHONPATH=. .venv/bin/python -m content_platform.cli performance-import \
  /secure/export/platform-metrics.csv --allow-unknown-job
```

`--allow-unknown-job` 会为未关联历史内容包的官方导出创建可审计的 `performance-import:<platform>:<external-id-or-title>` 快照任务；不会覆盖已有任务。

## 每行最低字段

```csv
platform,account_key,platform_content_id,title,published_at,observed_at,metric_window,views,likes,comments,shares,saves,follows
```

- `platform`：`wechat`、`douyin_ai`、`kuaishou`、`tiktok`、`youtube`、`bilibili`、`zhihu`、`juejin`
- `account_key`：账号维度。抖音 AI 与猫咪账号必须分开，且猫咪账号不得混入真实场景 AI lane。
- `platform_content_id`：文章/视频/回答的稳定 ID；可使用 `article_id`、`video_id`、`bvid`、`aid`、`content_id`。
- `observed_at`：必须带时区的 ISO-8601，例如 `2026-09-15T12:00:00+08:00`。
- `metric_window`：建议明确为 `1h`、`24h`、`72h`、`7d` 或官方报表窗口。
- 至少存在一个数值结果字段；缺失指标不要写成 `0`。

导入器会保留 `account_key`、`article_id`、`content_id`、`video_id`、`bvid`、`aid`、`platform_content_id`、`canonical_url`、`published_at`、`observed_at`、`metric_window`、`source` 为可追溯元数据。

## 平台特有字段

- **公众号**：`read_count`、`share_count`、`finish_rate`、`collect_count`，并带 `article_id`。
- **抖音 / 快手 / TikTok**：`play_count`、`three_second_rate`、`completion_rate`、`avg_play_seconds`。
- **YouTube**：`impressions`、`views`、`likes`、`comments`、`shares`、`avg_watch_seconds`、`completion_rate`；Shorts 与长视频分开导出、分开比较。
- **B站**：`views`、`likes`、`coins`、`favorites`、`danmaku`、`comments`，并带 `bvid` 或 `aid`。
- **知乎 / 掘金**：带 `article_id` / `question_id` / `content_id`，以及阅读、赞同/点赞、收藏、评论、分享、关注等官方可导字段。

未在核心列中的数值字段将作为平台特有指标保留。

## 状态机如何使用导入数据

1. 同一 `platform + platform_content_id` 的两次同口径、带时区观测可形成 **S2 双快照增长**。
2. 必须再附带可追溯的正文/公开字幕/授权媒体帧证据，才能进入 **S3 内容证据**。
3. 十项深拆和引用哈希完整且未过期，才是 **S4 深拆完成**。
4. 绑定 reference ID 与证据哈希后，才是 **S5 可建议**。
5. 只有自有/授权结果标签、足量样本、方法版本、评估哈希、回滚引用与显式策略开关齐备，才可进入 **S6 自动学习**。

默认所有导入只更新绩效记录；不会自动发布，也不会自动声明爆款。
