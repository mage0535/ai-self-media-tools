import hashlib
import json
import os
import shutil
import sys
from contextlib import nullcontext
from pathlib import Path

from .resource import ResourceGuard
from .tool_adapters import ScriptVideoProvider
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

            # Route only through renderer-backed themes; never activate an
            # unverified template simply because it exists in a skill folder.
            cfg = self.config.get("wechat_format", {})
            from .theme_registry import resolve_wechat_theme, select_theme
            selection = select_theme(
                "wechat",
                title + " " + body,
                str(draft_meta.get("content_form") or "article"),
                draft_meta.get("recent_theme_ids") or [],
            )
            theme = cfg.get("default_theme") or resolve_wechat_theme(selection)

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
                "theme_selection": selection,
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
        minimum = self._required_image_count(job, cfg)
        prompts = self._image_prompts(job, minimum)
        extra_args = [
            "--method",
            cfg.get("method", "auto"),
            "--provider",
            cfg.get("provider", "auto"),
            "--size",
            cfg.get("size", "1024x1024"),
            "--quality",
            cfg.get("quality", "low"),
        ]
        if cfg.get("model"):
            extra_args.extend(["--model", str(cfg["model"])])
        input_image = job.get("draft_meta", {}).get("image_reference") or job.get("draft_meta", {}).get("input_image")
        if input_image:
            extra_args.extend(["--input-image", str(input_image)])
        images = []
        for idx, item in enumerate(prompts):
            output = output_dir / ("cover.png" if idx == 0 else f"section-{idx:02d}.png")
            provider.run(item["prompt"], output, extra_args)
            if not output.is_file():
                raise RuntimeError("image provider produced no output file")
            checksum = hashlib.sha256(output.read_bytes()).hexdigest()
            images.append(
                {
                    "kind": "image",
                    "role": item["role"],
                    "section": item.get("section", ""),
                    "purpose": item.get("purpose", ""),
                    "path": str(output),
                    "checksum": checksum,
                }
            )
        section_map = [
            {
                "section": item["section"],
                "image": item["path"],
                "purpose": item["purpose"],
                "adjacent_to_text": True,
            }
            for item in images
            if item["role"] == "section"
        ]
        if section_map:
            (output_dir / "section_image_map.json").write_text(json.dumps(section_map, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"kind": "image", "path": images[0]["path"], "checksum": images[0]["checksum"], "images": images, "section_image_map": section_map}

    @staticmethod
    def _required_image_count(job, cfg):
        if cfg.get("min_count") is not None:
            return max(1, int(cfg.get("min_count", 1)))
        platforms = {str(item).lower() for item in job.get("platforms", [])}
        body_length = len(str(job.get("body") or ""))
        if "xiaohongshu" in platforms:
            return 6
        if platforms.intersection({"wechat", "zhihu", "juejin", "bilibili"}) or body_length >= 1000:
            return 3
        return 1

    @staticmethod
    def _default_image_prompt(job):
        topic = job.get("topic") or job.get("title") or "content cover"
        platforms = ", ".join(job.get("platforms") or [])
        return (
            f"{topic}. Clean editorial illustration for {platforms or 'social media'} content, "
            "clear subject on a modern desk or workspace scene, professional magazine style, "
            "soft natural lighting, balanced composition, visible foreground and background depth, "
            "no logo, no watermark, minimal readable text."
        )

    @classmethod
    def _image_prompt(cls, job):
        custom = str((job.get("draft_meta") or {}).get("image_prompt") or "").strip()
        if not custom:
            return cls._default_image_prompt(job)
        topic = job.get("topic") or job.get("title") or "content cover"
        return (
            f"{custom}. Topic context: {topic}. Clear subject, concrete workspace or real-scene background, "
            "professional editorial illustration style, soft natural lighting, balanced composition, "
            "foreground and background depth, no logo, no watermark, minimal readable text."
        )

    @classmethod
    def _image_prompts(cls, job, minimum):
        prompts = [
            {
                "role": "cover",
                "section": "cover",
                "purpose": "introduce the article promise with a topic-matched visual",
                "prompt": cls._image_prompt(job),
            }
        ]
        if minimum <= 1:
            return prompts
        sections = cls._article_sections(job)
        for idx in range(1, minimum):
            section = sections[idx - 1] if idx - 1 < len(sections) else f"section {idx}"
            purpose = "explain or prove the adjacent article point"
            prompt = (
                f"Section illustration for: {section}. Topic context: {job.get('topic') or job.get('title') or 'article'}. "
                "Concrete visual metaphor or workspace scene that explains the adjacent paragraph, "
                "professional editorial illustration style, soft natural lighting, balanced composition, "
                "clear foreground subject and background context, no logo, no watermark, minimal readable text."
            )
            prompts.append({"role": "section", "section": section, "purpose": purpose, "prompt": prompt})
        return prompts

    @staticmethod
    def _article_sections(job):
        meta_sections = (job.get("draft_meta") or {}).get("sections") or []
        if isinstance(meta_sections, list) and meta_sections:
            return [str(item)[:80] for item in meta_sections if str(item).strip()]
        body = str(job.get("body") or "")
        parts = [part.strip().replace("\n", " ") for part in body.split("\n\n") if len(part.strip()) > 40]
        return [part[:80] for part in parts[:6]]

    def _generate_video(self, job, output_dir):
        plan = job.get("draft_meta", {}).get("video_toolchain_plan") or {}
        provider = self._choose_video_provider(plan)
        if not provider:
            raise FileNotFoundError("video script not configured")
        visual_assets = self._prepare_video_visual_assets(job, output_dir, plan)
        script_body = job.get("draft_meta", {}).get("video_prompt") or job["body"][:1200]
        env = os.environ.copy()
        env["VIDEO_OUTPUT_DIR"] = str(output_dir)
        platforms = [str(item).lower() for item in job.get("platforms", [])]
        if platforms:
            env["BGM_TARGET_PLATFORM"] = "youtube" if any(item in {"youtube", "youtube_shorts", "youtube-shorts"} for item in platforms) else platforms[0]
        if visual_assets:
            assets_path = output_dir / "video_visual_assets.json"
            assets_path.write_text(json.dumps(visual_assets, ensure_ascii=False, indent=2), encoding="utf-8")
            env["VIDEO_VISUAL_ASSETS_PATH"] = str(assets_path)
        if plan:
            plan_path = output_dir / "video_toolchain_plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            env["VIDEO_TOOLCHAIN_PLAN_PATH"] = str(plan_path)
            env["VIDEO_SELECTED_PIPELINE"] = str(plan.get("selected_pipeline", ""))
            env["VIDEO_TEMPLATE_FAMILY"] = str(plan.get("template_family", ""))
        on_research = job.get("draft_meta", {}).get("open_notebook_research") or {}
        if on_research:
            research_path = output_dir / "open_notebook_research.json"
            research_path.write_text(json.dumps(on_research, ensure_ascii=False, indent=2))
            env["OPEN_NOTEBOOK_RESEARCH_PATH"] = str(research_path)
        with self.guard.video_lock():
            provider.run(script_body, job.get("title") or job["topic"], env=env)
        manifest = self._video_toolchain_manifest(output_dir)
        if manifest.get("dry_run") or manifest.get("status") == "dry_run":
            raise RuntimeError("video toolchain dry-run output is not publishable")
        if plan.get("required"):
            self._validate_required_video_toolchain_manifest(manifest, output_dir, plan)
        generated = sorted(output_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        output = generated[0] if generated else output_dir / "video.mp4"
        if not output.is_file():
            raise RuntimeError("video provider produced no output file")
        output_bytes = output.read_bytes()
        if output.name == "dry_run.mp4" or output_bytes == b"video-toolchain-dry-run":
            raise RuntimeError("video toolchain dry-run output is not publishable")
        checksum = hashlib.sha256(output_bytes).hexdigest()
        artifact = {"kind": "video", "path": str(output), "checksum": checksum}
        if plan:
            artifact["toolchain_plan"] = str(output_dir / "video_toolchain_plan.json")
            artifact["selected_pipeline"] = str(plan.get("selected_pipeline", ""))
            artifact["template_family"] = str(plan.get("template_family", ""))
        if visual_assets:
            artifact["visual_assets"] = str(output_dir / "video_visual_assets.json")
        return artifact

    def _prepare_video_visual_assets(self, job, output_dir, plan):
        selected_pipeline = str((plan or {}).get("selected_pipeline") or "")
        if selected_pipeline == "localized_repost_video":
            return {}
        image_paths = self._existing_image_paths(job, output_dir)
        image_cfg = dict(self.config.get("image", {}))
        required_count = max(1, int(self.config.get("video", {}).get("visual_image_count", 8)))
        if not image_paths and image_cfg.get("enabled", False):
            image_cfg.setdefault("min_count", required_count)
            image_artifact = self._generate_image(job, output_dir, image_cfg)
            image_paths = [item["path"] for item in image_artifact.get("images", []) if Path(item.get("path", "")).is_file()]
        if not image_paths:
            return {}
        backgrounds = output_dir / "backgrounds"
        backgrounds.mkdir(parents=True, exist_ok=True)
        assignments = []
        for index in range(required_count):
            source = Path(image_paths[index % len(image_paths)])
            suffix = source.suffix if source.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"} else ".png"
            target = backgrounds / f"bg_{index + 1:02d}{suffix}"
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            assignments.append(
                {
                    "scene": index + 1,
                    "source_image": str(source),
                    "background_image": str(target),
                    "reused": index >= len(image_paths),
                    "purpose": "scene background matched to narration and motion card",
                }
            )
        return {
            "source": "media.image",
            "image_count": len(image_paths),
            "scene_count": required_count,
            "assignments": assignments,
        }

    @staticmethod
    def _existing_image_paths(job, output_dir):
        paths = []
        for item in job.get("artifacts") or []:
            if item.get("kind") == "image" and Path(item.get("path", "")).is_file():
                paths.append(str(Path(item["path"])))
        for pattern in ("cover.*", "section-*.*"):
            for path in sorted(Path(output_dir).glob(pattern)):
                if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"} and path.is_file():
                    paths.append(str(path))
        return list(dict.fromkeys(paths))

    def _choose_video_provider(self, plan):
        selected = str((plan or {}).get("selected_pipeline") or "")
        scripts = self.config.get("video_toolchain", {}).get("scripts", {})
        script = scripts.get(selected) if isinstance(scripts, dict) else ""
        if script:
            return ScriptVideoProvider(script, self.config.get("video", {}).get("timeout", 120))
        return self.registry.choose_provider("video")

    @staticmethod
    def _video_toolchain_manifest(output_dir):
        path = Path(output_dir) / "video_toolchain_runner_manifest.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _validate_required_video_toolchain_manifest(manifest, output_dir, plan=None):
        if not manifest:
            raise RuntimeError("required video toolchain manifest is missing")
        if not manifest.get("ok") or manifest.get("status") != "rendered":
            raise RuntimeError("required video toolchain did not finish rendered")
        selected_pipeline = str((plan or {}).get("selected_pipeline") or manifest.get("selected_pipeline") or "")
        contract = manifest.get("toolchain_contract") or {}
        planned_tools = set(contract.get("planned_tools") or [])
        if selected_pipeline == "localized_repost_video":
            required_repost_tools = {
                "source_video_discovery",
                "source_asset_matcher",
                "autoclip_adapter.run_autoclip_pipeline",
                "source_dedup_db",
                "ffmpeg.clip_segments",
                "ffmpeg.concat",
                "repost_rights_manifest",
            }
            missing_repost = sorted(required_repost_tools - planned_tools)
            if missing_repost:
                raise RuntimeError(f"required localized repost toolchain_contract missing tools: {missing_repost}")
            if not (manifest.get("source_asset_match") or {}).get("passed"):
                raise RuntimeError("required localized repost source_asset_match did not pass")
            if not manifest.get("repost_source"):
                raise RuntimeError("required localized repost source evidence is missing")
            output = Path(str(manifest.get("output") or ""))
            if not output.is_file() or output_dir not in output.parents:
                raise RuntimeError("required video manifest output is missing or outside output_dir")
            return
        required_tools = {
            "cinema_composition.storyboard",
            "shotcraft_moves.shot_plan_for_text",
            "shotcraft_moves.shot_sequence",
            "video_toolchain_runner.build_cards",
            "kuaishou_render.render_cards",
            "kuaishou_render.gen_tts",
            "kuaishou_render.render_segments",
            "kuaishou_render.concat_video",
            "kuaishou_render.download_bgm",
            "mix_bgm_with_gate.mix_bgm",
            "kuaishou_render.gen_subtitles",
            "kuaishou_render.encode_final",
            "visual_gate.py --cinema",
        }
        missing = sorted(required_tools - planned_tools)
        if missing:
            raise RuntimeError(f"required video toolchain_contract missing tools: {missing}")
        if "cinema_storyboard" not in manifest or len(manifest.get("cinema_storyboard") or []) < 8:
            raise RuntimeError("required video cinema_storyboard missing or incomplete")
        visual_assets = manifest.get("visual_assets") or {}
        if len(visual_assets.get("assignments") or []) < 3:
            raise RuntimeError("required original video visual asset assignments missing or incomplete")
        shotcraft_plan = manifest.get("shotcraft_motion_plan") or {}
        if not shotcraft_plan.get("available") or len(shotcraft_plan.get("timeline") or []) < 3:
            raise RuntimeError("required video shotcraft_motion_plan missing or incomplete")
        if not (manifest.get("cinema_visual_gate") or {}).get("passed"):
            raise RuntimeError("required video cinema visual gate did not pass")
        motion_evidence = manifest.get("motion_evidence") or {}
        if not motion_evidence.get("passed") or int(motion_evidence.get("unique_frame_count") or 0) < 2:
            raise RuntimeError("required video final motion evidence is missing or insufficient")
        segment_motion = manifest.get("segment_motion_evidence") or {}
        segments = segment_motion.get("segments") if isinstance(segment_motion, dict) else []
        if len(segments) < 3 or any(not row.get("move_id") or not row.get("profile") for row in segments if isinstance(row, dict)):
            raise RuntimeError("required video Shotcraft segment render evidence is missing or incomplete")
        output = Path(str(manifest.get("output") or ""))
        if not output.is_file() or output_dir not in output.parents:
            raise RuntimeError("required video manifest output is missing or outside output_dir")

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
