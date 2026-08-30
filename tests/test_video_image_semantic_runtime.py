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


def test_agnes_footage_generation_materializes_eight_verified_scene_clips(tmp_path, monkeypatch):
    scenes = [
        {"scene_id": f"s{i:02d}", "narration": f"workflow step {i}", "visual_claim": f"dashboard {i}"}
        for i in range(1, 9)
    ]

    def generate(self, prompt, output, **kwargs):
        Path(output).write_bytes(b"video" + prompt.encode())
        return {"model": "agnes-video-2.5-flash", "video_id": Path(output).stem, "source_url": "https://cdn.test/video", "license": "agnes_api_terms"}

    def run(command, **kwargs):
        Path(command[-1]).write_bytes(b"frame")
        return type("Result", (), {"returncode": 0})()

    def analyze(path, expected, **kwargs):
        sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return {
            "version": "image_semantic_evidence_v1", "passed": True, "caption": "workflow dashboard",
            "labels": ["workflow", "dashboard"], "matched_concepts": [str(expected[0])],
            "semantic_match_score": 1.0, "image_sha256": sha,
            "score_source": "deterministic_caption_label_recall", "evidence_level": "artifact_verified",
        }

    monkeypatch.setattr("content_platform.agnes_provider.AgnesVideoProvider.generate", generate)
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr("scripts.image_semantic_analyze.analyze_image", analyze)

    evidence = runner._ensure_agnes_footage(tmp_path, {"scenes": scenes}, platform="douyin_ai")

    assert evidence["passed"] is True
    assert evidence["scene_count"] == 8
    provenance = json.loads((tmp_path / "footage_provenance.json").read_text(encoding="utf-8"))
    assert len(provenance["scenes"]) == 8
    assert all(row["provider"] == "agnes" for row in provenance["scenes"])
    manifest = json.loads((tmp_path / "scene_manifest.json").read_text(encoding="utf-8"))
    assert all(scene["asset"]["provider"] == "agnes" for scene in manifest["scenes"])
