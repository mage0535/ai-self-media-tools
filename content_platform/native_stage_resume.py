"""Resume one incomplete normal generation; successful Source is an immutable checkpoint."""
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .factual_candidate_revision import (
    current_generation_records, digest, private_read, registered_current_scope, write_once,
)

VERSION = 'normal_generation_checkpoint_v1'
GENERATED_VERSION = 'normal_generated_factual_checkpoint_v1'
EDIT_VERSION = 'normal_native_factual_patch_v1'
TARGET_VERSION = 'normal_completed_target_checkpoint_v1'
_SEAL = object()
_EFFECT_TABLES = ('draft_versions', 'artifacts', 'approvals', 'deliveries', 'delivery_queue',
                  'platform_outputs', 'review_tasks', 'delivery_intents', 'publish_receipts')


def _identifier(value, size):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{' + str(size) + '}', value)


def _native_snapshot(origin):
    from .target_adaptation import native_session
    home = Path('/srv/hermes-worker/authority-runtime-homes') / ('media-' + origin)
    sessions = current_generation_records(home)
    if not sessions or any(not row.get('ended_at') for row in sessions):
        raise PermissionError('generation_checkpoint_unfinished_native_action')
    result = []
    for row in sessions:
        messages = native_session(home, row['id'])[1]
        assistant = [m for m in messages if m.get('role') == 'assistant']
        result.append({'session': {k: row.get(k) for k in ('id', 'model', 'ended_at', 'api_call_count')},
                       'session_sha256': digest(row), 'messages_sha256': digest(messages),
                       'synthetic_notice_only': bool(assistant) and all(not m.get('tool_calls') and m.get('content') ==
                           'Your request was not processed. Send it again if you still want me to carry it out.' for m in assistant),
                       'has_tool_result': any(m.get('role') == 'tool' for m in messages)})
    return result


def _effect_counts(store, job_id):
    result = {}
    with store.connect() as conn:
        for name in _EFFECT_TABLES:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone():
                result[name] = conn.execute('SELECT count(*) FROM ' + name + ' WHERE job_id=?', (job_id,)).fetchone()[0]
    return result


def _history(store, job_id, origin):
    return {'job': store.get_job(job_id), 'steps': store.workflow_steps(job_id),
            'events': store.events(job_id), 'effects': _effect_counts(store, job_id),
            'native': _native_snapshot(origin)}


def prepare_generation_checkpoint(store, job_id, origin_task_id, nonce, directory,
                                  code_pins, *, refresh_strategy=False):
    """Root read-only sealer; creates new private proof files, never changes business state."""
    if (not _identifier(job_id, 16) or not _identifier(origin_task_id, 32)
            or not _identifier(nonce, 32) or type(refresh_strategy) is not bool):
        raise ValueError('generation_checkpoint_identifiers_required')
    directory = Path(directory)
    if directory != Path(store.path).parent / 'quality_runtime':
        raise PermissionError('generation_checkpoint_owned_proof_directory_required')
    history = _history(store, job_id, origin_task_id)
    stage = Path('/srv/hermes-worker-media/jobs') / origin_task_id
    prepared = stage / ('normal-primary-' + job_id + '-twitter.input.private.json')
    raw = prepared.read_bytes()
    private_read(prepared, hashlib.sha256(raw).hexdigest())
    proof = {'version': VERSION, 'job_id': job_id, 'origin_task_id': origin_task_id,
             'nonce': nonce, 'budget_seconds': 900, 'no_publish': True,
             'refresh_strategy': refresh_strategy, 'code_pins': code_pins,
             'prepared_ref': {'path': str(prepared), 'sha256': hashlib.sha256(raw).hexdigest()},
             'history_ref': write_once(directory / ('generation-checkpoint-' + nonce + '.history.private.json'), history)}
    validate_generation_checkpoint(store, proof)
    return write_once(directory / ('generation-checkpoint-' + nonce + '.proof.private.json'), proof)


def validate_generation_checkpoint(store, proof, *, initial=True):
    if (set(proof) != {'version', 'job_id', 'origin_task_id', 'nonce', 'budget_seconds', 'no_publish',
                       'refresh_strategy', 'code_pins', 'prepared_ref', 'history_ref'}
            or proof.get('version') != VERSION or proof.get('budget_seconds') != 900
            or proof.get('no_publish') is not True or type(proof.get('refresh_strategy')) is not bool
            or not _identifier(proof.get('job_id'), 16) or not _identifier(proof.get('origin_task_id'), 32)
            or not _identifier(proof.get('nonce'), 32)):
        raise PermissionError('generation_checkpoint_exact_contract_required')
    job_id = proof['job_id']
    history = private_read(**dict(path=proof['history_ref']['path'], expected=proof['history_ref']['sha256'], limit=16777216))
    original = history['job']
    failed = [r for r in history['steps'] if r.get('status') != 'SUCCEEDED']
    sources = [r for r in history['steps'] if r.get('step_name') == 'collect_native_source_inputs']
    if (original.get('id') != job_id or original.get('state') != 'failed'
            or original.get('lease_owner') or original.get('lease_expires_at')
            or original.get('platforms') != ['twitter'] or original.get('body')
            or len(failed) != 1 or failed[0].get('step_name') != 'generate_content'
            or failed[0].get('status') != 'FAILED_FINAL' or failed[0].get('reason_code') != 'exception'
            or len(sources) != 1 or sources[0].get('status') != 'SUCCEEDED'
            or any(history['effects'].values()) or not history['effects']):
        raise PermissionError('generation_checkpoint_only_incomplete_primary_required')
    if not (original.get('brief') or {}).get('source_collection_audit'):
        raise PermissionError('generation_checkpoint_successful_source_audit_required')
    # API counters do not prove that no HTTP request occurred. A new Root-signed action
    # authorizes this unfinished stage; no original invocation is replayed.
    if not history['native'] or any(not r['session'].get('ended_at') for r in history['native']):
        raise PermissionError('generation_checkpoint_unknown_running_model_rejected')
    last = history['native'][-1]
    if (last['session'].get('api_call_count') != 0 or last['synthetic_notice_only'] is not True
            or last['has_tool_result'] is not False):
        raise PermissionError('generation_checkpoint_no_completed_candidate_required')
    if _native_snapshot(proof['origin_task_id']) != history['native']:
        raise ValueError('generation_checkpoint_original_native_records_changed')
    prepared_path = Path('/srv/hermes-worker-media/jobs') / proof['origin_task_id'] / ('normal-primary-' + job_id + '-twitter.input.private.json')
    if Path(proof['prepared_ref']['path']) != prepared_path:
        raise PermissionError('generation_checkpoint_actual_primary_input_required')
    prepared = private_read(prepared_path, proof['prepared_ref']['sha256'])
    if prepared.get('source_collection_audit') != original['brief'].get('source_collection_audit'):
        raise ValueError('generation_checkpoint_original_source_binding_changed')
    pins = proof.get('code_pins') or []
    required = {'/srv/ai-self-media-tools/content_platform/' + name for name in
                ('native_stage_resume.py', 'pipeline.py', 'generator.py', 'target_adaptation.py',
                 'current_strategy_refresh.py', 'task_source_inputs.py', 'intelligence.py')}
    if len({p['path'] for p in pins}) != len(pins) or not required <= {p['path'] for p in pins}:
        raise PermissionError('generation_checkpoint_deployed_source_pins_required')
    for pin in pins:
        p = Path(pin['path'])
        if any(part.is_symlink() for part in (p, *p.parents)) or hashlib.sha256(p.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('generation_checkpoint_deployed_source_changed')
    current_steps = {row['id']: row for row in store.workflow_steps(job_id)}
    current_events = {row['id']: row for row in store.events(job_id)}
    if any(current_steps.get(r['id']) != r for r in history['steps']) or any(current_events.get(r['id']) != r for r in history['events']):
        raise ValueError('generation_checkpoint_original_history_changed')
    if initial and (_history(store, job_id, proof['origin_task_id']) != history):
        raise ValueError('generation_checkpoint_actual_checkpoint_changed')
    return history, prepared


def require_active_stage_grant(store, job_id, owner):
    grant = getattr(store, '_native_stage_resume_grant', None)
    if (not isinstance(grant, dict) or grant.get('_seal') is not _SEAL
            or grant.get('store_identity') != id(store) or grant.get('thread_id') != threading.get_ident()
            or grant.get('pid') != os.getpid() or grant.get('job_id') != job_id or grant.get('owner') != owner
            or time.monotonic() >= grant.get('deadline', 0)):
        raise PermissionError('generation_checkpoint_current_execution_grant_required')
    job = store.get_job(job_id)
    try:
        expiry = datetime.fromisoformat(job['lease_expires_at'].replace('Z', '+00:00'))
    except (KeyError, TypeError, ValueError):
        raise PermissionError('generation_checkpoint_current_lease_required')
    if (job.get('state') != 'generating' or job.get('lease_owner') != owner or expiry.tzinfo is None
            or expiry <= datetime.now(timezone.utc)):
        raise PermissionError('generation_checkpoint_current_lease_expired')
    return grant


def execute_native_stage_resume(pipeline, job_id, evidence_path, evidence_sha256):
    from .native_quality_runner import current_active_role
    from .workflow_runtime import WorkflowStepRunner, WorkflowBlocked, strict_workflow_lock
    from .platform_workflow_context import load_platform_workflow_context
    from .visual_policy_gate import validate_content_policy_inputs
    from .task_source_inputs import refresh_task_source_contexts, persist_task_source_inputs
    from .current_strategy_refresh import refresh_current_strategy_inputs, reuse_current_strategy_inputs

    proof = private_read(evidence_path, evidence_sha256)
    generated = proof.get('version') == GENERATED_VERSION
    completed_target = proof.get('version') == TARGET_VERSION
    validate_checkpoint = (validate_completed_target_checkpoint if completed_target else
                           validate_generated_checkpoint if generated else validate_generation_checkpoint)
    if proof.get('job_id') != job_id:
        raise PermissionError('generation_checkpoint_requested_job_changed')
    expected = Path(pipeline.data_dir) / 'quality_runtime' / ('generation-checkpoint-' + proof['nonce'] + '.proof.private.json')
    if Path(evidence_path) != expected:
        raise PermissionError('generation_checkpoint_exact_owned_proof_required')
    history, _ = validate_checkpoint(pipeline.store, proof)
    home, task, route = current_active_role(600)
    if task == proof['origin_task_id'] or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH') != '0':
        raise PermissionError('generation_checkpoint_new_current_no_publication_scope_required')
    cfg = pipeline.generator.config
    if (cfg.get('provider') != 'hermes-cli' or cfg.get('hermes_provider') != route['provider']
            or cfg.get('hermes_model') != route['model'] or cfg.get('allow_fallback') is not False):
        raise PermissionError('generation_checkpoint_current_sdk_route_required')
    if current_generation_records(home, allow_absent=True):
        raise PermissionError('generation_checkpoint_new_scope_has_model_history')
    seconds = registered_current_scope(home, task)
    if seconds <= 0:
        raise PermissionError('generation_checkpoint_original_scope_deadline_exhausted')
    store = pipeline.store
    owner = pipeline._worker_id()
    workflow = 'wf_' + job_id
    deadline = time.monotonic() + seconds
    prior_names = {row['step_name'] for row in history['steps']}
    suffix = '__generation_checkpoint_' + proof['nonce']

    class CheckpointRunner(WorkflowStepRunner):
        def _map(self, name):
            if history.get('saved_rendered_checkpoint') and name == 'validate_image_requirements':
                return next(row['step_name'] for row in history['steps'] if row['id'] == history['saved_rendered_checkpoint']['image_check_step_id'])
            if (generated or completed_target) and name == 'generate_content':
                return next(r['step_name'] for r in history['steps'] if r['id'] == proof['generation_step_id'])
            return name + suffix if name in prior_names and not name.endswith(suffix) else name

        def _deps(self, names):
            return [self._map(name) for name in names or []]

        def _guard(self):
            return require_active_stage_grant(store, job_id, owner)

        def run(self, name, func, required=True, depends_on=None, require_output=False, input_payload=None):
            if name == 'collect_native_source_inputs':
                raise PermissionError('generation_checkpoint_successful_source_cannot_replay')
            if completed_target and (name in {'generate_content', 'revise_factual_candidate'} or name.startswith('adapt_twitter_target_copy')):
                raise PermissionError('completed_target_successful_native_stage_cannot_replay')
            def bounded():
                self._guard()
                result = func()
                self._guard()
                return result
            return super().run(self._map(name), bounded, required, self._deps(depends_on), require_output, input_payload)

        def succeeded(self, name, output=None, required=True, depends_on=None, message=''):
            self._guard()
            return super().succeeded(self._map(name), output, required, self._deps(depends_on), message)

        def block(self, name, code, message, gate_result=None, depends_on=None):
            self._guard()
            return super().block(self._map(name), code, message, gate_result, self._deps(depends_on))

        def skipped(self, name, code, message, required=False, depends_on=None):
            self._guard()
            return super().skipped(self._map(name), code, message, required, self._deps(depends_on))

    with strict_workflow_lock(store, owner, workflow, seconds, pipeline.strict_serial):
        validate_checkpoint(store, proof)
        write_once(expected.with_name('generation-checkpoint-' + proof['nonce'] + '.invocation.private.json'),
                   {'version': proof['version'], 'job_id': job_id, 'task_id': task, 'proof_sha256': evidence_sha256,
                    'no_publish': True, 'automatic_replay': False, 'deadline_unix': time.time() + max(0, deadline - time.monotonic())})
        if not store.claim(job_id, {'blocked'} if completed_target and history.get('saved_visual_content_failure') else {'failed'} if completed_target and proof.get('precompiled_visual_span_ref') else {'blocked'} if generated or completed_target else {'failed'}, owner, max(1, math.floor(deadline - time.monotonic())), 'generating'):
            raise RuntimeError('generation_checkpoint_job_already_claimed')
        grant = {'_seal': _SEAL, 'store_identity': id(store), 'thread_id': threading.get_ident(),
                 'pid': os.getpid(), 'job_id': job_id, 'owner': owner, 'task_id': task, 'deadline': deadline,
                 'nonce': proof['nonce'], 'proof': proof, 'proof_ref': {'path':str(expected),'sha256':evidence_sha256},
                 'binding_mode': 'saved_rendered_checkpoint' if history.get('saved_rendered_checkpoint') else None}
        store._native_stage_resume_grant = grant
        runner = CheckpointRunner(store, workflow, job_id, notifier=pipeline.notifier)
        try:
            if history.get('saved_rendered_checkpoint'):
                _, draft = validate_completed_target_checkpoint(store, proof, initial=False)
                store.record_event(job_id, 'native_generation_checkpoint_consumed',
                    {'nonce':proof['nonce'], 'proof_ref':{'path':str(expected),'sha256':evidence_sha256},
                     'origin_task_id':proof['origin_task_id'], 'current_task_id':task,
                     'original_failed_step_id':history['saved_rendered_checkpoint']['failed_step_id'],
                     'successful_source_replayed':False,'original_observation_times_rewritten':False,
                     'saved_rendered_prefix_reused':True})
                return _continue_completed_saved_rendered(pipeline,store,proof,expected,evidence_sha256,history,draft,owner,runner)
            job = store.get_job(job_id)
            contexts = {p: load_platform_workflow_context(p, plan=job['brief']) for p in job['platforms']}
            policy = validate_content_policy_inputs(job, contexts, store=store)
            if not policy.get('passed'):
                runner.block('validate_content_policy_inputs', 'content_policy_inputs_invalid', 'Current policy rejected generation checkpoint', policy)
            runner.succeeded('validate_content_policy_inputs', policy)
            hygiene = pipeline._content_hygiene(job)
            if hygiene.get('status') == 'blocked':
                runner.block('run_content_hygiene', 'content_hygiene_blocked', 'Current topic dedup rejected checkpoint', hygiene)
            runner.succeeded('run_content_hygiene', hygiene)
            if proof['refresh_strategy']:
                refreshed = refresh_current_strategy_inputs(store, pipeline.config, job, contexts, runner=runner)
            else:
                refs = {p: job['brief']['platform_workflow_inputs'][p]['strategy_observation_ref'] for p in job['platforms']}
                refreshed = reuse_current_strategy_inputs(store, pipeline.config, job, contexts, refs, runner=runner)
            prepared = refreshed['brief']
            # Strategy observation is a new bounded action. Original factual Source,
            # its times and its successful row remain immutable in the checkpoint.
            factual_fields = ('production_intent', 'claim_ledger', 'sources', 'factual_sources',
                              'factual_reference_posts', 'original_method_factual_inputs',
                              'original_method_observed_ref', 'original_method_source_ref')
            for field in factual_fields:
                if prepared.get(field) != job['brief'].get(field):
                    raise ValueError('generation_checkpoint_original_facts_changed')
            for platform, scoped_brief in refreshed['platform_briefs'].items():
                original_scoped = job['brief']['platform_workflow_inputs'][platform]
                if any(scoped_brief.get(field) != original_scoped.get(field) for field in factual_fields):
                    raise ValueError('generation_checkpoint_original_platform_facts_changed')
                if scoped_brief.get('content_mode') == 'original_method':
                    scoped_brief['style_research_reference_posts'] = copy.deepcopy(scoped_brief.get('reference_posts') or [])
            audit = copy.deepcopy(job['brief']['source_collection_audit'])
            audit['current_strategy_refresh_audit'] = refreshed['strategy_refresh_audit']
            prepared['source_collection_audit'] = audit
            for b in refreshed['platform_briefs'].values():
                b['source_collection_audit'] = copy.deepcopy(audit)
            prepared['platform_workflow_inputs'] = copy.deepcopy(refreshed['platform_briefs'])
            # The binder hashes the actual current Store audit. Persist this derived
            # audit first; the successful original Source row stays immutable.
            job = persist_task_source_inputs(store, job, owner, prepared)
            contexts = refresh_task_source_contexts(contexts, prepared)
            scoped = {p: pipeline._bind_platform_source_inputs(job_id, b, p, contexts[p], owner)
                      for p, b in refreshed['platform_briefs'].items()}
            if len(scoped) == 1:
                prepared = dict(next(iter(scoped.values())))
            prepared['platform_workflow_inputs'] = copy.deepcopy(scoped)
            persist_task_source_inputs(store, job, owner, prepared)
            runner.succeeded('run_operation_strategy', {'strategy_gates': {p: b['strategy_evidence_gate'] for p, b in scoped.items()}}, depends_on=['run_content_hygiene'])
            grant['prepared_stage'] = {'brief': prepared, 'platform_briefs': scoped}
            store.record_event(job_id, 'native_generation_checkpoint_consumed',
                               {'nonce': proof['nonce'], 'proof_ref': {'path': str(expected), 'sha256': evidence_sha256},
                                'origin_task_id': proof['origin_task_id'], 'current_task_id': task,
                                'original_failed_step_id': proof['blocked_step_id'] if completed_target else next(r['id'] for r in history['steps'] if r['status'] == ('BLOCKED' if generated else 'FAILED_FINAL')),
                                'successful_source_replayed': False, 'original_observation_times_rewritten': False,
                                'strategy_refresh_audit': refreshed['strategy_refresh_audit']})
            if completed_target:
                if proof.get('precompiled_visual_span_ref'):
                    _, draft = validate_completed_target_checkpoint(store, proof, initial=False)
                    draft['draft_meta']['normal_completed_target_checkpoint_ref'] = {'path':str(expected),'sha256':evidence_sha256}
                else:
                    draft, _ = read_completed_target_candidate(store, job_id, proof['factual_step_id'], proof['target_step_id'])
                result = pipeline._continue_generated_draft(job_id, owner, workflow, runner, contexts,
                                                            store.get_job(job_id), prepared, scoped, draft)
            elif generated:
                draft = runner.run('revise_factual_candidate', lambda: _edit_generated_candidate(pipeline, proof, evidence_path, evidence_sha256, prepared, home, task, route),
                                   depends_on=['generate_content'], require_output=True)
                result = pipeline._continue_generated_draft(job_id, owner, workflow, runner, contexts,
                                                            store.get_job(job_id), prepared, scoped, draft)
            else:
                result = pipeline._continue_native_generation(job_id, owner, workflow, runner, contexts,
                                                              prepared_stage=grant['prepared_stage'])
            validate_checkpoint(store, proof, initial=False)
            return result
        except WorkflowBlocked as error:
            if store.get_job(job_id).get('lease_owner') == owner:
                return pipeline._hydrate(store.release_claim(job_id, owner, 'blocked', 'generation_checkpoint_blocked', error,
                                                             detail={'step': error.step, 'reason_code': error.reason_code}))
            raise
        except BaseException as error:
            if store.get_job(job_id).get('lease_owner') == owner:
                store.release_claim(job_id, owner, 'failed', 'generation_checkpoint_failed', str(error))
            raise
        finally:
            if getattr(store, '_native_stage_resume_grant', None) is grant:
                store._native_stage_resume_grant = None


def read_generated_candidate(store, job_id, step_id):
    """Pure reconstruction of a completed model result, with its exact original hash."""
    from .generator import DraftGenerator, strip_web_residue
    from .humanize import naturalize_copy
    from .target_adaptation import native_session, _normal_primary_record
    rows = [r for r in store.workflow_steps(job_id) if r['id'] == step_id]
    if (len(rows) != 1 or rows[0]['status'] != 'SUCCEEDED'
            or not re.fullmatch(r'generate_content(?:__generation_checkpoint_[a-f0-9]{32})?', rows[0]['step_name'])):
        raise PermissionError('generated_checkpoint_actual_successful_primary_required')
    result = rows[0]['output']; meta = copy.deepcopy(result['draft_meta'])
    ref = meta['normal_generation_source_ref']; record = private_read(ref['path'], ref['sha256'])
    prepared = private_read(record['prepared_input_ref']['path'], record['prepared_input_ref']['sha256'], limit=4194304)
    home = Path('/srv/hermes-worker/authority-runtime-homes') / ('media-' + record['task_id'])
    _, _, raw = native_session(home, record['session_id'])
    generator = DraftGenerator({})
    parsed = generator._coerce_provider_draft(generator._bounded_provider_content(raw, prepared), store.get_job(job_id)['topic'])
    if digest({'title': str(parsed.get('title') or ''), 'body': str(parsed.get('body') or '')}) != record['provider_input_sha256']:
        raise ValueError('generated_checkpoint_original_provider_input_changed')
    body = str(parsed.get('body') or '').strip(); cta = parsed.get('cta') or meta['style']['cta']
    if cta and cta not in body:
        body = body.rstrip() + '\n\n' + cta
    body = generator._fit_article_length(naturalize_copy(strip_web_residue(body), meta)['body'], meta)
    draft = {'title': result['title'], 'body': body, 'provider': result['provider'],
             'prompt_version': result['prompt_version'], 'draft_meta': meta}
    _normal_primary_record(dict(store.get_job(job_id), **draft))
    return draft, ref, record


def read_completed_target_candidate(store, job_id, factual_step_id, target_step_id):
    """Reconstruct only the already completed factual patch and target, without a model."""
    from .target_adaptation import read_target_adaptation
    steps = {row['id']: row for row in store.workflow_steps(job_id)}
    factual_step = steps.get(factual_step_id) or {}; target_step = steps.get(target_step_id) or {}
    if (factual_step.get('status') != 'SUCCEEDED' or factual_step.get('step_name') != 'revise_factual_candidate'
            or target_step.get('status') != 'SUCCEEDED' or target_step.get('step_name') != 'adapt_twitter_target_copy'
            or not factual_step_id < target_step_id):
        raise PermissionError('completed_target_actual_successful_native_steps_required')
    factual_ref = (factual_step.get('output') or {}).get('draft_meta', {}).get('normal_factual_revision_ref')
    if not isinstance(factual_ref, dict):
        raise ValueError('completed_target_original_factual_source_missing')
    factual = private_read(factual_ref['path'], factual_ref['sha256'])
    draft = copy.deepcopy(private_read(factual['candidate_ref']['path'], factual['candidate_ref']['sha256'], limit=4194304))
    draft['draft_meta']['normal_factual_revision_ref'] = copy.deepcopy(factual_ref)
    current = dict(store.get_job(job_id), **draft)
    checked_ref, checked = read_factual_revision_source(current)
    if checked_ref != factual_ref or checked != factual:
        raise ValueError('completed_target_original_factual_patch_changed')
    target_ref = copy.deepcopy(target_step.get('output'))
    if not isinstance(target_ref, dict) or set(target_ref) != {'path', 'sha256'}:
        raise ValueError('completed_target_actual_copy_reference_required')
    draft['draft_meta']['target_adaptation_ref'] = target_ref
    read_target_adaptation(dict(store.get_job(job_id), **draft), 'twitter')
    target = private_read(target_ref['path'], target_ref['sha256'])
    previous_ref = factual['proof_ref']; previous = private_read(previous_ref['path'], previous_ref['sha256'])
    if (previous.get('version') != GENERATED_VERSION or previous.get('job_id') != job_id
            or factual.get('task_id') != target.get('task_id') or target.get('source_generation_ref') != factual_ref
            or factual.get('source_generation_ref') != previous.get('generation_source_ref')):
        raise ValueError('completed_target_actual_factual_target_parent_changed')
    lineage = {'factual_source_ref': factual_ref, 'factual_record': factual,
               'target_copy_ref': target_ref, 'target_record': target,
               'previous_generated_proof_ref': previous_ref, 'previous_generated_proof': previous,
               'generation_source_ref': previous['generation_source_ref'], 'prepared_ref': previous['prepared_ref'],
               'generation_step_id': previous['generation_step_id']}
    return draft, lineage


def _validate_original_code_archive(ref, previous_ref, previous):
    archive = private_read(ref['path'], ref['sha256'])
    expected = {pin['path']: pin['sha256'] for pin in previous['code_pins']}
    rows = archive.get('files') or []
    if (archive.get('version') != 'generated_checkpoint_original_code_archive_v1'
            or archive.get('previous_generated_proof_ref') != previous_ref
            or len(expected) != 8 or len(rows) != 8 or len({row.get('source_path') for row in rows}) != 8
            or {row.get('source_path'): row.get('sha256') for row in rows} != expected):
        raise ValueError('completed_target_original_execution_code_archive_changed')
    for row in rows:
        if (row.get('archive_ref') or {}).get('sha256') != row['sha256']:
            raise ValueError('completed_target_original_code_pin_changed')
        _review_factual_raw(row['archive_ref'])
    return archive


def prepare_completed_target_checkpoint(store, job_id, factual_step_id, target_step_id, nonce,
                                        directory, code_pins, original_code_archive_ref, *, refresh_strategy=True,
                                        deterministic_patch=None, precompiled_visual_span_ref=None, rendered_checkpoint_code_archive_ref=None):
    if deterministic_patch is not None or precompiled_visual_span_ref is not None:
        return _prepare_completed_target_extension(store, job_id, factual_step_id, target_step_id, nonce,
            directory, code_pins, original_code_archive_ref, refresh_strategy, deterministic_patch, precompiled_visual_span_ref, rendered_checkpoint_code_archive_ref)
    directory = Path(directory)
    if directory != Path(store.path).parent / 'quality_runtime' or not _identifier(nonce, 32):
        raise PermissionError('completed_target_owned_new_proof_required')
    draft, lineage = read_completed_target_candidate(store, job_id, factual_step_id, target_step_id)
    history = _history(store, job_id, lineage['factual_record']['task_id'])
    blocked = [r for r in history['steps'] if r['step_name'] == 'validate_target_publication_copy' and r['status'] == 'BLOCKED']
    if len(blocked) != 1:
        raise PermissionError('completed_target_single_actual_target_block_required')
    proof = {'version': TARGET_VERSION, 'job_id': job_id, 'origin_task_id': lineage['factual_record']['task_id'],
        'nonce': nonce, 'budget_seconds': 900, 'no_publish': True, 'refresh_strategy': refresh_strategy,
        'code_pins': code_pins, 'generation_step_id': lineage['generation_step_id'], 'factual_step_id': factual_step_id,
        'target_step_id': target_step_id, 'blocked_step_id': blocked[0]['id'],
        'factual_source_ref': lineage['factual_source_ref'], 'target_copy_ref': lineage['target_copy_ref'],
        'previous_generated_proof_ref': lineage['previous_generated_proof_ref'],
        'prepared_ref': lineage['prepared_ref'], 'generation_source_ref': lineage['generation_source_ref'],
        'original_code_archive_ref': original_code_archive_ref,
        'candidate_ref': write_once(directory / ('generation-checkpoint-' + nonce + '.candidate.private.json'), draft),
        'history_ref': write_once(directory / ('generation-checkpoint-' + nonce + '.history.private.json'), history)}
    validate_completed_target_checkpoint(store, proof)
    return write_once(directory / ('generation-checkpoint-' + nonce + '.proof.private.json'), proof)


def _validate_completed_target_checkpoint_original(store, proof, *, initial=True):
    required = {'version', 'job_id', 'origin_task_id', 'nonce', 'budget_seconds', 'no_publish', 'refresh_strategy',
        'code_pins', 'generation_step_id', 'factual_step_id', 'target_step_id', 'blocked_step_id', 'factual_source_ref',
        'target_copy_ref', 'candidate_ref', 'history_ref', 'original_code_archive_ref', 'previous_generated_proof_ref',
        'prepared_ref', 'generation_source_ref'}
    if (set(proof) != required or proof.get('version') != TARGET_VERSION or proof.get('budget_seconds') != 900
            or proof.get('no_publish') is not True or type(proof.get('refresh_strategy')) is not bool
            or not _identifier(proof.get('job_id'), 16) or not _identifier(proof.get('origin_task_id'), 32)
            or not _identifier(proof.get('nonce'), 32)):
        raise PermissionError('completed_target_exact_checkpoint_contract_required')
    draft, lineage = read_completed_target_candidate(store, proof['job_id'], proof['factual_step_id'], proof['target_step_id'])
    for name in ('factual_source_ref', 'target_copy_ref', 'previous_generated_proof_ref', 'prepared_ref', 'generation_source_ref', 'generation_step_id'):
        if proof[name] != lineage[name]: raise ValueError('completed_target_original_lineage_changed')
    previous = lineage['previous_generated_proof']
    _validate_original_code_archive(proof['original_code_archive_ref'], lineage['previous_generated_proof_ref'], previous)
    if (proof['origin_task_id'] != lineage['factual_record']['task_id'] or
            draft != private_read(proof['candidate_ref']['path'], proof['candidate_ref']['sha256'], limit=4194304)):
        raise ValueError('completed_target_original_candidate_changed')
    history = private_read(proof['history_ref']['path'], proof['history_ref']['sha256'], limit=16777216)
    old = private_read(previous['history_ref']['path'], previous['history_ref']['sha256'], limit=16777216)
    primary = private_read(lineage['generation_source_ref']['path'], lineage['generation_source_ref']['sha256'])
    original_sources = [row for row in old['steps'] if row.get('step_name') == 'collect_native_source_inputs' and row.get('status') == 'SUCCEEDED']
    original_primary = [row for row in old['steps'] if row.get('id') == proof['generation_step_id'] and row.get('status') == 'SUCCEEDED']
    current_steps = {r['id']: r for r in store.workflow_steps(proof['job_id'])}
    current_events = {r['id']: r for r in store.events(proof['job_id'])}
    blocked = current_steps.get(proof['blocked_step_id']) or {}; gate = blocked.get('gate') or {}
    if (history.get('job', {}).get('id') != proof['job_id'] or old.get('job', {}).get('id') != proof['job_id']
            or previous.get('origin_task_id') != primary.get('task_id')
            or (history['job'].get('brief') or {}).get('source_control_job_id') != primary.get('task_id')
            or len(original_primary) != 1 or not original_sources
            or not any(row['id'] < proof['generation_step_id'] for row in original_sources)
            or blocked.get('step_name') != 'validate_target_publication_copy' or blocked.get('status') != 'BLOCKED'
            or blocked.get('reason_code') != 'target_publication_copy_invalid'
            or set(gate.get('failures') or []) != {'target_content_depth'}
            or gate.get('caption_sha256') != lineage['target_record'].get('caption_sha256')
            or gate.get('target_copy_ref') != lineage['target_copy_ref']
            or (gate.get('claim_gate') or {}).get('passed') is not True
            or (gate.get('risk') or {}).get('level') == 'block'
            or (gate.get('compliance') or {}).get('level') == 'block'
            or (gate.get('content_hygiene') or {}).get('status') == 'blocked'
            or set((gate.get('content_depth_gate') or {}).get('failures') or []) != {'knowledge_points_insufficient', 'action_steps_insufficient'}
            or any(row.get('status') not in {'SUCCEEDED', 'BLOCKED'} for row in history['steps'])
            or {row['id'] for row in history['steps'] if row.get('status') != 'SUCCEEDED'} !=
               {row['id'] for row in old['steps'] if row.get('status') != 'SUCCEEDED'} | {proof['blocked_step_id']}
            or not proof['generation_step_id'] < proof['factual_step_id'] < proof['target_step_id'] < proof['blocked_step_id']
            or any(current_steps.get(r['id']) != r for r in history['steps'] + old['steps'])
            or any(current_events.get(r['id']) != r for r in history['events'] + old['events'])
            or _native_snapshot(proof['origin_task_id']) != history['native']
            or _native_snapshot(previous['origin_task_id']) != old['native']):
        raise PermissionError('completed_target_original_success_failure_history_changed')
    if initial and (history != _history(store, proof['job_id'], proof['origin_task_id'])
            or history['job'].get('state') != 'blocked' or history['job'].get('lease_owner')
            or history['job'].get('lease_expires_at') or not history['effects'] or any(history['effects'].values())):
        raise PermissionError('completed_target_only_zero_effect_closed_failure_required')
    pins = proof.get('code_pins') or []
    required_paths = {'/srv/ai-self-media-tools/content_platform/' + name for name in
        ('native_stage_resume.py', 'pipeline.py', 'generator.py', 'target_adaptation.py',
         'current_strategy_refresh.py', 'task_source_inputs.py', 'intelligence.py', 'claim_ledger.py')}
    if len({pin['path'] for pin in pins}) != len(pins) or not required_paths <= {pin['path'] for pin in pins}:
        raise PermissionError('completed_target_current_code_pins_required')
    for pin in pins:
        path = Path(pin['path'])
        if any(p.is_symlink() for p in (path, *path.parents)) or hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('completed_target_current_code_changed')
    return history, draft


def prepare_generated_checkpoint(store, job_id, generation_step_id, nonce, directory, code_pins,
                                 old_text, instruction, *, refresh_strategy=True, review_factual_evidence_ref=None):
    directory = Path(directory)
    if directory != Path(store.path).parent / 'quality_runtime' or not _identifier(nonce, 32):
        raise PermissionError('generated_checkpoint_owned_new_proof_required')
    if review_factual_evidence_ref is not None:
        _review_factual_evidence(review_factual_evidence_ref)
    draft, source, record = read_generated_candidate(store, job_id, generation_step_id)
    history = _history(store, job_id, record['task_id'])
    proof = {'version': GENERATED_VERSION, 'job_id': job_id, 'origin_task_id': record['task_id'],
             'nonce': nonce, 'budget_seconds': 900, 'no_publish': True, 'refresh_strategy': refresh_strategy,
             'code_pins': code_pins, 'prepared_ref': record['prepared_input_ref'],
             'generation_step_id': generation_step_id, 'generation_source_ref': source,
             'editorial_change': {'old_text': old_text, 'instruction': instruction},
             'candidate_ref': write_once(directory / ('generation-checkpoint-' + nonce + '.candidate.private.json'), draft),
             'history_ref': write_once(directory / ('generation-checkpoint-' + nonce + '.history.private.json'), history)}
    if review_factual_evidence_ref is not None:
        proof['review_factual_evidence_ref'] = copy.deepcopy(review_factual_evidence_ref)
    validate_generated_checkpoint(store, proof)
    return write_once(directory / ('generation-checkpoint-' + nonce + '.proof.private.json'), proof)


def validate_generated_checkpoint(store, proof, *, initial=True):
    if (proof.get('version') != GENERATED_VERSION or proof.get('budget_seconds') != 900
            or proof.get('no_publish') is not True or type(proof.get('refresh_strategy')) is not bool
            or not _identifier(proof.get('job_id'), 16) or not _identifier(proof.get('origin_task_id'), 32)
            or not _identifier(proof.get('nonce'), 32)):
        raise PermissionError('generated_checkpoint_exact_contract_required')
    if 'review_factual_evidence_ref' in proof:
        _review_factual_evidence(proof['review_factual_evidence_ref'])
    history = private_read(proof['history_ref']['path'], proof['history_ref']['sha256'], limit=16777216)
    draft, source, record = read_generated_candidate(store, proof['job_id'], proof['generation_step_id'])
    if (source != proof['generation_source_ref'] or record['task_id'] != proof['origin_task_id']
            or record['prepared_input_ref'] != proof['prepared_ref']
            or draft != private_read(proof['candidate_ref']['path'], proof['candidate_ref']['sha256'], limit=4194304)):
        raise ValueError('generated_checkpoint_successful_candidate_changed')
    failures = [r for r in history['steps'] if r['status'] != 'SUCCEEDED' and r['step_name'] != 'generate_content']
    if (any(r['status'] not in {'SUCCEEDED', 'FAILED_FINAL', 'BLOCKED'} for r in history['steps'])
            or len(failures) != 1 or failures[0]['status'] != 'BLOCKED' or failures[0]['step_name'] != 'validate_factual_claims'
            or failures[0].get('reason_code') != 'factual_claim_evidence_missing'
            or set((failures[0].get('gate') or {}).get('failures') or []) != {'unsourced_numeric_claim'}):
        raise PermissionError('generated_checkpoint_only_unresolved_numeric_factual_gate')
    change = proof.get('editorial_change') or {}; old = change.get('old_text'); instruction = change.get('instruction')
    findings = (failures[0].get('gate') or {}).get('findings') or []
    if (set(change) != {'old_text', 'instruction'} or not isinstance(old, str) or not 8 <= len(old) <= 4096
            or draft['body'].count(old) != 1 or not isinstance(instruction, str) or not 8 <= len(instruction) <= 2048
            or not findings or any(str(r.get('text') or '') not in old for r in findings)):
        raise PermissionError('generated_checkpoint_exact_failed_claim_span_required')
    current_steps = {r['id']: r for r in store.workflow_steps(proof['job_id'])}
    current_events = {r['id']: r for r in store.events(proof['job_id'])}
    if (any(current_steps.get(r['id']) != r for r in history['steps'])
            or any(current_events.get(r['id']) != r for r in history['events'])):
        raise ValueError('generated_checkpoint_original_history_changed')
    if not any(r['step_name'] == 'collect_native_source_inputs' and r['status'] == 'SUCCEEDED' for r in history['steps']):
        raise PermissionError('generated_checkpoint_successful_Source_required')
    if initial and (history != _history(store, proof['job_id'], proof['origin_task_id'])
                    or history['job'].get('state') != 'blocked' or history['job'].get('lease_owner')
                    or history['job'].get('lease_expires_at') or any(history['effects'].values())):
        raise PermissionError('generated_checkpoint_only_saved_zero_output_gate_failure')
    pins = proof.get('code_pins') or []
    required = {'/srv/ai-self-media-tools/content_platform/' + name for name in
                ('native_stage_resume.py', 'pipeline.py', 'generator.py', 'target_adaptation.py',
                 'current_strategy_refresh.py', 'task_source_inputs.py', 'intelligence.py', 'claim_ledger.py')}
    if len({p['path'] for p in pins}) != len(pins) or not required <= {p['path'] for p in pins}:
        raise PermissionError('generated_checkpoint_current_code_pins_required')
    for p in pins:
        path = Path(p['path'])
        if any(x.is_symlink() for x in (path, *path.parents)) or hashlib.sha256(path.read_bytes()).hexdigest() != p['sha256']:
            raise ValueError('generated_checkpoint_current_code_changed')
    return history, draft


def _review_factual_raw(ref, *, size_required=False):
    import stat
    if (not isinstance(ref, dict) or set(ref) != ({'path', 'sha256', 'bytes'} if size_required else {'path', 'sha256'})
            or not isinstance(ref.get('path'), str) or not re.fullmatch('[a-f0-9]{64}', str(ref.get('sha256')))):
        raise ValueError('factual_review_exact_original_reference_required')
    path = Path(ref['path'])
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise PermissionError('factual_review_private_original_path_required')
    before = path.stat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_mode & 0o777 != 0o600
            or before.st_nlink != 1 or not 0 < before.st_size <= 2097152):
        raise PermissionError('factual_review_Root600_original_required')
    raw = path.read_bytes(); after = path.stat()
    if ((before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size)
            or hashlib.sha256(raw).hexdigest() != ref['sha256']
            or size_required and (type(ref['bytes']) is not int or len(raw) != ref['bytes'])):
        raise ValueError('factual_review_original_bytes_changed')
    return raw


def _review_factual_evidence(ref):
    """Read Root's pinned original PDF, extraction and HTTP record; this is no verdict."""
    from urllib.parse import urlsplit
    value = json.loads(_review_factual_raw(ref))
    if (not isinstance(value, dict) or set(value) != {'version', 'document_title', 'document_date', 'url', 'purpose',
            'pdf_ref', 'retrieval_ref', 'text_ref', 'relevant_sections', 'extraction', 'text'}
            or value.get('version') != 'official_factual_reference_v1'
            or value.get('purpose') != 'historical_factual_support_not_current_platform_metrics'
            or not isinstance(value.get('document_title'), str) or not value['document_title'].strip()):
        raise ValueError('factual_review_official_historical_record_required')
    url = urlsplit(value['url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port not in (None, 443):
        raise ValueError('factual_review_official_https_url_required')
    document_date = datetime.fromisoformat(value['document_date'])
    if document_date.date() > datetime.now(timezone.utc).date():
        raise ValueError('factual_review_historical_document_date_required')
    folder = Path(ref['path']).parent
    if any(Path(value[key]['path']).parent != folder for key in ('pdf_ref', 'text_ref', 'retrieval_ref')):
        raise ValueError('factual_review_same_original_capture_scope_required')
    pdf = _review_factual_raw(value['pdf_ref'], size_required=True)
    text = _review_factual_raw(value['text_ref'], size_required=True).decode('utf-8')
    retrieval = json.loads(_review_factual_raw(value['retrieval_ref']))
    extraction = value['extraction']; captured = retrieval.get('retrieved_at_unix')
    if (not pdf.startswith(b'%PDF-') or text != value['text'] or not text.strip()
            or not isinstance(extraction, dict) or extraction.get('method') != 'pypdf'
            or not isinstance(extraction.get('version'), str) or type(extraction.get('pages')) is not int or extraction['pages'] <= 0
            or extraction.get('source_pdf_sha256') != value['pdf_ref']['sha256']
            or extraction.get('utf8_text_sha256') != value['text_ref']['sha256']
            or retrieval.get('status') != 200 or type(retrieval.get('status')) is not int
            or retrieval.get('url') != value['url'] or retrieval.get('final_url') != value['url']
            or retrieval.get('path') != value['pdf_ref']['path'] or retrieval.get('sha256') != value['pdf_ref']['sha256']
            or retrieval.get('bytes') != len(pdf) or retrieval.get('content_type') != 'application/pdf'
            or type(captured) not in (int, float) or not math.isfinite(captured) or not 0 < captured <= time.time() + 60
            or not isinstance(value['relevant_sections'], list) or not value['relevant_sections']
            or any(not isinstance(item, str) or not item.strip() for item in value['relevant_sections'])):
        raise ValueError('factual_review_pdf_text_extraction_or_actual_HTTP_binding_changed')
    return {'source_kind': 'official_factual_reference', 'title': value['document_title'], 'body': text,
            'url': value['url'], 'document_date': value['document_date'], 'current_platform_data': False,
            'purpose': value['purpose'], 'retrieved_at_unix': captured, 'review_evidence_ref': copy.deepcopy(ref),
            'raw_ref': copy.deepcopy(value['pdf_ref']), 'text_ref': copy.deepcopy(value['text_ref']),
            'retrieval_ref': copy.deepcopy(value['retrieval_ref']), 'extraction': copy.deepcopy(extraction),
            'relevant_sections': copy.deepcopy(value['relevant_sections'])}


def _edit_generated_candidate(pipeline, proof, proof_path, proof_sha, prepared, home, task, route):
    from .target_adaptation import native_session, _normal_root
    from .humanize import _score, quality_gate
    from .content_depth import build_content_depth_plan
    original = private_read(proof['candidate_ref']['path'], proof['candidate_ref']['sha256'], limit=4194304)
    factual_excerpts = []
    for post in prepared.get('factual_reference_posts') or []:
        if post.get('source_kind') != 'official_factual_reference':
            continue
        body = str(post.get('body') or '')
        at = body.casefold().find('limit wait time')
        if at >= 0:
            factual_excerpts.append({'url': post.get('url'), 'raw_ref': post.get('raw_ref'),
                                     'excerpt': body[max(0, at - 160):at + 800]})
    context = {'job_id': proof['job_id'], 'source_candidate_ref': proof['candidate_ref'],
               'source_generation_ref': proof['generation_source_ref'], 'change': proof['editorial_change'],
               'factual_reference_excerpts': factual_excerpts,
               'instruction': 'Return only JSON with exactly replacement_text. Edit only the supplied old_text span as directed; remove unsupported illustrative numeric duration and universal/default behavior guarantees. Do not add facts, numbers, firsthand claims, tools or publication. Do not return a title or full body: all other text stays immutable.',
               'no_publish': True}
    reviewed = None
    if 'review_factual_evidence_ref' in proof:
        reviewed = _review_factual_evidence(proof['review_factual_evidence_ref'])
        context['review_factual_evidence'] = reviewed
    prompt = json.dumps(context, ensure_ascii=False, sort_keys=True)
    context['prompt'] = prompt; context['prompt_sha256'] = hashlib.sha256(prompt.encode()).hexdigest()
    root = _normal_root(task, proof['job_id'])
    context_ref = write_once(root / ('normal-factual-edit-' + proof['job_id'] + '.context.private.json'), context)
    before = {r['id'] for r in current_generation_records(home, allow_absent=True)}
    pipeline.generator._stage_job_id = proof['job_id']
    returned = pipeline.generator._call_hermes_text(prompt, prepared, bounded_stage='factual_edit')
    patch = _parse_editorial_patch(returned, proof['editorial_change']['old_text'])
    require_active_stage_grant(pipeline.store, proof['job_id'], pipeline.store._native_stage_resume_grant['owner'])
    new = [r for r in current_generation_records(home) if r['id'] not in before and not r.get('parent_session_id')]
    if len(new) != 1:
        raise ValueError('factual_edit_one_new_native_session_required')
    session, messages, raw = native_session(home, new[0]['id'])
    if (session.get('model') != route['model'] or not session.get('ended_at') or type(session.get('api_call_count')) is not int
            or session['api_call_count'] <= 0 or _parse_editorial_patch(raw, patch['old_text']) != patch
            or not any(r.get('role') == 'user' and isinstance(r.get('content'), str) and prompt in r['content'] for r in messages)):
        raise ValueError('factual_edit_actual_native_patch_binding_required')
    revised = copy.deepcopy(original)
    revised['body'] = original['body'].replace(patch['old_text'], patch['replacement_text'], 1)
    meta = revised['draft_meta']
    if reviewed is not None:
        meta['factual_reference_posts'] = copy.deepcopy(meta.get('factual_reference_posts') or []) + [reviewed]
    scores = _score(revised['body'], meta)
    meta.update(quality_scores=scores, quality_gate=quality_gate(scores))
    meta['content_depth_plan'] = build_content_depth_plan(revised['title'], revised['body'],
        evidence=pipeline.generator._depth_evidence(prepared, meta), actions=meta.get('actionable_checklist') or [], platform='twitter')
    candidate_ref = write_once(root / ('normal-factual-edit-' + proof['job_id'] + '.candidate.private.json'), revised)
    record = {'version': EDIT_VERSION, 'job_id': proof['job_id'], 'task_id': task,
              'provider': route['provider'], 'model': route['model'], 'session_id': session['id'],
              'session_sha256': digest(session), 'messages_sha256': digest(messages), 'api_call_count': session['api_call_count'],
              'native_final_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'patch': patch,
              'context_ref': context_ref, 'candidate_ref': candidate_ref, 'source_candidate_ref': proof['candidate_ref'],
              'source_generation_ref': proof['generation_source_ref'], 'proof_ref': {'path': str(proof_path), 'sha256': proof_sha},
              'normalized_generation_sha256': digest({'title': revised['title'], 'body': revised['body']}),
              'no_publish': True, 'primary_generation_replayed': False}
    ref = write_once(root / ('normal-factual-edit-' + proof['job_id'] + '.private.json'), record)
    revised['draft_meta']['normal_factual_revision_ref'] = ref
    return revised


def _parse_editorial_patch(raw, old):
    text = raw.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    value = json.loads(text)
    if (not isinstance(value, dict) or set(value) != {'replacement_text'}
            or not isinstance(value['replacement_text'], str) or not 8 <= len(value['replacement_text']) <= 4096
            or value['replacement_text'] == old):
        raise ValueError('factual_edit_exact_single_span_patch_required')
    return dict(value, old_text=old)


def read_factual_revision_source(job):
    """Historical source verification does not reactivate an ended Role."""
    if (job.get('draft_meta') or {}).get('normal_completed_target_checkpoint_ref'):
        job = read_completed_target_source_projection(job)
    from .target_adaptation import native_session, _normal_root, _normal_primary_record
    ref = job.get('draft_meta', {}).get('normal_factual_revision_ref')
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('factual_edit_actual_source_reference_required')
    record = private_read(ref['path'], ref['sha256'])
    root = _normal_root(record.get('task_id'), job.get('id'))
    if (Path(ref['path']) != root / ('normal-factual-edit-' + job['id'] + '.private.json')
            or record.get('version') != EDIT_VERSION or record.get('job_id') != job['id'] or record.get('no_publish') is not True):
        raise ValueError('factual_edit_source_owner_or_kind_changed')
    original = private_read(record['source_candidate_ref']['path'], record['source_candidate_ref']['sha256'], limit=4194304)
    parent, _ = _normal_primary_record(dict(job, **original))
    proof = private_read(record['proof_ref']['path'], record['proof_ref']['sha256'])
    invocation = private_read(Path(record['proof_ref']['path']).with_name('generation-checkpoint-' + proof['nonce'] + '.invocation.private.json'))
    if (parent != record['source_generation_ref'] or proof.get('version') != GENERATED_VERSION
            or proof.get('candidate_ref') != record['source_candidate_ref'] or proof.get('generation_source_ref') != parent
            or invocation.get('version') != GENERATED_VERSION or invocation.get('task_id') != record['task_id'] or invocation.get('proof_sha256') != record['proof_ref']['sha256']
            or invocation.get('no_publish') is not True):
        raise ValueError('factual_edit_original_signed_scope_lineage_changed')
    session, messages, raw = native_session(Path('/srv/hermes-worker/authority-runtime-homes') / ('media-' + record['task_id']), record['session_id'])
    if (Path(record['context_ref']['path']) != root / ('normal-factual-edit-' + job['id'] + '.context.private.json')
            or Path(record['candidate_ref']['path']) != root / ('normal-factual-edit-' + job['id'] + '.candidate.private.json')):
        raise ValueError('factual_edit_current_owned_artifact_paths_required')
    context = private_read(record['context_ref']['path'], record['context_ref']['sha256'])
    prompt = context.get('prompt')
    original_context = {k: v for k, v in context.items() if k not in {'prompt', 'prompt_sha256'}}
    if (not isinstance(prompt, str) or prompt != json.dumps(original_context, ensure_ascii=False, sort_keys=True)
            or hashlib.sha256(prompt.encode()).hexdigest() != context.get('prompt_sha256')
            or context.get('change') != proof['editorial_change'] or context.get('source_candidate_ref') != record['source_candidate_ref']
            or context.get('source_generation_ref') != parent or context.get('job_id') != job['id'] or context.get('no_publish') is not True):
        raise ValueError('factual_edit_native_exact_instruction_binding_changed')
    reviewed = _review_factual_evidence(proof['review_factual_evidence_ref']) if 'review_factual_evidence_ref' in proof else None
    if context.get('review_factual_evidence') != reviewed:
        raise ValueError('factual_edit_official_review_evidence_changed')
    patch = _parse_editorial_patch(raw, proof['editorial_change']['old_text'])
    if (not session.get('ended_at') or session.get('model') != record['model'] or session.get('api_call_count') != record['api_call_count']
            or type(record['api_call_count']) is not int or record['api_call_count'] <= 0
            or digest(session) != record['session_sha256'] or digest(messages) != record['messages_sha256']
            or hashlib.sha256(raw.encode()).hexdigest() != record['native_final_sha256'] or patch != record['patch']
            or not any(r.get('role') == 'user' and isinstance(r.get('content'), str) and context.get('prompt') in r['content'] for r in messages)):
        raise ValueError('factual_edit_native_patch_source_changed')
    candidate = private_read(record['candidate_ref']['path'], record['candidate_ref']['sha256'], limit=4194304)
    expected_body = original['body'].replace(patch['old_text'], patch['replacement_text'], 1)
    if reviewed is not None and (candidate.get('draft_meta') or {}).get('factual_reference_posts') != copy.deepcopy(original['draft_meta'].get('factual_reference_posts') or []) + [reviewed]:
        raise ValueError('factual_edit_only_pinned_official_review_evidence_may_be_added')
    if (candidate['title'] != original['title'] or candidate['body'] != expected_body
            or job.get('title') != candidate['title'] or job.get('body') != expected_body
            or digest({'title': candidate['title'], 'body': expected_body}) != record['normalized_generation_sha256']):
        raise ValueError('factual_edit_only_exact_authorized_span_may_change')
    return ref, record


# Only this completed-target continuation may preserve an unfinished visual request.
# It never reopens, relabels or calls that original native session.
def _completed_target_visual_history(store, job_id, origin):
    from .target_adaptation import native_session
    home = Path('/srv/hermes-worker/authority-runtime-homes') / ('media-' + origin)
    native = []
    for row in current_generation_records(home):
        messages = native_session(home, row['id'])[1] if row.get('ended_at') else _completed_target_unfinished_messages(home, row['id'])
        assistant = [m for m in messages if m.get('role') == 'assistant']
        native.append({'session': {k: row.get(k) for k in ('id', 'model', 'ended_at', 'api_call_count')},
                       'session_sha256': digest(row), 'messages_sha256': digest(messages),
                       'synthetic_notice_only': bool(assistant) and all(not m.get('tool_calls') and m.get('content') ==
                           'Your request was not processed. Send it again if you still want me to carry it out.' for m in assistant),
                       'has_tool_result': any(m.get('role') == 'tool' for m in messages)})
    history = {'job': store.get_job(job_id), 'steps': store.workflow_steps(job_id),
               'events': store.events(job_id), 'effects': _effect_counts(store, job_id), 'native': native,
               'preserved_artifacts': store.artifacts(job_id)}
    return history


def _completed_target_extension_draft(store, original, lineage, patch=None, visual_ref=None):
    draft = copy.deepcopy(original)
    if patch is not None:
        if (not isinstance(patch, dict) or set(patch) != {'old_text', 'replacement_text'}
                or any(not isinstance(patch.get(k), str) or not 8 <= len(patch[k]) <= 4096 for k in patch)
                or patch['old_text'] == patch['replacement_text'] or original['body'].count(patch['old_text']) != 1):
            raise ValueError('completed_target_exact_authorized_deterministic_patch_required')
        draft['body'] = original['body'].replace(patch['old_text'], patch['replacement_text'], 1)
        # Recompute deterministic derivative scores/depth; never carry old QA as new proof.
        from .humanize import _score, quality_gate
        from .content_depth import build_content_depth_plan
        from .generator import DraftGenerator
        prepared = private_read(lineage['prepared_ref']['path'], lineage['prepared_ref']['sha256'], limit=4194304)
        scores = _score(draft['body'], draft['draft_meta'])
        draft['draft_meta'].update(quality_scores=scores, quality_gate=quality_gate(scores))
        draft['draft_meta']['content_depth_plan'] = build_content_depth_plan(draft['title'], draft['body'],
            evidence=DraftGenerator({})._depth_evidence(prepared, draft['draft_meta']),
            actions=draft['draft_meta'].get('actionable_checklist') or [], platform='twitter')
    if visual_ref is not None:
        if (not isinstance(visual_ref, dict) or set(visual_ref) != {'path', 'sha256'}
                or Path(visual_ref['path']).parent != Path(store.path).parent / 'quality_runtime'):
            raise PermissionError('completed_target_owned_precompiled_visual_reference_required')
        value = private_read(visual_ref['path'], visual_ref['sha256'], limit=4194304)
        from .current_twitter_visual_plan_producer import build_precompiled_visual_span_bundle
        from .target_adaptation import read_target_adaptation
        original_job = dict(store.get_job(lineage['factual_record']['job_id']), **original)
        target = read_target_adaptation(original_job, 'twitter')
        current = dict(original_job, **draft)
        expected = build_precompiled_visual_span_bundle(current, target)
        if value != expected or value.get('version') != 'current_deterministic_visual_span_bundle_v1' or value.get('native_model_called') is not False:
            raise ValueError('completed_target_precompiled_visual_source_or_current_content_changed')
        draft['draft_meta']['precompiled_visual_span_ref'] = copy.deepcopy(visual_ref)
        draft['draft_meta']['precompiled_visual_span_required'] = True
    return draft


def _prepare_completed_target_extension(store, job_id, factual_step_id, target_step_id, nonce,
                                        directory, code_pins, original_code_archive_ref,
                                        refresh_strategy, deterministic_patch, precompiled_visual_span_ref, rendered_checkpoint_code_archive_ref=None):
    directory = Path(directory)
    if directory != Path(store.path).parent / 'quality_runtime' or not _identifier(nonce, 32) or precompiled_visual_span_ref is None:
        raise PermissionError('completed_target_new_deterministic_visual_proof_required')
    original, lineage = read_completed_target_candidate(store, job_id, factual_step_id, target_step_id)
    history = _completed_target_visual_history(store, job_id, lineage['factual_record']['task_id'])
    if rendered_checkpoint_code_archive_ref is not None:
        history['saved_rendered_checkpoint'] = _completed_target_saved_rendered_checkpoint(store, history, rendered_checkpoint_code_archive_ref)
    elif history['job'].get('state') == 'blocked':
        history['saved_visual_content_failure'] = _completed_target_saved_visual_failure(store, history)
    failed = [r for r in history['steps'] if r.get('step_name') == 'prepare_current_twitter_visual_plan' and r.get('status') == 'FAILED_FINAL']
    if len(failed) != 1:raise PermissionError('completed_target_single_original_visual_failure_required')
    draft = _completed_target_extension_draft(store, original, lineage, deterministic_patch, precompiled_visual_span_ref)
    proof = {'version': TARGET_VERSION, 'job_id': job_id, 'origin_task_id': lineage['factual_record']['task_id'],
        'nonce': nonce, 'budget_seconds': 900, 'no_publish': True, 'refresh_strategy': refresh_strategy,
        'code_pins': code_pins, 'generation_step_id': lineage['generation_step_id'], 'factual_step_id': factual_step_id,
        'target_step_id': target_step_id, 'blocked_step_id': failed[0]['id'],
        'factual_source_ref': lineage['factual_source_ref'], 'target_copy_ref': lineage['target_copy_ref'],
        'previous_generated_proof_ref': lineage['previous_generated_proof_ref'],
        'prepared_ref': lineage['prepared_ref'], 'generation_source_ref': lineage['generation_source_ref'],
        'original_code_archive_ref': original_code_archive_ref,
        'candidate_ref': write_once(directory / ('generation-checkpoint-' + nonce + '.candidate.private.json'), draft),
        'history_ref': write_once(directory / ('generation-checkpoint-' + nonce + '.history.private.json'), history),
        'precompiled_visual_span_ref': copy.deepcopy(precompiled_visual_span_ref)}
    if deterministic_patch is not None:proof['deterministic_patch'] = copy.deepcopy(deterministic_patch)
    validate_completed_target_checkpoint(store, proof)
    return write_once(directory / ('generation-checkpoint-' + nonce + '.proof.private.json'), proof)


def validate_completed_target_checkpoint(store, proof, *, initial=True, original_code_archive_ref=None):
    extras = {'deterministic_patch', 'precompiled_visual_span_ref'} & set(proof)
    if not extras:return _validate_completed_target_checkpoint_original(store, proof, initial=initial)
    base = {'version', 'job_id', 'origin_task_id', 'nonce', 'budget_seconds', 'no_publish', 'refresh_strategy',
        'code_pins', 'generation_step_id', 'factual_step_id', 'target_step_id', 'blocked_step_id', 'factual_source_ref',
        'target_copy_ref', 'candidate_ref', 'history_ref', 'original_code_archive_ref', 'previous_generated_proof_ref',
        'prepared_ref', 'generation_source_ref'}
    if (set(proof) not in (base | {'precompiled_visual_span_ref'}, base | extras) or 'precompiled_visual_span_ref' not in extras
            or proof.get('version') != TARGET_VERSION or proof.get('budget_seconds') != 900
            or proof.get('no_publish') is not True or type(proof.get('refresh_strategy')) is not bool
            or not _identifier(proof.get('job_id'), 16) or not _identifier(proof.get('origin_task_id'), 32)
            or not _identifier(proof.get('nonce'), 32)):
        raise PermissionError('completed_target_exact_extended_checkpoint_contract_required')
    original, lineage = read_completed_target_candidate(store, proof['job_id'], proof['factual_step_id'], proof['target_step_id'])
    for name in ('factual_source_ref', 'target_copy_ref', 'previous_generated_proof_ref', 'prepared_ref', 'generation_source_ref', 'generation_step_id'):
        if proof[name] != lineage[name]:raise ValueError('completed_target_original_lineage_changed')
    previous = lineage['previous_generated_proof']
    _validate_original_code_archive(proof['original_code_archive_ref'], lineage['previous_generated_proof_ref'], previous)
    draft = _completed_target_extension_draft(store, original, lineage, proof.get('deterministic_patch'), proof['precompiled_visual_span_ref'])
    if (proof['origin_task_id'] != lineage['factual_record']['task_id'] or
            draft != private_read(proof['candidate_ref']['path'], proof['candidate_ref']['sha256'], limit=4194304)):
        raise ValueError('completed_target_exact_derived_candidate_changed')
    history = private_read(proof['history_ref']['path'], proof['history_ref']['sha256'], limit=16777216)
    old = private_read(previous['history_ref']['path'], previous['history_ref']['sha256'], limit=16777216)
    primary = private_read(lineage['generation_source_ref']['path'], lineage['generation_source_ref']['sha256'])
    current_steps = {r['id']:r for r in store.workflow_steps(proof['job_id'])};current_events = {r['id']:r for r in store.events(proof['job_id'])}
    failed = current_steps.get(proof['blocked_step_id']) or {}
    old_failed = {r['id']for r in old['steps']if r.get('status') != 'SUCCEEDED'}
    if (history['job'].get('id') != proof['job_id'] or old['job'].get('id') != proof['job_id']
            or previous.get('origin_task_id') != primary.get('task_id')
            or (history['job'].get('brief') or {}).get('source_control_job_id') != primary.get('task_id')
            or not any(r.get('id') == proof['generation_step_id'] and r.get('status') == 'SUCCEEDED'for r in old['steps'])
            or not any(r.get('step_name') == 'collect_native_source_inputs' and r.get('status') == 'SUCCEEDED' and r['id'] < proof['generation_step_id']for r in old['steps'])
            or failed.get('step_name') != 'prepare_current_twitter_visual_plan' or failed.get('status') != 'FAILED_FINAL'
            or failed.get('reason_code') != 'exception'
            or not proof['generation_step_id'] < proof['factual_step_id'] < proof['target_step_id'] < proof['blocked_step_id']
            or {r['id']for r in history['steps']if r.get('status') != 'SUCCEEDED'} != old_failed | {proof['blocked_step_id']} | ({history['saved_rendered_checkpoint']['failed_step_id']} if history.get('saved_rendered_checkpoint') else set())
            or any(current_steps.get(r['id']) != r for r in history['steps'] + old['steps'])
            or any(current_events.get(r['id']) != r for r in history['events'] + old['events'])
            or _native_snapshot(previous['origin_task_id']) != old['native']
            or _completed_target_visual_history(store, proof['job_id'], proof['origin_task_id'])['native'] != history['native']):
        raise PermissionError('completed_target_preserved_visual_failure_history_changed')
    # A timeout record proves incompleteness, never absence of an upstream request.
    from .target_adaptation import native_session
    encoded = str(failed.get('message') or '')
    try:failure = json.loads(encoded[encoded.index('{'):]);diagref = failure['diagnostic_ref'];diag = private_read(diagref['path'], diagref['sha256'])
    except (ValueError,KeyError,TypeError):raise PermissionError('completed_target_original_visual_timeout_diagnostic_required')
    unfinished = [r for r in history['native'] if not r['session'].get('ended_at')]
    if len(unfinished) != 1 or diag.get('failure_reason') != 'hermes_cli_timeout':
        raise PermissionError('completed_target_one_original_unknown_visual_session_required')
    sid = unfinished[0]['session']['id'];home = Path('/srv/hermes-worker/authority-runtime-homes') / ('media-' + proof['origin_task_id'])
    messages = _completed_target_unfinished_messages(home, sid)
    if (len(messages) != 1 or messages[0].get('role') != 'user' or not isinstance(messages[0].get('content'), str)
            or hashlib.sha256(messages[0]['content'].encode()).hexdigest() != diag.get('prompt_sha256')
            or unfinished[0]['has_tool_result'] or unfinished[0]['session'].get('api_call_count') != 0):
        raise PermissionError('completed_target_original_unknown_visual_prompt_changed')
    terminal_path = Path('/srv/hermes-worker-media/jobs') / proof['origin_task_id'] / 'result.json'
    terminal = private_read(terminal_path)
    if terminal.get('status') not in {'needs_review','failed'}:
        raise PermissionError('completed_target_original_visual_control_not_terminal')
    if history.get('saved_rendered_checkpoint'):
        if proof['refresh_strategy'] is not True:raise PermissionError('completed_target_saved_rendered_fresh_strategy_required')
        _validate_completed_saved_rendered_checkpoint(store, history, initial=initial)
    elif history.get('saved_visual_content_failure'):
        _validate_completed_saved_visual_failure(store, history, initial=initial)
    else:
        artifacts = history.get('preserved_artifacts') or []
        if (not artifacts or any(a.get('kind') != 'illustration' or Path(a.get('path','')).suffix != '.txt' for a in artifacts)
                or any(history['effects'].get(k,0) for k in _EFFECT_TABLES if k != 'artifacts')
                or history['effects'].get('artifacts') != len(artifacts)):
            raise PermissionError('completed_target_only_original_illustration_prompt_effect_allowed')
        current_artifacts = {a['id']:a for a in store.artifacts(proof['job_id'])}
        for a in artifacts:
            if current_artifacts.get(a['id']) != a:raise ValueError('completed_target_original_artifact_row_changed')
            _completed_target_original_prompt(a)
        if initial and (history != _completed_target_visual_history(store, proof['job_id'], proof['origin_task_id'])
                or history['job'].get('state') != 'failed' or history['job'].get('lease_owner') or history['job'].get('lease_expires_at')):
            raise PermissionError('completed_target_only_original_closed_visual_failure_required')
    pins = proof.get('code_pins') or []
    required = {'/srv/ai-self-media-tools/content_platform/' + name for name in
        ('native_stage_resume.py','pipeline.py','generator.py','target_adaptation.py','current_strategy_refresh.py','task_source_inputs.py','intelligence.py','claim_ledger.py')}
    if len(pins) != 8 or {p.get('path')for p in pins} != required:raise PermissionError('completed_target_eight_current_code_pins_required')
    if original_code_archive_ref is not None:
        if initial:raise PermissionError('completed_target_archived_code_only_for_historical_source')
        archived_proof_path=Path(store.path).parent/'quality_runtime'/('generation-checkpoint-'+proof['nonce']+'.proof.private.json')
        archived_proof_sha=hashlib.sha256(archived_proof_path.read_bytes()).hexdigest()
        if private_read(archived_proof_path,archived_proof_sha)!=proof:raise ValueError('completed_target_historical_original_proof_changed')
        _validate_original_code_archive(original_code_archive_ref,
            {'path':str(archived_proof_path),'sha256':archived_proof_sha},proof)
    for pin in pins:
        path = Path(pin['path'])
        if any(p.is_symlink()for p in(path,*path.parents)) or original_code_archive_ref is None and hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('completed_target_current_code_changed')
    return history, draft


def _completed_target_readonly_store():
    from contextlib import contextmanager
    import sqlite3
    from .store import Store
    store = object.__new__(Store);store.path = Path(__file__).resolve().parents[1] / 'data/state.db'
    @contextmanager
    def ro():
        db = sqlite3.connect(store.path.resolve().as_uri() + '?mode=ro', uri=True);db.row_factory = sqlite3.Row;db.execute('PRAGMA query_only=ON')
        try:yield db
        finally:db.close()
    store.connect = ro
    return store


def read_completed_target_source_projection(job):
    """Only verify the old SDK source against its original body; current gates keep the new body."""
    from .native_quality_resume import historical_completed_target_source_projection
    quality_projection=historical_completed_target_source_projection(job)
    if quality_projection is not None:return quality_projection
    ref = (job.get('draft_meta') or {}).get('normal_completed_target_checkpoint_ref')
    if not isinstance(ref,dict) or set(ref) != {'path','sha256'}:raise PermissionError('completed_target_derived_source_reference_required')
    proof = private_read(ref['path'],ref['sha256'])
    quality = Path(__file__).resolve().parents[1] / 'data/quality_runtime'
    if (Path(ref['path']) != quality / ('generation-checkpoint-' + str(proof.get('nonce')) + '.proof.private.json')
            or proof.get('job_id') != job.get('id') or not proof.get('precompiled_visual_span_ref')):
        raise PermissionError('completed_target_derived_source_owned_proof_required')
    store = _completed_target_readonly_store()
    history, draft = validate_completed_target_checkpoint(store,proof,initial=False)
    invocation = private_read(Path(ref['path']).with_name('generation-checkpoint-' + proof['nonce'] + '.invocation.private.json'))
    if (invocation.get('version') != TARGET_VERSION or invocation.get('job_id') != job['id']
            or invocation.get('proof_sha256') != ref['sha256'] or invocation.get('no_publish') is not True
            or invocation.get('automatic_replay') is not False or not _identifier(invocation.get('task_id'),32)
            or invocation['task_id'] == proof['origin_task_id']):
        raise PermissionError('completed_target_new_registered_invocation_required')
    events = store.events(job['id'])
    if not any(e.get('event') == 'native_generation_checkpoint_consumed' and
               json.loads(e.get('detail_json') or '{}').get('proof_ref') == ref and
               json.loads(e.get('detail_json') or '{}').get('current_task_id') == invocation['task_id'] for e in events):
        raise PermissionError('completed_target_actual_consumed_transition_required')
    if job.get('state') == 'generating' and (type(invocation.get('deadline_unix')) not in (int,float) or time.time() >= invocation['deadline_unix']):
        raise PermissionError('completed_target_active_transition_deadline_elapsed')
    if (job.get('title') != draft['title'] or job.get('body') != draft['body']
            or any((job.get('draft_meta') or {}).get(k) != draft['draft_meta'].get(k) for k in
                   ('normal_factual_revision_ref','target_adaptation_ref','precompiled_visual_span_ref','precompiled_visual_span_required'))):
        raise ValueError('completed_target_only_exact_new_candidate_and_old_caption_allowed')
    original, _ = read_completed_target_candidate(store,proof['job_id'],proof['factual_step_id'],proof['target_step_id'])
    return dict(job,**original)


def _completed_target_original_prompt(row):
    import stat
    path=Path(row['path'])
    if not path.is_absolute() or any(p.is_symlink()for p in(path,*path.parents)):
        raise PermissionError('completed_target_original_illustration_path_changed')
    before=path.stat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid!=0 or before.st_mode&0o022
            or before.st_nlink!=1 or not 0<before.st_size<=2097152):
        raise PermissionError('completed_target_original_illustration_metadata_changed')
    raw=path.read_bytes();after=path.stat()
    if (before.st_ino,before.st_mtime_ns,before.st_size)!=(after.st_ino,after.st_mtime_ns,after.st_size) or hashlib.sha256(raw).hexdigest()!=row['checksum']:
        raise ValueError('completed_target_original_illustration_bytes_changed')
    return raw


def _completed_target_unfinished_messages(home, sid):
    # Read the exact native rows without inventing the final required by native_session.
    import sqlite3
    db=Path(home)/'state.db'
    if any(p.is_symlink()for p in(db,*db.parents)):
        raise PermissionError('completed_target_original_native_session_path_changed')
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON')
        row=conn.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
        if row is None or row['ended_at'] is not None:
            raise ValueError('completed_target_original_unfinished_native_row_required')
        return [dict(r)for r in conn.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id',(sid,))]



def _completed_target_saved_visual_failure(store, history, *, saved_versions=None, attempt_path=None):
    """Read a completed content rejection from the prior consumed Root checkpoint."""
    from .visual_candidate_revision import _normal_visual_failure_snapshot, _normal_visual_file
    job = history['job']; job_id = job.get('id')
    versions = store.draft_versions(job_id) if saved_versions is None else saved_versions
    artifacts = history.get('preserved_artifacts') or []
    effects = history.get('effects') or {}
    if (not _identifier(job_id, 16) or job.get('state') != 'blocked'
            or job.get('lease_owner') or job.get('lease_expires_at')
            or not versions or not artifacts
            or set(effects) - set(_EFFECT_TABLES)
            or effects.get('draft_versions') != len(versions) or effects.get('artifacts') != len(artifacts)
            or any(effects.get(k, 0) for k in _EFFECT_TABLES if k not in {'draft_versions', 'artifacts'})):
        raise PermissionError('completed_target_closed_saved_unpublished_rejection_required')
    prior_ref = (job.get('draft_meta') or {}).get('normal_completed_target_checkpoint_ref')
    if not isinstance(prior_ref, dict) or set(prior_ref) != {'path', 'sha256'}:
        raise PermissionError('completed_target_original_consumed_checkpoint_required')
    prior = private_read(prior_ref['path'], prior_ref['sha256'])
    directory = Path(store.path).parent / 'quality_runtime'
    if (prior.get('version') != TARGET_VERSION or prior.get('job_id') != job_id
            or prior.get('budget_seconds') != 900 or prior.get('no_publish') is not True
            or not _identifier(prior.get('nonce'), 32) or not _identifier(prior.get('origin_task_id'), 32)
            or Path(prior_ref['path']) != directory / ('generation-checkpoint-' + prior['nonce'] + '.proof.private.json')
            or not prior.get('precompiled_visual_span_ref')):
        raise PermissionError('completed_target_prior_owned_checkpoint_required')
    original, lineage = read_completed_target_candidate(store, job_id, prior['factual_step_id'], prior['target_step_id'])
    if (prior['origin_task_id'] != lineage['factual_record']['task_id']
            or any(prior.get(k) != lineage[k] for k in ('factual_source_ref', 'target_copy_ref',
                'previous_generated_proof_ref', 'prepared_ref', 'generation_source_ref', 'generation_step_id'))):
        raise ValueError('completed_target_prior_completed_native_lineage_changed')
    _validate_original_code_archive(prior['original_code_archive_ref'],
        lineage['previous_generated_proof_ref'], lineage['previous_generated_proof'])
    candidate = private_read(prior['candidate_ref']['path'], prior['candidate_ref']['sha256'], limit=4194304)
    if (versions[-1].get('title') != candidate.get('title') or versions[-1].get('body') != candidate.get('body')):
        raise ValueError('completed_target_latest_saved_draft_candidate_changed')
    patch = prior.get('deterministic_patch')
    expected_body = original['body']
    if patch is not None:
        if (not isinstance(patch, dict) or set(patch) != {'old_text', 'replacement_text'}
                or any(not isinstance(patch.get(k), str) or not 8 <= len(patch[k]) <= 4096 for k in patch)
                or patch['old_text'] == patch['replacement_text'] or expected_body.count(patch['old_text']) != 1):
            raise PermissionError('completed_target_prior_exact_authorized_span_required')
        expected_body = expected_body.replace(patch['old_text'], patch['replacement_text'], 1)
    if (candidate.get('title') != original['title'] or candidate.get('body') != expected_body
            or job.get('title') != candidate['title'] or job.get('body') != candidate['body']
            or any((job.get('draft_meta') or {}).get(k) != (candidate.get('draft_meta') or {}).get(k)
                for k in ('normal_factual_revision_ref', 'target_adaptation_ref',
                          'precompiled_visual_span_ref', 'precompiled_visual_span_required'))):
        raise ValueError('completed_target_saved_body_changed_from_consumed_candidate')
    consumed = []
    for event in history['events']:
        if event.get('event') != 'native_generation_checkpoint_consumed':continue
        detail = json.loads(event.get('detail_json') or '{}')
        if detail.get('proof_ref') == prior_ref:consumed.append(detail)
    if (len(consumed) != 1 or consumed[0].get('nonce') != prior['nonce']
            or consumed[0].get('origin_task_id') != prior['origin_task_id']
            or not _identifier(consumed[0].get('current_task_id'), 32)
            or consumed[0]['current_task_id'] == prior['origin_task_id']
            or consumed[0].get('successful_source_replayed') is not False
            or consumed[0].get('original_observation_times_rewritten') is not False):
        raise PermissionError('completed_target_prior_actual_consumed_transition_required')
    task = consumed[0]['current_task_id']
    invocation = private_read(directory / ('generation-checkpoint-' + prior['nonce'] + '.invocation.private.json'))
    if (invocation.get('version') != TARGET_VERSION or invocation.get('job_id') != job_id
            or invocation.get('task_id') != task or invocation.get('proof_sha256') != prior_ref['sha256']
            or invocation.get('no_publish') is not True or invocation.get('automatic_replay') is not False):
        raise PermissionError('completed_target_prior_registered_invocation_changed')
    current_versions = {row['id']: row for row in store.draft_versions(job_id)}
    current_artifacts = {row['id']: row for row in store.artifacts(job_id)}
    if any(current_versions.get(row['id']) != row for row in versions):
        raise ValueError('completed_target_original_saved_draft_row_changed')
    for row in artifacts:
        if current_artifacts.get(row['id']) != row:
            raise ValueError('completed_target_original_artifact_row_changed')
        _normal_visual_file({'path': row['path'], 'sha256': row['checksum']})
    snapshot = _normal_visual_failure_snapshot(store, job_id, task, versions[-1]['id'], attempt_path)
    refs = {Path(ref['path']).name: ref for ref in snapshot['registered_scope_files']}
    actual_invocation = private_read(refs['hard-factual-invocation.private.json']['path'],
        refs['hard-factual-invocation.private.json']['sha256'])
    if (actual_invocation.get('proof_sha256') != prior_ref['sha256']
            or actual_invocation.get('task_id') != task):
        raise ValueError('completed_target_original_native_rejection_checkpoint_binding_changed')
    return {'version': 'completed_native_visual_content_failure_v1', 'origin_task_id': task,
        'native_failure': snapshot, 'original_checkpoint_ref': copy.deepcopy(prior_ref),
        'saved_draft_versions': copy.deepcopy(versions)}


def _validate_completed_saved_visual_failure(store, history, *, initial):
    """Recheck sealed original rows and bytes; new revision rows may only append."""
    frozen = history['saved_visual_content_failure']
    if (not isinstance(frozen, dict) or set(frozen) != {'version', 'origin_task_id', 'native_failure',
            'original_checkpoint_ref', 'saved_draft_versions'}
            or frozen.get('version') != 'completed_native_visual_content_failure_v1'):
        raise PermissionError('completed_target_saved_visual_history_contract_required')
    actual = _completed_target_saved_visual_failure(store, history,
        saved_versions=frozen['saved_draft_versions'], attempt_path=frozen['native_failure']['attempt'])
    if actual != frozen:
        raise ValueError('completed_target_original_completed_native_rejection_changed')
    if initial:
        current = _completed_target_visual_history(store, history['job']['id'],
            private_read(frozen['original_checkpoint_ref']['path'],
                frozen['original_checkpoint_ref']['sha256'])['origin_task_id'])
        if {k: v for k, v in history.items() if k != 'saved_visual_content_failure'} != current:
            raise ValueError('completed_target_saved_visual_rejection_initial_state_changed')
    return True



def _completed_target_saved_rendered_checkpoint(store, history, code_archive_ref, *, saved_versions=None):
    """A sealed, completed render prefix may continue only its missing cover/QA tail."""
    from .visual_candidate_revision import _normal_visual_file
    job=history['job'];job_id=job['id'];versions=store.draft_versions(job_id)if saved_versions is None else saved_versions
    artifacts=history.get('preserved_artifacts')or[];effects=history.get('effects')or{}
    if (job.get('state')!='failed'or job.get('lease_owner')or job.get('lease_expires_at')or not versions or not artifacts
            or effects.get('draft_versions')!=len(versions)or effects.get('artifacts')!=len(artifacts)
            or set(effects)-set(_EFFECT_TABLES)
            or any(effects.get(k,0)for k in _EFFECT_TABLES if k not in{'draft_versions','artifacts'})):
        raise PermissionError('completed_target_closed_unpublished_rendered_prefix_required')
    consumed=[e for e in history['events']if e.get('event')=='native_generation_checkpoint_consumed']
    if not consumed:raise PermissionError('completed_target_rendered_actual_consumption_required')
    event=consumed[-1];detail=json.loads(event.get('detail_json')or'{}');prior_ref=detail.get('proof_ref')or{}
    if set(prior_ref)!={'path','sha256'}:raise PermissionError('completed_target_rendered_prior_proof_required')
    prior=private_read(prior_ref['path'],prior_ref['sha256']);nonce=prior.get('nonce');task=detail.get('current_task_id')
    directory=Path(store.path).parent/'quality_runtime'
    if (prior.get('version')!=TARGET_VERSION or prior.get('job_id')!=job_id or prior.get('no_publish')is not True
            or prior.get('budget_seconds')!=900 or not _identifier(nonce,32)or not _identifier(task,32)
            or detail.get('nonce')!=nonce or detail.get('origin_task_id')!=prior.get('origin_task_id')
            or task==prior.get('origin_task_id')or detail.get('successful_source_replayed')is not False
            or detail.get('original_observation_times_rewritten')is not False
            or Path(prior_ref['path'])!=directory/('generation-checkpoint-'+nonce+'.proof.private.json')):
        raise PermissionError('completed_target_rendered_same_consumed_scope_required')
    _validate_original_code_archive(code_archive_ref,prior_ref,prior)
    candidate=private_read(prior['candidate_ref']['path'],prior['candidate_ref']['sha256'],limit=4194304)
    original,lineage=read_completed_target_candidate(store,job_id,prior['factual_step_id'],prior['target_step_id'])
    expected_body=original['body'];patch=prior.get('deterministic_patch')
    if patch is not None:
        if (not isinstance(patch,dict)or set(patch)!={'old_text','replacement_text'}
                or any(not isinstance(patch.get(k),str)or not 8<=len(patch[k])<=4096 for k in patch)
                or patch['old_text']==patch['replacement_text']or expected_body.count(patch['old_text'])!=1):
            raise ValueError('completed_target_rendered_original_span_invalid')
        expected_body=expected_body.replace(patch['old_text'],patch['replacement_text'],1)
    if (job.get('title')!=candidate.get('title')or job.get('body')!=candidate.get('body')
            or candidate.get('title')!=original['title']or candidate.get('body')!=expected_body
            or prior.get('origin_task_id')!=lineage['factual_record']['task_id']
            or any(prior.get(k)!=lineage[k]for k in('factual_source_ref','target_copy_ref','previous_generated_proof_ref',
                'prepared_ref','generation_source_ref','generation_step_id'))):
        raise ValueError('completed_target_rendered_native_candidate_changed')
    invocation_ref={'path':str(directory/('generation-checkpoint-'+nonce+'.invocation.private.json'))}
    invocation_bytes=_review_factual_raw({'path':invocation_ref['path'],'sha256':hashlib.sha256(Path(invocation_ref['path']).read_bytes()).hexdigest()})
    invocation_ref['sha256']=hashlib.sha256(invocation_bytes).hexdigest();invocation=json.loads(invocation_bytes)
    if (invocation.get('version')!=TARGET_VERSION or invocation.get('job_id')!=job_id or invocation.get('task_id')!=task
            or invocation.get('proof_sha256')!=prior_ref['sha256']or invocation.get('no_publish')is not True
            or invocation.get('automatic_replay')is not False):
        raise PermissionError('completed_target_rendered_original_invocation_changed')
    stage=Path('/srv/hermes-worker-media/jobs')/task
    scope_refs=[{'path':str(stage/name),'sha256':hashlib.sha256((stage/name).read_bytes()).hexdigest()}for name in
        ('registered-driver-invocation.private.json','hard-factual-invocation.private.json','hard-factual-result.private.json')]
    registration,hard,terminal=[private_read(r['path'],r['sha256'])for r in scope_refs]
    if (registration.get('schema')!='root-registered-driver-invocation-v1'or registration.get('job_id')!=task
            or registration.get('no_publish')is not True or hard.get('schema')!='hard-factual-invocation-v1'
            or hard.get('task_id')!=task or hard.get('job_id')!=job_id or hard.get('budget_seconds')!=900
            or hard.get('no_publish')is not True or hard.get('automatic_replay')is not False
            or abs(hard['deadline_unix']-hard['original_invocation_started_at']-900)>0.01
            or hard.get('proof_sha256')!=prior_ref['sha256']or terminal.get('schema')!='hard-factual-result-v1'
            or terminal.get('task_id')!=task or terminal.get('job_id')!=job_id or terminal.get('state')!='failed'
            or terminal.get('returncode')!=1 or terminal.get('proof_sha256')!=prior_ref['sha256']
            or terminal.get('no_publish')is not True or terminal.get('automatic_replay')is not False
            or terminal.get('deadline_unix')!=hard['deadline_unix']
            or not hard['original_invocation_started_at']<=terminal['finished_at_unix']<hard['deadline_unix']
            or(stage/'registered-internal-delivery.private.json').exists()):
        raise PermissionError('completed_target_rendered_original_closed_failure_required')
    suffix='__generation_checkpoint_'+nonce
    def one(name,status='SUCCEEDED'):
        rows=[r for r in history['steps']if r.get('step_name')==name+suffix]
        if len(rows)!=1 or rows[0].get('status')!=status:raise PermissionError('completed_target_rendered_exact_successful_prefix_required:'+name)
        return rows[0]
    plan_step=one('prepare_current_twitter_visual_plan');image_step=one('generate_or_collect_images')
    image_check=one('validate_image_requirements');failed=one('generate_cover','FAILED_FINAL')
    geo=one('run_fact_check');risk=one('run_safety_gate');quality=one('run_quality_gate')
    for name in('validate_factual_claims','validate_content_depth','validate_target_publication_copy'):
        if (one(name).get('output')or{}).get('passed')is not True:
            raise PermissionError('completed_target_rendered_required_prefix_gate_failed')
    scoped=[r for r in history['steps']if r.get('step_name','').endswith(suffix)]
    if (not plan_step['id']<image_step['id']<image_check['id']<failed['id']
            or any(r['id']>failed['id']or(r['status']!='SUCCEEDED'and r['id']!=failed['id'])for r in scoped)
            or failed.get('reason_code')!='exception'or not failed.get('message')
            or (quality.get('output')or{}).get('passed')is not True
            or (risk.get('output')or{}).get('level')not in{'pass','review'}
            or type((geo.get('output')or{}).get('score'))not in(int,float)):
        raise PermissionError('completed_target_only_unexecuted_cover_tail_required')
    plan_ref=plan_step['output'];plan_raw=_review_factual_raw(plan_ref);plan=json.loads(plan_raw)
    generated=image_step['output'];images=generated.get('images')or[];aux=generated.get('auxiliary_artifacts')or[]
    generated_ref=generated.get('current_visual_plan_ref')or{}
    if (plan.get('version')!='current_image_text_visual_plan_v1'or plan.get('job_id')!=job_id
            or plan.get('current_task_id')!=task or plan.get('draft_source_sha256')!=digest({'title':candidate['title'],'body':candidate['body']})
            or plan.get('target_copy_ref')!=prior['target_copy_ref']
            or plan.get('caption_sha256')!=lineage['target_record']['caption_sha256']
            or set(generated_ref)not in({'path','sha256'},{'path','sha256','bytes'})
            or any(generated_ref.get(k)!=plan_ref.get(k)for k in('path','sha256'))
            or ('bytes'in generated_ref and(type(generated_ref['bytes'])is not int or generated_ref['bytes']!=len(plan_raw)))
            or len(images)!=4 or len(aux)!=2
            or {r.get('kind')for r in aux}!={'rights','render_manifest'}
            or len([r for r in images if r.get('role')=='cover'])!=1):
        raise ValueError('completed_target_rendered_same_plan_four_images_required')
    expected_dir=Path(generated.get('artifact_version_directory')or'')
    if expected_dir.parent!=Path(store.path).parent/'artifacts'/job_id:raise PermissionError('completed_target_rendered_artifacts_same_job_required')
    registered={r['path']:r for r in artifacts}
    for item in images+aux:
        row=registered.get(item['path'])
        expected_kind=('cover'if item.get('role')=='cover'else'image')if item in images else item.get('kind')
        if (not row or row.get('checksum')!=item.get('checksum')or row.get('kind')!=expected_kind
                or Path(item['path']).parent!=expected_dir):
            raise ValueError('completed_target_rendered_actual_group_changed')
        _normal_visual_file({'path':item['path'],'sha256':item['checksum']})
    maps=[r for r in artifacts if r.get('kind')=='section_image_map'and Path(r['path']).parent==expected_dir]
    if len(maps)!=1 or private_read(maps[0]['path'],maps[0]['checksum'])!=generated.get('section_image_map'):
        raise ValueError('completed_target_rendered_section_map_changed')
    from .media import MediaBridge
    MediaBridge._validate_current_generic_pool(plan,dict(job,**candidate))
    binding={k:plan.get(k)for k in('job_id','current_task_id','platform','language','production_topic','draft_source_sha256','target_copy_ref','caption_sha256')}
    for slot in plan['slots']:MediaBridge._read_current_licensed_photo(slot['background'],binding)
    for actor in plan.get('role_assets')or[]:MediaBridge._read_current_licensed_photo(actor['background'],binding)
    current_versions={r['id']:r for r in store.draft_versions(job_id)};current_artifacts={r['id']:r for r in store.artifacts(job_id)}
    if any(current_versions.get(r['id'])!=r for r in versions):raise ValueError('completed_target_rendered_original_drafts_changed')
    for row in artifacts:
        if current_artifacts.get(row['id'])!=row:raise ValueError('completed_target_rendered_original_artifact_row_changed')
        _normal_visual_file({'path':row['path'],'sha256':row['checksum']})
    native=_native_snapshot(task)if current_generation_records(Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+task),allow_absent=True)else[]
    return {'version':'saved_registered_image_group_checkpoint_v1','prior_checkpoint_ref':copy.deepcopy(prior_ref),
        'prior_code_archive_ref':copy.deepcopy(code_archive_ref),'consumed_event_id':event['id'],'origin_task_id':task,
        'invocation_ref':invocation_ref,'registered_scope_refs':scope_refs,'native':native,
        'plan_step_id':plan_step['id'],'image_step_id':image_step['id'],'image_check_step_id':image_check['id'],
        'failed_step_id':failed['id'],'geo_step_id':geo['id'],'risk_step_id':risk['id'],'quality_step_id':quality['id'],
        'saved_draft_versions':copy.deepcopy(versions)}


def _validate_completed_saved_rendered_checkpoint(store,history,*,initial):
    frozen=history['saved_rendered_checkpoint']
    if frozen.get('version')!='saved_registered_image_group_checkpoint_v1':
        raise PermissionError('completed_target_saved_rendered_contract_required')
    actual=_completed_target_saved_rendered_checkpoint(store,history,frozen['prior_code_archive_ref'],
        saved_versions=frozen['saved_draft_versions'])
    if actual!=frozen:raise ValueError('completed_target_saved_rendered_original_changed')
    if initial:
        current=_completed_target_visual_history(store,history['job']['id'],
            private_read(frozen['prior_checkpoint_ref']['path'],frozen['prior_checkpoint_ref']['sha256'])['origin_task_id'])
        if {k:v for k,v in history.items()if k!='saved_rendered_checkpoint'}!=current:
            raise ValueError('completed_target_saved_rendered_initial_changed')
    return True



def _continue_completed_saved_rendered(pipeline, store, proof, evidence_path, evidence_sha256, history, draft, owner, runner):
    """Consume the saved group and execute only the previously missing cover/quality tail."""
    checkpoint=history['saved_rendered_checkpoint'];steps={row['id']:row for row in history['steps']}
    generated=copy.deepcopy(steps[checkpoint['image_step_id']]['output'])
    meta=draft.setdefault('draft_meta',{})
    from .platform_workflow_context import load_platform_workflow_context
    from .current_strategy_refresh import refresh_current_strategy_inputs
    from .task_source_inputs import persist_task_source_inputs,refresh_task_source_contexts
    from .native_quality_resume import FACT_FIELDS
    current=store.get_job(proof['job_id']);oldbrief=copy.deepcopy(current['brief'])
    owned=pipeline._enrich_brief(current);strategy_job=copy.deepcopy(current)
    for field in('historical_feedback','platform_historical_feedback','topic_historical_feedback','cluster_memory','legacy_feedback_reference'):
        strategy_job['brief'][field]=copy.deepcopy(owned[field])
    contexts={p:load_platform_workflow_context(p,plan=strategy_job['brief'])for p in current['platforms']}
    refreshed=refresh_current_strategy_inputs(store,pipeline.config,strategy_job,contexts,runner)
    prepared=refreshed['brief']
    if any(prepared.get(k)!=oldbrief.get(k)for k in FACT_FIELDS):
        raise ValueError('completed_target_rendered_refresh_original_facts_changed')
    for platform,brief in refreshed['platform_briefs'].items():
        old=oldbrief['platform_workflow_inputs'][platform]
        if any(brief.get(k)!=old.get(k)for k in FACT_FIELDS):
            raise ValueError('completed_target_rendered_refresh_scoped_facts_changed')
    audit=copy.deepcopy(oldbrief['source_collection_audit']);audit['current_strategy_refresh_audit']=refreshed['strategy_refresh_audit']
    prepared['source_collection_audit']=audit
    for value in refreshed['platform_briefs'].values():value['source_collection_audit']=copy.deepcopy(audit)
    current=persist_task_source_inputs(store,current,owner,prepared);contexts=refresh_task_source_contexts(contexts,prepared)
    scoped={p:pipeline._bind_platform_source_inputs(proof['job_id'],brief,p,contexts[p],owner)
        for p,brief in refreshed['platform_briefs'].items()}
    prepared['platform_workflow_inputs']=copy.deepcopy(scoped)
    current=persist_task_source_inputs(store,current,owner,prepared)
    if len(scoped)!=1:raise PermissionError('completed_target_rendered_single_platform_required')
    observed=next(iter(scoped.values()))
    for field in('account_analysis','same_lane_intelligence','strategy_evidence','strategy_evidence_gate','strategy_observation_ref',
        'viral_collection','viral_breakdown','hot_work_parameter_pack','platform_intelligence_constraints','historical_feedback',
        'platform_historical_feedback','topic_historical_feedback','cluster_memory','legacy_feedback_reference'):
        if field in observed:meta[field]=copy.deepcopy(observed[field])
    for name in('native_quality','platform_quality_gates','final_quality_evidence'):meta.pop(name,None)
    meta['normal_completed_target_checkpoint_ref']={'path':str(evidence_path),'sha256':evidence_sha256}
    meta['current_visual_plan_ref']=copy.deepcopy(steps[checkpoint['plan_step_id']]['output'])
    meta['cover_design']=copy.deepcopy(generated['measured_cover_design'])
    geo=copy.deepcopy(steps[checkpoint['geo_step_id']]['output'])
    risk=copy.deepcopy(steps[checkpoint['risk_step_id']]['output'])
    meta.update(geo_score=geo['score'],geo_details=geo,quality_gate=copy.deepcopy(steps[checkpoint['quality_step_id']]['output']))
    current=store.get_job(proof['job_id'])
    cover=runner.run('generate_cover',
        lambda:pipeline._reuse_registered_cover(proof['job_id'],generated,dict(current,**draft)),
        depends_on=['validate_image_requirements'],require_output=True)
    if not any(item.get('role')=='cover'and item.get('path')==cover.get('path')and item.get('checksum')==cover.get('checksum')for item in generated['images']):
        raise ValueError('completed_target_reused_cover_not_original_rendered_group')
    store.save_draft(proof['job_id'],draft['title'],draft['body'],'unreviewed',risk,draft.get('prompt_version',''),meta)
    return pipeline.continue_rendered_candidate(proof['job_id'],owner,runner,generated,{})



def binding_step_name(store, job_id, platform):
    grant = getattr(store, '_native_stage_resume_grant', None)
    if grant is None:return None
    if grant.get('binding_mode') != 'saved_rendered_checkpoint':return None
    grant = require_active_stage_grant(store, job_id, store.get_job(job_id).get('lease_owner'))
    if (grant.get('proof') or {}).get('version') != TARGET_VERSION:return None
    if platform not in store.get_job(job_id)['platforms'] or not _identifier(grant.get('nonce'), 32):
        raise PermissionError('generation_checkpoint_binding_actual_platform_required')
    return 'bind_rendered_artifact_sources__generation_checkpoint_' + grant['nonce']


def record_binding_reference(store, job_id, platform, manifest_ref):
    step = binding_step_name(store, job_id, platform)
    if step is None:return None
    grant = require_active_stage_grant(store, job_id, store.get_job(job_id).get('lease_owner'))
    rows = [r for r in store.workflow_steps(job_id) if r.get('step_name') == step and r.get('platform') == platform]
    if len(rows) != 1 or rows[0].get('status') != 'SUCCEEDED' or rows[0].get('output') != {'artifact_manifest': manifest_ref}:
        raise ValueError('generation_checkpoint_actual_binding_step_required')
    manifest = private_read(manifest_ref['path'], manifest_ref['sha256'])
    if (manifest.get('job_id') != job_id or manifest.get('platform') != platform
            or manifest.get('draft_version_id') != store.draft_versions(job_id)[-1]['id']):
        raise ValueError('generation_checkpoint_current_draft_binding_required')
    record = {'version': TARGET_VERSION, 'job_id': job_id, 'platform': platform, 'task_id': grant['task_id'],
        'nonce': grant['nonce'], 'row_id': rows[0]['id'], 'row_sha256': digest(rows[0]), 'manifest_ref': manifest_ref,
        'proof_ref': copy.deepcopy(grant['proof_ref']), 'no_publish': True}
    path = Path(grant['proof_ref']['path']).with_name('generation-checkpoint-' + grant['nonce'] + '.binding-' + platform + '.private.json')
    ref = write_once(path, record)
    store.record_event(job_id, 'current_generation_checkpoint_binding',
        {'platform': platform, 'binding_receipt_ref': ref, 'nonce': grant['nonce']})
    return ref


def current_binding(store, job_id, platform):
    current_job=store.get_job(job_id)
    current_ref=(current_job.get('draft_meta')or{}).get('normal_completed_target_checkpoint_ref')
    if not isinstance(current_ref,dict)or set(current_ref)!={'path','sha256'}:return None
    current_proof=private_read(current_ref['path'],current_ref['sha256'])
    if current_proof.get('version')!=TARGET_VERSION:return None
    current_history=private_read(current_proof['history_ref']['path'],current_proof['history_ref']['sha256'],limit=16777216)
    if not current_history.get('saved_rendered_checkpoint'):return None
    kinds = {'current_generation_checkpoint_binding', 'current_rendered_quality_binding', 'current_visual_revision_binding'}
    candidates = [e for e in store.events(job_id) if e.get('event') in kinds
        and json.loads(e.get('detail_json') or '{}').get('platform') == platform]
    if not candidates or candidates[-1].get('event') != 'current_generation_checkpoint_binding':
        raise PermissionError('generation_checkpoint_declared_binding_missing')
    ref = json.loads(candidates[-1]['detail_json'])['binding_receipt_ref']
    record = private_read(ref['path'], ref['sha256'])
    if record.get('proof_ref')!=current_ref:raise ValueError('generation_checkpoint_binding_other_current_proof')
    proof_ref = record.get('proof_ref') or {};proof = private_read(proof_ref['path'], proof_ref['sha256'])
    directory = Path(store.path).parent / 'quality_runtime'
    if (record.get('version') != TARGET_VERSION or proof.get('version') != TARGET_VERSION
            or record.get('job_id') != job_id or record.get('platform') != platform
            or record.get('no_publish') is not True or record.get('nonce') != proof.get('nonce')
            or Path(proof_ref['path']) != directory / ('generation-checkpoint-' + str(proof.get('nonce')) + '.proof.private.json')
            or Path(ref['path']) != directory / ('generation-checkpoint-' + str(proof.get('nonce')) + '.binding-' + platform + '.private.json')):
        raise PermissionError('generation_checkpoint_binding_identity_changed')
    validate_completed_target_checkpoint(store, proof, initial=False)
    invocation = private_read(directory / ('generation-checkpoint-' + proof['nonce'] + '.invocation.private.json'))
    if (invocation.get('version') != TARGET_VERSION or invocation.get('job_id') != job_id
            or invocation.get('task_id') != record.get('task_id') or invocation.get('proof_sha256') != proof_ref['sha256']
            or invocation.get('no_publish') is not True or invocation.get('automatic_replay') is not False
            or not any(e.get('event') == 'native_generation_checkpoint_consumed'
                and json.loads(e.get('detail_json') or '{}').get('proof_ref') == proof_ref
                and json.loads(e.get('detail_json') or '{}').get('current_task_id') == record['task_id'] for e in store.events(job_id))):
        raise PermissionError('generation_checkpoint_current_binding_consumption_required')
    rows = [r for r in store.workflow_steps(job_id) if r.get('id') == record.get('row_id')]
    if (len(rows) != 1 or rows[0].get('status') != 'SUCCEEDED' or rows[0].get('platform') != platform
            or rows[0].get('step_name') != 'bind_rendered_artifact_sources__generation_checkpoint_' + proof['nonce']
            or digest(rows[0]) != record.get('row_sha256') or rows[0].get('output') != {'artifact_manifest': record.get('manifest_ref')}):
        raise ValueError('generation_checkpoint_bound_workflow_row_changed')
    manifest = private_read(record['manifest_ref']['path'], record['manifest_ref']['sha256'])
    if (manifest.get('job_id') != job_id or manifest.get('platform') != platform
            or manifest.get('draft_version_id') != store.draft_versions(job_id)[-1]['id']):
        raise ValueError('generation_checkpoint_bound_current_draft_changed')
    from .intelligence import prepare_generation_strategy_inputs
    from .task_source_inputs import project_task_source_brief
    job = store.get_job(job_id)
    prepare_generation_strategy_inputs(job['topic'], project_task_source_brief(job['brief'], platform))
    return {'row': rows[0], 'manifest_ref': record['manifest_ref'], 'binding_receipt_ref': ref}



# Explicit new caption work. Historical fact readers do not renew old authority.
CAPTION_VERSION = 'normal_caption_revision_v1'
_CAPTION_SEAL = object()
_CAPTION_ACTIVE = {}


def _caption_ref(value):
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256'}
            or not isinstance(value['path'], str) or not Path(value['path']).is_absolute()
            or not _identifier(value['sha256'], 64)):
        raise ValueError('caption_revision_exact_private_reference_required')
    return private_read(value['path'], value['sha256'], limit=16777216)


def _caption_rules(parent, store):
    from .platform_workflow_context import load_platform_workflow_context
    from .visual_policy_gate import validate_content_policy_inputs
    contexts = {p: load_platform_workflow_context(p, plan=parent['brief']) for p in parent['platforms']}
    checked = validate_content_policy_inputs(parent, contexts, store=store)
    if checked.get('passed') is not True:
        raise PermissionError('caption_revision_current_content_policy_blocked')
    return checked


def _caption_parent(store, parent_id, draft_id):
    """Read an immutable successful content version, never an analytics report."""
    from .target_adaptation import read_target_adaptation
    parent = store.get_job(parent_id)
    versions = store.draft_versions(parent_id)
    if (not _identifier(parent_id, 16) or type(draft_id) is not int
            or parent.get('state') not in {'review_required', 'approved', 'delivered'}
            or parent.get('lease_owner') or parent.get('lease_expires_at') or parent.get('platforms') != ['twitter']
            or not versions or versions[-1]['id'] != draft_id
            or not parent.get('title') or not parent.get('body')):
        raise PermissionError('caption_revision_successful_content_parent_required')
    latest = versions[-1]
    if any(latest.get(k) != parent.get(k) for k in ('title', 'body', 'draft_meta')):
        raise ValueError('caption_revision_parent_draft_changed')
    meta = parent.get('draft_meta') or {}
    historical = parent
    if meta.get('normal_completed_target_checkpoint_ref'):
        source = _caption_ref(meta['normal_completed_target_checkpoint_ref'])
        archive = None
        quality = meta.get('rendered_quality_revision')
        if quality:
            qproof = _caption_ref(quality['proof_ref'])
            qhistory = _caption_ref(qproof['history_ref'])
            validate_saved = __import__(__package__ + '.native_quality_resume', fromlist=['validate_saved_candidate']).validate_saved_candidate
            validate_saved(qhistory, parent, versions, store.artifacts(parent_id), initial=False)
            archive = qhistory.get('original_checkpoint_code_archive_ref')
        _, derived = validate_completed_target_checkpoint(store, source, initial=False, original_code_archive_ref=archive)
        if any(derived.get(k) != parent.get(k) for k in ('title', 'body')):
            raise ValueError('caption_revision_historical_content_derivation_changed')
        original, _ = read_completed_target_candidate(store, parent_id, source['factual_step_id'], source['target_step_id'])
        historical = dict(parent, **original)
    target = read_target_adaptation(historical, 'twitter')
    outputs = [r for r in store.platform_outputs(parent_id) if r.get('draft_version_id') == draft_id]
    if (not outputs or len({r.get('content_revision') for r in outputs}) != 1
            or len([r for r in outputs if r.get('role') == 'copy']) != 1
            or not all((r.get('quality_evidence') or {}).get('passed') is True for r in outputs)):
        raise PermissionError('caption_revision_historical_qualified_outputs_required')
    steps = store.workflow_steps(parent_id)
    def qualified_output(row):
        value = row.get('output') or {}
        return value.get('passed') is True or (set(value) == {'twitter'} and value['twitter'].get('passed') is True)
    if any(not any(r.get('status') == 'SUCCEEDED' and r.get('step_name', '').split('__', 1)[0] == name
                   and qualified_output(r) for r in steps)
           for name in ('run_native_mandatory_quality', 'run_final_platform_quality_gate')):
        raise PermissionError('caption_revision_historical_complete_quality_required')
    artifacts = store.artifacts(parent_id)
    selected = []
    for row in outputs:
        if row.get('role') in {'copy', 'manifest'}:
            continue
        matches = [a for a in artifacts if a.get('id') == row.get('artifact_id')]
        if len(matches) != 1:
            raise ValueError('caption_revision_original_artifact_identity_changed')
        artifact = matches[0]
        path = Path(artifact['path'])
        if (path.is_symlink() or any(q.is_symlink() for q in path.parents)
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get('checksum')):
            raise ValueError('caption_revision_original_artifact_bytes_changed')
        selected.append(copy.deepcopy(artifact))
    roles = [r.get('role') for r in outputs]
    if roles.count('cover') != 1 or not 1 <= roles.count('cover') + roles.count('image') <= 4:
        raise PermissionError('caption_revision_complete_image_text_parent_required')
    plan_ref = meta.get('current_visual_plan_ref')
    plan = _caption_ref(plan_ref)
    if (plan.get('job_id') != parent_id or plan.get('platform') != 'twitter'
            or plan.get('version') != 'current_image_text_visual_plan_v1'
            or plan.get('draft_source_sha256') != digest({'title': parent['title'], 'body': parent['body']})):
        raise ValueError('caption_revision_historical_visual_source_changed')
    return {'parent': parent, 'draft': latest, 'outputs': outputs, 'artifacts': selected,
            'steps': steps, 'events': store.events(parent_id), 'historical_source': historical,
            'old_target': target, 'plan_ref': plan_ref, 'plan': plan}


def _caption_code_pins(pins):
    required = {str(Path(__file__).with_name(name)) for name in
                ('native_stage_resume.py', 'target_adaptation.py', 'pipeline.py', 'media.py')}
    required.add('/srv/hermes-worker/root_registered_native_driver.py')
    if not isinstance(pins, list) or len(pins) != len(required) or {p.get('path') for p in pins} != required:
        raise PermissionError('caption_revision_exact_code_pins_required')
    for pin in pins:
        path = Path(pin['path'])
        if (not _identifier(pin.get('sha256'), 64) or path.is_symlink()
                or any(q.is_symlink() for q in path.parents)
                or hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']):
            raise ValueError('caption_revision_current_code_changed')


def prepare_caption_revision(store, parent_job_id, parent_draft_id, intent, instruction, nonce, directory, code_pins):
    """Root preparation only. Does not create a child or call a model."""
    directory = Path(directory)
    if (directory != Path(store.path).parent / 'quality_runtime' or not _identifier(nonce, 32)
            or not isinstance(intent, str) or not 8 <= len(intent.strip()) <= 512
            or not isinstance(instruction, str) or not 8 <= len(instruction.strip()) <= 2048):
        raise ValueError('caption_revision_explicit_bounded_intent_required')
    _caption_code_pins(code_pins)
    history = _caption_parent(store, parent_job_id, parent_draft_id)
    rules = _caption_rules(history['parent'], store)
    intent_name = digest({'parent': parent_job_id, 'intent': intent})
    if (directory / ('caption-intent-' + intent_name + '.started.private.json')).exists():
        raise PermissionError('caption_revision_existing_intent_inspect_only')
    proof = {'version': CAPTION_VERSION, 'parent_job_id': parent_job_id, 'parent_draft_id': parent_draft_id,
             'nonce': nonce, 'intent': intent, 'instruction': instruction, 'budget_seconds': 900,
             'no_publish': True, 'strategy_refresh': True,
             'origin_task_id': history['old_target']['adaptation_session_ref']['task_id'],
             'history_ref': write_once(directory / ('caption-revision-' + nonce + '.history.private.json'), history),
             'current_rules': rules, 'code_pins': code_pins}
    proof_ref = write_once(directory / ('caption-revision-' + nonce + '.proof.private.json'), proof)
    # Validate the original pixels/licence/source chain before any child or model.
    from .media import MediaBridge
    parent_view = copy.deepcopy(history['parent'])
    parent_view['_caption_revision_historical_ref'] = proof_ref
    MediaBridge._current_image_text_plan(parent_view)
    return proof_ref


def validate_caption_revision(store, proof_ref, *, child_id=None, live=False, historical=False):
    proof = _caption_ref(proof_ref)
    expected = {'version', 'parent_job_id', 'parent_draft_id', 'nonce', 'intent', 'instruction',
                'budget_seconds', 'no_publish', 'strategy_refresh', 'origin_task_id', 'history_ref', 'current_rules', 'code_pins'}
    root = Path(store.path).parent / 'quality_runtime'
    if (set(proof) != expected or proof.get('version') != CAPTION_VERSION
            or proof.get('no_publish') is not True or proof.get('strategy_refresh') is not True
            or type(proof.get('budget_seconds')) is not int or proof.get('budget_seconds') != 900
            or not _identifier(proof.get('nonce'), 32)
            or not _identifier(proof.get('origin_task_id'), 32)
            or not isinstance(proof.get('intent'), str) or not 8 <= len(proof['intent'].strip()) <= 512
            or not isinstance(proof.get('instruction'), str) or not 8 <= len(proof['instruction'].strip()) <= 2048
            or Path(proof_ref['path']) != root / ('caption-revision-' + str(proof.get('nonce')) + '.proof.private.json')):
        raise PermissionError('caption_revision_exact_proof_required')
    history = _caption_ref(proof['history_ref'])
    actual = _caption_parent(store, proof['parent_job_id'], proof['parent_draft_id'])
    if actual != history or proof['origin_task_id'] != history['old_target']['adaptation_session_ref']['task_id']:
        raise ValueError('caption_revision_readonly_parent_history_changed')
    if historical and live:
        raise PermissionError('caption_revision_historical_read_cannot_authorize_execution')
    if not historical:
        _caption_code_pins(proof['code_pins'])
        if _caption_rules(actual['parent'], store) != proof['current_rules']:
            raise ValueError('caption_revision_current_rules_changed')
    if child_id is not None:
        child = store.get_job(child_id)
        ref = (child.get('brief') or {}).get('caption_revision_ref')
        events = [json.loads(r.get('detail_json') or '{}') for r in store.events(child_id)
                  if r.get('event') == 'caption_revision_created']
        if (ref != proof_ref or len(events) != 1 or events[0].get('proof_ref') != proof_ref
                or events[0].get('parent_job_id') != proof['parent_job_id']
                or child_id == proof['parent_job_id'] or child.get('platforms') != actual['parent']['platforms']
                or child.get('title') not in ('', actual['parent']['title'])
                or child.get('body') not in ('', actual['parent']['body'])):
            raise ValueError('caption_revision_actual_child_lineage_required')
        invocation = private_read(root / ('caption-revision-' + proof['nonce'] + '.invocation.private.json'))
        if (invocation.get('version') != CAPTION_VERSION or invocation.get('job_id') != child_id
                or invocation.get('proof_ref') != proof_ref or invocation.get('proof_sha256') != proof_ref['sha256']
                or invocation.get('no_publish') is not True or invocation.get('automatic_replay') is not False
                or not _identifier(invocation.get('task_id'), 32) or invocation['task_id'] == proof['origin_task_id']
                or events[0].get('task_id') != invocation['task_id']):
            raise PermissionError('caption_revision_consumed_current_scope_required')
        if child.get('state') == 'generating':
            from .native_quality_runner import current_active_role
            from datetime import datetime, timezone
            _, current, _ = current_active_role(0)
            end = invocation.get('deadline_unix')
            expiry = child.get('lease_expires_at')
            if (current != invocation['task_id'] or type(end) not in (int, float) or not math.isfinite(end)
                    or time.time() >= end or not child.get('lease_owner') or not expiry
                    or datetime.fromisoformat(expiry.replace('Z', '+00:00')) <= datetime.now(timezone.utc)):
                raise PermissionError('caption_revision_current_role_and_deadline_required')
        if live:
            grant = _CAPTION_ACTIVE.get((id(store), child_id))
            if (not grant or grant.get('_seal') is not _CAPTION_SEAL or grant['pid'] != os.getpid()
                    or grant['thread'] != threading.get_ident() or grant['deadline'] <= time.monotonic()
                    or child.get('state') != 'generating' or child.get('lease_owner') != grant['owner']):
                raise PermissionError('caption_revision_live_lease_required')
    return proof, actual


def caption_revision_source(job):
    ref = (job.get('draft_meta') or {}).get('caption_revision_source_ref')
    store = _completed_target_readonly_store()
    proof, history = validate_caption_revision(store, ref, child_id=job['id'], historical=job.get('state') != 'generating')
    if job.get('title') != history['parent']['title'] or job.get('body') != history['parent']['body']:
        raise ValueError('caption_revision_only_caption_change_allowed')
    return copy.deepcopy(history['old_target']['source_generation_ref']), copy.deepcopy(history)


def caption_revision_historical_target(job):
    ref = job.get('_caption_revision_historical_ref')
    store = _completed_target_readonly_store()
    _, history = validate_caption_revision(store, ref, historical=True)
    parent = history['parent']
    if (job.get('id') != parent['id'] or job.get('title') != parent['title'] or job.get('body') != parent['body']
            or job.get('draft_meta') != parent.get('draft_meta')):
        raise ValueError('caption_revision_historical_parent_projection_changed')
    return copy.deepcopy(history['old_target'])


def caption_revision_visual_binding(job):
    ref = (job.get('draft_meta') or {}).get('current_visual_plan_ref')
    wrapper = _caption_ref(ref)
    required = {'version', 'job_id', 'current_task_id', 'proof_ref', 'parent_job_id', 'parent_draft_id',
                'original_plan_ref', 'target_copy_ref', 'caption_sha256', 'pixels', 'new_source_capture', 'new_pixel_render'}
    if (set(wrapper) != required or wrapper.get('version') != 'caption_revision_inherited_visual_binding_v1'
            or wrapper.get('job_id') != job.get('id') or wrapper.get('new_source_capture') is not False
            or wrapper.get('new_pixel_render') is not False):
        raise ValueError('caption_revision_inherited_visual_exact_binding_required')
    store = _completed_target_readonly_store()
    proof, history = validate_caption_revision(store, wrapper['proof_ref'], child_id=job['id'], historical=job.get('state') != 'generating')
    invocation = private_read(Path(wrapper['proof_ref']['path']).with_name('caption-revision-' + proof['nonce'] + '.invocation.private.json'))
    if (wrapper['parent_job_id'] != proof['parent_job_id'] or wrapper['parent_draft_id'] != proof['parent_draft_id']
            or wrapper['current_task_id'] != invocation['task_id']
            or wrapper['original_plan_ref'] != history['plan_ref']
            or wrapper['proof_ref'] != (job.get('draft_meta') or {}).get('caption_revision_source_ref')):
        raise ValueError('caption_revision_inherited_visual_parent_changed')
    from .target_adaptation import read_target_adaptation
    target = read_target_adaptation(job, 'twitter')
    if wrapper['target_copy_ref'] != target['target_copy_ref'] or wrapper['caption_sha256'] != target['caption_sha256']:
        raise ValueError('caption_revision_inherited_visual_current_caption_changed')
    originals = {a['path']: a for a in history['artifacts'] if a.get('kind') in {'cover', 'image'}}
    if set(wrapper['pixels']) != set(originals):
        raise ValueError('caption_revision_inherited_visual_complete_pixels_required')
    root = (Path(store.path).parent / 'artifacts' / job['id']).resolve()
    for path, bound in wrapper['pixels'].items():
        pixel = Path(bound.get('path', ''))
        if (set(bound) != {'path', 'checksum', 'kind'} or bound['checksum'] != originals[path]['checksum']
                or bound['kind'] != originals[path]['kind'] or pixel.is_symlink()
                or any(p.is_symlink() for p in pixel.parents) or not pixel.resolve().is_relative_to(root)
                or hashlib.sha256(pixel.read_bytes()).hexdigest() != bound['checksum']):
            raise ValueError('caption_revision_inherited_pixel_or_owner_changed')
    historical = copy.deepcopy(history['parent'])
    historical['_caption_revision_historical_ref'] = copy.deepcopy(wrapper['proof_ref'])
    return wrapper, historical, ref


def caption_revision_ancestor(store, job):
    ref = (job.get('brief') or {}).get('caption_revision_ref')
    if ref is None:
        return set()
    proof, _ = validate_caption_revision(store, ref, child_id=job['id'])
    return {proof['parent_job_id']}


def _caption_execution_window(home, task, *, now=None):
    """Original registered Role is 1800s; this new editing action is bounded to its first 900s."""
    marker = private_read(Path('/srv/hermes-worker-media/jobs') / task / 'registered-driver-invocation.private.json')
    scope_remaining = registered_current_scope(home, task)
    now = time.time() if now is None else now
    started = marker.get('started_at_unix');outer = marker.get('deadline_unix')
    if (marker.get('schema') != 'root-registered-driver-invocation-v1' or marker.get('job_id') != task
            or marker.get('no_publish') is not True or marker.get('outer_model_api_calls') != 0
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in (now, started, outer))
            or not 0 < outer - started <= 1800 or started > now):
        raise PermissionError('caption_revision_original_registered_window_required')
    seconds = min(scope_remaining, outer - now, started + 900 - now)
    if seconds <= 0:
        raise PermissionError('caption_revision_original_900_action_expired')
    return seconds


def caption_revision_stage_budget(store, job_id, maximum):
    """Clamp each new model operation to the already sealed action window."""
    if type(maximum) not in (int, float) or not math.isfinite(maximum) or maximum <= 0:
        raise PermissionError('caption_revision_stage_budget_invalid')
    job = store.get_job(job_id)
    ref = (job.get('brief') or {}).get('caption_revision_ref')
    validate_caption_revision(store, ref, child_id=job_id, live=True)
    grant = _CAPTION_ACTIVE[(id(store), job_id)]
    from .native_quality_runner import current_active_role
    home, task, _ = current_active_role(0)
    if task != grant['task']:
        raise PermissionError('caption_revision_stage_current_task_changed')
    original_remaining = _caption_execution_window(home, task)
    remaining = min(grant['deadline'] - time.monotonic(), original_remaining)
    seconds = math.floor(min(maximum, remaining))
    if seconds <= 0:
        raise PermissionError('caption_revision_original_900_action_expired')
    return seconds


def execute_caption_revision(pipeline, proof_path, proof_sha256):
    from .native_quality_runner import current_active_role
    from .workflow_runtime import WorkflowStepRunner, strict_workflow_lock
    ref = {'path': str(proof_path), 'sha256': proof_sha256}
    store = pipeline.store
    proof, history = validate_caption_revision(store, ref)
    home, task, route = current_active_role(120)
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH') != '0':
        raise PermissionError('caption_revision_no_publication_required')
    original_task = history['old_target']['adaptation_session_ref']['task_id']
    if task == original_task or current_generation_records(home, allow_absent=True):
        raise PermissionError('caption_revision_new_model_free_scope_required')
    cfg = pipeline.generator.config
    if (cfg.get('provider') != 'hermes-cli' or cfg.get('hermes_provider') != route['provider']
            or cfg.get('hermes_model') != route['model'] or cfg.get('allow_fallback') is not False):
        raise PermissionError('caption_revision_current_dynamic_role_required')
    remaining = _caption_execution_window(home, task)
    if remaining < 180:
        raise PermissionError('caption_revision_original_budget_insufficient')
    parent = history['parent'];owner = pipeline._worker_id()
    deadline = time.monotonic() + remaining
    marker = Path(proof_path).with_name('caption-revision-' + proof['nonce'] + '.invocation.private.json')
    if marker.exists():
        raise PermissionError('caption_revision_started_intent_inspect_only')
    with strict_workflow_lock(store, owner, 'caption_' + proof['nonce'], remaining, pipeline.strict_serial):
        proof, history = validate_caption_revision(store, ref)
        from .media import MediaBridge
        parent_view = copy.deepcopy(history['parent'])
        parent_view['_caption_revision_historical_ref'] = ref
        MediaBridge._current_image_text_plan(parent_view)
        intent_name = digest({'parent': proof['parent_job_id'], 'intent': proof['intent']})
        write_once(Path(proof_path).parent / ('caption-intent-' + intent_name + '.started.private.json'),
                   {'version': CAPTION_VERSION, 'task_id': task, 'proof_ref': ref, 'no_publish': True})
        brief = copy.deepcopy(parent['brief'])
        brief.update(caption_revision_ref=ref, publication_authorized=False, no_publish=True)
        brief.pop('quality_revision', None)
        child = store.create_job(parent['topic'], parent['platforms'], brief, parent.get('profile') or 'default', '')
        identity = {'proof_ref': ref, 'parent_job_id': parent['id'], 'parent_draft_id': proof['parent_draft_id'],
                    'child_job_id': child['id'], 'task_id': task, 'intent': proof['intent'], 'nonce': proof['nonce']}
        store.record_event(child['id'], 'caption_revision_created', identity)
        write_once(marker, {'version': CAPTION_VERSION, 'task_id': task, 'job_id': child['id'],
                           'proof_sha256': proof_sha256, 'proof_ref': ref, 'no_publish': True,
                           'deadline_unix': time.time() + max(0, deadline - time.monotonic()), 'automatic_replay': False})
        # Parent rows, including events and ACKs, remain immutable.
        if not store.claim(child['id'], {'created'}, owner, max(1, math.floor(deadline - time.monotonic())), 'generating'):
            raise PermissionError('caption_revision_child_claim_failed_inspect_only')
        grant = {'_seal': _CAPTION_SEAL, 'pid': os.getpid(), 'thread': threading.get_ident(),
                 'owner': owner, 'deadline': deadline, 'task': task, 'proof_ref': ref}
        _CAPTION_ACTIVE[(id(store), child['id'])] = grant
        runner = WorkflowStepRunner(store, 'wf_' + child['id'], child['id'], notifier=pipeline.notifier)
        try:
            return pipeline.continue_caption_revision(child['id'], owner, runner, ref, history)
        except Exception as error:
            if store.get_job(child['id']).get('lease_owner') == owner:
                store.release_claim(child['id'], owner, 'failed', 'caption_revision_failed', type(error).__name__)
            raise
        finally:
            _CAPTION_ACTIVE.pop((id(store), child['id']), None)
