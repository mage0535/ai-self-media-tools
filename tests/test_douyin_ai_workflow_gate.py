from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_douyin_ai_workflow_blocks_out_of_order_execution(tmp_path: Path):
    status_file = tmp_path / "status.json"
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "enforce_douyin_ai_workflow.py"),
        "topic_decision",
        "--topic", "AI测试",
        "--direction", "spreadsheet_cleanup",
    ]
    env = {"DOUYIN_AI_WORKFLOW_STATUS": str(status_file)}
    res = subprocess.run(cmd, env={**dict(os.environ), **env}, capture_output=True, text=True)
    assert res.returncode != 0
    assert "BLOCKED: complete 'trend_scan_11sources' before starting 'topic_decision'" in res.stderr or "BLOCKED" in res.stdout


def test_douyin_ai_workflow_blocks_script_without_8_beats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.enforce_douyin_ai_workflow import step_script_and_storyboard, save_status

    status_file = tmp_path / "status.json"
    monkeypatch.setenv("DOUYIN_AI_WORKFLOW_STATUS", str(status_file))
    save_status(status_file, {"current_step": 2, "completed": ["trend_scan_11sources", "topic_decision"]})
    
    # 7 beats instead of 8
    script_7_beats = "\n\n".join([f"第{i}段内容测试。" for i in range(1, 8)])
    contract_8 = [{"scene": i} for i in range(1, 9)]

    with pytest.raises(SystemExit) as exc:
        step_script_and_storyboard("20260922", script_7_beats, contract_8)
    assert "must contain exactly 8 beats" in str(exc.value)


def test_douyin_ai_workflow_blocks_subtitle_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.enforce_douyin_ai_workflow import step_script_and_storyboard, save_status

    status_file = tmp_path / "status.json"
    monkeypatch.setenv("DOUYIN_AI_WORKFLOW_STATUS", str(status_file))
    save_status(status_file, {"current_step": 2, "completed": ["trend_scan_11sources", "topic_decision"]})

    # One sentence > 16 chars without punctuation
    script_overflow = "\n\n".join([
        "这是一个非常非常长而且没有任何标点符号的严重违规超长字幕句子啊啊啊。" if i == 1 else f"正常句子{i}。"
        for i in range(1, 9)
    ])
    contract_8 = [{"scene": i} for i in range(1, 9)]

    with pytest.raises(SystemExit) as exc:
        step_script_and_storyboard("20260922", script_overflow, contract_8)
    assert "exceeding 16 chars" in str(exc.value)


def test_cross_platform_asset_collision_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.enforce_douyin_ai_workflow import check_cross_platform_collisions

    # Create dummy image in runs/kuaishou/20260922_dummy/
    fake_runs = tmp_path / "data" / "runs"
    ks_dir = fake_runs / "kuaishou" / "20260922_dummy"
    ks_dir.mkdir(parents=True, exist_ok=True)
    ks_img = ks_dir / "scene_01.jpg"
    ks_img.write_bytes(b"SAME_IMAGE_BYTES_12345678")

    # Our candidate image
    our_dir = tmp_path / "our_bg"
    our_dir.mkdir(parents=True, exist_ok=True)
    our_img = our_dir / "bg_01.jpg"
    our_img.write_bytes(b"SAME_IMAGE_BYTES_12345678")

    monkeypatch.setattr("scripts.enforce_douyin_ai_workflow.PROJECT_ROOT", tmp_path)
    collisions = check_cross_platform_collisions("20260922", [our_img])
    assert len(collisions) == 1
    assert "matches kuaishou asset" in collisions[0]


def test_douyin_ai_cover_template_collision_rejected(tmp_path: Path):
    from scripts.enforce_douyin_ai_workflow import check_cover_template_distinct

    # Mock a cover.html with Kuaishou's yellow sticker and red pill
    ks_cover_html = tmp_path / "cover.html"
    ks_cover_html.write_text('<div class="pill" style="background: #e11d48"></div><div class="sticker-title" style="background: #facc15">Title</div>', encoding="utf-8")

    failures = check_cover_template_distinct(ks_cover_html)
    assert len(failures) == 2
    assert "yellow sticker" in failures[0]
    assert "red pill" in failures[1]


def test_quality_gate_requires_keyframes_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.enforce_douyin_ai_workflow import step_quality_gate_and_handoff, save_status

    status_file = tmp_path / "status.json"
    monkeypatch.setenv("DOUYIN_AI_WORKFLOW_STATUS", str(status_file))
    save_status(status_file, {"current_step": 5, "completed": ["trend_scan_11sources", "topic_decision", "script_and_storyboard", "asset_provenance", "render_and_cover"]})

    empty_run = tmp_path / "run_empty"
    empty_run.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SystemExit) as exc:
        step_quality_gate_and_handoff("20260922", empty_run, {"platform": "douyin_ai"})
    assert "missing keyframes_audit directory" in str(exc.value)


def test_cross_platform_template_collision_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.enforce_douyin_ai_workflow import check_cross_platform_template_collisions

    fake_runs = tmp_path / "data" / "runs"
    ks_dir = fake_runs / "kuaishou" / "20260922_demo"
    ks_dir.mkdir(parents=True, exist_ok=True)
    ks_cover = ks_dir / "cover.html"
    ks_cover.write_text('<body data-template="evidence_card"><div class="evidence-row"></div></body>', encoding="utf-8")

    our_dir = tmp_path / "douyin_run"
    our_dir.mkdir(parents=True, exist_ok=True)
    our_cover = our_dir / "cover.html"
    our_cover.write_text('<body data-template="evidence_card"><div class="evidence-row"></div></body>', encoding="utf-8")

    monkeypatch.setattr("scripts.enforce_douyin_ai_workflow.PROJECT_ROOT", tmp_path)
    collisions = check_cross_platform_template_collisions("20260922", our_cover, current_platform="douyin_ai")
    assert len(collisions) == 1
    assert "template fingerprint 'evidence_card' was already used by platform 'kuaishou'" in collisions[0]


def test_cross_platform_distinct_template_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.enforce_douyin_ai_workflow import check_cross_platform_template_collisions

    fake_runs = tmp_path / "data" / "runs"
    ks_dir = fake_runs / "kuaishou" / "20260922_demo"
    ks_dir.mkdir(parents=True, exist_ok=True)
    ks_cover = ks_dir / "cover.html"
    ks_cover.write_text('<body data-template="vibrant_sticker"><div class="sticker-title"></div></body>', encoding="utf-8")

    our_dir = tmp_path / "douyin_run"
    our_dir.mkdir(parents=True, exist_ok=True)
    our_cover = our_dir / "cover.html"
    our_cover.write_text('<body data-template="evidence_card"><div class="evidence-row"></div></body>', encoding="utf-8")

    monkeypatch.setattr("scripts.enforce_douyin_ai_workflow.PROJECT_ROOT", tmp_path)
    collisions = check_cross_platform_template_collisions("20260922", our_cover, current_platform="douyin_ai")
    assert len(collisions) == 0


def test_dynamic_visual_style_selection():
    from scripts.fast_dialogue_pipeline import select_visual_style_for_topic

    assert select_visual_style_for_topic("用Python清洗混乱Excel表格避坑") == "terminal_code"
    assert select_visual_style_for_topic("为什么领导总能一眼看出你的表格是用AI做的？") == "evidence_card"
    assert select_visual_style_for_topic("AI Agent系统工作流落地架构SOP") == "minimal_blueprint"
    assert select_visual_style_for_topic("为什么老员工面试从不跟老板谈加班？") == "vibrant_sticker"


