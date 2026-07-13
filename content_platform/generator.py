import json
import os
import subprocess
import urllib.request
from pathlib import Path

from .humanize import naturalize_copy
from .intelligence import build_generation_context, prompt_brief
from .paths import style_guide_path


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

    def _style_guide(self):
        path = Path(self.config.get("style_guide_path", str(style_guide_path())))
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")[:5000]

    def _normalize(self, draft, context, provider):
        body = str(draft.get("body", "")).strip()
        cta = draft.get("cta") or context["style"]["cta"]
        if cta and cta not in body:
            body = body.rstrip() + f"\n\n{cta}"
        rewrite = naturalize_copy(body, context)
        body = rewrite["body"]
        strategy = context["strategy"]
        draft_meta = {
            "trend_stage": context["trend_stage"],
            "trend_angle": context["trend_angle"],
            "reference_titles": context["reference_titles"],
            "style": context["style"],
            "source_summary": context["source_summary"],
            "source_catalog": context["source_catalog"],
            "topic_clusters": context.get("topic_clusters", []),
            "niche_report": context["niche_report"],
            "viral_score": context["viral_score"],
            "strategy": strategy,
            "image_prompt": context["image_prompt"],
            "video_prompt": context["video_prompt"],
            "hashtags": draft.get("hashtags") or context["hashtags"],
            "hook": draft.get("hook") or next(iter(context["style"]["opening_patterns"]), ""),
            "cta": cta,
            "content_form": strategy["content_form"],
            "media_plan": strategy["asset_plan"],
            "quality_scores": rewrite["quality_scores"],
            "quality_gate": rewrite["quality_gate"],
            "rewrite_notes": rewrite["rewrite_notes"],
            "open_notebook_research": context.get("open_notebook_research", {}),
            "content_hygiene": context.get("content_hygiene", {}),
            "cornerstone_mode": context.get("cornerstone_mode", False),
        }
        return {
            "title": str(draft["title"]),
            "body": body,
            "provider": provider,
            "prompt_version": self.PROMPT_VERSION,
            "draft_meta": draft_meta,
        }

    def _hermes(self, topic, brief, context):
        prompt = (
            "Return only JSON. Do not use markdown fences. "
            "Required keys: title, body. Optional keys: hook, cta, hashtags. "
            "Write a factual, high-retention draft. First learn from same-track references, then generate. "
            "If content_hygiene recommends a cornerstone refresh or merge, update the canonical asset angle instead of creating a redundant near-duplicate article. "
            "Do not invent statistics or sources. Prefer scannable structure, strong opening hook, visual rhythm, and platform-friendly formatting.\n"
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
        draft = json.loads(content)
        if not draft.get("title") or not draft.get("body"):
            raise ValueError("Hermes returned an incomplete draft")
        return self._normalize(draft, context, "hermes-cli")

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
        return self._normalize({"title": title, "body": body, "hook": hook}, context, "fallback")

    def _remote(self, topic, brief, context, api_key):
        base = self.config.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = self.config.get("model") or os.environ.get("CONTENT_PLATFORM_MODEL", "gpt-4.1-mini")
        prompt = (
            "Return JSON with title and body, plus optional hook, cta, hashtags. "
            "Write a factual, visually scannable, engaging draft. Learn from the reference style signals and trend stage before generating. "
            "If content_hygiene recommends a cornerstone refresh or merge, update the canonical asset angle instead of creating a redundant near-duplicate article.\n"
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
        draft = json.loads(content)
        if not draft.get("title") or not draft.get("body"):
            raise ValueError("provider returned an incomplete draft")
        return self._normalize(draft, context, model)
