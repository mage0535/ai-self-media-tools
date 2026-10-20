"""Current policy inputs and real pixel evidence shared by normal media paths.

Flags in a packet are never quality evidence. Source bytes, the native review
query/result/session and the final artifact are checked again at handoff.
"""
import hashlib
import json
import os
import stat
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_record(path, expected=None):
    raw_path = Path(path)
    if (not raw_path.is_absolute() or raw_path.is_symlink()
            or any(p.is_symlink() for p in raw_path.parents)):
        raise ValueError('policy_file_path_untrusted')
    before = raw_path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('policy_regular_file_required')
    checksum = hashlib.sha256()
    fd = os.open(raw_path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
        closed = os.fstat(stream.fileno())
    after = raw_path.stat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if len({identity(before), identity(opened), identity(closed), identity(after)}) != 1:
        raise ValueError('policy_file_changed_during_read')
    actual = checksum.hexdigest()
    if expected and actual != expected:
        raise ValueError('policy_file_sha_changed')
    return {'path': str(raw_path), 'sha256': actual, 'bytes': before.st_size}


def _skill_file(name):
    root = Path(__file__).resolve().parents[1]
    homes = [Path(os.environ.get('HERMES_HOME') or Path.home()/'.hermes')/'skills',
        Path('/srv/hermes-runtime/skills'), root/'skills']
    for base in homes:
        candidate = base/name/'SKILL.md'
        if candidate.is_file():
            # Runtime installation roots may be managed aliases; generated
            # artifacts remain subject to the raw-path no-symlink check.
            return candidate.resolve(strict=True)
    raise FileNotFoundError('policy_required_skill_missing:'+name)


def validate_content_policy_inputs(job, platform_contexts, *, store):
    from .run_contract import build_run_contract, validate_run_contract
    from .strategy_compiler import compile_strategy, validate_compiled_strategy
    from .preflight_manifest import REQUIRED_SKILLS_BY_CHANNEL
    failures = []; records = {}
    for platform in job.get('platforms') or []:
        if platform in {'file', 'demo'}:
            continue
        try:
            context = platform_contexts.get(platform) or {}
            contract = build_run_contract(platform)
            checked = validate_run_contract(contract)
            if not checked.get('passed'):
                raise ValueError('current_run_contract_invalid')
            if not contract.get('visual_quality_standards'):
                raise ValueError('current_visual_policy_missing')
            if contract.get('enforce_strategy_evidence') is not True:
                raise ValueError('strategy_evidence_not_enforced')
            strategy = context.get('strategy') or {}
            source = file_record(strategy.get('path') or '', strategy.get('sha256'))
            compiled = compile_strategy(Path(source['path']), platform)
            if (not validate_compiled_strategy(compiled).get('passed')
                    or compiled != strategy.get('compiled')):
                raise ValueError('actual_compiled_strategy_changed')
            required = set(REQUIRED_SKILLS_BY_CHANNEL.get(platform, ()))
            required.update(x.get('name') for x in context.get('skills') or [] if x.get('name'))
            form = str((job.get('brief') or {}).get('content_form') or '')
            if any(key in form for key in ('video', 'image', 'card', 'article')):
                required.update({'content/visual-quality-standards', 'cover-film-poster'})
            skills = {name: file_record(_skill_file(name)) for name in sorted(required)}
            rulebook = context.get('rulebook') or {}
            rules = file_record(Path(rulebook.get('path') or '').resolve(strict=True))
            actual = json.loads(Path(rules['path']).read_text(encoding='utf-8'))
            if actual.get('visual_quality_standards') != contract['visual_quality_standards']:
                raise ValueError('actual_rulebook_visual_policy_changed')
            records[platform] = {'run_contract': contract, 'rulebook': rules,
                'strategy': source, 'compiled_strategy_sha256': digest(compiled), 'skills': skills,
                'executed_checks': ['actual_rulebook_loaded', 'actual_strategy_recompiled',
                    'required_skill_bytes_loaded', 'current_contract_enforced'],
                'required_after_render': ['source_pixel_review', 'real_scene_mapping',
                    'final_pixel_review', 'actual_duration', 'native_audio_rights_and_sync']}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            failures.append(platform+':'+str(exc))
    return {'passed': not failures, 'failed_dimensions': failures,
        'version': 'content_policy_execution_v1', 'job_id': job.get('id'), 'platforms': records}


def background_requirement(topic, beat, scene):
    claim = ('主题实景主背景：'+str(topic)+'；此段口播：'+str(beat)+
        '。必须为可辨认的真实摄影场景或摄影写实生图，应能清楚辨认与本段主题、口播相符的实际主体、环境或实物关系；'
        '禁止纯色、渐变、抽象图形、图表卡片、无关风景充当主背景。图像不证明真实客户或实际执行结果。')
    intent = {'beat_id': str(scene['beat_id']), 'claim': claim, 'semantic_subject': claim,
        'asset_role': 'illustration', 'content_match_reason': 'primary photographic scene behind accurate evidence',
        'visual_mode': scene['visual_mode'], 'template_id': scene['template_id'], 'group_motion': scene['group_motion']}
    return {'intent': intent, 'sha256': digest(intent)}


def final_requirement(topic, beat, scene):
    value = background_requirement(topic, beat, scene)
    intent = dict(value['intent'])
    intent['claim'] += (' 最终交付像素必须仍能清楚辨认与本段主题、口播相符的摄影场景主体与环境，不得由遮罩或大面板退化成纯色；'
        '与本段来源相符且复核过的事实或关系作为信息前景，字形完整、文字无重叠，静音可独立读懂此段。')
    intent['semantic_subject'] = intent['claim']
    return {'intent': intent, 'sha256': digest(intent)}


def _admit_review(path, topic, requirement, review):
    from .video_asset_semantics import admit_review
    # This native function rereads source image/query/result hashes and the
    # actual Hermes session (one image request, zero tools) instead of flags.
    return admit_review(path, topic, requirement, review)


def _probe(path):
    import subprocess
    proc = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
        '-show_format', '-of', 'json', str(path)], capture_output=True, text=True, timeout=60)
    if proc.returncode:
        raise ValueError('policy_actual_video_probe_failed')
    return json.loads(proc.stdout)


def validate_visual_policy_release(packet, platform, *, video_path=None, render_manifest=None):
    from .run_contract import validate_run_contract
    failures = []; gates = {}
    try:
        contract = packet.get('run_contract') or (packet.get('preflight_manifest') or {}).get('run_contract') or {}
        checked = validate_run_contract(contract)
        if not checked.get('passed') or not contract.get('visual_quality_standards'):
            raise ValueError('current_visual_policy_contract_required')
        manifest = render_manifest or packet.get('render_manifest') or {}
        evidence = packet.get('visual_policy_evidence') or manifest.get('visual_policy_evidence') or {}
        if evidence.get('version') != 'native_visual_policy_evidence_v1':
            raise ValueError('actual_visual_policy_evidence_required')
        if evidence.get('run_contract_sha256') != digest(contract):
            raise ValueError('visual_policy_contract_binding_changed')
        topic = str(packet.get('topic') or evidence.get('topic') or '')
        if not topic or topic != evidence.get('topic'):
            raise ValueError('visual_policy_topic_binding_changed')
        backgrounds = evidence.get('backgrounds') or []
        scenes = evidence.get('scenes') or []
        if not scenes or len(backgrounds) != len(scenes):
            raise ValueError('real_scene_every_beat_required')
        seen = set()
        for scene, row in zip(scenes, backgrounds):
            identity = scene['beat_id']
            if row.get('beat_id') != identity:
                raise ValueError('background_cross_beat_binding')
            source = file_record(row['path'], row['sha256'])
            if source['sha256'] in seen:
                raise ValueError('repeated_primary_background')
            seen.add(source['sha256'])
            if (row.get('source_kind') not in {'licensed_real_scene_photo', 'generated_photographic_scene'}
                    or not row.get('source_url') or not row.get('license') or not row.get('generation_or_license_evidence')):
                raise ValueError('real_scene_source_provenance_required')
            provenance = row['generation_or_license_evidence']
            file_record(provenance['path'], provenance['sha256'])
            required = background_requirement(topic, scene['narration'], scene)
            if row.get('semantic_requirement') != required:
                raise ValueError('photographic_scene_requirement_changed')
            _admit_review(source['path'], topic, required, row.get('semantic_review') or {})
        cover = evidence.get('cover') or {}
        cover_source = file_record(cover['background_path'], cover['background_sha256'])
        if cover_source['sha256'] in seen:
            raise ValueError('cover_primary_background_reused')
        cover_requirement = background_requirement(topic, scenes[0]['narration'], scenes[0])
        if cover.get('semantic_requirement') != cover_requirement:
            raise ValueError('cover_photographic_requirement_changed')
        file_record(cover['generation_or_license_evidence']['path'], cover['generation_or_license_evidence']['sha256'])
        _admit_review(cover_source['path'], topic, cover_requirement, cover.get('semantic_review') or {})
        output = file_record(video_path or manifest.get('output'), evidence.get('video_sha256')) if video_path else None
        if output:
            from .video_artifact import validate_duration_policy
            probe = _probe(output['path'])
            duration = max([float(probe['format']['duration'])] +
                [float(s.get('duration') or 0) for s in probe.get('streams') or []])
            gate = validate_duration_policy(platform, duration, manifest)
            if not gate.get('passed'):
                raise ValueError('actual_short_duration_exceeded')
            gates['actual_duration'] = {'passed': True, 'duration_seconds': duration, 'video_sha256': output['sha256']}
        # Final reviews are of captures reread from the exact movie/cover.
        captures = evidence.get('final_pixel_reviews') or []
        required_ids = {s['beat_id'] for s in scenes} | {'cover', 'first_frame'}
        if {r.get('beat_id') for r in captures} != required_ids:
            raise ValueError('final_all_beats_cover_first_frame_required')
        from PIL import Image, ImageChops
        import subprocess, io
        by_id = {s['beat_id']: s for s in scenes}
        for row in captures:
            capture = file_record(row['path'], row['sha256'])
            identity = row['beat_id']
            scene = by_id.get(identity) or scenes[0]
            required = final_requirement(topic, scene['narration'], scene)
            if row.get('semantic_requirement') != required:
                raise ValueError('final_background_visibility_requirement_changed')
            if identity == 'cover':
                final_cover = file_record(cover['path'], cover['sha256'])
                if capture['sha256'] != final_cover['sha256']:
                    raise ValueError('final_cover_pixels_changed')
            elif output:
                frame = row.get('frame_index')
                if type(frame) is not int or frame < 0 or (identity == 'first_frame' and frame != 0):
                    raise ValueError('final_frame_index_invalid')
                proc = subprocess.run(['ffmpeg', '-v', 'error', '-i', output['path'], '-vf',
                    'select=eq(n\\,'+str(frame)+')', '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'],
                    capture_output=True, timeout=60)
                if proc.returncode:
                    raise ValueError('actual_final_frame_decode_failed')
                actual = Image.open(io.BytesIO(proc.stdout)).convert('RGB')
                with Image.open(capture['path']) as saved:
                    if actual.size != saved.size or ImageChops.difference(actual, saved.convert('RGB')).getbbox():
                        raise ValueError('final_review_capture_not_actual_movie_frame')
            _admit_review(capture['path'], topic, required, row.get('semantic_review') or {})
        gates['native_source_and_final_pixel_reviews'] = {'passed': True, 'source_count':len(backgrounds)+1,
            'final_capture_count': len(captures)}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        failures.append(str(exc))
    return {'passed': not failures, 'gates': gates, 'failed_dimensions': failures}
