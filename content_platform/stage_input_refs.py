"""Immutable native stage evidence bound to the existing Store and run contract."""
import hashlib
import json
import os
from pathlib import Path
import re

from .run_contract import BOUNDS, DEFAULT_RULEBOOK, RunContractError, bound_stage_payload, validate_run_contract

MARKER = 'native_stage_ref_v1'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def has_stage_refs(payload):
    return isinstance(payload, dict) and any(isinstance(value, dict) and MARKER in value for value in payload.values())


def evidence_path(store, job_id, stage, payload_sha):
    if not re.fullmatch(r'[0-9a-f]{16}', str(job_id)) or not re.fullmatch(r'[a-z_]+', str(stage)):
        raise RunContractError('stage_reference_identity_invalid')
    if not re.fullmatch(r'[0-9a-f]{64}', str(payload_sha)):
        raise RunContractError('stage_reference_digest_invalid')
    database = Path(store.path)
    if database.is_symlink() or not database.is_file():
        raise RunContractError('trusted_stage_store_required')
    root = database.resolve().parent
    path = root / 'runtime' / 'stage_inputs' / job_id / (stage + '-' + payload_sha + '.json')
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(root)):
        raise RunContractError('stage_reference_symlink_forbidden')
    return path


def summary(field, value):
    if field == 'content_blueprint' and isinstance(value, dict):
        keys = ('platform', 'content_form', 'audience', 'language', 'content_goal', 'user_pain', 'scene_count')
        result = {key: value[key] for key in keys if key in value}
        observations = value.get('source_observations')
        if isinstance(observations, list):
            result['source_observations'] = [{key: row[key] for key in ('content_id', 'title', 'url', 'raw_response_hash') if key in row}
                                             for row in observations if isinstance(row, dict)]
        return result
    return {}


def bind_stage_payload(store, job_id, contract, stage, payload, *, lease_owner=None, rulebook_path=DEFAULT_RULEBOOK, force_reference=False):
    validation = validate_run_contract(contract, rulebook_path=rulebook_path)
    if not validation['passed']:
        raise RunContractError('invalid stage evidence contract:' + ','.join(validation['failures']))
    allowed = set((contract.get('stage_fields') or {}).get(stage) or [])
    if not allowed or set(payload) - allowed:
        raise RunContractError('unknown stage evidence fields')
    limit = int((contract.get('bounds') or {}).get('stage_payload_bytes') or BOUNDS['stage_payload_bytes'])
    if limit > BOUNDS['stage_payload_bytes']:
        raise RunContractError('stage evidence cannot raise native payload limit')
    if len(encoded(payload)) <= limit and not force_reference:
        return bound_stage_payload(contract, stage, payload, rulebook_path=rulebook_path)
    job = store.get_job(job_id)
    if job.get('id') != job_id or (lease_owner is not None and
            (job.get('state') != 'generating' or job.get('lease_owner') != lease_owner)):
        raise RunContractError('stage evidence job or lease changed')
    raw = encoded(payload)
    payload_sha = hashlib.sha256(raw).hexdigest()
    manifest = {'version': 1, 'job_id': job_id, 'stage': stage,
        'contract_sha256': digest(contract), 'payload_sha256': payload_sha, 'bytes': len(raw),
        'source_audit_sha256': digest((job.get('brief') or {}).get('source_collection_audit') or {}),
        'field_sha256': {field: digest(value) for field, value in payload.items()}}
    result = json.loads(raw)
    for field in sorted(payload, key=lambda name: len(encoded(payload[name])), reverse=True):
        ref = {key: manifest[key] for key in ('job_id', 'stage', 'contract_sha256', 'payload_sha256')}
        ref.update(field=field, field_sha256=manifest['field_sha256'][field])
        result[field] = {MARKER: ref, 'summary': summary(field, payload[field])}
        if len(encoded(result)) <= limit:
            break
    bounded = bound_stage_payload(contract, stage, result, rulebook_path=rulebook_path)
    path = evidence_path(store, job_id, stage, payload_sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != payload_sha:
            raise RunContractError('immutable stage evidence already differs')
    else:
        with path.open('xb') as stream:
            os.chmod(path, 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    store.record_event(job_id, 'native_stage_inputs_bound', manifest)
    return bounded


def resolve_stage_payload(store, job_id, contract, stage, payload):
    if not has_stage_refs(payload):
        return payload
    if store is None or not job_id:
        raise RunContractError('trusted stage Store and current job required')
    events = [json.loads(row['detail_json']) for row in store.events(job_id)
              if row.get('event') == 'native_stage_inputs_bound']
    source_audit_sha = digest((store.get_job(job_id).get('brief') or {}).get('source_collection_audit') or {})
    resolved = json.loads(encoded(payload))
    cache = {}
    for field, value in payload.items():
        if not isinstance(value, dict) or MARKER not in value:
            continue
        if set(value) != {MARKER, 'summary'}:
            raise RunContractError('stage reference wrapper fields changed')
        ref = value[MARKER]
        if (not isinstance(ref, dict) or set(ref) != {'job_id', 'stage', 'contract_sha256', 'payload_sha256', 'field', 'field_sha256'}
                or ref['job_id'] != job_id or ref['stage'] != stage or ref['field'] != field
                or ref['contract_sha256'] != digest(contract)):
            raise RunContractError('stage reference owner or contract mismatch')
        records = [row for row in events if row.get('job_id') == job_id and row.get('stage') == stage
                   and row.get('contract_sha256') == ref['contract_sha256']
                   and row.get('payload_sha256') == ref['payload_sha256']
                   and row.get('source_audit_sha256') == source_audit_sha
                   and (row.get('field_sha256') or {}).get(field) == ref['field_sha256']]
        if not records:
            raise RunContractError('stage reference has no native Store binding')
        key = ref['payload_sha256']
        if key not in cache:
            path = evidence_path(store, job_id, stage, key)
            raw = path.read_bytes()
            if len(raw) != records[-1]['bytes'] or hashlib.sha256(raw).hexdigest() != key:
                raise RunContractError('stage evidence bytes or SHA changed')
            cache[key] = json.loads(raw)
        full = cache[key]
        if field not in full or digest(full[field]) != ref['field_sha256']:
            raise RunContractError('stage evidence field SHA changed')
        if value['summary'] != summary(field, full[field]):
            raise RunContractError('stage reference summary changed')
        resolved[field] = full[field]
    if len(cache) != 1:
        raise RunContractError('mixed stage evidence revisions')
    original = next(iter(cache.values()))
    if set(original) != set(payload):
        raise RunContractError('stage evidence field set changed')
    for field, value in payload.items():
        if not isinstance(value, dict) or MARKER not in value:
            if digest(value) != digest(original[field]):
                raise RunContractError('inline stage evidence changed')
    return resolved
