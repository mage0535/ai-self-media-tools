"""Tiny non-solid scene clip for delivery tests that must pass the body-visual gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np


def write_color_scene_mp4(path: Path, seconds: float = 1.0) -> None:
    height, width = 284, 160
    yy, xx = np.mgrid[0:height, 0:width]
    frame = np.zeros((height, width, 3), np.uint8)
    frame[..., 0] = np.clip(30 + xx * 0.8 + 12 * np.sin(yy / 14.0), 0, 220).astype(np.uint8)
    frame[..., 1] = np.clip(50 + yy * 0.5 + 18 * np.cos(xx / 16.0), 0, 210).astype(np.uint8)
    frame[..., 2] = np.clip(70 + 28 * np.sin((xx + yy) / 24.0), 0, 200).astype(np.uint8)
    payload = frame.tobytes() * max(1, int(8 * seconds))
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            "8",
            "-i",
            "pipe:0",
            "-t",
            str(seconds),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        input=payload,
        check=True,
    )
