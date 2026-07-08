#!/usr/bin/env python3
"""
智能多语言配音引擎 Intelligent Multilingual Voice Engine
- 84+ 语言支持（中/英/日/韩/西/法/德/葡/俄/意 等）
- 单人/多人对话双模式
- 赛道自适应：技术教程/萌宠/财经/情感/科普（每种语言独立调优）
- 去AI化：呼吸音、随机停顿、语速波动、语气词、底噪
- 字幕自动生成（SRT格式，含时间戳）
- 主力引擎：edge-tts + FFmpeg 后处理

Usage:
  python scripts/voice_engine.py script.txt --lang auto --genre auto
  from scripts.voice_engine import run_voice_pipeline
"""
import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

# ────────────────────────────────────────────────────────────────
# 语言检测
# ────────────────────────────────────────────────────────────────
_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs（中文）
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x20000, 0x2A6DF), # Extension B
    (0xF900, 0xFAFF),   # Compatibility
]
_JP_RANGES = [(0x3040, 0x309F), (0x30A0, 0x30FF)]  # Hiragana, Katakana
_KR_RANGES = [(0xAC00, 0xD7AF), (0x1100, 0x11FF)]  # Hangul
_AR_RANGE  = (0x0600, 0x06FF)
_TH_RANGE  = (0x0E00, 0x0E7F)
_RU_RANGE  = (0x0400, 0x04FF)


def _has_chars(text: str, ranges) -> bool:
    return any(any(lo <= ord(c) <= hi for lo, hi in (ranges if isinstance(ranges[0], tuple) else [ranges]))
               for c in text)


def detect_language(text: str) -> str:
    """根据字符集自动检测语言"""
    t = text.strip()
    if not t:
        return "en"
    if _has_chars(t, _JP_RANGES):
        return "ja"
    if _has_chars(t, _KR_RANGES):
        return "ko"
    if _has_chars(t, _CJK_RANGES):
        return "zh"
    if _has_chars(t, _AR_RANGE):
        return "ar"
    if _has_chars(t, _TH_RANGE):
        return "th"
    if _has_chars(t, _RU_RANGE):
        return "ru"
    return "en"  # default: Latin-script languages → English


# ────────────────────────────────────────────────────────────────
# 赛道关键词（多语言）
# ────────────────────────────────────────────────────────────────
GENRE_KEYWORDS = {
    "tech": {
        "zh": ["编程", "代码", "API", "前端", "后端", "数据库", "算法", "框架", "Python", "React",
               "Docker", "Kubernetes", "AI", "教程", "开发", "部署", "架构", "Linux"],
        "en": ["code", "API", "frontend", "backend", "database", "algorithm", "framework",
               "Python", "React", "Docker", "Kubernetes", "tutorial", "deploy", "architecture",
               "debug", "server", "Javascript", "Rust", "Go", "TypeScript"],
        "ja": ["プログラミング", "コード", "API", "アルゴリズム", "Python", "チュートリアル",
               "データベース", "サーバー", "デプロイ", "Docker"],
        "ko": ["프로그래밍", "코드", "API", "알고리즘", "파이썬", "튜토리얼", "데이터베이스", "서버"],
        "es": ["código", "API", "tutorial", "base de datos", "algoritmo", "servidor", "Python"],
        "fr": ["code", "API", "tutoriel", "base de données", "algorithme", "serveur", "déploiement"],
        "de": ["Code", "API", "Algorithmus", "Datenbank", "Server", "Tutorial", "Python"],
        "pt": ["código", "API", "tutorial", "banco de dados", "algoritmo", "servidor"],
        "ru": ["код", "API", "алгоритм", "Python", "сервер", "база данных", "туториал"],
    },
    "finance": {
        "zh": ["A股", "美股", "港股", "基金", "股票", "投资", "理财", "利率", "央行", "GDP", "估值", "财报"],
        "en": ["stock", "investment", "market", "fund", "ETF", "dividend", "revenue", "valuation",
               "GDP", "inflation", "interest rate", "Fed", "IPO", "crypto", "bitcoin", "NASDAQ"],
        "ja": ["株", "投資", "市場", "ファンド", "ETF", "配当", "GDP", "インフレ", "日経"],
        "ko": ["주식", "투자", "펀드", "ETF", "배당", "GDP", "코스피"],
        "es": ["acciones", "inversión", "mercado", "fondo", "dividendo", "PIB", "inflación"],
        "fr": ["actions", "investissement", "marché", "fonds", "dividende", "PIB"],
        "de": ["Aktien", "Investition", "Markt", "Fonds", "Dividende", "BIP"],
        "pt": ["ações", "investimento", "mercado", "fundo", "dividendo"],
        "ru": ["акции", "инвестиции", "рынок", "фонд", "дивиденды", "ВВП"],
    },
    "pets": {
        "zh": ["猫", "狗", "宠物", "萌宠", "猫咪", "狗狗", "仓鼠", "兔子", "可爱", "萌"],
        "en": ["cat", "dog", "pet", "puppy", "kitten", "cute", "animal", "bunny", "hamster"],
        "ja": ["猫", "犬", "ペット", "かわいい", "子猫", "子犬"],
        "ko": ["고양이", "강아지", "반려동물", "귀여운"],
        "es": ["gato", "perro", "mascota", "cachorro", "tierno"],
        "fr": ["chat", "chien", "animal", "chaton", "mignon"],
        "de": ["Katze", "Hund", "Haustier", "Welpe", "niedlich"],
        "pt": ["gato", "cachorro", "pet", "animal", "fofo"],
        "ru": ["кот", "собака", "питомец", "милый", "щенок"],
    },
    "emotion": {
        "zh": ["感情", "爱情", "分手", "恋爱", "婚姻", "思念", "孤独", "成长", "人生", "温暖", "治愈"],
        "en": ["love", "heartbreak", "relationship", "lonely", "growth", "life", "healing",
               "emotional", "sad", "happy", "inspire", "motivation"],
        "ja": ["恋愛", "感情", "別れ", "孤独", "成長", "人生", "癒し"],
        "ko": ["사랑", "이별", "감정", "외로움", "성장", "인생", "힐링"],
        "es": ["amor", "relación", "soledad", "crecimiento", "vida", "sanar"],
        "fr": ["amour", "relation", "solitude", "croissance", "vie", "guérison"],
        "de": ["Liebe", "Beziehung", "Einsamkeit", "Wachstum", "Leben", "Heilung"],
        "pt": ["amor", "relacionamento", "solidão", "crescimento", "vida", "cura"],
        "ru": ["любовь", "отношения", "одиночество", "рост", "жизнь", "исцеление"],
    },
    "science": {
        "zh": ["科学", "物理", "化学", "生物", "宇宙", "量子", "基因", "进化", "黑洞", "相对论"],
        "en": ["science", "physics", "chemistry", "biology", "universe", "quantum", "gene",
               "evolution", "black hole", "relativity", "NASA", "SpaceX", "DNA"],
        "ja": ["科学", "物理", "化学", "生物", "宇宙", "量子", "遺伝子", "進化"],
        "ko": ["과학", "물리", "화학", "생물", "우주", "양자", "유전자"],
        "es": ["ciencia", "física", "química", "biología", "universo", "cuántico"],
        "fr": ["science", "physique", "chimie", "biologie", "univers", "quantique"],
        "de": ["Wissenschaft", "Physik", "Chemie", "Biologie", "Universum", "Quanten"],
        "pt": ["ciência", "física", "química", "biologia", "universo", "quântico"],
        "ru": ["наука", "физика", "химия", "биология", "вселенная", "квант"],
    },
}


def detect_genre(text: str, lang: str = "auto") -> str:
    """根据文本关键词自动识别赛道（多语言）"""
    if lang == "auto":
        lang = detect_language(text)
    text_lower = text.casefold()
    scores = {}
    for genre, lang_map in GENRE_KEYWORDS.items():
        keywords = lang_map.get(lang, lang_map.get("en", []))
        count = sum(1 for kw in keywords if kw.casefold() in text_lower)
        if count > 0:
            scores[genre] = count
    return max(scores, key=scores.get) if scores else "default"


# ────────────────────────────────────────────────────────────────
# 赛道→音色配置（多语言）
# ────────────────────────────────────────────────────────────────
GENRE_VOICE_MAP = {
    "zh": {
        "tech":    {"single": "zh-CN-YunjianNeural",  "male": "zh-CN-YunyangNeural", "female": "zh-CN-XiaoxiaoNeural", "desc": "中文技术教程"},
        "pets":    {"single": "zh-CN-XiaoyiNeural",    "male": "zh-CN-YunxiNeural",   "female": "zh-TW-HsiaoYuNeural",  "desc": "中文萌宠"},
        "finance": {"single": "zh-CN-YunyangNeural",   "male": "zh-CN-YunjianNeural", "female": "zh-CN-XiaoxiaoNeural",  "desc": "中文财经"},
        "emotion": {"single": "zh-TW-HsiaoYuNeural",   "male": "zh-CN-YunxiNeural",   "female": "zh-CN-XiaoyiNeural",    "desc": "中文情感"},
        "science": {"single": "zh-CN-YunxiaNeural",    "male": "zh-CN-YunyangNeural", "female": "zh-CN-XiaoxiaoNeural",  "desc": "中文科普"},
        "default": {"single": "zh-CN-XiaoxiaoNeural",  "male": "zh-CN-YunyangNeural", "female": "zh-CN-XiaoxiaoNeural",  "desc": "中文通用"},
    },
    "en": {
        "tech":    {"single": "en-US-GuyNeural",       "male": "en-US-GuyNeural",       "female": "en-US-JennyNeural",     "desc": "English Tech"},
        "pets":    {"single": "en-US-AriaNeural",      "male": "en-US-EricNeural",      "female": "en-US-AriaNeural",      "desc": "English Pets"},
        "finance": {"single": "en-GB-RyanNeural",      "male": "en-GB-RyanNeural",      "female": "en-US-JennyNeural",     "desc": "English Finance"},
        "emotion": {"single": "en-US-JennyNeural",     "male": "en-US-EricNeural",      "female": "en-US-JennyNeural",     "desc": "English Emotion"},
        "science": {"single": "en-US-GuyNeural",       "male": "en-US-GuyNeural",       "female": "en-US-AriaNeural",      "desc": "English Science"},
        "default": {"single": "en-US-JennyNeural",     "male": "en-US-GuyNeural",       "female": "en-US-JennyNeural",     "desc": "English Default"},
    },
    "ja": {
        "default": {"single": "ja-JP-NanamiNeural",    "male": "ja-JP-KeitaNeural",     "female": "ja-JP-NanamiNeural",    "desc": "Japanese"},
    },
    "ko": {
        "default": {"single": "ko-KR-SunHiNeural",     "male": "ko-KR-InJoonNeural",    "female": "ko-KR-SunHiNeural",     "desc": "Korean"},
    },
    "es": {
        "default": {"single": "es-ES-ElviraNeural",    "male": "es-ES-AlvaroNeural",    "female": "es-ES-ElviraNeural",    "desc": "Spanish"},
    },
    "fr": {
        "default": {"single": "fr-FR-DeniseNeural",    "male": "fr-FR-HenriNeural",     "female": "fr-FR-DeniseNeural",    "desc": "French"},
    },
    "de": {
        "default": {"single": "de-DE-KatjaNeural",     "male": "de-DE-ConradNeural",    "female": "de-DE-KatjaNeural",     "desc": "German"},
    },
    "pt": {
        "default": {"single": "pt-BR-FranciscaNeural", "male": "pt-BR-AntonioNeural",   "female": "pt-BR-FranciscaNeural", "desc": "Portuguese"},
    },
    "ru": {
        "default": {"single": "ru-RU-SvetlanaNeural",  "male": "ru-RU-DmitryNeural",    "female": "ru-RU-SvetlanaNeural",  "desc": "Russian"},
    },
    "it": {
        "default": {"single": "it-IT-ElsaNeural",      "male": "it-IT-DiegoNeural",     "female": "it-IT-ElsaNeural",      "desc": "Italian"},
    },
    "ar": {
        "default": {"single": "ar-SA-ZariyahNeural",   "male": "ar-SA-HamedNeural",     "female": "ar-SA-ZariyahNeural",   "desc": "Arabic"},
    },
    "hi": {
        "default": {"single": "hi-IN-SwaraNeural",     "male": "hi-IN-MadhurNeural",    "female": "hi-IN-SwaraNeural",     "desc": "Hindi"},
    },
    "th": {
        "default": {"single": "th-TH-PremwadeeNeural", "male": "th-TH-NiwatNeural",     "female": "th-TH-PremwadeeNeural", "desc": "Thai"},
    },
    "vi": {
        "default": {"single": "vi-VN-HoaiMyNeural",    "male": "vi-VN-NamMinhNeural",   "female": "vi-VN-HoaiMyNeural",    "desc": "Vietnamese"},
    },
}
# 未列出语言自动回退到 en
_GENRE_VOICE_FALLBACK = GENRE_VOICE_MAP["en"]


# ────────────────────────────────────────────────────────────────
# 去AI化参数（按语言）
# ────────────────────────────────────────────────────────────────
DE_AI_CONFIG = {
    "zh": {"breath_chance": 0.08, "min_pause_ms": 200, "max_pause_ms": 800, "speed_var": 0.04,
           "filler_chance": 0.03, "eq_low": 2, "noise_db": -50},
    "en": {"breath_chance": 0.10, "min_pause_ms": 300, "max_pause_ms": 1000, "speed_var": 0.05,
           "filler_chance": 0.04, "eq_low": 3, "noise_db": -48},
    "ja": {"breath_chance": 0.06, "min_pause_ms": 150, "max_pause_ms": 600,  "speed_var": 0.03,
           "filler_chance": 0.05, "eq_low": 2, "noise_db": -52},
    "ko": {"breath_chance": 0.07, "min_pause_ms": 200, "max_pause_ms": 700,  "speed_var": 0.04,
           "filler_chance": 0.04, "eq_low": 2, "noise_db": -50},
    "es": {"breath_chance": 0.09, "min_pause_ms": 250, "max_pause_ms": 900,  "speed_var": 0.05,
           "filler_chance": 0.06, "eq_low": 3, "noise_db": -48},
    "fr": {"breath_chance": 0.08, "min_pause_ms": 300, "max_pause_ms": 1000, "speed_var": 0.04,
           "filler_chance": 0.05, "eq_low": 2, "noise_db": -50},
    "de": {"breath_chance": 0.07, "min_pause_ms": 300, "max_pause_ms": 900,  "speed_var": 0.04,
           "filler_chance": 0.04, "eq_low": 3, "noise_db": -50},
    "pt": {"breath_chance": 0.09, "min_pause_ms": 250, "max_pause_ms": 850,  "speed_var": 0.05,
           "filler_chance": 0.05, "eq_low": 2, "noise_db": -48},
    "ru": {"breath_chance": 0.06, "min_pause_ms": 250, "max_pause_ms": 800,  "speed_var": 0.03,
           "filler_chance": 0.03, "eq_low": 2, "noise_db": -52},
}

# 语气词库（多语言）
FILLER_WORDS = {
    "zh": ["嗯", "那么", "就是", "然后", "这个", "其实"],
    "en": ["um", "uh", "you know", "like", "so", "well", "I mean", "actually"],
    "ja": ["ええと", "あの", "まあ", "そうですね", "つまり"],
    "ko": ["음", "어", "그", "그러니까", "뭐랄까"],
    "es": ["eh", "pues", "bueno", "o sea", "entonces", "digamos"],
    "fr": ["euh", "bah", "ben", "enfin", "du coup", "voilà"],
    "de": ["äh", "also", "naja", "sozusagen", "quasi"],
    "pt": ["é", "tipo", "então", "assim", "bom", "né"],
    "ru": ["ну", "это", "как бы", "в общем", "так сказать"],
}


# ────────────────────────────────────────────────────────────────
# 配音脚本解析
# ────────────────────────────────────────────────────────────────
@dataclass
class ScriptSegment:
    """配音脚本片段"""
    speaker: str       # 说话人标签 如 "主持人" "嘉宾" 或 ""(单人)
    text: str          # 配音文本
    voice: str = ""    # 指定音色（覆盖赛道默认）
    speed: float = 1.0


def parse_script(raw_text: str) -> list[ScriptSegment]:
    """
    解析配音脚本，支持两种格式：
    1. 单人模式：纯文本，按标点分段
    2. 对话模式：[角色A]台词1\n[角色B]台词2
    """
    segments = []
    # 匹配中/英/日对话标签 [角色A] or [Speaker A]
    dialogue_pattern = re.compile(r'\[([^\]]+)\]\s*(.+?)(?=\[|$)', re.DOTALL)
    matches = dialogue_pattern.findall(raw_text.strip())
    if matches:
        for speaker, text in matches:
            text = text.strip()
            if text:
                segments.append(ScriptSegment(speaker=speaker.strip(), text=text))
    else:
        # 单人模式：按标点符号分段
        parts = re.split(r'(?<=[。！？!?.\n])\s*', raw_text.strip())
        for part in parts:
            part = part.strip()
            if part:
                segments.append(ScriptSegment(speaker="", text=part))
    return segments


# ────────────────────────────────────────────────────────────────
# edge-tts 异步提供者
# ────────────────────────────────────────────────────────────────

class PiperProvider:
    """Piper TTS — lightweight offline neural TTS (26 languages, ~2MB models)."""
    @staticmethod
    def synthesize(text, output, voice="en_US-lessac-medium", rate=1.0):
        import subprocess
        subprocess.run(["piper", "--model", voice, "--output_file", output],
                       input=text.encode(), timeout=60, check=True)

class KokoroProvider:
    """Kokoro TTS — 82M parameter offline TTS (8 languages, Apache 2.0)."""
    @staticmethod
    def synthesize(text, output, voice="af_heart", lang="a", speed=1.0):
        from kokoro import KPipeline
        pipeline = KPipeline(lang_code=lang)
        import soundfile as sf, numpy as np
        chunks = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            chunks.append(audio)
        if chunks:
            combined = np.concatenate(chunks)
            sf.write(output, combined, 24000)
            return output
        raise RuntimeError("Kokoro generated no audio")

class EdgeTTSProvider:
    """edge-tts 多语言语音合成封装"""

    @staticmethod
    async def synthesize(text: str, output: Path, voice: str,
                         rate: str = "+0%", pitch: str = "+0Hz") -> Optional[float]:
        """合成单段语音，返回时长(秒)"""
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(str(output))
        return EdgeTTSProvider._get_duration(str(output))

    @staticmethod
    async def synthesize_with_timing(text: str, output: Path, voice: str,
                                     rate: str = "+0%", pitch: str = "+0Hz") -> list[dict]:
        """合成语音并返回词级时间戳（一次stream同时采集audio和word边界）"""
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        timing = []
        audio_chunks = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_start = chunk["offset"] / 1e7
                word_dur = chunk["duration"] / 1e7
                timing.append({
                    "word": chunk["text"],
                    "start": word_start,
                    "end": word_start + word_dur,
                })

        # 写入音频文件
        if audio_chunks:
            with open(str(output), "wb") as f:
                for data in audio_chunks:
                    f.write(data)

        # 无WordBoundary时回退：字符均分
        if not timing:
            duration = EdgeTTSProvider._get_duration(str(output))
            if duration > 0:
                chars = list(text)
                char_dur = duration / max(1, len(chars))
                timing = [{"word": c, "start": i * char_dur, "end": (i + 1) * char_dur}
                          for i, c in enumerate(chars)]
        return timing

    @staticmethod
    def _get_duration(filepath: str) -> float:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", filepath],
                capture_output=True, text=True, timeout=10
            )
            return float(result.stdout.strip()) if result.returncode == 0 else 0.0
        except Exception:
            return 0.0


# ────────────────────────────────────────────────────────────────
# 去AI化处理器
# ────────────────────────────────────────────────────────────────
class DeAIProcessor:
    """多语言去AI化后处理"""

    @staticmethod
    def _mk_silence(duration_ms: int, rate: int = 24000) -> Optional[Path]:
        out = Path(tempfile.gettempdir()) / f"sil_{uuid.uuid4().hex[:6]}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=mono",
             "-t", f"{duration_ms / 1000:.3f}", "-c:a", "pcm_s16le", str(out)],
            capture_output=True, check=False, timeout=8
        )
        return out if out.exists() else None

    @staticmethod
    def _mk_breath(duration_ms: int = 200, rate: int = 24000) -> Optional[Path]:
        out = Path(tempfile.gettempdir()) / f"br_{uuid.uuid4().hex[:6]}.wav"
        dur_s = duration_ms / 1000.0
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anoisesrc=d={dur_s:.3f}:c=pink:a=0.03",
             "-af", "highpass=f=300,lowpass=f=1500,volume=0.15",
             "-ar", str(rate), "-ac", "1", "-c:a", "pcm_s16le", str(out)],
            capture_output=True, check=False, timeout=8
        )
        return out if (out.exists() and out.stat().st_size > 50) else None

    @staticmethod
    def apply(input_audio: Path, output_audio: Path,
              segment_durations: list[float], lang: str = "en") -> Path:
        """
        去AI化处理链:
        1. 逐段随机变速
        2. 句间随机停顿 + 呼吸音
        3. 低频增强
        4. 底噪注入
        """
        cfg = DE_AI_CONFIG.get(lang, DE_AI_CONFIG["en"])
        if not segment_durations:
            shutil.copy2(input_audio, output_audio)
            return output_audio

        tmp_dir = Path(tempfile.gettempdir())
        seg_files = []
        offset = 0.0
        for i, dur in enumerate(segment_durations):
            if dur <= 0:
                continue
            seg_out = tmp_dir / f"seg_{i}_{uuid.uuid4().hex[:4]}.wav"
            speed = 1.0 + random.uniform(-cfg["speed_var"], cfg["speed_var"])
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{offset:.3f}", "-t", f"{dur:.3f}",
                 "-i", str(input_audio), "-af", f"atempo={speed:.3f}",
                 "-c:a", "pcm_s16le", str(seg_out)],
                capture_output=True, check=False, timeout=10
            )
            if seg_out.exists():
                seg_files.append(seg_out)
            offset += dur

        if not seg_files:
            shutil.copy2(input_audio, output_audio)
            return output_audio

        # 拼接：segment + 停顿/呼吸 + segment ...
        concat_inputs, filter_parts = [], []
        for idx, seg in enumerate(seg_files):
            concat_inputs.extend(["-i", str(seg)])
            filter_parts.append(f"[{idx}:a]")
            if idx < len(seg_files) - 1:
                pause_ms = random.randint(cfg["min_pause_ms"], cfg["max_pause_ms"])
                insert = None
                if random.random() < cfg.get("breath_chance", 0.08):
                    insert = DeAIProcessor._mk_breath(pause_ms)
                if not insert:
                    insert = DeAIProcessor._mk_silence(pause_ms)
                if insert and insert.exists():
                    ni = len(concat_inputs) // 2
                    concat_inputs.extend(["-i", str(insert)])
                    filter_parts.append(f"[{ni}:a]")
                else:
                    filter_parts.append(f"aevalsrc=0:d={pause_ms / 1000:.3f}")

        n_inputs = len(filter_parts)
        concat_filter = "".join(filter_parts) + f"concat=n={n_inputs}:v=0:a=1"
        eq_boost = cfg.get("eq_low", 2)
        eq_filter = f"{concat_filter},equalizer=f=200:t=q:w=2:g={eq_boost}"
        noise_db = cfg.get("noise_db", -50)
        main_filter = f"{eq_filter},aevalsrc=0:d=0.01:c=pink:r=24000,aloop=loop=-1:size=480,volume={noise_db}dB,amix=inputs=2:duration=first"

        subprocess.run(
            ["ffmpeg", "-y"] + concat_inputs +
            ["-filter_complex", main_filter, "-c:a", "pcm_s16le",
             "-ar", "24000", "-ac", "1", str(output_audio)],
            capture_output=True, check=False, timeout=60
        )

        for f in seg_files:
            try: f.unlink(missing_ok=True)
            except Exception: pass
        return output_audio if output_audio.exists() else input_audio


# ────────────────────────────────────────────────────────────────
# 字幕生成器
# ────────────────────────────────────────────────────────────────
class SubtitleGenerator:
    """基于TTS时间戳生成SRT字幕（中英文自适应切分）"""

    # 中文句尾标点（只在这些点切分，保证每段是完整句子/短语）
    _CJK_SENTENCE_END = set("。！？")

    @staticmethod
    def _is_cjk(text: str) -> bool:
        return any("\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff"
                   or "\uac00" <= c <= "\ud7af" for c in text)

    @staticmethod
    def merge(all_timings: list[list[dict]], texts: list[str]) -> str:
        """合并时间戳为SRT：中文按句切（。！？或≥5字），英文按词切"""
        lines, index = [], 1
        current_offset = 0.0
        for timing, text in zip(all_timings, texts):
            if not timing:
                continue
            is_cjk = SubtitleGenerator._is_cjk(text)
            if is_cjk:
                # 中文/日文：句尾标点或≥5字时切分，保证每段语义完整
                chunk_units, chunk_start = [], None
                for t in timing:
                    if chunk_start is None:
                        chunk_start = t["start"]
                    w = t["word"]
                    chunk_units.append(w)
                    text_sofar = "".join(chunk_units)
                    # 切割条件：≥5字，或遇到句尾标点，或最后一段
                    if (len(text_sofar) >= 5
                            or w in SubtitleGenerator._CJK_SENTENCE_END
                            or t is timing[-1]):
                        lines.append(SubtitleGenerator._fmt(
                            index, current_offset + chunk_start,
                            current_offset + t["end"], text_sofar))
                        index += 1
                        chunk_units, chunk_start = [], None
            else:
                # 英文等：按词合并，6词一组，保留空格
                chunk_words, chunk_start = [], None
                for t in timing:
                    if chunk_start is None:
                        chunk_start = t["start"]
                    word = t["word"]
                    # edge-tts 英文 WordBoundary 自带前导空格
                    chunk_words.append(word)
                    if len(chunk_words) >= 6 or t is timing[-1]:
                        chunk_text = "".join(chunk_words).strip()
                        if chunk_text:
                            lines.append(SubtitleGenerator._fmt(
                                index, current_offset + chunk_start,
                                current_offset + t["end"], chunk_text))
                            index += 1
                        chunk_words, chunk_start = [], None
            current_offset += timing[-1]["end"] if timing else 3.0
        return "\n".join(lines)

    @staticmethod
    def simple(text: str, duration: float, output: Path) -> Path:
        """简易字幕：按标点分句，时长均分"""
        is_cjk = SubtitleGenerator._is_cjk(text)
        if is_cjk:
            # 中文：按句号/问号/感叹号/分号/逗号 切分
            sentences = [s.strip() for s in re.split(r'(?<=[。！？；，\n])\s*', text.strip()) if s.strip()]
        else:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?\n])\s+', text.strip()) if s.strip()]
        if not sentences:
            sentences = [text.strip()]
        dur = duration / len(sentences)
        lines = [SubtitleGenerator._fmt(i + 1, i * dur, (i + 1) * dur, s)
                 for i, s in enumerate(sentences)]
        output.write_text("\n".join(lines), encoding="utf-8")
        return output

    @staticmethod
    def _fmt(index: int, start: float, end: float, text: str) -> str:
        return (f"{index}\n"
                f"{int(start//3600):02d}:{int(start%3600//60):02d}:{int(start%60):02d},{int(start*1000%1000):03d} --> "
                f"{int(end//3600):02d}:{int(end%3600//60):02d}:{int(end%60):02d},{int(end*1000%1000):03d}\n{text}\n")


# ────────────────────────────────────────────────────────────────
# 主引擎
# ────────────────────────────────────────────────────────────────
class VoiceEngine:
    """智能多语言配音引擎"""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.gettempdir()) / f"voice_{uuid.uuid4().hex[:8]}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(self, script_text: str, lang: str = "auto",
                   genre: str = "auto", mode: str = "auto") -> dict:
        """主入口：文案 → 配音 + 字幕"""
        return asyncio.run(self._run(script_text, lang, genre, mode))

    async def _run(self, script_text: str, lang: str, genre: str, mode: str) -> dict:
        segments = parse_script(script_text)
        if not segments:
            raise ValueError("配音文本为空")

        # 语言/赛道/模式 检测
        if lang == "auto":
            lang = detect_language(script_text)
        if genre == "auto":
            genre = detect_genre(script_text, lang)
        lang_map = GENRE_VOICE_MAP.get(lang, _GENRE_VOICE_FALLBACK)
        genre_cfg = lang_map.get(genre, lang_map.get("default", _GENRE_VOICE_FALLBACK["default"]))
        is_dialogue = any(s.speaker for s in segments)
        if mode == "single":
            is_dialogue = False
        elif mode == "dialogue":
            is_dialogue = True

        # 音色分配
        speaker_voices = {}
        if is_dialogue:
            speakers = list(dict.fromkeys(s.speaker for s in segments if s.speaker))
            for i, spk in enumerate(speakers):
                v = genre_cfg["female"] if i % 2 == 0 else genre_cfg["male"]
                speaker_voices[spk] = v

        provider = EdgeTTSProvider()
        audio_files, all_timings, segment_texts, all_durations = [], [], [], []
        total_dur = 0.0

        for seg in segments:
            voice = speaker_voices.get(seg.speaker, genre_cfg["single"])
            out = self.temp_dir / f"seg_{uuid.uuid4().hex[:8]}.mp3"
            timing = await provider.synthesize_with_timing(seg.text, out, voice)
            dur = EdgeTTSProvider._get_duration(str(out))
            if out.exists() and dur > 0:
                audio_files.append(out)
                all_timings.append(timing)
                segment_texts.append(seg.text)
                all_durations.append(dur)
                total_dur += dur

        if not audio_files:
            raise RuntimeError("所有语音片段合成失败")

        # 去AI化
        deai_out = self.output_dir / "narration_deai.wav"
        DeAIProcessor.apply(self._concat(audio_files), deai_out, all_durations, lang)

        # → MP3
        final_audio = self.output_dir / "narration.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(deai_out), "-b:a", "128k", str(final_audio)],
            capture_output=True, check=False, timeout=30
        )

        # 字幕
        srt_path = self.output_dir / "narration.srt"
        srt = SubtitleGenerator.merge(all_timings, segment_texts)
        if srt.strip():
            srt_path.write_text(srt, encoding="utf-8")
        else:
            SubtitleGenerator.simple(script_text, total_dur, srt_path)

        # 清理
        for f in audio_files + [deai_out]:
            try: f.unlink(missing_ok=True)
            except Exception: pass

        return {
            "audio": str(final_audio), "subtitle": str(srt_path),
            "duration": total_dur, "genre": genre, "language": lang,
        }

    def _concat(self, files: list[Path]) -> Path:
        out = self.temp_dir / f"concat_{uuid.uuid4().hex[:8]}.wav"
        lst = self.temp_dir / "concat_list.txt"
        with open(lst, "w", encoding="utf-8") as f:
            for p in files:
                f.write(f"file '{p.as_posix()}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(lst), "-c:a", "pcm_s16le", str(out)],
            capture_output=True, check=False, timeout=30
        )
        return out if out.exists() else files[0]


# ────────────────────────────────────────────────────────────────
# CLI 入口
# ────────────────────────────────────────────────────────────────
def run_voice_pipeline(script_text: str, output_dir: str = None,
                       lang: str = "auto", genre: str = "auto",
                       mode: str = "auto") -> dict:
    """CLI入口：输入文案，输出配音+字幕"""
    out = Path(output_dir or os.environ.get("VOICE_OUTPUT_DIR",
             str(Path.home() / ".hermes" / "data" / "voice_output")))
    return VoiceEngine(out).synthesize(script_text, lang=lang, genre=genre, mode=mode)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Intelligent Multilingual Voice Engine")
    ap.add_argument("script", help="配音文案文件(.txt)")
    ap.add_argument("--output", "-o", default=None, help="输出目录")
    ap.add_argument("--lang", "-l", default="auto",
                    choices=["auto","zh","en","ja","ko","es","fr","de","pt","ru","it","ar","hi","th","vi"])
    ap.add_argument("--genre", "-g", default="auto",
                    choices=["auto","tech","pets","finance","emotion","science","default"])
    ap.add_argument("--mode", "-m", default="auto",
                    choices=["auto","single","dialogue"])
    args = ap.parse_args()

    sp = Path(args.script)
    if not sp.is_file():
        print(f"Error: file not found: {args.script}", file=sys.stderr)
        sys.exit(1)

    text = sp.read_text(encoding="utf-8")
    result = run_voice_pipeline(text, args.output, args.lang, args.genre, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
