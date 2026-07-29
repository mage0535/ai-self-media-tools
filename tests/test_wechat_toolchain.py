import json
from pathlib import Path

from content_platform.wechat_toolchain import prepare_wechat_professional_draft, requires_wechat_toolchain


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


def test_requires_wechat_toolchain_only_for_enforced_wechat():
    assert requires_wechat_toolchain({"feature_flags": {"channel_auto_workflow_gate": "enforce"}}, ["wechat"])
    assert not requires_wechat_toolchain({"feature_flags": {"channel_auto_workflow_gate": "enforce"}}, ["devto"])
    assert not requires_wechat_toolchain({}, ["wechat"])


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
