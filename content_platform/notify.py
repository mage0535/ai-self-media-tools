import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


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
            "review_actions": job.get("review_actions", {}),
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
        target = self.config.get("hermes_target", "")
        if not target:
            return False
        message = self._message(row)
        proc = subprocess.run(
            ["hermes", "send", "--to", target, "--quiet", message],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
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
        actions = row.get("review_actions", {})
        if actions.get("approve"):
            text += f"\n\napprove: content-platform review-action {actions['approve']} --action approve --actor REVIEWER"
        if actions.get("reject"):
            text += f"\nreject: content-platform review-action {actions['reject']} --action reject --actor REVIEWER"
        return text

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
