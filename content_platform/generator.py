import json
import hashlib
import os
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .humanize import naturalize_copy
from .intelligence import build_generation_context, prompt_brief
from .generation_context_compiler import compile_generation_context
from .paths import style_guide_path
from .growth_policy import build_growth_strategy
from .preflight_manifest import build_preflight_manifest
from .visual_content_policy import KNOWLEDGE_CARD_SKILL, visual_content_policy
from .content_recipe import build_article_recipe, build_image_text_card_recipe, build_knowledge_card_recipe, build_tool_invocation_manifest
from .content_depth import build_content_depth_plan
from .tool_selection import build_tool_selection_evidence
from .growth_recipe import build_growth_recipe


# 2026-08-17 新增：网页抓取残留清洗（douyin/kuaishou 批量 JS/导航文本污染根因修复）
WEB_RESIDUE_PATTERNS = (
    # JS 代码残留（var glb; (glb="undefined"==typeof window ... 等）
    r"var\s+glb",
    r"glb\s*=\s*[\"']undefined[\"']",
    r"typeof\s+window",
    r"\(glb=",
    r"if\(navigator",
    r"navigator\.\w+",
    r"window\.\w+",
    r"document\.\w+",
    # 常见网页导航文本
    r"产品与服务\s+解决方案",
    r"产品与服务",
    r"关于我们\s+加入",
    r"关于我们",
    r"联系我们\s+业务咨询",
    r"联系我们",
    r"解决方案\s+关于我们",
    r"加入我们|友情链接|隐私政策|合作咨询",
)


def strip_web_residue(text: str) -> str:
    """移除 AI 生成内容中的网页抓取残留（JS 代码 + 导航文本）。

    按行过滤：含 JS 变量/导航词的行整体删除；保留正文行。
    """
    import re
    text = str(text or "")
    kept: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            kept.append("")
            continue
        lowered = line.casefold()
        if any(re.search(pat, line) or re.search(pat, lowered) for pat in WEB_RESIDUE_PATTERNS):
            continue  # 丢弃残留行
        kept.append(raw_line)
    cleaned = "\n".join(kept)
    # 折叠 3+ 连续空行为 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


class ProviderAuthError(RuntimeError):
    """A provider returned an authentication or service-level failure."""


class GenerationTimeoutError(RuntimeError):
    """Hermes exceeded the hard deadline."""

    error_class = "hard_timeout"


class DraftGenerator:
    PROMPT_VERSION = "v4.0"

    def __init__(self, config=None):
        self.config = config or {}

    def generate(self, topic, brief=None):
        brief = dict(brief or {})
        blueprint = brief.get("content_blueprint") if isinstance(brief.get("content_blueprint"), dict) else {}
        if blueprint:
            brief.setdefault("content_form", blueprint.get("content_form"))
            brief.setdefault("audience", blueprint.get("audience"))
            brief.setdefault("platform_style", blueprint.get("platform_style"))
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

    @staticmethod
    def _provider_brief(brief):
        contract = brief.get("run_contract") if isinstance(brief, dict) else None
        if not contract:
            return brief
        from .run_contract import bound_stage_payload

        payload = dict(brief.get("bounded_model_input") or {})
        strategy = payload.get("strategy")
        if isinstance(strategy, dict):
            # Provenance remains in local workflow context; providers only need
            # the strategy policy and stable source hash, never machine paths.
            payload["strategy"] = {key: value for key, value in strategy.items() if key != "source_path"}
        return bound_stage_payload(contract, "generate", payload)

    @staticmethod
    def _bounded_provider_content(content, brief):
        text = str(content or "")
        contract = brief.get("run_contract") if isinstance(brief, dict) else None
        limit = int(((contract or {}).get("bounds") or {}).get("provider_response_bytes") or 1_048_576)
        if len(text.encode("utf-8")) > limit:
            raise ValueError(f"provider response exceeds {limit} bytes")
        return text



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
        # Prefer a strict parse first (clean providers).
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Tolerate raw control characters inside string values (strict=False).
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate, strict=False)
            except json.JSONDecodeError:
                pass
        # Field-level fallback: many providers emit one well-formed top-level
        # object whose string values contain raw newlines, an unescaped lone
        # backslash, or a duplicated nested copy of the same object. Extract
        # each known string field by scanning the value span, then unescape
        # JSON escapes manually so we never lose the article body.
        return DraftGenerator._extract_fields_tolerant(text)

    @staticmethod
    def _unescape_json_string(value):
        """Decode a JSON string body that may contain raw control characters
        and lone backslashes. Falls back to a manual unescape so provider
        output that is almost-JSON still yields usable text."""
        try:
            return json.loads('"' + value.replace("\n", "\\n").replace("\r", "\\r") + '"', strict=False)
        except json.JSONDecodeError:
            out = []
            i = 0
            n = len(value)
            while i < n:
                ch = value[i]
                if ch == "\\" and i + 1 < n:
                    nxt = value[i + 1]
                    if nxt == "n":
                        out.append("\n"); i += 2; continue
                    if nxt == "t":
                        out.append("\t"); i += 2; continue
                    if nxt == "r":
                        out.append("\r"); i += 2; continue
                    if nxt in ('"', "\\", "/"):
                        out.append(nxt); i += 2; continue
                    # unknown escape: keep both chars verbatim
                    out.append(ch); out.append(nxt); i += 2; continue
                out.append(ch)
                i += 1
            return "".join(out)

    @staticmethod
    def _scan_balanced_value(text, start):
        """Return text[start:end] for a balanced {..} / [..] value, tolerating
        raw newlines and escaping inside string members."""
        stack = []
        i = start
        n = len(text)
        in_string = False
        while i < n:
            ch = text[i]
            if in_string:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == '"':
                    in_string = False
                i += 1
                continue
            if ch == '"':
                in_string = True
                i += 1
                continue
            if ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack:
                    break
                stack.pop()
                if not stack:
                    return text[start : i + 1]
            i += 1
        return text[start:]

    @staticmethod
    def _extract_field_value(text, field):
        """Return the raw span of a JSON field value, tolerant of raw
        newlines and duplicated nested objects. When a provider repeats the
        object (first copy truncated by an unescaped backslash), the LAST
        occurrence is usually the complete one, so we scan the last match.
        Returns None if absent."""
        import re as _re

        pattern = _re.compile(r'"%s"\s*:\s*(?:"|\{|\[)' % _re.escape(field))
        matches = list(pattern.finditer(text))
        if not matches:
            return None
        match = matches[-1]
        i = match.end()
        # If the value starts with an object/array (e.g. body: {"chars": N,
        # "excerpt": "..."}), scan a balanced structure instead of a string.
        if i <= len(text) and text[i - 1] in "{[":
            return DraftGenerator._scan_balanced_value(text, i - 1)
        out = []
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == "\\":
                if i + 1 < n and text[i + 1] in ('"', "\\", "/", "n", "t", "r", "u"):
                    out.append(ch)
                    out.append(text[i + 1])
                    i += 2
                    continue
                # lone backslash before a structural char: treat as literal
                out.append(ch)
                i += 1
                continue
            if ch == '"':
                # End of string only when followed by a structural char
                # (comma/brace) or end of the outer object; otherwise it is a
                # stray quote inside the value and we keep it.
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j >= n or text[j] in ",}]":
                    break
                out.append(ch)
                i += 1
                continue
            if ch in "\r\n":
                # raw newline inside a string value: encode as \n
                out.append("\\n")
                i += 1
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    @classmethod
    def _extract_fields_tolerant(cls, text):
        fields = {}
        for field in ("title", "hook", "body", "cta"):
            raw = cls._extract_field_value(text, field)
            if raw is not None:
                fields[field] = cls._unescape_json_string(cls._unwrap_field_value(raw))
        hashtags = []
        import re as _re

        ht_match = _re.search(r'"hashtags"\s*:\s*\[(.*?)\]', text, flags=_re.S)
        if ht_match:
            hashtags = _re.findall(r'"([^"]+)"', ht_match.group(1))
        if not fields.get("title") or not fields.get("body"):
            raise ValueError("provider returned non-JSON content")
        if hashtags:
            fields["hashtags"] = hashtags
        return fields

    @staticmethod
    def _unwrap_field_value(raw):
        """Some providers wrap long bodies as ``{"chars": N, "excerpt": "..."}``
        instead of a plain string. Recover the excerpt when that shape appears."""
        value = str(raw or "").strip()
        if value.startswith("{") and '"excerpt"' in value:
            import re as _re

            excerpt = _re.search(r'"excerpt"\s*:\s*"((?:[^"\\]|\\.)*)"', value)
            if excerpt:
                return excerpt.group(1)
        return value

    @staticmethod
    def _provider_error(content):
        """Classify transport failures that some CLIs print with exit code 0."""
        text = str(content or "").strip()
        import re

        match = re.match(r"^HTTP\s+(401|403|429|5\d{2})\b", text, flags=re.IGNORECASE)
        if not match:
            return ""
        code = match.group(1)
        if code in {"401", "403"}:
            return "provider_auth_failed"
        if code == "429":
            return "provider_429"
        return "provider_5xx"

    def _style_guide(self, limit=5000):
        path = Path(self.config.get("style_guide_path", str(style_guide_path())))
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]

    @staticmethod
    def _generation_requirements(context):
        strategy = context.get("strategy") or {}
        form = str(strategy.get("content_form") or "").casefold()
        platforms = {str(item).casefold() for item in strategy.get("primary_platforms") or []}
        if form in {"short_video", "knowledge_card_video", "edited_short_video", "microcase_video"} or platforms.intersection({"douyin", "douyin_ai", "douyin_pet", "kuaishou", "shipinhao", "tiktok", "youtube", "bilibili"}):
            return (
                "Body must be 280-420 Chinese characters for Chinese video narration or 90-140 English words. "
                "Use exactly eight short paragraphs separated by blank lines: hook, problem, three concrete steps, "
                "case or caution, takeaway, and CTA. Do not write an article."
            ), 1800
        return "Body must be 1200-2200 Chinese characters for Chinese articles or 900-1600 English words for English articles.", 5000

    def _normalize(self, draft, context, provider, topic="", brief=None):
        brief = brief or {}
        body = str(draft.get("body", "")).strip()
        cta = draft.get("cta") or context["style"]["cta"]
        if cta and cta not in body:
            body = body.rstrip() + f"\n\n{cta}"
        # 2026-08-17 新增：先清网页残留再 humanize，防止 JS/导航文本混入成稿
        body = strip_web_residue(body)
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
        if not draft_meta.get("cover_design"):
            draft_meta["cover_design"] = self._default_cover_design(topic, draft, brief, draft_meta)
        self._attach_growth_recipe(brief, context, draft_meta)
        platforms = list(strategy.get("primary_platforms") or brief.get("platforms") or [])
        if not draft_meta.get("tool_invocation_manifest"):
            selected = [
                str(item).strip()
                for item in (draft_meta.get("tool_selection_plan") or {}).get("selected_tools") or []
                if str(item).strip()
            ]
            draft_meta["tool_invocation_manifest"] = build_tool_invocation_manifest(
                planned_tools={name: "pre_generation_selection" for name in selected},
                invocations={
                    name: {"status": "planned", "output": "pending_runtime_execution"}
                    for name in selected
                },
            )
            draft_meta.update(build_tool_selection_evidence(
                platform=platforms[0] if platforms else "",
                content_type=str((context.get("strategy") or {}).get("content_form") or draft_meta.get("content_form") or "article"),
                content_goal="select an executable, platform-matched tool stack before generation",
                capability_status={"tools": self._runtime_capabilities(brief).get("tools") or {}},
                video_effect_registry=self._runtime_capabilities(brief).get("video_effect_modules") or {},
                planned_manifest=draft_meta["tool_invocation_manifest"],
            ))
        platform = str(platforms[0] if platforms else brief.get("platform") or "")
        draft_meta["content_depth_plan"] = build_content_depth_plan(
            str(draft.get("title") or topic),
            body,
            evidence=self._depth_evidence(brief, draft_meta),
            actions=draft_meta.get("actionable_checklist") or [],
            series_plan=draft.get("series_plan") if isinstance(draft.get("series_plan"), dict) else {},
            platform=platform,
        )
        return {
            "title": str(draft["title"]),
            "body": body,
            "provider": provider,
            "prompt_version": self.PROMPT_VERSION,
            "draft_meta": draft_meta,
        }

    @staticmethod
    def _depth_evidence(brief, draft_meta):
        matrices = [draft_meta.get("platform_source_matrix") or {}, brief.get("platform_source_matrix") or {}]
        rows = []
        for matrix in matrices:
            rows.extend((matrix.get("trend_evidence") or {}).get("samples") or [])
            rows.extend(matrix.get("attempted_sources") or [])
        evidence = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = str(row.get("url") or row.get("evidence_path") or "").strip()
            if value and value not in evidence:
                evidence.append(value)
        editorial = brief.get("editorial_evidence") or {}
        if isinstance(editorial, dict) and editorial.get("strategy_source"):
            evidence.append(str(editorial["strategy_source"]))
        return evidence[:8]

    @staticmethod
    def _default_cover_design(topic, draft, brief, draft_meta):
        topic_text = str(topic or draft.get("title") or "content topic")
        layouts = ["hero_conflict", "diagonal_split", "evidence_interface", "checklist_poster", "magazine_story", "result_reveal"]
        layout = layouts[int(hashlib.sha256(topic_text.encode("utf-8")).hexdigest()[:8], 16) % len(layouts)]
        blueprint = brief.get("content_blueprint") if isinstance(brief.get("content_blueprint"), dict) else {}
        roles = blueprint.get("mascot_roles") if isinstance(blueprint.get("mascot_roles"), dict) else {}
        focal = list(roles) if roles else [topic_text, "problem evidence", "actionable result"]
        return {
            "visual_subject": f"{topic_text} narrative proof",
            "topic_alignment": "matches the selected topic and content payoff",
            "mobile_readable": True,
            "visual_hierarchy": "hook, conflict, proof, payoff",
            "template_family": str(draft_meta.get("content_form") or "content_specific"),
            "layout_key": layout,
            "hook": str(draft.get("hook") or draft.get("title") or topic_text),
            "conflict_or_payoff": str(blueprint.get("user_pain") or "show the costly mistake and the verifiable corrective result"),
            "focal_subjects": focal,
            "content_match_reason": "the poster visualizes the current platform blueprint rather than reusing a fixed cover",
            "safe_zone_verified": True,
            "degraded": False,
        }

    @staticmethod
    def _attach_growth_recipe(brief, context, draft_meta):
        """Persist source and selection evidence without inventing collection success."""
        strategy = draft_meta.get("strategy") or {}
        platforms = list(strategy.get("primary_platforms") or brief.get("platforms") or [])
        platform = str(platforms[0] if platforms else brief.get("platform") or "").casefold()
        source_matrix = draft_meta.get("platform_source_matrix") or brief.get("platform_source_matrix") or brief.get("source_matrix") or {}
        if not source_matrix:
            supplied_sources = [str(item) for item in (brief.get("sources") or []) if str(item).strip()]
            source_name = str(brief.get("source") or "").strip()
            source_matrix = {
                "attempted_sources": [
                    {"source": source_name or url, "status": "success", "url": url}
                    for url in supplied_sources
                ]
            }
            if not source_matrix["attempted_sources"] and source_name:
                source_matrix["attempted_sources"].append({"source": source_name, "status": "success"})
            if not source_matrix["attempted_sources"]:
                source_matrix["attempted_sources"].append(
                    {"source": "generation_input", "status": "unavailable", "error": "no collection evidence supplied"}
                )
        score = draft_meta.get("viral_score") or {}
        dimensions = score.get("dimensions") if isinstance(score, dict) else {}
        signals = []
        if float((dimensions or {}).get("utility") or 0) >= 0.5:
            signals.append("user_benefit")
        if float((dimensions or {}).get("visual_promise") or 0) >= 0.5:
            signals.append("result_contrast")
        if str(draft_meta.get("trend_stage") or "").casefold() in {"emerging", "hot", "viral"}:
            signals.append("timeliness")
        topic_decision = dict(brief.get("topic_decision") or {})
        topic_decision.setdefault("score", float(score.get("total_score") or 0.01) if isinstance(score, dict) else 0.01)
        topic_decision.setdefault("growth_signals", topic_decision.get("signals") or signals)
        content_form = str(draft_meta.get("content_form") or strategy.get("content_form") or "article")
        runtime = DraftGenerator._runtime_capabilities(brief)
        draft_meta.update(build_tool_selection_evidence(
            platform=platform,
            content_type=content_form,
            content_goal="select a platform-matched format and tool stack from verified available capabilities",
            capability_status={"tools": runtime.get("tools") or {}},
            video_effect_registry=runtime.get("video_effect_modules") or {},
            planned_manifest=draft_meta.get("tool_invocation_manifest") or {},
        ))
        draft_meta["growth_recipe"] = build_growth_recipe(
            platform=platform,
            content_form=content_form,
            source_matrix=source_matrix,
            topic_decision=topic_decision,
            tool_selection_plan=draft_meta.get("tool_selection_plan"),
            process_evidence=brief.get("process_evidence") or {},
            cta=brief.get("cta_evidence") or {},
        )
        # Kuaishou's publish gate requires concrete samples, not a planned
        # source list. Preserve only already-successful collection evidence.
        if platform == "kuaishou":
            successful = [
                row for row in (source_matrix.get("attempted_sources") or [])
                if isinstance(row, dict) and str(row.get("status") or "").casefold() in {"ok", "success", "saved", "usable"}
            ]
            draft_meta["trend_evidence"] = {
                "source": str(successful[0].get("source") or "") if successful else "",
                "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds") if successful else "",
                "samples": [
                    {
                        "source": str(row.get("source") or ""),
                        "topic_signal": str(row.get("topic_signal") or ""),
                        **({"url": str(row["url"])} if row.get("url") else {}),
                    }
                    for row in successful[:5]
                ],
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
        cover_layouts = ["hero_conflict", "diagonal_split", "evidence_interface", "checklist_poster", "magazine_story", "result_reveal"]
        cover_layout = cover_layouts[int(hashlib.sha256(topic_text.encode("utf-8")).hexdigest()[:8], 16) % len(cover_layouts)]
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
            platform_source_matrix = self._platform_source_matrix(platform, sources, topic_text, {**context, **brief})
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
                "layout_key": cover_layout,
                "hook": opening,
                "conflict_or_payoff": "show the concrete mistake and the usable corrective result",
                "focal_subjects": [topic_text, "problem evidence", "actionable result"],
                "content_match_reason": "the cover visualizes the selected topic, opening conflict, and reader payoff",
                "safe_zone_verified": True,
                "degraded": False,
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
        draft_meta["image_text_card_recipe"] = build_image_text_card_recipe(
            platform=platform,
            content_type="image_text_cards",
            title=topic_text,
            cards=cards,
            sections=sections,
            content_goal="increase opens, saves, shares, comments, and follow conversion with platform-matched visual cards",
        )
        tool_manifest = build_tool_invocation_manifest(
            planned_tools={
                "generator_normalize": "content_platform.generator",
                "preflight_manifest": "content_platform.preflight_manifest",
                "visual_policy": "content_platform.visual_content_policy",
                "growth_strategy": "content_platform.growth_policy",
                "knowledge_card_designer": KNOWLEDGE_CARD_SKILL,
                "image_text_card_recipe": "content_platform.content_recipe",
            },
            invocations={
                "generator_normalize": {"status": "ok", "output": "draft_meta"},
                "preflight_manifest": {"status": "ok", "output": "draft_meta.preflight_manifest"},
                "visual_policy": {"status": "ok", "output": "draft_meta.visual_content_policy"},
                "growth_strategy": {"status": "ok", "output": "draft_meta.growth_strategy"},
                "knowledge_card_designer": {"status": "planned_internal", "output": "draft_meta.embedded_knowledge_cards"},
                "image_text_card_recipe": {"status": "ok", "output": "draft_meta.image_text_card_recipe"},
            },
        )
        draft_meta["tool_invocation_manifest"] = tool_manifest
        selection_content_type = "note" if platform in {"xiaohongshu", "rednote"} else (content_form or "article")
        draft_meta.update(build_tool_selection_evidence(
            platform=platform,
            content_type=selection_content_type,
            content_goal="increase opens, saves, and follow conversion with platform-matched structure, cards, and visuals",
            capability_status={"tools": self._runtime_capabilities(brief).get("tools") or {}},
            video_effect_registry=self._runtime_capabilities(brief).get("video_effect_modules") or {},
            planned_manifest=tool_manifest,
        ))

    @staticmethod
    def _runtime_capabilities(brief):
        bounded = brief.get("bounded_model_input") if isinstance(brief, dict) else {}
        bounded = bounded if isinstance(bounded, dict) else {}
        direct = brief.get("runtime_capabilities") if isinstance(brief, dict) else {}
        runtime = bounded.get("runtime_capabilities") or direct or {}
        return runtime if isinstance(runtime, dict) else {}

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
        """按内容赛道/关键词选择文章结构（2026-08-16 修复：不再固定 problem-cause-solution）。

        之前只有 checklist/case/workflow 触发，其余一律 problem-cause-solution，
        忽略了 style guide 的故事-观点/热点-预判模板。现在按内容语义选 4 种结构。
        """
        content = f"{content_form} {topic}".casefold()
        if any(k in content for k in ["checklist", "list", "清单", "步骤", "模板", "合集", "避坑", "top", "个技巧", "个坑", "个方法"]):
            return "checklist-steps-cautions"
        if any(k in content for k in ["case", "workflow", "实测", "案例", "工作流", "拆解", "教程", "复盘", "实操"]):
            return "case-breakdown-method"
        # 热点/趋势类 → 热点-解读-预判（2026-08-16 新增）
        if any(k in content for k in ["热点", "趋势", "热搜", "爆款", "为什么突然", "新规", "重磅", "变天", "最新"]):
            return "hotspot-interpret-forecast"
        # 故事/情感类 → 故事-观点-延伸（2026-08-16 新增）
        if any(k in content for k in ["故事", "经历", "我", "崩溃", "后悔", "坚持", "新手", "感悟", "治愈", "翻车", "踩坑"]):
            return "story-opinion-extension"
        # 赛道兜底（2026-08-16 新增：结合 detect_genre）
        try:
            from scripts.voice_engine import detect_genre
            genre = detect_genre(topic or "")
            if genre in {"emotion", "pets"}:
                return "story-opinion-extension"
            if genre in {"finance", "science"}:
                return "problem-cause-solution"
        except Exception:
            pass
        return "problem-cause-solution"

    @staticmethod
    def _platform_source_matrix(platform, sources, topic, brief=None):
        """Preserve collection evidence instead of treating planned sources as collected."""
        brief = brief or {}
        supplied = brief.get("platform_source_matrix") or brief.get("source_matrix") or {}
        raw_attempted = supplied.get("attempted_sources") if isinstance(supplied, dict) else []
        attempted = []
        for row in raw_attempted if isinstance(raw_attempted, list) else []:
            if isinstance(row, str):
                row = {"source": row}
            if not isinstance(row, dict) or not str(row.get("source") or "").strip():
                continue
            attempted.append({
                "source": str(row["source"]),
                "status": str(row.get("status") or "unknown"),
                "topic_signal": str(row.get("topic_signal") or topic),
                **({"collected_at": str(row["collected_at"])} if row.get("collected_at") else {}),
                **({"evidence_kind": str(row["evidence_kind"])} if row.get("evidence_kind") else {}),
                **({"url": str(row["url"])} if row.get("url") else {}),
                **({"error": str(row["error"])} if row.get("error") else {}),
            })
        if not attempted:
            attempted = [
                {
                    "source": source,
                    "status": "unavailable",
                    "topic_signal": topic,
                    "error": "collection evidence was not supplied to the generation brief",
                }
                for source in sources
            ]
        successful = [row for row in attempted if row.get("status") == "ok"]
        platform_aliases = {str(platform).casefold(), "rednote" if platform == "xiaohongshu" else ""}
        if str(platform).casefold().startswith("douyin"):
            platform_aliases.add("douyin")
        platform_evidence = any(
            row.get("status") == "ok"
            and bool(row.get("collected_at"))
            and any(alias and alias in str(row.get("source") or "").casefold() for alias in platform_aliases)
            for row in attempted
        )
        trend_evidence = supplied.get("trend_evidence") if isinstance(supplied.get("trend_evidence"), dict) else {}
        real_collection = (
            bool(supplied.get("real_platform_collection_verified"))
            and platform_evidence
            and bool(trend_evidence.get("source"))
            and bool(trend_evidence.get("collected_at"))
            and bool(trend_evidence.get("samples"))
        )
        internally_verified = bool(supplied.get("platform_internal_verified")) and real_collection
        return {
            "platform": platform,
            "attempted_sources": attempted,
            "successful_source_count": len(successful),
            "platform_internal_verified": internally_verified,
            "real_platform_collection_verified": real_collection,
            "current_platform_specific_topic": real_collection,
            "platform_strategy_verified": bool(supplied.get("platform_strategy_verified")),
            "shared_trend_only": not internally_verified,
            "report_path": str(supplied.get("report_path") or "runtime:strategy_brief.platform_source_matrix"),
            "trend_evidence": trend_evidence if real_collection else {"source": "", "collected_at": "", "samples": []},
        }

    def _hermes(self, topic, brief, context):
        language = context.get("language") or "zh"
        language_instruction = (
            "Write in English for this international channel. Translate non-English topic words naturally; do not output Chinese unless it is a quoted product name."
            if language == "en"
            else "Write in Simplified Chinese for this Chinese-language channel."
        )
        body_requirement, style_limit = self._generation_requirements(context)
        editorial_facts_only = str(brief.get("selection_mode") or "") == "editorial_calendar"
        factual_boundary = (
            "Do not write first-person operational history, named-team anecdotes, incident timelines, "
            "percentages, durations, benchmark figures, provider performance claims, or invented examples. "
            "Write recommendations and clearly labelled hypothetical steps only; do not imply they happened. "
            if editorial_facts_only else ""
        )
        try:
            return self._hermes_attempt(topic, brief, context, retry=False, language_instruction=language_instruction, factual_boundary=factual_boundary, body_requirement=body_requirement, style_limit=style_limit)
        except GenerationTimeoutError:
            return self._hermes_attempt(topic, brief, context, retry=True, language_instruction=language_instruction, factual_boundary=factual_boundary, body_requirement=body_requirement, style_limit=style_limit)
        except RuntimeError as exc:
            if str(exc) != "transient provider error":
                raise
            return self._hermes_attempt(topic, brief, context, retry=True, language_instruction=language_instruction, factual_boundary=factual_boundary, body_requirement=body_requirement, style_limit=style_limit)

    def _hermes_attempt(self, topic, brief, context, *, retry, language_instruction, factual_boundary, body_requirement, style_limit):
        platform = str(brief.get("platform") or context.get("platform") or "wechat")
        language = context.get("language") or "zh"
        compiled = compile_generation_context(
            platform=platform,
            content_format=str(brief.get("content_form") or (brief.get("content_blueprint") or {}).get("content_form") or "article"),
            stage="generate", brief=brief, context=context, retry=retry,
        )
        prompt = (
            "Return only JSON. Do not use markdown fences. "
            "Required keys: title, body. Optional keys: hook, cta, hashtags. "
            f"Target language: {language}. {language_instruction} "
            "Write a factual, high-retention draft. First learn from same-track references, then generate. "
            "Open with a concrete hook in the first 2 sentences: a striking number, a rhetorical question "
            "(为什么/难道/是不是/有没有, or for English: 'Why do...', 'What if...', 'Still using...?'), "
            "a direct pain point (坑/误区/翻车/浪费, or for English: mistake, trap, waste, broken, no one tells you), "
            "or a first-person conflict. Example English hook: 'Most teams still trust AI agents blindly — until one silently deletes production data.' "
            "The hook must read like a real person grabbing attention, not like a headline. "
            "If content_hygiene recommends a cornerstone refresh or merge, update the canonical asset angle instead of creating a redundant near-duplicate article. "
            "Do not invent statistics or sources. Prefer scannable structure, strong opening hook, visual rhythm, and platform-friendly formatting. "
            f"{factual_boundary}"
            f"{body_requirement}\n"
            f"Platform rules (must follow for this channel):\n{context.get('platform_rules', '')[:800]}\n\n"
            f"Viral hook templates (pick one and adapt for your title/opening):\n{context.get('hook_samples', '')[:600]}\n\n"
            f"Style guide:\n{self._style_guide(style_limit)}\n\n"
            f"Generation context (compiled, bounded):\n{compiled['text']}"
        )
        command = [self.config.get("hermes_command", "hermes")]
        command.extend(["-z", prompt, "--cli"])
        clock = self.config.get("clock", time.time)
        started = clock()
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        soft = int(self.config.get("soft_deadline", 240))
        hard = int(self.config.get("hard_deadline", 420))
        heartbeat_interval = max(1, int(self.config.get("heartbeat_interval", 30)))
        # elapsed is relative to started, so keep heartbeat thresholds relative too.
        next_heartbeat_at = soft
        while proc.poll() is None:
            elapsed = clock() - started
            if elapsed >= hard:
                finished = clock()
                attempt = 2 if retry else 1
                try:
                    self._terminate_generation_process(proc)
                except Exception as exc:
                    payload = self._checkpoint_payload(
                        attempt=attempt, status="process_termination_failed", error_class="process_termination_failed",
                        prompt_hash=compiled["sha256"], prompt_length=len(prompt), started_at=started, finished_at=finished,
                    )
                    self._write_generation_checkpoint(payload)
                    self._record_generation_attempt(payload)
                    raise RuntimeError("Hermes process termination failed") from exc
                payload = self._checkpoint_payload(
                    attempt=attempt, status="hard_timeout", error_class="hard_timeout",
                    prompt_hash=compiled["sha256"], prompt_length=len(prompt), started_at=started, finished_at=finished,
                )
                self._write_generation_checkpoint(payload)
                self._record_generation_attempt(payload)
                raise GenerationTimeoutError("Hermes hard deadline exceeded")
            if elapsed >= next_heartbeat_at:
                heartbeat_at = clock()
                self._write_generation_checkpoint(self._checkpoint_payload(
                    attempt=2 if retry else 1, status="running_after_soft_deadline", error_class="soft_deadline",
                    prompt_hash=compiled["sha256"], prompt_length=len(prompt), started_at=started, finished_at=heartbeat_at,
                    elapsed=heartbeat_at - started, heartbeat_at=heartbeat_at,
                ))
                next_heartbeat_at += heartbeat_interval
            self.config.get("sleep", time.sleep)(0.05)
        stdout, stderr = proc.communicate()
        finished = clock()
        attempt = 2 if retry else 1
        prompt_evidence = {
            "prompt_hash": compiled["sha256"],
            "prompt_length": len(prompt),
            "started_at": started,
            "finished_at": finished,
        }
        if proc.returncode != 0:
            error_text = stdout or stderr
            is_transient = self._is_transient_provider_error(error_text)
            error_class = self._transient_error_class(error_text) if is_transient else self._persistent_error_class(error_text)
            status = "transient_provider_error" if is_transient else "provider_error"
            payload = self._checkpoint_payload(attempt=attempt, status=status, error_class=error_class, **prompt_evidence)
            self._write_generation_checkpoint(payload)
            self._record_generation_attempt(payload)
            if self._is_transient_provider_error(stdout or stderr):
                raise RuntimeError("transient provider error")
            raise RuntimeError("Hermes generation command failed")
        content = self._bounded_provider_content(stdout, brief).strip()
        provider_error = self._provider_error(content)
        if provider_error:
            status = "transient_provider_error" if provider_error in {"provider_429", "provider_5xx"} else "provider_error"
            payload = self._checkpoint_payload(attempt=attempt, status=status, error_class=provider_error, **prompt_evidence)
            self._write_generation_checkpoint(payload)
            self._record_generation_attempt(payload)
            if status == "transient_provider_error":
                raise RuntimeError("transient provider error")
            raise ProviderAuthError(provider_error)
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            draft = self._coerce_provider_draft(content, topic)
        except ValueError:
            payload = self._checkpoint_payload(attempt=attempt, status="provider_error", error_class="invalid_json", **prompt_evidence)
            self._write_generation_checkpoint(payload)
            self._record_generation_attempt(payload)
            raise
        if not draft.get("title") or not draft.get("body"):
            payload = self._checkpoint_payload(attempt=attempt, status="provider_error", error_class="invalid_json", **prompt_evidence)
            self._write_generation_checkpoint(payload)
            self._record_generation_attempt(payload)
            raise ValueError("Hermes returned an incomplete draft")
        payload = self._checkpoint_payload(attempt=attempt, status="success", error_class="", **prompt_evidence)
        self._write_generation_checkpoint(payload)
        self._record_generation_attempt(payload)
        return self._normalize(draft, context, "hermes-cli", topic, brief)

    def _terminate_generation_process(self, proc):
        grace = float(self.config.get("termination_grace", self.config.get("process_termination_grace", 5)))
        proc.terminate()
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=grace)

    @staticmethod
    def _transient_error_class(content):
        text = str(content or "").casefold()
        if "429" in text or "rate limit" in text:
            return "provider_429"
        if any(code in text for code in ("500", "502", "503", "504", "5xx")):
            return "provider_5xx"
        return "provider_error"

    @staticmethod
    def _persistent_error_class(content):
        text = str(content or "").casefold()
        if any(marker in text for marker in ("permission denied", "access denied", "permissionerror")):
            return "permission_denied"
        return "provider_error"

    def _is_transient_provider_error(self, content):
        text = str(content or "").casefold()
        transient_markers = ("429", "500", "502", "503", "504", "rate limit", "temporarily unavailable", "timeout", "timed out")
        return any(marker in text for marker in transient_markers) and not any(code in text for code in ("401", "403"))

    def _write_generation_checkpoint(self, payload):
        directory = Path(self.config.get("checkpoint_dir") or Path.cwd())
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "generation_checkpoint.json"
        previous = {}
        if target.is_file():
            try:
                previous = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = {}
        transitions = list(previous.get("transitions") or [])
        transitions.append({
            "attempt": payload.get("attempt"),
            "status": payload.get("status"),
            "error_class": payload.get("error_class", ""),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "at": payload.get("heartbeat_at") or payload.get("finished_at"),
        })
        payload = dict(payload)
        payload["transitions"] = transitions
        fd, temp_name = tempfile.mkstemp(prefix="generation_checkpoint.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    @staticmethod
    def _checkpoint_payload(*, attempt, status, error_class, prompt_hash, prompt_length, started_at, finished_at, elapsed=None, heartbeat_at=None):
        payload = {
            "attempt": attempt,
            "status": status,
            "prompt_hash": prompt_hash,
            "prompt_length": prompt_length,
            "error_class": error_class,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        if elapsed is not None:
            payload["elapsed"] = elapsed
        if heartbeat_at is not None:
            payload["heartbeat_at"] = heartbeat_at
        return payload

    def _record_generation_attempt(self, payload):
        path = self.config.get("generation_attempts_path")
        if not path:
            return
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        if target.is_file():
            try:
                rows = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                rows = []
        rows.append({key: value for key, value in payload.items() if key != "prompt"})
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temp, target)

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
            f"- Platform rules: {context.get('platform_rules', '')[:400]}\n"
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
        body_requirement, style_limit = self._generation_requirements(context)
        prompt = (
            "Return JSON with title and body, plus optional hook, cta, hashtags. "
            f"Target language: {language}. {language_instruction} "
            "Write a factual, visually scannable, engaging draft. Learn from the reference style signals and trend stage before generating. "
            "If content_hygiene recommends a cornerstone refresh or merge, update the canonical asset angle instead of creating a redundant near-duplicate article. "
            f"{body_requirement}\n"
            f"Platform rules (must follow for this channel):\n{context.get('platform_rules', '')[:800]}\n\n"
            f"Viral hook templates (pick one and adapt for your title/opening):\n{context.get('hook_samples', '')[:600]}\n\n"
            f"Style guide:\n{self._style_guide(style_limit)}\n\n"
            f"Planning context:\n{prompt_brief(topic, self._provider_brief(brief))}"
        )
        payload = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.4}).encode()
        request = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=int(self.config.get("timeout", 90))) as response:
            result = json.loads(response.read())
        content = self._bounded_provider_content(result["choices"][0]["message"]["content"], brief).strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        draft = self._coerce_provider_draft(content, topic)
        if not draft.get("title") or not draft.get("body"):
            raise ValueError("provider returned an incomplete draft")
        return self._normalize(draft, context, model, topic, brief)
