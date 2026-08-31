from __future__ import annotations

import hashlib
import json

import pytest

from scripts import image_semantic_analyze as analyzer


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._body


def test_analyze_calls_cloudflare_vision_and_returns_strict_contract(tmp_path, monkeypatch):
    image = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG\r\nsemantic-image")
    monkeypatch.setattr(
        analyzer,
        "load_secret",
        lambda name: {
            "CLOUDFLARE_ACCOUNT_ID": "account-1",
            "CLOUDFLARE_API_TOKEN": "token-1",
        }.get(name, ""),
    )
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "success": True,
                "result": {
                    "response": '{"caption":"A cat beside a laptop","labels":["cat","computer"],"score":0.01}'
                },
            }
        )

    monkeypatch.setattr(analyzer.urllib.request, "urlopen", fake_urlopen)

    result = analyzer.analyze_image(image, ["cat", "laptop"], role="cover", platform="wechat")

    assert set(result) == {
        "version",
        "ok",
        "analyzer",
        "model",
        "caption",
        "labels",
        "expected_concepts",
        "matched_concepts",
        "semantic_match_score",
        "threshold",
        "passed",
        "output_sha256",
        "image_sha256",
        "score_source",
        "evidence_level",
    }
    assert result["ok"] is True
    assert result["passed"] is True
    assert result["semantic_match_score"] == 1.0
    assert result["matched_concepts"] == ["cat", "laptop"]
    assert result["output_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    assert captured["request"].get_header("Authorization") == "Bearer token-1"
    body = json.loads(captured["request"].data)
    assert body["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert body["messages"][0]["role"] == "user"
    prompt = body["messages"][0]["content"][1]["text"]
    assert "cover" in prompt and "wechat" in prompt
    assert body["response_format"]["type"] == "json_schema"


def test_prose_vision_response_is_captioned_and_scored_locally():
    caption, labels = analyzer._extract_model_output(
        {"success": True, "result": {"response": "A camera on a tripod inside a busy workshop."}}
    )

    score, matched = analyzer.score_semantics(["camera workshop"], caption, labels)
    assert caption.startswith("A camera")
    assert {"camera", "workshop"}.issubset(set(labels))
    assert score == 1.0
    assert matched == ["camera workshop"]


def test_compound_concept_accepts_a_visible_anchor_but_multiple_concepts_still_need_coverage():
    one_score, one_matches = analyzer.score_semantics(
        ["AI workflow dashboard"],
        "A monitor displays a dashboard with charts and graphs.",
        ["monitor", "dashboard"],
    )
    many_score, many_matches = analyzer.score_semantics(
        ["AI workflow dashboard", "developer typing code", "team collaboration"],
        "A monitor displays a dashboard with charts and graphs.",
        ["monitor", "dashboard"],
    )

    assert one_score >= analyzer.DEFAULT_THRESHOLD
    assert one_matches == ["AI workflow dashboard"]
    assert many_score < analyzer.DEFAULT_THRESHOLD
    assert many_matches == ["AI workflow dashboard"]


def test_score_is_deterministic_and_supports_multilingual_synonyms():
    score, matched = analyzer.score_semantics(
        ["人工智能", "手机", "猫"],
        "An AI assistant is shown on a smartphone screen.",
        ["technology", "feline"],
    )

    assert score == 1.0
    assert matched == ["人工智能", "手机", "猫"]


def test_visual_equivalents_ground_agent_search_and_dashboard_concepts():
    score, matched = analyzer.score_semantics(
        ["AI software agent", "connected workflow task nodes", "information retrieval search", "data analytics dashboard"],
        "A futuristic robot uses a magnifying glass beside several digital displays in a modern office.",
        ["artificial intelligence", "robot", "screen", "magnifying glass"],
    )

    assert score >= analyzer.DEFAULT_THRESHOLD
    assert "AI software agent" in matched
    assert "information retrieval search" in matched
    assert "data analytics dashboard" in matched


def test_bookshelf_documents_and_robot_assistant_ground_memory_archive():
    score, matched = analyzer.score_semantics(
        ["organized memory archive"],
        "A woman works at a desk in front of a bookshelf while a robot arm hands her a document. Books and boxes are organized behind the laptop.",
        ["bookshelf", "documents", "library", "laptop"],
    )

    assert score >= analyzer.DEFAULT_THRESHOLD
    assert matched == ["organized memory archive"]


def test_model_numeric_score_is_ignored(tmp_path, monkeypatch):
    image = tmp_path / "unrelated.jpg"
    image.write_bytes(b"not-a-real-jpeg-but-valid-test-input")
    monkeypatch.setattr(
        analyzer,
        "load_secret",
        lambda name: {"CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t"}.get(name, ""),
    )
    monkeypatch.setattr(
        analyzer.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {"result": {"caption": "A mountain landscape", "labels": ["nature"], "semantic_match_score": 1.0}}
        ),
    )

    result = analyzer.analyze_image(image, ["cat", "laptop"])

    assert result["semantic_match_score"] == 0.0
    assert result["matched_concepts"] == []
    assert result["passed"] is False


def test_main_merges_expected_json_and_repeated_expected(tmp_path, monkeypatch, capsys):
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    expected_file = tmp_path / "expected.json"
    expected_file.write_text(json.dumps({"expected_concepts": ["猫", "laptop"]}), encoding="utf-8")
    monkeypatch.setattr(
        analyzer,
        "analyze_image",
        lambda path, expected, **kwargs: analyzer.empty_result(
            path, expected, ok=True, caption="cat laptop", labels=["cat", "computer"], passed=True, score=1.0
        ),
    )

    exit_code = analyzer.main([str(image), "--expected-json", str(expected_file), "--expected", "phone, AI"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["expected_concepts"] == ["猫", "laptop", "phone", "AI"]


def test_main_returns_nonzero_and_json_when_analyzer_unavailable(tmp_path, monkeypatch, capsys):
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(analyzer, "load_secret", lambda _name: "")

    exit_code = analyzer.main([str(image), "--expected", "cat"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code != 0
    assert payload["ok"] is False
    assert payload["passed"] is False
    assert payload["output_sha256"] == hashlib.sha256(b"image").hexdigest()


@pytest.mark.parametrize("response", [{"result": {}}, {"result": {"response": "not json"}}])
def test_invalid_cloudflare_output_raises(tmp_path, monkeypatch, response):
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(
        analyzer,
        "load_secret",
        lambda name: {"CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t"}.get(name, ""),
    )
    monkeypatch.setattr(analyzer.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse(response))

    with pytest.raises(analyzer.AnalyzerError):
        analyzer.analyze_image(image, ["cat"])
