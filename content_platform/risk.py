import json
import re
import subprocess


DEFAULT_BLOCK = ["儿童色情", "制作炸弹", "银行卡盗刷", "仇恨灭绝"]
DEFAULT_REVIEW = ["保证收益", "稳赚不赔", "治愈", "第一", "最强", "内幕消息"]


def redact_secrets(value):
    text = str(value)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", text)
    text = re.sub(r"\b(?:sk|ak|ghp|xoxb)_[A-Za-z0-9_-]{10,}\b", "[REDACTED]", text)
    return text


class RiskFilter:
    def __init__(self, block_words=None, review_words=None, legacy_script="", timeout=20):
        self.block_words = block_words if block_words is not None else DEFAULT_BLOCK
        self.review_words = review_words if review_words is not None else DEFAULT_REVIEW
        self.legacy_script = legacy_script
        self.timeout = int(timeout)

    def evaluate(self, text):
        lowered = str(text).lower()
        block_hits = [word for word in self.block_words if str(word).lower() in lowered]
        review_hits = [word for word in self.review_words if str(word).lower() in lowered]
        legacy = self._legacy(text) if self.legacy_script else None
        if legacy and not legacy.get("pass", True):
            level = "block" if legacy.get("level") in {"block", "high"} else "review"
            (block_hits if level == "block" else review_hits).extend(legacy.get("hits", []))
        level = "block" if block_hits else "review" if review_hits else "pass"
        return {"level": level, "hits": list(dict.fromkeys(block_hits + review_hits)), "legacy": legacy}

    def _legacy(self, text):
        try:
            proc = subprocess.run(
                ["python3", self.legacy_script, str(text)], capture_output=True, text=True, timeout=self.timeout, check=False
            )
            return json.loads(proc.stdout) if proc.returncode == 0 else {"pass": False, "level": "review", "hits": ["legacy_filter_error"]}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {"pass": False, "level": "review", "hits": ["legacy_filter_unavailable"]}

