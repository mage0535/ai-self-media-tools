# Project Guide

[中文](PROJECT_GUIDE.zh.md) | [English](PROJECT_GUIDE.en.md)

Version: `0.1`

## 1. What This Project Is

AI Self-Media Tools is a workflow system for content intelligence, generation, draft-first delivery, and automation.

It is designed to turn repeated content work into a structured pipeline:

- discover
- analyze
- score
- generate
- review
- draft-deliver
- learn from results

## 2. Problems It Solves

- too many trend candidates, weak prioritization
- too much reference material, weak structured analysis
- generated outputs becoming generic or platform-misaligned
- multi-platform delivery being fragile and risky
- historical performance being recorded but not actively reused

## 3. Core Goal

Build a content system that:

- stores intelligence as reusable memory
- routes topics to the right form and platform
- gates low-quality outputs before delivery
- defaults to drafts rather than unsafe live publishing
- improves decisions over repeated runs

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

## 6. Installation Steps

```bash
python scripts/install.py
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform project-audit
```

## 7. User Decisions During Installation

1. Install root  
Choose whether to use the default home directory install root or a dedicated directory.

2. Generation provider  
Choose between Hermes CLI, OpenAI-compatible provider, or fallback-only mode.

3. Media scripts  
Decide whether image/video/OCR/transcription/analyze scripts already exist or should be stubbed first.

4. Delivery mode  
Decide whether to stay draft-only or connect real publishers.

5. Notification mode  
Choose local logs only or add Hermes / Telegram / webhook channels.

6. Credentials  
Decide whether this is a dry-run environment or a real delivery environment.

## 8. Tooling

Current integrated or detectable tooling includes:

- ffmpeg
- yt-dlp
- playwright
- AutoCLI
- Open Notebook
- AiToEarn
- social-auto-upload
- script-backed OCR / transcription / analysis

See also:
- [Acknowledgements](ACKNOWLEDGEMENTS.md)

## 9. Current Roadmap Direction

`0.1` already includes:

- thicker intelligence memory
- topic clustering
- historical-feedback enrichment
- quality gate
- queue-backed delivery
- provider abstraction

Recommended next steps:

- weight calibration from historical performance
- dedicated workers
- provider priority / fallback matrix
- stronger long-term memory and topic ranking optimization
