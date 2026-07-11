# Agent Context Snippet

## Purpose

This file provides a publish-safe project-identification snippet that can be
sent to any agent. It avoids server-private absolute paths and keeps the public
repository agent-neutral.

## Default Snippet

Use this when you want an agent to stay inside this project only:

```text
From this point on, `自媒体推广工具` is the fixed project alias.
Compatible legacy alias: `AI自媒体运营推广工具`.

This alias refers only to:
- GitHub repository: `<github-owner>/<repository>`
- the main orchestration project for content generation, delivery, scheduling,
  management console, and platform operations
- the paired domestic browser-publishing runtime model built around
  `social-auto-upload`

Do not reinterpret this alias as a generic promo workspace, a generic matrix
workspace, an old content-platform clone, or a backup copy.

If you cannot first confirm that the current repository, runtime, or service
context matches this alias, stop and say:
`当前不在 自媒体推广工具 上下文`
before doing any further analysis or changes.
```

## Companion Snippet For Similar Projects

Use this when you also need to distinguish the other common workspace:

```text
Use these fixed aliases only:
- `自媒体推广工具`
- `推广矩阵`
- `旧版内容平台`

Do not switch between them unless I explicitly tell you to.
If the current context does not match the alias I named, stop and report:
`当前不在 <项目名> 上下文`
```

## Notes

- This file is intentionally public and publish-safe.
- Server-specific absolute paths belong in a private alias registry outside the
  repository.
- The goal is agent compatibility, not one-agent customization.
