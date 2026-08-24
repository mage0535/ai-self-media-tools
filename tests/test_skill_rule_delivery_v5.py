from unittest.mock import patch

from content_platform.capability_context import build_generation_capability_context


def test_compiled_skill_rules_retain_all_selected_rules():
    compiled = {
        "version": "compiled_skill_rules_v1",
        "sources": [{"id": "s1", "sha256": "x"}],
        "rules": [
            {"id": "r1", "source": "s1", "section": "hook", "text": "hook"},
            {"id": "r2", "source": "s1", "section": "visual", "text": "visual"},
            {"id": "r3", "source": "s1", "section": "cta", "text": "cta"},
        ],
    }
    with patch("content_platform.capability_context.compile_skill_rules", return_value=compiled):
        result = build_generation_capability_context("kuaishou", {"topic": "AI工具", "content_form": "short_video"})
    assert [row["id"] for row in result["compiled_skill_rules"]["rules"]] == ["r1", "r2", "r3"]
