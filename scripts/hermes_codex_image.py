"""Dedicated image bridge to the existing Hermes Codex OAuth provider."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--model', default='')
    parser.add_argument('--quality', default='low')
    parser.add_argument('--size', default='1024x1024')
    parser.add_argument('--input-image', default='')
    args = parser.parse_args()
    worker = Path('/srv/hermes-agent/source/root/.hermes/hermes-agent')
    code = worker if worker.is_dir() else Path('/root/.hermes/hermes-agent')
    os.environ['HERMES_HOME'] = '/srv/hermes-runtime' if worker.is_dir() else '/root/.hermes'
    if os.environ.get('US_PROXY'):
        os.environ['HTTP_PROXY'] = os.environ['HTTPS_PROXY'] = os.environ['US_PROXY']
    sys.path.insert(0, str(code))
    plugin = code / 'plugins/image_gen/openai-codex/__init__.py'
    try:
        spec = importlib.util.spec_from_file_location('dedicated_codex_image', plugin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tier = args.quality if args.quality in {'low', 'medium', 'high'} else 'medium'
        model = args.model or 'gpt-image-2-' + tier
        if model == 'gpt-image-2':
            model += '-' + tier
        width, height = map(int, args.size.split('x'))
        aspect = '1:1' if width == height else '16:9' if width > height else '9:16'
        result = module.OpenAICodexImageGenProvider().generate(
            args.prompt, aspect_ratio=aspect, model=model,
            image_url=args.input_image or None)
        source = Path(result['image']) if result.get('success') else None
        if not source or not source.is_file():
            error = str(result.get('error', ''))
            print(json.dumps({'ok': False, 'error_code': result.get('error_code') or 'codex_image_failed',
                              'http_status': next((v for v in ['401','403','404','429','500','503'] if v in error), None)}))
            return 2
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        print(json.dumps({'ok': True, 'provider': 'openai-codex', 'model': result.get('model'),
                          'reported_size': result.get('reported_size'), 'pixel_size': result.get('pixel_size'),
                          'reported_quality': result.get('reported_quality')}))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error_code': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
