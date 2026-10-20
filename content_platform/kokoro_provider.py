"""Normal local Chinese TTS provider, executed in its isolated runtime."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

MODEL_SHA = '859f9ded9f53be16c24857cdab3254a45da53c3afd5ba6ef134c7de3f822e326'
VOICES_SHA = '14cb6186c99e4f6016871405f62046c5df863ae27465cbdc4ee08be7dd703acd'


class KokoroProvider:
    def __init__(self, options=None):
        self.options = dict(options or {})
        self.home = Path(self.options.get('runtime_home') or os.environ.get('KOKORO_RUNTIME_HOME', Path.home() / '.local/share/kokoro-onnx'))

    def synthesize(self, text, output, *, language='zh'):
        if language not in {'zh', 'zh-CN'} or not text.strip() or len(text) > 5000:
            raise ValueError('kokoro_chinese_text_required')
        output = Path(output).resolve()
        if output.exists():
            raise ValueError('kokoro_output_already_exists')
        payload = {'runtime_home': str(self.home.resolve()), 'text': text, 'output': str(output),
                   'voice': self.options.get('voice', 'zf_001'), 'speed': float(self.options.get('speed', 1.15))}
        if payload['voice'] != 'zf_001' or not .75 <= payload['speed'] <= 1.5:
            raise ValueError('kokoro_voice_or_speed_not_supported')
        env = {k: v for k, v in os.environ.items() if k in {'PATH', 'HOME', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH'}}
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', MKL_NUM_THREADS='4')
        result = subprocess.run([str(self.home / 'venv/bin/python'), '-B', str(Path(__file__).resolve()), '--worker'],
            input=json.dumps(payload).encode(), capture_output=True, env=env, timeout=120)
        records = [line[len(b'KOKORO_RESULT='):] for line in result.stdout.splitlines() if line.startswith(b'KOKORO_RESULT=')]
        if result.returncode or len(records) != 1 or not output.is_file():
            raise RuntimeError('kokoro_local_synthesis_failed:' + result.stderr.decode(errors='replace')[-500:])
        record = json.loads(records[0])
        if record['audio_sha256'] != hashlib.sha256(output.read_bytes()).hexdigest():
            raise ValueError('kokoro_output_hash_changed')
        return record


def _worker(packet):
    import onnxruntime as ort
    import soundfile as sf
    from kokoro_onnx import Kokoro
    from misaki import zh
    home = Path(packet['runtime_home']); models = home / 'models'
    for name, expected in [('kokoro-v1.1-zh.onnx', MODEL_SHA), ('voices-v1.1-zh.bin', VOICES_SHA)]:
        path = models / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('kokoro_model_changed')
    opts = ort.SessionOptions(); opts.intra_op_num_threads = 4; opts.inter_op_num_threads = 1
    session = ort.InferenceSession(str(models / 'kokoro-v1.1-zh.onnx'), sess_options=opts, providers=['CPUExecutionProvider'])
    engine = Kokoro.from_session(session, str(models / 'voices-v1.1-zh.bin'))
    phonemes, _ = zh.ZHG2P(version='1.1')(packet['text'])
    audio, rate = engine.create(phonemes, voice=packet['voice'], speed=packet['speed'], is_phonemes=True)
    if rate != 24000 or len(audio) < 2400:
        raise ValueError('kokoro_audio_empty_or_invalid')
    output = Path(packet['output']); wave = output.with_suffix('.kokoro.wav')
    if output.exists() or wave.exists():
        raise ValueError('kokoro_output_already_exists')
    sf.write(wave, audio, rate, subtype='PCM_16')
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-n', '-i', str(wave), '-c:a', 'libmp3lame', '-b:a', '128k', str(output)],
            capture_output=True, check=True, timeout=30)
    finally:
        wave.unlink(missing_ok=True)
    return {'provider': 'kokoro-onnx', 'voice': packet['voice'], 'speed': packet['speed'], 'fallback_used': False,
            'model': 'Kokoro-82M-v1.1-zh', 'model_sha256': MODEL_SHA, 'voices_sha256': VOICES_SHA,
            'model_license': 'Apache-2.0', 'code_license': 'MIT', 'sample_rate': rate,
            'duration_seconds': len(audio) / rate, 'phonemes_sha256': hashlib.sha256(phonemes.encode()).hexdigest(),
            'audio_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'external_synthesis_calls': 0}


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('internal local provider worker only')
    print('KOKORO_RESULT=' + json.dumps(_worker(json.load(sys.stdin)), ensure_ascii=False))
