---
name: content-ai-autoclip
description: AI automatic video clipping - long video to highlights to compilation
category: content
trigger_keywords: [autoclip, auto-clip, video-clip, highlight-extraction, video-slicing]
---

## AutoClip - AI Video Highlight Extraction

Downloads a long video, transcribes speech to text, extracts highlight segments, clips them, and creates a compilation.

### Usage

```python
from autoclip_adapter import run_autoclip_pipeline

result = run_autoclip_pipeline("https://www.youtube.com/watch?v=...")
# result["clips"] - list of highlight clips
# result["compilation"] - path to combined compilation video
```

### CLI

```bash
python autoclip_adapter.py "https://www.youtube.com/watch?v=..."
python autoclip_adapter.py --check  # check dependencies
```

### Pipeline Integration

Registered in content_generator.py as `video_autoclip` content type. The video_operator.py dispatches to `run_autoclip_pipeline()` automatically.

### Dependencies

- ffmpeg (system)
- yt-dlp (python)
- openai-whisper (python)

### Quality Gate

Output is validated by `content_quality_gate.py` - checks for minimum clip count and compilation file existence.
