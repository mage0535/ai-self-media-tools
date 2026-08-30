import hashlib
import json
from pathlib import Path

from PIL import Image

from scripts import video_toolchain_runner as runner


def _image(path: Path, color=(20, 60, 120)) -> Path:
    Image.new("RGB", (1080, 1920), color).save(path)
    return path


def _evidence(path: Path, *, passed=True) -> dict:
    return {
        "version": "image_semantic_evidence_v1",
        "analyzer": "fixture",
        "caption": "AI workflow dashboard" if passed else "cat in park",
        "labels": ["workflow", "dashboard"] if passed else ["cat", "park"],
        "expected_concepts": ["workflow"],
        "matched_concepts": ["workflow"] if passed else [],
        "semantic_match_score": 1.0 if passed else 0.0,
        "threshold": 0.6,
        "passed": passed,
        "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "score_source": "deterministic_caption_label_recall",
        "evidence_level": "artifact_verified",
    }


def test_video_assets_reuse_hash_bound_verified_semantics_without_reanalysis(tmp_path, monkeypatch):
    image = _image(tmp_path / "bg.png")
    row = {"path": str(image), "semantic_evidence": _evidence(image), "semantic_match_score": 1.0}
    monkeypatch.setattr(runner, "_analyze_background_semantics", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")))

    passed, rejected = runner._verify_materialized_semantics(
        [row], title="AI workflow", script_body="dashboard", platform="kuaishou"
    )

    assert len(passed) == 1
    assert rejected == []
    assert passed[0]["semantic_required"] is True


def test_video_assets_reanalyze_declared_scores_and_reject_mismatch(tmp_path, monkeypatch):
    image = _image(tmp_path / "bg.png")
    row = {
        "path": str(image), "source_query": "AI workflow", "semantic_match_score": 0.99,
        "match_reason": "declared match", "semantic_tags": ["workflow"],
    }
    monkeypatch.setattr(runner, "_analyze_background_semantics", lambda *_args, **_kwargs: _evidence(image, passed=False))

    passed, rejected = runner._verify_materialized_semantics(
        [row], title="AI workflow", script_body="dashboard", platform="kuaishou"
    )

    assert passed == []
    assert len(rejected) == 1
    assert rejected[0]["semantic_match_score"] == 0.0
    assert rejected[0]["match_reason"] == "cat in park"


def test_video_provenance_json_is_written_atomically(tmp_path):
    target = tmp_path / "asset_provenance.json"
    runner._write_json_atomic(target, {"version": "v1", "assets": [{"id": 1}]})

    assert json.loads(target.read_text(encoding="utf-8"))["assets"] == [{"id": 1}]
    assert not target.with_suffix(".json.tmp").exists()
