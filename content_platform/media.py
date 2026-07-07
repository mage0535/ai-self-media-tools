import hashlib
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path

from .resource import ResourceGuard
from .tool_registry import ToolRegistry


class MediaBridge:
    def __init__(self, config, data_dir, guard=None):
        self.config = config or {}
        self.data_dir = Path(data_dir)
        self.guard = guard or ResourceGuard(self.data_dir, {})
        self.registry = ToolRegistry({"media": self.config, **self.config})

    def inventory(self):
        return self.registry.probe()

    def ocr(self, target):
        provider = self.registry.choose_provider("ocr")
        if not provider:
            raise FileNotFoundError("ocr script not configured")
        return provider.run(target)

    def transcribe(self, target):
        provider = self.registry.choose_provider("transcription")
        if not provider:
            raise FileNotFoundError("transcription script not configured")
        return provider.run(target)

    def analyze(self, target):
        provider = self.registry.choose_provider("analysis")
        if not provider:
            raise FileNotFoundError("analysis script not configured")
        return provider.run(target)

    def generate(self, kind, job):
        if kind not in {"image", "video", "audio"}:
            raise ValueError(f"unsupported media kind: {kind}")
        cfg = self.config.get(kind, {})
        if not cfg.get("enabled", False):
            return None
        target_platforms = set(cfg.get("platforms", []))
        if target_platforms and target_platforms.isdisjoint(job.get("platforms", [])):
            return None
        self.guard.check(kind)
        output_dir = self.data_dir / "artifacts" / job["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        if kind == "audio":
            return self._generate_audio(job, output_dir, cfg)
        if kind == "image":
            return self._generate_image(job, output_dir, cfg)
        return self._generate_video(job, output_dir)

    def _generate_image(self, job, output_dir, cfg):
        provider = self.registry.choose_provider("image")
        if not provider:
            raise FileNotFoundError("image script not configured")
        output = output_dir / "cover.png"
        prompt = job.get("draft_meta", {}).get("image_prompt") or job["topic"]
        provider.run(prompt, output, ["--method", cfg.get("method", "pil")])
        if not output.is_file():
            raise RuntimeError("image provider produced no output file")
        checksum = hashlib.sha256(output.read_bytes()).hexdigest()
        return {"kind": "image", "path": str(output), "checksum": checksum}

    def _generate_video(self, job, output_dir):
        provider = self.registry.choose_provider("video")
        if not provider:
            raise FileNotFoundError("video script not configured")
        script_body = job.get("draft_meta", {}).get("video_prompt") or job["body"][:1200]
        env = os.environ.copy()
        env["VIDEO_OUTPUT_DIR"] = str(output_dir)
        on_research = job.get("draft_meta", {}).get("open_notebook_research") or {}
        if on_research:
            research_path = output_dir / "open_notebook_research.json"
            research_path.write_text(json.dumps(on_research, ensure_ascii=False, indent=2))
            env["OPEN_NOTEBOOK_RESEARCH_PATH"] = str(research_path)
        with self.guard.video_lock():
            provider.run(script_body, job.get("title") or job["topic"], env=env)
        generated = sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        output = generated[0] if generated else output_dir / "video.mp4"
        if not output.is_file():
            raise RuntimeError("video provider produced no output file")
        checksum = hashlib.sha256(output.read_bytes()).hexdigest()
        return {"kind": "video", "path": str(output), "checksum": checksum}

    def _generate_audio(self, job, output_dir, cfg):
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from scripts.voice_engine import VoiceEngine

        narration = job.get("draft_meta", {}).get("narration_script")
        if not narration:
            narration = f"# {job['title']}\n\n{job['body']}"
        genre = job.get("draft_meta", {}).get("genre", "auto")
        mode = cfg.get("mode", "auto")
        engine = VoiceEngine(output_dir)
        result = engine.synthesize(narration, genre=genre, mode=mode)
        audio_path = result.get("audio")
        if not audio_path or not Path(audio_path).is_file():
            raise RuntimeError("voice synthesis produced no audio file")
        checksum = hashlib.sha256(Path(audio_path).read_bytes()).hexdigest()
        subtitle_path = result.get("subtitle")
        if subtitle_path and Path(subtitle_path).is_file():
            srt_checksum = hashlib.sha256(Path(subtitle_path).read_bytes()).hexdigest()
            return {
                "kind": "audio",
                "path": audio_path,
                "checksum": checksum,
                "subtitle": subtitle_path,
                "subtitle_checksum": srt_checksum,
                "duration": result.get("duration", 0),
                "genre": result.get("genre", "auto"),
            }
        return {
            "kind": "audio",
            "path": audio_path,
            "checksum": checksum,
            "duration": result.get("duration", 0),
            "genre": result.get("genre", "auto"),
        }
