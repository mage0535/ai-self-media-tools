import hashlib
import json
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path

from .resource import ResourceGuard
from .tool_adapters import ScriptAnalyzerProvider, ScriptOCRProvider, ScriptTranscriberProvider
from .tool_registry import ToolRegistry


class MediaBridge:
    def __init__(self, config, data_dir, guard=None):
        self.config = config or {}
        self.data_dir = Path(data_dir)
        self.guard = guard or ResourceGuard(self.data_dir, {})
        self.registry = ToolRegistry({"media": self.config})

    def inventory(self):
        return self.registry.probe()

    def _provider_cfg(self, section):
        return self.config.get(section, {})

    def ocr(self, target):
        cfg = self._provider_cfg("ocr")
        if not cfg.get("script"):
            raise FileNotFoundError("ocr script not configured")
        return ScriptOCRProvider(cfg.get("script", ""), cfg.get("timeout", 120)).run(target)

    def transcribe(self, target):
        cfg = self._provider_cfg("transcription")
        if not cfg.get("script"):
            raise FileNotFoundError("transcription script not configured")
        return ScriptTranscriberProvider(cfg.get("script", ""), cfg.get("timeout", 300)).run(target)

    def analyze(self, target):
        cfg = self._provider_cfg("analysis")
        if not cfg.get("script"):
            raise FileNotFoundError("analysis script not configured")
        return ScriptAnalyzerProvider(cfg.get("script", ""), cfg.get("timeout", 180)).run(target)

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
        script = Path(cfg.get("script", ""))
        if not script.is_file():
            raise FileNotFoundError(f"{kind} script not found: {script}")
        if kind == "image":
            output = output_dir / "cover.png"
            prompt = job.get("draft_meta", {}).get("image_prompt") or job["topic"]
            command = ["python3", str(script), prompt, "--output", str(output), "--method", cfg.get("method", "pil")]
            env = None
        else:
            script_body = job.get("draft_meta", {}).get("video_prompt") or job["body"][:1200]
            command = ["python3", str(script), script_body, job.get("title") or job["topic"]]
            env = os.environ.copy()
            env["VIDEO_OUTPUT_DIR"] = str(output_dir)
            # 注入 Open Notebook 研究数据（如存在）
            on_research = job.get("draft_meta", {}).get("open_notebook_research") or {}
            if on_research:
                research_path = output_dir / "open_notebook_research.json"
                research_path.write_text(json.dumps(on_research, ensure_ascii=False, indent=2))
                env["OPEN_NOTEBOOK_RESEARCH_PATH"] = str(research_path)
        lock = self.guard.video_lock() if kind == "video" else nullcontext()
        with lock:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=int(cfg.get("timeout", 300)), check=False, env=env
            )
        if kind == "video":
            generated = sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
            output = generated[0] if generated else output_dir / "video.mp4"
        if proc.returncode != 0 or not output.is_file():
            detail = (proc.stderr or proc.stdout or "media command failed")[-500:]
            raise RuntimeError(detail)
        checksum = hashlib.sha256(output.read_bytes()).hexdigest()
        return {"kind": kind, "path": str(output), "checksum": checksum}

    def _generate_audio(self, job, output_dir, cfg):
        """智能配音：调用 voice_engine 合成语音 + 字幕"""
        import sys
        _root = Path(__file__).resolve().parent.parent
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
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
                "kind": "audio", "path": audio_path, "checksum": checksum,
                "subtitle": subtitle_path, "subtitle_checksum": srt_checksum,
                "duration": result.get("duration", 0),
                "genre": result.get("genre", "auto"),
            }
        return {
            "kind": "audio", "path": audio_path, "checksum": checksum,
            "duration": result.get("duration", 0),
            "genre": result.get("genre", "auto"),
        }
