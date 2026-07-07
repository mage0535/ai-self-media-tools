# Project Guide

[中文](PROJECT_GUIDE.zh.md) | [English](PROJECT_GUIDE.en.md)

Version: `0.2`

## 1. What This Project Is

AI Self-Media Tools is a workflow system that turns content work into a repeatable chain:

- discover
- analyze
- score
- generate
- review
- draft-deliver
- manage
- learn from results

## 2. Problems It Solves

- too many trend candidates, weak prioritization
- too much reference material, weak structured analysis
- generic AI outputs
- multi-platform delivery and account-management complexity
- weak learning from historical performance

## 3. Goal

Build a content system that:

- stores intelligence as reusable memory
- routes topics to the right form and platform
- gates low-quality outputs before delivery
- defaults to drafts rather than unsafe live publishing
- improves decisions over repeated runs
- exposes platform/account/workflow state through a management console

## 4. Workflow

### 4.1 Topic Analysis

```bash
python -m content_platform trends --limit 10
python -m content_platform analyze-topic --topic "AI automation"
python -m content_platform account-report --topic "AI automation"
```

### 4.2 Generation

```bash
python -m content_platform create --topic "AI automation" --platform wechat --platform xiaohongshu
python -m content_platform run <job_id>
```

### 4.3 Review

```bash
python -m content_platform approve <job_id> --actor operator --note "checked"
python -m content_platform reject <job_id> --actor operator --note "rewrite"
```

### 4.4 Draft Delivery / Publishing

```bash
python -m content_platform publish <job_id>
python -m content_platform status <job_id>
```

### 4.5 Performance Feedback

```bash
python -m content_platform record-performance <job_id> --platform wechat --views 1200 --likes 90 --comments 25 --shares 12
python -m content_platform feedback-summary
```

### 4.6 Management Console

```bash
python -m content_platform admin-serve --password "your-password"
```

The command prints a one-time access URL.

The console provides:

- global platform overview
- per-platform detail pages
- multi-account binding
- account status checks
- latest works
- review / queue / failure panels
- charts on the home page and platform pages

## 5. Main Outputs

- jobs
- draft metadata
- topic clusters
- account snapshots
- idea candidates
- media artifacts
- platform draft payloads
- metrics
- notification logs
- management-console binding and chart data

## 6. Installation Decisions

The user must decide:

1. install root
2. generation provider
3. media script paths
4. delivery mode
5. notification mode
6. whether to use real credentials
7. management-console password and access mode

## 7. Tooling

Current integrated or detectable tooling includes:

- ffmpeg
- yt-dlp
- playwright
- AutoCLI
- Open Notebook
- AiToEarn
- social-auto-upload
- script-backed OCR / transcription / analysis
- built-in management service

See also:
- [Acknowledgements](ACKNOWLEDGEMENTS.md)

## 8. Current Roadmap Direction

`0.2` already includes:

- thicker intelligence memory
- topic clustering
- historical-feedback enrichment
- quality gate
- queue-backed delivery
- provider abstraction
- management console
- multi-account platform binding and chart analytics

Recommended next steps:

- weight calibration from historical performance
- dedicated workers
- provider priority / fallback matrix
- stronger long-term memory and topic ranking optimization
