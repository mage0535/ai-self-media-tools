#!/usr/bin/env python3
"""Archived legacy Video Channels uploader.

Direct Video Channels upload scripts bypass Pipeline, platform quality gates,
preflight manifests, and management-page postcheck. They are intentionally
blocked to prevent accidental Hermes/manual execution.
"""

raise SystemExit(
    "archived_shipinhao_upload_script: use Pipeline + "
    "validate_shipinhao_auto_packet + shipinhao-handoff/postcheck"
)
