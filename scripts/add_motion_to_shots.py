import json
import subprocess
from pathlib import Path

BASE_DIR = Path('/root/.ai-self-media-tools/data/runs/kuaishou/20260922_dialogue_r1')
CUSTOM_DIR = BASE_DIR / 'custom_render'
CARD_DIR = CUSTOM_DIR / 'card_images'
SHOTS_DIR = CUSTOM_DIR / 'shots'
AUDIO_DIR = BASE_DIR / 'audio'
OUTPUT_DIR = BASE_DIR / 'render'

# 8 segments TTS durations
durations = json.loads((AUDIO_DIR / 'durations.json').read_text('utf-8'))
durs = [
    durations['s01'], # 9.408
    durations['s02'], # 9.864
    durations['s03'], # 5.904
    durations['s04'], # 8.136
    durations['s05'], # 8.472
    durations['s06'], # 8.616
    durations['s07'], # 8.160
    durations['s08'], # 9.432
]

# Use continuous Ken Burns motion with slightly higher delta (zoom+0.0018 / pan)
print("Re-encoding 16 shots with cinema-grade motion flow...")
for idx in range(8):
    sid = f'shot_{idx+1:02d}'
    dur = durs[idx]
    dur_a = round(dur * 0.45, 2)
    dur_b = round(dur - dur_a, 2)
    
    for suffix, d in [('A', dur_a), ('B', dur_b)]:
        name = f'{sid}{suffix}'
        png_path = CARD_DIR / f'{name}.png'
        mp4_path = SHOTS_DIR / f'{name}.mp4'
        frames = int(d * 25)
        
        # Smooth directional pan & slow zoom that gives delta ~0.018-0.022 without jitter
        if idx % 2 == 0:
            vf = f"zoompan=z='min(1.10,1.0+0.0008*on)':x='iw/2-(iw/zoom/2)+sin(on/10)*2':y='ih/2-(ih/zoom/2)':d={frames}:s=720x1280:fps=25,format=yuv420p"
        else:
            vf = f"zoompan=z='max(1.0,1.10-0.0008*on)':x='iw/2-(iw/zoom/2)-sin(on/10)*2':y='ih/2-(ih/zoom/2)':d={frames}:s=720x1280:fps=25,format=yuv420p"
            
        cmd = [
            'ffmpeg', '-y', '-loop', '1',
            '-i', str(png_path),
            '-vf', vf,
            '-c:v', 'libx264', '-preset', 'fast', '-profile:v', 'baseline', '-level', '3.1',
            '-pix_fmt', 'yuv420p', '-r', '25',
            '-t', str(d),
            str(mp4_path)
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        print(f"Motion-encoded {name}.mp4 ({d:.2f}s)")

# Re-composite video
print("\nRe-compositing full video with dynamic motion...")
subprocess.run(['python3', '/root/.ai-self-media-tools/scripts/composite_custom_video.py'], check=True)
print("Complete motion-enhanced composite done!")
