import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from content_platform import mcp_server
from content_platform.pipeline import Pipeline
from content_platform.run_contract import build_run_contract
from content_platform.store import Store


def _pipeline(tmp_path: Path) -> tuple[Pipeline, Store]:
    store = Store(tmp_path / "state.db")
    store.init()
    return Pipeline(store, {"data_dir": str(tmp_path)}), store


def test_production_automated_job_without_run_contract_is_rejected(tmp_path, monkeypatch):
    pipeline, store = _pipeline(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")

    with pytest.raises(ValueError, match="run_contract.missing"):
        pipeline.create("topic", ["kuaishou"], {"automated_workflow": True})

    assert store.list_jobs(limit=10) == []


def test_production_automated_job_rejects_contract_for_another_platform(tmp_path, monkeypatch):
    pipeline, store = _pipeline(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")
    brief = {
        "automated_workflow": True,
        "run_contract": build_run_contract("wechat"),
    }

    with pytest.raises(ValueError, match="run_contract.platform_mismatch"):
        pipeline.create("topic", ["kuaishou"], brief)

    assert store.list_jobs(limit=10) == []


def test_production_run_rejects_legacy_automated_job_without_contract(tmp_path, monkeypatch):
    pipeline, store = _pipeline(tmp_path)
    job = pipeline.create("legacy topic", ["kuaishou"], {"automated_workflow": True})
    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")

    with pytest.raises(ValueError, match="run_contract.missing"):
        pipeline.run(job["id"])

    assert store.get_job(job["id"])["state"] == "created"


def test_mcp_create_job_compiles_single_platform_automated_contract(tmp_path):
    home = tmp_path / "runtime"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    config = home / "config.json"
    config.write_text(json.dumps({"data_dir": str(data)}), encoding="utf-8")

    with patch.dict(
        "os.environ",
        {
            "CONTENT_PLATFORM_HOME": str(home),
            "CONTENT_PLATFORM_CONFIG": str(config),
            "CONTENT_PLATFORM_DATA_DIR": str(data),
            "HOME": str(home),
            "USERPROFILE": str(home),
        },
        clear=True,
    ):
        tools = {name: handler for handler, name, _, _ in mcp_server._tools()}
        result = asyncio.run(tools["create_job"]("MCP topic", "kuaishou", "{}"))

    saved = Store(data / "state.db").get_job(result["job_id"])
    assert saved["brief"]["automated_workflow"] is True
    assert saved["brief"]["run_contract"]["platform"] == "kuaishou"


def test_mcp_create_job_rejects_multiple_platforms(tmp_path):
    home = tmp_path / "runtime"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    config = home / "config.json"
    config.write_text(json.dumps({"data_dir": str(data)}), encoding="utf-8")

    with patch.dict(
        "os.environ",
        {
            "CONTENT_PLATFORM_HOME": str(home),
            "CONTENT_PLATFORM_CONFIG": str(config),
            "CONTENT_PLATFORM_DATA_DIR": str(data),
            "HOME": str(home),
            "USERPROFILE": str(home),
        },
        clear=True,
    ):
        tools = {name: handler for handler, name, _, _ in mcp_server._tools()}
        with pytest.raises(ValueError, match="exactly one platform"):
            asyncio.run(tools["create_job"]("MCP topic", "wechat,kuaishou", "{}"))
