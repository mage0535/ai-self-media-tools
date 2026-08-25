"""Read-only Chinese business reporting for the durable batch event stream."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .risk import redact_secrets


PLATFORM_LABELS = {
    "wechat": "微信",
    "xiaohongshu": "小红书",
    "douyin": "抖音",
    "douyin_ai": "抖音 AI 赛道",
    "douyin_pet": "抖音宠物赛道",
    "kuaishou": "快手",
    "shipinhao": "视频号",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "bilibili": "哔哩哔哩",
    "zhihu": "知乎",
    "twitter": "X",
    "x": "X",
}

_SECRET_VALUE = re.compile(r"(?i)(?:token|secret|password|cookie|api[_-]?key)\s*[:=]\s*[^\s,;]+")
_RAW_SYNTAX = re.compile(r"[`{}\[\]]")


def _safe(value: Any, limit: int = 240) -> str:
    text = redact_secrets(str(value or ""))
    text = _SECRET_VALUE.sub(lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=[已隐藏]", text)
    text = _RAW_SYNTAX.sub("", text).replace("\r", " ").replace("\n", " ")
    return text[:limit].strip()


class ChineseReporter:
    """Consume append-only events with a durable line cursor.

    The reporter never writes the event stream or workflow state.  Only its
    own cursor is updated after a line has been formatted successfully.
    """

    def __init__(self, events_path: str | Path, cursor_path: str | Path):
        self.events_path = Path(events_path)
        self.cursor_path = Path(cursor_path)

    def consume(self) -> list[str]:
        if not self.events_path.is_file():
            return []
        cursor = self._read_cursor()
        start = int(cursor.get("line", 0))
        lines = self.events_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        messages: list[str] = []
        consumed = start
        for index in range(start, len(lines)):
            raw = lines[index]
            if not raw.endswith(("\n", "\r")):
                break
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                consumed = index + 1
                continue
            if isinstance(row, dict):
                messages.append(self.format_event(row))
            consumed = index + 1
        if consumed != start:
            self._write_cursor({"line": consumed})
        return messages

    @classmethod
    def format_event(cls, row: dict[str, Any]) -> str:
        event = str(row.get("event") or "")
        platform_key = str(row.get("platform") or "")
        platform = PLATFORM_LABELS.get(platform_key.casefold(), platform_key or "未指定平台")
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        stage = _safe(detail.get("stage") or row.get("stage") or "")
        stage_text = stage or "当前流程"
        lower = event.casefold()
        if "stale" in lower or int(detail.get("heartbeat_age_seconds") or 0) > int(detail.get("stale_after_seconds") or 1800):
            status = "心跳已超时，疑似停滞"
        elif "failed" in lower:
            status = "已终止"
        elif "blocked" in lower:
            status = "已阻塞"
        elif "completed" in lower or lower.endswith("finished") or stage == "completed":
            status = "已完成"
        elif detail.get("progress") or "progress" in lower or "started" in lower or "heartbeat" in lower:
            status = "正在推进"
        else:
            status = "已更新"

        parts = [f"{platform}：{stage_text}{status}"]
        for label, key in (("具体动作", "action"), ("查询", "query")):
            if detail.get(key):
                parts.append(f"{label}：{_safe(detail[key])}")
        if detail.get("progress"):
            parts.append(f"进度：{_safe(detail['progress'])}")
        if detail.get("candidate_count") is not None:
            parts.append(f"候选 {_safe(detail['candidate_count'], 30)} 个")
        if detail.get("selected_topic"):
            parts.append(f"选题：{_safe(detail['selected_topic'])}")
        if detail.get("selection_reason"):
            parts.append(f"选择理由：{_safe(detail['selection_reason'])}")
        if detail.get("tool_calls"):
            calls = detail["tool_calls"] if isinstance(detail["tool_calls"], list) else [detail["tool_calls"]]
            parts.append("工具调用：" + ", ".join(_safe(item, 80) for item in calls[:8]))
        if detail.get("error") or detail.get("reason"):
            parts.append(f"错误：{_safe(detail.get('error') or detail.get('reason'))}")
        if detail.get("root_cause"):
            parts.append(f"根因：{_safe(detail['root_cause'])}")
        if detail.get("fix"):
            parts.append(f"修复：{_safe(detail['fix'])}")
        if any(detail.get(key) is not None for key in ("repair_attempts", "repair_round", "retry_count")):
            retry = detail.get("repair_attempts", detail.get("repair_round", detail.get("retry_count")))
            parts.append(f"重试/修复轮次：{_safe(retry, 30)}")
        gate = detail.get("gate")
        if isinstance(gate, dict) and "passed" in gate:
            parts.append("门禁：通过" if gate.get("passed") else "门禁：未通过")
        if detail.get("delivery_receipt"):
            parts.append(f"交付回执：{_safe(detail['delivery_receipt'])}")
        if detail.get("heartbeat_age_seconds") is not None:
            parts.append(f"心跳年龄：{_safe(detail['heartbeat_age_seconds'], 30)} 秒")
        return "；".join(parts) + "。"

    def _read_cursor(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.cursor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"line": 0}
        return payload if isinstance(payload, dict) else {"line": 0}

    def _write_cursor(self, payload: dict[str, Any]) -> None:
        self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cursor_path.with_suffix(self.cursor_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self.cursor_path)
