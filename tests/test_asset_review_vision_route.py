import json

from content_platform import asset_semantic_review as review


def _config(tmp_path, **generator):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"generator": {"hermes_command": "hermes", "hermes_provider": "custom",
                                              "hermes_model": "m1", **generator}}), encoding="utf-8")
    return path


def test_route_config_prefers_declared_vision_route(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(_config(tmp_path, vision_provider="media-vision", vision_model="m1")))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    _, _, route = review.route_config()

    assert route["hermes_provider"] == "media-vision"
    assert route["billing_provider"] == "custom"


def test_route_config_without_vision_keys_keeps_text_route(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(_config(tmp_path)))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    _, _, route = review.route_config()

    assert route == {"hermes_command": "hermes", "hermes_provider": "custom", "hermes_model": "m1"}
