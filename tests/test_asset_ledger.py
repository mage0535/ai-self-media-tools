from pathlib import Path

from PIL import Image

from content_platform.asset_ledger import AssetLedger, validate_asset_set


def _image(path: Path, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (64, 64), color).save(path)
    return path


def _record(path: Path, score: float = 0.9) -> dict:
    sha256 = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "source_url": "https://example.test/asset",
        "license": "licensed",
        "semantic_match_score": score,
        "match_reason": "the visible subject demonstrates the narrated step",
        "semantic_tags": ["workflow", "checklist"],
        "semantic_evidence": {
            "version": "image_semantic_evidence_v1",
            "analyzer": "fixture",
            "caption": "workflow checklist",
            "labels": ["workflow", "checklist"],
            "expected_concepts": ["workflow"],
            "matched_concepts": ["workflow"],
            "semantic_match_score": score,
            "threshold": 0.55,
            "passed": score >= 0.55,
            "image_sha256": sha256,
            "score_source": "deterministic_caption_label_recall",
            "evidence_level": "artifact_verified",
        },
    }


def test_asset_gate_rejects_internal_duplicate(tmp_path: Path) -> None:
    asset = _image(tmp_path / "a.png", (20, 40, 60))
    ledger = AssetLedger(tmp_path / "ledger.db")
    result = validate_asset_set([_record(asset), _record(asset)], "tiktok", "work-1", ledger)
    assert result["passed"] is False
    assert "within_work_exact_duplicate" in result["failures"]


def test_asset_gate_rejects_cross_platform_reuse(tmp_path: Path) -> None:
    asset = _image(tmp_path / "a.png", (20, 40, 60))
    ledger = AssetLedger(tmp_path / "ledger.db")
    first = validate_asset_set([_record(asset)], "youtube", "work-1", ledger, register=True)
    second = validate_asset_set([_record(asset)], "tiktok", "work-2", ledger)
    assert first["passed"] is True
    assert second["passed"] is False
    assert "cross_platform_exact_duplicate" in second["failures"]


def test_asset_gate_rejects_weak_semantic_match_and_missing_license(tmp_path: Path) -> None:
    asset = _image(tmp_path / "a.png", (80, 10, 10))
    record = _record(asset, score=0.4)
    record["license"] = ""
    result = validate_asset_set([record], "tiktok", "work-1", AssetLedger(tmp_path / "ledger.db"))
    assert "semantic_match_below_threshold" in result["failures"]
    assert "asset_license_missing" in result["failures"]


def test_asset_gate_registers_unique_assets_only_after_pass(tmp_path: Path) -> None:
    first = _image(tmp_path / "a.png", (0, 0, 0))
    second = _image(tmp_path / "b.png", (255, 255, 255))
    ledger = AssetLedger(tmp_path / "ledger.db")
    result = validate_asset_set([_record(first), _record(second)], "tiktok", "work-1", ledger, register=True)
    assert result["passed"] is True
    assert len(ledger.uses()) == 2
