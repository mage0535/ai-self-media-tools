from content_platform.capability_catalog import build_capability_catalog, validate_capability_catalog


def test_catalog_keeps_legacy_tools_discoverable_without_making_them_executable():
    catalog = build_capability_catalog(
        {"capabilities": []},
        legacy_groups={"tts": ["voice_engine"], "quality_gate": ["visual_gate"]},
        mcp_servers=["content-platform"],
        skill_paths=["content/content-hooks/SKILL.md", "_archive/old/SKILL.md"],
    )

    by_id = {item["id"]: item for item in catalog["capabilities"]}
    assert "voice_engine" in by_id
    assert by_id["voice_engine"]["lifecycle"] == "inventory_only"
    assert "mcp:content-platform" in by_id
    assert by_id["mcp:content-platform"]["source"] == "mcp"
    assert "_archive/old/SKILL.md" not in by_id
    assert validate_capability_catalog(catalog)["passed"] is True


def test_catalog_rejects_executable_entry_without_adapter_or_gate():
    catalog = {
        "version": "capability_catalog_v1",
        "capabilities": [{"id": "broken", "lifecycle": "executable", "adapter": "", "quality_gate": ""}],
    }

    result = validate_capability_catalog(catalog)
    assert result["passed"] is False
    assert "broken.adapter_missing" in result["failures"]
    assert "broken.quality_gate_missing" in result["failures"]
