from content_platform.asset_ledger import AssetLedger, validate_asset_set


def test_empty_asset_set_fails_closed(tmp_path):
    result = validate_asset_set([], "kuaishou", "job-1", AssetLedger(tmp_path / "asset.db"))
    assert result["passed"] is False
    assert "assets_missing" in result["failures"]
