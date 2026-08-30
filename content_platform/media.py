import hashlib
import json
import os
import re
import shutil
import sys
from contextlib import nullcontext
from pathlib import Path

from .resource import ResourceGuard
from .tool_adapters import ScriptVideoProvider
from .tool_registry import ToolRegistry
from .paths import agent_scripts_dir
from .cover_director import render_cover_poster
from .cover_quality import normalize_cover_resolution
from .adapters.media import execute_article_media

try:
    from PIL import Image, ImageStat, UnidentifiedImageError
except ImportError:  # pragma: no cover - image generation already depends on Pillow in production/test paths.
    Image = None
    ImageStat = None
    UnidentifiedImageError = OSError


class MediaBridge:
    VIDEO_SCRIPT_MAX_SEGMENTS = 8
    VIDEO_SCRIPT_MAX_CHARS_PER_SEGMENT = 40
    VIDEO_SCRIPT_MIN_CHARS_PER_SEGMENT = 8

    def __init__(self, config, data_dir, guard=None):
        self.config = config or {}
        self.data_dir = Path(data_dir)
        self.guard = guard or ResourceGuard(self.data_dir, {})
        self.registry = ToolRegistry({"media": self.config, **self.config})
        self._visual_route: dict | None = None

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
        if kind not in {"image", "cover", "video", "audio", "illustration", "logo", "wechat_format", "magazine_format"}:
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
        # ── visual-router 自动适配层：生成前自动判断内容类型 → 注入路由建议 ──
        # 内容驱动: 结构化→内容驱动卡/电影级视频, 情感→AI生图, 知识→知识图块
        # 用户零指定，管线自动选择最佳视觉效果
        try:
            sys.path.insert(0, str(agent_scripts_dir()))
            from visual_router import classify, route
            text = " ".join([
                str(job.get("title", "")),
                str(job.get("topic", "")),
                str((job.get("draft_meta") or {}).get("summary", "")),
                str(job.get("body", ""))[:800],
            ])
            media_kind = "video" if kind == "video" else ("card" if kind == "image" else "article")
            cls = classify(text)
            route_order = route(text, media_kind)
            job["visual_route"] = {
                "content_type": cls["type"],
                "signals": {k: v for k, v in cls.items() if k != "type"},
                "media_kind": media_kind,
                "route_order": route_order,
                "auto": True,
            }
            self._visual_route = job["visual_route"]
        except Exception as e:
            job["visual_route"] = {"auto": False, "error": str(e)[:100]}
            self._visual_route = job["visual_route"]
        output_dir = self.data_dir / "artifacts" / job["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        if kind == "cover":
            return self._generate_cover(job, output_dir)
        if kind == "audio":
            return self._generate_audio(job, output_dir, cfg)
        if kind == "image":
            return self._generate_image(job, output_dir, cfg)
        return self._generate_video(job, output_dir)

    def _generate_cover(self, job, output_dir):
        for pattern in ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp"):
            candidate = output_dir / pattern
            if candidate.is_file() and candidate.stat().st_size > 0:
                return {
                    "kind": "cover",
                    "path": str(candidate),
                    "checksum": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    "source": "existing_verified_image_artifact",
                }
        image_cfg = dict(self.config.get("image", {}))
        if not image_cfg.get("enabled", False):
            raise FileNotFoundError("cover is missing and image generation is not configured")
        image_cfg["min_count"] = 1
        artifact = self._generate_image(job, output_dir, image_cfg)
        rows = [item for item in artifact.get("images", []) if str(item.get("role") or "").casefold() == "cover"]
        if not rows:
            raise RuntimeError("image provider produced no cover artifact")
        cover = rows[0]
        return {
            "kind": "cover",
            "path": str(cover["path"]),
            "checksum": str(cover.get("checksum") or hashlib.sha256(Path(cover["path"]).read_bytes()).hexdigest()),
            "source": "adaptive_image_pipeline",
        }

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
        # ── visual-router 自动适配：结构化/知识内容 → 内容驱动知识图块系列 ──
        # 仅对图文平台（非视频8场景）生效，且路由首选 content-driven-cards 时
        vr = job.get("visual_route") or {}
        platforms = {str(item).lower() for item in job.get("platforms", [])}
        video_platforms = platforms.intersection(
            {"kuaishou", "douyin", "douyin_ai", "tiktok", "shipinhao", "youtube", "youtube_shorts", "bilibili"}
        )
        if ("juejin" not in platforms and not video_platforms and not job.get("_video_asset_generation")
                and vr.get("auto") and vr.get("route_order")
                and vr["route_order"][0] == "content-driven-cards"):
            try:
                scripts_dir = agent_scripts_dir()
                sys.path.insert(0, str(scripts_dir))
                import subprocess as _sp
                card_dir = output_dir / "cards"
                card_dir.mkdir(parents=True, exist_ok=True)
                # 用内容驱动卡片生成器（8 卡系列，每卡按内容选视觉）
                title = job.get("title") or job.get("topic") or "AI"
                body = str(job.get("body") or "")[:2000]
                _sp.run([sys.executable, str(scripts_dir / "diagram_knowledge_cards_v2.py"),
                         str(card_dir), title, body],
                        capture_output=True, text=True, timeout=120)
                # 脚本产出 HTML → 渲染 PNG（diagram_html2png）
                htmls = sorted(card_dir.glob("dcard_*.html"))
                for hidx, hp in enumerate(htmls, 1):
                    png_path = card_dir / f"card_{hidx:02d}.png"
                    _sp.run([sys.executable, str(scripts_dir / "diagram_html2png.py"),
                             str(hp), str(png_path), "--width", "1080", "--height", "1920"],
                            capture_output=True, text=True, timeout=90)
                pngs = sorted(card_dir.glob("*.png"))
                if pngs:
                    images = []
                    for idx, png in enumerate(pngs):
                        images.append({
                            "kind": "image",
                            "role": "cover" if idx == 0 else "section",
                            "section": "",
                            "purpose": f"内容驱动知识图块卡 {idx+1}",
                            "path": str(png),
                            "checksum": hashlib.sha256(png.read_bytes()).hexdigest(),
                        })
                    self._persist_asset_provenance(output_dir, images, [], "diagram_knowledge_cards_v2", job)
                    return {"kind": "image", "path": str(pngs[0]),
                            "checksum": images[0]["checksum"],
                            "images": images, "section_image_map": [], "auto_route": "content-driven-cards"}
            except Exception as e:
                # 内容驱动卡失败 → 静默降级到 AI 生图
                pass
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
        if "juejin" in platforms:
            staging_url = str(cfg.get("public_staging_base_url") or self.config.get("public_staging_base_url") or "").strip()

            def generate_article_asset(item, target):
                prompt = next(row["prompt"] for row in prompts if row["role"] == item["role"] and (item["role"] == "cover" or row["section"] == item["section"]))
                provider.run(prompt, target, extra_args)
                if item["role"] == "cover":
                    generated_target = target.with_name("cover-background" + target.suffix)
                    target.replace(generated_target)
                    evidence = render_cover_poster(
                        generated_target,
                        target,
                        (job.get("draft_meta") or {}).get("cover_design") or {},
                    )
                    (output_dir / "cover_quality_evidence.json").write_text(
                        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    cover_gate = normalize_cover_resolution(target)
                    if not cover_gate.get("passed"):
                        raise RuntimeError("adaptive cover normalization failed: " + str(cover_gate.get("error") or "unknown"))
                return {
                    "origin_type": "generated",
                    "generation_evidence": {
                        "provider": type(provider).__name__,
                        "model": str(cfg.get("model") or cfg.get("provider") or "auto"),
                        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    },
                    "license": "generated_for_project",
                    "semantic_match_score": 0.82,
                    "match_reason": item["section"],
                }

            package = execute_article_media(
                job,
                output_dir,
                generate_article_asset,
                public_staging_base_url=staging_url,
                public_staging_uploader=cfg.get("public_staging_uploader"),
                public_staging_verifier=cfg.get("public_staging_verifier"),
                staging_timeout_seconds=float(cfg.get("staging_timeout_seconds", 5)),
                max_concurrency=int(cfg.get("max_concurrency", 3)),
                max_attempts=int(cfg.get("max_attempts", 3)),
            )
            images = [
                {
                    **item,
                    "kind": "cover" if item["role"] == "cover" else "image",
                    "url": item["public_url"],
                    "public_url": item["public_url"],
                }
                for item in package["assets"]
            ]
            return {
                "kind": "image",
                "path": images[0]["path"],
                "checksum": images[0]["checksum"],
                "images": images,
                "section_image_map": package["section_image_map"],
                "article_media_contract": str(output_dir / "article_media_contract.json"),
            }
        images = []
        recovery = self._image_quality_recovery_plan(job, cfg)
        accepted_checksums: set[str] = set()
        accepted_hashes: set[str] = set()
        for idx, item in enumerate(prompts):
            output = output_dir / ("cover.png" if idx == 0 else f"section-{idx:02d}.png")
            raw_gate = self._run_image_provider_with_quality_recovery(
                provider,
                item,
                output,
                extra_args,
                output_dir,
                accepted_checksums,
                accepted_hashes,
                recovery,
            )
            if item["role"] == "cover" and output.is_file():
                generated_output = output.with_name("cover-background.png")
                output.replace(generated_output)
                evidence = render_cover_poster(
                    generated_output,
                    output,
                    (job.get("draft_meta") or {}).get("cover_design") or {},
                )
                (output_dir / "cover_quality_evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            if not output.is_file():
                raise RuntimeError("image provider produced no output file")
            if item["role"] == "cover":
                cover_gate = normalize_cover_resolution(output)
                if not cover_gate.get("passed"):
                    raise RuntimeError("cover normalization failed: " + str(cover_gate.get("error") or "unknown"))
            checksum = hashlib.sha256(output.read_bytes()).hexdigest()
            accepted_checksums.add(checksum)
            if raw_gate.get("checksum"):
                accepted_checksums.add(str(raw_gate["checksum"]))
            if raw_gate.get("visual_hash"):
                accepted_hashes.add(str(raw_gate["visual_hash"]))
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
        self._persist_asset_provenance(output_dir, images, prompts, type(provider).__name__, job)
        result = {"kind": "image", "path": images[0]["path"], "checksum": images[0]["checksum"], "images": images, "section_image_map": section_map}
        if recovery["enabled"]:
            self._write_image_quality_recovery(output_dir, recovery, passed=True)
            result["quality_recovery"] = self._image_quality_recovery_summary(recovery, passed=True)
        return result

    def _run_image_provider_with_quality_recovery(
        self,
        provider,
        item,
        output,
        extra_args,
        output_dir,
        accepted_checksums,
        accepted_hashes,
        recovery,
    ):
        if not recovery["enabled"]:
            provider.run(item["prompt"], output, extra_args)
            if not output.is_file():
                raise RuntimeError("image provider produced no output file")
            return {}

        last_failures = []
        max_attempts = recovery["max_attempts"]
        for attempt in range(1, max_attempts + 1):
            prompt = self._image_quality_retry_prompt(item["prompt"], attempt, last_failures)
            try:
                if output.exists():
                    output.unlink()
                provider.run(prompt, output, extra_args)
                gate = self._validate_image_quality_candidate(output, accepted_checksums, accepted_hashes)
            except Exception as exc:
                gate = {
                    "passed": False,
                    "failures": ["provider_or_quality_exception"],
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                }
            self._record_image_quality_attempt(output_dir, recovery, item, output, prompt, attempt, gate)
            if gate.get("passed"):
                return gate
            last_failures = list(gate.get("failures") or ["quality_gate_failed"])
        self._write_image_quality_recovery(output_dir, recovery, passed=False)
        raise RuntimeError(
            "image quality recovery exhausted: "
            + ", ".join(last_failures or ["quality_gate_failed"])
        )

    @classmethod
    def _image_quality_recovery_plan(cls, job, cfg):
        enabled = cls._is_xiaohongshu_knowledge_image_job(job)
        raw_attempts = cfg.get("quality_recovery_attempts", cfg.get("max_quality_recovery_attempts", 3))
        try:
            max_attempts = int(raw_attempts)
        except (TypeError, ValueError):
            max_attempts = 3
        return {
            "enabled": enabled,
            "max_attempts": min(5, max(1, max_attempts)),
            "attempts": [],
        }

    @staticmethod
    def _is_xiaohongshu_knowledge_image_job(job):
        platforms = {str(item).casefold() for item in job.get("platforms") or []}
        if not platforms.intersection({"xiaohongshu", "rednote"}):
            return False
        meta = job.get("draft_meta") or {}
        signals = [
            job.get("content_type"),
            job.get("content_form"),
            job.get("selected_pipeline"),
            meta.get("content_type"),
            meta.get("content_form"),
            meta.get("selected_pipeline"),
        ]
        joined = " ".join(str(item).casefold() for item in signals if item)
        return any(
            token in joined
            for token in ("knowledge_card", "image_text", "carousel", "manual_carousel")
        )

    @staticmethod
    def _image_quality_retry_prompt(base_prompt, attempt, failures):
        if attempt <= 1:
            return base_prompt
        failure_text = ", ".join(failures or ["previous candidate failed quality checks"])
        return (
            f"{base_prompt}\n\nQuality recovery attempt {attempt}: choose a different real-scene candidate, "
            f"with richer foreground/background detail, distinct composition and subject from prior attempts. "
            f"Avoid the previous failure modes: {failure_text}."
        )

    @classmethod
    def _validate_image_quality_candidate(cls, path, accepted_checksums, accepted_hashes):
        path = Path(path)
        failures = []
        if not path.is_file() or path.stat().st_size <= 0:
            return {"passed": False, "failures": ["image_missing"]}
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum in accepted_checksums:
            failures.append("duplicate_checksum")
        if Image is None or ImageStat is None:
            raise RuntimeError("Pillow is required for image quality validation")
        try:
            with Image.open(path) as raw:
                image = raw.convert("RGB")
                width, height = image.size
                probe = image.resize((64, 64))
                stat = ImageStat.Stat(probe)
                complexity = sum(float(value) for value in stat.stddev) / max(1, len(stat.stddev))
                colors = probe.getcolors(maxcolors=4096) or []
                visual_hash = cls._average_hash(probe)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            return {
                "passed": False,
                "failures": ["image_decode_failed"],
                "checksum": checksum,
                "error": str(exc)[:200],
            }
        if min(width, height) < 512:
            failures.append("resolution_too_low")
        if complexity < 18 or len(colors) < 24:
            failures.append("low_complexity")
        if visual_hash and any(cls._hamming_distance(visual_hash, previous) <= 2 for previous in accepted_hashes):
            failures.append("duplicate_visual_hash")
        return {
            "passed": not failures,
            "failures": failures,
            "checksum": checksum,
            "visual_hash": visual_hash,
            "dimensions": [width, height],
            "complexity": round(complexity, 3),
            "color_count": len(colors),
        }

    @staticmethod
    def _average_hash(image):
        gray = image.convert("L").resize((8, 8))
        values = list(gray.tobytes())
        average = sum(values) / len(values)
        return "".join("1" if value >= average else "0" for value in values)

    @staticmethod
    def _hamming_distance(left, right):
        return sum(1 for a, b in zip(str(left), str(right)) if a != b) + abs(len(str(left)) - len(str(right)))

    @staticmethod
    def _record_image_quality_attempt(output_dir, recovery, item, output, prompt, attempt, gate):
        failed_candidate_path = ""
        if not gate.get("passed") and Path(output).is_file():
            evidence_dir = output_dir / "image_quality_recovery"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(output).suffix or ".bin"
            failed_candidate = evidence_dir / f"{item['role']}-{len(recovery['attempts']) + 1:02d}-attempt-{attempt}{suffix}"
            shutil.copy2(output, failed_candidate)
            failed_candidate_path = str(failed_candidate)
        recovery["attempts"].append(
            {
                "role": item.get("role", ""),
                "section": item.get("section", ""),
                "attempt": attempt,
                "passed": gate.get("passed") is True,
                "failures": list(gate.get("failures") or []),
                "prompt_sha256": hashlib.sha256(str(prompt).encode("utf-8")).hexdigest(),
                "candidate_path": str(output),
                "failed_candidate_path": failed_candidate_path,
                "checksum": gate.get("checksum", ""),
                "visual_hash": gate.get("visual_hash", ""),
                "dimensions": gate.get("dimensions", []),
                "complexity": gate.get("complexity"),
                "color_count": gate.get("color_count"),
                "error": gate.get("error", ""),
            }
        )

    @classmethod
    def _write_image_quality_recovery(cls, output_dir, recovery, passed):
        payload = cls._image_quality_recovery_summary(recovery, passed)
        payload["attempts"] = recovery["attempts"]
        (output_dir / "image_quality_recovery.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _image_quality_recovery_summary(recovery, passed):
        failures = [
            failure
            for attempt in recovery["attempts"]
            if not attempt.get("passed")
            for failure in attempt.get("failures", [])
        ]
        return {
            "version": "image_quality_recovery_v1",
            "passed": passed,
            "max_attempts": recovery["max_attempts"],
            "attempt_count": len(recovery["attempts"]),
            "retry_count": max(0, len(recovery["attempts"]) - len([item for item in recovery["attempts"] if item.get("attempt") == 1])),
            "failure_count": len([item for item in recovery["attempts"] if not item.get("passed")]),
            "failure_types": sorted(set(failures)),
        }

    @staticmethod
    def _persist_asset_provenance(output_dir, images, prompts, provider_name, job):
        records = []
        for index, image in enumerate(images):
            prompt = prompts[index] if index < len(prompts) else {}
            purpose = str(image.get("purpose") or prompt.get("purpose") or "topic-matched visual")
            section = str(image.get("section") or prompt.get("section") or image.get("role") or "")
            prompt_text = str(prompt.get("prompt") or purpose)
            records.append({
                "scene_id": section or f"asset_{index + 1}",
                "path": str(image.get("path") or ""),
                "source_url": f"generated:{provider_name}",
                "license": "generated_for_project",
                "semantic_match_score": 0.82,
                "match_reason": purpose,
                "semantic_tags": [value for value in [str(job.get("topic") or job.get("title") or ""), section] if value],
                "generation_evidence": {
                    "provider": provider_name,
                    "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
                    "role": str(image.get("role") or ""),
                },
                "render_evidence": {
                    "verified": bool(Path(str(image.get("path") or "")).is_file()),
                    "renderer": provider_name,
                    "artifact_sha256": str(image.get("checksum") or ""),
                },
            })
        (output_dir / "asset_provenance.json").write_text(json.dumps({"version": "asset_provenance_v1", "assets": records}, ensure_ascii=False, indent=2), encoding="utf-8")
        if any(str(image.get("role") or "").casefold() == "cover" for image in images):
            design = (job.get("draft_meta") or {}).get("cover_design") or {}
            platforms = [str(item).casefold() for item in job.get("platforms") or []]
            evidence = {
                "version": "cover_quality_evidence_v1",
                "platform": platforms[0] if platforms else "",
                "layout_key": design.get("layout_key"),
                "hook": design.get("hook"),
                "conflict_or_payoff": design.get("conflict_or_payoff"),
                "focal_subjects": design.get("focal_subjects") or [],
                "content_match_reason": design.get("content_match_reason") or design.get("topic_alignment"),
                "safe_zone_verified": design.get("safe_zone_verified") is True,
                "degraded": design.get("degraded") is True,
            }
            evidence_path = output_dir / "cover_quality_evidence.json"
            if not evidence_path.is_file():
                evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _required_image_count(job, cfg):
        if cfg.get("min_count") is not None:
            return max(1, int(cfg.get("min_count", 1)))
        platforms = {str(item).lower() for item in job.get("platforms", [])}
        body_length = len(str(job.get("body") or ""))
        video_platforms = platforms.intersection(
            {"kuaishou", "douyin", "douyin_ai", "tiktok", "shipinhao", "youtube", "youtube_shorts", "bilibili"}
        )
        # Short-video knowledge cards need one distinct real-scene background
        # per scene (8 scenes), never 1-3 reused images. Same-batch videos
        # must also differ, handled upstream by per-topic queries + md5 gate.
        if video_platforms:
            return 8
        if "xiaohongshu" in platforms:
            return 6
        if "juejin" in platforms:
            return 4
        if platforms.intersection({"wechat", "zhihu"}) or body_length >= 1000:
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
                "prompt": cls._cover_prompt(job),
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

    @classmethod
    def _cover_prompt(cls, job):
        meta = job.get("draft_meta") or {}
        design = meta.get("cover_design") if isinstance(meta.get("cover_design"), dict) else {}
        return str(design.get("background_prompt") or cls._image_prompt(job))

    @staticmethod
    def _article_sections(job):
        meta_sections = (job.get("draft_meta") or {}).get("sections") or []
        if isinstance(meta_sections, list) and meta_sections:
            return [str(item)[:80] for item in meta_sections if str(item).strip()]
        body = str(job.get("body") or "")
        parts = [part.strip().replace("\n", " ") for part in body.split("\n\n") if len(part.strip()) > 40]
        return [part[:80] for part in parts[:6]]

    @staticmethod
    def _video_duration(path):
        try:
            import subprocess as _sp
            d = _sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
            return round(float(d.stdout.strip()), 1)
        except Exception:
            return 0.0

    @classmethod
    def compile_video_script(cls, job):
        """Compile an article draft into bounded narration beats.

        Video renderers consume paragraph-separated narration. Passing an
        article body through unchanged makes one TTS segment arbitrarily long
        and can stall an entire overnight batch. The display article remains
        untouched; this only creates the dedicated spoken representation.
        """
        meta = job.get("draft_meta") or {}
        explicit = str(meta.get("video_script") or "").strip()
        body = str(job.get("body") or meta.get("video_prompt") or "").strip()
        raw = explicit or body
        if not raw:
            raise ValueError("video narration is missing")

        chunks = cls._video_script_chunks(raw)
        segments = []
        english = sum(ch.isascii() and ch.isalpha() for ch in raw) > sum("\u4e00" <= ch <= "\u9fff" for ch in raw) * 2
        if english:
            words = re.sub(r"\s+", " ", raw).strip().split()
            count = min(cls.VIDEO_SCRIPT_MAX_SEGMENTS, max(1, len(words)))
            base, extra = divmod(len(words), count)
            cursor = 0
            for index in range(count):
                size = base + (1 if index < extra else 0)
                segments.append(" ".join(words[cursor : cursor + size]))
                cursor += size
        for chunk in chunks:
            if english:
                break
            compact = re.sub(r"\s+", " ", chunk).strip(" -#*\t")
            while len(compact) > cls.VIDEO_SCRIPT_MAX_CHARS_PER_SEGMENT:
                cut = cls._video_script_cutpoint(compact, cls.VIDEO_SCRIPT_MAX_CHARS_PER_SEGMENT)
                # Do not create an unusable one-word tail. Move the split
                # back when enough text remains for a complete final beat.
                if len(compact) - cut < cls.VIDEO_SCRIPT_MIN_CHARS_PER_SEGMENT:
                    cut = max(
                        cls.VIDEO_SCRIPT_MIN_CHARS_PER_SEGMENT,
                        len(compact) - cls.VIDEO_SCRIPT_MIN_CHARS_PER_SEGMENT,
                    )
                segments.append(compact[:cut].strip())
                compact = compact[cut:].strip()
            if compact:
                segments.append(compact)
            if len(segments) >= cls.VIDEO_SCRIPT_MAX_SEGMENTS:
                break
        segments = [segment for segment in segments if segment][:cls.VIDEO_SCRIPT_MAX_SEGMENTS]
        if not segments:
            raise ValueError("video narration has no usable beats")

        normalized = "\n\n".join(segments)
        source = "explicit_video_script" if explicit and normalized == explicit else (
            "normalized_explicit_script" if explicit else "derived_from_draft"
        )
        return {
            "version": "video_script_v1",
            "source": source,
            "input_characters": len(raw),
            "output_characters": len(normalized),
            "segment_count": len(segments),
            "max_characters_per_segment": cls.VIDEO_SCRIPT_MAX_CHARS_PER_SEGMENT,
            "max_words_per_segment": max((len(segment.split()) for segment in segments), default=0) if english else 0,
            "segments": segments,
            "script": normalized,
        }

    @staticmethod
    def _video_script_chunks(text):
        cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", str(text))
        cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        chunks = []
        for paragraph in paragraphs or [cleaned]:
            chunks.extend(part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", paragraph) if part.strip())
        return chunks

    @staticmethod
    def _video_script_cutpoint(text, limit):
        for index in range(limit, max(1, limit - 12), -1):
            if text[index - 1] in "，。；：、！？!?;: ":
                return index
        return limit

    def _generate_video(self, job, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        script_contract = self.compile_video_script(job)
        script_body = script_contract["script"]
        (output_dir / "video_script_manifest.json").write_text(
            json.dumps(script_contract, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # ── visual-router 自动适配：结构化/知识内容 → 电影级视频管线 ──
        vr = job.get("visual_route") or {}
        video_cfg = self.config.get("video", {}) if isinstance(self.config.get("video", {}), dict) else {}
        meta = job.get("draft_meta") or {}
        requested_cinematic = bool(
            (vr.get("route_order") or [""])[0] == "cinema-video"
            or str(meta.get("quality_profile") or video_cfg.get("quality_profile") or os.environ.get("FILM_QUALITY_PROFILE", "")).casefold() == "high"
            or str(meta.get("motion_mode") or video_cfg.get("motion_mode") or os.environ.get("FILM_MOTION_MODE", "")).casefold() == "cinematic"
        )
        explicit_safe_mode = (
            str(meta.get("quality_profile") or video_cfg.get("quality_profile") or os.environ.get("FILM_QUALITY_PROFILE", "")).casefold() == "degraded"
            and str(meta.get("motion_mode") or video_cfg.get("motion_mode") or os.environ.get("FILM_MOTION_MODE", "")).casefold() == "safe"
            and (meta.get("allow_degraded") is True or video_cfg.get("allow_degraded") is True or os.environ.get("FILM_ALLOW_DEGRADED") == "1")
        )
        plan = dict(job.get("draft_meta", {}).get("video_toolchain_plan") or {})
        if requested_cinematic:
            plan.update({"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False})
        elif explicit_safe_mode:
            plan.update({"quality_profile": "degraded", "motion_mode": "safe", "allow_degraded": True})
        run_contract = (job.get("brief") or {}).get("run_contract") or (job.get("draft_meta") or {}).get("run_contract")
        if run_contract:
            plan["run_contract"] = run_contract
        provider = self._choose_video_provider(plan)
        if not provider:
            raise FileNotFoundError("video script not configured")
        visual_assets = self._prepare_video_visual_assets(job, output_dir, plan)
        # ``script_body`` is a separate, bounded narration contract. The
        # article stays long-form; a renderer must never infer narration from
        # the full body again.
        env = os.environ.copy()
        runtime_root = str(Path(__file__).resolve().parents[1])
        env["CONTENT_PLATFORM_HOME"] = runtime_root
        env["PYTHONPATH"] = runtime_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["FILM_QUALITY_PROFILE"] = str(plan.get("quality_profile") or "high")
        env["FILM_MOTION_MODE"] = str(plan.get("motion_mode") or "cinematic")
        env["FILM_ALLOW_DEGRADED"] = "1" if plan.get("allow_degraded") is True else "0"
        env["VIDEO_OUTPUT_DIR"] = str(output_dir)
        # Make the licensed local BGM fallback explicit for nested renderers;
        # do not rely on an inherited shell environment across adapters.
        if os.environ.get("BGM_LIBRARY_DIR"):
            env["BGM_LIBRARY_DIR"] = os.environ["BGM_LIBRARY_DIR"]
        if os.environ.get("BGM_LIBRARY_MANIFEST"):
            env["BGM_LIBRARY_MANIFEST"] = os.environ["BGM_LIBRARY_MANIFEST"]
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
        artifact = {
            "kind": "video",
            "path": str(output),
            "checksum": checksum,
            "render_manifest": manifest,
            "render_packet": self._renderer_packet(output_dir),
        }
        if self._visual_route:
            artifact["visual_route"] = self._visual_route
        if plan:
            artifact["toolchain_plan"] = str(output_dir / "video_toolchain_plan.json")
            artifact["selected_pipeline"] = str(plan.get("selected_pipeline", ""))
            artifact["template_family"] = str(plan.get("template_family", ""))
        if visual_assets:
            artifact["visual_assets"] = str(output_dir / "video_visual_assets.json")
        return artifact

    @staticmethod
    def _renderer_packet(output_dir):
        """Load measurements written by the renderer for the final gate."""
        path = Path(output_dir) / "packet.json"
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _prepare_video_visual_assets(self, job, output_dir, plan):
        selected_pipeline = str((plan or {}).get("selected_pipeline") or "")
        if selected_pipeline == "localized_repost_video":
            return {}
        image_paths = self._existing_image_paths(job, output_dir)
        image_cfg = dict(self.config.get("image", {}))
        required_count = max(1, int(self.config.get("video", {}).get("visual_image_count", 8)))
        if not image_paths and image_cfg.get("enabled", False):
            image_cfg.setdefault("min_count", required_count)
            job["_video_asset_generation"] = True
            try:
                image_artifact = self._generate_image(job, output_dir, image_cfg)
            finally:
                job.pop("_video_asset_generation", None)
            image_paths = [item["path"] for item in image_artifact.get("images", []) if Path(item.get("path", "")).is_file()]
        if not image_paths:
            return {}
        unique_image_paths = []
        seen_checksums = set()
        for image_path in image_paths:
            try:
                checksum = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
            except OSError:
                continue
            if checksum in seen_checksums:
                continue
            seen_checksums.add(checksum)
            unique_image_paths.append(image_path)
        image_paths = unique_image_paths
        if not image_paths:
            return {}
        provenance_by_path = {}
        provenance_path = output_dir / "asset_provenance.json"
        if provenance_path.is_file():
            try:
                payload = json.loads(provenance_path.read_text(encoding="utf-8"))
                for row in payload.get("assets") or []:
                    if isinstance(row, dict) and row.get("path"):
                        provenance_by_path[str(Path(row["path"]).resolve())] = row
            except (OSError, json.JSONDecodeError):
                provenance_by_path = {}
        backgrounds = output_dir / "backgrounds"
        backgrounds.mkdir(parents=True, exist_ok=True)
        assignments = []
        # Never fill missing scenes by cycling the same image. The renderer's
        # asset gate must receive the actual unique set so approved retrieval
        # or generation can add more material, otherwise the job fails closed.
        for index, image_path in enumerate(image_paths[:required_count]):
            source = Path(image_path)
            suffix = source.suffix if source.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"} else ".png"
            target = backgrounds / f"bg_{index + 1:02d}{suffix}"
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            evidence = provenance_by_path.get(str(source.resolve()), {})
            assignments.append(
                {
                    "scene": index + 1,
                    "source_image": str(source),
                    "background_image": str(target),
                    "reused": False,
                    "purpose": "scene background matched to narration and motion card",
                    "source_url": evidence.get("source_url", ""),
                    "license": evidence.get("license", ""),
                    "semantic_match_score": evidence.get("semantic_match_score", 0),
                    "match_reason": evidence.get("match_reason", ""),
                    "semantic_tags": evidence.get("semantic_tags", []),
                    "generation_evidence": evidence.get("generation_evidence", {}),
                }
            )
        return {
            "source": "media.image",
            "image_count": len(image_paths),
            "scene_count": len(assignments),
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
        renderer_id = str(((manifest.get("video_route") or {}).get("renderer_id") if isinstance(manifest.get("video_route"), dict) else "") or "")
        route_tools = {
            "landscape_explainer_renderer": {
                "render_landscape_video.slides", "render_landscape_video.playwright", "render_landscape_video.tts",
                "render_landscape_video.segments", "render_landscape_video.concat", "kuaishou_render.download_bgm",
                "mix_bgm_with_gate.mix_bgm", "render_landscape_video.subtitles", "render_landscape_video.encode_final",
                "visual_gate.py --cinema",
            },
            "real_footage_renderer": {
                "cinematic_v11.source_asset_gate", "cinematic_v11.tts", "kuaishou_render.download_bgm",
                "cinematic_v11.scene_compositor", "cinematic_v11.semantic_transitions", "cinematic_v11.subtitle_overlay",
                "cinematic_v11.audio_mix", "cinematic_v11.encode_final", "visual_gate.py --cinema",
            },
        }
        required_tools = route_tools.get(renderer_id, {
            "cinema_composition.storyboard", "shotcraft_moves.shot_plan_for_text", "shotcraft_moves.shot_sequence",
            "video_toolchain_runner.build_cards", "kuaishou_render.render_cards", "kuaishou_render.gen_tts",
            "kuaishou_render.render_segments", "kuaishou_render.concat_video", "kuaishou_render.download_bgm",
            "mix_bgm_with_gate.mix_bgm", "kuaishou_render.gen_subtitles", "kuaishou_render.encode_final",
            "visual_gate.py --cinema",
        })
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
        # Voice narration must never carry webpage scaffolding the model
        # copied from a source article (JS stubs, cookie banners, CSS vars).
        from .humanize import _strip_web_residue

        narration = _strip_web_residue(narration)
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
