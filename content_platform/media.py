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
        if kind not in {"image", "video", "audio", "illustration", "logo", "wechat_format", "magazine_format"}:
            raise ValueError(f"unsupported media kind: {kind}")
        if kind == "illustration":
            return self._generate_illustration(job)
        if kind == "logo":
            return self._generate_logo(job)
        if kind == "wechat_format":
            return self._format_wechat(job)
        if kind == "magazine_format":
            return self._format_magazine(job)
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

    def _generate_logo(self, job):
        """使用归藏 logo-generator 为品牌/产品生成 SVG Logo 变体。"""
        try:
            from .logogen import generate_logo

            name = job.get("title", job.get("topic", "MyBrand"))
            draft_meta = job.get("draft_meta", {})
            industry = draft_meta.get("industry", "")
            concept = draft_meta.get("core_concept", "")

            output_dir = self.data_dir / "artifacts" / job["id"] / "logo"
            output_dir.mkdir(parents=True, exist_ok=True)

            result = generate_logo(
                name=name,
                industry=industry or "",
                concept=concept or "",
                output_dir=str(output_dir),
            )

            if not result.get("ok"):
                return None

            return {
                "kind": "logo",
                "variants": result.get("variants", []),
                "count": result.get("count", 0),
                "output_dir": str(output_dir),
            }
        except ImportError:
            return None
        except Exception as exc:
            raise RuntimeError(f"logo generation failed: {exc}")

    def _format_wechat(self, job):
        """Use gzh-design-skill to convert markdown to WeChat HTML."""
        try:
            from .gzh_design import format_for_wechat

            body = job.get("body", "")
            title = job.get("title", job.get("topic", ""))
            draft_meta = job.get("draft_meta", {})

            # Pick theme from config or auto-detect from content form
            cfg = self.config.get("wechat_format", {})
            theme = cfg.get("default_theme", "摸鱼绿")

            result = format_for_wechat(
                markdown=f"# {title}\n\n{body}",
                theme=theme,
                title=title,
            )

            if not result.get("ok"):
                return None

            return {
                "kind": "wechat_format",
                "html": result["html"],
                "html_path": result.get("html_path", ""),
                "theme": result.get("theme", theme),
                "validated": result.get("validation", {}).get("ok", False),
            }
        except ImportError:
            return None
        except Exception as exc:
            raise RuntimeError(f"wechat formatting failed: {exc}")

    def _format_magazine(self, job):
        """Use magazine-layout skill to create standalone article HTML."""
        try:
            from .magazine import create_magazine

            body = job.get("body", "")
            title = job.get("title", job.get("topic", ""))
            cfg = self.config.get("magazine_format", {})
            style = cfg.get("default_style", "现代极简")

            result = create_magazine(markdown=f"# {title}\n\n{body}",
                                      style=style, title=title)
            if not result.get("ok"):
                return None

            return {
                "kind": "magazine_format",
                "html": result["html"],
                "html_path": result.get("path", ""),
                "style": result.get("style", style),
            }
        except ImportError:
            return None
        except Exception as exc:
            raise RuntimeError(f"magazine formatting failed: {exc}")

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

    def _generate_illustration(self, job):
        """使用归藏材质插画风格生成带中文标签的解释图。"""
        try:
            from .illustrator import illustrate_for_pipeline

            draft_meta = job.get("draft_meta", {})
            draft = {
                "title": job.get("title", ""),
                "body": job.get("body", ""),
                "topic": job.get("topic", ""),
            }
            # 优先从 draft_meta 取图提示词，没有则自动生成
            if draft_meta.get("illustration_prompts"):
                concepts = draft_meta["illustration_prompts"]
            else:
                result = illustrate_for_pipeline(draft)
                if not result or not result.get("illustrations"):
                    return None
                concepts = result["illustrations"]

            output_dir = self.data_dir / "artifacts" / job["id"]
            output_dir.mkdir(parents=True, exist_ok=True)

            artifacts = []
            for idx, concept in enumerate(concepts):
                prompt = concept["prompt"]
                # 调用 hermes image_generate 生成图片
                # 这里保存提示词，实际生成由 pipeline 编排层或外部调用
                prompt_path = output_dir / f"illustration-{idx+1}-prompt.txt"
                prompt_path.write_text(prompt, encoding="utf-8")
                artifacts.append({
                    "kind": "illustration",
                    "index": idx,
                    "prompt": prompt,
                    "prompt_path": str(prompt_path),
                    "structure": concept.get("structure", ""),
                    "labels": concept.get("labels", []),
                    "accent": concept.get("accent", "ikb_blue"),
                })

            return {
                "kind": "illustration",
                "artifacts": artifacts,
                "prompt_count": len(artifacts),
            }
        except ImportError:
            return None
        except Exception as exc:
            raise RuntimeError(f"illustration generation failed: {exc}")

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
