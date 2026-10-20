"""Explicit media-only revisions of failed work, using verified inherited inputs.

The parent and its failed steps remain immutable. A revision is an ordinary
Store job whose input lineage is visible; only the uncompleted media work runs.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_record(path, expected=None):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():
        raise ValueError('media_revision_input_not_regular')
    raw = path.read_bytes(); actual = hashlib.sha256(raw).hexdigest()
    if expected and actual != expected:
        raise ValueError('media_revision_input_changed:' + path.name)
    return raw, actual


def private_manifest(path, expected):
    raw, actual = file_record(path, expected)
    info = Path(path).stat()
    if getattr(os, 'geteuid', lambda: -1)() != 0 or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError('root_private_media_revision_required')
    value = json.loads(raw)
    if (value.get('version') != 'media_revision_inputs_v1' or value.get('no_publish_no_approval') is not True
            or not value.get('intent') or value.get('budget_seconds') != 1800):
        raise ValueError('media_revision_contract_invalid')
    return value


def verify_parent(store, manifest):
    parent = store.get_job(manifest['parent_job_id'])
    steps = store.workflow_steps(parent['id'])
    if (parent['state'] != 'failed' or parent.get('lease_owner') or digest(parent) != manifest['parent_job_sha256']
            or digest(steps) != manifest['parent_workflow_sha256'] or parent['platforms'] != ['kuaishou']):
        raise ValueError('media_revision_parent_changed')
    assets = json.loads(file_record(manifest['qualified_assets']['path'], manifest['qualified_assets']['sha256'])[0])
    audio = json.loads(file_record(manifest['prepared_audio']['path'], manifest['prepared_audio']['sha256'])[0])
    if assets.get('passed') is not True or len(assets.get('assignments', [])) != 8 or len(audio.get('records', [])) != 8:
        raise ValueError('media_revision_complete_inputs_required')
    if audio.get('provider') != 'kokoro-onnx' or audio.get('voice') != 'zf_001':
        raise ValueError('media_revision_audio_provider_changed')
    for row in assets['assignments']:
        file_record(row['source_image'], row['sha256'])
        from .asset_semantic_review import parse_response, validate, verify_session
        from .video_asset_semantics import review_context
        from .asset_ledger import MIN_SEMANTIC_SCORE
        review=row['semantic_review'];context=review_context(parent['topic'],row['semantic_requirement'])
        if (review.get('status')!='evaluated' or review.get('score',0)<MIN_SEMANTIC_SCORE
                or review.get('image_sha256')!=row['sha256'] or review.get('context_sha256')!=digest(context)):
            raise ValueError('media_revision_parent_review_not_qualified')
        query=file_record(review['query']['path'],review['query']['sha256'])[0].decode()
        output=file_record(review['stdout']['path'],review['stdout']['sha256'])[0].decode()
        if json.loads(query.split('UNTRUSTED_DATA:\n',1)[1])!=context:
            raise ValueError('media_revision_parent_review_context_changed')
        actual,session=parse_response(output,review['route']['model'])
        actual=validate(actual,requirement=True)
        if any(review.get(key)!=value for key,value in actual.items()) or actual.get('requirement_match') is not True:
            raise ValueError('media_revision_parent_review_response_changed')
        if verify_session(session,review['route'],manifest['quality_session_database'])!=review['execution']:
            raise ValueError('media_revision_parent_review_session_changed')
    for row in audio['records']:
        file_record(row['path'], row['audio_sha256'])
        if hashlib.sha256(row['source_text'].encode()).hexdigest() != row['source_text_sha256']:
            raise ValueError('media_revision_audio_text_changed')
    script = '\n\n'.join(row['source_text'] for row in audio['records'])
    if hashlib.sha256(script.encode()).hexdigest() != assets['script_sha256'] or assets['script_sha256'] != manifest['script_sha256']:
        raise ValueError('media_revision_narration_changed')
    for row in manifest['evidence_files']:
        file_record(row['path'], row['sha256'])
    return parent, steps, assets, audio


def create_revision(pipeline, parent_id, manifest_path, manifest_sha256):
    manifest = private_manifest(manifest_path, manifest_sha256)
    if manifest['parent_job_id'] != parent_id:
        raise ValueError('media_revision_parent_id_mismatch')
    parent, _, _, _ = verify_parent(pipeline.store, manifest)
    # Single business intent, even if the create response was lost.
    with pipeline.store.connect() as conn:
        rows = conn.execute("SELECT id,brief_json FROM jobs WHERE json_extract(brief_json,'$.media_revision.manifest_sha256')=?", (manifest_sha256,)).fetchall()
    if rows:
        if len(rows) != 1:
            raise ValueError('media_revision_intent_ambiguous')
        return pipeline.store.get_job(rows[0]['id'])
    reference = {'parent_job_id': parent_id, 'manifest_path': str(Path(manifest_path).resolve()),
                 'manifest_sha256': manifest_sha256, 'intent': manifest['intent']}
    brief = copy.deepcopy(parent['brief']); brief['media_revision'] = reference
    job = pipeline.store.create_job(parent['topic'], parent['platforms'], brief, parent['profile'], parent['topic_fingerprint'])
    pipeline.store.record_event(job['id'], 'media_revision_created', reference)
    pipeline.store.record_event(parent_id, 'media_revision_child_created', {'job_id': job['id'], **reference})
    return job


class RebindInputs:
    def __init__(self, store, parent, child, authority):
        self.store, self.parent, self.child, self.authority = store, parent, child, authority
        self.old_root = Path(store.get_job(parent)['brief']['original_knowledge_ref']['path']).parent.parent
        self.new_root = store.path.parent / 'jobs' / child
        self.references = {}; self.hashes = {}; self.pending = set(); self.events = []

    def walk(self, value):
        if isinstance(value, list):
            return [self.walk(x) for x in value]
        if isinstance(value, str):
            return self.child if value == self.parent else self.hashes.get(value, value)
        if not isinstance(value, dict):
            return value
        if value.get('job_id') == self.parent and value.get('path') and value.get('sha256'):
            path = Path(value['path'])
            if path.is_relative_to(self.old_root):
                return self.reference(value)
        result = {key: self.walk(item) for key, item in value.items()}
        # Exact secondary evidence pointers used by original factual claims.
        if value.get('evidence_path') in self.references:
            ref = self.references[value['evidence_path']]
            result['evidence_path'] = ref['path']
            for key in ('evidence_sha256', 'sha256'):
                if value.get(key) in self.hashes:
                    result[key] = self.hashes[value[key]]
        return result

    def reference(self, ref):
        old = ref['path']
        if old in self.references:
            return copy.deepcopy(self.references[old])
        if old in self.pending:
            raise ValueError('media_revision_input_cycle')
        self.pending.add(old)
        raw, old_sha = file_record(old, ref['sha256'])
        payload = json.loads(raw)
        if payload.get('job_id') != self.parent:
            raise ValueError('media_revision_source_owner_mismatch')
        original_fact = payload.get('content_mode') == 'original_knowledge' and 'authority' in payload and 'documents' in payload
        payload = self.walk(payload)
        if original_fact:
            payload['authority'] = self.authority
            payload['inherited_from'] = {'job_id': self.parent, 'path': old, 'sha256': old_sha}
        target = self.new_root / Path(old).relative_to(self.old_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        with target.open('xb') as stream:
            os.chmod(target, 0o600); stream.write(data)
        new = dict(ref, job_id=self.child, path=str(target), sha256=hashlib.sha256(data).hexdigest())
        if 'store_path' in new:new['store_path']=str(self.store.path.resolve())
        if original_fact:
            new['producer'] = 'native.media_revision'
        self.references[old] = new; self.hashes[old_sha] = new['sha256']; self.pending.remove(old)
        event = 'native_original_knowledge_inputs_bound' if original_fact else 'native_video_research_snapshot_bound'
        self.store.record_event(self.child, event, new)
        self.events.append({'parent_path': old, 'parent_sha256': old_sha, 'ref': new})
        return copy.deepcopy(new)


def prepared_inputs(store, job):
    reference = job.get('brief', {}).get('media_revision')
    if not reference:
        return None
    manifest = private_manifest(reference['manifest_path'], reference['manifest_sha256'])
    verify_parent(store, manifest)
    path = store.path.parent / 'artifacts' / job['id'] / 'media_revision_inputs.json'
    raw, checksum = file_record(path)
    events = [json.loads(row['detail_json']) for row in store.events(job['id']) if row['event'] == 'media_revision_artifacts_bound']
    if {'path': str(path), 'sha256': checksum, 'manifest_sha256': reference['manifest_sha256']} not in events:
        raise ValueError('media_revision_assets_not_bound')
    return json.loads(raw)


def inherited_review_database(path, review):
    from .store import Store
    inheritance=review['inherited_review'];database=Path(inheritance['store_path'])
    if not database.is_absolute() or database.is_symlink() or not database.is_file():raise ValueError('media_revision_store_untrusted')
    store=Store(database);job=store.get_job(inheritance['job_id']);reference=job['brief']['media_revision']
    if inheritance['manifest_sha256']!=reference['manifest_sha256']:raise ValueError('media_revision_review_manifest_changed')
    manifest=private_manifest(reference['manifest_path'],reference['manifest_sha256'])
    parent,steps,assets,audio=verify_parent(store,manifest)
    original=next(row['semantic_review'] for row in assets['assignments'] if row['sha256']==inheritance['image_sha256'])
    current={key:value for key,value in review.items() if key not in {'query','stdout','inherited_review'}}
    expected={key:value for key,value in original.items() if key not in {'query','stdout'}}
    if current!=expected or file_record(path)[1]!=inheritance['image_sha256']:raise ValueError('media_revision_review_changed')
    for field in ('query','stdout'):
        if review[field]['sha256']!=original[field]['sha256']:raise ValueError('media_revision_review_capture_changed')
    source=Path(manifest['quality_session_database'])
    if source.is_symlink() or any(p.is_symlink() for p in source.parents) or not source.is_file():raise ValueError('media_revision_review_database_untrusted')
    return source


def run_revision(pipeline, job_id, owner, workflow_id, runner):
    from .stage_input_refs import resolve_stage_payload, bind_stage_payload
    from .task_source_inputs import persist_task_source_inputs
    store = pipeline.store; job = store.get_job(job_id); reference = job['brief']['media_revision']
    manifest = private_manifest(reference['manifest_path'], reference['manifest_sha256'])
    parent, steps, assets, audio = verify_parent(store, manifest)
    started = time.time(); deadline = started + manifest['budget_seconds']
    store.record_event(job_id, 'media_revision_execution_started', {'parent_job_id': parent['id'], 'deadline_unix': deadline, 'manifest_sha256': reference['manifest_sha256']})
    token = pipeline.review_tokens.issue(job_id, 'original_knowledge', ttl=1800, continuation_sha256=reference['manifest_sha256'])
    seal = pipeline.review_tokens.verify(token, 'original_knowledge')
    authority = {'actor_uid': 0, 'action': 'original_knowledge', 'nonce': seal['nonce'], 'expires_at': seal['exp'],
                 'token_sha256': hashlib.sha256(token.encode()).hexdigest(), 'execution_budget_seconds': 1800, 'source_budget_seconds': 0}
    clone = RebindInputs(store, parent['id'], job_id, authority)
    clone.reference(parent['brief']['original_knowledge_ref'])
    full = resolve_stage_payload(store, parent['id'], parent['brief']['run_contract'], 'generate', parent['brief']['bounded_model_input'])
    full = clone.walk(full); brief = clone.walk(parent['brief']); brief['media_revision'] = reference
    brief.pop('_final_bounded_model_input', None)
    brief['source_collection_audit'] = dict(brief['source_collection_audit'], producer='native.media_revision',
        inherited_from_job_id=parent['id'], inherited_source_sha256=digest(parent['brief']['source_collection_audit']))
    full['content_blueprint']['video_asset_requirements'] = assets['requirements']
    brief['content_blueprint'] = full['content_blueprint']
    for platform in brief.get('platform_workflow_inputs', {}):
        brief['platform_workflow_inputs'][platform].update(original_knowledge_ref=brief['original_knowledge_ref'],
            content_blueprint=copy.deepcopy(full['content_blueprint']), source_collection_audit=brief['source_collection_audit'])
    brief['bounded_model_input'] = full
    job = persist_task_source_inputs(store, job, owner, brief)
    bounded = bind_stage_payload(store, job_id, brief['run_contract'], 'generate', full, lease_owner=owner, force_reference=True)
    brief['bounded_model_input'] = bounded
    for platform in brief.get('platform_workflow_inputs', {}):
        brief['platform_workflow_inputs'][platform]['bounded_model_input'] = bounded
    job = persist_task_source_inputs(store, job, owner, brief)
    inherited = {}
    names = ('collect_native_source_inputs', 'run_content_hygiene', 'validate_factual_claims', 'run_safety_gate', 'run_quality_gate', 'original_copy_dedup', 'run_fact_check')
    for name in names:
        row = next(x for x in steps if x['step_name'] == name and x['status'] == 'SUCCEEDED')
        value = clone.walk(row['output']); inherited[name] = value
        runner.succeeded(name, value, message='复用已验证父任务输入；未再次执行：' + parent['id'])
    generated_row = next(x for x in steps if x['step_name'] == manifest['generation_step'] and x['status'] == 'SUCCEEDED')
    draft = clone.walk(generated_row['output'])
    native_draft=json.loads(file_record(manifest['draft_return']['path'],manifest['draft_return']['sha256'])[0])
    body_record=draft.get('body')
    if (native_draft.get('title')!=draft.get('title') or not isinstance(native_draft.get('body'),str)
            or not isinstance(body_record,dict) or body_record.get('chars',0)<len(native_draft['body'])
            or ''.join(native_draft['body'].split()) not in ''.join(body_record.get('excerpt','').split())):
        raise ValueError('media_revision_native_draft_changed')
    draft['body']=native_draft['body']
    planning = full['content_blueprint']['video_source_planning']
    meta = draft['draft_meta']
    for field in ('video_script', 'narration_script', 'video_planning_audit'):
        meta[field] = planning[field]
    plan = meta['video_toolchain_plan']; plan.update(content_mode='original_knowledge', original_knowledge_ref=brief['original_knowledge_ref'],
        visual_contract=copy.deepcopy(assets['scenes']), video_asset_requirements=copy.deepcopy(assets['requirements']))
    from .video_asset_semantics import requirement_tag
    for scene, requirement in zip(plan['visual_contract'], assets['requirements']):
        scene.update(semantic_requirement=requirement, required_semantic_tag=requirement_tag(requirement))
    runner.succeeded('generate_content', draft, message='继承父任务已审稿件；正文模型调用0；父失败步骤保留')
    for event in store.events(parent['id']):
        if event['event'] == 'native_platform_narrations_validated':
            store.record_event(job_id, event['event'], clone.walk(json.loads(event['detail_json'])))
    root = pipeline.data_dir / 'artifacts' / job_id; root.mkdir(parents=True, exist_ok=True)
    assignments = []
    for index, row in enumerate(assets['assignments'], 1):
        row = copy.deepcopy(row); source = Path(row['source_image']); target = root / ('scene-%02d' % index + source.suffix)
        shutil.copy2(source, target); row.update(source_image=str(target), background_image=str(target), path=str(target), reused_from_parent_job=parent['id'])
        review=copy.deepcopy(row['semantic_review'])
        for field in ('query','stdout'):
            record=review[field];capture=Path(record['path']);captured=root/capture.name
            file_record(capture,record['sha256'])
            if captured.exists():file_record(captured,record['sha256'])
            else:shutil.copy2(capture,captured)
            record['path']=str(captured)
        review['inherited_review']={'job_id':job_id,'manifest_sha256':reference['manifest_sha256'],'image_sha256':row['sha256'],'store_path':str(store.path.resolve())}
        row['semantic_review']=review
        assignments.append(row); store.add_artifact(job_id, 'image', str(target), row['sha256'])
    for index, row in enumerate(audio['records'], 1):
        source = Path(row['path']); target = root / ('audio-%02d' % index + source.suffix)
        shutil.copy2(source, target); row['path'] = str(target)
    prepared_audio = root / 'prepared_audio_manifest.json'; prepared_audio.write_text(json.dumps(audio, ensure_ascii=False), encoding='utf8')
    bound = {'assignments': assignments, 'audio_manifest': str(prepared_audio), 'audio_manifest_sha256': hashlib.sha256(prepared_audio.read_bytes()).hexdigest()}
    file = root / 'media_revision_inputs.json'; file.write_text(json.dumps(bound, ensure_ascii=False), encoding='utf8')
    store.record_event(job_id, 'media_revision_artifacts_bound', {'path': str(file), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'manifest_sha256': reference['manifest_sha256']})
    store.record_event(job_id, 'media_revision_inputs_inherited', {'parent_job_id': parent['id'], 'sources': clone.events,
        'image_generation_calls': 0, 'tts_calls': 0, 'text_model_calls': 0, 'source_fetch_calls': 0})
    images = {'kind': 'image', 'images': [{'kind': 'image', 'path': x['source_image'], 'checksum': x['sha256']} for x in assignments]}
    runner.succeeded('generate_or_collect_images', images, message='逐文件校验并复用8张已审图片')
    runner.succeeded('validate_image_requirements', {'passed': True, 'asset_count': 8, 'qualified_assets_sha256': manifest['qualified_assets']['sha256']})
    import subprocess
    concat=root/'audio-concat.txt';concat.write_text(''.join("file '"+row['path'].replace("'", "'\\''")+"'\n" for row in audio['records']),encoding='utf8')
    narration=root/'narration.mp3'
    subprocess.run(['ffmpeg','-v','error','-n','-f','concat','-safe','0','-i',str(concat),'-c:a','libmp3lame','-b:a','128k',str(narration)],capture_output=True,check=True,timeout=60)
    audio_artifact={'kind':'audio','path':str(narration),'checksum':hashlib.sha256(narration.read_bytes()).hexdigest(),
        'provider':'kokoro-onnx','prepared_audio_manifest':str(prepared_audio),'duration':audio['duration_seconds'],
        'reused_verified_segments':8,'synthesis_calls':0}
    store.add_artifact(job_id,'audio',str(narration),audio_artifact['checksum'])
    runner.succeeded('generate_audio',audio_artifact,message='合并八段已核音轨；未重复语音推理')
    risk = inherited['run_safety_gate']; geo = inherited['run_fact_check']
    meta['geo_score']=geo['score'];meta['geo_details']=geo;store.save_geo_score(job_id,geo)
    store.save_draft(job_id, draft['title'], draft['body'], risk['level'], risk, draft.get('prompt_version', ''), meta)
    return _finish_revision(pipeline, job_id, owner, runner, draft, images, audio_artifact, risk, geo, parent, reference, deadline)


def _finish_revision(pipeline, job_id, owner, runner, draft, images, audio_artifact, risk, geo, parent, reference, deadline, attempt_id=None):
    store = pipeline.store; meta = draft['draft_meta']
    from .original_knowledge import read_original_inputs
    original_ref = store.get_job(job_id)['brief']['original_knowledge_ref']
    original = read_original_inputs(store, job_id, original_ref)
    script = '\n\n'.join(original['beats'])
    if script != meta['narration_script'] or hashlib.sha256(script.encode()).hexdigest() != private_manifest(reference['manifest_path'], reference['manifest_sha256'])['script_sha256']:
        raise ValueError('media_revision_script_profile_exact_narration_required')
    scope = store.path.parent / 'jobs' / job_id / 'video-preflight' / ('original-profile-' + (attempt_id or 'initial') + '.json')
    raw = json.dumps(original_ref, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if scope.exists():
        if file_record(scope)[0] != raw: raise ValueError('media_revision_script_profile_scope_changed')
    else:
        with scope.open('xb') as stream:
            os.chmod(scope, 0o600); stream.write(raw)
    store.record_event(job_id, 'media_revision_script_profile_bound', {'path': str(scope),
        'sha256': hashlib.sha256(raw).hexdigest(), 'original_knowledge_ref': original_ref,
        'script_sha256': hashlib.sha256(script.encode()).hexdigest(), 'lease_owner': owner})
    previous_scope = os.environ.get('MEDIA_QUALIFIED_VISION_SCOPE_PATH')
    os.environ['MEDIA_QUALIFIED_VISION_SCOPE_PATH'] = str(scope)
    try:
        rendered = pipeline._generate_video_per_platform(job_id, runner, ['validate_image_requirements'], draft=draft, owner=owner, attempt_id=attempt_id)
    finally:
        if previous_scope is None: os.environ.pop('MEDIA_QUALIFIED_VISION_SCOPE_PATH', None)
        else: os.environ['MEDIA_QUALIFIED_VISION_SCOPE_PATH'] = previous_scope
    if attempt_id is not None:
        for platform, artifact in rendered:
            artifact['producer_step'] = runner.alias
    videos = dict(rendered)
    for platform, artifact in rendered:
        scoped = {'draft_meta': {}}; pipeline._attach_video_render_evidence(scoped, artifact)
        meta.setdefault('platform_render_evidence', {})[platform] = scoped['draft_meta']; meta.update(scoped['draft_meta'])
    cover = Path(videos['kuaishou']['path']).parent / 'cover.png'
    _, checksum = file_record(cover); store.add_artifact(job_id, 'cover', str(cover), checksum)
    cover_row = {'kind': 'cover', 'role': 'cover', 'path': str(cover), 'checksum': checksum}
    images['images'].append(cover_row); runner.succeeded('generate_cover', cover_row)
    # Publishable normal platform records require the existing full rendered gate.
    gate = pipeline._quality_gate(job_id, draft, risk, geo, phase='rendered'); meta['quality_gate'] = gate
    if not gate.get('passed'):
        runner.block('run_final_platform_quality_gate', 'final_platform_quality_gate_failed', '修订成片未通过正常平台质量门', gate)
    runner.succeeded('run_final_platform_quality_gate', gate)
    store.save_draft(job_id, draft['title'], draft['body'], risk['level'], risk, draft.get('prompt_version', ''), meta)
    pipeline._record_platform_outputs(job_id, gate, images, videos, [('audio',audio_artifact)])
    if not store.platform_outputs(job_id):
        raise ValueError('media_revision_normal_platform_outputs_missing')
    if time.time() > deadline:
        raise TimeoutError('media_revision_deadline_exceeded')
    reviewed = store.release_claim(job_id, owner, 'review_required', 'media_revision_review_requested',
        detail={'parent_job_id': parent['id'], 'manifest_sha256': reference['manifest_sha256'], 'external_publish': False})
    pipeline.notifier.send('review_required', reviewed)
    return pipeline._hydrate(reviewed)


def trusted_recipe_registry(expected=None):
    path = Path('/srv/hermes-runtime/data/visual_recipe_fingerprints.json')
    raw, checksum = file_record(path, expected)
    registry = json.loads(raw)
    evidence = registry.get('trust_evidence') or {}
    if (registry.get('trusted') is not True or int(registry.get('coverage_days', 0)) < 7
            or not isinstance(registry.get('recipes'), list) or len(registry['recipes']) < 149
            or (evidence.get('owner') or {}).get('canonical_registry_path') != str(path)
            or evidence.get('audited_entry_count') != 149):
        raise ValueError('trusted_shared_seven_day_registry_required')
    file_record(evidence['path'], evidence['sha256'])
    return {'path': str(path), 'sha256': checksum, 'entry_count': len(registry['recipes']),
            'recipes_sha256': digest(registry['recipes'])}


def resume_evidence(path, expected):
    import re
    raw, checksum = file_record(path, expected)
    info = Path(path).stat()
    if getattr(os, 'geteuid', lambda: -1)() != 0 or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError('root_private_media_resume_required')
    value = json.loads(raw)
    index = value.get('recovery_index', 1)
    first = index == 1 and value.get('failed_step_name') == 'generate_video[kuaishou]' and value.get('failure_code') == 'trusted_seven_day_registry_missing'
    second = (index == 2 and value.get('job_id') == '940c5334ccb445a0'
              and value.get('origin_run_id') == 'd874153b8d644b1cb4baa660c2e9b31a'
              and value.get('previous_evidence_sha256') == '3e516525fd90842b500b808ea978d5e275340c5704b5948668713a806b38657a'
              and value.get('failed_step_name') == 'generate_video[kuaishou]__resume_bdda6d8074d540db9517480f22ef5f50'
              and value.get('failure_code') == '脚本质量门禁: FAIL')
    third = (index == 3 and value.get('job_id') == '940c5334ccb445a0'
             and value.get('origin_run_id') == '362f93e7bbe3493ba96b191293ae5eb9'
             and value.get('previous_evidence_sha256') == 'a68b16af731e4268c0e962b15fb93ed8ec58397d67b29b46d9811bc2664a0e39'
             and value.get('failed_step_name') == 'generate_video[kuaishou]__resume_d874153b8d644b1cb4baa660c2e9b31a'
             and value.get('failure_code') == 'computed_evidence_unavailable:TargetClosedError'
             and value.get('final_video_file_count') == 0 and value.get('all_video_file_count') == 0)
    if (value.get('version') != 'media_revision_resume_v1' or value.get('no_publish_no_approval') is not True
            or value.get('budget_seconds') != 1800 or value.get('zero_video_confirmed') is not True
            or not re.fullmatch('[a-f0-9]{16}', str(value.get('job_id', '')))
            or not re.fullmatch('[a-f0-9]{32}', str(value.get('origin_run_id', '')))
            or not re.fullmatch('[a-f0-9]{32}', str(value.get('create_control_job_id', '')))
            or not re.fullmatch('[a-f0-9]{64}', str(value.get('input_manifest_sha256', '')))
            or not (first or second or third)
            or len(value.get('original_steps') or []) != 13 + index
            or len(value.get('original_events') or []) < 20 or len(value.get('input_files') or []) < 65):
        raise ValueError('exact_unencoded_media_resume_evidence_required')
    return value


def verify_resume_originals(store, evidence):
    steps = {row['id']: row for row in store.workflow_steps(evidence['job_id'])}
    events = {row['id']: row for row in store.events(evidence['job_id'])}
    for row in evidence['original_steps']:
        if steps.get(row['id']) != row:
            raise ValueError('media_resume_original_step_changed')
    for row in evidence['original_events']:
        if events.get(row['id']) != row:
            raise ValueError('media_resume_original_event_changed')
    for row in evidence['origin_files'] + evidence['input_files']:
        file_record(row['path'], row['sha256'])


def validate_resume_inputs(store, path, expected):
    evidence = resume_evidence(path, expected)
    job = store.get_job(evidence['job_id'])
    reference = job.get('brief', {}).get('media_revision') or {}
    index = evidence.get('recovery_index', 1)
    if (job['state'] != 'failed' or job.get('lease_owner') or job.get('attempts') != index
            or digest(job) != evidence['job_sha256'] or job['platforms'] != ['kuaishou']
            or reference.get('manifest_sha256') != evidence['input_manifest_sha256']
            or job['brief'].get('original_knowledge_ref') != evidence['original_knowledge_ref']):
        raise ValueError('media_resume_same_failed_entity_changed')
    verify_resume_originals(store, evidence)
    failed = [row for row in evidence['original_steps'] if row['status'] != 'SUCCEEDED']
    if (len(failed) != index or any(row['status'] != 'FAILED_FINAL' for row in failed)
            or failed[-1]['step_name'] != evidence['failed_step_name']
            or evidence['failure_code'] not in failed[-1]['message']
            or failed[0]['step_name'] != 'generate_video[kuaishou]'
            or 'trusted_seven_day_registry_missing' not in failed[0]['message']):
        raise ValueError('media_resume_unencoded_failure_required')
    origin = json.loads(file_record(evidence['origin_files'][0]['path'], evidence['origin_files'][0]['sha256'])[0])
    if (origin.get('control_id') != evidence['origin_run_id'] or origin.get('media_id') != job['id']
            or origin.get('create_control_job_id') != evidence['create_control_job_id']
            or origin.get('phase') != 'finished' or origin.get('result', {}).get('reason') != 'media_failed'):
        raise ValueError('media_resume_origin_control_failed_required')
    if any(row.get('kind') == 'video' for row in store.artifacts(job['id'])) or store.platform_outputs(job['id']):
        raise ValueError('media_resume_completed_video_forbidden')
    if index == 3 and any((store.path.parent / 'artifacts' / job['id']).rglob('*.mp4')):
        raise ValueError('media_resume_unregistered_video_forbidden')
    starts = [json.loads(row['detail_json']) for row in store.events(job['id']) if row['event'] == 'media_revision_resume_started']
    if (len(starts) != index - 1 or (index >= 2 and (starts[0]['origin_run_id'] != 'bdda6d8074d540db9517480f22ef5f50'
            or starts[0]['evidence_sha256'] != '3e516525fd90842b500b808ea978d5e275340c5704b5948668713a806b38657a'))
            or (index == 3 and (starts[1]['origin_run_id'] != 'd874153b8d644b1cb4baa660c2e9b31a'
            or starts[1]['evidence_sha256'] != evidence['previous_evidence_sha256']))):
        raise ValueError('media_resume_already_started_no_replay')
    trusted_recipe_registry(evidence['registry']['sha256'])
    manifest = private_manifest(reference['manifest_path'], reference['manifest_sha256'])
    verify_parent(store, manifest)
    prepared_inputs(store, job)
    return evidence


def resume_original_authority(store, job_id, ref, authority):
    from .review import ReviewTokens
    events = [json.loads(row['detail_json']) for row in store.events(job_id)
              if row['event'] == 'media_revision_authority_renewed']
    if not events:
        return authority
    if len(events) > 6:
        raise ValueError('media_resume_authority_ambiguous')
    current = store.get_job(job_id)
    active = [row for row in events if row['lease_owner'] == current.get('lease_owner')]
    if len(active) != 1: raise ValueError('media_resume_authority_same_active_lease_required')
    renewal = active[0]
    raw, _ = file_record(renewal['evidence_path'], renewal['evidence_sha256'])
    if json.loads(raw).get('version') == 'media_encoded_pixel_repair_v1':
        from .encoded_media_repair import encoded_evidence
        evidence = encoded_evidence(renewal['evidence_path'], renewal['evidence_sha256'])
    else:
        evidence = resume_evidence(renewal['evidence_path'], renewal['evidence_sha256'])
    if len(events) != evidence.get('recovery_index', 1): raise ValueError('media_resume_authority_chain_changed')
    if (evidence['job_id'] != job_id or evidence['original_knowledge_ref'] != ref
            or current['state'] != 'generating' or current.get('lease_owner') != renewal['lease_owner']
            or current.get('brief', {}).get('media_revision', {}).get('manifest_sha256') != evidence['input_manifest_sha256']):
        raise ValueError('media_resume_same_lease_authority_required')
    from datetime import datetime, timezone
    if datetime.fromisoformat(current['lease_expires_at']) <= datetime.now(timezone.utc):
        raise ValueError('media_resume_lease_expired')
    raw, _ = file_record(renewal['token_path'], renewal['token_sha256'])
    info = Path(renewal['token_path']).stat()
    if info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError('media_resume_token_not_private')
    seal = ReviewTokens(store.path.parent / 'review.key').verify(raw.decode(), 'original_knowledge')
    pin = digest({'manifest_sha256': evidence['input_manifest_sha256'], 'resume_evidence_sha256': renewal['evidence_sha256'],
                  'lease_owner': renewal['lease_owner']})
    if (seal.get('job_id') != job_id or seal.get('continuation_sha256') != pin
            or not 0 < seal['exp'] - time.time() <= 1800):
        raise ValueError('media_resume_authority_scope_changed')
    return {'actor_uid': 0, 'action': 'original_knowledge', 'nonce': seal['nonce'], 'expires_at': seal['exp'],
            'token_sha256': renewal['token_sha256'], 'execution_budget_seconds': 1800, 'source_budget_seconds': 0}


def validate_media_recovery_inputs(store, path, expected):
    raw,_=file_record(path,expected)
    if json.loads(raw).get('version')=='media_source_checkpoint_resume_v1':
        return validate_source_checkpoint_resume(store,path,expected)
    if json.loads(raw).get('version')=='media_encoded_pixel_repair_v1':
        from .encoded_media_repair import validate_encoded_inputs
        return validate_encoded_inputs(store,path,expected)
    return validate_resume_inputs(store,path,expected)


def resume_media_action(pipeline, job_id, path, expected):
    raw,_=file_record(path,expected)
    if json.loads(raw).get('version')=='media_source_checkpoint_resume_v1':
        return resume_source_checkpoint(pipeline,job_id,path,expected)
    if json.loads(raw).get('version')=='media_encoded_pixel_repair_v1':
        from .encoded_media_repair import finish_encoded_revision
        return finish_encoded_revision(pipeline,job_id,path,expected)
    return resume_revision(pipeline,job_id,path,expected)


def _finish_registered_encoded(pipeline, evidence, owner, runner, artifact):
    store=pipeline.store;job=store.get_job(evidence['job_id'])
    draft={key:copy.deepcopy(job[key]) for key in ('title','body','draft_meta','prompt_version')};meta=draft['draft_meta']
    steps={row['step_name']:row for row in evidence['original_steps']}
    risk=steps['run_safety_gate']['output'];geo=steps['run_fact_check']['output']
    images=copy.deepcopy(steps['generate_or_collect_images']['output']);audio=copy.deepcopy(steps['generate_audio']['output'])
    pipeline._attach_video_render_evidence(draft,artifact)
    meta['platform_render_evidence']={'kuaishou':copy.deepcopy(meta)}
    cover=Path(artifact['cover']);_,pin=file_record(cover)
    store.add_artifact(job['id'],'video',artifact['path'],artifact['checksum'])
    store.add_artifact(job['id'],'cover',str(cover),pin)
    cover_row={'kind':'cover','role':'cover','path':str(cover),'checksum':pin};images['images'].append(cover_row)
    runner.succeeded('generate_cover__encoded_pixel_repair',cover_row)
    gate=pipeline._quality_gate(job['id'],draft,risk,geo,phase='rendered')
    if not gate.get('passed'):runner.block('run_final_platform_quality_gate__encoded_pixel_repair','encoded_repair_final_quality_failed','同片修复未通过正常平台门',gate)
    runner.succeeded('run_final_platform_quality_gate__encoded_pixel_repair',gate)
    meta['quality_gate']=gate;store.save_draft(job['id'],draft['title'],draft['body'],risk['level'],risk,draft.get('prompt_version',''),meta)
    pipeline._record_platform_outputs(job['id'],gate,images,{'kuaishou':artifact},[('audio',audio)])
    if len(store.platform_outputs(job['id']))!=13:raise ValueError('encoded_repair_normal_13_outputs_required')
    from scripts.video_toolchain_runner import _register_visual_recipe_use
    plan=artifact['resolved_video_toolchain_plan'];recipe=json.loads((Path(artifact['path']).parent/'visual_recipe.json').read_bytes())
    _register_visual_recipe_use(recipe,plan,artifact['path'])
    reviewed=store.release_claim(job['id'],owner,'review_required','encoded_pixel_repair_review_requested',detail={
        'origin_run_id':evidence['origin_run_id'],'original_video_sha256':evidence['original_video']['sha256'],
        'new_video_sha256':artifact['checksum'],'external_publish':False})
    pipeline.notifier.send('review_required',reviewed);return pipeline._hydrate(reviewed)


def resume_revision(pipeline, job_id, evidence_path, evidence_sha256):
    from .workflow_runtime import WorkflowStepRunner, strict_workflow_lock, WorkflowBlocked
    if (os.environ.get('CONTENT_PLATFORM_NO_MODEL_CALLS') != '1'
            or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH') != '0'):
        raise PermissionError('media_resume_no_model_no_publish_required')
    store = pipeline.store; evidence = validate_resume_inputs(store, evidence_path, evidence_sha256)
    if evidence['job_id'] != job_id:
        raise ValueError('media_resume_job_identity_changed')
    owner = pipeline._worker_id(); workflow_id = 'wf_' + job_id
    alias = 'generate_video[kuaishou]__resume_' + evidence['origin_run_id']

    class ResumeRunner(WorkflowStepRunner):
        def _map(self, name):
            if name == 'generate_video[kuaishou]':
                return alias
            if name in {row['step_name'] for row in evidence['original_steps']}:
                raise PermissionError('media_resume_successful_prefix_cannot_replay')
            return name

        def run(self, name, func, **kwargs):
            return super().run(self._map(name), func, **kwargs)

        def succeeded(self, name, *args, **kwargs):
            return super().succeeded(self._map(name), *args, **kwargs)

        def block(self, name, *args, **kwargs):
            return super().block(self._map(name), *args, **kwargs)

        def skipped(self, name, *args, **kwargs):
            return super().skipped(self._map(name), *args, **kwargs)

    with strict_workflow_lock(store, owner, workflow_id, 1800, pipeline.strict_serial):
        validate_resume_inputs(store, evidence_path, evidence_sha256)
        if not store.claim(job_id, {'failed'}, owner, 1800, 'generating'):
            raise RuntimeError('media_resume_job_already_claimed')
        runner = ResumeRunner(store, workflow_id, job_id, notifier=pipeline.notifier); runner.alias = alias
        started = time.time()
        try:
            job = store.get_job(job_id); reference = job['brief']['media_revision']
            manifest = private_manifest(reference['manifest_path'], reference['manifest_sha256'])
            parent, _, _, _ = verify_parent(store, manifest)
            pin = digest({'manifest_sha256': evidence['input_manifest_sha256'], 'resume_evidence_sha256': evidence_sha256,
                          'lease_owner': owner})
            token = pipeline.review_tokens.issue(job_id, 'original_knowledge', ttl=1800, continuation_sha256=pin)
            token_path = Path(evidence_path).with_suffix('.token')
            with token_path.open('x', encoding='utf8') as stream:
                os.chmod(token_path, 0o600); stream.write(token)
            store.record_event(job_id, 'media_revision_resume_started', {'origin_run_id': evidence['origin_run_id'],
                'evidence_path': str(evidence_path), 'evidence_sha256': evidence_sha256, 'alias': alias,
                'deadline_unix': started + 1800, 'source_fetch_calls': 0, 'text_model_calls': 0,
                'image_generation_calls': 0, 'tts_calls': 0, 'external_publish': False})
            store.record_event(job_id, 'media_revision_authority_renewed', {'evidence_path': str(evidence_path),
                'evidence_sha256': evidence_sha256, 'lease_owner': owner, 'token_path': str(token_path),
                'token_sha256': hashlib.sha256(token.encode()).hexdigest(), 'original_knowledge_ref': evidence['original_knowledge_ref']})
            steps = {row['step_name']: row for row in evidence['original_steps']}
            draft = {key: copy.deepcopy(job[key]) for key in ('title', 'body', 'draft_meta', 'prompt_version')}
            risk = steps['run_safety_gate']['output']; geo = steps['run_fact_check']['output']
            images = copy.deepcopy(steps['generate_or_collect_images']['output'])
            audio_artifact = copy.deepcopy(steps['generate_audio']['output'])
            file_record(audio_artifact['path'], audio_artifact['checksum'])
            result = _finish_revision(pipeline, job_id, owner, runner, draft, images, audio_artifact, risk, geo, parent,
                                      reference, started + 1800, attempt_id='resume-' + evidence['origin_run_id'])
            verify_resume_originals(store, evidence)
            store.record_event(job_id, 'media_revision_resume_completed', {'origin_run_id': evidence['origin_run_id'],
                'evidence_sha256': evidence_sha256, 'alias': alias, 'original_failure_preserved': True,
                'final_state': store.get_job(job_id)['state'], 'external_publish': False})
            return result
        except Exception as exc:
            verify_resume_originals(store, evidence)
            current = store.get_job(job_id)
            if current.get('lease_owner') == owner:
                state = 'blocked' if isinstance(exc, WorkflowBlocked) else 'failed'
                store.release_claim(job_id, owner, state, 'media_revision_resume_failed', str(exc),
                                    detail={'origin_run_id': evidence['origin_run_id'], 'original_failure_preserved': True})
            raise


def source_checkpoint_evidence(path, expected):
    raw,_=file_record(path,expected);info=Path(path).stat();value=json.loads(raw)
    if (os.geteuid()!=0 or info.st_uid!=0 or info.st_mode&0o077
            or value.get('version')!='media_source_checkpoint_resume_v1'
            or value.get('budget_seconds')!=1800 or value.get('no_publish_no_approval')is not True):
        raise ValueError('root_source_checkpoint_resume_proof_required')
    for name,size in [('job_id',16),('origin_run_id',32),('create_control_job_id',32)]:
        import re
        if not re.fullmatch('[a-f0-9]{'+str(size)+'}',str(value.get(name,''))):
            raise ValueError('source_checkpoint_resume_identity_invalid')
    ref=value.get('source_checkpoint_ref')
    if not isinstance(ref,dict)or set(ref)!={'path','sha256'}:raise ValueError('source_checkpoint_reference_required')
    return value


def source_checkpoint_local_audio_inputs(proof):
    reference = proof.get('local_input_ref')
    if reference is None:
        return None
    import re
    if (not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}
            or not re.fullmatch('[a-f0-9]{64}', str(reference.get('sha256', '')))):
        raise ValueError('source_checkpoint_local_audio_reference_invalid')
    raw, _ = file_record(reference['path'], reference['sha256'])
    info = Path(reference['path']).stat()
    if (os.geteuid() != 0 or info.st_uid != 0 or info.st_mode & 0o077 or len(raw) > 65536):
        raise PermissionError('root_private_local_audio_inputs_required')
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {'version', 'audio_plan_resolver', 'sources', 'rights_source'}
            or value['version'] != 'media_local_audio_input_v1'):
        raise ValueError('source_checkpoint_local_audio_inputs_schema_invalid')
    settings = value['audio_plan_resolver']
    if (not isinstance(settings, dict) or set(settings) != {'sources', 'license_grants', 'native_quality_script', 'native_quality_sha256'}
            or not isinstance(settings['sources'], list) or len(settings['sources']) != 1):
        raise ValueError('source_checkpoint_only_local_audio_resolver_allowed')
    source = settings['sources'][0]
    if not isinstance(source, dict) or set(source) != {'audio_path', 'record_path', 'audio_sha256', 'record_sha256'}:
        raise ValueError('source_checkpoint_pinned_local_audio_source_required')
    for kind in ('audio', 'record'):
        if not re.fullmatch('[a-f0-9]{64}', str(source[kind + '_sha256'])):
            raise ValueError('source_checkpoint_local_audio_pin_invalid')
        file_record(source[kind + '_path'], source[kind + '_sha256'])
    if value['sources'] != {'audio': {'path': source['audio_path'], 'sha256': source['audio_sha256']},
                            'record': {'path': source['record_path'], 'sha256': source['record_sha256']}}:
        raise ValueError('source_checkpoint_local_audio_source_pins_conflict')
    script = Path(settings['native_quality_script'])
    if (script != Path('/srv/ai-self-media-tools/scripts/validate_kuaishou_video.py')
            or not re.fullmatch('[a-f0-9]{64}', str(settings['native_quality_sha256']))):
        raise ValueError('source_checkpoint_current_native_audio_gate_required')
    file_record(script, settings['native_quality_sha256'])

    record = json.loads(Path(source['record_path']).read_bytes())
    rights = value['rights_source']; license_url = 'https://creativecommons.org/licenses/by/4.0/'
    grants = settings['license_grants']
    if (not isinstance(grants, dict) or set(grants) != {license_url}
            or not isinstance(grants[license_url], dict) or set(grants[license_url]) != {'platforms', 'use', 'commercial', 'derivatives', 'evidence_url'}
            or grants[license_url] != {'platforms': ['kuaishou'], 'use': 'embedded_bgm', 'commercial': True, 'derivatives': True, 'evidence_url': license_url}
            or not isinstance(rights, dict) or set(rights) != {'artist', 'title', 'file_page', 'license', 'attribution_required', 'changes_notice_required', 'rights_quality_passed'}
            or rights['license'] != license_url or record.get('license') != license_url or rights['artist'] != record.get('artist')
            or not isinstance(rights['title'], str) or not rights['title'].strip()
            or rights['attribution_required'] is not True or rights['changes_notice_required'] is not True
            or rights['rights_quality_passed'] is not False):
        raise ValueError('source_checkpoint_local_audio_rights_binding_invalid')
    return copy.deepcopy(settings)


def check_source_checkpoint_state(proof, job, steps, events, effects):
    if (proof.get('version')!='media_source_checkpoint_resume_v1' or proof.get('job_id')!=job.get('id')
            or job.get('state')not in {'blocked','failed'} or job.get('attempts')!=1
            or job.get('lease_owner')or job.get('lease_expires_at')or digest(job)!=proof.get('job_sha256')
            or steps!=proof.get('original_steps')or events!=proof.get('original_events')or any(effects.values())):
        raise ValueError('source_checkpoint_original_or_zero_media_changed')
    if (len(steps)!=4 or [s['step_name']for s in steps]!=['initialize_task','load_platform_workflow_context','validate_content_policy_inputs','collect_native_source_inputs']
            or any(s['status']!='SUCCEEDED'for s in steps[:3])or steps[-1]['status']not in {'BLOCKED','FAILED_FINAL'}):
        raise ValueError('source_checkpoint_exact_pre_media_stage_required')


def validate_source_checkpoint_resume(store, path, expected):
    proof=source_checkpoint_evidence(path,expected)
    source_checkpoint_local_audio_inputs(proof)
    job=store.get_job(proof['job_id']);steps=store.workflow_steps(job['id']);events=store.events(job['id'])
    with store.connect()as conn:
        effects={}
        for table in ['draft_versions','artifacts','approvals','deliveries','delivery_queue','platform_outputs','review_tasks','delivery_intents','publish_receipts']:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'AND name=?",(table,)).fetchone():
                effects[table]=conn.execute('SELECT count(*) FROM '+table+' WHERE job_id=?',(job['id'],)).fetchone()[0]
        if conn.execute("SELECT 1 FROM events WHERE job_id=?AND event='media_source_checkpoint_resume_started'",(job['id'],)).fetchone():
            raise ValueError('source_checkpoint_resume_already_consumed')
    check_source_checkpoint_state(proof,job,steps,events,effects)
    reference=(job.get('brief')or{}).get('quality_revision')or{}
    if reference.get('request_sha256')!=proof.get('quality_revision_request_sha256'):
        raise ValueError('source_checkpoint_original_quality_request_changed')
    from .quality_revision import verified_quality_revision
    verified_quality_revision(store,job)
    checkpoint=proof['source_checkpoint_ref'];raw,_=file_record(checkpoint['path'],checkpoint['sha256']);info=Path(checkpoint['path']).stat();captured=json.loads(raw)
    if (info.st_uid!=0 or info.st_mode&0o077 or captured.get('version')!='original_generation_checkpoint_v1'
            or captured.get('job_id')!=job['id']or captured.get('store_path')!=str(store.path.resolve())
            or captured.get('quality_revision_request_sha256')!=proof['quality_revision_request_sha256']
            or captured.get('generation_session',{}).get('task_job_id')!=proof['origin_run_id']):
        raise ValueError('source_checkpoint_original_generation_binding_changed')
    from .original_knowledge import revision_source_context,verify_revision_generation,validate_revision_script,verify_native_execution_window
    parent,ref,facts,context=revision_source_context(store,job)
    if captured.get('context_sha256')!=digest(context):raise ValueError('source_checkpoint_original_context_changed')
    generation=captured['generation_session'];generated=verify_revision_generation(generation,context)
    validate_revision_script(generated,digest(context),facts['texts']);lease=captured['generation_lease']
    verify_native_execution_window(store,job['id'],lease['owner'],lease['expires_at'],generation['task_job_id'],generation['session_id'])
    return proof


def resume_source_checkpoint(pipeline, job_id, evidence_path, evidence_sha256):
    # Native CLI resume entry delegates to a public Pipeline method; no direct Root/private bypass.
    return pipeline.resume_source_checkpoint(job_id,evidence_path,evidence_sha256)
