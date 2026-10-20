"""Fail-closed policy for real-world AI application content."""
from __future__ import annotations

import json
import random
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "real_world_ai_implementation_v1.json"


def load_real_world_ai_positioning() -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("policy_profile") != "real_world_ai_implementation_v1":
        raise ValueError("invalid real-world AI positioning profile")
    if not str(policy.get("policy_revision") or "").strip():
        raise ValueError("real-world AI positioning revision is missing")
    return policy


def is_real_world_ai_context(payload: dict[str, Any] | None) -> bool:
    """Return true only when the caller explicitly binds the canonical AI lane.

    A platform name is transport/routing metadata, not an account-lane identity.
    Inferring the lane from ``wechat``/``zhihu`` would contaminate non-AI jobs
    that share the same publisher. Production AI jobs must carry the canonical
    lane/profile through the workflow context.
    """
    data = payload if isinstance(payload, dict) else {}
    policy = load_real_world_ai_positioning()
    accepted = {"real_world_ai_implementation", str(policy["policy_profile"])}
    values = {
        str(data.get("lane") or "").strip(),
        str(data.get("policy_profile") or "").strip(),
    }
    for key in ("positioning", "real_world_ai_positioning", "workflow_context"):
        nested = data.get(key)
        if not isinstance(nested, dict):
            continue
        values.update(
            {
                str(nested.get("lane") or "").strip(),
                str(nested.get("policy_profile") or "").strip(),
            }
        )
        positioning = nested.get("positioning")
        if isinstance(positioning, dict):
            values.update(
                {
                    str(positioning.get("lane") or "").strip(),
                    str(positioning.get("policy_profile") or "").strip(),
                }
            )
    return bool(values & accepted)


def _terms_for_language(terms: list[str], language: str) -> list[str]:
    wants_zh = str(language or "zh").casefold().startswith("zh")
    selected = [term for term in terms if bool(re.search(r"[\u4e00-\u9fff]", term)) == wants_zh]
    return selected or terms


def build_discovery_queries(*, seed: str | None = None, language: str = "zh") -> list[str]:
    """Build one policy-bound discovery query per pillar.

    Query wording may rotate, but every query contains an AI capability, one
    concrete scene, and one result/case signal from the canonical contract.
    """
    policy = load_real_world_ai_positioning()
    contract = policy.get("discovery_query_contract") or {}
    if contract.get("required_groups") != [
        "ai_capability_terms", "pillar_terms", "outcome_case_terms"
    ]:
        raise ValueError("invalid real-world AI discovery query contract")
    capabilities = _terms_for_language(
        [str(value) for value in policy.get("ai_capability_terms") or []], language
    )
    outcomes = _terms_for_language(
        [str(value) for value in policy.get("outcome_case_terms") or []], language
    )
    pillars = policy.get("pillars") or {}
    if not capabilities or not outcomes or not pillars:
        raise ValueError("real-world AI discovery terms are incomplete")
    rng = random.Random(seed or date.today().isoformat())
    queries: list[str] = []
    for pillar, raw_terms in pillars.items():
        terms = _terms_for_language([str(value) for value in raw_terms or []], language)
        if not terms:
            raise ValueError(f"real-world AI pillar has no terms: {pillar}")
        capability = rng.choice(capabilities)
        scene = rng.choice(terms)
        outcome = rng.choice(outcomes)
        queries.append(f"{capability} {scene} {outcome}")
    return queries


def _contains(text: str, terms: list[str]) -> list[str]:
    haystack = str(text or "").casefold()
    found = []
    for term in terms:
        needle = str(term).casefold()
        if not needle:
            continue
        left = r"(?<![a-z0-9_])" if re.match(r"[a-z0-9_]", needle) else ""
        right = r"(?![a-z0-9_])" if re.search(r"[a-z0-9_]$", needle) else ""
        if re.search(left + re.escape(needle) + right, haystack):
            found.append(term)
    return found


def validate_native_semantic_discovery(value, candidates, *, control_id, source_bundle_sha256, rules_sha256, source_eligibility=False):
    """Validate a native model's decision data; this pure function grants no Native qualification."""
    import hashlib
    expected = {'version', 'control_id', 'source_bundle_sha256', 'rules_sha256', 'reviews'}
    if (not isinstance(value, dict) or set(value) != expected
            or value.get('version') != ('native_semantic_discovery_v2' if source_eligibility is True else 'native_semantic_discovery_v1')
            or value.get('control_id') != control_id or value.get('source_bundle_sha256') != source_bundle_sha256
            or value.get('rules_sha256') != rules_sha256 or not isinstance(candidates, list) or not candidates):
        raise ValueError('semantic_discovery_current_scope_required')
    sources = {}
    for candidate in candidates:
        required = {'content_id', 'author', 'source_text', 'source_text_sha256', 'raw_response_sha256'}
        if (not isinstance(candidate, dict) or not required <= set(candidate)
                or any(not isinstance(candidate.get(k), str) or not candidate[k] for k in required)
                or candidate['content_id'] in sources
                or hashlib.sha256(candidate['source_text'].encode()).hexdigest() != candidate['source_text_sha256']
                or not re.fullmatch(r'[a-f0-9]{64}', candidate['raw_response_sha256'])):
            raise ValueError('semantic_discovery_original_source_identity')
        sources[candidate['content_id']] = candidate
    reviews = value['reviews']
    if (not isinstance(reviews, list) or len(reviews) != len(candidates)
            or any(not isinstance(row, dict) for row in reviews)
            or [row.get('content_id') for row in reviews] != list(sources)):
        raise ValueError('semantic_discovery_complete_unique_ordered_pool_required')
    policy = load_real_world_ai_positioning()
    pillars = set(policy.get('pillars') or {})
    span_keys = {'ai_capability', 'actor', 'inputs', 'steps', 'outputs', 'boundaries', 'human_handoff', 'benefit'}
    measure_keys = {'baseline', 'measurement_method', 'sample_or_period'}
    review_keys = {'content_id', 'author', 'source_text_sha256', 'raw_response_sha256', 'pillar', 'case_kind',
                   'primary_tasks', 'outcome_status', 'evidence_spans', 'measured_evidence', 'reason'}
    decisions = []
    for row in reviews:
        source = sources[row['content_id']]
        if (set(row) != review_keys or any(row.get(k) != source[k] for k in ('author', 'source_text_sha256', 'raw_response_sha256'))
                or (row['pillar'] is not None and not isinstance(row['pillar'], str)) or row['pillar'] not in pillars | {None}
                or not isinstance(row['case_kind'], str) or row['case_kind'] not in ({'author_applied_workflow', 'quoted_case', 'model_news', 'generic_advice', 'unknown', 'concrete_proposed_workflow'} if source_eligibility is True else {'author_applied_workflow', 'quoted_case', 'model_news', 'generic_advice', 'unknown'})
                or (row['outcome_status'] is not None and not isinstance(row['outcome_status'], str)) or row['outcome_status'] not in {'measured', 'hypothesis', 'verification_required', None}
                or not isinstance(row['reason'], str) or not row['reason'].strip()
                or not isinstance(row['evidence_spans'], dict) or set(row['evidence_spans']) != span_keys
                or not isinstance(row['measured_evidence'], dict) or set(row['measured_evidence']) != measure_keys):
            raise ValueError('semantic_discovery_exact_review_or_source_required')
        groups = [row['primary_tasks'], *row['evidence_spans'].values(), *row['measured_evidence'].values()]
        if any(not isinstance(spans, list)
               or any(not isinstance(span, str) or len(span) < 12 or span not in source['source_text'] for span in spans)
               or len(spans) != len(set(spans))
               for spans in groups):
            raise ValueError('semantic_discovery_exact_original_quote_required')
        reasons = []
        if row['case_kind'] not in ({'author_applied_workflow','quoted_case','concrete_proposed_workflow'}if source_eligibility is True else {'author_applied_workflow'}):
            reasons.append('not_source_author_applied_workflow')
        if len(row['primary_tasks']) != 1:
            reasons.append('single_primary_task_required')
        if row['pillar'] not in pillars:
            reasons.append('canonical_application_pillar_required')
        if source_eligibility is True:
            facts=row['evidence_spans']
            if not facts['ai_capability']or not any(facts[k]for k in('inputs','steps','outputs')):
                reasons.append('source_grounded_AI_task_or_implementation_detail_missing')
            if row['case_kind']=='concrete_proposed_workflow'and row['outcome_status']=='measured':
                reasons.append('proposed_workflow_is_not_an_observed_measured_result')
        elif any(not spans for spans in row['evidence_spans'].values()) or len(row['evidence_spans']['steps']) < 2:
            reasons.append('source_grounded_operational_flow_or_handoff_missing')
        if row['outcome_status'] is None:
            reasons.append('explicit_outcome_status_required')
        if row['outcome_status'] == 'measured':
            benefit = ' '.join(row['evidence_spans']['benefit']).casefold()
            speculative = re.search(r'\b(?:could|might|may|would)\b|假设|预计|可能', benefit)
            if speculative or not row['evidence_spans']['benefit']or any(not spans for spans in row['measured_evidence'].values()):
                reasons.append('measured_benefit_requires_original_measurement_not_hypothesis')
        decisions.append({'content_id': row['content_id'], 'accepted': not reasons, 'reasons': reasons,
                          'pillar': row['pillar'], 'outcome_status': row['outcome_status'],
                          'policy_profile': policy['policy_profile'], 'policy_revision': policy['policy_revision'],
                          'candidate_case_only_not_viral_evidence': True,
                          'evidence_level': 'attributed_external_source_not_our_observed_result'})
        if source_eligibility is True:
            decisions[-1].update(source_eligibility_mode='native_source_facts_v2',case_kind=row['case_kind'],
                observed_source_spans=row['evidence_spans'],unobserved_source_fields=[k for k,v in row['evidence_spans'].items()if not v],
                source_author_is_implementation_actor=row['case_kind']=='author_applied_workflow',
                own_implementation_or_benefit_verified=False,final_complete_scenario_and_current_quality_required=True)
    accepted = next((row['content_id'] for row in decisions if row['accepted']), None)
    return {'selected_content_id': accepted, 'decisions': decisions}


def classify_discovery_text(title: str, summary: str = "") -> dict[str, Any]:
    """Accept only an AI capability tied to one allowed real-world scene."""
    policy = load_real_world_ai_positioning()
    text = f"{title} {summary}".strip()
    lowered = text.casefold()
    excluded_shapes = (
        r"(?:十大|十款|top\s*\d*)?\s*工具(?:清单|合集|大全|推荐)",
        r"prompt\s*(?:合集|清单|大全|collection|library)",
        r"(?:行业新闻|新闻速递|行业快讯|资讯速递)",
    )
    if any(re.search(pattern, lowered) for pattern in excluded_shapes):
        return {"accepted": False, "reason": "excluded_tool_prompt_or_industry_news"}
    excluded = _contains(text, list(policy.get("excluded_terms") or []))
    if excluded:
        return {"accepted": False, "reason": "excluded_model_news_or_ranking"}
    capability = _contains(text, list(policy.get("ai_capability_terms") or []))
    if not capability:
        return {"accepted": False, "reason": "ai_capability_missing"}
    outcomes = _contains(text, list(policy.get("outcome_case_terms") or []))
    if not outcomes and re.search(r"(?:交给\S{1,8}|人工|工程师|专员|主管|医生|教师|操作员|质检员)复核", text):
        outcomes = ["human_review_signal"]
    case_evidence = None
    if not outcomes:
        # A demonstrated input-to-deliverable workflow is a case clue, not a measured outcome.
        implementation = re.search(
            r"构建|搭建|演示|实测|自己做|我(?:自己)?做|手把手(?:教学|教你)|\b(?:built|demo|demonstration|walkthrough|prototype)\b",
            text, re.IGNORECASE,
        )
        inputs = re.search(r"上传|导入|输入|读取|查询|接入|\b(?:upload|import|input|read|query|connect)\b", text, re.IGNORECASE)
        delivery = re.search(r"生成|导出|写入|写进|输出|推送|保存|\b(?:generate|export|write|output|save|deliver)\b", text, re.IGNORECASE)
        deliverable = re.search(r"分析报告|审查意见(?:书)?|报告|趋势图(?:表)?|图表|手机日历|日历|文档|清稿|修订稿|\b(?:word|report|chart|calendar|document)\b", text, re.IGNORECASE)
        if not all((implementation, inputs, delivery, deliverable)):
            return {"accepted": False, "reason": "outcome_or_case_signal_missing"}
        case_evidence = {
            "implementation_clue": implementation.group(0),
            "input_or_lookup": inputs.group(0),
            "delivery_operation": delivery.group(0),
            "deliverable": deliverable.group(0),
        }
    matched_pillars = {
        pillar: _contains(text, list(terms or []))
        for pillar, terms in (policy.get("pillars") or {}).items()
    }
    matched_pillars = {pillar: terms for pillar, terms in matched_pillars.items() if terms}
    # Some canonical concepts intentionally appear in two pillars (for example
    # equipment maintenance bridges industrial operations and intelligent
    # manufacturing). A single shared term is not semantic ambiguity; two or
    # more distinct scene concepts are and require review.
    distinct_scene_terms = {
        str(term).casefold()
        for terms in matched_pillars.values()
        for term in terms
    }
    matched_names = set(matched_pillars)
    adjacent_manufacturing = matched_names <= {
        "industrial_application", "intelligent_manufacturing"
    }
    if len(matched_pillars) > 1 and len(distinct_scene_terms) > 1 and not adjacent_manufacturing:
        return {
            "accepted": False,
            "review_required": True,
            "reason": "multiple_application_scenes_require_review",
            "matched_pillars": list(matched_pillars),
        }
    if matched_pillars:
        pillar, matched = max(
            matched_pillars.items(),
            key=lambda item: (max((len(str(term)) for term in item[1]), default=0), len(item[1])),
        )
        result = {
            "accepted": True,
            "pillar": pillar,
            "ai_capability_terms": capability,
            "scenario_terms": matched,
            "outcome_case_terms": outcomes,
            "policy_profile": policy["policy_profile"],
            "policy_revision": policy["policy_revision"],
        }
        if case_evidence is not None:
            result.update(
                discovery_only=True, outcome_status="verification_required",
                independent_semantic_verified=False, generation_ready=False,
                case_evidence=case_evidence,
            )
        return result
    return {"accepted": False, "reason": "concrete_application_scene_missing"}


def validate_real_world_ai_package(package: dict[str, Any] | None) -> dict[str, Any]:
    """Validate publishable scenario metadata; missing proof fails closed."""
    payload = package if isinstance(package, dict) else {}
    failures: list[str] = []
    if payload.get("policy_profile") != "real_world_ai_implementation_v1":
        failures.append("policy_profile_missing")
    if payload.get("scenario_count") != 1:
        failures.append("scenario_count_must_equal_one")
    scenario = payload.get("scenario") if isinstance(payload.get("scenario"), dict) else {}
    policy = load_real_world_ai_positioning()
    if scenario.get("domain") not in set((policy.get("pillars") or {})):
        failures.append("domain_out_of_scope")
    actor = scenario.get("actor") if isinstance(scenario.get("actor"), dict) else {}
    if not str(actor.get("role") or "").strip() or not str(actor.get("context") or "").strip():
        failures.append("actor_generic_or_missing")
    inputs = scenario.get("inputs")
    if not isinstance(inputs, list) or not inputs or any(not isinstance(row, dict) or not all(str(row.get(k) or "").strip() for k in ("type", "source", "example_or_schema")) for row in inputs):
        failures.append("input_missing_or_abstract")
    process = scenario.get("process") if isinstance(scenario.get("process"), dict) else {}
    steps = process.get("steps")
    if not isinstance(steps, list) or len(steps) < 2 or any(not isinstance(row, dict) or not all(str(row.get(k) or "").strip() for k in ("action", "ai_function", "output")) for row in steps):
        failures.append("process_missing_or_nonoperational")
    outcome = scenario.get("outcome") if isinstance(scenario.get("outcome"), dict) else {}
    valid_outcome = all(str(outcome.get(k) or "").strip() for k in ("deliverable", "measurement_method", "value_or_verification")) and outcome.get("status") in set(policy["content_contract"]["outcome_statuses"])
    if not valid_outcome:
        failures.append("outcome_unverifiable")
    status = outcome.get("status")
    if status == "measured" and not all(
        str(outcome.get(key) or "").strip()
        for key in ("source", "baseline", "metric", "measurement_method", "sample_or_period")
    ):
        failures.append("measured_outcome_evidence_missing")
    if status == "hypothesis" and not all(
        str(outcome.get(key) or "").strip() for key in ("assumption", "verification_plan")
    ):
        failures.append("hypothesis_contract_missing")
    if status == "verification_required" and not all(
        str(outcome.get(key) or "").strip() for key in ("responsible_role", "verification_action")
    ):
        failures.append("verification_responsibility_missing")
    boundaries = scenario.get("boundaries")
    if not isinstance(boundaries, list) or not boundaries or any(not isinstance(row, dict) or not str(row.get("detail") or "").strip() for row in boundaries):
        failures.append("boundary_missing")
    handoff = scenario.get("human_handoff") if isinstance(scenario.get("human_handoff"), dict) else {}
    if not all(str(handoff.get(k) or "").strip() for k in ("trigger", "responsible_role", "review_or_action", "acceptance_or_escalation_rule")):
        failures.append("human_handoff_missing")
    return {"passed": not failures, "failures": failures}
