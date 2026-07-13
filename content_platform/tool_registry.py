import os
import shutil
from pathlib import Path

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
        path = Path(text).expanduser()
        if path.is_absolute() or text.startswith(".") or "/" in text or "\\" in text:
            return path.exists()
        return bool(shutil.which(text))

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
                "available": self._exists(self.config.get("analysis", {}).get("script", "")),
                "kind": "multimodal_analysis",
            },
            "open_notebook": self._probe_open_notebook(),
            "tts_engines": self._probe_tts(),
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

    def _probe_skills_adapter(self):
        import importlib.util

        project_home = Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools"))
        path = project_home / "content_platform" / "skills_adapter.py"
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
        api = os.environ.get("OPEN_NOTEBOOK_API", "http://<open-notebook-host>")
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
        return engines

    def choose_provider(self, kind):
        mapping = {
            "image": (self.config.get("media", {}).get("image", {}), ScriptImageProvider),
            "video": (self.config.get("media", {}).get("video", {}), ScriptVideoProvider),
            "ocr": (self.config.get("ocr", {}), ScriptOCRProvider),
            "transcription": (self.config.get("transcription", {}), ScriptTranscriberProvider),
            "analysis": (self.config.get("analysis", {}), ScriptAnalyzerProvider),
        }
        cfg, provider_type = mapping.get(kind, ({}, None))
        if provider_type and cfg.get("script"):
            return provider_type(cfg.get("script", ""), cfg.get("timeout", 120))
        return None
