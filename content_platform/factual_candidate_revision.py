"""A single explicit factual correction; original Source/generation/failure stay immutable."""
import copy,hashlib,json,math,os,re,sqlite3,threading,time
from datetime import datetime,timezone
from pathlib import Path

VERSION='normal-factual-candidate-revision-v1'
VERSION_V2='normal-factual-candidate-revision-v2'
VERSION_V3='normal-factual-candidate-revision-v3'
FRESH_SCOPE='1023797dfcb64de38c855725294c806a'
FRESH_NONCE='f4631baec1d9295c7cced7600f776c75'
FRESH_REF={'path':'/srv/ai-self-media-tools/data/jobs/25110343c3354385/source-observations/source-1791994410377610393.current-strategy-twitter.private.json','sha256':'0abbe973c0b3907416b5be9a2212cfccada32fffb205b6025fdd092f076821f7'}
EXPIRED_SCOPE='8957980fc9d04c1d86168993423fbb87'
EXPIRED_NONCE='a7e605038bd9e830277683da23ddea49'
EXPIRED_PROOF_SHA='fb1b1ed258a65faaf59c1df9d4676f4c1e260a292e1ca09b231df300841fa9c2'
EXPIRED_RESULT_SHA='2396166dfee8fcd28e32162153f0a3aa900cab6a38a9db727d9d1f645aa2b25d'
JOB='25110343c3354385'
ORIGIN='06af82585a2442da9c64442b643e9e99'
SESSION='20261014_135428_f0d1e6'
STEP_IDS={'source':5353,'generation':5360,'failure':5362}
_SEAL=object()

def digest(value):
    def blob(item):
        if isinstance(item,bytes):return {'sqlite_blob_sha256':hashlib.sha256(item).hexdigest(),'sqlite_blob_bytes':len(item)}
        raise TypeError('unsupported_original_record_type:'+type(item).__name__)
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False,default=blob).encode()).hexdigest()

def private_read(path,expected=None,limit=2097152):
    path=Path(path)
    if any(p.is_symlink()for p in(path,*path.parents)):raise PermissionError('factual_revision_symlink_forbidden')
    st=path.stat();raw=path.read_bytes()
    if not path.is_file()or st.st_uid!=0 or st.st_mode&0o777!=0o600 or st.st_nlink!=1 or not 0<len(raw)<=limit:
        raise PermissionError('factual_revision_root_private_original_required')
    if expected and hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('factual_revision_original_file_changed')
    return json.loads(raw)

def write_once(path,value):
    path=Path(path)
    if any(p.is_symlink()for p in(path,*path.parents)):raise PermissionError('factual_revision_nonce_path_invalid')
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}

def original_session_records():
    path=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+ORIGIN)/'state.db'
    if any(p.is_symlink()for p in(path,*path.parents)):raise PermissionError('factual_revision_original_session_path_invalid')
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)as conn:
        conn.row_factory=sqlite3.Row
        row=conn.execute('SELECT * FROM sessions WHERE id=?',(SESSION,)).fetchone()
        if row is None:raise ValueError('factual_revision_original_session_absent')
        session=dict(row);messages=[dict(r)for r in conn.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id',(SESSION,))]
    if not session.get('ended_at')or session.get('api_call_count')!=10:raise ValueError('factual_revision_original_generation_not_ended')
    return session,messages

def expired_attempt_records():
    """Only the exact known 895 expiry failure, not an unknown or successful request."""
    root=Path('/srv/ai-self-media-tools/data/quality_runtime')
    prior_path=root/('factual-revision-'+EXPIRED_NONCE+'.proof.private.json')
    prior=private_read(prior_path,EXPIRED_PROOF_SHA)
    invocation=private_read(root/('factual-revision-'+EXPIRED_NONCE+'.invocation.private.json'))
    stage=Path('/srv/hermes-worker-media/jobs')/EXPIRED_SCOPE
    result=private_read(stage/'hard-factual-result.private.json',EXPIRED_RESULT_SHA)
    if (prior.get('version')!=VERSION or prior.get('job_id')!=JOB or prior.get('nonce')!=EXPIRED_NONCE
            or invocation.get('version')!=VERSION or invocation.get('task_id')!=EXPIRED_SCOPE or invocation.get('job_id')!=JOB
            or invocation.get('proof_sha256')!=EXPIRED_PROOF_SHA or invocation.get('no_publish')is not True
            or result.get('schema')!='hard-factual-result-v1' or result.get('task_id')!=EXPIRED_SCOPE
            or result.get('job_id')!=JOB or result.get('state')!='failed'or result.get('returncode')!=1
            or result.get('proof_sha256')!=EXPIRED_PROOF_SHA):
        raise PermissionError('factual_revision_exact_expired_attempt_receipts_required')
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+EXPIRED_SCOPE)
    for path in(home,stage):
        if any(p.is_symlink()for p in(path,*path.parents)):raise PermissionError('factual_revision_expired_scope_path_changed')
    for name in('state.db','state.db-wal','state.db-shm'):
        path=home/name
        if path.exists()or path.is_symlink():raise PermissionError('factual_revision_expired_scope_model_effect_unknown')
    generation=stage/('factual-revision-'+EXPIRED_NONCE+'.generation.private.json')
    if generation.exists()or generation.is_symlink():raise PermissionError('factual_revision_expired_scope_generation_exists')
    return {'prior_proof_sha256':EXPIRED_PROOF_SHA,'prior_nonce':EXPIRED_NONCE,'task_id':EXPIRED_SCOPE,
        'result_sha256':EXPIRED_RESULT_SHA,'invocation_sha256':digest(invocation),'original_model_database_absent':True,
        'known_reason':'strategy_evidence_sample_observation_expired','new_model_calls':0}

def fresh_attempt_records():
    root=Path('/srv/ai-self-media-tools/data/quality_runtime')
    path=root/('factual-revision-'+FRESH_NONCE+'.proof.private.json');prior=private_read(path)
    pin=hashlib.sha256(path.read_bytes()).hexdigest()
    invocation=private_read(root/('factual-revision-'+FRESH_NONCE+'.invocation.private.json'))
    stage=Path('/srv/hermes-worker-media/jobs')/FRESH_SCOPE;result=private_read(stage/'hard-factual-result.private.json')
    if (prior.get('version')!=VERSION_V2 or prior.get('job_id')!=JOB or prior.get('nonce')!=FRESH_NONCE
            or invocation.get('version')!=VERSION_V2 or invocation.get('task_id')!=FRESH_SCOPE or invocation.get('proof_sha256')!=pin
            or result.get('schema')!='hard-factual-result-v1'or result.get('task_id')!=FRESH_SCOPE or result.get('state')!='failed'
            or result.get('returncode')!=1 or result.get('proof_sha256')!=pin):
        raise PermissionError('factual_revision_exact_successful_fresh_failed_generation_chain_required')
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+FRESH_SCOPE)
    for name in('state.db','state.db-wal','state.db-shm'):
        item=home/name
        if item.exists()or item.is_symlink():raise PermissionError('factual_revision_fresh_generation_model_effect_unknown')
    item=stage/('factual-revision-'+FRESH_NONCE+'.generation.private.json')
    if item.exists()or item.is_symlink():raise PermissionError('factual_revision_fresh_generation_already_completed')
    observed=private_read(FRESH_REF['path'],FRESH_REF['sha256'])
    if observed.get('job_id')!=JOB or observed.get('platform')!='twitter':raise ValueError('factual_revision_fresh_observation_identity_changed')
    return {'task_id':FRESH_SCOPE,'nonce':FRESH_NONCE,'prior_proof_sha256':pin,'invocation_sha256':digest(invocation),
        'hard_result_sha256':digest(result),'observation_ref':FRESH_REF,'new_model_calls':0,'known_failed_step_id':5378}

def build_proof(store,nonce,editorial_candidate_ref,module_pins):
    """Root reads current exact originals; this method performs no business action."""
    job=store.get_job(JOB);steps=store.workflow_steps(JOB);events=store.events(JOB)
    session,messages=original_session_records()
    proof={'version':VERSION_V3,'fresh_attempt':fresh_attempt_records(),'expired_attempt':expired_attempt_records(),'job_id':JOB,'origin_task_id':ORIGIN,'nonce':nonce,'budget_seconds':900,'no_publish':True,
        'original_job_sha256':digest(job),'original_steps':steps,'original_steps_sha256':digest(steps),
        'original_events':events,'original_events_sha256':digest(events),
        'original_session_sha256':digest(session),'original_messages_sha256':digest(messages),
        'editorial_candidate_ref':editorial_candidate_ref,'module_pins':module_pins}
    validate_proof(store,proof,initial=True)
    return proof

def validate_proof(store,proof,initial=True):
    if (proof.get('version')!=VERSION_V3 or proof.get('job_id')!=JOB or proof.get('origin_task_id')!=ORIGIN
            or not re.fullmatch('[a-f0-9]{32}',str(proof.get('nonce')or''))or proof.get('nonce')in{EXPIRED_NONCE,FRESH_NONCE} or proof.get('budget_seconds')!=900
            or proof.get('no_publish')is not True):raise PermissionError('factual_revision_exact_contract_required')
    if proof.get('fresh_attempt')!=fresh_attempt_records():raise ValueError('factual_revision_successful_fresh_attempt_changed')
    if proof.get('expired_attempt')!=expired_attempt_records():raise ValueError('factual_revision_known_expired_attempt_changed')
    if digest(proof['original_steps'])!=proof['original_steps_sha256']or digest(proof['original_events'])!=proof['original_events_sha256']:
        raise ValueError('factual_revision_history_contract_changed')
    current={r['id']:r for r in store.workflow_steps(JOB)}
    for row in proof['original_steps']:
        if current.get(row['id'])!=row:raise ValueError('factual_revision_original_step_changed')
    historical={r['id']:r for r in store.events(JOB)}
    for row in proof['original_events']:
        if historical.get(row['id'])!=row:raise ValueError('factual_revision_original_event_changed')
    failure_event=historical.get(7476)or{}
    if failure_event.get('event')!='factual_revision_failed'or 'strategy_evidence_sample_observation_expired'not in str(failure_event.get('detail_json')or''):
        raise PermissionError('factual_revision_actual_expired_failure_event_required')
    if not any(row.get('id')==7476 for row in proof['original_events']):raise PermissionError('factual_revision_expired_failure_event_pin_required')
    exact={name:current.get(identifier)for name,identifier in STEP_IDS.items()}
    if (not all(exact.values())or exact['source']['step_name']!='collect_native_source_inputs' or exact['source']['status']!='SUCCEEDED'
            or exact['generation']['step_name']!='generate_content'or exact['generation']['status']!='SUCCEEDED'
            or exact['failure']['step_name']!='validate_factual_claims'or exact['failure']['status']!='BLOCKED'
            or exact['failure']['reason_code']!='factual_claim_evidence_missing'):
        raise PermissionError('factual_revision_exact_source_generation_failure_required')
    gate=exact['failure'].get('gate')or{}
    if (gate.get('ledger_count')!=0 or set(gate.get('failures')or[])!={'unsourced_first_person_operation','unsourced_numeric_claim'}):
        raise PermissionError('factual_revision_original_fact_gate_changed')
    job=store.get_job(JOB)
    if job.get('platforms')!=['twitter']or job.get('topic')!='用AI工作流核对报表交付回执':raise PermissionError('factual_revision_original_intent_changed')
    brief=job.get('brief')or{}
    if brief.get('no_publish')is not True or brief.get('publication_authorized')is not False or brief.get('claim_ledger'):
        raise PermissionError('factual_revision_no_publication_empty_ledger_required')
    expected_previous={5363:'validate_content_policy_inputs__factual_revision_'+EXPIRED_NONCE,5364:'run_content_hygiene__factual_revision_'+EXPIRED_NONCE}
    for identifier,name in expected_previous.items():
        if current.get(identifier,{}).get('step_name')!=name or current[identifier].get('status')!='SUCCEEDED':
            raise PermissionError('factual_revision_known_expired_attempt_prefix_changed')
    additional={5365:'validate_content_policy_inputs',5366:'run_content_hygiene',5367:'collect_current_strategy_accounts',
        5369:'collect_current_strategy_platform_research',5371:'validate_current_strategy_raw[twitter]',5373:'distill_current_strategy_same_lane[twitter]',
        5375:'prepare_current_strategy[twitter]',5377:'run_operation_strategy',5378:'generate_content'}
    for identifier,name in additional.items():
        row=current.get(identifier)or{};expected='FAILED_FINAL'if identifier==5378 else'SUCCEEDED'
        if row.get('step_name')!=name+'__factual_revision_'+FRESH_NONCE or row.get('status')!=expected:
            raise PermissionError('factual_revision_successful_fresh_prefix_or_generation_failure_changed')
    if current[5378].get('reason_code')!='exception'or'strategy_evidence_sample_observation_expired'not in str(current[5378].get('message')or''):
        raise PermissionError('factual_revision_known_before_model_projection_failure_required')
    if {r['id']for r in proof['original_steps']if r['id']>5362}!=set(expected_previous)|set(additional):
        raise PermissionError('factual_revision_other_previous_effects_forbidden')
    if historical.get(7496,{}).get('event')!='factual_revision_failed' or 'strategy_evidence_sample_observation_expired'not in str(historical.get(7496,{}).get('detail_json')or''):
        raise PermissionError('factual_revision_actual_projection_failure_event_required')
    if initial:
        if (digest(job)!=proof['original_job_sha256']or job.get('state')!='failed'or job.get('last_error')!='strategy_evidence_sample_observation_expired'or job.get('lease_owner')
                or job.get('lease_expires_at')or job.get('attempts')!=3 or store.draft_versions(JOB)
                or store.artifacts(JOB)or store.platform_outputs(JOB)):
            raise PermissionError('factual_revision_original_zero_output_scope_changed')
        if digest(store.workflow_steps(JOB))!=proof['original_steps_sha256']or digest(store.events(JOB))!=proof['original_events_sha256']:
            raise ValueError('factual_revision_new_unaccounted_history')
    session,messages=original_session_records()
    if digest(session)!=proof['original_session_sha256']or digest(messages)!=proof['original_messages_sha256']:
        raise ValueError('factual_revision_original_generation_session_changed')
    for ref in proof.get('module_pins')or[]:
        path=Path(ref['path']);raw=path.read_bytes()
        if any(p.is_symlink()for p in(path,*path.parents))or hashlib.sha256(raw).hexdigest()!=ref['sha256']:
            raise ValueError('factual_revision_deployed_code_changed')
    if not proof.get('module_pins'):raise PermissionError('factual_revision_deployed_code_pins_required')
    candidate=private_read(proof['editorial_candidate_ref']['path'],proof['editorial_candidate_ref']['sha256'])
    from .claim_ledger import validate_claims
    if (not candidate.get('title')or len(candidate.get('body')or'')<100 or not validate_claims(candidate['title']+'\n'+candidate['body'],[])['passed']):
        raise ValueError('factual_revision_editorial_candidate_contains_unsupported_claim')
    return job,candidate

def require_active_factual_revision(store,job_id,owner):
    grant=getattr(store,'_root_factual_revision',None)
    if (not isinstance(grant,dict)or grant.get('_seal')is not _SEAL or grant.get('thread_id')!=threading.get_ident()
            or grant.get('job_id')!=job_id or grant.get('owner')!=owner or time.monotonic()>=grant.get('deadline',0)):
        raise PermissionError('active_factual_revision_scope_required')
    from .native_quality_runner import current_active_role
    _,task,_=current_active_role(0)
    if task!=grant['task_id']:raise PermissionError('factual_revision_current_role_changed')
    validate_proof(store,grant['proof'],initial=False)
    job=store.get_job(job_id)
    if job.get('state')!='generating'or job.get('lease_owner')!=owner:raise PermissionError('factual_revision_current_lease_required')
    try:lease=datetime.fromisoformat(str(job['lease_expires_at']).replace('Z','+00:00')).timestamp()
    except (KeyError,TypeError,ValueError):raise PermissionError('factual_revision_actual_lease_deadline_invalid')
    if lease<=time.time():raise PermissionError('factual_revision_actual_lease_expired')
    return grant

def resolve_factual_revision_step(store,job_id,name):
    """Current authorized alias only; never borrow an old successful artifact binding."""
    grant=getattr(store,'_root_factual_revision',None)
    if grant is None:return name
    require_active_factual_revision(store,job_id,grant['owner'])
    return name+'__factual_revision_'+grant['proof']['nonce']

def registered_current_scope(home,task):
    """Reuse the existing authenticated HMAC management binding; no local signature substitute."""
    import sys,urllib.request
    if '/srv/hermes-worker'not in sys.path:sys.path.insert(0,'/srv/hermes-worker')
    from root_registered_native_driver import authenticated_binding
    stage=Path('/srv/hermes-worker-media/jobs')/task
    marker=private_read(stage/'registered-driver-invocation.private.json')
    deadline=marker.get('deadline_unix')
    if (marker.get('schema')!='root-registered-driver-invocation-v1'or marker.get('job_id')!=task
            or marker.get('no_publish')is not True or marker.get('outer_model_api_calls')!=0
            or type(deadline)not in(int,float)or not math.isfinite(deadline)or deadline<=time.time()
            or not re.fullmatch('[A-Za-z0-9_-]{1,128}',str(marker.get('request_id')or''))):
        raise PermissionError('factual_revision_registered_driver_scope_required')
    registry=private_read(Path('/etc/hermes/root-native-drivers')/(marker['request_id']+'.json'),marker['registry_sha256'])
    program=stage/'registered-driver.program.private.py'
    st=program.stat();raw=program.read_bytes()
    if (any(p.is_symlink()for p in(program,*program.parents))or st.st_uid!=0 or st.st_mode&0o777!=0o600 or st.st_nlink!=1
            or hashlib.sha256(raw).hexdigest()!=marker['script_sha256']or registry.get('script_sha256')!=marker['script_sha256']
            or registry.get('schema')!='root-current-native-driver-v1'or registry.get('request_id')!=marker['request_id']or registry.get('no_publish')is not True):
        raise PermissionError('factual_revision_registered_program_changed')
    if os.environ.get('HERMES_WORKER_CONTROL_URL','http://127.0.0.1:22120')!='http://127.0.0.1:22120':raise PermissionError('factual_revision_current_control_tunnel_required')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise PermissionError('factual_revision_control_redirect_forbidden')
    request=urllib.request.Request('http://127.0.0.1:22120/v1/jobs/'+task,
        headers={'X-Hermes-Worker-Token':os.environ['HERMES_WORKER_CONTROL_TOKEN']})
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=12)as response:
        if response.status!=200:raise PermissionError('factual_revision_actual_control_job_unavailable')
        raw=response.read(65537)
    if not 0<len(raw)<=65536:raise PermissionError('factual_revision_current_control_job_size_invalid')
    job=json.loads(raw)
    if (job.get('job_id')!=task or job.get('request_id')!=marker['request_id']or job.get('status')!='running'
            or job.get('claim_lane')!='media'or job.get('task_type')!='hermes_task'
            or job.get('payload',{}).get('registered_root_driver')!=marker['registry_sha256']):
        raise PermissionError('factual_revision_actual_management_job_changed')
    receipt=private_read(Path(home)/'old-runtime-authority.private.json')
    authenticated_binding(job,receipt,dict(os.environ))
    return min(900,math.floor(deadline-time.time()))

def current_generation_records(home,allow_absent=False):
    path=Path(home)/'state.db'
    if any(p.is_symlink()for p in(path,*path.parents)):raise PermissionError('factual_revision_current_session_path_invalid')
    if not path.exists():
        if allow_absent and Path(home).is_dir()and not Path(str(path)+'-wal').exists()and not Path(str(path)+'-shm').exists():return[]
        raise ValueError('factual_revision_current_generation_database_required')
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)as conn:
        conn.row_factory=sqlite3.Row
        return [dict(r)for r in conn.execute('SELECT * FROM sessions ORDER BY started_at,id')]

def generation_once(pipeline,home,task,route,proof,scoped):
    before={r['id']for r in current_generation_records(home,allow_absent=True)}
    pipeline.generator._last_provider_normalization=None
    draft=pipeline._generate_scoped_drafts(JOB,pipeline.store.get_job(JOB)['topic'],scoped)
    new=[r for r in current_generation_records(home)if r['id']not in before and not r.get('parent_session_id')]
    if len(new)!=1:raise ValueError('factual_revision_unique_new_native_generation_session_required')
    session=new[0]
    if session.get('model')!=route['model']or not session.get('ended_at')or type(session.get('api_call_count'))is not int or session['api_call_count']<=0:
        raise ValueError('factual_revision_actual_current_generation_route_or_terminal_missing')
    with sqlite3.connect('file:'+str(Path(home)/'state.db')+'?mode=ro',uri=True)as conn:
        conn.row_factory=sqlite3.Row
        messages=[dict(r)for r in conn.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id',(session['id'],))]
    final=[r for r in messages if r.get('role')=='assistant'and not r.get('tool_calls')and isinstance(r.get('content'),str)and r['content'].strip()]
    if not final:raise ValueError('factual_revision_native_final_assistant_missing')
    normalization=pipeline.generator._last_provider_normalization
    if (not isinstance(normalization,dict)or normalization.get('provider')!='hermes-cli'or normalization.get('stage_job_id')!=JOB
            or normalization.get('normalized_title')!=draft.get('title')or normalization.get('normalized_body')!=draft.get('body')):
        raise ValueError('factual_revision_actual_provider_normalization_missing')
    raw=final[-1]['content'];brief=scoped['twitter']
    bounded=pipeline.generator._bounded_provider_content(raw,brief)
    parsed=pipeline.generator._coerce_provider_draft(bounded,pipeline.store.get_job(JOB)['topic'])
    observed={'title':str(parsed.get('title')or''),'body':str(parsed.get('body')or'')}
    if observed!=normalization['provider_input']:raise ValueError('factual_revision_native_final_not_generated_candidate')
    evidence={'version':'factual-revision-current-generation-v1','task_id':task,'job_id':JOB,'nonce':proof['nonce'],
        'session_id':session['id'],'model':session['model'],'api_call_count':session['api_call_count'],
        'started_at':session['started_at'],'ended_at':session['ended_at'],'session_sha256':digest(session),'messages_sha256':digest(messages),
        'native_final_sha256':hashlib.sha256(raw.encode()).hexdigest(),'provider_input_sha256':digest(observed),
        'normalized_generation_sha256':digest({'title':draft['title'],'body':draft['body']}),'generation_stage_only':True}
    ref=write_once(Path('/srv/hermes-worker-media/jobs')/task/('factual-revision-'+proof['nonce']+'.generation.private.json'),evidence)
    draft.setdefault('draft_meta',{})['factual_revision_generation_ref']=ref
    return draft

def run_factual_revision(pipeline,proof_path,proof_sha256):
    from .native_quality_runner import current_active_role
    from .platform_workflow_context import load_platform_workflow_context
    from .visual_policy_gate import validate_content_policy_inputs
    from .intelligence import prepare_generation_strategy_inputs
    from .task_source_inputs import project_task_source_brief
    from .workflow_runtime import WorkflowStepRunner,WorkflowBlocked,strict_workflow_lock
    home,task,route=current_active_role(600)
    if task in{ORIGIN,EXPIRED_SCOPE,FRESH_SCOPE} or not re.fullmatch('[a-f0-9]{32}',task)or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':
        raise PermissionError('factual_revision_new_current_no_publication_role_required')
    seconds=registered_current_scope(home,task)
    if seconds<600:raise PermissionError('factual_revision_remaining_budget_insufficient')
    proof=private_read(proof_path,proof_sha256);store=pipeline.store;job,candidate=validate_proof(store,proof)
    cfg=pipeline.generator.config
    if (cfg.get('provider')!='hermes-cli'or cfg.get('hermes_provider')!=route['provider']or cfg.get('hermes_model')!=route['model']
            or cfg.get('allow_fallback')is not False):raise PermissionError('factual_revision_current_model_binding_required')
    owner=pipeline._worker_id();workflow='wf_'+JOB;deadline=time.monotonic()+seconds
    alias_suffix='__factual_revision_'+proof['nonce']
    class RevisionRunner(WorkflowStepRunner):
        def _map(self,name):return name if name.endswith(alias_suffix)else name+alias_suffix
        def _deps(self,values):return[self._map(v)for v in(values or[])]
        def _assert_dependencies(self,values,step):return super()._assert_dependencies(values,step)
        def _guard(self):require_active_factual_revision(store,JOB,owner)
        def run(self,name,func,required=True,depends_on=None,require_output=False,input_payload=None):
            if name=='collect_native_source_inputs':raise PermissionError('factual_revision_source_cannot_replay')
            def bounded():
                self._guard();result=func();self._guard();return result
            return super().run(self._map(name),bounded,required,self._deps(depends_on),require_output,input_payload)
        def succeeded(self,name,output=None,required=True,depends_on=None,message=''):
            self._guard()
            return super().succeeded(self._map(name),output,required,self._deps(depends_on),message)
        def block(self,name,code,message,gate_result=None,depends_on=None):
            self._guard()
            return super().block(self._map(name),code,message,gate_result,self._deps(depends_on))
        def skipped(self,name,code,message,required=False,depends_on=None):
            self._guard()
            return super().skipped(self._map(name),code,message,required,self._deps(depends_on))
    with strict_workflow_lock(store,owner,workflow,seconds,pipeline.strict_serial):
        job,candidate=validate_proof(store,proof)
        # Before any new effect: O_EXCL marks this correction intent; unknown effects never auto-retry.
        write_once(Path(proof_path).parent/('factual-revision-'+proof['nonce']+'.invocation.private.json'),
            {'version':VERSION_V3,'task_id':task,'job_id':JOB,'proof_sha256':proof_sha256,'no_publish':True,'automatic_replay':False})
        if not store.claim(JOB,{'failed'},owner,max(1,math.floor(deadline-time.monotonic())),'generating'):raise RuntimeError('factual_revision_job_already_claimed')
        runner=RevisionRunner(store,workflow,JOB,notifier=pipeline.notifier)
        grant={'_seal':_SEAL,'thread_id':threading.get_ident(),'job_id':JOB,'owner':owner,'task_id':task,'deadline':deadline,'proof':proof}
        store._root_factual_revision=grant
        try:
            job=store.get_job(JOB)
            contexts={p:load_platform_workflow_context(p,plan=job['brief'])for p in job['platforms']}
            policy=validate_content_policy_inputs(job,contexts,store=store)
            if not policy.get('passed'):runner.block('validate_content_policy_inputs','content_policy_inputs_invalid','Current policy rejected correction inputs',policy)
            runner.succeeded('validate_content_policy_inputs',policy)
            hygiene=pipeline._content_hygiene(job)
            if hygiene.get('status')=='blocked':runner.block('run_content_hygiene','content_hygiene_blocked','Current topic dedup rejected correction',hygiene)
            runner.succeeded('run_content_hygiene',hygiene)
            from .current_strategy_refresh import refresh_current_strategy_inputs
            # The preserved 1023 observation has passed its original 900s window.
            # Root explicitly authorized this new bounded read, not replay of 1023 or its topic Source.
            refreshed=refresh_current_strategy_inputs(store,pipeline.config,job,contexts,runner=runner)
            prepared=refreshed['brief']
            if (prepared.get('source_collection_audit')!=job['brief'].get('source_collection_audit')
                    or prepared.get('production_intent')!=job['brief'].get('production_intent')or prepared.get('sources')!=job['brief'].get('sources')):
                raise ValueError('factual_revision_original_Source_facts_changed_by_strategy_refresh')
            store.record_event(JOB,'factual_revision_current_strategy_refreshed',{'nonce':proof['nonce'],'audit':refreshed['strategy_refresh_audit']})
            prepared['factual_revision_request']={'version':VERSION_V3,'requested_topic':job['topic'],'editorial_candidate':candidate,
                'original_rejected_session':SESSION,'original_failure_step_id':5362,'source_is_research_only':True,'measured_outcome_claimed':False}
            from .task_source_inputs import refresh_task_source_contexts
            contexts=refresh_task_source_contexts(contexts,prepared)
            scoped={p:pipeline._bind_platform_source_inputs(JOB,b,p,contexts[p],owner)for p,b in refreshed['platform_briefs'].items()}
            for p,b in scoped.items():b['factual_revision_request']=prepared['factual_revision_request']
            runner.succeeded('run_operation_strategy',{'strategy_gates':{p:b['strategy_evidence_gate']for p,b in scoped.items()}},depends_on=['run_content_hygiene'])
            draft=runner.run('generate_content',lambda:generation_once(pipeline,home,task,route,proof,scoped),depends_on=['run_operation_strategy'],require_output=True)
            grant.update(prepared_brief=prepared,platform_briefs=scoped,draft=draft)
            return pipeline.continue_revised_draft(JOB,owner,workflow,runner,contexts,prepared,scoped,draft)
        except WorkflowBlocked as error:
            if store.get_job(JOB).get('lease_owner')==owner:
                return pipeline._hydrate(store.release_claim(JOB,owner,'blocked','factual_revision_blocked',error,detail={'step':error.step,'reason_code':error.reason_code,'nonce':proof['nonce']}))
            raise
        except BaseException as error:
            if store.get_job(JOB).get('lease_owner')==owner:store.release_claim(JOB,owner,'failed','factual_revision_failed',str(error))
            raise
        finally:
            store._root_factual_revision=None
