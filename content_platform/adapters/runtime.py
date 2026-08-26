"""Deterministic adapters for capabilities implemented inside this repository."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


RUNTIME_EVIDENCE_VERSION = "runtime_evidence_v1"


def probe(_capability: dict[str, Any], _inputs: dict[str, Any]) -> tuple[bool, str]:
    """The module is available statically; execution still requires evidence."""
    return True, "available"


def execute(inputs: dict[str, Any]) -> dict[str, Any]:
    capability = inputs.get("_capability") or {}
    capability_id = str(capability.get("id") or "")
    handlers = {
        "growth_strategy_latest": _growth_strategy,
        "platform_source_matrix": _platform_source_matrix,
        "performance_cycle": _performance_evidence,
        "duplication_policy": _topic_dedup,
        "content_platform.content_recipe": _content_recipe,
        "seo_geo_check": _seo_geo,
        "content_platform.video_recipe": _visual_recipe,
        "video_toolchain_runner": _video_template_plan,
        "shotcraft_moves": _shotcraft_plan,
        "voice_engine": _tts_plan,
        "lower_third_subtitle_renderer": _subtitle_plan,
        "mix_bgm_with_gate": _audio_mix_plan,
        "media_quality": _media_quality,
        "preflight_manifest": _preflight,
        "media_asset_pipeline": _media_assets,
        "pipeline_publisher": _delivery_receipt,
        "handoff_package_builder": _delivery_receipt,
    }
    handler = handlers.get(capability_id)
    if handler is None:
        return _failure(capability_id, str(capability.get("output_contract") or "runtime_evidence_v1"), "unsupported_runtime_capability")
    return handler(inputs, capability_id)


def _growth_strategy(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    from ..strategy_compiler import compile_strategy, validate_compiled_strategy

    strategy = _dict_value(inputs, "growth_strategy_evidence", "compiled_strategy", "growth_strategy")
    if not strategy and inputs.get("strategy_path"):
        strategy = compile_strategy(Path(str(inputs["strategy_path"])), str(inputs.get("platform") or ""))
    if not strategy:
        return _failure(capability_id, "compiled_strategy_v1", "missing_evidence:growth_strategy")
    gate = validate_compiled_strategy(strategy)
    if not gate["passed"]:
        return _failure(capability_id, "compiled_strategy_v1", "invalid_evidence:growth_strategy", gate["failures"])
    evidence = {key: value for key, value in strategy.items() if key != "source_path"}
    return _verified(capability_id, "compiled_strategy_v1", evidence)


def _platform_source_matrix(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    from ..trend_intelligence import build_platform_matrix

    matrix = _dict_value(inputs, "platform_source_matrix", "platform_source_evidence", "source_matrix")
    if not matrix and inputs.get("snapshot") and inputs.get("candidate"):
        matrix = build_platform_matrix(
            str(inputs.get("platform") or ""),
            inputs["snapshot"],
            inputs["candidate"],
            platform_keywords=list(inputs.get("platform_keywords") or []),
            strategy_status=inputs.get("strategy_status") or {},
        )
    if not matrix:
        return _failure(capability_id, "platform_source_matrix_v2", "missing_evidence:platform_source_matrix")
    required = ("version", "attempted_sources", "platform_internal_verified", "real_platform_collection_verified")
    if matrix.get("version") != "platform_source_matrix_v2" or not isinstance(matrix.get("attempted_sources"), list):
        return _failure(capability_id, "platform_source_matrix_v2", "invalid_evidence:platform_source_matrix")
    if any(key not in matrix for key in required):
        return _failure(capability_id, "platform_source_matrix_v2", "invalid_evidence:platform_source_matrix")
    return _verified(capability_id, "platform_source_matrix_v2", matrix)


def _performance_evidence(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    evidence = _dict_value(inputs, "performance_evidence", "account_evidence", "performance_report")
    if not evidence:
        return _failure(capability_id, "performance_evidence_v1", "missing_evidence:performance")
    if not any(key in evidence for key in ("platforms", "totals", "metrics", "samples")):
        return _failure(capability_id, "performance_evidence_v1", "invalid_evidence:performance")
    return _verified(capability_id, "performance_evidence_v1", evidence)


def _topic_dedup(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    evidence = _dict_value(inputs, "topic_dedup_evidence", "dedup_evidence", "duplication_evidence")
    if not evidence:
        return _failure(capability_id, "topic_dedup_evidence_v1", "missing_evidence:topic_dedup")
    lookback = int(evidence.get("lookback_days") or evidence.get("lookback") or 0)
    if lookback < 7 or not any(key in evidence for key in ("passed", "duplicate_found", "matches", "topic_dedup_report")):
        return _failure(capability_id, "topic_dedup_evidence_v1", "invalid_evidence:topic_dedup")
    return _verified(capability_id, "topic_dedup_evidence_v1", evidence)


def _content_recipe(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    from ..content_recipe import build_article_recipe, validate_article_recipe

    blueprint = _dict_value(inputs, "content_blueprint", "article_blueprint")
    recipe = _dict_value(inputs, "article_recipe", "recipe")
    if not recipe:
        title = str(blueprint.get("title") or blueprint.get("topic") or inputs.get("content_topic") or "").strip()
        body = str(blueprint.get("body") or inputs.get("script_text") or "").strip()
        sections = blueprint.get("sections") if isinstance(blueprint.get("sections"), list) else []
        if not title or not body:
            return _failure(capability_id, "content_recipe_v1", "missing_evidence:article_content")
        if len(sections) < 3:
            sections = [{"id": f"section_{index}", "role": role} for index, role in enumerate(("problem", "method", "proof"), 1)]
        mapping = blueprint.get("section_image_map") if isinstance(blueprint.get("section_image_map"), list) else []
        if len(mapping) < 3:
            mapping = [{"section": section.get("id") or f"section_{index}", "asset_id": f"planned_visual_{index}"} for index, section in enumerate(sections[:3], 1)]
        recipe = build_article_recipe(
            platform=str(blueprint.get("platform") or inputs.get("platform") or ""),
            content_type=str(blueprint.get("content_form") or "article"),
            title=title,
            body=body,
            sections=sections,
            section_image_map=mapping,
            embedded_knowledge_cards=blueprint.get("embedded_knowledge_cards") or [],
            visual_template_selection=blueprint.get("visual_template_selection") or {},
        )
    validation = validate_article_recipe(recipe)
    if not validation["passed"]:
        return _failure(capability_id, "content_recipe_v1", "invalid_evidence:article_recipe", validation["failures"])
    return _verified(capability_id, "content_recipe_v1", recipe)


def _seo_geo(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    from ..seo import geo_check

    blueprint = _dict_value(inputs, "content_blueprint")
    text = str(inputs.get("seo_text") or inputs.get("script_text") or blueprint.get("body") or "").strip()
    if not text:
        return _failure(capability_id, "seo_geo_v1", "missing_evidence:seo_text")
    return _verified(capability_id, "seo_geo_v1", {"text_length": len(text), "geo": geo_check(text)})


def _visual_recipe(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    from ..video_recipe import build_visual_recipe, validate_visual_recipe

    blueprint = _dict_value(inputs, "content_blueprint", "video_blueprint")
    recipe = _dict_value(inputs, "visual_recipe", "video_visual_recipe")
    if not recipe:
        plan = _dict_value(inputs, "video_plan", "video_toolchain_plan") or blueprint
        recipe = build_visual_recipe(
            plan,
            script_body=str(inputs.get("script_text") or blueprint.get("body") or ""),
            title=str(blueprint.get("title") or blueprint.get("topic") or inputs.get("content_topic") or ""),
            cinema_scenes=inputs.get("cinema_scenes") or [],
            shotcraft_plan=inputs.get("shotcraft_plan") or {},
            visual_assets=inputs.get("visual_assets") or {},
        )
    validation = validate_visual_recipe(recipe)
    if not validation["passed"]:
        return _failure(capability_id, "visual_recipe_v1", "invalid_evidence:visual_recipe", validation["failures"])
    return _verified(capability_id, "visual_recipe_v1", recipe)


def _video_template_plan(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    rendered = _dict_value(inputs, "render_manifest")
    output = Path(str(rendered.get("output") or ""))
    if rendered.get("status") == "rendered" and rendered.get("ok") is True and output.is_file():
        return _executed(capability_id, "video_template_plan_v1", rendered)
    from ..video_toolchain import build_video_toolchain_plan

    plan = _dict_value(inputs, "video_toolchain_plan", "video_template_plan")
    if not plan:
        strategy = _dict_value(inputs, "strategy", "growth_strategy_evidence")
        brief = _dict_value(inputs, "video_brief", "content_blueprint")
        if not strategy and not brief:
            return _failure(capability_id, "video_template_plan_v1", "missing_evidence:video_plan")
        plan = build_video_toolchain_plan(strategy, brief)
    if not plan.get("required") or not plan.get("selected_pipeline") or not plan.get("template_family") or not plan.get("required_tools"):
        return _failure(capability_id, "video_template_plan_v1", "invalid_evidence:video_plan")
    return _planned(capability_id, "video_template_plan_v1", plan)


def _shotcraft_plan(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    rendered = _dict_value(inputs, "render_manifest")
    observed = rendered.get("segment_motion_evidence") if isinstance(rendered.get("segment_motion_evidence"), dict) else {}
    motion = rendered.get("shotcraft_motion_plan") if isinstance(rendered.get("shotcraft_motion_plan"), dict) else {}
    if rendered.get("status") == "rendered" and motion.get("available") and len(observed.get("segments") or []) >= 3:
        return _executed(capability_id, "shotcraft_plan_v1", {"shots": observed["segments"], "motion_plan": motion})
    evidence = _dict_value(inputs, "shotcraft_plan", "shotcraft_motion_plan")
    if not evidence:
        return _failure(capability_id, "shotcraft_plan_v1", "missing_evidence:shotcraft_plan")
    shots = evidence.get("shots") or evidence.get("moves") or evidence.get("segments")
    if not isinstance(shots, list) or len(shots) < 3:
        return _failure(capability_id, "shotcraft_plan_v1", "invalid_evidence:shotcraft_plan")
    return _planned(capability_id, "shotcraft_plan_v1", evidence)


def _tts_plan(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    evidence = _dict_value(inputs, "tts_plan", "voice_plan", "tts_fingerprint")
    if not evidence:
        return _failure(capability_id, "tts_plan_v1", "missing_evidence:tts_plan")
    audio_paths = [Path(str(item.get("path") or "")) for item in inputs.get("artifacts") or [] if isinstance(item, dict) and item.get("kind") == "audio"]
    if evidence.get("sha256") and any(path.is_file() for path in audio_paths):
        return _executed(capability_id, "tts_plan_v1", evidence)
    return _planned(capability_id, "tts_plan_v1", evidence)


def _subtitle_plan(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    evidence = _dict_value(inputs, "subtitle_plan", "subtitle_evidence")
    if not evidence:
        return _failure(capability_id, "subtitle_plan_v1", "missing_evidence:subtitle_plan")
    subtitle_path = Path(str(evidence.get("path") or evidence.get("subtitle") or ""))
    if subtitle_path.is_file() and subtitle_path.stat().st_size > 0:
        return _executed(capability_id, "subtitle_plan_v1", evidence)
    return _planned(capability_id, "subtitle_plan_v1", evidence)


def _audio_mix_plan(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    evidence = _dict_value(inputs, "audio_mix_plan", "audio_mix_evidence", "bgm_plan")
    if not evidence:
        return _failure(capability_id, "audio_mix_plan_v1", "missing_evidence:audio_mix_plan")
    output = Path(str(evidence.get("output") or evidence.get("path") or ""))
    if output.is_file() and evidence.get("source_url") and evidence.get("license"):
        return _executed(capability_id, "audio_mix_plan_v1", evidence)
    return _planned(capability_id, "audio_mix_plan_v1", evidence)


def _media_quality(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    from ..media_quality import validate_article_packet, validate_video_packet

    evidence = _dict_value(inputs, "media_quality_evidence", "media_quality", "quality_evidence")
    if not evidence:
        packet = _dict_value(inputs, "media_packet", "packet")
        if packet:
            content_type = str(inputs.get("content_type") or inputs.get("content_profile", {}).get("content_format") or "")
            evidence = validate_video_packet(packet) if "video" in content_type else validate_article_packet(packet)
    if not evidence:
        return _failure(capability_id, "media_quality_v1", "missing_evidence:media_quality")
    if evidence.get("passed") is not True:
        return _failure(capability_id, "media_quality_v1", "invalid_evidence:media_quality", evidence.get("failures") or evidence.get("failed_dimensions") or [])
    return _verified(capability_id, "media_quality_v1", evidence)


def _preflight(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    from ..preflight_manifest import validate_preflight_manifest

    manifest = _dict_value(inputs, "preflight_manifest", "content_preflight_manifest")
    if manifest:
        packet = {**(_dict_value(inputs, "packet") or {}), "preflight_manifest": manifest}
        evidence = validate_preflight_manifest(packet, str(inputs.get("platform") or manifest.get("channel") or ""))
    else:
        evidence = _dict_value(inputs, "preflight_evidence")
    if not evidence:
        return _failure(capability_id, "preflight_manifest_v1", "missing_evidence:preflight_manifest")
    if evidence.get("passed") is not True:
        return _failure(capability_id, "preflight_manifest_v1", "invalid_evidence:preflight_manifest", evidence.get("failures") or [])
    return _verified(capability_id, "preflight_manifest_v1", evidence)


def _media_assets(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    verified = []
    for item in inputs.get("artifacts") or []:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        checksum = str(item.get("checksum") or "")
        if not path.is_file() or path.stat().st_size <= 0 or not checksum:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == checksum:
            verified.append({"kind": item.get("kind"), "path": str(path), "sha256": digest})
    if not verified:
        return _failure(capability_id, "media_asset_evidence_v1", "missing_evidence:verified_media_assets")
    return _executed(capability_id, "media_asset_evidence_v1", {"artifacts": verified})


def _delivery_receipt(inputs: dict[str, Any], capability_id: str) -> dict[str, Any]:
    receipt = _dict_value(inputs, "delivery_result")
    if receipt.get("ok") is not True or receipt.get("status") not in {"published", "drafted", "scheduled", "handoff_pending"} or not receipt.get("external_id"):
        return _failure(capability_id, "delivery_receipt_v1", "missing_evidence:delivery_receipt")
    return _executed(capability_id, "delivery_receipt_v1", receipt)


def _dict_value(inputs: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = inputs.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def _verified(capability_id: str, version: str, evidence: dict[str, Any]) -> dict[str, Any]:
    result = {
        "version": version,
        "status": "verified",
        "capability_id": capability_id,
        "runtime_evidence": {
            "version": RUNTIME_EVIDENCE_VERSION,
            "source": "content_platform.adapters.runtime",
            "capability_id": capability_id,
        },
        "evidence": evidence,
    }
    result.update({key: value for key, value in evidence.items() if key not in result})
    return result


def _planned(capability_id: str, version: str, evidence: dict[str, Any]) -> dict[str, Any]:
    result = _verified(capability_id, version, evidence)
    result["status"] = "planned"
    return result


def _executed(capability_id: str, version: str, evidence: dict[str, Any]) -> dict[str, Any]:
    result = _verified(capability_id, version, evidence)
    result["status"] = "executed"
    return result


def _failure(capability_id: str, version: str, reason: str, failures: Any = None) -> dict[str, Any]:
    return {
        "version": version,
        "status": "failed",
        "capability_id": capability_id,
        "reason": reason,
        "failures": [str(item) for item in (failures or [])],
        "runtime_evidence": {
            "version": RUNTIME_EVIDENCE_VERSION,
            "source": "content_platform.adapters.runtime",
            "capability_id": capability_id,
        },
        "evidence": {},
    }
