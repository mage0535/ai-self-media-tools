import shutil
from pathlib import Path


class ToolRegistry:
    def __init__(self, config=None):
        self.config = config or {}

    def _exists(self, value):
        if not value:
            return False
        path = Path(str(value))
        return path.exists() if path.drive or str(value).startswith(("/", ".")) else bool(shutil.which(str(value)))

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
        }

    def choose_provider(self, kind):
        cfg = self.config.get("media", {}).get(kind, {})
        if cfg.get("script"):
            return {"provider": "script", "script": cfg.get("script", "")}
        return {"provider": "none"}
