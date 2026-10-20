"""Root-authorized same generated draft, current-role native render/QA; no primary generation."""
import copy,hashlib,json,math,os,re,sqlite3,threading,time
from datetime import datetime,timezone
from pathlib import Path
from .factual_candidate_revision import digest,private_read,write_once,registered_current_scope

VERSION='same-generated-candidate-twitter-target-resume-v4'
TARGET_NONCE='99195e017f461068797702944f6b902c'
TARGET_SCOPE='b876ce921737463c80be15ccd0b73ac1'
HYGIENE_NONCE='c6dbf2daa10cd353de3e050057e6871c'
HYGIENE_SCOPE='ddbe2d72a5264188b2d91cd28cc10a94'
HYGIENE_ERROR="name 'hygiene' is not defined"
SIGNATURE_NONCE='171529766840fe6ab297a75f8b53adf8'
SIGNATURE_SCOPE='5e3bb1795b724fdd83bf5901929df626'
SIGNATURE_ERROR="Pipeline._continue_generated_draft() missing 1 required positional argument: 'draft'"
JOB='25110343c3354385'
ORIGIN='42f5bbd84ef64a75a37673d621acc559'
OLD_NONCE='363f142632b082635779fd983ae2a313'
SID='20261014_165643_e10b8e'
GENREF={'path':'/srv/hermes-worker-media/jobs/'+ORIGIN+'/factual-revision-'+OLD_NONCE+'.generation.private.json',
        'sha256':'c0dc812e7cbd8394c3dfae3fc1c48fe39455a38ad162edfd2bd54ee3bdfb838f'}
NORMALIZED='499741e1e77470353f7ed83f1c9ea0bd9d344152e30dc75b9e97b8ffc63b0518'

def original_model():
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+ORIGIN);db=home/'state.db'
    if any(p.is_symlink()for p in(db,*db.parents)):raise PermissionError('same_draft_original_session_path_changed')
    with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)as conn:
        conn.row_factory=sqlite3.Row;s=dict(conn.execute('SELECT * FROM sessions WHERE id=?',(SID,)).fetchone())
        messages=[dict(r)for r in conn.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id',(SID,))]
    record=private_read(GENREF['path'],GENREF['sha256'])
    if (s.get('api_call_count')!=2 or not s.get('ended_at')or s.get('model')!=record['model']
            or digest(s)!=record['session_sha256']or digest(messages)!=record['messages_sha256']
            or record['normalized_generation_sha256']!=NORMALIZED):raise ValueError('same_draft_original_native_generation_changed')
    return record

def materialize_original_generated_candidate(store):
    """Pure replay of deterministic formatting, never the model or Source action."""
    from .generator import DraftGenerator,strip_web_residue
    from .humanize import naturalize_copy
    record=original_model();step=next(r for r in store.workflow_steps(JOB)if r['id']==5393)
    out=step['output'];meta=copy.deepcopy(out['draft_meta'])
    db=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+ORIGIN)/'state.db'
    with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)as conn:
        conn.row_factory=sqlite3.Row
        message=dict(conn.execute('SELECT * FROM messages WHERE session_id=? AND id=6',(SID,)).fetchone())
    raw=message.get('content')
    if not isinstance(raw,str)or hashlib.sha256(raw.encode()).hexdigest()!=record['native_final_sha256']:
        raise ValueError('same_draft_native_final_changed')
    parsed=json.loads(raw)
    if digest({'title':str(parsed.get('title')or''),'body':str(parsed.get('body')or'')})!=record['provider_input_sha256']:
        raise ValueError('same_draft_original_provider_input_changed')
    body=str(parsed.get('body')or'').strip();cta=parsed.get('cta')or meta['style']['cta']
    if cta and cta not in body:body=body.rstrip()+'\n\n'+cta
    body=DraftGenerator._fit_article_length(naturalize_copy(strip_web_residue(body),meta)['body'],meta)
    if digest({'title':str(parsed['title']),'body':body})!=NORMALIZED:
        raise ValueError('same_draft_deterministic_normalization_changed')
    return {'title':str(parsed['title']),'body':body,'provider':out['provider'],'prompt_version':out['prompt_version'],'draft_meta':meta}

def prepare_same_generated_proof(store,nonce,directory,code_pins):
    """Root600 materialization and exact history, no canonical business writes."""
    if not re.fullmatch('[a-f0-9]{32}',nonce)or nonce in{OLD_NONCE,SIGNATURE_NONCE,HYGIENE_NONCE,TARGET_NONCE}:raise PermissionError('same_draft_new_nonce_required')
    directory=Path(directory)
    if directory!=store.path.parent/'quality_runtime':raise PermissionError('same_draft_owned_Root_preparation_path_required')
    history={'job':store.get_job(JOB),'steps':store.workflow_steps(JOB),'events':store.events(JOB)}
    draft=materialize_original_generated_candidate(store)
    prepared=next(r['output']for r in history['steps']if r['id']==5390)
    history_ref=write_once(directory/('same-draft-'+nonce+'.history.private.json'),history)
    draft_ref=write_once(directory/('same-draft-'+nonce+'.draft.private.json'),draft)
    prepared_ref=write_once(directory/('same-draft-'+nonce+'.prepared.private.json'),prepared)
    proof={'version':VERSION,'job_id':JOB,'origin_task_id':ORIGIN,'nonce':nonce,'no_publish':True,'budget_seconds':900,
        'history_ref':history_ref,'draft_ref':draft_ref,'prepared_brief_ref':prepared_ref,'code_pins':code_pins}
    validate(type('RootReadOnly',(),{'store':store})(),proof)
    return write_once(directory/('same-draft-'+nonce+'.proof.private.json'),proof)

def read_history(ref):
    # Full history has its own bounded Root600 file; caller-visible proof remains small.
    return private_read(ref['path'],ref['sha256'],limit=16777216)

def validate(pipeline,proof,initial=True):
    if (proof.get('version')!=VERSION or proof.get('job_id')!=JOB or proof.get('origin_task_id')!=ORIGIN
            or not re.fullmatch('[a-f0-9]{32}',str(proof.get('nonce')or''))or proof['nonce']in{OLD_NONCE,SIGNATURE_NONCE,HYGIENE_NONCE,TARGET_NONCE}
            or proof.get('budget_seconds')!=900 or proof.get('no_publish')is not True):
        raise PermissionError('same_draft_exact_known_depth_contract_required')
    history=read_history(proof['history_ref']);store=pipeline.store
    steps={r['id']:r for r in store.workflow_steps(JOB)};events={r['id']:r for r in store.events(JOB)}
    for row in history['steps']:
        if steps.get(row['id'])!=row:raise ValueError('same_draft_original_step_changed')
    for row in history['events']:
        if events.get(row['id'])!=row:raise ValueError('same_draft_original_event_changed')
    for identifier,name in ((5393,'generate_content'),(5395,'validate_content_structure'),(5396,'validate_real_world_ai_package'),(5397,'validate_factual_claims')):
        row=steps.get(identifier)or{}
        if row.get('status')!='SUCCEEDED'or not row.get('step_name','').startswith(name):raise PermissionError('same_draft_successful_prefix_changed')
    failure=steps.get(5398)or{}
    if failure.get('status')!='BLOCKED'or failure.get('step_name')!='validate_content_depth__factual_revision_'+OLD_NONCE or failure.get('gate',{}).get('failures')!=['continuation_without_series_plan']:
        raise PermissionError('same_draft_only_known_depth_failure_required')
    if steps[5393]['output']['draft_meta']['factual_revision_generation_ref']!=GENREF:raise ValueError('same_draft_generation_receipt_changed')
    bound=steps.get(5399)or{}
    failed=events.get(7525)or{}
    if (bound.get('step_name')!='bind_existing_generated_candidate__same_draft_'+SIGNATURE_NONCE or bound.get('status')!='SUCCEEDED'
            or failed.get('event')!='same_draft_suffix_failed'or json.loads(failed.get('detail_json')or'{}').get('error')!=SIGNATURE_ERROR
            ):
        raise PermissionError('same_draft_only_known_signature_failure_required')
    failed_home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+SIGNATURE_SCOPE)
    for name in('state.db','state.db-wal','state.db-shm'):
        item=failed_home/name
        if item.exists()or item.is_symlink():raise PermissionError('same_draft_signature_failure_model_effect_unknown')
    expected={5400:'bind_existing_generated_candidate',5401:'validate_content_structure',5402:'validate_real_world_ai_package',5403:'validate_factual_claims',5404:'validate_content_depth',5405:'run_fact_check',5407:'run_safety_gate'}
    for identifier,name in expected.items():
        row=steps.get(identifier)or{}
        if row.get('step_name')!=name+'__same_draft_'+HYGIENE_NONCE or row.get('status')!='SUCCEEDED':raise PermissionError('same_draft_known_post_signature_prefix_changed')
    failure=events.get(7537)or{}
    if ({r['id']for r in history['steps']if 5398<r['id']<5409}!={5399}|set(expected)or failure.get('event')!='same_draft_suffix_failed'
            or json.loads(failure.get('detail_json')or'{}').get('error')!=HYGIENE_ERROR):
        raise PermissionError('same_draft_only_known_hygiene_name_failure_required')
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+HYGIENE_SCOPE)
    for name in('state.db','state.db-wal','state.db-shm'):
        item=home/name
        if item.exists()or item.is_symlink():raise PermissionError('same_draft_hygiene_failure_native_model_effect_unknown')
    target_expected={5409:'bind_existing_generated_candidate',5410:'validate_current_suffix_hygiene',5411:'validate_content_structure',5412:'validate_real_world_ai_package',5413:'validate_factual_claims',5414:'validate_content_depth',5415:'run_fact_check',5417:'run_safety_gate'}
    for identifier,name in target_expected.items():
        row=steps.get(identifier)or{}
        if row.get('step_name')!=name+'__same_draft_'+TARGET_NONCE or row.get('status')!='SUCCEEDED':raise PermissionError('same_draft_known_target_prefix_changed')
    row=steps.get(5419)or{};gate=row.get('gate',{});allgates=gate.get('gates',{})
    failure=events.get(7553)or{}
    detail=json.loads(failure.get('detail_json')or'{}')
    if (row.get('step_name')!='run_quality_gate__same_draft_'+TARGET_NONCE or row.get('status')!='BLOCKED'
            or row.get('reason_code')!='quality_gate_failed' or gate.get('passed')is not False
            or set(allgates)!={'G1_risk_compliance','G2_geo','G3_anti_generic','G4_media_assets','G5_format','G6_platform_quality','G7_growth_recipe'}
            or any(value.get('passed')is not True for key,value in allgates.items()if key!='G6_platform_quality')
            or allgates['G6_platform_quality'].get('mode')!='enforce'
            or allgates['G6_platform_quality'].get('results')!={'twitter':{'passed':False,'failed_dimensions':['x_text_length']}}
            or failure.get('event')!='same_draft_suffix_blocked'
            or detail!={'step':'run_quality_gate__same_draft_'+TARGET_NONCE,'reason_code':'quality_gate_failed','nonce':TARGET_NONCE}
            or {r['id']for r in history['steps']if r['id']>5398}!={5399}|set(expected)|set(target_expected)|{5419}):
        raise PermissionError('same_draft_only_known_target_length_failure_required')
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+TARGET_SCOPE)
    if any((home/name).exists()or(home/name).is_symlink()for name in('state.db','state.db-wal','state.db-shm')):
        raise PermissionError('same_draft_previous_target_model_effect_unknown')
    invocation=private_read(Path('/srv/ai-self-media-tools/data/quality_runtime')/('same-draft-'+TARGET_NONCE+'.invocation.private.json'))
    if invocation.get('task_id')!=TARGET_SCOPE or invocation.get('job_id')!=JOB or invocation.get('no_publish')is not True:
        raise PermissionError('same_draft_original_target_nonce_consumption_missing')
    original_model()
    draft=private_read(proof['draft_ref']['path'],proof['draft_ref']['sha256'])
    if (digest({'title':draft['title'],'body':draft['body']})!=NORMALIZED or draft['title']!=steps[5393]['output']['title']
            or draft.get('draft_meta')!=steps[5393]['output']['draft_meta']or draft.get('provider')!='hermes-cli'):
        raise ValueError('same_draft_exact_normalized_candidate_required')
    prepared=private_read(proof['prepared_brief_ref']['path'],proof['prepared_brief_ref']['sha256'])
    if steps.get(5390,{}).get('status')!='SUCCEEDED'or prepared!=steps[5390].get('output'):raise ValueError('same_draft_original_prepared_step_changed')
    if prepared.get('production_intent')!=history['job']['brief'].get('production_intent')or prepared.get('source_collection_audit')!=history['job']['brief'].get('source_collection_audit'):
        raise ValueError('same_draft_original_factual_intent_changed')
    for pin in proof.get('code_pins')or[]:
        if hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('same_draft_deployed_code_changed')
    required_pins={'/srv/ai-self-media-tools/content_platform/'+name+'.py'for name in('generated_candidate_resume','target_adaptation','generator','pipeline','formatters','content_depth')}
    if {pin.get('path')for pin in proof.get('code_pins')or[]}!=required_pins or len(proof['code_pins'])!=len(required_pins):raise PermissionError('same_draft_six_exact_code_pins_required')
    job=store.get_job(JOB)
    if initial:
        if (job!=history['job']or job.get('state')!='blocked'or job.get('attempts')!=7 or job.get('last_error')!='required quality gate failed' or job.get('lease_owner')
                or store.draft_versions(JOB)or store.artifacts(JOB)or store.platform_outputs(JOB)
                or store.workflow_steps(JOB)!=history['steps']or store.events(JOB)!=history['events']):
            raise PermissionError('same_draft_original_zero_output_state_changed')
    return job,copy.deepcopy(draft),prepared

def run_generated_candidate_resume(pipeline,proof_path,proof_sha256):
    from .native_quality_runner import current_active_role
    from .platform_workflow_context import load_platform_workflow_context
    from .task_source_inputs import refresh_task_source_contexts,project_task_source_brief
    from .workflow_runtime import WorkflowStepRunner,WorkflowBlocked,strict_workflow_lock
    from .content_depth import build_content_depth_plan,validate_content_depth_plan
    home,task,route=current_active_role(600)
    if task in{ORIGIN,SIGNATURE_SCOPE,HYGIENE_SCOPE,TARGET_SCOPE} or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':raise PermissionError('same_draft_new_no_publication_scope_required')
    seconds=registered_current_scope(home,task)
    if seconds<600:raise PermissionError('same_draft_remaining_budget_insufficient')
    proof=private_read(proof_path,proof_sha256);store=pipeline.store;job,draft,prepared=validate(pipeline,proof)
    owner=pipeline._worker_id();workflow='wf_'+JOB;deadline=time.monotonic()+seconds;suffix='__same_draft_'+proof['nonce']
    original_gen='generate_content__factual_revision_'+OLD_NONCE
    def guard():
        _,cid,_=current_active_role(0)
        current=store.get_job(JOB)
        if (cid!=task or time.monotonic()>=deadline or current.get('lease_owner')!=owner or current.get('state')!='generating'
                or datetime.fromisoformat(current['lease_expires_at'].replace('Z','+00:00')).timestamp()<=time.time()):
            raise PermissionError('same_draft_current_role_and_original_deadline_required')
        validate(pipeline,proof,initial=False)
    class Runner(WorkflowStepRunner):
        def _map(self,name):return name if name.endswith(suffix)else name+suffix
        def _deps(self,names):return[original_gen if n=='generate_content'else self._map(n)for n in(names or[])]
        def run(self,name,func,required=True,depends_on=None,require_output=False,input_payload=None):
            if name in{'generate_content','collect_native_source_inputs'}:raise PermissionError('same_draft_primary_generation_and_Source_forbidden')
            def bounded():guard();result=func();guard();return result
            return super().run(self._map(name),bounded,required,self._deps(depends_on),require_output,input_payload)
        def succeeded(self,name,output=None,required=True,depends_on=None,message=''):
            if name in{'generate_content','collect_native_source_inputs'}:raise PermissionError('same_draft_original_success_cannot_rewrite')
            guard();return super().succeeded(self._map(name),output,required,self._deps(depends_on),message)
        def block(self,name,code,message,gate_result=None,depends_on=None):guard();return super().block(self._map(name),code,message,gate_result,self._deps(depends_on))
        def skipped(self,name,code,message,required=False,depends_on=None):guard();return super().skipped(self._map(name),code,message,required,self._deps(depends_on))
    with strict_workflow_lock(store,owner,workflow,seconds,pipeline.strict_serial):
        job,draft,prepared=validate(pipeline,proof)
        write_once(Path(proof_path).parent/('same-draft-'+proof['nonce']+'.invocation.private.json'),{'version':VERSION,'task_id':task,'job_id':JOB,'proof_sha256':proof_sha256,'no_publish':True,'automatic_replay':False})
        if not store.claim(JOB,{'blocked'},owner,max(1,math.floor(deadline-time.monotonic())),'generating'):raise RuntimeError('same_draft_already_claimed')
        runner=Runner(store,workflow,JOB,notifier=pipeline.notifier)
        try:
            # Only metadata is re-evaluated under the fixed classifier; candidate bytes remain exact.
            old=draft['draft_meta']['content_depth_plan']
            rebuilt=build_content_depth_plan(draft['title'],draft['body'],evidence=old.get('evidence'),actions=old.get('steps'),series_plan=old.get('series_plan'),platform='twitter')
            if not validate_content_depth_plan(rebuilt)['passed']:runner.block('validate_content_depth','content_depth_contract_failed','Same candidate failed current depth rules',validate_content_depth_plan(rebuilt))
            draft['draft_meta']['content_depth_plan']=rebuilt
            contexts={'twitter':load_platform_workflow_context('twitter',plan=prepared)}
            contexts=refresh_task_source_contexts(contexts,prepared)
            scoped={'twitter':project_task_source_brief(prepared,'twitter')}
            runner.succeeded('bind_existing_generated_candidate',{'origin_generation_step':5393,'generation_ref':GENREF,'normalized_generation_sha256':NORMALIZED,'primary_generation_calls':0,'Source_calls':0})
            from .target_adaptation import generate_target_adaptation
            ref=runner.run('adapt_twitter_target_copy',lambda:generate_target_adaptation(pipeline,store.get_job(JOB),draft,prepared,runner),required=True,depends_on=['bind_existing_generated_candidate'],require_output=True,
                           input_payload={'source_generation_ref':GENREF,'source_long_sha256':NORMALIZED,'current_model_required':True})
            draft['draft_meta']['target_adaptation_ref']=ref
            # Authenticated public wrapper invokes the unchanged normal generated-draft suffix.
            job=store.get_job(JOB)
            return pipeline._continue_generated_draft(JOB,owner,workflow,runner,contexts,job,prepared,scoped,draft)
        except WorkflowBlocked as error:
            if store.get_job(JOB).get('lease_owner')==owner:return pipeline._hydrate(store.release_claim(JOB,owner,'blocked','same_draft_suffix_blocked',error,detail={'step':error.step,'reason_code':error.reason_code,'nonce':proof['nonce']}))
            raise
        except BaseException as error:
            if store.get_job(JOB).get('lease_owner')==owner:store.release_claim(JOB,owner,'failed','same_draft_suffix_failed',str(error))
            raise
