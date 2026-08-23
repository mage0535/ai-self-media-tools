import pytest

from content_platform.generator import DraftGenerator


def test_automated_workflow_rejects_fixed_model():
    with pytest.raises(ValueError, match="active Hermes model"):
        DraftGenerator({"automated_workflow": True, "hermes_model": "fixed-test-model"}).generate(
            "AI workflow", {"platforms": ["wechat"]}
        )
