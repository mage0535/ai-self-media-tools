import json
import os
import subprocess
import urllib.request
from pathlib import Path

from .intelligence import build_generation_context, prompt_brief
from .paths import style_guide_path


class DraftGenerator:
    PROMPT_VERSION = "v3.0"
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
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:5000]

    def _normalize(self, draft, context, provider):
        body = str(draft.get("body", ""))
        body = body.strip()
        if context["style"]["cta"] and context["style"]["cta"] not in body:
            body = body.rstrip() + f"\n\n{context['style']['cta']}"
        draft_meta = {
            "trend_stage": context["trend_stage"],
            "trend_angle": context["trend_angle"],
            "reference_titles": context["reference_titles"],
            "style": context["style"],
            "image_prompt": context["image_prompt"],
            "video_prompt": context["video_prompt"],
            "hashtags": draft.get("hashtags") or context["hashtags"],
            "hook": draft.get("hook") or next(iter(context["style"]["opening_patterns"]), ""),
            "cta": draft.get("cta") or context["style"]["cta"],
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
            "Do not invent statistics or sources. Prefer scannable structure, strong opening hook, visual rhythm, and platform-friendly formatting.\n"
            f"默认文案规则:\n{self._style_guide()}\n\n"
            f"热门趋势与参考样本:\n{prompt_brief(topic, brief)}"
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
        audience = brief.get("audience", "目标读者")
        tone = brief.get("tone", "清晰、克制")
        title = f"{topic}：{ '现在最值得做的 3 件事' if context['trend_stage'] in {'hot', 'viral_candidate'} else '一份可执行指南'}"
        hook = next(iter(context["style"]["opening_patterns"]), "先看结论：")
        body = (
            f"# {title}\n\n"
            f"{hook} 面向{audience}，本文用{tone}的方式梳理 {topic}。\n\n"
            "## 为什么值得关注\n\n先确认问题、输入与验收标准，再选择最小可行路径。\n\n"
            "## 实施步骤\n\n1. 收集可靠信息并去重。\n2. 生成初稿并完成事实与风险检查。\n"
            "3. 针对目标平台调整结构和长度。\n4. 人工审核后再进入草稿或发布流程。\n\n"
            "## 检查清单\n\n- 信息来源可追溯\n- 结论没有夸大承诺\n- 格式适合目标平台\n- 发布状态有记录\n\n"
            f"{context['style']['cta']}"
        )
        return self._normalize({"title": title, "body": body}, context, "fallback")

    def _remote(self, topic, brief, context, api_key):
        base = self.config.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = self.config.get("model") or os.environ.get("CONTENT_PLATFORM_MODEL", "gpt-4.1-mini")
        prompt = (
            "Return JSON with title and body, plus optional hook, cta, hashtags. "
            "Write a factual, visually scannable, engaging draft. Learn from the reference style signals and trend stage before generating. "
            f"Style guide:\n{self._style_guide()}\n\n"
            f"Planning context: {prompt_brief(topic, brief)}"
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
