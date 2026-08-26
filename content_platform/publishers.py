import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
from pathlib import Path

from .aitoearn import AitoEarnClient
from .auth_registry import resolve_cookie_file
from .content_policy import default_publisher_config, is_manual_handoff_platform, is_short_video_platform, is_xiaohongshu_platform, platform_region
from .formatters import format_for_platform
from .juejin_publisher import JuejinPublisher
from .media_quality import validate_article_packet
from .models import DeliveryResult
from .paths import project_home, social_auto_upload_home
from .publication_ledger import PublicationLedger
from .visual_content_policy import KNOWLEDGE_CARD_SKILL, packet_uses_current_policy
from .wechat_toolchain import TOOLCHAIN_META_KEYS
from .xiaohongshu_policy import build_recovery_strategy
from .zhihu_publisher import ZhihuPublisher
from scripts.deliver_media import deliver_xiaohongshu_package

AITOEARN_DISABLED_PLATFORMS = {"youtube", "tiktok", "twitter", "x", "threads"}
DOUYIN_ACCOUNT_VARIANTS = {"douyin_pet", "douyin_ai"}


def read_setting(name, env_file="", explicit=""):
    if explicit:
        return explicit
    if os.environ.get(name):
        return os.environ[name]
    if env_file and Path(env_file).is_file():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("'\"")
    return ""


class FileDraftPublisher:
    def __init__(self, outbox):
        self.outbox = Path(outbox)

    def deliver(self, job, platform):
        directory = self.outbox / platform
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{job['id']}.json"
        payload = {
            "job_id": job["id"],
            "platform": platform,
            "status": "drafted",
            "title": job["title"],
            "body": job["body"],
            "artifacts": job.get("artifacts", []),
            "platform_payload": format_for_platform(job, platform),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DeliveryResult(True, "drafted", str(path))


class ManualHandoffPublisher:
    """Write a handoff package and make the non-automatic status explicit."""

    def __init__(self, outbox, reason="manual publish required"):
        self.outbox = Path(outbox)
        self.reason = reason

    @staticmethod
    def _readable_artifacts(job, kind):
        readable = []
        for artifact in job.get("artifacts") or []:
            if not isinstance(artifact, dict) or artifact.get("kind") != kind:
                continue
            path = Path(str(artifact.get("path") or "")).expanduser()
            try:
                if path.is_file() and path.stat().st_size > 0:
                    with path.open("rb") as handle:
                        handle.read(1)
                    readable.append(str(path.resolve()))
            except OSError:
                continue
        return readable

    def _validate(self, job, platform, formatted):
        failures = []
        media_kind = "video" if is_short_video_platform(platform) or formatted.get("kind") == "video" else "image"
        media = self._readable_artifacts(job, media_kind)
        covers = self._readable_artifacts(job, "cover")
        if not media:
            failures.append(f"readable_{media_kind}_missing")
        if not covers:
            failures.append("readable_cover_missing")
        if set(media) & set(covers):
            failures.append("cover_must_be_distinct_from_content_media")
        title = str(formatted.get("title") or job.get("title") or "").strip()
        text = str(
            formatted.get("caption")
            or formatted.get("text")
            or formatted.get("markdown")
            or formatted.get("description")
            or job.get("body")
            or ""
        ).strip()
        if not title:
            failures.append("publish_title_missing")
        if not text:
            failures.append("publish_text_missing")
        return failures

    def deliver(self, job, platform):
        directory = self.outbox / platform
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{job['id']}.json"
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        failures = self._validate(job, platform, formatted)
        payload = {
            "job_id": job["id"],
            "platform": platform,
            "status": "blocked" if failures else "handoff_pending",
            "live_publish": False,
            "reason": self.reason,
            "title": job["title"],
            "body": job["body"],
            "artifacts": job.get("artifacts", []),
            "platform_payload": formatted,
            "validation_failures": failures,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if failures:
            return DeliveryResult(False, "blocked", str(path), error=f"{self.reason}; manual handoff package incomplete: " + ",".join(failures))
        return DeliveryResult(True, "handoff_pending", str(path), error=self.reason)


class XiaohongshuManualHandoffPublisher:
    """Create and deliver a verified user-only Xiaohongshu handoff package.

    This publisher deliberately has no uploader fallback.  A package is not
    handoff-ready until the full text and every image have been sent through
    the configured Hermes delivery target.
    """

    def __init__(self, outbox):
        self.outbox = Path(outbox)

    @staticmethod
    def _images(job):
        paths = []
        for artifact in job.get("artifacts", []):
            if not isinstance(artifact, dict) or artifact.get("kind") not in {"image", "cover"}:
                continue
            path = Path(str(artifact.get("path") or "")).expanduser()
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                resolved = str(path.resolve())
                if resolved not in paths:
                    paths.append(resolved)
        return paths

    @staticmethod
    def _guide():
        return (
            "请在小红书 App 或创作者中心手动上传以下图片，按给定顺序填写标题、正文和话题；"
            "核对图片、敏感词和排版后，仅由账号所有者点击发布。发布后再手动确认数据。"
        )

    def deliver(self, job, platform):
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        images = self._images(job)
        payload = {
            "job_id": job["id"],
            "platform": "xiaohongshu",
            "status": "handoff_pending",
            "publish_mode": "manual",
            "live_publish": False,
            "title": str(formatted.get("title") or job.get("title") or "")[:20],
            "body": str(formatted.get("text") or job.get("body") or ""),
            "topics": list(formatted.get("hashtags") or [])[:6],
            "cover": images[0] if images else "",
            "images": images,
            "manual_publish_guide": self._guide(),
            "postcheck": "user_manual_publish_confirmation",
            "growth_strategy": build_recovery_strategy(job, formatted),
        }
        directory = self.outbox / "xiaohongshu"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{job['id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        from scripts.xhs_manual_publish_gate import check_handoff_package

        gate = check_handoff_package(str(path))
        if not gate.get("passed"):
            return DeliveryResult(False, "blocked", str(path), error="xiaohongshu handoff gate failed: " + ",".join(gate.get("failures", [])))
        receipt = deliver_xiaohongshu_package(path)
        payload["operator_delivery"] = receipt
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not receipt.get("passed"):
            return DeliveryResult(False, "blocked", str(path), error="xiaohongshu operator delivery failed: " + str(receipt.get("error") or "unknown"))
        return DeliveryResult(True, "handoff_pending", str(path), error="Xiaohongshu manual publish required")


class RedditDraftPublisher:
    def __init__(self, outbox, default_subreddit=""):
        self.outbox = Path(outbox)
        self.default_subreddit = default_subreddit

    def deliver(self, job, platform):
        directory = self.outbox / "reddit"
        directory.mkdir(parents=True, exist_ok=True)
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        subreddit = (
            job.get("draft_meta", {}).get("subreddit")
            or formatted.get("subreddit")
            or self.default_subreddit
            or "manual-selection"
        )
        formatted["subreddit"] = subreddit
        payload = {
            "job_id": job["id"],
            "platform": "reddit",
            "status": "review_required",
            "live_publish": False,
            "title": job["title"],
            "body": job["body"],
            "platform_payload": formatted,
            "safety_notes": [
                "human review required before posting",
                "do not duplicate substantially similar posts across subreddits",
                "follow subreddit rules and disclose affiliation when relevant",
            ],
        }
        path = directory / f"{job['id']}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DeliveryResult(True, "review_required", str(path), error="reddit draft requires human review")


class DevtoDraftPublisher:
    def __init__(self, api_key_env="DEVTO_API_KEY", env_file="", api_key=""):
        self.api_key_env = api_key_env
        self.env_file = env_file
        self.api_key = api_key

    def deliver(self, job, platform):
        key = read_setting(self.api_key_env, self.env_file, self.api_key)
        if not key:
            return DeliveryResult(False, "blocked", error=f"missing environment variable: {self.api_key_env}")
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        payload = {
            "article": {
                "title": formatted.get("title", job["title"])[:128],
                "body_markdown": formatted.get("markdown", job["body"]),
                "published": False,
            }
        }
        request = urllib.request.Request(
            "https://dev.to/api/articles",
            data=json.dumps(payload).encode(),
            headers={
                "api-key": key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "HermesContentPlatform/3.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read())
            return DeliveryResult(True, "drafted", str(result.get("id", "")))
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])


class WechatDraftPublisher:
    def __init__(self, app_id_env="WECHAT_APP_ID", app_secret_env="WECHAT_APP_SECRET", env_file="", app_id="", app_secret=""):
        self.app_id_env = app_id_env
        self.app_secret_env = app_secret_env
        self.env_file = env_file
        self.app_id = app_id
        self.app_secret = app_secret

    def deliver(self, job, platform):
        app_id = read_setting(self.app_id_env, self.env_file, self.app_id)
        secret = read_setting(self.app_secret_env, self.env_file, self.app_secret)
        if not app_id or not secret:
            return DeliveryResult(False, "blocked", error="missing WeChat app credentials")
        try:
            token_url = "https://api.weixin.qq.com/cgi-bin/token?" + urllib.parse.urlencode(
                {"grant_type": "client_credential", "appid": app_id, "secret": secret}
            )
            with urllib.request.urlopen(urllib.request.Request(token_url), timeout=30) as response:
                token_result = json.loads(response.read())
            token = token_result.get("access_token", "")
            if not token:
                return DeliveryResult(False, "failed", error=f"WeChat token error code: {token_result.get('errcode', 'unknown')}")
            image = next(
                (Path(item["path"]) for item in job.get("artifacts", []) if item.get("kind") == "image" and Path(item["path"]).is_file()),
                None,
            )
            if not image:
                return DeliveryResult(False, "failed", error="WeChat draft requires an image artifact")
            boundary = "----Hermes" + uuid.uuid4().hex
            file_data = image.read_bytes()
            upload_body = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"{image.name}\"\r\n"
                f"Content-Type: image/png\r\n\r\n"
            ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
            upload = urllib.request.Request(
                "https://api.weixin.qq.com/cgi-bin/material/add_material?" + urllib.parse.urlencode({"access_token": token, "type": "image"}),
                data=upload_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(upload, timeout=60) as response:
                material_result = json.loads(response.read())
            thumb_media_id = material_result.get("media_id", "")
            if not thumb_media_id:
                return DeliveryResult(False, "failed", error=f"WeChat material error code: {material_result.get('errcode', 'unknown')}")
            formatted = job.get("platform_payload") or format_for_platform(job, platform)
            article = {
                "title": formatted.get("title", job["title"])[:64],
                "content": formatted.get("html", job["body"]),
                "digest": formatted.get("summary", "")[:54],
                "author": "Hermes",
                "need_open_comment": 1,
                "only_fans_can_comment": 0,
                "thumb_media_id": thumb_media_id,
            }
            request = urllib.request.Request(
                "https://api.weixin.qq.com/cgi-bin/draft/add?" + urllib.parse.urlencode({"access_token": token}),
                data=json.dumps({"articles": [article]}, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read())
            if result.get("media_id"):
                return DeliveryResult(True, "drafted", result["media_id"])
            return DeliveryResult(False, "failed", error=f"WeChat draft error code: {result.get('errcode', 'unknown')}")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])


class HermesWechatAdapter:
    """Delegate WeChat drafting to the Hermes article toolchain.

    This path is intentionally stricter than the legacy direct API publisher:
    it requires the channel visual policy, article packet quality gates, theme
    selection evidence, inline image mapping, and adapter postcheck.
    """

    def __init__(self, data_dir, env_file="", command="", python_bin="", timeout=600, require_cn_proxy=True):
        self.data_dir = Path(data_dir)
        self.env_file = env_file
        self.command = command
        self.python_bin = python_bin or os.environ.get("PYTHON") or sys.executable
        self.timeout = int(timeout or 600)
        self.require_cn_proxy = bool(require_cn_proxy)

    def deliver(self, job, platform):
        packet = self._packet(job, platform)
        validation_error = self._validation_error(packet)
        if validation_error:
            return DeliveryResult(False, "blocked", error=validation_error)
        if self.require_cn_proxy and not read_setting("CN_PROXY", self.env_file):
            return DeliveryResult(False, "blocked", error="missing CN_PROXY for WeChat Hermes adapter")
        runner = Path(self.command or os.environ.get("HERMES_WECHAT_ADAPTER_COMMAND", ""))
        if not str(runner):
            runner = project_home() / "scripts" / "hermes_wechat_adapter.py"
        if not runner.is_file():
            return DeliveryResult(False, "blocked", error=f"Hermes WeChat adapter command not found: {runner}")
        run_dir = self.data_dir / "runtime" / "wechat_adapter" / str(job.get("id", uuid.uuid4().hex))
        run_dir.mkdir(parents=True, exist_ok=True)
        input_path = run_dir / "input.json"
        output_path = run_dir / "result.json"
        input_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        env = os.environ.copy()
        self._load_env_file(env)
        try:
            proc = subprocess.run(
                [self.python_bin, str(runner), "--input", str(input_path), "--output", str(output_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=self.timeout,
            )
        except Exception as exc:
            return DeliveryResult(False, "failed", error=f"Hermes WeChat adapter failed to start: {str(exc)[:300]}")
        if proc.returncode != 0 and not output_path.is_file():
            return DeliveryResult(False, "failed", error=(proc.stderr or proc.stdout or "Hermes WeChat adapter failed")[:500])
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return DeliveryResult(False, "failed", error=f"Hermes WeChat adapter returned no valid JSON: {str(exc)[:200]}")
        postcheck = result.get("postcheck") or {}
        media_id = str(result.get("media_id") or result.get("external_id") or "")
        evidence = str(result.get("evidence_path") or result.get("error") or "")[:300]
        if result.get("ok") and media_id and postcheck.get("passed"):
            return DeliveryResult(True, "drafted", media_id, error=evidence)
        if media_id:
            return DeliveryResult(True, "handoff_pending", media_id, error="WeChat draft submitted but batchget postcheck is missing or failed")
        return DeliveryResult(False, str(result.get("status") or "failed"), error=str(result.get("error") or "WeChat adapter failed")[:500])

    def _load_env_file(self, env):
        if not self.env_file or not Path(self.env_file).is_file():
            return
        for line in Path(self.env_file).read_text(encoding="utf-8").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() and key.strip() not in env:
                env[key.strip()] = value.strip().strip("'\"")

    def _packet(self, job, platform):
        packet = dict(job)
        draft_meta = job.get("draft_meta") or {}
        if isinstance(draft_meta, dict):
            for key in TOOLCHAIN_META_KEYS:
                if key in draft_meta and key not in packet:
                    packet[key] = draft_meta[key]
        packet["platform"] = platform
        packet["platform_payload"] = job.get("platform_payload") or format_for_platform(job, platform)
        return packet

    def _validation_error(self, job):
        if not packet_uses_current_policy(job):
            return "WeChat packet missing current visual_content_design_policy_v1"
        quality = validate_article_packet(job)
        if not quality.get("passed"):
            return "WeChat packet failed media quality gates: " + ",".join(quality.get("failed_dimensions", []))
        mapping = job.get("section_image_map") or []
        if len(mapping) < 3:
            return "WeChat packet requires at least 3 inline section images"
        card_plan = job.get("knowledge_card_plan") or {}
        if str(card_plan.get("skill", "")) != KNOWLEDGE_CARD_SKILL:
            return "WeChat packet must use Hermes knowledge-card-designer skill"
        policy = job.get("visual_content_policy") or {}
        refs = policy.get("tool_refs") or {}
        missing = [
            key for key in ["image_generation_engine", "wechat_theme_renderer", "wechat_publisher"]
            if not str(refs.get(key, "")).startswith("hermes_tool:")
        ]
        if missing:
            return "WeChat visual policy missing tool refs: " + ",".join(missing)
        requirements = policy.get("wechat_requirements") or {}
        overrides = policy.get("platform_overrides") or {}
        if isinstance(overrides.get("wechat"), dict):
            requirements = {**requirements, **(overrides.get("wechat", {}).get("wechat_requirements") or {})}
        if int(requirements.get("theme_count_required", 0)) < 109:
            return "WeChat visual policy must require 109 themes"
        strategy = job.get("strategy_brief") or {}
        for key in ["seo_geo_intent", "selected_theme_reason"]:
            if not strategy.get(key):
                return f"WeChat strategy brief missing {key}"
        invocations = job.get("tool_invocations") or {}
        wewrite = invocations.get("wewrite") or {}
        hermes_writer = invocations.get("hermes_writer") or {}
        wewrite_commands = [item.get("name") for item in wewrite.get("commands", []) if isinstance(item, dict)]
        hermes_commands = [item.get("name") for item in hermes_writer.get("commands", []) if isinstance(item, dict)]
        wewrite_used = wewrite.get("status") == "used" and "llm-write" in wewrite_commands
        hermes_used = hermes_writer.get("status") == "used" and "hermes --cli" in hermes_commands
        if not (wewrite_used or hermes_used):
            return "WeChat packet requires successful WeWrite llm-write or Hermes writer invocation evidence"
        return ""


class SocialAutoUploadPublisher:
    def __init__(
        self,
        platform_name,
        account_name,
        project_dir=str(social_auto_upload_home()),
        python_bin=str(social_auto_upload_home() / "venv/bin/python"),
        schedule_at="2099-12-31 23:59",
        extra_args=None,
        video_extra_args=None,
        note_extra_args=None,
        schedule_delay_hours=2,
        postcheck_callback=None,
    ):
        self.platform_name = platform_name
        self.account_name = account_name
        self.project_dir = project_dir
        self.python_bin = python_bin
        self.schedule_at = schedule_at
        self.schedule_delay_hours = int(schedule_delay_hours or 2)
        self.extra_args = list(extra_args or [])
        self.video_extra_args = list(video_extra_args or [])
        self.note_extra_args = list(note_extra_args or [])
        self.postcheck_callback = postcheck_callback
        self.delivery_callback = None

    def set_delivery_callback(self, callback):
        self.delivery_callback = callback

    def set_postcheck_callback(self, callback):
        self.postcheck_callback = callback

    def _emit_delivery(self, event):
        if callable(self.delivery_callback):
            return self.delivery_callback(dict(event))
        return None

    def _run(self, args):
        command = [self.python_bin, "sau_cli.py", self.platform_name, *args]
        return subprocess.run(command, cwd=self.project_dir, capture_output=True, text=True, timeout=900)

    def _schedule_at(self):
        if str(self.schedule_at).strip().lower() != "auto":
            return self.schedule_at
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + self.schedule_delay_hours * 3600))

    def _management_page_postcheck(self, intent):
        """Use the checked-in browser postcheck unless a test callback is injected."""
        description = str(intent.get("expected_description") or "")
        with tempfile.TemporaryDirectory(prefix="kuaishou-postcheck-") as tmp:
            out_dir = Path(tmp)
            manifest = out_dir / "manifest.json"
            manifest.write_text(json.dumps({
                "account": intent["internal_account_alias"],
                "title": intent["expected_title"],
                "description": description,
                "schedule_time": intent["scheduled_at"],
            }, ensure_ascii=False), encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "scripts" / "kuaishou_postcheck_manifest.py"
            try:
                process = subprocess.run(
                    [self.python_bin, str(script), str(manifest), str(out_dir / "postcheck")],
                    cwd=str(script.parents[1]), capture_output=True, text=True, timeout=180,
                )
            except Exception as exc:
                return {"postcheck_status": "postcheck_failed", "error": str(exc)[:300]}
            report_path = out_dir / "postcheck" / "postcheck.json"
            if not report_path.is_file():
                return {"postcheck_status": "postcheck_missing", "error": (process.stderr or process.stdout or "postcheck report missing")[:300]}
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return {"postcheck_status": "postcheck_invalid", "error": str(exc)[:300]}
            if not report.get("passed") or process.returncode != 0:
                return {"postcheck_status": str(report.get("status") or "postcheck_failed"), "report": report}
            evidence_path = str(report.get("evidence_path") or "")
            if evidence_path and not Path(evidence_path).is_absolute():
                evidence_path = str((out_dir / "postcheck" / evidence_path).resolve())
            return {
                "account_alias": intent["internal_account_alias"],
                "title": intent["expected_title"],
                "description_digest": hashlib.sha256(description.encode("utf-8")).hexdigest(),
                "scheduled_at": intent["scheduled_at"],
                "screenshot_path": evidence_path,
                "postcheck_report": report,
            }

    def _video_file(self, job):
        for item in job.get("artifacts", []):
            if item.get("kind") == "video" and Path(item.get("path", "")).is_file():
                return item["path"]
        return ""

    def _image_files(self, job):
        files = []
        for item in job.get("artifacts", []):
            if item.get("kind") == "image" and Path(item.get("path", "")).is_file():
                files.append(item["path"])
        return files

    def poll_delivery_intent(self, intent):
        if self.platform_name.casefold() != "kuaishou":
            return {"status": "inconclusive", "reason": "publisher has no immutable-identity postcheck"}
        evidence = self.postcheck_callback(intent) if callable(self.postcheck_callback) else self._management_page_postcheck(intent)
        check = PublicationLedger.validate_kuaishou_scheduled_postcheck(intent, evidence)
        if check["passed"]:
            return {"status": "scheduled", "postcheck": check}
        report = evidence.get("postcheck_report") if isinstance(evidence, dict) else {}
        report_status = str((report or {}).get("status") or evidence.get("postcheck_status") or "").casefold() if isinstance(evidence, dict) else ""
        if report_status in {"not_found", "absent"} and (evidence.get("screenshot_path") or evidence.get("dom")):
            return {"status": "absent", "postcheck": check}
        return {"status": "inconclusive", "reason": "management-page postcheck did not prove presence or absence", "postcheck": check}

    def deliver(self, job, platform):
        if self.platform_name.casefold() in {"xiaohongshu", "xhs", "rednote"}:
            return DeliveryResult(
                False,
                "blocked",
                error="xiaohongshu manual publish only: automatic uploader routes are permanently disabled",
            )
        check = self._run(["check", "--account", self.account_name])
        if check.returncode != 0:
            return DeliveryResult(False, "blocked", error=f"social-auto-upload check failed for {self.platform_name}: {check.stderr[:200] or check.stdout[:200]}")
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        title = formatted.get("title", job.get("title", ""))[:100]
        tags = ",".join(tag.lstrip("#") for tag in formatted.get("hashtags", [])[:8])
        if formatted.get("kind") == "video":
            video_path = self._video_file(job)
            if not video_path:
                return DeliveryResult(False, "blocked", error="social-auto-upload requires a video artifact")
            args = [
                "upload-video",
                "--account", self.account_name,
                "--file", video_path,
                "--title", title,
                "--desc", formatted.get("caption", job.get("body", ""))[:500],
                "--schedule", self._schedule_at(),
            ]
            if tags:
                args.extend(["--tags", tags])
            args.extend(self.video_extra_args)
        else:
            images = self._image_files(job)
            if not images:
                return DeliveryResult(False, "blocked", error="social-auto-upload note mode requires image artifacts")
            args = [
                "upload-note",
                "--account", self.account_name,
                "--title", title[:30],
                "--note", formatted.get("text", formatted.get("markdown", job.get("body", "")))[:1000],
                "--schedule", self._schedule_at(),
                "--images",
                *images,
            ]
            if tags:
                args.extend(["--tags", tags])
            args.extend(self.note_extra_args)
        args.extend(self.extra_args)
        upload = self._run(args)
        if upload.returncode == 0:
            info = (upload.stdout or "").strip()[:300]
            if self.platform_name.casefold() == "kuaishou":
                schedule = self._schedule_at()
                description = str(formatted.get("caption") or formatted.get("description") or job.get("body") or "")
                intent = {
                    "platform": "kuaishou",
                    "internal_account_alias": self.account_name,
                    "expected_title": title,
                    "expected_description": description,
                    "expected_description_digest": hashlib.sha256(description.encode("utf-8")).hexdigest(),
                    "scheduled_at": schedule,
                }
                evidence = self.postcheck_callback(intent) if callable(self.postcheck_callback) else self._management_page_postcheck(intent)
                check = PublicationLedger.validate_kuaishou_scheduled_postcheck(intent, evidence)
                event = {"status": "scheduled" if check["passed"] else "unknown_requires_review", "postcheck": check, "external_id": f"{self.platform_name}:{self.account_name}"}
                self._emit_delivery(event)
                if not check["passed"]:
                    return DeliveryResult(False, "unknown_requires_review", event["external_id"], error="Kuaishou management-page postcheck is required")
                return DeliveryResult(True, "scheduled", event["external_id"], error=f"scheduled via social-auto-upload: {info}")
            return DeliveryResult(True, "drafted", f"{self.platform_name}:{self.account_name}", error=f"scheduled via social-auto-upload: {info}")
        return DeliveryResult(False, "failed", error=(upload.stderr or upload.stdout)[:300])


class FallbackPublisher:
    def __init__(self, publishers):
        self.publishers = list(publishers)

    def deliver(self, job, platform):
        errors = []
        for publisher in self.publishers:
            result = publisher.deliver(job, platform)
            if result.ok:
                return result
            errors.append(result.error or result.status)
        return DeliveryResult(False, "blocked", error="; ".join(errors)[-500:])


class XPlaywrightPublisher:
    """Post to X/Twitter with an operator-provided browser cookie state."""

    def __init__(self, account="main", cookie_dir="", proxy="", headless=True, timeout=900, live=True):
        self.account = account
        self.cookie_dir = cookie_dir
        self.proxy = proxy
        self.headless = bool(headless)
        self.timeout = int(timeout or 900)
        self.live = bool(live)

    def _compose_text(self, job, platform):
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        text = (
            formatted.get("text")
            or formatted.get("caption")
            or formatted.get("markdown")
            or f"{job.get('title', '')}\n\n{job.get('body', '')}"
        )
        return str(text).strip()[:280]

    def deliver(self, job, platform):
        if not self.live:
            return DeliveryResult(False, "blocked", error="X live publishing disabled in publisher config")
        cookie_file = resolve_cookie_file("twitter", self.account, self.cookie_dir)
        if not cookie_file.is_file():
            return DeliveryResult(False, "blocked", error="X/Twitter cookie not found")
        text = self._compose_text(job, platform)
        if len(text) < 8:
            return DeliveryResult(False, "blocked", error="X/Twitter post text too short")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return DeliveryResult(False, "blocked", error="playwright not installed")
        try:
            storage = json.loads(cookie_file.read_text(encoding="utf-8"))
        except Exception:
            return DeliveryResult(False, "blocked", error="X/Twitter cookie file invalid")
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=self.headless, args=["--no-sandbox"])
                context_kwargs = {
                    "storage_state": storage if isinstance(storage, dict) else {"cookies": storage},
                    "locale": "en-US",
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                }
                if self.proxy:
                    context_kwargs["proxy"] = {"server": self.proxy}
                context = browser.new_context(**context_kwargs)
                page = context.new_page()
                page.goto("https://x.com/compose/post", timeout=self.timeout * 1000, wait_until="domcontentloaded")
                box = page.locator('[data-testid="tweetTextarea_0"]').first
                box.wait_for(timeout=30000)
                box.fill(text)
                button = page.locator('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]').first
                button.click(timeout=30000)
                page.wait_for_timeout(5000)
                browser.close()
            return DeliveryResult(True, "published", f"x:{job.get('id', '')}", error="X/Twitter post submitted via cookie browser session")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=f"X/Twitter browser publish failed: {str(exc)[:300]}")


class TelegraphPublisher:
    def __init__(self, live_enabled=False, token_env="TELEGRAPH_TOKEN", env_file=""):
        self.live_enabled = live_enabled
        self.token_env = token_env
        self.env_file = env_file

    def deliver(self, job, platform):
        if not self.live_enabled:
            return DeliveryResult(False, "blocked", error="live publishing is disabled")
        token = read_setting(self.token_env, self.env_file)
        if not token:
            return DeliveryResult(False, "blocked", error=f"missing environment variable: {self.token_env}")
        content = json.dumps([{"tag": "p", "children": [job["body"][:10000]]}], ensure_ascii=False)
        data = urllib.parse.urlencode(
            {"access_token": token, "title": job["title"][:256], "author_name": "Hermes", "content": content}
        ).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request("https://api.telegra.ph/createPage", data=data), timeout=30) as response:
                result = json.loads(response.read())
            if result.get("ok"):
                return DeliveryResult(True, "published", result["result"].get("url", ""))
            return DeliveryResult(False, "failed", error=str(result.get("error", "unknown error")))
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])


class YouTubePublisher:
    def __init__(self, client_id_env="YOUTUBE_CLIENT_ID", client_secret_env="YOUTUBE_CLIENT_SECRET",
                 refresh_token_env="YOUTUBE_REFRESH_TOKEN", env_file="", privacy="unlisted",
                 client_id="", client_secret="", refresh_token=""):
        self.client_id_env = client_id_env
        self.client_secret_env = client_secret_env
        self.refresh_token_env = refresh_token_env
        self.env_file = env_file
        self.privacy = privacy
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token

    def _get_access_token(self):
        cid = read_setting(self.client_id_env, self.env_file, self.client_id)
        csc = read_setting(self.client_secret_env, self.env_file, self.client_secret)
        rtk = read_setting(self.refresh_token_env, self.env_file, self.refresh_token)
        if not all([cid, csc, rtk]):
            raise ValueError("missing YouTube OAuth credentials (client_id, client_secret, refresh_token)")
        data = urllib.parse.urlencode({
            "client_id": cid, "client_secret": csc, "refresh_token": rtk, "grant_type": "refresh_token"
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]

    def deliver(self, job, platform):
        try:
            token = self._get_access_token()
        except Exception as exc:
            return DeliveryResult(False, "blocked", error=f"YouTube auth failed: {str(exc)[:200]}")
        video_file = next(
            (Path(item["path"]) for item in job.get("artifacts", [])
             if item.get("kind") == "video" and Path(item["path"]).is_file()),
            None,
        )
        if not video_file:
            return DeliveryResult(False, "blocked", error="YouTube requires a video artifact")
        try:
            formatted = job.get("platform_payload") or format_for_platform(job, platform)
            snippet = {
                "title": formatted.get("title", job["title"])[:100],
                "description": formatted.get("caption", job["body"])[:5000],
            }
            tags = formatted.get("hashtags", [])
            if tags:
                snippet["tags"] = [t.lstrip("#") for t in tags[:20]]
            metadata = json.dumps({"snippet": snippet, "status": {"privacyStatus": self.privacy}}).encode()
            file_bytes = video_file.read_bytes()
            boundary = "youtube_hermes_" + uuid.uuid4().hex
            body = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{metadata.decode()}\r\n"
                f"--{boundary}\r\nContent-Type: video/mp4\r\n\r\n"
            ).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                "https://www.googleapis.com/upload/youtube/v3/videos?part=snippet,status",
                data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                    "User-Agent": "HermesContentPlatform/3.0",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            video_id = result.get("id", "")
            if video_id:
                url = f"https://youtube.com/watch?v={video_id}"
                return DeliveryResult(True, "drafted", video_id, error=url)
            return DeliveryResult(False, "failed", error=f"YouTube response missing id: {str(result)[:200]}")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])


class BilibiliPublisher:
    def __init__(self, sessdata_env="BILIBILI_SESSDATA", bili_jct_env="BILIBILI_JCT",
                 env_file="", sessdata="", bili_jct=""):
        self.sessdata_env = sessdata_env
        self.bili_jct_env = bili_jct_env
        self.env_file = env_file
        self.sessdata = sessdata
        self.bili_jct = bili_jct

    def deliver(self, job, platform):
        sessdata = read_setting(self.sessdata_env, self.env_file, self.sessdata)
        bili_jct = read_setting(self.bili_jct_env, self.env_file, self.bili_jct)
        if not sessdata:
            return DeliveryResult(False, "blocked", error="missing Bilibili SESSDATA cookie")
        cookie = f"SESSDATA={sessdata}"
        if bili_jct:
            cookie += f"; bili_jct={bili_jct}"
        try:
            formatted = job.get("platform_payload") or format_for_platform(job, platform)
            if formatted.get("kind") == "video":
                return DeliveryResult(False, "failed", error="Bilibili video upload requires AiToEarn or browser automation")
            body = {
                "title": formatted.get("title", job["title"])[:80],
                "content": formatted.get("markdown", job["body"]),
                "category": 4,
                "original": 1,
                "words": len(job["body"]),
                "summary": formatted.get("caption", "")[:100],
                "list_id": 0,
                "tid": 0,
                "reprint": 0,
                "image_urls": "",
                "origin_image_urls": "",
                "dynamic_intro": "",
                "media_id": 0,
                "spoiler": 0,
                "csrf": bili_jct or "",
                "from": "hermes",
            }
            data = json.dumps(body, ensure_ascii=False).encode()
            req = urllib.request.Request(
                "https://api.bilibili.com/x/article/creative/draft/addupdate",
                data=data,
                headers={
                    "Cookie": cookie,
                    "Content-Type": "application/json; charset=utf-8",
                    "Referer": "https://member.bilibili.com/platform/upload/text/edit",
                    "Origin": "https://member.bilibili.com",
                    "User-Agent": "HermesContentPlatform/3.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            if result.get("code") == 0:
                aid = result.get("data", {}).get("id", "")
                return DeliveryResult(True, "drafted", str(aid))
            return DeliveryResult(False, "failed", error=f"Bilibili code={result.get('code')}: {result.get('message', 'unknown')}")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])


def _ayrshare_platform(platform):
    platform = str(platform).lower()
    return "twitter" if platform == "x" else platform


def _aitoearn_platform(platform):
    mapping = {
        "xiaohongshu": "xhs",
        "rednote": "xhs",
        "shipinhao": "wxSph",
        "kuaishou": "KWAI",
        "wechat": "wxGzh",
        "weixin": "wxGzh",
    }
    return mapping.get(str(platform), str(platform))


def _public_media_urls(artifacts):
    urls = []
    for item in artifacts:
        if item.get("kind") not in {"image", "video"}:
            continue
        value = item.get("url") or item.get("public_url") or item.get("path", "")
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            urls.append(value)
    return urls[:4]


def _first_public_media(job, kinds):
    for item in job.get("artifacts", []):
        if item.get("kind") in kinds:
            value = item.get("url") or item.get("public_url") or item.get("path", "")
            if isinstance(value, str) and value.startswith(("https://", "http://")):
                return value
    return ""


class AiToEarnDraftPublisher:
    def __init__(
        self,
        base_url="https://aitoearn.cn/api/unified/mcp",
        api_key_env="AITOEARN_API_KEY",
        env_file="",
        api_key="",
        image_model="gpt-image-2",
        video_model="grok-imagine-video",
        image_count=3,
        poll_attempts=10,
        poll_interval=2,
        client=None,
    ):
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.env_file = env_file
        self.api_key = api_key
        self.image_model = image_model
        self.video_model = video_model
        self.image_count = int(image_count)
        self.poll_attempts = int(poll_attempts)
        self.poll_interval = float(poll_interval)
        self.client = client

    def _client(self):
        if self.client:
            return self.client
        key = read_setting(self.api_key_env, self.env_file, self.api_key)
        if not key:
            return None
        return AitoEarnClient(self.base_url, key)

    def deliver(self, job, platform):
        client = self._client()
        if not client:
            return DeliveryResult(False, "blocked", error=f"missing environment variable: {self.api_key_env}")
        target = _aitoearn_platform(platform)
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        is_video = formatted.get("kind") == "video" or target in {"douyin", "wxSph", "bilibili", "youtube", "KWAI", "tiktok"}
        caption = "\n".join(
            part for part in [formatted.get("title", job.get("title", "")), formatted.get("caption"), formatted.get("text"), job.get("body", "")]
            if part
        )[:1800]
        if is_video:
            result = client.create_video_draft(
                model=self.video_model,
                prompt=formatted.get("script", job.get("body", ""))[:1800] or job.get("title", ""),
                captionPrompt=caption,
                draftType="draft",
                platforms=[target],
                imageUrls=_public_media_urls(job.get("artifacts", []))[:3],
                disableMemory=True,
            )
        else:
            result = client.create_image_text_draft(
                prompt=formatted.get("text", job.get("body", ""))[:1800] or job.get("title", ""),
                captionPrompt=caption,
                imageModel=self.image_model,
                draftType="draft",
                platforms=[target],
                imageUrls=_public_media_urls(job.get("artifacts", []))[:9],
                imageCount=self.image_count,
                disableMemory=True,
            )
        task_id = next(iter(result.get("task_ids", [])), "")
        if not task_id:
            return DeliveryResult(False, "failed", error=f"AiToEarn draft task id missing: {result.get('raw_text', '')[:300]}")
        for _ in range(max(1, self.poll_attempts)):
            try:
                status = client.get_draft_task_status(task_id)
            except Exception as exc:
                return DeliveryResult(True, "drafted", task_id, error=f"AiToEarn draft pending after status probe failure: {str(exc)[:200]}")
            if status.get("status") == "success":
                return DeliveryResult(True, "drafted", status.get("draft_id", task_id), error=status.get("raw_text", "")[:300])
            if status.get("status") == "failed":
                return DeliveryResult(False, "failed", error=status.get("raw_text", "")[:300])
            if self.poll_interval:
                time.sleep(self.poll_interval)
        return DeliveryResult(True, "drafted", task_id, error=f"AiToEarn draft still generating: {task_id}")


class AiToEarnFlowPublisher:
    def __init__(
        self,
        account_id="",
        base_url="https://aitoearn.cn/api/unified/mcp",
        api_key_env="AITOEARN_API_KEY",
        env_file="",
        api_key="",
        option=None,
        delivery_status="drafted",
        poll_attempts=12,
        poll_interval=5,
        client=None,
    ):
        self.account_id = account_id
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.env_file = env_file
        self.api_key = api_key
        self.option = option or {}
        self.delivery_status = delivery_status
        self.poll_attempts = int(poll_attempts)
        self.poll_interval = float(poll_interval)
        self.client = client

    def _client(self):
        if self.client:
            return self.client
        key = read_setting(self.api_key_env, self.env_file, self.api_key)
        if not key:
            return None
        return AitoEarnClient(self.base_url, key)

    def _check_youtube_duplicate(self, client, title):
        """Two-source duplicate check: publish records (ALL uploads) + channel works (visible)."""
        if not title:
            return False
        normalized = title.strip().lower()
        try:
            records = client.list_channel_publish_records(platform="youtube", page_size=200)
            for t in records.get("titles", []):
                if t.strip().lower() == normalized:
                    return True
        except Exception:
            pass
        try:
            result = client.list_channel_works("youtube", self.account_id)
            for t in result.get("titles", []):
                if t.strip().lower() == normalized:
                    return True
        except Exception:
            pass
        return False

    def _validate_video_quality(self, job, platform):
        """Check video file quality before publishing (resolution, codec, audio, duration)."""
        target = _aitoearn_platform(platform)
        video_platforms = {"youtube", "tiktok", "douyin", "KWAI", "bilibili", "wxSph"}
        if target not in video_platforms:
            return True, ""
        artifacts = job.get("artifacts", [])
        video_artifacts = [a for a in artifacts if a.get("kind") == "video"]
        if not video_artifacts:
            return True, ""
        video_path = video_artifacts[0].get("path") or video_artifacts[0].get("url", "")
        if not video_path or not video_path.startswith(("/", "file://")):
            return True, ""
        if video_path.startswith("file://"):
            video_path = video_path[7:]
        if not os.path.isfile(video_path):
            return False, f"❌ 视频文件不存在: {video_path}"
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type,width,height",
                 "-show_entries", "format=duration", "-of", "json", video_path],
                capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            fmt = data.get("format", {})
            duration = float(fmt.get("duration", 0))
            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
            if not video_streams:
                return False, f"❌ 无视频流"
            vinfo = video_streams[0]
            codec = vinfo.get("codec_name", "?")
            width = int(vinfo.get("width", 0))
            height = int(vinfo.get("height", 0))
            checks = []
            if codec not in ("h264", "hevc"):
                checks.append(f"编解码器 {codec}")
            if width < 720 and height < 720:
                checks.append(f"分辨率 {width}x{height}<720p")
            if not audio_streams:
                checks.append("无音轨")
            min_dur = {"youtube": 3, "tiktok": 3, "douyin": 20, "KWAI": 5, "bilibili": 10, "wxSph": 5}
            max_dur = {"youtube": 43200, "tiktok": 180, "douyin": 100, "KWAI": 600, "bilibili": 18000, "wxSph": 600}
            plat_min = min_dur.get(target, 3)
            plat_max = max_dur.get(target, 43200)
            if duration > 0:
                if duration < plat_min:
                    checks.append(f"时长{duration:.0f}s<最短{plat_min}s")
                if duration > plat_max:
                    checks.append(f"时长{duration:.0f}s>最长{plat_max}s")
            if checks:
                return False, f"⚠️ {target}门禁: {'; '.join(checks)}"
            return True, f"✅ {width}x{height} {codec} {duration:.0f}s"
        except Exception as exc:
            return True, f"⚠️ 检查异常: {exc}"

    def deliver(self, job, platform):
        client = self._client()
        if not client:
            return DeliveryResult(False, "blocked", error=f"missing {self.api_key_env}")
        if not self.account_id:
            return DeliveryResult(False, "blocked", error="missing account_id")
        target = _aitoearn_platform(platform)

        # Quality gate
        quality_ok, quality_msg = self._validate_video_quality(job, platform)
        if not quality_ok:
            return DeliveryResult(False, "blocked", error=quality_msg)

        # Duplicate check for YouTube
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        video_title = formatted.get("title", job.get("title", ""))
        if target == "youtube" and video_title:
            if self._check_youtube_duplicate(client, video_title):
                return DeliveryResult(False, "duplicate",
                    error=f"YouTube 已存在同名视频: 「{video_title}」")

        metadata = client.get_platform_metadata(target)
        strategy = metadata.get("publishPolicy", {}).get("completionStrategy", "") or "sync"
        media_urls = _public_media_urls(job.get("artifacts", []))
        content = {"body": formatted.get("text", formatted.get("markdown", job.get("body", "")))}
        if formatted.get("title") or job.get("title"):
            content["title"] = formatted.get("title", job.get("title", ""))
        if media_urls:
            content["media"] = [{"url": url} for url in media_urls]
            cover_url = _first_public_media(job, {"image"})
            if cover_url:
                content["cover"] = {"url": cover_url}
        item = {"platform": target, "accountId": self.account_id}
        option = dict(self.option)
        if target == "bilibili" and "tid" not in option:
            option = {"tid": 160, "copyright": 1, **option}
        if option:
            item["option"] = option
        payload = {"content": content, "items": [item]}
        flow = client.create_channel_publish_flow(payload)
        flow_id = flow.get("flow_id", "")
        if not flow_id:
            return DeliveryResult(False, "failed", error=f"AiToEarn flow id missing: {flow.get('raw_text', '')[:300]}")
        if strategy == "user_handoff":
            return DeliveryResult(True, "handoff_pending", flow_id, error=metadata.get("status", "user_handoff"))
        if strategy == "polling":
            for _ in range(max(1, self.poll_attempts)):
                record = client.get_channel_publish_record_by_flow_id(flow_id)
                if record.get("publish_record_id") or record.get("work_link") or record.get("status", 0) > 0:
                    external_id = record.get("publish_record_id") or flow_id
                    return DeliveryResult(True, self.delivery_status, external_id, error=record.get("work_link", ""))
                if record.get("error"):
                    return DeliveryResult(False, "failed", error=record.get("error", "")[:300])
                if self.poll_interval:
                    time.sleep(self.poll_interval)
            return DeliveryResult(False, "failed", error=f"AiToEarn flow polling timeout: {flow_id}")
        return DeliveryResult(True, self.delivery_status, flow_id)


class AyrshareQuotaStore:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ayrshare_quota (
            account TEXT NOT NULL,
            platform TEXT NOT NULL,
            month TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            monthly_limit INTEGER NOT NULL DEFAULT 20,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(account, platform, month)
            )"""
        )
        return conn

    def try_reserve(self, account, platform, monthly_limit=20, month=None):
        month = month or time.strftime("%Y-%m")
        limit = max(0, int(monthly_limit or 20))
        conn = None
        try:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT used FROM ayrshare_quota WHERE account=? AND platform=? AND month=?",
                (account, platform, month),
            ).fetchone()
            used = int(row["used"]) if row else 0
            if used >= limit:
                conn.rollback()
                return False
            conn.execute(
                """INSERT INTO ayrshare_quota(account,platform,month,used,monthly_limit,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(account,platform,month) DO UPDATE SET
                used=used+1,monthly_limit=excluded.monthly_limit,updated_at=excluded.updated_at""",
                (account, platform, month, 1, limit, int(time.time())),
            )
            conn.commit()
            return True
        except Exception:
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()

    def release(self, account, platform, month=None):
        month = month or time.strftime("%Y-%m")
        conn = None
        try:
            conn = self._connect()
            conn.execute(
                """UPDATE ayrshare_quota SET used=CASE WHEN used>0 THEN used-1 ELSE 0 END,updated_at=?
                WHERE account=? AND platform=? AND month=?""",
                (int(time.time()), account, platform, month),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    def remaining(self, account, platform, monthly_limit=20, month=None):
        month = month or time.strftime("%Y-%m")
        limit = max(0, int(monthly_limit or 20))
        conn = None
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT used FROM ayrshare_quota WHERE account=? AND platform=? AND month=?",
                (account, platform, month),
            ).fetchone()
            used = int(row["used"]) if row else 0
            return max(0, limit - used)
        except Exception:
            return 0
        finally:
            if conn:
                conn.close()

    def usage_rows(self):
        if not self.path.exists():
            return []
        conn = None
        try:
            conn = self._connect()
            return [dict(row) for row in conn.execute("SELECT * FROM ayrshare_quota ORDER BY account,platform,month")]
        except Exception:
            return []
        finally:
            if conn:
                conn.close()


class AyrsharePublisher:
    def __init__(
        self,
        api_key_env="AYRSHARE_API_KEY",
        env_file="",
        api_key="",
        live_enabled=False,
        fallback_outbox="",
        quota_db_path="",
        monthly_limit=20,
        accounts=None,
    ):
        self.api_key_env = api_key_env
        self.env_file = env_file
        self.api_key = api_key
        self.live_enabled = bool(live_enabled)
        self.fallback_outbox = fallback_outbox
        self.monthly_limit = int(monthly_limit or 20)
        self.accounts = accounts or []
        self.quota_store = AyrshareQuotaStore(quota_db_path) if quota_db_path else None
        self._counter_path = None

    def _account_candidates(self, platform):
        platform = _ayrshare_platform(platform)
        accounts = self.accounts or [
            {
                "label": self.api_key_env,
                "api_key_env": self.api_key_env,
                "env_file": self.env_file,
                "api_key": self.api_key,
                "monthly_limit": self.monthly_limit,
                "platforms": [],
            }
        ]
        candidates = []
        for account in accounts:
            platforms = [_ayrshare_platform(item) for item in account.get("platforms", [])]
            if platforms and platform not in platforms:
                continue
            label = account.get("label") or account.get("api_key_env") or self.api_key_env
            limit = int(account.get("monthly_limit", self.monthly_limit) or self.monthly_limit)
            key = read_setting(account.get("api_key_env", self.api_key_env), account.get("env_file", self.env_file), account.get("api_key", ""))
            if not key:
                continue
            remaining = self.quota_store.remaining(label, platform, limit) if self.quota_store else limit
            candidates.append((remaining, label, key, limit))
        candidates.sort(reverse=True)
        return candidates

    def _check_quota(self, platform):
        if not self._counter_path:
            return True
        try:
            if self._counter_path.exists():
                data = json.loads(self._counter_path.read_text(encoding="utf-8") or "{}")
            else:
                data = {}
            now = time.strftime("%Y-%m")
            monthly_key = f"ayrshare_count_{now}"
            count = data.get(monthly_key, 0)
            return count < 20
        except Exception:
            return True

    def _increment_quota(self, platform):
        if not self._counter_path:
            return
        try:
            data = {}
            if self._counter_path.exists():
                data = json.loads(self._counter_path.read_text(encoding="utf-8") or "{}")
            now = time.strftime("%Y-%m")
            monthly_key = f"ayrshare_count_{now}"
            data[monthly_key] = data.get(monthly_key, 0) + 1
            self._counter_path.parent.mkdir(parents=True, exist_ok=True)
            self._counter_path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def _fallback(self, job, platform, reason):
        if not self.fallback_outbox:
            return DeliveryResult(False, "blocked", error=reason)
        result = FileDraftPublisher(self.fallback_outbox).deliver(job, platform)
        return DeliveryResult(result.ok, result.status, result.external_id, error=f"Ayrshare fallback: {reason}")

    def deliver(self, job, platform):
        if not self.live_enabled or os.environ.get("CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH") != "1":
            return self._fallback(job, platform, "live publishing is disabled")
        api_platform = _ayrshare_platform(platform)
        candidates = self._account_candidates(api_platform)
        if not candidates:
            return self._fallback(job, platform, f"missing environment variable: {self.api_key_env} or monthly quota reached")
        remaining, account, key, limit = candidates[0]
        if remaining <= 0:
            return self._fallback(job, platform, f"Ayrshare monthly quota ({limit}) reached for {account}")
        reserved = False
        if self.quota_store:
            reserved = self.quota_store.try_reserve(account, api_platform, limit)
            if not reserved:
                return self._fallback(job, platform, f"Ayrshare monthly quota ({limit}) reached for {account}")
        elif not self._check_quota(api_platform):
            return self._fallback(job, platform, f"Ayrshare monthly quota ({limit}) reached")
        try:
            formatted = job.get("platform_payload") or format_for_platform(job, platform)
            post_body = {
                "post": formatted.get("text", job["body"])[:2000],
                "platforms": [api_platform],
                "shortenLinks": False,
            }
            media_urls = _public_media_urls(job.get("artifacts", []))
            if media_urls:
                post_body["mediaUrls"] = media_urls
            payload = json.dumps(post_body, ensure_ascii=False).encode()
            req = urllib.request.Request(
                "https://api.ayrshare.com/api/post",
                data=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "HermesContentPlatform/3.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            if result.get("status") == "success":
                if not self.quota_store:
                    self._increment_quota(api_platform)
                post_url = result.get("postUrl", "")
                return DeliveryResult(True, "published", str(result.get("id", "")), error=post_url)
            if reserved:
                self.quota_store.release(account, api_platform)
            return self._fallback(job, platform, f"Ayrshare API rejected request: {str(result.get('errors', result))[:200]}")
        except Exception as exc:
            if reserved:
                self.quota_store.release(account, api_platform)
            return self._fallback(job, platform, f"Ayrshare request failed: {str(exc)[:300]}")


PLATFORM_TIERS = {
    "wechat": "a", "weixin": "a", "devto": "a", "youtube": "a",
    "kuaishou": "a", "bluesky": "a", "telegram": "a", "telegraph": "a",
    "mataroa": "a", "tabnews": "a",
    "bilibili": "b", "facebook": "b", "instagram": "b",
    "reddit": "b", "pinterest": "b", "threads": "b",
    "tiktok": "c", "douyin": "c", "xiaohongshu": "c", "rednote": "c",
    "twitter": "c", "x": "c",
}

TIER_LABELS = {"a": "stable_api", "b": "limited_api", "c": "browser_only"}

# 地区分类：domestic（国内） vs international（国际）
# Dev.to 是国际开发者平台，非国内渠道
PLATFORM_REGIONS = {
    # 国内平台
    "wechat": "domestic", "weixin": "domestic",
    "bilibili": "domestic",
    "douyin": "domestic",
    "xiaohongshu": "domestic", "rednote": "domestic",
    "kuaishou": "domestic",
    "shipinhao": "domestic",
    "zhihu": "domestic",
    "weibo": "domestic",
    "juejin": "domestic",
    "csdn": "domestic",
    "toutiao": "domestic",
    # 国际平台
    "devto": "international",
    "telegraph": "international",
    "mataroa": "international",
    "tabnews": "international",
    "youtube": "international",
    "bluesky": "international",
    "telegram": "international",
    "telegraph": "international",
    "facebook": "international",
    "instagram": "international",
    "reddit": "international",
    "pinterest": "international",
    "threads": "international",
    "twitter": "international",
    "x": "international",
    "tiktok": "international",
}


def platform_tier(platform):
    normalized = platform.lower()
    if normalized in DOUYIN_ACCOUNT_VARIANTS:
        normalized = "douyin"
    return PLATFORM_TIERS.get(normalized, "c")


def platform_region(platform):
    """返回平台所属地区: 'domestic' 或 'international'，未知返回 'unknown'"""
    normalized = platform.lower()
    if normalized in DOUYIN_ACCOUNT_VARIANTS:
        normalized = "douyin"
    return PLATFORM_REGIONS.get(normalized, "unknown")


def domestic_platforms():
    """返回所有国内平台列表"""
    return [p for p, r in PLATFORM_REGIONS.items() if r == "domestic"]


def international_platforms():
    """返回所有国际平台列表"""
    return [p for p, r in PLATFORM_REGIONS.items() if r == "international"]


def build_publisher(platform, config, data_dir):
    publishers = config.get("publishers", {})
    platform_cfg = publishers.get("platforms", {}).get(platform)
    cfg = platform_cfg or default_publisher_config(platform, publishers.get("routing_defaults", {})) or publishers.get("default", {"type": "file"})
    kind = cfg.get("type", "file")
    if is_xiaohongshu_platform(platform):
        return XiaohongshuManualHandoffPublisher(cfg.get("outbox", str(Path(data_dir) / "outbox")))
    if is_manual_handoff_platform(platform):
        return ManualHandoffPublisher(
            cfg.get("outbox", str(Path(data_dir) / "outbox")),
            f"{platform} is manual-only by operator policy",
        )
    if kind == "fallback":
        options = cfg.get("publishers", [])
        if not options:
            raise ValueError(f"fallback publisher for {platform} requires publishers")
        return FallbackPublisher([
            build_publisher(platform, {"publishers": {"default": option}}, data_dir)
            for option in options
        ])
    if kind == "file":
        return FileDraftPublisher(cfg.get("outbox", str(Path(data_dir) / "outbox")))
    if kind == "manual-handoff":
        return ManualHandoffPublisher(
            cfg.get("outbox", str(Path(data_dir) / "outbox")),
            cfg.get("reason", "manual publish required by operator policy"),
        )
    if kind == "reddit-draft":
        return RedditDraftPublisher(
            cfg.get("outbox", str(Path(data_dir) / "outbox")),
            cfg.get("default_subreddit", ""),
        )
    if kind == "devto-draft":
        return DevtoDraftPublisher(cfg.get("api_key_env", "DEVTO_API_KEY"), cfg.get("env_file", ""))
    if kind == "wechat-draft":
        return HermesWechatAdapter(
            data_dir=data_dir,
            env_file=cfg.get("env_file", ""),
            command=cfg.get("adapter_command", ""),
            python_bin=cfg.get("python_bin", os.environ.get("PYTHON", "python3")),
            timeout=cfg.get("timeout", 600),
            require_cn_proxy=cfg.get("require_cn_proxy", True),
        )
    if kind == "wechat-legacy-draft":
        return WechatDraftPublisher(
            cfg.get("app_id_env", "WECHAT_APP_ID"), cfg.get("app_secret_env", "WECHAT_APP_SECRET"),
            cfg.get("env_file", "")
        )
    if kind == "telegraph":
        return TelegraphPublisher(cfg.get("live", False), cfg.get("token_env", "TELEGRAPH_TOKEN"), cfg.get("env_file", ""))
    if kind == "youtube":
        return YouTubePublisher(
            cfg.get("client_id_env", "YOUTUBE_CLIENT_ID"),
            cfg.get("client_secret_env", "YOUTUBE_CLIENT_SECRET"),
            cfg.get("refresh_token_env", "YOUTUBE_REFRESH_TOKEN"),
            cfg.get("env_file", ""),
            cfg.get("privacy", "unlisted"),
        )
    if kind == "bluesky":
        return BlueskyPublisher(
            cfg.get("identifier_env", "BLUESKY_IDENTIFIER"),
            cfg.get("password_env", "BLUESKY_PASSWORD"),
            cfg.get("env_file", ""),
        )
    if kind == "bilibili":
        return BilibiliPublisher(
            cfg.get("sessdata_env", "BILIBILI_SESSDATA"),
            cfg.get("bili_jct_env", "BILIBILI_JCT"),
            cfg.get("env_file", ""),
        )
    if kind == "social-auto-upload":
        return SocialAutoUploadPublisher(
            platform_name=cfg.get("platform_name", platform),
            account_name=cfg.get("account_name", "default"),
            project_dir=cfg.get("project_dir", str(social_auto_upload_home())),
            python_bin=cfg.get("python_bin", str(social_auto_upload_home() / "venv/bin/python")),
            schedule_at=cfg.get("schedule_at", "2099-12-31 23:59"),
            schedule_delay_hours=cfg.get("schedule_delay_hours", 2),
            postcheck_callback=cfg.get("postcheck_callback"),
            extra_args=cfg.get("extra_args", []),
            video_extra_args=cfg.get("video_extra_args", []),
            note_extra_args=cfg.get("note_extra_args", []),
        )
    if kind == "juejin-api":
        return JuejinPublisher(
            account=cfg.get("account", "main"),
            cookie_dir=cfg.get("cookie_dir", str(Path.home() / "social-auto-upload" / "cookies")),
            proxy=cfg.get("proxy") or os.environ.get("CN_PROXY", ""),
            save_as_draft=True,
        )
    if kind == "zhihu-playwright":
        return ZhihuPublisher(
            account=cfg.get("account", "main"),
            cookie_dir=cfg.get("cookie_dir", str(Path.home() / "social-auto-upload" / "cookies")),
            proxy=cfg.get("proxy") or os.environ.get("CN_PROXY", ""),
            headless=cfg.get("headless", True),
            save_as_draft=True,
        )
    if kind == "x-playwright":
        return XPlaywrightPublisher(
            account=cfg.get("account", "main"),
            cookie_dir=cfg.get("cookie_dir", str(Path.home() / "social-auto-upload" / "cookies")),
            proxy=cfg.get("proxy", os.environ.get("US_PROXY", "")),
            headless=cfg.get("headless", True),
            timeout=cfg.get("timeout", 900),
            live=cfg.get("live", True),
        )
    if kind in {"aitoearn-draft", "aitoearn-intl"}:
        if platform.casefold() in AITOEARN_DISABLED_PLATFORMS:
            return ManualHandoffPublisher(
                cfg.get("outbox", str(Path(data_dir) / "outbox")),
                f"{platform} is configured for cookie/manual route; AiToEarn is disabled by operator policy",
            )
        default_base_url = "https://aitoearn.ai/api/unified/mcp" if platform_region(platform) == "international" else "https://aitoearn.cn/api/unified/mcp"
        default_key_env = "AITOEARN_INTL_API_KEY" if platform_region(platform) == "international" else "AITOEARN_API_KEY"
        return AiToEarnDraftPublisher(
            base_url=cfg.get("base_url", default_base_url),
            api_key_env=cfg.get("api_key_env", default_key_env),
            env_file=cfg.get("env_file", ""),
            api_key=cfg.get("api_key", ""),
            image_model=cfg.get("image_model", "gpt-image-2"),
            video_model=cfg.get("video_model", "grok-imagine-video"),
            image_count=cfg.get("image_count", 3),
            poll_attempts=cfg.get("poll_attempts", 10),
            poll_interval=cfg.get("poll_interval", 2),
        )
    if kind == "aitoearn-flow":
        if platform.casefold() in AITOEARN_DISABLED_PLATFORMS:
            return ManualHandoffPublisher(
                cfg.get("outbox", str(Path(data_dir) / "outbox")),
                f"{platform} is configured for cookie/manual route; AiToEarn is disabled by operator policy",
            )
        default_base_url = "https://aitoearn.ai/api/unified/mcp" if platform_region(platform) == "international" else "https://aitoearn.cn/api/unified/mcp"
        default_key_env = "AITOEARN_INTL_API_KEY" if platform_region(platform) == "international" else "AITOEARN_API_KEY"
        return AiToEarnFlowPublisher(
            account_id=cfg.get("account_id", ""),
            base_url=cfg.get("base_url", default_base_url),
            api_key_env=cfg.get("api_key_env", default_key_env),
            env_file=cfg.get("env_file", ""),
            api_key=cfg.get("api_key", ""),
            option=cfg.get("option", {}),
            delivery_status=cfg.get("delivery_status", "drafted"),
            poll_attempts=cfg.get("poll_attempts", 12),
            poll_interval=cfg.get("poll_interval", 5),
        )
    if kind == "ayrshare":
        fallback_cfg = cfg.get("fallback", {})
        default_outbox = publishers.get("default", {}).get("outbox", str(Path(data_dir) / "outbox"))
        pub = AyrsharePublisher(
            cfg.get("api_key_env", "AYRSHARE_API_KEY"),
            cfg.get("env_file", ""),
            cfg.get("api_key", ""),
            live_enabled=cfg.get("live", False),
            fallback_outbox=fallback_cfg.get("outbox", default_outbox),
            quota_db_path=cfg.get("quota_db", str(Path(data_dir) / "ayrshare_quota.db")),
            monthly_limit=cfg.get("monthly_limit", 20),
            accounts=cfg.get("accounts"),
        )
        pub._counter_path = Path(data_dir) / "ayrshare_counter.json"
        return pub
    if kind == "mataroa":
        return MataroaPublisher(
            cfg.get("api_key_env", "MATAROA_API_KEY"),
            cfg.get("env_file", ""),
        )
    if kind == "tabnews":
        return TabnewsPublisher(
            cfg.get("email_env", "TABNEWS_EMAIL"),
            cfg.get("password_env", "TABNEWS_PASSWORD"),
            cfg.get("env_file", ""),
        )
    if kind == "mastodon":
        return MastodonPublisher(
            instance=cfg.get("instance", ""),
            token_env=cfg.get("token_env", "MASTODON_TOKEN"),
            env_file=cfg.get("env_file", ""),
        )
    if kind == "bluesky":
        return BlueskyPublisher(
            identifier_env=cfg.get("identifier_env", "BLUESKY_IDENTIFIER"),
            password_env=cfg.get("password_env", "BLUESKY_PASSWORD"),
            env_file=cfg.get("env_file", ""),
        )
    if kind == "nostr":
        return NostrPublisher(
            key_env=cfg.get("key_env", "NOSTR_PRIVATE_KEY"),
            env_file=cfg.get("env_file", ""),
        )
    if kind == "writeas":
        return WriteAsPublisher(
            token_env=cfg.get("token_env", "WRITEAS_TOKEN"),
            env_file=cfg.get("env_file", ""),
        )
    if kind == "github-discuss":
        return GitHubDiscussPublisher(
            token_env=cfg.get("token_env", "GITHUB_TOKEN"),
            repo=cfg.get("repo", "user/repo"),
            env_file=cfg.get("env_file", ""),
        )
    if kind == "buttondown":
        return ButtondownPublisher(
            api_key_env=cfg.get("api_key_env", "BUTTONDOWN_API_KEY"),
            env_file=cfg.get("env_file", ""),
        )
    if kind == "cnblogs":
        return CnblogsPublisher()
    if kind == "steemit":
        return SteemitPublisher()
    if kind == "email":
        return EmailPublisher(
            smtp_host=cfg.get("smtp_host", ""),
            smtp_port=int(cfg.get("smtp_port", 587)),
            smtp_user=cfg.get("smtp_user", ""),
            smtp_pass=cfg.get("smtp_pass", ""),
            from_addr=cfg.get("from_addr", ""),
            to_addrs=cfg.get("to_addrs", ""),
        )
    raise ValueError(f"unknown publisher type for {platform}: {kind}")


class MataroaPublisher:
    """Mataroa.blog — minimal publishing platform.
    API: POST https://mataroa.blog/api/posts/ with Bearer token.
    """
    def __init__(self, api_key_env="MATAROA_API_KEY", env_file="", api_key=""):
        self.api_key_env = api_key_env
        self.env_file = env_file
        self.api_key = api_key

    def deliver(self, job, platform):
        key = read_setting(self.api_key_env, self.env_file, self.api_key)
        if not key:
            return DeliveryResult(False, "blocked", error=f"missing environment variable: {self.api_key_env}")
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        payload = json.dumps({
            "title": formatted.get("title", job["title"])[:256],
            "body": formatted.get("markdown", job["body"]),
        }).encode()
        try:
            req = urllib.request.Request(
                "https://mataroa.blog/api/posts/",
                data=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "HermesContentPlatform/3.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            slug = result.get("slug", "")
            if slug:
                return DeliveryResult(True, "published", f"https://mataroa.blog/posts/{slug}/")
            return DeliveryResult(True, "published", str(result.get("id", "")))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:200]
            return DeliveryResult(False, "failed", error=f"Mataroa HTTP {exc.code}: {body}")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])


class TabnewsPublisher:
    """Tabnews.com.br — Brazilian developer community.
    API: login → session token → POST /api/v1/contents
    """
    def __init__(self, email_env="TABNEWS_EMAIL", password_env="TABNEWS_PASSWORD",
                 env_file="", email="", password=""):
        self.email_env = email_env
        self.password_env = password_env
        self.env_file = env_file
        self.email = email
        self.password = password

    def deliver(self, job, platform):
        email = read_setting(self.email_env, self.env_file, self.email)
        password = read_setting(self.password_env, self.env_file, self.password)
        if not email or not password:
            return DeliveryResult(False, "blocked", error="missing Tabnews credentials (email + password)")
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        try:
            # Step 1: Login
            login_data = json.dumps({"email": email, "password": password}).encode()
            login_req = urllib.request.Request(
                "https://www.tabnews.com.br/api/v1/sessions",
                data=login_data,
                headers={"Content-Type": "application/json", "User-Agent": "HermesContentPlatform/3.0"},
            )
            with urllib.request.urlopen(login_req, timeout=30) as resp:
                session = json.loads(resp.read())
            token = session.get("token", "")
            if not token:
                return DeliveryResult(False, "failed", error="Tabnews login succeeded but no token")

            # Step 2: Create post
            post_data = json.dumps({
                "title": formatted.get("title", job["title"])[:256],
                "body": formatted.get("markdown", job["body"]),
                "status": "published",
            }).encode()
            post_req = urllib.request.Request(
                "https://www.tabnews.com.br/api/v1/contents",
                data=post_data,
                headers={
                    "Cookie": f"session_id={token}",
                    "Content-Type": "application/json",
                    "User-Agent": "HermesContentPlatform/3.0",
                },
            )
            with urllib.request.urlopen(post_req, timeout=30) as resp:
                result = json.loads(resp.read())
            username = result.get("owner_username", result.get("owner", ""))
            slug = result.get("slug", "")
            if username and slug:
                return DeliveryResult(True, "published", f"https://www.tabnews.com.br/{username}/{slug}")
            return DeliveryResult(True, "published", str(result.get("id", "")))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:300]
            return DeliveryResult(False, "failed", error=f"Tabnews HTTP {exc.code}: {body}")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])


# ====== New channel-matrix publishers (v3.1) ======
# Imported and adapted from Hermes channel_matrix.py
# Each publisher implements .deliver(job, platform) -> DeliveryResult


class MastodonPublisher:
    """Mastodon / ActivityPub — post a status to a Mastodon instance."""
    def __init__(self, instance="", token_env="MASTODON_TOKEN", env_file=""):
        self.instance = instance.rstrip("/")
        self.token_env = token_env
        self.env_file = env_file

    def deliver(self, job, platform):
        token = read_setting(self.token_env, self.env_file)
        if not token:
            return DeliveryResult(False, "blocked", error=f"missing {self.token_env}")
        if not self.instance:
            return DeliveryResult(False, "blocked", error="no mastodon instance configured")
        text = self._extract_text(job, platform, max_len=500)
        import httpx
        try:
            r = httpx.post(f"{self.instance}/api/v1/statuses",
                headers={"Authorization": f"Bearer {token}"},
                json={"status": text, "visibility": "unlisted"}, timeout=15)
            ok = r.status_code == 200
            return DeliveryResult(ok, "published" if ok else "failed",
                str(r.json().get("id", "")) if ok else "",
                error="" if ok else f"Mastodon HTTP {r.status_code}")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:300])

    def _extract_text(self, job, platform, max_len=500):
        formatted = job.get("platform_payload") or {}
        text = formatted.get("text") or formatted.get("markdown") or job.get("body", "")
        return text[:max_len]


class BlueskyPublisher:
    """Bluesky AT Protocol — create a post on bsky.social."""
    def __init__(self, identifier_env="BLUESKY_IDENTIFIER", password_env="BLUESKY_PASSWORD",
                 env_file="", identifier="", password=""):
        self.identifier_env = identifier_env
        self.password_env = password_env
        self.env_file = env_file

    def deliver(self, job, platform):
        identifier = read_setting(self.identifier_env, self.env_file)
        password = read_setting(self.password_env, self.env_file)
        if not identifier or not password:
            return DeliveryResult(False, "blocked", error="missing Bluesky credentials")
        text = self._extract_text(job, platform, max_len=300)
        import httpx
        try:
            s = httpx.Client(timeout=15)
            r = s.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": identifier, "password": password})
            if r.status_code != 200:
                return DeliveryResult(False, "failed", error="Bluesky auth failed")
            t = r.json()["accessJwt"]
            d = r.json()["did"]
            from datetime import datetime
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
            r2 = s.post("https://bsky.social/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {t}"},
                json={"repo": d, "collection": "app.bsky.feed.post",
                      "record": {"$type": "app.bsky.feed.post", "text": text, "createdAt": now}})
            s.close()
            ok = r2.status_code == 200
            uri = r2.json().get("uri", "") if ok else ""
            return DeliveryResult(ok, "published" if ok else "failed", uri)
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:300])

    def _extract_text(self, job, platform, max_len=300):
        formatted = job.get("platform_payload") or {}
        text = formatted.get("text") or formatted.get("markdown") or job.get("body", "")
        return text[:max_len]


class NostrPublisher:
    """Nostr — broadcast an event to configured relays."""
    RELAYS = [
        "wss://nos.lol", "wss://relay.snort.social",
        "wss://nostr-pub.wellorder.net", "wss://relay.nostr.band",
        "wss://relay.current.fyi",
    ]

    def __init__(self, key_env="NOSTR_PRIVATE_KEY", env_file="", relays=None):
        self.key_env = key_env
        self.env_file = env_file
        if relays:
            self.RELAYS = relays

    def deliver(self, job, platform):
        try:
            from nacl.signing import SigningKey
            from nacl.encoding import HexEncoder, RawEncoder
            from websocket import create_connection
        except ImportError as e:
            return DeliveryResult(False, "blocked", error=f"Missing dependency: {e}. Run: pip install pynacl websocket-client")
        key_hex = read_setting(self.key_env, self.env_file)
        if not key_hex:
            return DeliveryResult(False, "blocked", error=f"missing {self.key_env}")
        text = self._extract_text(job, platform, max_len=8000)
        sk = SigningKey(key_hex, encoder=HexEncoder)
        pk = sk.verify_key.encode(encoder=HexEncoder).decode()
        ev = {"pubkey": pk, "created_at": int(time.time()), "kind": 1, "tags": [], "content": text}
        ser = json.dumps([0, pk, ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
                         separators=(",", ":"), ensure_ascii=False)
        ev["id"] = hashlib.sha256(ser.encode()).hexdigest()
        ev["sig"] = sk.sign(hashlib.sha256(ser.encode()).digest(), encoder=RawEncoder).signature.hex()
        msg = json.dumps(["EVENT", ev])
        success = 0
        for rl in self.RELAYS:
            try:
                ws = create_connection(rl, timeout=5)
                ws.send(msg)
                ws.settimeout(3)
                ws.recv()
                ws.close()
                success += 1
            except Exception:
                pass
        ok = success > 0
        return DeliveryResult(ok, "published" if ok else "failed",
                              f"{success}/{len(self.RELAYS)}",
                              error="" if ok else "all relays failed")

    def _extract_text(self, job, platform, max_len=8000):
        formatted = job.get("platform_payload") or {}
        text = formatted.get("text") or formatted.get("markdown") or job.get("body", "")
        return text[:max_len]


class WriteAsPublisher:
    """Write.as / WriteFreely — create a blog post."""
    def __init__(self, token_env="WRITEAS_TOKEN", env_file=""):
        self.token_env = token_env
        self.env_file = env_file

    def deliver(self, job, platform):
        token = read_setting(self.token_env, self.env_file)
        if not token:
            return DeliveryResult(False, "blocked", error=f"missing {self.token_env}")
        formatted = job.get("platform_payload") or {}
        title = (formatted.get("title") or job.get("title", "Post"))[:80]
        body = formatted.get("markdown") or job.get("body", "")
        import httpx
        try:
            r = httpx.post("https://write.as/api/posts",
                headers={"Authorization": f"Token {token}"},
                json={"body": body, "title": title}, timeout=15)
            ok = r.status_code in (200, 201)
            url = r.json().get("data", {}).get("url", "") if ok else ""
            return DeliveryResult(ok, "published" if ok else "failed", url)
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:300])


class GitHubDiscussPublisher:
    """GitHub Discussions — create a discussion in a repo."""
    def __init__(self, token_env="GITHUB_TOKEN", repo="user/repo", env_file=""):
        self.token_env = token_env
        self.repo = repo
        self.env_file = env_file

    def deliver(self, job, platform):
        token = read_setting(self.token_env, self.env_file)
        if not token:
            return DeliveryResult(False, "blocked", error=f"missing {self.token_env}")
        formatted = job.get("platform_payload") or {}
        title = (formatted.get("title") or job.get("title", "Update"))[:80]
        body = formatted.get("markdown") or job.get("body", "")
        import httpx
        try:
            r = httpx.post(f"https://api.github.com/repos/{self.repo}/discussions",
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github.v3+json"},
                json={"title": title, "body": body}, timeout=15)
            ok = r.status_code in (200, 201)
            url = r.json().get("html_url", "") if ok else ""
            return DeliveryResult(ok, "published" if ok else "failed", url)
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:300])


class ButtondownPublisher:
    """Buttondown.email — create a draft newsletter."""
    def __init__(self, api_key_env="BUTTONDOWN_API_KEY", env_file=""):
        self.api_key_env = api_key_env
        self.env_file = env_file

    def deliver(self, job, platform):
        key = read_setting(self.api_key_env, self.env_file)
        if not key:
            return DeliveryResult(False, "blocked", error=f"missing {self.api_key_env}")
        formatted = job.get("platform_payload") or {}
        subject = (formatted.get("title") or job.get("title", "Newsletter"))[:80]
        body = formatted.get("markdown") or job.get("body", "")
        import httpx
        try:
            r = httpx.post("https://api.buttondown.email/v1/emails",
                headers={"Authorization": f"Token {key}"},
                json={"subject": subject, "body": body, "status": "draft"}, timeout=15)
            ok = r.status_code in (200, 201)
            eid = r.json().get("id", "") if ok else ""
            return DeliveryResult(ok, "drafted" if ok else "failed", str(eid))
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:300])



class EmailPublisher:
    """Simple SMTP email publisher for newsletters."""
    def __init__(self, smtp_host="", smtp_port=587, smtp_user="", smtp_pass="", from_addr="", to_addrs=""):
        self.smtp_host = smtp_host
        self.smtp_port = int(smtp_port)
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_addr = from_addr or smtp_user
        self.to_addrs = to_addrs

    def deliver(self, job, platform):
        if not self.smtp_host:
            return DeliveryResult(False, "blocked", error="no smtp host configured")
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        formatted = job.get("platform_payload", {})
        html = formatted.get("html") or job.get("body", "")
        title = formatted.get("title") or job.get("title", "Newsletter")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = title
        msg["From"] = self.from_addr
        msg["To"] = self.to_addrs
        msg.attach(MIMEText(html, "html", "utf-8"))
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            return DeliveryResult(True, "published")
        except Exception as exc:
            return DeliveryResult(False, "failed", error=str(exc)[:500])

class CnblogsPublisher:
    """博客园 — connectivity test (XML-RPC publishing requires account config)."""
    def deliver(self, job, platform):
        import httpx
        try:
            r = httpx.get("https://www.cnblogs.com/", timeout=10)
            ok = r.status_code == 200
            return DeliveryResult(ok, "reachable" if ok else "unreachable",
                                  f"HTTP {r.status_code}")
        except Exception as exc:
            return DeliveryResult(False, "unreachable", error=str(exc)[:300])


class SteemitPublisher:
    """Steem blockchain — connectivity test (full publish requires account keys)."""
    def deliver(self, job, platform):
        import httpx
        try:
            r = httpx.get("https://api.steemit.com", timeout=10)
            ok = r.status_code == 200
            return DeliveryResult(ok, "reachable" if ok else "unreachable",
                                  f"HTTP {r.status_code}")
        except Exception as exc:
            return DeliveryResult(False, "unreachable", error=str(exc)[:300])
