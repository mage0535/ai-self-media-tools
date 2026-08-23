from scripts.video_script_gate import validate_script


def test_validate_script_includes_structure_match_evidence():
    script = """很多人第一步就做错了，导致结果不稳定。

真正的问题在于没有检查证据。

按这三个步骤修复，最后把清单收藏起来。"""
    result = validate_script(script)
    assert "structure_match" in result["checks"]
    assert result["checks"]["structure_match"]["matched_structure"]
    assert result["checks"]["structure_match"]["passed"] is True
