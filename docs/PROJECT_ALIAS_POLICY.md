# Project Alias Policy

## Purpose

This project is intended to work across multiple agents and runtimes. Similar
names such as `promo`, `matrix`, and `content-platform` can appear in parallel
workspaces. To avoid cross-project confusion, every long-lived workspace should
have one stable human-readable alias and one clear technical anchor.

## Public Alias For This Repository

The primary public alias for this repository is:

- `自媒体推广工具`

Compatible legacy alias:

- `AI自媒体运营推广工具`

Use this alias when referring to the repository represented by:

- GitHub repository `<github-owner>/<repository>`
- the main orchestration/runtime project for content generation, scheduling,
  management console, and multi-platform delivery
- the paired browser-publishing runtime used by domestic platforms such as
  Douyin and Bilibili

## Required Anchor Rule

A project alias is not valid by name alone. It should always resolve to one
specific technical anchor set:

1. source repository
2. main runtime/project root
3. any required external runtime paired with that project

For this repository, that means:

1. GitHub repository `<github-owner>/<repository>`
2. the main content-platform orchestration runtime
3. the paired `social-auto-upload` domestic browser-publishing runtime

## Distinguish From Other Similar Workspaces

Do not use `自媒体推广工具` or `AI自媒体运营推广工具` as a loose synonym for:

- a generic `promo` workspace
- a generic `matrix` workspace
- an older `content-platform` clone or backup
- a historical backup snapshot

Each of those should have its own alias and its own anchor set.

## Multi-Agent Rule

The alias policy should be usable by Hermes, Codex, Claude Code, OpenCode, or
any other agent runtime. Public documentation should stay agent-neutral and
describe:

1. the stable alias
2. the repository anchor
3. the runtime pairing model
4. the rule that the agent must stop if the anchor set is not confirmed

## Operator Rule

If an agent or operator cannot confirm the alias anchor set before acting, it
should stop and report that the current context is not confirmed.

## Server-Private Registry

Actual server-specific absolute paths, backup locations, and private runtime
layouts should be recorded only in a server-private alias registry, not in the
publishable repository.
