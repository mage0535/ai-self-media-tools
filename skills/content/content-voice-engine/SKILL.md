---
name: content-voice-engine
description: Intelligent multilingual voice engine - text to natural speech with genre adaptation, de-AI processing, and subtitles
category: content
trigger_keywords: [voice-engine, tts, 配音, 语音合成, text-to-speech, dubbing, narration, ai-voice]
---

## Voice Engine - 智能多语言配音引擎

Converts text scripts into natural-sounding speech with automatic genre/style adaptation, de-AI processing, and subtitle generation. Supports 84+ languages.

### Usage

```python
from scripts.voice_engine import run_voice_pipeline

result = run_voice_pipeline(
    "Python is the most popular programming language for AI development.",
    lang="en", genre="tech"
)
# result["audio"]   - path to MP3 narration
# result["subtitle"] - path to SRT subtitle file
# result["duration"] - audio length in seconds
```

### CLI

```bash
python scripts/voice_engine.py script.txt --lang auto --genre auto
python scripts/voice_engine.py script.txt --lang zh --genre tech --mode dialogue
```

### Supported Languages

Chinese (zh), English (en), Japanese (ja), Korean (ko), Spanish (es), French (fr),
German (de), Portuguese (pt), Russian (ru), Italian (it), Arabic (ar), Hindi (hi),
Thai (th), Vietnamese (vi) — plus 70+ more via auto-fallback to English voices.

### Genre Adaptation

| Genre | Description | Voice Style |
|-------|-------------|-------------|
| tech | Tech tutorials | Calm male, moderate speed |
| pets | Cute animals | Lively female, faster |
| finance | Finance/economy | Deep male, slower |
| emotion | Life/relationships | Warm female, natural |
| science | Science explainers | Neutral male, moderate |
| default | General content | Default female |

### Dialogue Mode

Scripts using `[Speaker A]` / `[Speaker B]` tags are automatically detected as multi-speaker.
Voices are assigned alternating female/male from the selected genre.

### De-AI Processing

- Random breath sounds at punctuation boundaries
- Variable pauses between sentences (200-1000ms)
- Subtle speed fluctuation (±4-5% per sentence)
- Low-frequency EQ boost for vocal warmth
- -50dB noise floor for natural ambience

### Pipeline Integration

Registered in content_platform/media.py as `audio` artifact kind.
The pipeline auto-generates voice when `narration_script` is present in `draft_meta`.

### Dependencies

- edge-tts (python, 84+ languages via Microsoft Edge TTS)
- ffmpeg (system, for audio post-processing)

### Quality Gate

Output is validated by `content_quality_gate.py` — checks for audio file existence and minimum duration.
