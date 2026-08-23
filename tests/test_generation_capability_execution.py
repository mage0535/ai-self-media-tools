from content_platform.capability_runtime import execute_generation_capabilities


def test_generation_capabilities_execute_structure_after_draft():
    result = execute_generation_capabilities(
        {"title": "结果先说", "body": "很多人第一步就错了。真正的问题在于证据。按这三个步骤解决。"},
        {"content_profile": {"content_format": "article"}},
    )
    assert result["passed"] is True
    assert result["executed"][0]["status"] == "executed"
    assert result["executed"][0]["output_hash"].startswith("sha256:")
