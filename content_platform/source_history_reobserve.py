"""固定F8已知history env失败的签证只读再观察；原5216与三个旧row永久保。"""
import base64
import contextlib
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import threading
import time
from datetime import datetime,timedelta,timezone
from .source_repair_runtime import JOB,WF,EFFECTS,private_bytes,raw_hash,digest,encoded,load_evidence,check_original_rows,read_signed,signed_record,state_update
from .scoped_history_collector_guard import ACTION,ALIAS,scoped_history_collector
ROW_SHA='7aefbf95ec7e6ad043223136c3be46b2b8792296a227cc708a4d558dbf22b24d'
FAILED_ALIAS_SHA='f1fb8aba6ba3ab69fb2c73283afd84639706a50e52158756377a5de0551272df'
EVENT_PINS={'root_source_repair_registered':'6f0e3d6f95be4d6546028f35e1dee20e3687f087cda1f55c075ceba46e083162',
 'root_source_repair_scope_closed':'d4439cfc34c9e31d3577d1b3d45ab74e019a387e4c269ea439da52e983eba040',
 'root_source_repair_continuation_registered':'c05a1dcb1df2df1e1b1c473b668341fa4cdbad4da8a54844571f1f73c5a05230',
 'root_source_repair_continuation_scope_closed':'9a769f2e442f630ffd7fa01179dc99f0d2d2db204bd85d710bde7deadc49c689'}
ENTITY_PINS={'SOURCE-REPAIR-CONTINUE-INTENT.private.json':'9c8db7e446fce074800d59bd26d7093f56aa3c3bf35cb37c370da6831bdf4ca0',
 'SOURCE-REPAIR-CONTINUATION-TOKEN-REGISTRATION.private.json':'09031177520fde4e3a894294fb274ab80fcb5f39a88a28e474f279e20c6ff051',
 'SOURCE-REPAIR-CONTINUE-FAILURE.private.json':'3d7a3b12e5628c209ca284fb683fb4ddfe6e8bfcfa7581b4d15181ec70ca2d21'}


def checkpoint(conn,evidence,policy):
    row,_=check_original_rows(conn,evidence)
    if digest(row)!=ROW_SHA or row['state']!='failed' or row['attempts']!=1 or row['lease_owner'] or row['lease_expires_at']:
        raise PermissionError('same_actual_failed_history_checkpoint_changed')
    alias=conn.execute('SELECT * FROM workflow_steps WHERE job_id=? AND id=5216',(JOB,)).fetchone()
    if not alias or digest(dict(alias))!=FAILED_ALIAS_SHA or alias['status']!='FAILED_FINAL':raise PermissionError('original_failed_source_alias_changed')
    if conn.execute('SELECT count(*) FROM workflow_steps WHERE job_id=?',(JOB,)).fetchone()[0]!=4 or any(conn.execute('SELECT 1 FROM '+t+' WHERE job_id=? LIMIT 1',(JOB,)).fetchone() for t in EFFECTS):
        raise PermissionError('history_known_source_boundary_downstream_or_unknown')
    records={}
    for name,pin in EVENT_PINS.items():
        rows=conn.execute('SELECT * FROM events WHERE job_id=? AND event=?',(JOB,name)).fetchall()
        if len(rows)!=1 or digest(dict(rows[0]))!=pin:raise PermissionError('original_consumed_source_events_changed')
        records[name]=dict(rows[0])
    for event,domain in [('root_source_repair_registered','source_repair_registered_v1'),('root_source_repair_continuation_registered','source_repair_continuation_registered_v1')]:
        payload=read_signed(policy,domain,json.loads(records[event]['detail_json']))
        if payload.get('job_id')!=JOB or payload.get('workflow_id')!=WF or payload.get('attempts')!=1 or payload.get('evidence_sha256')!=evidence['_actual_evidence_sha256']:
            raise PermissionError('actual_prior_root_signature_chain_required')
    if conn.execute("SELECT 1 FROM events WHERE job_id=? AND event='root_source_history_reobserve_registered'",(JOB,)).fetchone():raise PermissionError('history_reobservation_already_consumed')
    return row


def validate(store,policy,evidence_path,evidence_sha,proof_path,proof_sha):
    evidence=load_evidence(store,evidence_path,evidence_sha,initial=False);evidence['_actual_evidence_sha256']=evidence_sha
    raw=private_bytes(proof_path)
    if raw_hash(raw)!=proof_sha:raise PermissionError('actual_history_reobservation_proof_changed')
    proof=json.loads(raw)
    if (proof.get('schema')!='same-f8-known-history-env-readonly-reobservation-v1' or proof.get('job_id')!=JOB or proof.get('workflow_id')!=WF or proof.get('attempts')!=1
        or proof.get('remaining_budget_seconds')!=1748 or proof.get('renderer_budget_seconds')!=900 or proof.get('effect_unknown') is not False
        or proof.get('allow_readonly_reobservation') is not True or proof.get('approval_or_publication_authorized') is not False
        or proof.get('old_failed_alias_sha256')!=FAILED_ALIAS_SHA or proof.get('current_row_sha256')!=ROW_SHA
        or proof.get('unit_start_monotonic_us')!=1684215578910 or proof.get('unit_exit_monotonic_us')!=1684262653422
        or {k:v.get('sha256') for k,v in proof.get('prior_entities',{}).items()}!=ENTITY_PINS):raise PermissionError('fixed_signed_history_reobservation_scope_required')
    if 1796-math.ceil((proof['unit_exit_monotonic_us']-proof['unit_start_monotonic_us'])/1000000)!=1748:raise PermissionError('whole_previous_unit_budget_required')
    for item in proof['prior_entities'].values():
        if raw_hash(private_bytes(item['path']))!=item['sha256']:raise PermissionError('actual_prior_source_effect_failure_changed')
    failure=json.loads(private_bytes(proof['prior_entities']['SOURCE-REPAIR-CONTINUE-FAILURE.private.json']['path']))
    if failure.get('error_type')!='HistoryUnavailable' or not any(v.get('file')=='history_reader.py' and v.get('function')=='_mirror_path' and v.get('line')==45 for v in failure.get('safe_frames',[])):
        raise PermissionError('only_known_history_environment_rejection_allowed')
    if (os.environ.get('CONTENT_PLATFORM_HISTORY_REQUIRED')!='1' or os.environ.get('CONTENT_PLATFORM_HISTORY_DB')!='/srv/business-sync/current/media/state.db'
        or os.environ.get('CONTENT_PLATFORM_HISTORY_STATUS_FILE')!='/srv/business-sync/status.json'):raise PermissionError('actual_formal_history_context_required')
    from .history_reader import read_history
    with read_history(store.path,('jobs','topic_history')) as (reader,prefix):
        reader.execute(prefix+'SELECT count(*) FROM read_jobs').fetchone();reader.execute(prefix+'SELECT count(*) FROM read_topic_history').fetchone()
    with store.connect() as conn:checkpoint(conn,evidence,policy)
    return evidence,proof


def issue(store,policy,evidence_path,evidence_sha,proof_path,proof_sha):
    from .review import ReviewTokens
    if os.geteuid()!=0 or type(policy) is not ReviewTokens or policy.key_path.resolve()!=(store.path.parent/'review.key').resolve() or not policy.key_path.is_file():raise PermissionError('native_root_history_reobservation_key_required')
    validate(store,policy,evidence_path,evidence_sha,proof_path,proof_sha)
    p={'action':ACTION,'job_id':JOB,'workflow_id':WF,'attempts':1,'evidence_sha256':evidence_sha,'history_proof_sha256':proof_sha,
       'nonce':os.urandom(16).hex(),'exp':int(time.time())+1748,'remaining_budget_seconds':1748,'allow_readonly_reobservation':True,'alias':ALIAS}
    b64=lambda value:base64.urlsafe_b64encode(value).decode().rstrip('=');body=b64(json.dumps(p,separators=(',',':')).encode());token=body+'.'+b64(hmac.new(policy._key(),body.encode(),hashlib.sha256).digest())
    fd=os.open(Path(proof_path).parent/'SOURCE-HISTORY-REOBSERVE-TOKEN-REGISTRATION.private.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(encoded({'token_sha256':raw_hash(token.encode()),'job_id':JOB,'history_proof_sha256':proof_sha,'remaining_budget_seconds':1748,'readonly_reobservation_explicitly_authorized':True})+b'\n');f.flush();os.fsync(f.fileno())
    return token


@contextlib.contextmanager
def authorized(store,policy,token,evidence_path,evidence_sha,proof_path,proof_sha,owner):
    from .review import ReviewTokens
    if os.geteuid()!=0 or type(policy) is not ReviewTokens or policy.key_path.resolve()!=(store.path.parent/'review.key').resolve() or not policy.key_path.is_file() or getattr(store,'_root_source_repair',None) is not None:raise PermissionError('native_same_store_root_history_context_required')
    evidence,proof=validate(store,policy,evidence_path,evidence_sha,proof_path,proof_sha);payload=policy.verify(token,ACTION)
    if (payload.get('job_id')!=JOB or payload.get('workflow_id')!=WF or payload.get('attempts')!=1 or payload.get('evidence_sha256')!=evidence_sha or payload.get('history_proof_sha256')!=proof_sha
        or payload.get('alias')!=ALIAS or payload.get('allow_readonly_reobservation') is not True or payload.get('remaining_budget_seconds')!=1748 or not 0<payload.get('exp',0)-time.time()<=1748
        or not owner or not isinstance(payload.get('nonce'),str) or len(payload['nonce'])!=32):raise PermissionError('actual_signed_same_history_scope_budget_required')
    grant={'policy':policy,'token':token,'action':ACTION,'alias':ALIAS,'allow_readonly_reobservation':True,'nonce':payload['nonce'],'evidence':evidence,'evidence_sha256':evidence_sha,
           'store_identity':id(store),'pid':os.getpid(),'thread_id':threading.get_ident(),'expires_at':payload['exp'],'remaining_budget_seconds':1748,'owner':owner}
    store._root_source_repair=grant;admitted=False
    try:
        with store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE');row=checkpoint(conn,evidence,policy);now=datetime.now(timezone.utc).isoformat(timespec='seconds')
            lease=min(900,math.floor(payload['exp']-time.time()))
            if lease<=0:raise PermissionError('history_reobservation_budget_exhausted')
            expires=(datetime.now(timezone.utc)+timedelta(seconds=lease)).isoformat(timespec='seconds');updated=dict(row,state='generating',lease_owner=owner,lease_expires_at=expires,updated_at=now)
            record=signed_record(policy,'source_history_reobserve_registered_v1',{'job_id':JOB,'workflow_id':WF,'attempts':1,'evidence_sha256':evidence_sha,'history_proof_sha256':proof_sha,
                    'alias':ALIAS,'old_failed_alias_id':5216,'old_failed_alias_sha256':FAILED_ALIAS_SHA,'remaining_budget_seconds':1748,'readonly_reobservation_authorized':True,
                    'allowed_readonly_post_policy_sha256':'53dd13bbd4a14842402f11d953c7a059fd1455b64544c781bcd3656fdcdc6336','token_sha256':raw_hash(token.encode()),'approval_authorized':False,'publication_authorized':False})
            store._event(conn,JOB,'root_source_history_reobserve_registered',record)
            state_update(store,conn,"UPDATE jobs SET state=?,lease_owner=?,lease_expires_at=?,updated_at=? WHERE id=? AND state='failed' AND attempts=1 AND lease_owner='' AND lease_expires_at=''",('generating',owner,expires,now,JOB),updated);grant['lease_expires_at']=expires
        admitted=True
        with scoped_history_collector(store):yield dict(evidence,remaining_budget_seconds=1748)
    finally:
        if getattr(store,'_root_source_repair',None) is grant:del store._root_source_repair
        if admitted:store.record_event(JOB,'root_source_history_reobserve_scope_closed',{'old_failed_alias_preserved':True,'original_hold_kept':True,'approval_or_publication_authorized':False})
