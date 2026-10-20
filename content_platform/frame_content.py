"""Distinguish structured light artwork from an unpainted white video frame."""
import subprocess


def frame_has_structure(raw, width=160, height=284):
    if len(raw) != width * height:
        raise ValueError('frame_content_sample_size_invalid')
    background = sorted(raw)[len(raw) // 2]
    dark = [value < background - 40 for value in raw]
    coverage = sum(dark) / len(dark)
    bands = [sum(dark[i * len(dark) // 4:(i + 1) * len(dark) // 4]) / (len(dark) // 4) for i in range(4)]
    # A title or browser watermark alone is not a painted content frame.
    return {'content_present': coverage >= .02 and sum(value >= .01 for value in bands) >= 2,
            'foreground_fraction': round(coverage, 6), 'vertical_band_fractions': [round(x, 6) for x in bands]}


def leading_frame_structure(path, count):
    width, height = 160, 284
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', f'scale={width}:{height},format=gray',
        '-frames:v', str(count), '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'], capture_output=True, timeout=60)
    size = width * height
    if result.returncode or len(result.stdout) != count * size:
        raise ValueError('frame_content_decode_incomplete')
    return [frame_has_structure(result.stdout[i * size:(i + 1) * size]) for i in range(count)]
