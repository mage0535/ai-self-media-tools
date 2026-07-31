#!/usr/bin/env python3
"""Disabled legacy renderer.

This file is kept only so old cron entries fail closed with a clear message.
Use the Pipeline video path:
  content_platform.media.MediaBridge -> scripts/video_toolchain_runner.py -> scripts/kuaishou_render.py
"""

raise SystemExit("legacy_render_demo_disabled: use Pipeline + video_toolchain_runner.py + current BGM/video gates")
