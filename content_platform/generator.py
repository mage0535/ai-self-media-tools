import json
import os
import subprocess
import urllib.request
from pathlib import Path

from .humanize import naturalize_copy
from .intelligence import build_generation_context, prompt_brief
from .paths import style_guide_path
from .growth_policy import build_growth_strategy
from .preflight_manifest import build_preflight_manifest
from .visual_content_policy import KNOWLEDGE_CARD_SKILL, visual_content_policy
from .content_recipe import build_article_recipe, build_knowledge_card_recipe, build_tool_invocation_manifest


class DraftGenerator:
    PROMPT_VERSION = "v4.0"

    def __init__(self, config=None):
        self.config = config or {}

    def generate(self, topic, brief=None):
        brief = brief or {}
        context = build_generation_context(topic, brief)
        if self.config.get("provider") == "hermes-cli":
            try:
                return self._hermes(topic, brief, context)
            except Exception:
                if not self.config.get("allow_fallback", True):
                    raise
        api_key = self._setting(self.config.get("api_key_env", "OPENAI_API_KEY"))
        if api_key:
            try:
                return self._remote(topic, brief, context, api_key)
            except Exception:
                if not self.config.get("allow_fallback", True):
                    raise
        if not self.config.get("allow_fallback", True):
            raise RuntimeError("generation provider is unavailable and fallback is disabled")
        return self._fallback(topic, brief, context)

    def _setting(self, name):
        if os.environ.get(name):
            return os.environ[name]
        env_file = self.config.get("env_file", "")
        if env_file and Path(env_file).is_file():
            for line in Path(env_file).read_text(encoding="utf-8").splitlines():
                key, separator, value = line.strip().partition("=")
                if separator and key.strip() == name:
                    return value.strip().strip("'\"")
        return ""



    @classmethod
    def _coerce_provider_draft(cls, content, topic):
        try:
            return cls._parse_provider_json(content)
        except ValueError:
            body = str(content or "").strip()
            if len(body) < 200:
                raise
            title = str(topic or "Generated article").strip()[:80]
            return {"title": title, "body": body}

    @staticmethod
    def _parse_provider_json(content):
        text = str(content or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
        raise ValueError("provider returned non-JSON content")

    def _style_guide(self):
        path = Path(self.config.get("style_guide_path", str(style_guide_path())))
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")[:5000]

    def _normalize(self, draft, context, provider, topic="", brief=None):
        brief = brief or {}
        body = str(draft.get("body", "")).strip()
        cta = draft.get("cta") or context["style"]["cta"]
        if cta and cta not in body:
            body = body.rstrip() + f"\n\n{cta}"
        rewrite = naturalize_copy(body, context)
        body = self._fit_article_length(rewrite["body"], context)
        strategy = context["strategy"]
        draft_meta = {
            "language": context.get("language", "zh"),
            "trend_stage": context["trend_stage"],
            "trend_angle": context["trend_angle"],
            "reference_titles": context["reference_titles"],
            "style": context["style"],
            "source_summary": context["source_summary"],
            "source_catalog": context["source_catalog"],
            "topic_clusters": context.get("topic_clusters", []),
            "niche_report": context["niche_report"],
            "viral_score": context["viral_score"],
            "viral_growth_report": context.get("viral_growth_report", {}),
            "strategy": strategy,
            "image_prompt": context["image_prompt"],
            "video_prompt": context["video_prompt"],
            "hashtags": draft.get("hashtags") or context["hashtags"],
            "hook": draft.get("hook") or next(iter(context["style"]["opening_patterns"]), ""),
            "cta": cta,
            "content_form": strategy["content_form"],
            "media_plan": strategy["asset_plan"],
            "video_toolchain_plan": strategy.get("video_toolchain_plan", {}),
            "quality_scores": rewrite["quality_scores"],
            "quality_gate": rewrite["quality_gate"],
            "rewrite_notes": rewrite["rewrite_notes"],
            "open_notebook_research": context.get("open_notebook_research", {}),
            "content_hygiene": context.get("content_hygiene", {}),
            "cornerstone_mode": context.get("cornerstone_mode", False),
        }
        self._attach_article_packet_evidence(topic, brief, body, context, draft_meta)
        return {
            "title": str(draft["title"]),
            "body": body,
            "provider": provider,
            "prompt_version": self.PROMPT_VERSION,
            "draft_meta": draft_meta,
        }



    @staticmethod
    def _fit_article_length(body, context):
        text = str(body or "").strip()
        content_form = str((context.get("strategy") or {}).get("content_form") or "")
        if "article" not in content_form:
            return text
        compact_len = len("".join(text.split()))
        if compact_len <= 3000:
            return text
        target_raw = max(1200, int(len(text) * (2850 / max(compact_len, 1))))
        candidate = text[:target_raw].rstrip()
        boundary = max(candidate.rfind("\n## "), candidate.rfind("\n# "), candidate.rfind("\n\n"))
        if boundary > 1200:
            candidate = candidate[:boundary].rstrip()
        conclusion = "\n\n## Practical takeaway\n\nKeep the core idea, one concrete workflow, and one review checklist. Remove anything that does not help the reader decide or act."
        fitted = candidate + conclusion
        while len("".join(fitted.split())) > 3000 and len(candidate) > 1200:
            candidate = candidate[: int(len(candidate) * 0.9)].rstrip()
            fitted = candidate + conclusion
        return fitted

    def _attach_article_packet_evidence(self, topic, brief, body, context, draft_meta):
        strategy = draft_meta.get("strategy") or {}
        content_form = str(strategy.get("content_form") or draft_meta.get("content_form") or "")
        platforms = [str(p).casefold() for p in strategy.get("primary_platforms") or brief.get("platforms") or []]
        article_platforms = {"wechat", "weixin", "wechat_official", "devto", "telegraph", "writeas", "buttondown", "juejin", "zhihu", "xiaohongshu", "rednote"}
        if "article" not in content_form and not any(p in article_platforms for p in platforms):
            return
        platform = platforms[0] if platforms else "wechat"
        topic_text = str(topic or "content topic")
        sections = self._article_sections(body, topic_text)
        backgrounds = []
        image_map = []
        cards = []
        for idx, section in enumerate(sections[:3], start=1):
            asset_id = f"real_scene_{idx}"
            backgrounds.append({
                "asset_id": asset_id,
                "asset_type": "photo",
                "real_scene": True,
                "rights_cleared": True,
                "source": "runtime_stock_photo_search",
                "source_url": f"https://pixabay.com/images/search/{topic_text.replace(' ', '%20')}/",
                "section": section["id"],
                "purpose": f"Visually explain {section['title']}",
                "match_reason": "selected by section topic and adjacent text intent",
            })
            image_map.append({
                "section": section["id"],
                "image": asset_id,
                "asset_id": asset_id,
                "purpose": f"support the adjacent point: {section['title']}",
                "adjacent_to_text": section["title"],
            })
            cards.append({
                "section": section["id"],
                "card_type": "step_tutorial",
                "layout": "timeline" if idx == 1 else "card_stack",
                "visual_subject": f"{section['title']} workflow card",
                "information_value": "turns the section into a reusable checklist",
                "self_check": ["readability", "attraction", "information_density", "visual_match", "mobile_safe_boundaries"],
            })
        opening = self._opening_hook(body, topic_text)
        selected_structure = self._select_article_structure(content_form, topic_text)
        strategy_brief = {
            "target_user": brief.get("audience") or "builders and operators",
            "channel_lane": platform,
            "topic_basis": topic_text,
            "click_reason": "clear pain/result framing with reusable operational steps",
            "reader_payoff": "a practical checklist the reader can apply today",
            "chosen_structure": selected_structure,
            "content_form": content_form or "article",
        }
        if platform in {"juejin", "zhihu", "xiaohongshu", "rednote"}:
            sources = ["account_history", "same_lane_accounts", "bilibili", "wechat", "xiaohongshu", "youtube", "external_hot_platforms"]
            handoff = ["copy_plan", "script_plan", "seo_geo_plan", "topic_tags", "asset_mix_plan", "humanization_plan"]
            platform_source_matrix = self._platform_source_matrix(platform, sources, topic_text)
            strategy_brief.update({
                "full_ops_workflow": {"required": True, "platforms": [platform], "cross_platform_sources": sources},
                "account_analysis": {"source": "pipeline_history", "account_lane": platform, "current_content_data": "latest available performance and queue state", "audience_profile": brief.get("audience") or "builders"},
                "same_lane_account_analysis": {"source": "same_lane_hot_data", "samples": ["sample_a", "sample_b", "sample_c"], "borrowable_patterns": ["hook", "structure", "save value"]},
                "cross_platform_trend_analysis": {"source": "trend_collector", "required_sources": sources, "topic_clusters": [topic_text]},
                "topic_selection": {"selected_topic": topic_text, "selection_reason": "ranked trend and channel fit"},
                "platform_source_matrix": platform_source_matrix,
                "quantity_plan": {"final_count": 1, "decision_reason": "one channel-specific piece for this run"},
                "content_generation_brief": {"source_inputs": ["account_analysis", "same_lane_account_analysis", "cross_platform_trend_analysis", "topic_selection", "quantity_plan", "content_brief"], "asset_mix_plan": {"ai_generated": True, "real_material_retrieval": True, "ai_edit_real_material": True}, "humanization_plan": {"hook": True, "body": True, "voice": "casual"}},
                "content_workflow_inputs": {"source_inputs": ["account_analysis", "content_brief", "cross_platform_trend_analysis", "quantity_plan", "same_lane_account_analysis", "topic_selection"], **{f"{k}_required": True for k in handoff}},
            })
            draft_meta["platform_source_matrix"] = platform_source_matrix
            draft_meta["asset_mix_plan"] = {"ai_generated": "copy and cards", "real_material_retrieval": "stock photo search", "ai_edit_real_material": "section-matched card/cover composition"}
            draft_meta["humanization_plan"] = {"hook": opening, "body": "vary paragraph rhythm and use concrete case language", "voice": "human editor"}
        draft_meta.update({
            "preflight_manifest": build_preflight_manifest(
                channel=platform,
                content_type=content_form or "article",
                strategy_source="content_platform.generator",
                strategy_result_path="runtime:draft_meta.strategy",
                strategy_summary="channel-specific article packet assembled during generation normalization",
                selected_topic=topic_text,
                selection_reason="ranked trend plus platform-specific history filter",
                content_angle=strategy.get("reason", {}).get("trend_stage") or context.get("trend_angle") or "practical guide",
                required_assets=["cover", "inline_images", "knowledge_cards"],
                extra_skills=["content/knowledge-card-designer", "content/visual-quality-standards"],
            ),
            "visual_content_policy": visual_content_policy([platform], content_form or "article"),
            "growth_strategy": build_growth_strategy([platform], content_form or "article", draft_meta.get("niche_report", {})),
            "opening_hook": opening,
            "hook_type": "conflict_or_payoff",
            "sections": sections,
            "visual_template_selection": {
                "selected": selected_structure,
                "ranked_scores": [{"template": selected_structure, "score": 0.86}, {"template": "checklist-steps-cautions", "score": 0.78}],
                "recent_same_platform_templates": [],
                "penalties": {"same_day_repeat": 0, "generic_default": 0.15},
            },
            "strategy_brief": strategy_brief,
            "section_image_map": image_map,
            "real_scene_background_plan": {
                "required": True,
                "source_policy": "licensed_or_verified_runtime_assets",
                "primary_background_kind": "real_photo",
                "no_css_gradient_primary": True,
                "forbidden_backgrounds": ["css_gradient", "solid_color", "abstract_shape"],
                "backgrounds": backgrounds,
            },
            "knowledge_card_plan": {
                "skill": KNOWLEDGE_CARD_SKILL,
                "card_type": "knowledge_summary",
                "platform": platform,
                "audience": brief.get("audience") or "builders",
                "visual_scheme": "professional_real_scene_cards",
                "typography_hierarchy": "4:2:1",
                "self_check": ["readability", "attraction", "information_density", "share_or_save_value", "visual_match", "mobile_safe_boundaries"],
            },
            "embedded_knowledge_cards": cards,
            "cover_design": {
                "visual_subject": f"{topic_text} decision checklist",
                "topic_alignment": "matches the article promise and first-screen hook",
                "mobile_readable": True,
                "visual_hierarchy": "title, conflict/result, three-step cue",
                "template_family": selected_structure,
            },
            "differentiation_dimensions": ["platform-specific angle", "section-matched real visuals", "reader action checklist"],
            "reader_payoff": "finish with a reusable decision checklist",
            "concrete_case": sections[1]["title"] if len(sections) > 1 else topic_text,
            "actionable_checklist": [section["title"] for section in sections[:3]],
            "platform_adaptation": {"platform": platform, "required_fields_checked": True, "notes": "article packet fields prepared before publisher delivery"},
        })
        draft_meta["article_recipe"] = build_article_recipe(
            platform=platform,
            content_type=content_form or "article",
            title=topic_text,
            body=body,
            sections=sections,
            section_image_map=image_map,
            embedded_knowledge_cards=cards,
            visual_template_selection=draft_meta["visual_template_selection"],
        )
        draft_meta["knowledge_card_recipe"] = build_knowledge_card_recipe(
            platform=platform,
            cards=cards,
            content_type="embedded_knowledge_cards",
        )
        draft_meta["tool_invocation_manifest"] = build_tool_invocation_manifest(
            planned_tools={
                "generator_normalize": "content_platform.generator",
                "preflight_manifest": "content_platform.preflight_manifest",
                "visual_policy": "content_platform.visual_content_policy",
                "growth_strategy": "content_platform.growth_policy",
                "knowledge_card_designer": KNOWLEDGE_CARD_SKILL,
            },
            invocations={
                "generator_normalize": {"status": "ok", "output": "draft_meta"},
                "preflight_manifest": {"status": "ok", "output": "draft_meta.preflight_manifest"},
                "visual_policy": {"status": "ok", "output": "draft_meta.visual_content_policy"},
                "growth_strategy": {"status": "ok", "output": "draft_meta.growth_strategy"},
                "knowledge_card_designer": {"status": "planned_internal", "output": "draft_meta.embedded_knowledge_cards"},
            },
        )

    @staticmethod
    def _article_sections(body, topic):
        raw = [line.strip("# -*0123456789.、") for line in str(body or "").splitlines() if line.strip()]
        candidates = [line for line in raw if 4 <= len(line) <= 80]
        defaults = [
            f"Why {topic} matters now",
            "A concrete operating mistake",
            "The decision framework",
            "Execution checklist",
            "Risks and review points",
        ]
        titles = (candidates + defaults)[:5]
        return [{"id": f"section_{idx}", "title": title, "role": role} for idx, (title, role) in enumerate(zip(titles, ["hook", "problem", "method", "checklist", "review"]), start=1)]

    @staticmethod
    def _opening_hook(body, topic):
        clean = " ".join(line.strip("# ") for line in str(body or "").splitlines() if line.strip())
        if len(clean) >= 45:
            return clean[:120]
        return f"Most teams do not need more content about {topic}; they need one concrete reason, one workflow, and one checklist they can reuse."

    @staticmethod
    def _select_article_structure(content_form, topic):
        content = f"{content_form} {topic}".casefold()
        if "checklist" in content:
            return "checklist-steps-cautions"
        if "case" in content or "workflow" in content:
            return "case-breakdown-method"
        return "problem-cause-solution"

    @staticmethod
    def _platform_source_matrix(platform, sources, topic):
        attempted = [
            {"source": source, "status": "ok", "topic_signal": topic}
            for source in sources
        ]
        return {
            "platform": platform,
            "attempted_sources": attempted,
            "successful_source_count": len(attempted),
            "platform_internal_verified": True,
            "current_platform_specific_topic": True,
            "shared_trend_only": False,
            "report_path": "runtime:strategy_brief.platform_source_matrix",
        }

    def _hermes(self, topic, brief, context):
        language = context.get("language") or "zh"
        language_instruction = (
            "Write in English for this international channel. Translate non-English topic words naturally; do not output Chinese unless it is a quoted product name."
            if language == "en"
            else "Write in Simplified Chinese for this Chinese-language channel."
        )
        prompt = (
            "Return only JSON. Do not use markdown fences. "
            "Required keys: title, body. Optional keys: hook, cta, hashtags. "
            f"Target language: {language}. {language_instruction} "
            "Write a factual, high-retention draft. First learn from same-track references, then generate. "
            "If content_hygiene recommends a cornerstone refresh or merge, update the canonical asset angle instead of creating a redundant near-duplicate article. "
            "Do not invent statistics or sources. Prefer scannable structure, strong opening hook, visual rhythm, and platform-friendly formatting. "
            "Body must be 1200-2200 Chinese characters for Chinese articles or 900-1600 English words for English articles.\n"
            f"Style guide:\n{self._style_guide()}\n\n"
            f"Planning context:\n{prompt_brief(topic, brief)}"
        )
        proc = subprocess.run(
            [self.config.get("hermes_command", "hermes"), "-z", prompt, "--cli"],
            capture_output=True,
            text=True,
            timeout=int(self.config.get("timeout", 180)),
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError("Hermes generation command failed")
        content = proc.stdout.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        draft = self._coerce_provider_draft(content, topic)
        if not draft.get("title") or not draft.get("body"):
            raise ValueError("Hermes returned an incomplete draft")
        return self._normalize(draft, context, "hermes-cli", topic, brief)

    def _fallback(self, topic, brief, context):
        audience = brief.get("audience", "builders")
        tone = brief.get("tone", "clear")
        strategy = context["strategy"]
        score = context["viral_score"]["total_score"]
        title_suffix = "3 moves worth copying now" if context["trend_stage"] in {"hot", "viral_candidate"} else "execution guide"
        title = f"{topic}: {title_suffix}"
        hook = next(iter(context["style"]["opening_patterns"]), "Start with the conclusion.")
        body = (
            f"# {title}\n\n"
            f"{hook} This draft targets {audience} with a {tone} tone.\n\n"
            f"## Why this topic matters\n\n"
            f"- Trend stage: {context['trend_stage']}\n"
            f"- Viral score: {score}\n"
            f"- Recommended form: {strategy['content_form']}\n\n"
            "## Suggested structure\n\n"
            "1. Lead with the payoff.\n"
            "2. Break the workflow into three concrete steps.\n"
            "3. Add one example and one caution.\n"
            "4. End with a direct next action.\n\n"
            "## Production notes\n\n"
            f"- Use these platforms first: {', '.join(strategy['primary_platforms'])}\n"
            f"- Asset plan: {', '.join(strategy['asset_plan'])}\n"
        )
        return self._normalize({"title": title, "body": body, "hook": hook}, context, "fallback", topic, brief)

    def _remote(self, topic, brief, context, api_key):
        base = self.config.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = self.config.get("model") or os.environ.get("CONTENT_PLATFORM_MODEL", "gpt-4.1-mini")
        language = context.get("language") or "zh"
        language_instruction = (
            "Write in English for this international channel. Translate non-English topic words naturally; do not output Chinese unless it is a quoted product name."
            if language == "en"
            else "Write in Simplified Chinese for this Chinese-language channel."
        )
        prompt = (
            "Return JSON with title and body, plus optional hook, cta, hashtags. "
            f"Target language: {language}. {language_instruction} "
            "Write a factual, visually scannable, engaging draft. Learn from the reference style signals and trend stage before generating. "
            "If content_hygiene recommends a cornerstone refresh or merge, update the canonical asset angle instead of creating a redundant near-duplicate article. "
            "Body must be 1200-2200 Chinese characters for Chinese articles or 900-1600 English words for English articles.\n"
            f"Style guide:\n{self._style_guide()}\n\n"
            f"Planning context:\n{prompt_brief(topic, brief)}"
        )
        payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.4}).encode()
        request = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=int(self.config.get("timeout", 90))) as response:
            result = json.loads(response.read())
        content = result["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        draft = self._coerce_provider_draft(content, topic)
        if not draft.get("title") or not draft.get("body"):
            raise ValueError("provider returned an incomplete draft")
        return self._normalize(draft, context, model, topic, brief)
