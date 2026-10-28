from unittest.mock import patch

import pytest

from content_platform.media import MediaBridge


def test_knowledge_route_does_not_render_the_fixed_demo_card_deck(tmp_path):
    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j1", "title": "AI Agent 之 用户记忆和知识库", "body": "正文", "platforms": ["juejin"],
           "visual_route": {"auto": True, "route_order": ["content-driven-cards"]}}

    with patch("subprocess.run") as run, patch.object(bridge.registry, "choose_provider", return_value=None):
        with pytest.raises(FileNotFoundError, match="image script not configured"):
            bridge._generate_image(job, tmp_path / "out", {})

    run.assert_not_called()
    assert not (tmp_path / "out" / "cards").exists()
