import json
from pathlib import Path

from content_platform.content_assets import compile_content_assets, load_compiled_assets


def test_compile_separates_hooks_structures_and_formulas(tmp_path: Path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps({
        "title": [{"id": "T1", "template": "结果先说"}],
        "opening": [{"id": "H1", "template": "先看结果"}],
        "ending": [{"id": "E1", "template": "留下你的证据"}],
    }), encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({
        "content_structure_gate": {"structure_pool": ["pain_reversal_tutorial"]},
        "hook_title_gate": {"allowed_hook_families": ["result_first"]},
    }), encoding="utf-8")
    out = tmp_path / "compiled"

    report = compile_content_assets(hooks, rules, out)

    assert report["passed"] is True
    assert (out / "hooks.json").is_file()
    assert (out / "structures.json").is_file()
    assert (out / "formulas.json").is_file()
    assert load_compiled_assets(out)["hooks"]["title"][0]["id"] == "T1"


def test_unverified_sources_are_not_loaded_as_production_capabilities(tmp_path: Path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps({"title": [], "opening": [], "ending": []}), encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"sources": [{"id": "x", "license": "unverified"}]}), encoding="utf-8")
    out = tmp_path / "compiled"

    report = compile_content_assets(hooks, rules, out)

    assert report["passed"] is False
    assert "unverified_source:x" in report["failures"]


def test_compiled_assets_are_rebuilt_when_source_hash_changes(tmp_path: Path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps({"title": [{"id": "T1"}], "opening": [], "ending": []}), encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({}), encoding="utf-8")
    out = tmp_path / "compiled"
    first = compile_content_assets(hooks, rules, out)
    hooks.write_text(json.dumps({"title": [{"id": "T2"}], "opening": [], "ending": []}), encoding="utf-8")
    second = compile_content_assets(hooks, rules, out)

    assert first["source_sha256"] != second["source_sha256"]
    assert load_compiled_assets(out)["hooks"]["title"][0]["id"] == "T2"
