"""仅真实normal7b12的一次明确追加Source；不借F8、不创建任务、不批准发布。"""
import copy,json,math,os,signal,threading,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .review import ReviewTokens
from .source_repair_runtime import digest,encoded,private_bytes,raw_hash,signed_record,read_signed
from .workflow_runtime import WorkflowStepRunner,WorkflowBlocked,strict_workflow_lock

JOB='7b12e9aae980484b';WF='wf_'+JOB;SOURCE='collect_native_source_inputs'
ALIAS=SOURCE+'__normal_7b12_additional_source_r2'
REG='normal_7b12_additional_source_registered_r2';SUCCESS='normal_7b12_additional_source_succeeded_r2'
REG_DOMAIN='normal_7b12_source_registered_r2';SUCCESS_DOMAIN='normal_7b12_source_success_r2';CAP_DOMAIN='normal_7b12_source_scope_r2'
TOPIC_SHA='8f46a37bcb7044621e8d40b420ce9b0caa0a4f2892ee631bf06889509421180a'
ROW_SHA='1936d95a23d6f8c93f3fd41fba7069a621831a7f2c4e9e03f7f981fcff3a1a1b'
PINS={5220:'33f6a4474a4a7ecb3ab80d4ec0b1d6496d7c2a294073af63f9ce2170dc3eb698',5221:'bc7c0786adbdee569fec20545b80729db5766df7e49fcfb826421ab47d5e4c9c',5222:'7af62545c516cde781cdff36545c992b90eb2cae06ccfe4292963814039354cf'}
TOTAL=1800;PRIOR_SPENT=42;REMAINING=1758;SOURCE_LIMIT=45;RENDER_LIMIT=900
ROOT=Path('/srv/ai-self-media-tools')
ROLE_READY=Path('/srv/hermes-worker/staging/media-normal-ai-customer-service-authority-20261012-r1/ACTUAL-CURRENT-NORMAL-ROLE-READY.private.json')
FIRST=Path('/srv/hermes-worker/staging/media-normal-ai-customer-service-20261012-r1')

class SourceWindowExpired(BaseException):pass
class TotalWindowExpired(BaseException):pass

def private_create(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())

def prefix(conn):
    rows=[dict(row) for row in conn.execute('SELECT * FROM workflow_steps WHERE job_id=? AND id IN (5220,5221,5222) ORDER BY id',(JOB,))]
    if {row['id']:digest(row) for row in rows}!=PINS:raise PermissionError('normal_original_three_steps_changed')
    return rows

def role_check():
    if raw_hash(private_bytes(ROLE_READY))!='872a194b18e2d6ee0333a28c34751d33389c0afefe0ef78608de3ec265b5830a':raise PermissionError('normal_original_role_ready_changed')
    ready=json.loads(private_bytes(ROLE_READY));home=Path(ready['home'])
    if ready['task_id']!=JOB or ready['profile_id']!='fb17b73cad7b20ff63e81756f25dcad4' or ready['refresh_grant_included'] is not False:
        raise PermissionError('normal_original_full_role_task_required')
    for path,pin in [(home/'.env',ready['profile_env_sha256']),(home/'config.yaml',ready['profile_config_sha256']),
        (home/'old-runtime-authority.private.json',ready['authority_receipt_sha256']),
        (Path(ready['nohttp_proof_path']),ready['nohttp_proof_sha256'])]:
        if raw_hash(private_bytes(path))!=pin:raise PermissionError('normal_original_role_binding_changed')
    if time.time()+REMAINING>ready['expires_at_unix']:raise PermissionError('normal_role_lifetime_insufficient')
    return ready

def preflight(store):
    import sqlite3
    if os.geteuid()!=0 or store.path.resolve()!=(ROOT/'data/state.db').resolve():raise PermissionError('actual_root_normal_store_required')
    ready=role_check()
    if raw_hash(private_bytes(FIRST/'NORMAL-RUN-INTENT.private.json'))!='23ba76261457ca3629bc8a816d2301746c1762c3ac3f60e57ea3d04074619a78':raise PermissionError('normal_first_run_intent_changed')
    if raw_hash(private_bytes(FIRST/'NORMAL-RUN-RESULT.private.json'))!='2a337462fd64657b1fb3331ce6ac4973756e98667f2360e89b513b1d2f77fecc':raise PermissionError('normal_first_run_known_result_changed')
    begin=(FIRST/'NORMAL-RUN-INTENT.private.json').stat().st_mtime_ns;end=(FIRST/'NORMAL-RUN-RESULT.private.json').stat().st_mtime_ns
    elapsed=(end-begin)/1e9
    if math.ceil(max(elapsed,41))!=PRIOR_SPENT or elapsed<=0:raise PermissionError('normal_first_actual_durable_cost_changed')
    with sqlite3.connect('file:'+str(store.path)+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON');rows=prefix(conn)
        row=dict(conn.execute('SELECT * FROM jobs WHERE id=?',(JOB,)).fetchone())
        if digest(row)!=ROW_SHA or row['state']!='blocked' or row['attempts']!=1 or row['lease_owner'] or row['lease_expires_at']:
            raise PermissionError('normal_known_blocked_first_attempt_required')
        if raw_hash(row['topic'].encode())!=TOPIC_SHA or json.loads(row['platforms_json'])!=['kuaishou'] or row['profile']!='default':raise PermissionError('normal_original_identity_changed')
        if conn.execute('SELECT 1 FROM media_migration_hold WHERE job_id=?',(JOB,)).fetchone():raise PermissionError('normal_unheld_job_required')
        if conn.execute('SELECT 1 FROM events WHERE job_id=? AND event=?',(JOB,REG)).fetchone() or conn.execute('SELECT 1 FROM workflow_steps WHERE job_id=? AND step_name=?',(JOB,ALIAS)).fetchone():raise PermissionError('normal_additional_source_already_registered_query_only')
        for table in ('approvals','deliveries','delivery_receipts','delivery_attempts'):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                cols={v[1] for v in conn.execute('PRAGMA table_info('+table+')')}
                if 'job_id' in cols and conn.execute('SELECT 1 FROM '+table+' WHERE job_id=?',(JOB,)).fetchone():raise PermissionError('normal_delivery_or_approval_effect_present')
    return {'schema':'normal_7b12_additional_source_preflight_r2','job_id':JOB,'workflow_id':WF,'topic_sha256':TOPIC_SHA,
        'original_row_sha256':ROW_SHA,'original_step_pins':{str(k):v for k,v in PINS.items()},'first_actual_durable_elapsed_seconds':elapsed,
        'first_spent_charge_seconds':PRIOR_SPENT,'total_budget_seconds':TOTAL,'remaining_budget_seconds':REMAINING,
        'additional_source_budget_seconds':SOURCE_LIMIT,'renderer_budget_seconds':RENDER_LIMIT,
        'full_role_profile_id':ready['profile_id'],'role_ready_sha256':raw_hash(private_bytes(ROLE_READY)),
        'known_first_source_effect_preserved':True,'approval_authorized':False,'publication_authorized':False,'model_calls':0}

def grant(store,allow_cleanup=False):
    value=getattr(store,'_normal_7b12_source_scope',None)
    if (not isinstance(value,dict) or value.get('store_identity')!=id(store) or value.get('pid')!=os.getpid()
        or value.get('thread_id')!=threading.get_ident() or os.geteuid()!=0):raise PermissionError('same_normal_root_store_pid_thread_scope_required')
    record=read_signed(value['policy'],CAP_DOMAIN,value['cap'])
    if (record['job_id']!=JOB or record['alias']!=ALIAS or record['nonce']!=value['nonce'] or record['remaining_budget_seconds']!=REMAINING
        or record['approval_authorized'] is not False or record['publication_authorized'] is not False):raise PermissionError('normal_signed_scope_changed')
    if not allow_cleanup and (time.monotonic()-value['started_monotonic']>=REMAINING or time.time()>record['expires_at_unix']):raise PermissionError('normal_total_budget_exhausted')
    return value

def assert_step_write(store,workflow_id,job_id,step_name,status):
    if job_id!=JOB:return
    if step_name in {'initialize_task','load_platform_workflow_context',SOURCE}:
        with store.connect() as conn:
            if conn.execute('SELECT 1 FROM events WHERE job_id=? AND event=?',(JOB,REG)).fetchone():raise PermissionError('normal_original_three_steps_immutable')
    if step_name==ALIAS:
        current=grant(store);prefix_checked=False
        with store.connect() as conn:
            prefix(conn);previous=conn.execute('SELECT status FROM workflow_steps WHERE job_id=? AND step_name=?',(JOB,ALIAS)).fetchone()
            if workflow_id!=WF or (previous and previous[0]!='RUNNING'):raise PermissionError('normal_source_alias_terminal_immutable')
        if status not in {'RUNNING','SUCCEEDED','BLOCKED','FAILED_FINAL'}:raise PermissionError('normal_source_alias_status_invalid')

def resolve(store,job_id,name):
    if job_id!=JOB or name!=SOURCE:raise PermissionError('normal_source_mapping_exact_case_required')
    policy=ReviewTokens(store.path.parent/'review.key')
    if not policy.key_path.is_file():raise PermissionError('existing_native_review_key_required')
    with store.connect() as conn:
        prefix(conn)
        def one(event,domain):
            rows=conn.execute('SELECT detail_json FROM events WHERE job_id=? AND event=?',(JOB,event)).fetchall()
            if len(rows)!=1:raise PermissionError('normal_unique_signed_source_event_required')
            return read_signed(policy,domain,json.loads(rows[0][0]))
        registration=one(REG,REG_DOMAIN);receipt=one(SUCCESS,SUCCESS_DOMAIN)
        if (registration['job_id']!=JOB or registration['workflow_id']!=WF or receipt['job_id']!=JOB or receipt['workflow_id']!=WF
            or registration['alias']!=ALIAS or registration['original_step_pins']!={str(k):v for k,v in PINS.items()}
            or registration['total_budget_seconds']!=TOTAL or registration['first_spent_charge_seconds']!=PRIOR_SPENT
            or registration['remaining_budget_seconds']!=REMAINING or registration['additional_source_budget_seconds']!=SOURCE_LIMIT
            or registration['approval_authorized'] is not False or registration['publication_authorized'] is not False
            or receipt['source_budget_seconds']!=SOURCE_LIMIT or receipt['registration_sha256']!=digest(registration)):
            raise PermissionError('normal_source_signed_mapping_changed')
        row=dict(conn.execute('SELECT * FROM workflow_steps WHERE job_id=? AND id=? AND step_name=?',(JOB,receipt['alias_step_id'],ALIAS)).fetchone())
        if row['status']!='SUCCEEDED' or digest(row)!=receipt['alias_step_sha256']:raise PermissionError('normal_actual_alias_row_changed')
        output=json.loads(row['output_json'])
        if digest(output)!=receipt['output_sha256']:raise PermissionError('normal_actual_alias_output_changed')
    return output,{'id':row['id'],'step_name':ALIAS,'logical_step_name':SOURCE,'output_sha256':digest(output),'finished_at':row['finished_at'],
        'original_failure_id':5222,'original_failure_sha256':PINS[5222],'normal_source_registration_sha256':digest(registration)}

class NormalRunner(WorkflowStepRunner):
    def mapped(self,name):return ALIAS if name==SOURCE else name
    def deps(self,values):return [self.mapped(value) for value in values or []]
    def block(self,name,reason,message,gate_result=None,depends_on=None):return super().block(self.mapped(name),reason,message,gate_result,self.deps(depends_on))
    def succeeded(self,name,output=None,required=True,depends_on=None,message=''):
        if name in {'initialize_task','load_platform_workflow_context',SOURCE}:raise PermissionError('normal_original_prefix_not_replayed')
        return super().succeeded(name,output,required,self.deps(depends_on),message)
    def run(self,name,func,required=True,depends_on=None,require_output=False,input_payload=None):
        current=grant(self.store)
        remaining=REMAINING-(time.monotonic()-current['started_monotonic'])
        expiry=(datetime.now(timezone.utc)+timedelta(seconds=min(900,max(1,math.floor(remaining))))).isoformat(timespec='seconds')
        with self.store.connect() as conn:
            changed=conn.execute("UPDATE jobs SET lease_expires_at=? WHERE id=? AND state='generating' AND attempts=1 AND lease_owner=?",(expiry,JOB,current['owner'])).rowcount
            if changed!=1:raise PermissionError('normal_original_owner_lease_changed')
        if name in {'initialize_task','load_platform_workflow_context'}:raise PermissionError('normal_original_success_not_replayed')
        if name!=SOURCE:
            if not current.get('render_completed') and REMAINING-(time.monotonic()-current['started_monotonic'])<RENDER_LIMIT:
                self.block(name,'normal_remaining_budget_insufficient','Original total budget has insufficient reserved render time',{'remaining':REMAINING-(time.monotonic()-current['started_monotonic'])},depends_on)
            output=super().run(name,func,required,self.deps(depends_on),require_output,input_payload)
            if name=='generate_video[kuaishou]':current['render_completed']=True
            return output
        if any(row['step_name']==ALIAS for row in self.store.workflow_steps(JOB)):raise PermissionError('normal_source_once_only_no_replay')
        start=time.monotonic();old_handler=signal.getsignal(signal.SIGALRM)
        def expired(signum,frame):raise SourceWindowExpired()
        signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,min(SOURCE_LIMIT,REMAINING-(start-current['started_monotonic'])))
        try:
            try:result=super().run(ALIAS,func,required,self.deps(depends_on),require_output,input_payload)
            except SourceWindowExpired:
                self.block(SOURCE,'normal_additional_source_45_seconds_exhausted','Explicit one additional source window expired; no automatic retry',{'source_elapsed_seconds':time.monotonic()-start,'source_budget_seconds':SOURCE_LIMIT},depends_on)
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)
            elapsed=time.monotonic()-start
            self.store.record_event(JOB,'normal_7b12_source_budget_observed_r2',{'source_elapsed_seconds':elapsed,'source_charge_seconds':math.ceil(elapsed),
                'first_spent_charge_seconds':PRIOR_SPENT,'total_elapsed_charge_seconds':PRIOR_SPENT+math.ceil(time.monotonic()-current['started_monotonic']),
                'total_budget_seconds':TOTAL,'source_limit_seconds':SOURCE_LIMIT})
            signal.setitimer(signal.ITIMER_REAL,max(0.001,REMAINING-(time.monotonic()-current['started_monotonic'])))
        with self.store.connect() as conn:
            prefix(conn);row=dict(conn.execute('SELECT * FROM workflow_steps WHERE job_id=? AND step_name=?',(JOB,ALIAS)).fetchone())
            if row['status']!='SUCCEEDED':raise PermissionError('normal_source_success_alias_required')
            output=json.loads(row['output_json'])
            receipt={'job_id':JOB,'workflow_id':WF,'alias_step_id':row['id'],'alias_step_sha256':digest(row),'output_sha256':digest(output),
                'registration_sha256':digest(current['registration']),'actual_source_elapsed_seconds':elapsed,'source_budget_seconds':SOURCE_LIMIT}
            self.store._event(conn,JOB,SUCCESS,signed_record(current['policy'],SUCCESS_DOMAIN,receipt))
        return result

def execute(pipeline,stage):
    store=pipeline.store;proof=preflight(store);policy=pipeline.review_tokens
    if threading.current_thread() is not threading.main_thread():raise PermissionError('normal_source_timer_main_thread_required_before_effect')
    if signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):raise PermissionError('normal_foreign_timer_present_before_effect')
    if type(policy) is not ReviewTokens or not policy.key_path.is_file() or policy.key_path.resolve()!=(store.path.parent/'review.key').resolve():raise PermissionError('original_native_review_key_required')
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0' or os.environ.get('AI_SELF_MEDIA_HERMES_TARGET','')!='':raise PermissionError('normal_explicit_no_publish_environment_required')
    if any((stage/name).exists() for name in ('NORMAL-7B12-SCOPE-INTENT.private.json','NORMAL-7B12-SCOPE-RESULT.private.json')):raise PermissionError('normal_prior_scope_query_only_no_replay')
    started=time.monotonic();owner=pipeline._worker_id();nonce=os.urandom(16).hex()
    payload=dict(proof,alias=ALIAS,nonce=nonce,expires_at_unix=time.time()+REMAINING)
    cap=signed_record(policy,CAP_DOMAIN,payload)
    private_create(stage/'NORMAL-7B12-SCOPE-INTENT.private.json',{'scope':cap,'original_failure_preserved':True,'same_job_id':JOB,'started_at_unix':time.time()})
    current={'policy':policy,'cap':cap,'nonce':nonce,'owner':owner,'pid':os.getpid(),'thread_id':threading.get_ident(),
        'store_identity':id(store),'started_monotonic':started,'registration':payload}
    store._normal_7b12_source_scope=current
    old_handler=signal.getsignal(signal.SIGALRM)
    def exhausted(signum,frame):raise TotalWindowExpired()
    signal.signal(signal.SIGALRM,exhausted);signal.setitimer(signal.ITIMER_REAL,REMAINING)
    result=None;admitted=False
    try:
        with strict_workflow_lock(store,owner,WF,min(pipeline.lock_timeout_seconds,REMAINING),pipeline.strict_serial):
            with store.connect() as conn:
                conn.execute('BEGIN IMMEDIATE');rows=prefix(conn);row=dict(conn.execute('SELECT * FROM jobs WHERE id=?',(JOB,)).fetchone())
                if digest(row)!=ROW_SHA or conn.execute('SELECT 1 FROM events WHERE job_id=? AND event=?',(JOB,REG)).fetchone():raise PermissionError('normal_original_row_or_registration_changed_before_effect')
                expiry=(datetime.now(timezone.utc)+timedelta(seconds=min(900,math.floor(REMAINING-(time.monotonic()-started))))).isoformat(timespec='seconds')
                changed=conn.execute("UPDATE jobs SET state='generating',lease_owner=?,lease_expires_at=?,updated_at=? WHERE id=? AND state='blocked' AND attempts=1 AND lease_owner='' AND lease_expires_at=''",(owner,expiry,datetime.now(timezone.utc).isoformat(timespec='seconds'),JOB)).rowcount
                if changed!=1:raise PermissionError('normal_exact_original_lease_transition_required')
                store._event(conn,JOB,REG,signed_record(policy,REG_DOMAIN,payload))
            admitted=True
            runner=NormalRunner(store,WF,JOB,notifier=pipeline.notifier)
            contexts=copy.deepcopy(json.loads(rows[1]['output_json'])['platforms'])
            original_delivery=pipeline.config.get('delivery');pipeline.config['delivery']=dict(original_delivery or {},auto_stage_review_required=False)
            try:result=pipeline._continue_native_generation(JOB,owner,WF,runner,contexts,force=False)
            except WorkflowBlocked as error:
                result=store.release_claim(JOB,owner,'blocked','workflow_blocked',error,{'step':error.step,'reason_code':error.reason_code,'original_failure_preserved':True})
            except TotalWindowExpired:
                result=store.release_claim(JOB,owner,'failed','generation_failed','normal_total_budget_expired_effect_must_be_queried',{'unknown_effect_not_replayed':True})
            except Exception as error:
                current_job=store.get_job(JOB)
                if current_job.get('lease_owner')==owner:store.release_claim(JOB,owner,'failed','generation_failed',type(error).__name__)
                raise
            finally:
                if original_delivery is None:pipeline.config.pop('delivery',None)
                else:pipeline.config['delivery']=original_delivery
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)
        if admitted:
            with store.connect() as conn:prefix(conn)
            elapsed=time.monotonic()-started
            value={'job_id':JOB,'elapsed_seconds':elapsed,'this_scope_charge_seconds':math.ceil(elapsed),'first_spent_charge_seconds':PRIOR_SPENT,
                'original_total_budget_seconds':TOTAL,'remaining_after_actual_scope_seconds':max(0,TOTAL-PRIOR_SPENT-math.ceil(elapsed)),
                'state':(result or {}).get('state'),'approval_authorized':False,'publication_authorized':False,'original_three_steps_preserved':True}
            private_create(stage/'NORMAL-7B12-SCOPE-RESULT.private.json',value);store.record_event(JOB,'normal_7b12_additional_scope_closed_r2',value)
        if getattr(store,'_normal_7b12_source_scope',None) is current:del store._normal_7b12_source_scope
    return result
