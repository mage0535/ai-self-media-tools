import json
from pathlib import Path

from content_platform.wechat_toolchain import _repair_ai_slop, _wechat_digest, prepare_wechat_professional_draft, requires_wechat_toolchain


def _fake_wewrite(path: Path) -> Path:
    script = path / "fake_wewrite.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args=sys.argv[1:]\n"
        "if args[:2] == ['run','start']:\n"
        "    print(json.dumps({'run_id':'20260729-120000-abcdef'})); sys.exit(0)\n"
        "if args and args[0] == 'llm-write':\n"
        "    out=args[args.index('--output')+1]\n"
        "    body='# Professional WeChat Title\\n\\n' + ('## Section\\nThis is a concrete paragraph with useful operational detail. ' * 80)\n"
        "    open(out,'w',encoding='utf-8').write(body)\n"
        "    print(json.dumps({'ok': True, 'output': out, 'chars': len(body), 'model': 'fake'})); sys.exit(0)\n"
        "print('bad command', args, file=sys.stderr); sys.exit(2)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _failing_wewrite(path: Path) -> Path:
    script = path / "failing_wewrite.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:3] == ['run', 'start']:\n"
        "    print('{\\\"run_id\\\": \\\"failed-run\\\"}'); sys.exit(0)\n"
        "print('writer unavailable', file=sys.stderr); sys.exit(4)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _fake_hermes_writer(path: Path) -> Path:
    script = path / "fake_hermes.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "print('# Hermes Writer Title\\n\\n' + ('## Practical section\\nConcrete operational guidance with a usable example. ' * 80))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_requires_wechat_toolchain_only_for_enforced_wechat():
    assert requires_wechat_toolchain({"feature_flags": {"channel_auto_workflow_gate": "enforce"}}, ["wechat"])
    assert not requires_wechat_toolchain({"feature_flags": {"channel_auto_workflow_gate": "enforce"}}, ["devto"])
    assert not requires_wechat_toolchain({}, ["wechat"])


def test_wechat_postwriter_repairs_binary_slop_and_builds_bounded_digest():
    body = "不是平台算法，也不是流量池。不是更新不够勤奋，而是AI无法读取正文。"

    repaired, evidence = _repair_ai_slop(body)
    digest = _wechat_digest("一直更新图文，GEO提及率为何不动", repaired)

    assert "不是" not in repaired
    assert evidence["changed"] is True
    assert evidence["change_count"] == 2
    assert 1 <= len(digest) <= 54


def test_prepare_wechat_professional_draft_records_wewrite_evidence(tmp_path):
    fake = _fake_wewrite(tmp_path)
    draft = {"title": "Old", "body": "short seed", "draft_meta": {}}
    job = {"id": "j1", "topic": "AI tool overload", "platforms": ["wechat"], "brief": {"audience": "operators"}}

    result = prepare_wechat_professional_draft(
        "j1",
        job,
        draft,
        {"feature_flags": {"channel_auto_workflow_gate": "enforce"}, "wechat_toolchain": {"wewrite_bin": str(fake), "timeout": 10}},
        tmp_path,
    )

    meta = result["draft_meta"]
    assert result["title"] == "Professional WeChat Title"
    assert "concrete paragraph" in result["body"]
    assert meta["tool_invocations"]["wewrite"]["status"] == "used"
    assert meta["tool_invocations"]["wewrite"]["run_id"] == "20260729-120000-abcdef"
    assert meta["preflight_manifest"]["channel"] == "wechat"
    assert len(meta["section_image_map"]) == 3
    assert meta["wechat_image_post_plan"]["required"] is True
    assert meta["wechat_image_post_plan"]["card_count_range"] == [3, 9]
    assert meta["wechat_image_post_plan"]["publish_target"] == "wechat_newspic_draft"
    assert meta["visual_content_policy"]["wechat_requirements"]["theme_count_required"] == 109
    assert Path(meta["wechat_toolchain_evidence_path"]).is_file()


def test_prepare_wechat_professional_draft_records_failure_when_required(tmp_path):
    missing = tmp_path / "missing_wewrite"
    draft = {"title": "Old", "body": "short seed", "draft_meta": {}}
    job = {"id": "j1", "topic": "AI tool overload", "platforms": ["wechat"], "brief": {}}

    result = prepare_wechat_professional_draft(
        "j1",
        job,
        draft,
        {"feature_flags": {"channel_auto_workflow_gate": "enforce"}, "wechat_toolchain": {"wewrite_bin": str(missing)}},
        tmp_path,
    )

    assert result["draft_meta"]["tool_invocations"]["wewrite"]["status"] == "failed"
    assert "not found" in result["draft_meta"]["tool_invocations"]["wewrite"]["error"]


def test_prepare_wechat_draft_uses_explicit_hermes_writer_fallback(tmp_path):
    draft = {"title": "Old", "body": "short seed", "draft_meta": {}}
    job = {"id": "j1", "topic": "AI tool overload", "platforms": ["wechat"], "brief": {}}

    result = prepare_wechat_professional_draft(
        "j1",
        job,
        draft,
        {
            "feature_flags": {"channel_auto_workflow_gate": "enforce"},
            "wechat_toolchain": {
                "wewrite_bin": str(_failing_wewrite(tmp_path)),
                "hermes_writer_fallback": True,
                "hermes_bin": str(_fake_hermes_writer(tmp_path)),
                "timeout": 10,
            },
        },
        tmp_path,
    )

    meta = result["draft_meta"]
    assert meta["tool_invocations"]["wewrite"]["status"] == "failed"
    assert meta["tool_invocations"]["hermes_writer"]["status"] == "used"
    assert meta["tool_invocations"]["hermes_writer"]["commands"][0]["name"] == "hermes --cli"
    assert result["title"] == "Hermes Writer Title"
    assert "Concrete operational guidance" in result["body"]


def test_wechat_writer_failure_cooldown_skips_known_failed_primary(tmp_path):
    cfg = {
        "feature_flags": {"channel_auto_workflow_gate": "enforce"},
        "wechat_toolchain": {
            "wewrite_bin": str(_failing_wewrite(tmp_path)),
            "hermes_writer_fallback": True,
            "hermes_bin": str(_fake_hermes_writer(tmp_path)),
            "writer_failure_cooldown_seconds": 3600,
            "timeout": 10,
        },
    }
    job = {"id": "j1", "topic": "AI tool overload", "platforms": ["wechat"], "brief": {}}
    prepare_wechat_professional_draft("j1", job, {"title": "Old", "body": "short", "draft_meta": {}}, cfg, tmp_path)

    second = prepare_wechat_professional_draft("j2", {**job, "id": "j2"}, {"title": "Old", "body": "short", "draft_meta": {}}, cfg, tmp_path)

    wewrite = second["draft_meta"]["tool_invocations"]["wewrite"]
    assert wewrite["status"] == "skipped"
    assert wewrite["reason"] == "recent_writer_provider_failure"
    assert second["draft_meta"]["tool_invocations"]["hermes_writer"]["status"] == "used"
