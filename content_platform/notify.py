import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import re


class Notifier:
    def __init__(self, config=None):
        self.config = config or {}

    def send(self, event, job):
        log_path = Path(self.config.get("log_path", "notifications.jsonl"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            "job_id": job["id"],
            "title": job.get("title") or job.get("topic", ""),
            "state": job.get("state", ""),
            "platforms": job.get("platforms", []),
            "deliveries": job.get("deliveries", []),
            "report_path": job.get("report_path", ""),
            "review_required": bool(job.get("review_actions")) or event == "review_required",
            "workflow_id": job.get("workflow_id", ""),
            "step_name": job.get("step_name", ""),
            "reason_code": job.get("reason_code", ""),
            "message": job.get("message", ""),
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        result = {"logged": True, "hermes": False, "telegram": False, "webhook": False}
        if self.config.get("network_enabled", False):
            for key, sender in (("hermes", self._hermes), ("telegram", self._telegram), ("webhook", self._webhook)):
                try:
                    result[key] = sender(row)
                except (OSError, subprocess.SubprocessError, urllib.error.URLError):
                    result[key] = False
        return result

    def _hermes(self, row):
        target_env = str(self.config.get("hermes_target_env") or "").strip()
        target = os.environ.get(target_env, "").strip() if target_env else ""
        target = target or str(self.config.get("hermes_target") or "").strip()
        if not target:
            return False
        message = self._message(row)
        proc = subprocess.run(
            ["hermes", "send", "--to", target, "--quiet", message], capture_output=True, text=True, timeout=30, check=False
        )
        return proc.returncode == 0

    def _telegram(self, row):
        token = self._setting(self.config.get("telegram_token_env", "TELEGRAM_BOT_TOKEN"))
        chat_id = self._setting(self.config.get("telegram_chat_env", "TELEGRAM_CHAT_ID"))
        if not token or not chat_id:
            return False
        text = self._message(row)
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(request, timeout=15):
            return True

    @staticmethod
    def _message(row):
        text = f"[{row['event']}] {row['title']}\njob={row['job_id']} state={row['state']}"
        platforms = [str(item) for item in row.get("platforms", []) if str(item)]
        if platforms:
            text += "\nplatforms=" + ",".join(platforms)
        if row.get("workflow_id"):
            text += f"\nworkflow={row['workflow_id']}"
        if row.get("step_name"):
            text += f"\nstep={row['step_name']}"
        if row.get("reason_code"):
            text += f"\nreason={row['reason_code']}"
        if row.get("message"):
            text += f"\nmessage={str(row['message'])[:240]}"
        deliveries = []
        for item in row.get("deliveries", [])[:5]:
            platform = str(item.get("platform", ""))
            status = str(item.get("status", ""))
            external_id = str(item.get("external_id", ""))
            if platform and status:
                delivery = f"{platform}:{status}"
                if platform == "reddit" and external_id:
                    delivery += f" {external_id}"
                deliveries.append(delivery)
        if deliveries:
            text += "\ndeliveries=" + "; ".join(deliveries)
        if row.get("report_path"):
            text += f"\nreport={row['report_path']}"
        if row.get("review_required") or row.get("event") == "review_required":
            text += "\nreview action required through the secure console"
        return text

    @staticmethod
    def redact_log(path):
        """Remove credential-like review actions from legacy notification logs."""
        source = Path(path)
        if not source.is_file():
            return {"changed": 0, "rows": 0}
        changed, cleaned = 0, []
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                cleaned.append(line)
                continue
            if not isinstance(row, dict):
                cleaned.append(line)
                continue
            if row.pop("review_actions", None) is not None:
                row["review_required"] = True
                changed += 1
            message = str(row.get("message") or "")
            redacted = re.sub(r"content-platform review-action\s+\S+", "content-platform review-action [REDACTED]", message)
            if redacted != message:
                row["message"] = redacted
                changed += 1
            cleaned.append(json.dumps(row, ensure_ascii=False))
        if changed:
            source.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
        return {"changed": changed, "rows": len(cleaned)}

    def _setting(self, name):
        if os.environ.get(name):
            return os.environ[name]
        env_file = self.config.get("telegram_env_file", "")
        if not env_file or not Path(env_file).is_file():
            return ""
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() == name:
                return value.strip().strip("'\"")
        return ""

    def _webhook(self, row):
        url = os.environ.get(self.config.get("webhook_env", "CONTENT_PLATFORM_WEBHOOK_URL"), "")
        if not url:
            return False
        request = urllib.request.Request(url, data=json.dumps(row).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=15):
            return True
