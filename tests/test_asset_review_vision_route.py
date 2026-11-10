import json

import pytest

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


def test_task_role_is_checked_against_the_text_route_when_vision_is_declared(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(_config(tmp_path, vision_provider="media-vision", vision_model="m1")))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    role = tmp_path / "node-role.json"
    role.write_text(json.dumps({"route": {"provider": "custom", "model": "m1"}}), encoding="utf-8")

    assert review.route_config()[2]["hermes_provider"] == "media-vision"

    role.write_text(json.dumps({"route": {"provider": "other", "model": "m1"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="task_profile_route_mismatch"):
        review.route_config()


def _stream(text, model="m1"):
    events = [{"type": "system", "subtype": "init", "model": model, "session_id": "s1"},
              {"type": "result", "exit_code": 0, "text": text}]
    return "\n".join(json.dumps(e) for e in events)


def test_parse_response_accepts_one_markdown_fence_only():
    value, session = review.parse_response(_stream('```json\n{"score": 0.8}\n```'), "m1")
    assert value == {"score": 0.8} and session == "s1"
    with pytest.raises(ValueError):
        review.parse_response(_stream('note ```json\n{"score": 0.8}\n```'), "m1")


def _review_with(tmp_path, monkeypatch, calls, outcomes, **generator):
    from types import SimpleNamespace
    from PIL import Image

    monkeypatch.setattr(review, "_PRIMARY_DOWN_UNTIL", {})

    monkeypatch.setenv("CONTENT_PLATFORM_CONFIG", str(_config(tmp_path, vision_provider="media-vision", vision_model="m1",
                                                              **generator)))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(review, "verify_session", lambda session, route, path: {"route": route})
    monkeypatch.setattr(review, "session_database", lambda *args: None)
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 64), (120, 30, 200)).save(image)

    def invoke(command, **kwargs):
        model = command[command.index("--model") + 1]
        calls.append(model)
        outcome = outcomes[model]
        if isinstance(outcome, Exception):
            raise outcome
        code, text = outcome
        return SimpleNamespace(returncode=code, stdout=_stream(text, model), stderr="")

    return review.review_asset(image, "topic", "section", invoke=invoke, check_native=lambda route: "native")


GOOD = '{"score": 0.8, "reason": "r", "observed_subject": "s", "topic_relation": "t", "image_observed": true}'


def test_a_failed_primary_review_is_asked_once_on_the_declared_fallback(tmp_path, monkeypatch):
    # MED79: the single gateway account answered 503; the review moves to a declared non-Google route.
    calls = []
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": (1, ""), "m2": (0, GOOD)},
                         vision_fallback_provider="vision-fallback", vision_fallback_model="m2")

    assert calls == ["m1", "m2"] and audit["status"] == "evaluated" and audit["fallback_raw_score"] == 0.8
    assert audit["route"]["model"] == "m2" and audit["fallback_from"]["model"] == "m1"
    assert "hermes_pixel_review_exit_1" in audit["fallback_from"]["error"]


def test_a_low_score_is_not_asked_again_and_no_fallback_means_one_call(tmp_path, monkeypatch):
    calls = []
    low = GOOD.replace("0.8", "0.5")
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": (0, low), "m2": (0, GOOD)},
                         vision_fallback_provider="vision-fallback", vision_fallback_model="m2")
    assert calls == ["m1"] and audit["score"] == 0.5 and "fallback_from" not in audit

    calls.clear()
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": (1, "")})
    assert calls == ["m1"] and audit["status"] == "failed"


def test_a_timed_out_primary_review_moves_to_the_fallback(tmp_path, monkeypatch):
    import subprocess

    calls = []
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": subprocess.TimeoutExpired("hermes", 90), "m2": (0, GOOD)},
                         vision_fallback_provider="vision-fallback", vision_fallback_model="m2")
    assert calls == ["m1", "m2"] and audit["status"] == "evaluated" and "TimeoutExpired" in audit["fallback_from"]["error"]


def test_after_a_primary_failure_the_next_review_goes_straight_to_the_fallback(tmp_path, monkeypatch):
    import subprocess

    calls = []
    outcomes = {"m1": subprocess.TimeoutExpired("hermes", 90), "m2": (0, GOOD)}
    generator = {"vision_fallback_provider": "vision-fallback", "vision_fallback_model": "m2"}
    _review_with(tmp_path, monkeypatch, calls, outcomes, **generator)
    down = dict(review._PRIMARY_DOWN_UNTIL)
    monkeypatch.setattr(review, "_PRIMARY_DOWN_UNTIL", down)
    from types import SimpleNamespace
    from PIL import Image
    image = tmp_path / "b.png"
    Image.new("RGB", (64, 64), (20, 160, 90)).save(image)

    def invoke(command, **kwargs):
        model = command[command.index("--model") + 1]
        calls.append(model)
        return SimpleNamespace(returncode=0, stdout=_stream(GOOD, model), stderr="")

    audit = review.review_asset(image, "topic", "section", invoke=invoke, check_native=lambda route: "native")
    assert calls == ["m1", "m2", "m2"] and audit["route"]["model"] == "m2"
    assert audit["fallback_from"]["error"] == "primary_skipped_after_recent_failure"


def test_a_fallback_score_below_the_fallback_bar_is_capped_under_the_gate(tmp_path, monkeypatch):
    # MED84 calibration: the fallback passed 0.75 / 0.85 where Gemini failed; its pass needs >= 0.85.
    calls = []
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": (1, ""), "m2": (0, GOOD)},
                         vision_fallback_provider="vision-fallback", vision_fallback_model="m2")
    assert audit["route"]["model"] == "m2" and audit["score"] == 0.71 and audit["fallback_raw_score"] == 0.8
    calls.clear()
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": (1, ""), "m2": (0, GOOD.replace("0.8", "0.9"))},
                         vision_fallback_provider="vision-fallback", vision_fallback_model="m2")
    assert audit["score"] == 0.9 and "fallback_raw_score" not in audit
    calls.clear()
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": (0, GOOD)},
                         vision_fallback_provider="vision-fallback", vision_fallback_model="m2")
    assert audit["route"]["model"] == "m1" and audit["score"] == 0.8 and "fallback_raw_score" not in audit


def test_parse_response_maps_python_literals_only_in_value_positions():
    # MED84: Cloudflare mistral-small answered '"image_observed":True'.
    value, _ = review.parse_response(_stream('{"score": 0.85, "reason": "said True, ok", "image_observed":True}'), "m1")
    assert value == {"score": 0.85, "reason": "said True, ok", "image_observed": True}
    value, _ = review.parse_response(_stream('{"a": [False, None], "b": 1}'), "m1")
    assert value == {"a": [False, None], "b": 1}
    for bad in ('{"score": 0.8, "image_observed": Yes}', '{"score": 0.8,}', 'score 0.8 True'):
        with pytest.raises(ValueError):
            review.parse_response(_stream(bad), "m1")


def test_a_failing_fallback_while_the_primary_is_skipped_falls_back_to_the_primary(tmp_path, monkeypatch):
    # MED84: primary marked down, fallback broken -> the primary is still asked instead of failing the review.
    calls = []
    audit = _review_with(tmp_path, monkeypatch, calls, {"m1": (0, GOOD), "m2": (1, "")},
                         vision_fallback_provider="vision-fallback", vision_fallback_model="m2")
    assert calls == ["m1"]
    review._PRIMARY_DOWN_UNTIL["m1"] = 10 ** 12
    from types import SimpleNamespace
    from PIL import Image
    image = tmp_path / "c.png"
    Image.new("RGB", (64, 64), (200, 160, 90)).save(image)

    def invoke(command, **kwargs):
        model = command[command.index("--model") + 1]
        calls.append(model)
        return SimpleNamespace(returncode=0 if model == "m1" else 1, stdout=_stream(GOOD, model) if model == "m1" else "",
                               stderr="")

    audit = review.review_asset(image, "topic", "section", invoke=invoke, check_native=lambda route: "native")
    assert calls == ["m1", "m2", "m1"] and audit["status"] == "evaluated" and audit["route"]["model"] == "m1"
    assert audit["fallback_from"]["model"] == "m2"

