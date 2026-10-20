"""Resolve native licensed BGM before video planning; no replacement audio engine."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from content_platform.run_contract import validate_audio_plan


class AudioInputError(ValueError):
    pass


def _path(value, *, existing=True):
    p = Path(value).expanduser().absolute()
    if any(part.is_symlink() for part in (p, *p.parents)):
        raise AudioInputError('symlink_path_rejected')
    if existing and not p.is_file():
        raise AudioInputError('required_file_missing')
    return p


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _json(path):
    if path.stat().st_size > 1024*1024:
        raise AudioInputError('record_too_large')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise AudioInputError('record_object_required')
    return value


def _url(value):
    if not isinstance(value, str):
        raise AudioInputError('source_url_missing')
    parts = urlsplit(value)
    if parts.scheme not in {'https', 'http'} or not parts.hostname or parts.username or parts.password:
        raise AudioInputError('invalid_source_url')
    return value


def _copy(source, target):
    if source == target:
        return
    _path(target, existing=False)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temp = Path(stream.name)
        os.chmod(temp, 0o600)
        try:
            with source.open('rb') as original:
                shutil.copyfileobj(original, stream)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def _rights(record, settings, platform):
    license_url = record.get('license')
    if not isinstance(license_url, str):
        raise AudioInputError('license_string_required')
    # These grants allow embedded, commercial, derivative use subject to their
    # stated obligations. NC/ND and ambiguous labels are never guessed safe.
    licenses = {
        'https://creativecommons.org/licenses/by/4.0/',
        'https://creativecommons.org/publicdomain/zero/1.0/',
    }
    grants = settings.get('license_grants') or {}
    if not isinstance(grants, dict):
        raise AudioInputError('license_grants_object_required')
    grant = grants.get(license_url)
    if license_url not in licenses or not isinstance(grant, dict):
        raise AudioInputError('rights_scope_missing_or_unsupported_license')
    if not isinstance(grant.get('platforms'), list) or platform not in grant['platforms']:
        raise AudioInputError('rights_scope_platform_mismatch')
    if (grant.get('use') != 'embedded_bgm' or grant.get('commercial') is not True
            or grant.get('derivatives') is not True or grant.get('evidence_url') != license_url):
        raise AudioInputError('rights_scope_incomplete')
    if license_url.endswith('/by/4.0/'):
        for field in ('artist', 'title'):
            value = record.get(field)
            if (not isinstance(value, str) or not value.strip() or len(value) > 2048
                    or any(ord(char) < 32 for char in value)):
                raise AudioInputError('attribution_missing_or_malformed')
    return dict(grant)


def _native_quality(audio_dir, settings):
    script = _path(settings['native_quality_script'])
    script_sha = _sha(script)
    if settings.get('native_quality_sha256') not in (None, script_sha):
        raise AudioInputError('native_bgm_quality_script_hash_mismatch')
    # Invoke the existing spectrum gate as-is, never its upload/postcheck main.
    code = (
        "import runpy,sys; "
        "m=runpy.run_path(sys.argv[1],run_name='audio_planner_gate'); "
        "m['check_bgm_spectrum'](sys.argv[2])"
    )
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, '-c', code, str(script), str(audio_dir)],
                            capture_output=True, timeout=90, env=env)
    if result.returncode:
        raise AudioInputError('native_bgm_quality_gate_failed')
    if _sha(script) != script_sha:
        raise AudioInputError('native_bgm_quality_script_changed')
    return {'status': 'passed', 'gate': 'check_bgm_spectrum',
            'gate_sha256': script_sha,
            'response_sha256': hashlib.sha256(result.stdout+result.stderr).hexdigest()}


def _resolve_record(source, settings, platform, output):
    if not isinstance(source, dict):
        raise AudioInputError('source_object_required')
    audio = _path(source['audio_path'])
    record_path = _path(source['record_path'])
    record_sha = _sha(record_path)
    record = _json(record_path)
    if not 500_000 < audio.stat().st_size <= 48*1024*1024:
        raise AudioInputError('native_bgm_file_size_invalid')
    fingerprint = _sha(audio)
    manifest = record.get('manifest') or {}
    if not isinstance(manifest, dict):
        raise AudioInputError('record_manifest_invalid')
    claims = [record.get('sha256'), manifest.get('fingerprint')]
    if not any(claims) or any(claim and claim != fingerprint for claim in claims):
        raise AudioInputError('audio_sha_mismatch')
    if record.get('real_instrument') is not True or record.get('vocal') != 'none':
        raise AudioInputError('native_instrumental_evidence_missing')
    source_url = _url(record.get('source_url'))
    if manifest.get('source_url') not in (None, '', source_url) or manifest.get('license') not in (None, '', record.get('license')):
        raise AudioInputError('record_license_source_conflict')
    rights = _rights(record, settings, platform)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'format=duration:stream=codec_type', '-of', 'json', str(audio)],
                           capture_output=True, timeout=30, check=True)
    measured = json.loads(probe.stdout)
    duration = float(measured.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration < 35 or not any(
            stream.get('codec_type') == 'audio' for stream in measured.get('streams', [])):
        raise AudioInputError('native_bgm_duration_or_stream_invalid')
    _copy(audio, output/'bgm.mp3')
    _copy(record_path, output/'bgm_source.json')
    if (_sha(output/'bgm.mp3') != fingerprint or _sha(audio) != fingerprint
            or _sha(output/'bgm_source.json') != record_sha or _sha(record_path) != record_sha):
        raise AudioInputError('audio_changed_during_resolution')
    quality = _native_quality(output, settings)
    if _sha(output/'bgm.mp3') != fingerprint:
        raise AudioInputError('audio_changed_during_quality_gate')
    plan = {
        'status': 'resolved', 'route': 'embedded_licensed_bgm',
        'route_reason': 'native licensed instrumental with measured file and rights evidence',
        'source_audio_action': 'embed_licensed_bgm', 'fallback_route': None,
        'license': record['license'], 'source_url': source_url,
        'fingerprint': fingerprint, 'rights_scope': rights,
        'audio_path': str(output/'bgm.mp3'),
        'source_record_path': str(output/'bgm_source.json'),
        'source_record_sha256': record_sha,
        'attribution': {'artist': record.get('artist', ''), 'title': record.get('title', ''),
                        'source_url': source_url, 'license': record['license']},
        'audio_evidence': {'duration_seconds': duration, 'sha256': fingerprint},
        'quality_evidence': quality,
    }
    checked = validate_audio_plan(plan, require_bgm=True)
    if not checked['passed']:
        raise AudioInputError('native_audio_contract_failed:'+','.join(checked['failures']))
    return plan


def _online_source(settings, platform, output):
    online = settings.get('online') or {}
    if not isinstance(online, dict):
        raise AudioInputError('online_config_object_required')
    if online.get('enabled') is not True:
        return None
    root = Path(online['native_project_root']).absolute()
    _path(root/'scripts/kuaishou_render.py')
    registry = _path(online['fingerprint_registry'], existing=False)
    style = str(online.get('style', 'acoustic guitar instrumental'))
    if len(style) > 300:
        raise AudioInputError('music_style_too_long')
    env = dict(os.environ, BGM_TARGET_PLATFORM=platform,
               BGM_FINGERPRINT_REGISTRY=str(registry), BGM_RESOLUTION_MAX_SECONDS='60',
               BGM_ARCHIVE_FALLBACK_TIMEOUT='120', PYTHONIOENCODING='utf-8')
    code = ('import sys;sys.path.insert(0,sys.argv[1]); '
            'from scripts.kuaishou_render import download_bgm; '
            'download_bgm(sys.argv[2],sys.argv[3])')
    result = subprocess.run([sys.executable, '-c', code, str(root), str(output), style],
                            capture_output=True, timeout=210, env=env)
    if result.returncode:
        raise AudioInputError('native_music_resolver_failed')
    return {'audio_path': str(output/'bgm.mp3'), 'record_path': str(output/'bgm_source.json')}


def resolve_audio_plan(config, job, data_dir) -> dict:
    """Trusted config only. Online acquisition is opt-in; never enabled by job data.

    A resolved plan references job-private BGM/record files. The video bridge must
    bind these exact files into its render directory before invoking the native
    renderer, rather than resolving a different music track after approval.
    """
    failures = []
    try:
        if not isinstance(config, dict) or not isinstance(job, dict):
            raise AudioInputError('config_and_job_objects_required')
        settings = config.get('audio_plan_resolver') or {}
        if not isinstance(settings, dict):
            raise AudioInputError('audio_plan_resolver_object_required')
        platforms = job.get('platforms') or [job.get('platform')]
        if not isinstance(platforms, list) or len(platforms) != 1 or not isinstance(platforms[0], str) or not platforms[0]:
            raise AudioInputError('single_platform_required')
        platform = platforms[0]
        identity = str(job.get('id') or job.get('job_id') or '')
        if not identity:
            raise AudioInputError('stable_job_identity_required')
        digest = hashlib.sha256((identity+'\0'+platform).encode()).hexdigest()
        output = _path(Path(data_dir)/'audio-planner'/digest, existing=False)
        output.mkdir(parents=True, exist_ok=True)
        sources = settings.get('sources') or []
        if not isinstance(sources, list) or len(sources) > 16:
            raise AudioInputError('bounded_audio_sources_required')
        for source in sources:
            try:
                return _resolve_record(source, settings, platform, output)
            except (AudioInputError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
                failures.append({'source_index': len(failures), 'reason': str(exc)[:240]})
        source = _online_source(settings, platform, output)
        if source:
            return _resolve_record(source, settings, platform, output)
        if not failures:
            failures.append({'reason': 'licensed_music_source_required_online_not_authorized'})
    except (AudioInputError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        failures.append({'reason': str(exc)[:240]})
    return {'status': 'needs_input', 'route': 'resolution_required',
            'route_reason': 'licensed native BGM planning is incomplete',
            'source_audio_action': 'pending_resolution', 'fallback_route': None,
            'failures': failures}
