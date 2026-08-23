from pathlib import Path

from content_platform.skill_rule_compiler import compile_skill_rules


def test_compiler_emits_rule_ids_and_source_hash_without_absolute_paths(tmp_path: Path):
    skill = tmp_path / "skills" / "content" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Demo\n\n- Use a concrete hook\n- Show evidence\n", encoding="utf-8")

    result = compile_skill_rules([skill], root=tmp_path)

    assert result["passed"] is True
    assert result["rules"][0]["id"].startswith("skill:content/demo:")
    assert result["sources"][0]["path"] == "skills/content/demo/SKILL.md"
    assert str(tmp_path) not in str(result)


def test_compiler_ignores_archived_skill_sources(tmp_path: Path):
    skill = tmp_path / "_archive" / "old" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Old\n- Do not load\n", encoding="utf-8")

    result = compile_skill_rules([skill], root=tmp_path)

    assert result["passed"] is True
    assert result["rules"] == []
    assert result["sources"] == []
