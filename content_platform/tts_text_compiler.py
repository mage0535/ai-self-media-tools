"""Compile display copy into provider-safe narration copy.

The compiler is provider-neutral: Edge TTS, Qwen TTS, and future providers
receive the same `tts_text`, while subtitles retain `display_text`.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CompiledTTS:
    display_text: str
    tts_text: str
    applied_rules: list[dict[str, Any]]
    unhandled_latin_tokens: list[str]


class TTSTextCompiler:
    def __init__(self, rules: list[dict[str, Any]] | None = None):
        self.rules = [row for row in (rules or []) if isinstance(row, dict) and row.get("source")]

    @classmethod
    def from_file(cls, path: str | Path) -> "TTSTextCompiler":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload.get("rules", []) if isinstance(payload, dict) else [])

    @classmethod
    def default(cls) -> "TTSTextCompiler":
        path = Path(__file__).resolve().parents[1] / "config" / "pronunciation_dictionary.json"
        if path.is_file():
            return cls.from_file(path)
        return cls([])

    def compile(self, display_text: str, *, context: str = "default", platform: str = "") -> CompiledTTS:
        display = re.sub(
            r"(?<![a-z0-9-])([a-z0-9-]+)\s*\.\s*([a-z0-9-]+)\s*\.\s*(com|cn|org|net|io|ai|dev)(?![a-z0-9-])",
            r"\1.\2.\3",
            str(display_text or ""),
            flags=re.I,
        )
        result = display
        applied: list[dict[str, Any]] = []
        occupied: list[tuple[int, int]] = []
        rules = sorted(self.rules, key=lambda row: int(row.get("priority", 0)), reverse=True)
        for rule in rules:
            contexts = rule.get("contexts") or []
            platforms = rule.get("platforms") or []
            if contexts and context not in contexts:
                continue
            if platforms and platform and platform not in platforms:
                continue
            source = str(rule["source"])
            alias = str(rule.get("alias") or source)
            # 国际英文平台必须保持英文 TTS；中文发音词典只适用于中文口播，
            # 否则 "AI" -> "人工智能" 会把中文混入英文音轨并改变时长。
            international_english = {"tiktok", "youtube", "youtube_shorts", "shorts"}
            if platform.casefold() in international_english and re.search(r"[\u3400-\u9fff]", alias):
                continue
            expression = re.escape(source)
            if source.isascii() and source.replace("-", "").isalnum():
                expression = rf"(?<![A-Za-z0-9]){expression}(?![A-Za-z0-9])"
            pattern = re.compile(expression, re.IGNORECASE if source.isascii() else 0)
            cursor = 0
            while True:
                match = pattern.search(result, cursor)
                if match is None:
                    break
                span = match.span()
                if any(span[0] < end and start < span[1] for start, end in occupied):
                    cursor = max(match.end(), cursor + 1)
                    continue
                result = result[:span[0]] + alias + result[span[1]:]
                delta = len(alias) - (span[1] - span[0])
                occupied = [(start if start < span[0] else start + delta, end if end <= span[0] else end + delta) for start, end in occupied]
                occupied.append((span[0], span[0] + len(alias)))
                applied.append({"source": source, "alias": alias, "priority": int(rule.get("priority", 0)), "context": context})
                cursor = span[0] + len(alias)
        allowed = {token for row in applied for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", row["alias"])}
        unhandled = []
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", result):
            if token in allowed or (len(token) == 1 and token.upper() in {"A", "I"}):
                continue
            if token not in unhandled:
                unhandled.append(token)
        return CompiledTTS(display, result, applied, unhandled)
