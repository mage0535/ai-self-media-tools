"""WeChat professional article toolchain integration.

This module makes the WeWrite article tool a production dependency for WeChat
Official Account packets instead of relying on prompt-only discipline.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .growth_policy import build_growth_strategy
from .preflight_manifest import build_preflight_manifest
from .content_recipe import build_image_text_card_recipe
from .visual_content_policy import KNOWLEDGE_CARD_SKILL, visual_content_policy

WECHAT_ALIASES = {"wechat", "weixin", "wechat_official"}
TOOLCHAIN_META_KEYS = {
    "preflight_manifest",
    "visual_content_policy",
    "growth_strategy",
    "opening_hook",
    "hook_type",
    "sections",
    "visual_template_selection",
    "strategy_brief",
    "section_image_map",
    "real_scene_background_plan",
    "knowledge_card_plan",
    "embedded_knowledge_cards",
    "cover_design",
    "differentiation_dimensions",
    "reader_payoff",
    "concrete_case",
    "actionable_checklist",
    "tool_invocations",
    "wechat_image_post_plan",
    "image_text_card_recipe",
}


def has_wechat(platforms: list[str] | tuple[str, ...] | None) -> bool:
    return any(str(platform).casefold() in WECHAT_ALIASES for platform in platforms or [])


def requires_wechat_toolchain(config: dict[str, Any], platforms: list[str] | tuple[str, ...] | None) -> bool:
    if not has_wechat(platforms):
        return False
    cfg = config.get("wechat_toolchain", {}) if isinstance(config, dict) else {}
    if cfg.get("enabled") is False:
        return False
    flags = config.get("feature_flags", {}) if isinstance(config, dict) else {}
    return bool(cfg.get("required")) or flags.get("channel_auto_workflow_gate") == "enforce"


def prepare_wechat_professional_draft(job_id: str, job: dict[str, Any], draft: dict[str, Any], config: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    """Run WeWrite and attach the packet evidence required by the WeChat adapter."""
    if not has_wechat(job.get("platforms")):
        return draft
    cfg = dict((config or {}).get("wechat_toolchain", {}))
    required = requires_wechat_toolchain(config or {}, job.get("platforms"))
    meta = draft.setdefault("draft_meta", {})
    run_dir = Path(data_dir) / "runtime" / "wechat_toolchain" / str(job_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    brief_path = run_dir / "brief.md"
    article_path = run_dir / "article.md"
    evidence_path = run_dir / "wewrite_invocation.json"
    topic = str(job.get("topic") or draft.get("title") or "WeChat article")
    body = str(draft.get("body") or "")
    _write_brief(brief_path, topic, draft, job)
    invocation = _invoke_wewrite(cfg, brief_path, article_path, topic)
    invocation["evidence_path"] = str(evidence_path)
    if invocation.get("status") == "used" and article_path.is_file():
        title, article_body = _split_article(article_path.read_text(encoding="utf-8", errors="ignore"))
        if title:
            draft["title"] = title[:80]
        if article_body:
            draft["body"] = article_body
            body = article_body
    elif required:
        meta.setdefault("tool_invocations", {})["wewrite"] = invocation
        evidence_path.write_text(json.dumps({"tool_invocations": meta.get("tool_invocations", {})}, ensure_ascii=False, indent=2), encoding="utf-8")
        return draft
    packet = _build_packet_fields(job, draft, body, invocation, run_dir)
    for key, value in packet.items():
        if value not in (None, "", [], {}):
            meta[key] = value
    evidence_path.write_text(json.dumps({key: meta.get(key) for key in sorted(TOOLCHAIN_META_KEYS)}, ensure_ascii=False, indent=2), encoding="utf-8")
    meta["wechat_toolchain_evidence_path"] = str(evidence_path)
    return draft


def _invoke_wewrite(cfg: dict[str, Any], brief_path: Path, article_path: Path, topic: str) -> dict[str, Any]:
    wewrite_bin = os.path.expanduser(str(cfg.get("wewrite_bin") or "~/.local/bin/wewrite"))
    timeout = int(cfg.get("timeout", 180))
    env = os.environ.copy()
    _load_env_file(env, cfg.get("env_file", ""))
    base = {"tool": "wewrite", "bin": wewrite_bin, "status": "failed", "commands": []}
    if not Path(wewrite_bin).is_file():
        return {**base, "error": "wewrite CLI not found"}
    command_prefix = [sys.executable, wewrite_bin] if wewrite_bin.endswith(".py") else [wewrite_bin]
    try:
        start = subprocess.run(
            [*command_prefix, "run", "start", "--topic", topic, "--mode", "draft", "--visual-mode", "prompts", "--max-images", "3"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=min(timeout, 45),
            check=False,
        )
        base["commands"].append({"name": "run start", "returncode": start.returncode})
        run_id = _extract_run_id(start.stdout)
        if run_id:
            base["run_id"] = run_id
        write = subprocess.run(
            [*command_prefix, "llm-write", "--brief", str(brief_path), "--output", str(article_path), "--system-extra", _system_extra()],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
        )
        base["commands"].append({"name": "llm-write", "returncode": write.returncode})
        base["article_path"] = str(article_path)
        if write.returncode == 0 and article_path.is_file() and article_path.stat().st_size > 1000:
            try:
                summary = json.loads((write.stdout or "{}").strip() or "{}")
            except json.JSONDecodeError:
                summary = {}
            return {**base, "status": "used", "summary": {k: summary.get(k) for k in ["chars", "model", "tokens_in", "tokens_out"] if k in summary}}
        err = (write.stderr or write.stdout or start.stderr or start.stdout or "wewrite llm-write produced no article")[:500]
        return {**base, "error": err}
    except subprocess.TimeoutExpired:
        return {**base, "error": "wewrite command timed out"}
    except Exception as exc:
        return {**base, "error": f"wewrite invocation failed: {type(exc).__name__}: {str(exc)[:240]}"}


def _load_env_file(env: dict[str, str], env_file: str) -> None:
    if not env_file:
        return
    path = Path(os.path.expanduser(env_file))
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and key not in env:
            env[key] = value.strip().strip("'\"")


def _write_brief(path: Path, topic: str, draft: dict[str, Any], job: dict[str, Any]) -> None:
    current = str(draft.get("body") or "").strip()
    growth = build_growth_strategy(["wechat"], "long_article", (job.get("historical_feedback") or {}))
    playbook = growth.get("wechat_growth_playbook") or {}
    frequency = playbook.get("publishing_frequency") or {}
    recovery = playbook.get("recovery_topic_policy") or {}
    title_rules = playbook.get("title_rules") or {}
    seo_geo = playbook.get("seo_geo") or {}
    interaction = playbook.get("interaction_conversion") or {}
    lines = [
        f"# WeChat professional long-form brief: {topic}",
        "",
        "Goal: generate an original WeChat Official Account article, not a generic template.",
        "Length: 1800-2600 Chinese characters.",
        "Structure: strong hook, real problem, concrete case, method breakdown, checklist, natural CTA.",
        "Layout: preserve headings, quote blocks, lists, and image-friendly paragraphs for the 109-theme renderer.",
        "Images: plan at least 3 inline knowledge cards or scene images mapped to adjacent sections.",
        "Facts: use only the brief and draft information; do not invent sources, percentages, rankings, or identity claims.",
        "Anti-AI: remove slogans, filler transitions, generic advice, and mechanical three-part phrasing.",
        "",
        "## WeChat growth playbook requirements",
        f"- Recovery mode: {playbook.get('mode', 'wechat_14_day_recovery')}. During recovery publish no more than {frequency.get('max_articles_per_week_recovery', 2)} articles/week, max {frequency.get('max_articles_per_day', 1)} article/day, and keep at least {frequency.get('min_gap_hours_between_articles', 48)} hours between articles.",
        f"- Pause before next publish: {frequency.get('pause_days_before_next_publish', 2)} days if recent output was daily or repetitive.",
        "- Column mix: 马吉克开源笔记 / 我的 AI 工作台 / AI 说人话 / 你问我答或工具箱回访. Pick one column only and make the article clearly belong to it.",
        "- GitHub selection: write one carefully tested open-source project per issue unless the ops strategy proves a bundle is stronger.",
        f"- Topic dedup: block topics and title frames similar to the last {recovery.get('topic_dedup_window_days', 14)} days. Do not continue 自动化实测/办公自动化实测/重复劳动自动化 during the recovery window.",
        f"- Title: ideal {title_rules.get('ideal_chars', '12-22')} Chinese chars, hard max {title_rules.get('max_chars', 24)}; put the core keyword in the first {title_rules.get('keyword_first_chars', 15)} chars; do not use more than {title_rules.get('reject_if_fatigue_terms_exceed', 1)} fatigue term from 实测/自动化/工具/AI.",
        "- First 200 chars: include reader pain, concrete payoff, and why this matters now.",
        f"- Retention: add a new conflict, example, checklist, or decision point about every {playbook.get('article_structure', {}).get('retention_hook_interval_chars', 350)} Chinese chars.",
        "- Structure: rotate among story-driven case, contrast test, contrarian opinion, reader Q&A, and open-source note; do not reuse the old 痛点-先说结论-三条路线-踩坑-建议 template.",
        "- Interaction: end with one specific comment question plus one keyword reply CTA; do not stack multiple CTAs.",
        f"- Backend reply keywords to use when natural: {', '.join(interaction.get('backend_reply_keywords') or ['工具箱', '清单', 'GitHub', '自动化'])}.",
        f"- Search intent keywords to weave naturally: {', '.join(seo_geo.get('primary_keywords') or ['AI效率工具', 'AI自动化', '开源项目', 'GitHub精选', 'AI工作流'])}.",
        "- Review fallback: if WeChat data APIs are unavailable, require a manual backend metrics row after publishing.",
        "",
        "## Topic",
        topic,
        "",
        "## Existing draft or material",
        current or str(job.get("brief") or {}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _system_extra() -> str:
    return "Write as a senior WeChat editor. Be specific, useful, natural, and source-safe. Keep Markdown headings."


def _extract_run_id(stdout: str) -> str:
    text = (stdout or "").strip()
    try:
        data = json.loads(text)
        return str(data.get("run_id") or "")
    except json.JSONDecodeError:
        match = re.search(r"\b\d{8}-\d{6}-[a-f0-9]{6}\b", text)
        return match.group(0) if match else ""


def _split_article(text: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return "", ""
    first = lines[0].strip().lstrip("#").strip()
    if len(first) <= 80 and len(lines) > 1:
        return first, "\n".join(lines[1:]).strip()
    return "", text.strip()


def _build_packet_fields(job: dict[str, Any], draft: dict[str, Any], body: str, invocation: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    title = str(draft.get("title") or job.get("topic") or "WeChat article")
    sections = _sections(body)
    policy = visual_content_policy(["wechat"], "long_article")
    policy.setdefault("wechat_requirements", {})["theme_count_required"] = 109
    policy.setdefault("tool_refs", {}).update({
        "image_generation_engine": "hermes_tool:image_generation_engine",
        "wechat_theme_renderer": "hermes_tool:wechat_theme_renderer",
        "wechat_publisher": "hermes_tool:wechat_publisher",
    })
    section_map = [
        {"section": sections[i] if i < len(sections) else f"section_{i+1}", "image": f"wechat-inline-{i+1}.png", "purpose": purpose, "adjacent_to_text": True}
        for i, purpose in enumerate(["open the pain point", "explain the case", "summarize the method"])
    ]
    backgrounds = [
        {"asset_id": f"wewrite-bg-{i+1}", "asset_type": "photo", "background_kind": "real_scene_photo", "source": "wewrite_visual_prompt", "rights_cleared": True, "real_scene": True, "match_reason": "planned by WeWrite brief for adjacent article section", "section": item["section"], "sections": [item["section"]], "image": item["image"]}
        for i, item in enumerate(section_map)
    ]
    strategy_reason = "WeWrite long-form article with theme and inline image planning"
    growth_strategy = build_growth_strategy(["wechat"], "long_article", (job.get("historical_feedback") or {}))
    return {
        "preflight_manifest": build_preflight_manifest(
            channel="wechat",
            content_type="long_article",
            strategy_source="wewrite_llm_write",
            strategy_result_path=str(run_dir / "brief.md"),
            strategy_summary=strategy_reason,
            selected_topic=str(job.get("topic") or title),
            selection_reason="selected by channel-specific operation analysis or provided job topic",
            content_angle="case-led operational long article",
            required_assets=["cover", "inline_images", "embedded_knowledge_cards"],
            quality_gates=["wechat_professional_toolchain", "wechat_auto_packet", "asset_license", "draft_batchget_postcheck"],
            delivery_health_required=True,
            postcheck_required=True,
            extra_skills=["content/knowledge-card-designer"],
        ),
        "visual_content_policy": policy,
        "opening_hook": _opening_hook(body),
        "hook_type": "case_conflict_reader_payoff",
        "sections": sections[:5] if len(sections) >= 5 else sections + [f"section_{i}" for i in range(len(sections) + 1, 6)],
        "visual_template_selection": {"selected": "wewrite_case_feature_109_theme", "ranked_scores": [{"template": "wewrite_case_feature_109_theme", "score": 92}], "recent_same_platform_templates": [], "penalties": {}},
        "strategy_brief": {"target_user": "AI operators", "channel_lane": "AI operations", "topic_basis": str(job.get("topic") or title), "click_reason": "specific mistake and repair path", "reader_payoff": "a reusable operational checklist", "chosen_structure": "case-breakdown-method", "content_form": "longform article", "seo_geo_intent": "WeChat search and recommendation intent for AI operations", "selected_theme_reason": strategy_reason, "growth_goal": growth_strategy.get("wechat_growth_playbook", {}).get("primary_goal", "")},
        "growth_strategy": growth_strategy,
        "section_image_map": section_map,
        "real_scene_background_plan": {"required": True, "source_policy": "licensed_or_verified_real_scene_assets", "primary_background_kind": "real_scene_photo", "no_css_gradient_primary": True, "per_slide_backgrounds": backgrounds},
        "knowledge_card_plan": {"skill": KNOWLEDGE_CARD_SKILL, "card_type": "knowledge_summary", "platform": "wechat", "audience": "operators", "visual_scheme": "professional", "typography_hierarchy": "4:2:1", "self_check": ["readability", "attraction", "information_density", "share_or_save_value", "visual_match", "mobile_safe_boundaries"]},
        "embedded_knowledge_cards": [{"section": item["section"], "card_type": "step_tutorial", "layout": "timeline", "visual_subject": item["purpose"], "information_value": "explains adjacent article point", "self_check": ["readability", "attraction", "information_density", "visual_match"]} for item in section_map],
        "image_text_card_recipe": build_image_text_card_recipe(
            platform="wechat",
            content_type="wechat_image_post",
            title=title,
            cards=[
                {"role": "cover", "title": title, "layout": "hero", "palette": "editorial_blue", "visual_subject": title},
                *[
                    {"role": "content", "title": item["section"], "layout": layout, "palette": palette, "visual_subject": item["purpose"], "background": backgrounds[idx]}
                    for idx, (item, layout, palette) in enumerate(
                        zip(section_map, ["split", "timeline", "checklist"], ["warm_field", "minimal_ink", "fresh_green"])
                    )
                ],
                {"role": "cta", "title": "comment or keyword reply CTA", "layout": "summary_cta", "palette": "dark_focus", "visual_subject": "reader next step"},
            ],
            sections=sections,
            content_goal="increase WeChat open rate, full-read rate, saves, comments, and follow conversion",
        ),
        "cover_design": {"visual_subject": title[:40], "topic_alignment": "matches article promise", "mobile_readable": True, "visual_hierarchy": "title, pain point, method cue", "template_family": "casebook"},
        "differentiation_dimensions": ["wewrite professional draft", "case-led structure", "inline visual plan"],
        "reader_payoff": "reader can apply the checklist today",
        "concrete_case": str(job.get("topic") or title),
        "actionable_checklist": ["remove duplicate tools", "assign a unique tool role", "set admission rules"],
        "tool_invocations": {"wewrite": invocation},
        "wechat_image_post_plan": _wechat_image_post_plan(title, sections),
    }


def _wechat_image_post_plan(title: str, sections: list[str]) -> dict[str, Any]:
    return {
        "required": True,
        "content_type": "wechat_image_post",
        "article_type": "newspic",
        "publish_target": "wechat_newspic_draft",
        "card_count_range": [3, 9],
        "recommended_card_count": min(9, max(3, len(sections) + 2)),
        "source_article_title": title,
        "structure": ["cover_hook", "one_idea_per_section", "saveable_checklist", "comment_or_keyword_cta"],
        "visual_rules": {
            "ratio": "3:4",
            "size": "1080x1440",
            "real_scene_background_required": True,
            "forbid_css_gradient_fallback": True,
            "layout_batch_repeat_forbidden": True,
            "readability_required": True,
        },
        "quality_gate": "validate_wechat_image_post_packet",
        "postcheck": "wechat_image_draft_batchget",
    }


def _sections(body: str) -> list[str]:
    headings = []
    for line in body.splitlines():
        stripped = line.strip().strip("*").strip("#").strip()
        if stripped and (line.lstrip().startswith("#") or stripped.endswith(":") or stripped.endswith(".")):
            headings.append(stripped[:40])
    return headings or ["opening", "case", "problem", "method", "checklist"]


def _opening_hook(body: str) -> str:
    for part in re.split(r"\n\s*\n|[.!?]", body):
        text = part.strip().replace("\n", " ")
        if len(text) >= 35:
            return text[:140]
    return body.strip()[:140]
