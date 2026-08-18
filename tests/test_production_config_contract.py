import json
from pathlib import Path


def test_public_production_config_inherits_active_hermes_model_and_enforces_gates():
    config = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    generator = config["generator"]
    assert generator["provider"] == "hermes-cli"
    assert generator["hermes_provider"] == ""
    assert generator["hermes_model"] == ""
    assert generator["model"] == ""
    assert generator["allow_fallback"] is False
    assert config["workflow"]["require_gate_pass"] is True
    assert config["workflow"]["require_unified_acceptance"] is True
    assert all(value == "enforce" for value in config["feature_flags"].values())
