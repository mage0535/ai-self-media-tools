import os
import shutil
from pathlib import Path

from .paths import project_home
from .tool_adapters import (
    ScriptAnalyzerProvider,
    ScriptImageProvider,
    ScriptOCRProvider,
    ScriptTranscriberProvider,
    ScriptVideoProvider,
)


class ToolRegistry:
    def __init__(self, config=None):
        self.config = config or {}
        self.fast_probe = bool(self.config.get("fast_probe", False))

    def _exists(self, value):
        if not value:
            return False
        text = str(value)
        path = self._resolve_path(text)
        if path.is_absolute() or text.startswith(".") or "/" in text or "\\" in text:
            return path.exists()
        return bool(shutil.which(text))

    @staticmethod
    def _resolve_path(value):
        path = Path(str(value or "")).expanduser()
        if not path.is_absolute() and ("/" in str(value) or "\\" in str(value) or str(value).startswith(".")):
            path = project_home() / path
        return path

    def probe(self):
        media_cfg = self.config.get("media", {})
        return {
            "ffmpeg": {"available": bool(shutil.which("ffmpeg")), "kind": "media_runtime"},
            "yt_dlp": {"available": bool(shutil.which("yt-dlp")), "kind": "collection"},
            "gallery_dl": {"available": bool(shutil.which("gallery-dl")), "kind": "collection"},
            "playwright": {"available": bool(shutil.which("playwright")), "kind": "browser"},
            "python": {"available": bool(shutil.which("python") or shutil.which("python3")), "kind": "runtime"},
            "image_script": {
                "available": self._exists(media_cfg.get("image", {}).get("script", "")),
                "kind": "image_generation",
            },
            "video_script": {
                "available": self._exists(media_cfg.get("video", {}).get("script", "")),
                "kind": "video_generation",
            },
            "ocr_script": {
                "available": self._exists(self.config.get("ocr", {}).get("script", "")),
                "kind": "ocr",
            },
            "transcription_script": {
                "available": self._exists(self.config.get("transcription", {}).get("script", "")),
                "kind": "transcription",
            },
            "analysis_script": {
                "available": self._exists(self._analysis_config().get("script", "")),
                "kind": "multimodal_analysis",
            },
            "open_notebook": self._probe_open_notebook(),
            "tts_engines": self._probe_tts(),
            "image_providers": self._probe_image_providers(),
            "autocli": self._probe_autocli(),
            "browser_ext": self._probe_browser_ext(),
            "khazix_skills": self._probe_skill_dir("khazix-skills"),
            "kangarooking_skills": self._probe_skill_dir("kangarooking-skills"),
            "canghe_skills": self._probe_skill_dir("canghe-skills"),
            "huashu_skills": self._probe_skill_dir("huashu-skills"),
            "guizang_material_illustration": self._probe_skill_dir("creative/guizang-material-illustration"),
            "guizang_social_card": self._probe_skill_dir("creative/guizang-social-card"),
            "guizang_ppt": self._probe_skill_dir("creative/guizang-ppt"),
            "humanizer_zh": self._probe_skill_dir("humanizer-zh"),
            "logo_generator": self._probe_skill_dir("creative/logo-generator"),
            "gzh_design_skill": self._probe_skill_dir("creative/gzh-design-skill"),
            "magazine_layout": self._probe_skill_dir("creative/magazine-layout"),
            "gif_splitter_skill": self._probe_skill_dir("utilities/gif-splitter"),
            "zhihu_open_platform": self._probe_skill_dir("content/zhihu-open-platform"),
            "zhihu_publisher_skill": self._probe_skill_dir("zhihu-publisher"),
            "zhihu_open_cli": self._probe_zhihu_open_cli(),
            "skills_adapter": self._probe_skills_adapter(),
        }

    def _probe_autocli(self):
        ok = bool(shutil.which("autocli"))
        daemon = False
        try:
            import requests

            response = requests.get("http://127.0.0.1:19925/health", timeout=0.5 if self.fast_probe else 2)
            daemon = response.status_code == 200
        except Exception:
            pass
        return {"available": ok, "daemon": daemon, "kind": "data_collection"}

    def _probe_browser_ext(self):
        extension = os.path.expanduser("~/.chrome-autocli/autocli-extension/manifest.json")
        chrome = bool(shutil.which(os.path.expanduser("~/.cloakbrowser/chromium-146.0.7680.177.5/chrome")))
        return {"available": os.path.exists(extension) and chrome, "kind": "browser_automation"}

    def _probe_skill_dir(self, name):
        path = os.path.expanduser(f"~/.hermes/skills/{name}")
        count = 0
        if os.path.isdir(path):
            import glob

            count = len(glob.glob(os.path.join(path, "**/SKILL.md"), recursive=True))
        return {"available": count > 0, "skill_count": count, "kind": "content_generation"}

    def _probe_zhihu_open_cli(self):
        configured = os.environ.get("ZHIHU_SEARCH_BIN")
        found = shutil.which("zhihu-search")
        binary = configured or found or str(Path.home() / ".local" / "bin" / "zhihu-search")
        available = bool(found) if not configured else Path(configured).expanduser().is_file()
        if not available and not found:
            available = Path(binary).expanduser().is_file()
        return {"available": available, "binary": binary, "kind": "zhihu_open_platform"}

    def _probe_skills_adapter(self):
        import importlib.util

        path = project_home() / "content_platform" / "skills_adapter.py"
        if not path.exists():
            return {"available": False, "kind": "skills_bridge"}
        spec = importlib.util.spec_from_file_location("skills_adapter", path)
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            status = module.get_status()
            return {
                "available": True,
                "kind": "skills_bridge",
                "autocli_ok": status["autocli"]["available"],
                "fusion_script_ok": status["fusion_script"],
                "chrome_ext_ok": status["chrome_ext"],
                "total_skills": status["total_skills"],
            }
        except Exception:
            return {"available": False, "kind": "skills_bridge", "error": "import_failed"}

    def _probe_open_notebook(self):
        api = os.environ.get("OPEN_NOTEBOOK_API", "")
        if not api:
            return {"available": False, "url": "", "kind": "research"}
        try:
            import requests

            response = requests.get(f"{api}/health", timeout=0.8 if self.fast_probe else 5)
            ok = response.json().get("status") == "healthy"
            return {"available": ok, "url": api, "kind": "research"}
        except Exception:
            return {"available": False, "url": api, "kind": "research"}

    def _probe_tts(self):
        engines = {}
        for name in ["edge-tts", "kokoro"]:
            try:
                __import__(name)
                engines[name] = True
            except ImportError:
                engines[name] = False
        engines["piper"] = shutil.which("piper") is not None
        qwen_key = os.environ.get("QWEN_TTS_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
        engines["qwen3-tts"] = {
            "available": bool(qwen_key),
            "model": os.environ.get("QWEN_TTS_MODEL_CHAIN") or os.environ.get("QWEN_TTS_MODEL", "qwen3-tts-flash"),
            "kind": "cloud_tts",
        }
        return engines

    def _probe_image_providers(self):
        from .image_provider import load_secret

        providers = {
            "stock": {
                "available": bool(load_secret("PEXELS_API_KEY") or load_secret("PIXABAY_API_KEY")),
                "supports_generate": True,
                "supports_edit": False,
                "kind": "real_scene_search",
            },
            "sense_nova": {
                "available": bool(load_secret("SN_IMAGE_GEN_API_KEY") or load_secret("SN_API_KEY") or load_secret("SENSENOVA_API_KEY")),
                "supports_generate": True,
                "supports_edit": True,
                "kind": "generated_image_and_edit",
            },
            "pixazo": {
                "available": bool(load_secret("PIXAZO_API_KEY")),
                "supports_generate": True,
                "supports_edit": False,
                "kind": "generated_image",
            },
            "cloudflare": {
                "available": bool(
                    load_secret("CF_WORKER_URL")
                    or load_secret("CLOUDFLARE_IMAGE_WORKER_URL")
                    or (load_secret("CLOUDFLARE_ACCOUNT_ID") and (load_secret("CLOUDFLARE_API_TOKEN") or load_secret("CF_WORKER_KEY")))
                ),
                "supports_generate": True,
                "supports_edit": False,
                "kind": "fast_generated_image",
            },
            "pollinations": {
                "available": True,
                "supports_generate": True,
                "supports_edit": False,
                "kind": "public_generated_image_fallback",
            },
        }
        return {"available": any(item["available"] for item in providers.values()), "kind": "image_provider_registry", "providers": providers}

    def choose_provider(self, kind):
        mapping = {
            "image": (self.config.get("media", {}).get("image", {}), ScriptImageProvider),
            "video": (self.config.get("media", {}).get("video", {}), ScriptVideoProvider),
            "ocr": (self.config.get("ocr", {}), ScriptOCRProvider),
            "transcription": (self.config.get("transcription", {}), ScriptTranscriberProvider),
            "analysis": (self._analysis_config(), ScriptAnalyzerProvider),
        }
        cfg, provider_type = mapping.get(kind, ({}, None))
        if kind == "analysis" and cfg.get("script") and not self._exists(cfg.get("script")):
            return None
        if provider_type and cfg.get("script"):
            return provider_type(str(self._resolve_path(cfg.get("script", ""))), cfg.get("timeout", 120))
        return None

    def _analysis_config(self):
        configured = dict(self.config.get("analysis", {}) or {})
        if configured.get("script"):
            return configured
        bundled = project_home() / "scripts" / "image_semantic_analyze.py"
        if bundled.is_file():
            configured["script"] = str(bundled)
            configured.setdefault("timeout", 180)
        return configured
