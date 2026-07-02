import hashlib
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
        if kind not in {"image", "video"}:
            raise ValueError(f"unsupported media kind: {kind}")
        cfg = self.config.get(kind, {})
        if not cfg.get("enabled", False):
            return None
        target_platforms = set(cfg.get("platforms", []))
        if target_platforms and target_platforms.isdisjoint(job.get("platforms", [])):
            return None
        self.guard.check(kind)
        script = Path(cfg.get("script", ""))
        if not script.is_file():
            raise FileNotFoundError(f"{kind} script not found: {script}")
        output_dir = self.data_dir / "artifacts" / job["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
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
