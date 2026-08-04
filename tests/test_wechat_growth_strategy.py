from pathlib import Path

from content_platform.growth_policy import build_growth_strategy, validate_growth_strategy
from content_platform.wechat_toolchain import prepare_wechat_professional_draft


def _fake_wewrite(path: Path) -> Path:
    script = path / "fake_wewrite.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args=sys.argv[1:]\n"
        "if args[:2] == ['run','start']:\n"
        "    print(json.dumps({'run_id':'20260804-120000-abcdef'})); sys.exit(0)\n"
        "if args and args[0] == 'llm-write':\n"
        "    out=args[args.index('--output')+1]\n"
        "    body='# AI效率工具别再堆了\\n\\n' + ('## Section\\nThis article gives a concrete case, a payoff, and a checklist. ' * 90)\n"
        "    open(out,'w',encoding='utf-8').write(body)\n"
        "    print(json.dumps({'ok': True, 'output': out, 'chars': len(body), 'model': 'fake'})); sys.exit(0)\n"
        "print('bad command', args, file=sys.stderr); sys.exit(2)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_wechat_growth_strategy_contains_account_specific_playbook():
    strategy = build_growth_strategy(["wechat"], "long_article")
    playbook = strategy["wechat_growth_playbook"]

    assert validate_growth_strategy(strategy, "wechat", "long_article")["passed"] is True
    assert strategy["target_user_action"] == "read_to_follow"
    assert "follow_conversion_rate" in strategy["secondary_metrics"]
    assert playbook["publishing_frequency"]["max_articles_per_day"] == 1
    assert playbook["publishing_frequency"]["recommended_articles_per_week"] == "3-4"
    assert playbook["github_selection_policy"]["default_mode"] == "weekly_bundle"
    assert len(playbook["columns"]) >= 4
    assert "工具箱" in playbook["interaction_conversion"]["backend_reply_keywords"]
    assert "AI效率工具" in playbook["seo_geo"]["primary_keywords"]


def test_wechat_toolchain_passes_growth_playbook_to_draft_meta_and_brief(tmp_path):
    fake = _fake_wewrite(tmp_path)
    draft = {"title": "Old", "body": "short seed", "draft_meta": {}}
    job = {"id": "j1", "topic": "AI工具太多怎么删", "platforms": ["wechat"], "brief": {"audience": "operators"}}

    result = prepare_wechat_professional_draft(
        "j1",
        job,
        draft,
        {"feature_flags": {"channel_auto_workflow_gate": "enforce"}, "wechat_toolchain": {"wewrite_bin": str(fake), "timeout": 10}},
        tmp_path,
    )

    meta = result["draft_meta"]
    playbook = meta["growth_strategy"]["wechat_growth_playbook"]
    brief = (tmp_path / "runtime" / "wechat_toolchain" / "j1" / "brief.md").read_text(encoding="utf-8")

    assert playbook["publishing_frequency"]["max_articles_per_day"] == 1
    assert playbook["title_rules"]["keyword_first_chars"] <= 15
    assert "WeChat growth playbook requirements" in brief
    assert "AI说人话" in brief
    assert "工具箱" in brief
