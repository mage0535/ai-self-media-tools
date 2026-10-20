"""Normal saved-media quality revision; refresh strategy, never regenerate content/assets."""
import copy,hashlib,json,math,os,re,time
from datetime import datetime,timezone
from pathlib import Path

VERSION='normal-rendered-quality-revision-v1'
_ACTIVE={}
FACT_FIELDS=('production_intent','claim_ledger','sources','factual_sources','factual_reference_posts',
 'original_method_factual_inputs','original_method_observed_ref','original_method_source_ref')

def digest(value):
    def blob(item):
        if isinstance(item,bytes):return {'sqlite_blob_sha256':hashlib.sha256(item).hexdigest(),'sqlite_blob_bytes':len(item)}
        raise TypeError('unsupported_original_record_type:'+type(item).__name__)
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False,default=blob).encode()).hexdigest()
def _key(store,job_id):return(str(Path(store.path).resolve()),job_id)

def _saved_rendered_group(history):
    """Select the current plan's actual four-image group, preserving older groups."""
    from .factual_candidate_revision import private_read
    job=history['job'];ref=(job.get('draft_meta')or{}).get('current_visual_plan_ref')
    if not ref:
        rows=[r for r in history['steps']if r.get('step_name')=='generate_or_collect_images'and r.get('status')=='SUCCEEDED']
        if len(rows)!=1 or len((rows[0].get('output')or{}).get('images')or[])!=4:raise PermissionError('rendered_quality_original_four_image_group_required')
        return rows[0]
    def same_ref(left,right):
        return isinstance(left,dict)and isinstance(right,dict)and all(left.get(k)==right.get(k)for k in('path','sha256'))
    rows=[r for r in history['steps']if r.get('status')=='SUCCEEDED'and same_ref((r.get('output')or{}).get('current_visual_plan_ref'),ref)and len((r.get('output')or{}).get('images')or[])==4]
    if len(rows)!=1:raise PermissionError('rendered_quality_one_current_plan_group_required')
    row=rows[0];result=row['output'];actual_ref=result['current_visual_plan_ref'];path=Path(ref['path'])
    if any(p.is_symlink()for p in(path,*path.parents))or not path.is_file():raise PermissionError('rendered_quality_current_plan_original_required')
    plan=private_read(path,ref['sha256'],limit=262144)
    if actual_ref.get('bytes',path.stat().st_size)!=path.stat().st_size:raise ValueError('rendered_quality_current_plan_size_changed')
    if (plan.get('version')!='current_image_text_visual_plan_v1'or plan.get('job_id')!=job['id']or job.get('platforms')!=[plan.get('platform')]
            or plan.get('draft_source_sha256')!=digest({'title':job.get('title'),'body':job.get('body')})):
        raise ValueError('rendered_quality_current_plan_content_changed')
    images=result['images'];aux=result.get('auxiliary_artifacts')or[]
    if (len(aux)!=2 or {r.get('kind')for r in aux}!={'rights','render_manifest'}
            or len({r.get('path')for r in images})!=4 or sum(r.get('role')=='cover'for r in images)!=1
            or [(r.get('role'),r.get('section'))for r in images]!=[(r.get('role'),r.get('id'))for r in plan.get('slots')or[]]):
        raise ValueError('rendered_quality_current_complete_slots_required')
    originals=history['artifacts']
    for item in images+aux:
        p=Path(item['path']);kind=('cover'if item.get('role')=='cover'else'image')if item in images else item['kind']
        matches=[r for r in originals if r.get('kind')==kind and r.get('path')==str(p)and r.get('checksum')==item.get('checksum')]
        if (len(matches)!=1 or any(v.is_symlink()for v in(p,*p.parents))or not p.is_file()
                or hashlib.sha256(p.read_bytes()).hexdigest()!=item['checksum']):raise ValueError('rendered_quality_current_registered_asset_changed')
    aux={r['kind']:r for r in aux};rights=private_read(aux['rights']['path'],aux['rights']['checksum']);manifest=private_read(aux['render_manifest']['path'],aux['render_manifest']['checksum'])
    if (rights.get('version')!='current_image_text_rights_v1'or manifest.get('version')!='current_image_text_render_manifest_v1'
            or any(r.get('job_id')!=job['id']or not same_ref(r.get('plan_ref'),actual_ref)for r in(rights,manifest))
            or not same_ref(manifest.get('rights'),{'path':aux['rights']['path'],'sha256':aux['rights']['checksum']})
            or [(r.get('role'),r.get('file',{}).get('path'),r.get('file',{}).get('sha256'))for r in manifest.get('images')or[]]!=[(r.get('role'),r.get('path'),r.get('checksum'))for r in images]):
        raise ValueError('rendered_quality_current_manifest_or_rights_changed')
    return row

def validate_saved_candidate(snapshot,current,versions,artifacts,*,initial=True):
    """Only immutable saved text/assets; state/strategy updates are separate explicit work."""
    original=snapshot['job']
    if current['id']!=original['id']or current['platforms']!=original['platforms']:
        raise ValueError('rendered_quality_owner_changed')
    for field in ('title','body','prompt_version'):
        if current.get(field)!=original.get(field):raise ValueError('rendered_quality_primary_changed')
    if not versions or versions[:len(snapshot['draft_versions'])]!=snapshot['draft_versions']:
        raise ValueError('rendered_quality_original_drafts_changed')
    if artifacts!=snapshot['artifacts']:raise ValueError('rendered_quality_original_artifacts_changed')
    for row in artifacts:
        p=Path(row['path'])
        if (any(v.is_symlink()for v in(p,*p.parents))or not p.is_file()
            or hashlib.sha256(p.read_bytes()).hexdigest()!=row['checksum']):raise ValueError('rendered_quality_original_asset_bytes_changed')
    original_meta=original.get('draft_meta')or{};current_meta=current.get('draft_meta')or{}
    mutable_meta={'quality_scores','quality_gate','platform_quality_gates','native_quality','final_quality_evidence','rendered_quality_revision','account_analysis','same_lane_intelligence','strategy_evidence','strategy_evidence_gate','strategy_observation_ref','viral_collection','viral_breakdown','hot_work_parameter_pack','platform_intelligence_constraints','historical_feedback','platform_historical_feedback','topic_historical_feedback','cluster_memory','legacy_feedback_reference'}
    if any(current_meta.get(field)!=value for field,value in original_meta.items()if field not in mutable_meta):raise ValueError('rendered_quality_primary_target_visual_lineage_changed')
    for field in FACT_FIELDS:
        if (current.get('brief')or{}).get(field)!=(original.get('brief')or{}).get(field):raise ValueError('rendered_quality_original_facts_changed')
    if initial and (current!=original or versions!=snapshot['draft_versions']):raise ValueError('rendered_quality_original_snapshot_changed')
    return True

def prepare_rendered_quality_revision(store,job_id,origin_task_id,nonce,directory,code_pins,*,original_checkpoint_code_archive_ref=None):
    from .factual_candidate_revision import write_once
    if not re.fullmatch('[a-f0-9]{16}',job_id)or not re.fullmatch('[a-f0-9]{32}',origin_task_id)or not re.fullmatch('[a-f0-9]{32}',nonce):raise ValueError('rendered_quality_identifiers_invalid')
    directory=Path(directory)
    if directory!=Path(store.path).parent/'quality_runtime':raise PermissionError('rendered_quality_owned_directory_required')
    snapshot={'job':store.get_job(job_id),'draft_versions':store.draft_versions(job_id),'artifacts':store.artifacts(job_id),'steps':store.workflow_steps(job_id),'events':store.events(job_id)}
    job=snapshot['job']
    if len(job.get('platforms')or[])!=1 or job.get('state')!='failed'or job.get('lease_owner')or not job.get('title')or not job.get('body')or not snapshot['draft_versions']or store.platform_outputs(job_id):raise PermissionError('rendered_quality_failed_saved_unpublished_required')
    if not str(job.get('last_error')or'').startswith(("Expecting ", 'protocol_error:', 'typed_protocol_error:')):raise PermissionError('rendered_quality_known_protocol_failure_required')
    snapshot['protocol_failure']=_protocol_failure_snapshot(store,job_id,origin_task_id)
    snapshot['rendered_group_step_id']=_saved_rendered_group(snapshot)['id']
    if original_checkpoint_code_archive_ref is not None:
        snapshot['original_checkpoint_code_archive_ref']=original_checkpoint_code_archive_ref
    from .native_stage_resume import _effect_counts
    snapshot['effects']=_effect_counts(store,job_id)
    if any(snapshot['effects'].get(k,0)for k in('approvals','deliveries','delivery_queue','platform_outputs','review_tasks','delivery_intents','publish_receipts')):
        raise PermissionError('rendered_quality_original_publishing_effects_forbidden')
    proof={'version':VERSION,'job_id':job_id,'origin_task_id':origin_task_id,'nonce':nonce,'no_publish':True,'budget_seconds':900,'refresh_strategy':True,'code_pins':code_pins,
        'history_ref':write_once(directory/('rendered-quality-'+nonce+'.history.private.json'),snapshot)}
    _validate_proof(store,proof)
    return write_once(directory/('rendered-quality-'+nonce+'.proof.private.json'),proof)

def _protocol_failure_snapshot(store,job_id,origin_task_id,attempt_path=None):
    from .target_adaptation import native_session
    root=Path(store.path).parent/'quality_runtime'/job_id
    attempted=[Path(attempt_path)]if attempt_path is not None else[p.parent for p in root.glob('*/attempts/*/vlm.native-failure.json')]
    if any(not p.resolve().is_relative_to(root.resolve())or p.parent.name!='attempts'for p in attempted):raise PermissionError('rendered_quality_protocol_attempt_scope_invalid')
    actual=[]
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+origin_task_id)
    from .factual_candidate_revision import current_generation_records
    sessions=current_generation_records(home)
    if not sessions or any(not row.get('ended_at')for row in sessions):raise PermissionError('rendered_quality_origin_unknown_or_running_model_rejected')
    for attempt in attempted:
        paths=[attempt/name for name in ('vlm.native-failure.json','vlm.native-stdout.log','vlm.usage.json','prepared-context.json')]
        if any(any(q.is_symlink()for q in(p,*p.parents))or not p.is_file()or p.stat().st_uid!=0 or p.stat().st_mode&0o077 or p.stat().st_nlink!=1 or not 0<p.stat().st_size<=4194304 for p in paths):raise PermissionError('rendered_quality_protocol_private_source_required')
        failure=json.loads(paths[0].read_bytes())
        if failure.get('error_type') not in {'JSONDecodeError','NativeQualityProtocolError'}:continue
        stdout=paths[1]
        try:json.loads(stdout.read_text())
        except json.JSONDecodeError:pass
        else:continue
        usage=json.loads(paths[2].read_bytes())
        if usage.get('completed')is not True or usage.get('failed')is True or usage.get('partial')is True or usage.get('interrupted')is True:continue
        if usage.get('session_id') not in {row['id'] for row in sessions}:continue
        session,messages,raw=native_session(home,usage['session_id'])
        if not session.get('ended_at')or raw.strip()!=stdout.read_text().strip():continue
        actual.append({'attempt':str(attempt),'session_sha256':digest(session),'messages_sha256':digest(messages),
            'files':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}for p in paths]})
    if len(actual)!=1:raise PermissionError('rendered_quality_one_actual_completed_protocol_failure_required')
    return actual[0]

def _validate_proof(store,proof,*,initial=True):
    from .factual_candidate_revision import private_read
    from .target_adaptation import native_session
    if set(proof)!={'version','job_id','origin_task_id','nonce','no_publish','budget_seconds','refresh_strategy','code_pins','history_ref'}or not re.fullmatch('[a-f0-9]{16}',str(proof.get('job_id')or''))or not re.fullmatch('[a-f0-9]{32}',str(proof.get('origin_task_id')or''))or not re.fullmatch('[a-f0-9]{32}',str(proof.get('nonce')or''))or proof.get('version')!=VERSION or proof.get('no_publish')is not True or proof.get('budget_seconds')!=900 or proof.get('refresh_strategy')is not True:raise PermissionError('rendered_quality_exact_contract_required')
    job_id=proof['job_id'];history=private_read(proof['history_ref']['path'],proof['history_ref']['sha256'],limit=16777216)
    if history['job'].get('state')!='failed'or history['job'].get('lease_owner'):raise PermissionError('rendered_quality_original_failed_unpublished_required')
    if initial and store.platform_outputs(job_id):raise PermissionError('rendered_quality_existing_outputs_not_revisable')
    validate_saved_candidate(history,store.get_job(job_id),store.draft_versions(job_id),store.artifacts(job_id),initial=initial)
    steps={r['id']:r for r in store.workflow_steps(job_id)};events={r['id']:r for r in store.events(job_id)}
    if any(steps.get(r['id'])!=r for r in history['steps'])or any(events.get(r['id'])!=r for r in history['events']):raise ValueError('rendered_quality_original_history_changed')
    if _protocol_failure_snapshot(store,job_id,proof['origin_task_id'],history.get('protocol_failure',{}).get('attempt'))!=history.get('protocol_failure'):raise ValueError('rendered_quality_original_protocol_evidence_changed')
    selected=_saved_rendered_group(history)
    if history.get('rendered_group_step_id',selected['id'])!=selected['id']:raise ValueError('rendered_quality_current_image_group_changed')
    source_ref=(history['job'].get('draft_meta')or{}).get('normal_completed_target_checkpoint_ref')
    if source_ref:
        from .native_stage_resume import validate_completed_target_checkpoint
        source=private_read(source_ref['path'],source_ref['sha256'])
        validate_completed_target_checkpoint(store,source,initial=False,original_code_archive_ref=history.get('original_checkpoint_code_archive_ref'))
    if initial:
        from .native_stage_resume import _effect_counts
        effects=_effect_counts(store,job_id)
        if any(effects.get(k,0)for k in('approvals','deliveries','delivery_queue','platform_outputs','review_tasks','delivery_intents','publish_receipts')):
            raise PermissionError('rendered_quality_original_publishing_effects_forbidden')
        if 'effects'in history and effects!=history['effects']:raise ValueError('rendered_quality_original_effects_changed')
    required={'native_quality_resume.py','pipeline.py','mandatory_release_gate.py','native_quality_runner.py','current_strategy_refresh.py','task_source_inputs.py','intelligence.py','growth_policy.py','store.py'}
    pins=proof.get('code_pins')or[]
    if not required<={Path(row['path']).name for row in pins}:raise PermissionError('rendered_quality_deployed_code_pins_required')
    for row in pins:
        p=Path(row['path'])
        if any(q.is_symlink()for q in(p,*p.parents))or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('rendered_quality_deployed_source_changed')
    return history

def binding_step_name(store,job_id,platform):
    grant=_ACTIVE.get(_key(store,job_id))
    if grant is None:return None
    grant['guard']()
    if platform not in grant['platforms']:raise PermissionError('rendered_quality_binding_platform_changed')
    return 'bind_rendered_artifact_sources__quality_revision_'+grant['nonce']

def record_binding_reference(store,job_id,platform,manifest_ref):
    from .factual_candidate_revision import write_once,private_read
    grant=_ACTIVE.get(_key(store,job_id))
    if grant is None:return None
    grant['guard']();name=binding_step_name(store,job_id,platform)
    rows=[r for r in store.workflow_steps(job_id)if r.get('step_name')==name and r.get('platform')==platform]
    if len(rows)!=1 or rows[0].get('status')!='SUCCEEDED'or rows[0].get('output')!={'artifact_manifest':manifest_ref}:raise ValueError('rendered_quality_actual_binding_row_required')
    record={'version':VERSION,'job_id':job_id,'platform':platform,'task_id':grant['task'],'nonce':grant['nonce'],'row_id':rows[0]['id'],'row_sha256':digest(rows[0]),'manifest_ref':manifest_ref,'proof_ref':grant['proof_ref'],'no_publish':True}
    ref=write_once(Path(grant['proof_ref']['path']).parent/('rendered-quality-'+grant['nonce']+'.binding-'+platform+'.private.json'),record)
    store.record_event(job_id,'current_rendered_quality_binding',{'platform':platform,'binding_receipt_ref':ref})
    return ref

def current_binding(store,job_id,platform):
    from .factual_candidate_revision import private_read
    events=store.events(job_id)
    candidates=[r for r in events if r.get('event')in {'current_generation_checkpoint_binding','current_rendered_quality_binding','current_visual_revision_binding'}and json.loads(r['detail_json']).get('platform')==platform]
    if candidates and candidates[-1]['event']=='current_visual_revision_binding':return None
    if not candidates or candidates[-1]['event']!='current_rendered_quality_binding':
        from .native_stage_resume import current_binding as current_checkpoint_binding
        return current_checkpoint_binding(store,job_id,platform)
    matches=[json.loads(r['detail_json'])for r in store.events(job_id)if r.get('event')=='current_rendered_quality_binding'and json.loads(r['detail_json']).get('platform')==platform]
    if not matches:return None
    ref=matches[-1]['binding_receipt_ref'];record=private_read(ref['path'],ref['sha256']);proof=private_read(record['proof_ref']['path'],record['proof_ref']['sha256'])
    if record.get('version')!=VERSION or record.get('job_id')!=job_id or record.get('platform')!=platform or record.get('no_publish')is not True or proof.get('nonce')!=record.get('nonce'):raise PermissionError('rendered_quality_binding_identity_changed')
    history=_validate_proof(store,proof,initial=False)
    invocation=private_read(Path(record['proof_ref']['path']).parent/('rendered-quality-'+proof['nonce']+'.invocation.private.json'))
    if invocation.get('task_id')!=record['task_id']or invocation.get('proof_sha256')!=record['proof_ref']['sha256']or invocation.get('no_publish')is not True or invocation.get('job_id')!=job_id:raise PermissionError('rendered_quality_binding_invocation_changed')
    rows={r['id']:r for r in store.workflow_steps(job_id)};row=rows.get(record['row_id']);source=private_read(record['manifest_ref']['path'],record['manifest_ref']['sha256'])
    if not row or row.get('status')!='SUCCEEDED'or row.get('platform')!=platform or row.get('step_name')!='bind_rendered_artifact_sources__quality_revision_'+proof['nonce']or digest(row)!=record['row_sha256']or row.get('output')!={'artifact_manifest':record['manifest_ref']}:raise ValueError('rendered_quality_bound_row_changed')
    if source.get('job_id')!=job_id or source.get('platform')!=platform or source.get('draft_version_id')!=store.draft_versions(job_id)[-1]['id']:raise ValueError('rendered_quality_current_draft_binding_changed')
    from .intelligence import prepare_generation_strategy_inputs
    from .task_source_inputs import project_task_source_brief
    current_job=store.get_job(job_id)
    prepare_generation_strategy_inputs(current_job['topic'],project_task_source_brief(current_job['brief'],platform))
    return {'row':row,'manifest_ref':record['manifest_ref'],'binding_receipt_ref':ref}

def historical_completed_target_source_projection(job):
    """Validate old source using its archived code under a real new quality scope."""
    from .factual_candidate_revision import private_read
    from .native_stage_resume import _completed_target_readonly_store,validate_completed_target_checkpoint,read_completed_target_candidate
    store=_completed_target_readonly_store();grant=_ACTIVE.get(_key(store,job.get('id')))
    revision=(job.get('draft_meta')or{}).get('rendered_quality_revision')or{}
    ref=grant['proof_ref']if grant is not None else revision.get('proof_ref')
    if ref is None:return None
    if not isinstance(ref,dict)or set(ref)!={'path','sha256'}:raise PermissionError('rendered_quality_historical_source_proof_required')
    proof=private_read(ref['path'],ref['sha256']);history=_validate_proof(store,proof,initial=False)
    directory=Path(store.path).parent/'quality_runtime'
    if Path(ref['path'])!=directory/('rendered-quality-'+proof['nonce']+'.proof.private.json')or proof['job_id']!=job.get('id'):
        raise PermissionError('rendered_quality_historical_source_scope_changed')
    invocation=private_read(directory/('rendered-quality-'+proof['nonce']+'.invocation.private.json'))
    if (invocation.get('version')!=VERSION or invocation.get('job_id')!=job['id']or invocation.get('task_id')==proof['origin_task_id']
            or not re.fullmatch('[a-f0-9]{32}',str(invocation.get('task_id')))
            or invocation.get('proof_sha256')!=ref['sha256']or invocation.get('no_publish')is not True or invocation.get('automatic_replay')is not False
            or not any(e.get('event')=='native_rendered_quality_revision_consumed'and json.loads(e.get('detail_json')or'{}').get('proof_ref')==ref
                and json.loads(e.get('detail_json')or'{}').get('current_task_id')==invocation['task_id']for e in store.events(job['id']))):
        raise PermissionError('rendered_quality_historical_source_real_consumption_required')
    if job.get('state')=='generating':
        from .native_quality_runner import current_active_role
        _,active,_=current_active_role(0)
        deadline=invocation.get('deadline_unix')
        if (active!=invocation['task_id']or job.get('lease_owner')!=invocation.get('owner')or type(deadline)not in(int,float)
                or not math.isfinite(deadline)or time.time()>=deadline or not job.get('lease_expires_at')
                or datetime.fromisoformat(job['lease_expires_at'].replace('Z','+00:00')).timestamp()<=time.time()):
            raise PermissionError('rendered_quality_current_lease_deadline_required')
    old_ref=(history['job'].get('draft_meta')or{}).get('normal_completed_target_checkpoint_ref')
    if (job.get('draft_meta')or{}).get('normal_completed_target_checkpoint_ref')!=old_ref:
        raise ValueError('rendered_quality_original_checkpoint_source_changed')
    original=private_read(old_ref['path'],old_ref['sha256'])
    _,draft=validate_completed_target_checkpoint(store,original,initial=False,original_code_archive_ref=history.get('original_checkpoint_code_archive_ref'))
    if (job.get('title')!=draft['title']or job.get('body')!=draft['body']or any((job.get('draft_meta')or{}).get(k)!=draft['draft_meta'].get(k)
            for k in('normal_factual_revision_ref','target_adaptation_ref','precompiled_visual_span_ref','precompiled_visual_span_required'))):
        raise ValueError('rendered_quality_only_original_saved_candidate_allowed')
    source,_=read_completed_target_candidate(store,original['job_id'],original['factual_step_id'],original['target_step_id'])
    return dict(job,**source)

def run_rendered_quality_revision(pipeline,proof_path,proof_sha256):
    from .factual_candidate_revision import private_read,write_once,registered_current_scope
    from .native_quality_runner import current_active_role
    from .workflow_runtime import WorkflowStepRunner,WorkflowBlocked,strict_workflow_lock
    from .platform_workflow_context import load_platform_workflow_context
    from .current_strategy_refresh import refresh_current_strategy_inputs
    from .task_source_inputs import persist_task_source_inputs,refresh_task_source_contexts
    home,task,route=current_active_role(600)
    proof=private_read(proof_path,proof_sha256);history=_validate_proof(pipeline.store,proof)
    if task==proof['origin_task_id']or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0' or (pipeline.config.get('delivery')or{}).get('auto_stage_review_required')is not False:raise PermissionError('rendered_quality_new_no_publish_scope_required')
    seconds=registered_current_scope(home,task)
    if not 600<=seconds<=900:raise PermissionError('rendered_quality_original_scope_budget_required')
    store=pipeline.store;job_id=proof['job_id'];owner=pipeline._worker_id();deadline=time.monotonic()+seconds;workflow='wf_'+job_id;suffix='__quality_revision_'+proof['nonce']
    def guard():
        _,active,_=current_active_role(0);job=store.get_job(job_id)
        if active!=task or time.monotonic()>=deadline or job.get('state')!='generating'or job.get('lease_owner')!=owner or datetime.fromisoformat(job['lease_expires_at'].replace('Z','+00:00')).timestamp()<=time.time():raise PermissionError('rendered_quality_current_lease_deadline_required')
        validate_saved_candidate(history,job,store.draft_versions(job_id),store.artifacts(job_id),initial=False)
    class Runner(WorkflowStepRunner):
        def _name(self,name):return name+suffix
        def _deps(self,names):return[self._name(n)for n in names or[]]
        def run(self,name,func,required=True,depends_on=None,require_output=False,input_payload=None):
            if name not in {'collect_current_strategy_accounts','collect_current_strategy_platform_research'} and not name.startswith(('validate_current_strategy_raw[','distill_current_strategy_same_lane[','prepare_current_strategy[')):raise PermissionError('rendered_quality_primary_media_regeneration_forbidden')
            def bounded():guard();result=func();guard();return result
            return super().run(self._name(name),bounded,required,self._deps(depends_on),require_output,input_payload)
        def succeeded(self,name,output=None,required=True,depends_on=None,message=''):
            guard();return super().succeeded(self._name(name),output,required,self._deps(depends_on),message)
        def block(self,name,code,message,gate_result=None,depends_on=None):
            guard();return super().block(self._name(name),code,message,gate_result,self._deps(depends_on))
    with strict_workflow_lock(store,owner,workflow,seconds,pipeline.strict_serial):
        _validate_proof(store,proof)
        expected=Path(store.path).parent/'quality_runtime'/('rendered-quality-'+proof['nonce']+'.proof.private.json')
        if Path(proof_path)!=expected:raise PermissionError('rendered_quality_owned_proof_required')
        invocation=write_once(expected.with_name('rendered-quality-'+proof['nonce']+'.invocation.private.json'),{'version':VERSION,'task_id':task,'job_id':job_id,'proof_sha256':proof_sha256,'no_publish':True,'automatic_replay':False,'owner':owner,'deadline_unix':time.time()+max(0,deadline-time.monotonic())})
        if not store.claim(job_id,{'failed'},owner,max(1,math.floor(deadline-time.monotonic())),'generating'):raise PermissionError('rendered_quality_already_claimed')
        runner=Runner(store,workflow,job_id,notifier=pipeline.notifier)
        grant={'guard':guard,'nonce':proof['nonce'],'task':task,'platforms':history['job']['platforms'],'proof_ref':{'path':str(proof_path),'sha256':proof_sha256}}
        _ACTIVE[_key(store,job_id)]=grant
        store.record_event(job_id,'native_rendered_quality_revision_consumed',{'proof_ref':grant['proof_ref'],'current_task_id':task,'no_publish':True})
        try:
            job=store.get_job(job_id)
            owned=pipeline._enrich_brief(job)
            feedback=owned.get('historical_feedback')or{}
            if feedback.get('schema')!='owned_feedback_v1'or feedback.get('status')not in {'verified','unavailable'}:raise PermissionError('rendered_quality_owned_feedback_reader_required')
            strategy_job=copy.deepcopy(job)
            for field in ('historical_feedback','platform_historical_feedback','topic_historical_feedback','cluster_memory','legacy_feedback_reference'):
                strategy_job['brief'][field]=copy.deepcopy(owned[field])
            contexts={p:load_platform_workflow_context(p,plan=strategy_job['brief'])for p in job['platforms']}
            refreshed=refresh_current_strategy_inputs(store,pipeline.config,strategy_job,contexts,runner)
            prepared=refreshed['brief'];oldbrief=history['job']['brief']
            for field in FACT_FIELDS:
                if prepared.get(field)!=oldbrief.get(field):raise ValueError('rendered_quality_refreshed_facts_changed')
            for platform,scoped in refreshed['platform_briefs'].items():
                original=oldbrief['platform_workflow_inputs'][platform]
                if any(scoped.get(field)!=original.get(field)for field in FACT_FIELDS):raise ValueError('rendered_quality_scoped_facts_changed')
            audit=copy.deepcopy(oldbrief['source_collection_audit']);audit['current_strategy_refresh_audit']=refreshed['strategy_refresh_audit'];prepared['source_collection_audit']=audit
            for scoped in refreshed['platform_briefs'].values():scoped['source_collection_audit']=copy.deepcopy(audit)
            prepared['platform_workflow_inputs']=copy.deepcopy(refreshed['platform_briefs'])
            job=persist_task_source_inputs(store,job,owner,prepared);contexts=refresh_task_source_contexts(contexts,prepared)
            scoped={p:pipeline._bind_platform_source_inputs(job_id,b,p,contexts[p],owner)for p,b in refreshed['platform_briefs'].items()}
            prepared['platform_workflow_inputs']=copy.deepcopy(scoped);job=persist_task_source_inputs(store,job,owner,prepared)
            meta=copy.deepcopy(history['job']['draft_meta'])
            if len(scoped)!=1:raise PermissionError('rendered_quality_single_platform_revision_required')
            current_strategy=next(iter(scoped.values()))
            for field in ('account_analysis','same_lane_intelligence','strategy_evidence','strategy_evidence_gate','strategy_observation_ref','viral_collection','viral_breakdown','hot_work_parameter_pack','platform_intelligence_constraints','historical_feedback','platform_historical_feedback','topic_historical_feedback','cluster_memory','legacy_feedback_reference'):
                if field in current_strategy:meta[field]=copy.deepcopy(current_strategy[field])
            for field in ('quality_gate','platform_quality_gates','native_quality','final_quality_evidence'):meta.pop(field,None)
            from .humanize import _score, quality_gate
            scores=_score(job['body'],meta)
            meta.update(quality_scores=scores,quality_gate=quality_gate(scores))
            meta['rendered_quality_revision']={'version':VERSION,'nonce':proof['nonce'],'proof_ref':grant['proof_ref'],'origin_task_id':proof['origin_task_id'],'current_task_id':task,'original_draft_version_id':history['draft_versions'][-1]['id'],'strategy_observation_refs':refreshed['strategy_refresh_audit']['strategy_observation_refs'],'original_primary_replayed':False,'original_assets_replayed':False,'old_quality_inherited':False}
            # Preserve title/body/current primary/target source references and all original bytes.
            store.save_draft(job_id,job['title'],job['body'],job['risk_level'],job['risk'],job.get('prompt_version',''),meta)
            runner.succeeded('validate_image_requirements',{'passed':True,'kind':'immutable_existing_rendered_group_sha_revalidated','artifact_count':len(history['artifacts'])})
            generated=copy.deepcopy(_saved_rendered_group(history)['output'])
            # The normal tail binds these same source artifacts to the new real draft version.
            return pipeline.continue_rendered_candidate(job_id,owner,runner,generated,{})
        except WorkflowBlocked as exc:
            if store.get_job(job_id).get('lease_owner')==owner:store.release_claim(job_id,owner,'blocked','rendered_quality_revision_blocked',str(exc),detail={'reason_code':exc.reason_code})
            raise
        except Exception as exc:
            if store.get_job(job_id).get('lease_owner')==owner:store.release_claim(job_id,owner,'failed','rendered_quality_revision_failed',str(exc))
            raise
        finally:_ACTIVE.pop(_key(store,job_id),None)
