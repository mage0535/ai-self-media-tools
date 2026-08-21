from content_platform.source_quality import source_is_rankable, text_quality


def test_source_quality_rejects_mojibake_and_code():
    assert text_quality("���� AI����")["passed"] is False
    assert text_quality("var glb; typeof window")["passed"] is False


def test_source_quality_rejects_synthetic_fallback():
    assert source_is_rankable({"title": "Hypothesis", "source": "x:source_fallback", "provenance_kind": "synthetic_fallback"}) is False


def test_source_quality_accepts_clean_collected_item():
    assert source_is_rankable({"title": "AI workflow checklist", "source": "douyin", "provenance_kind": "native_platform"}) is True
