"""Root finite visual revision: immutable existing draft/caption, newly reviewed assets only."""
import copy,hashlib,json,math,os,re,time
from datetime import datetime
from pathlib import Path
from .factual_candidate_revision import private_read,write_once,registered_current_scope,digest
from .target_adaptation import read_target_adaptation

JOB='25110343c3354385'
VERSION='finite-current-twitter-visual-revision-v3'
REFSHAPE_VERSION='finite-current-twitter-visual-revision-v2'
RENDERER_VERSION='current_image_text_pixel_layout_v2'
PREVIOUS_VERSION='finite-current-twitter-visual-revision-v1'
ORIGIN='9ec38d884ad749499d063c7a7711e2bc'
FIRST_REVIEW_ORIGIN='be31c84165ff472289fb90f194a665ff'
OLD_NONCE='54cea2fc7615755024ba9a505b970fef'
FIRST_REVIEW_NONCE='718b9cf41d9320c2060b771e56314f1d'
BODY_SHA='499741e1e77470353f7ed83f1c9ea0bd9d344152e30dc75b9e97b8ffc63b0518'
CAPTION_SHA='c32286380fcd4a4752d05ac2960a67608f92ccebb8851c72ed516cd1c9dd5d49'
OLD_BINDING_SHA='7d611f74d473014aa0c157ff4d27c7213f7dbffeffeb8cc1739bd7c399bc45fc'

def history_snapshot(store):
    return {'job':store.get_job(JOB),'steps':store.workflow_steps(JOB),'events':store.events(JOB),'draft_versions':store.draft_versions(JOB),'artifacts':store.artifacts(JOB)}

def prepare_visual_revision_proof(store,nonce,directory,code_pins,scene_pool_ref):
    if not re.fullmatch('[a-f0-9]{32}',nonce)or nonce in {OLD_NONCE,FIRST_REVIEW_NONCE}:raise PermissionError('visual_revision_new_nonce_required')
    directory=Path(directory)
    if directory!=store.path.parent/'quality_runtime':raise PermissionError('visual_revision_Root_preparation_directory_required')
    history=history_snapshot(store)
    ref=write_once(directory/('visual-revision-'+nonce+'.history.private.json'),history)
    proof={'version':VERSION,'job_id':JOB,'origin_task_id':ORIGIN,'nonce':nonce,'history_ref':ref,'scene_pool_ref':scene_pool_ref,'code_pins':code_pins,'no_publish':True,'budget_seconds':900,'renderer_version':RENDERER_VERSION}
    validate(type('RootReadOnly',(),{'store':store,'data_dir':str(store.path.parent)})(),proof)
    return write_once(directory/('visual-revision-'+nonce+'.proof.private.json'),proof)

def validate(pipeline,proof,initial=True):
    if (proof.get('version')!=VERSION or proof.get('job_id')!=JOB or proof.get('origin_task_id')!=ORIGIN
            or not re.fullmatch('[a-f0-9]{32}',str(proof.get('nonce')or''))or proof['nonce']in{OLD_NONCE,FIRST_REVIEW_NONCE}
            or proof.get('no_publish')is not True or proof.get('budget_seconds')!=900 or proof.get('renderer_version')!=RENDERER_VERSION):raise PermissionError('visual_revision_exact_known_failure_contract_required')
    history=private_read(proof['history_ref']['path'],proof['history_ref']['sha256'],limit=16777216)
    store=pipeline.store;steps={r['id']:r for r in store.workflow_steps(JOB)};events={r['id']:r for r in store.events(JOB)}
    for row in history['steps']:
        if steps.get(row['id'])!=row:raise ValueError('visual_revision_original_step_changed')
    for row in history['events']:
        if events.get(row['id'])!=row:raise ValueError('visual_revision_original_event_changed')
    binding=steps.get(5444)or{};ref=(binding.get('output')or{}).get('artifact_manifest')or{}
    if binding.get('status')!='SUCCEEDED'or binding.get('step_name')!='bind_rendered_artifact_sources'or ref.get('sha256')!=OLD_BINDING_SHA:
        raise PermissionError('visual_revision_original_successful_binding_changed')
    original_binding=private_read(ref['path'],ref['sha256'])
    if original_binding.get('job_id')!=JOB or original_binding.get('platform')!='twitter'or original_binding.get('draft_version_id')!=184:
        raise ValueError('visual_revision_original_bound_source_changed')
    failure=events.get(7586)or{}
    if failure.get('event')!='rendered_tail_review_failed'or json.loads(failure.get('detail_json')or'{}')!={'error':'unknown_current_content_form'}:
        raise PermissionError('visual_revision_only_known_enum_preflight_failure_required')
    previous=private_read(Path('/srv/ai-self-media-tools/data/quality_runtime')/('rendered-tail-'+FIRST_REVIEW_NONCE+'.invocation.private.json'))
    if previous.get('task_id')!=FIRST_REVIEW_ORIGIN or previous.get('job_id')!=JOB or previous.get('no_publish')is not True:raise PermissionError('visual_revision_original_consumed_nonce_missing')
    if any(row.get('event')in{'native_mandatory_quality_attempt','native_mandatory_quality_result'}for row in history['events']):raise PermissionError('visual_revision_unknown_original_model_action_rejected')
    validate_existing_visual_group(store,history)
    job=store.get_job(JOB)
    if digest({'title':job['title'],'body':job['body']})!=BODY_SHA:raise ValueError('visual_revision_original_primary_candidate_changed')
    target=read_target_adaptation(job,'twitter')
    if target['caption_sha256']!=CAPTION_SHA or target['adaptation_session_ref'].get('api_call_count')!=1:
        raise ValueError('visual_revision_actual_original_target_copy_changed')
    if store.platform_outputs(JOB)or len(history['draft_versions'])!=1 or history['draft_versions'][0]['id']!=184 or store.draft_versions(JOB)!=history['draft_versions']:
        raise ValueError('visual_revision_saved_candidate_or_output_state_changed')
    current={r['id']:r for r in store.artifacts(JOB)}
    if len(history['artifacts'])!=14 or not {r['id']for r in history['artifacts']}<=set(current):raise ValueError('visual_revision_original_fourteen_artifacts_required')
    for row in history['artifacts']:
        now=current[row['id']];path=Path(row['path'])
        if any(now.get(k)!=row.get(k)for k in('id','job_id','kind','path','checksum'))or any(p.is_symlink()for p in(path,*path.parents))or not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=row['checksum']:
            raise ValueError('visual_revision_original_artifact_changed')
    pool=private_read(proof['scene_pool_ref']['path'],proof['scene_pool_ref']['sha256'],limit=262144)
    if pool.get('version')!='twitter_report_receipt_scene_pool_v1'or pool.get('scene_key')!='report_delivery_receipt_check'or pool.get('language')!='en':raise ValueError('visual_revision_current_scene_pool_scope_invalid')
    pins=proof.get('code_pins')or[]
    required={'/srv/ai-self-media-tools/content_platform/'+name for name in('visual_candidate_revision.py','pipeline.py','media.py','mandatory_quality_context.py','mandatory_release_gate.py','target_adaptation.py','current_twitter_visual_plan_producer.py','native_quality_runner.py')}
    if (not pins or len({p['path']for p in pins})!=len(pins)or not required<={p['path']for p in pins}):raise PermissionError('visual_revision_exact_deployed_code_pins_required')
    for pin in pins:
        if hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('visual_revision_deployed_code_changed')
    if initial and (job!=history['job']or job.get('state')!='failed'or job.get('attempts')!=10 or job.get('last_error')!='visual_revision_actual_four_image_group_required'or job.get('lease_owner')
                    or store.workflow_steps(JOB)!=history['steps']or store.events(JOB)!=history['events']or store.artifacts(JOB)!=history['artifacts']):
        raise PermissionError('visual_revision_only_exact_original_postclaim_failure_required')
    return job,history


def validate_existing_visual_group(store,history):
    """Only the already successful physical group, never caller-supplied material."""
    rows={r['id']:r for r in history['steps']};events={r['id']:r for r in history['events']}
    failed=events.get(7592)or{}
    if failed.get('event')!='visual_revision_execution_failed'or json.loads(failed.get('detail_json')or'{}')!={'error':'visual_revision_actual_four_image_group_required'}:
        raise PermissionError('visual_revision_only_known_post_image_refshape_failure_required')
    consumed=private_read(Path('/srv/ai-self-media-tools/data/quality_runtime')/('visual-revision-'+OLD_NONCE+'.invocation.private.json'))
    if consumed.get('version')!=PREVIOUS_VERSION or consumed.get('task_id')!=ORIGIN or consumed.get('job_id')!=JOB or consumed.get('no_publish')is not True:
        raise PermissionError('visual_revision_previous_postclaim_scope_consumption_required')
    previousproof=private_read(Path('/srv/ai-self-media-tools/data/quality_runtime')/('visual-revision-'+OLD_NONCE+'.proof.private.json'),consumed['proof_sha256'])
    if previousproof.get('nonce')!=OLD_NONCE or previousproof.get('version')!=PREVIOUS_VERSION:
        raise PermissionError('visual_revision_previous_consumed_proof_changed')
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+ORIGIN)
    if any((home/name).exists()for name in('state.db','state.db-wal','state.db-shm')):
        raise PermissionError('visual_revision_previous_unknown_model_effect_rejected')
    plan=rows.get(5445)or{};images=rows.get(5447)or{}
    if (plan.get('status')!='SUCCEEDED'or images.get('status')!='SUCCEEDED'
            or plan.get('step_name')!='prepare_current_twitter_visual_plan__visual_revision_'+OLD_NONCE
            or images.get('step_name')!='generate_visual_revision_images__visual_revision_'+OLD_NONCE
            or store.workflow_steps(JOB).count(plan)!=1 or store.workflow_steps(JOB).count(images)!=1):
        raise PermissionError('visual_revision_exact_successful_plan_images_required')
    result=images.get('output')or{};ref=plan.get('output')or{};actual=result.get('current_visual_plan_ref')or{}
    expected='/srv/ai-self-media-tools/data/quality_runtime/current-twitter-visual-plan-'+ORIGIN+'-'+JOB+'.private.json'
    if ref.get('path')!=expected or ref.get('sha256')!='5cffe4cff1ef401c5a120b9ff77ad1819ff007296c20bd65e12ce94d41f57530':raise ValueError('visual_revision_original_actual_plan_changed')
    # A reference may carry optional measured bytes; identity is canonical path/SHA.
    if any(actual.get(k)!=ref.get(k)for k in('path','sha256')):raise ValueError('visual_revision_actual_plan_identity_changed')
    source=private_read(ref['path'],ref['sha256'])
    if type(actual.get('bytes'))is not int or actual['bytes']!=Path(ref['path']).stat().st_size:raise ValueError('visual_revision_actual_plan_measured_bytes_changed')
    if source.get('job_id')!=JOB or source.get('platform')!='twitter' or source.get('draft_source_sha256')!=BODY_SHA:
        raise ValueError('visual_revision_original_plan_candidate_scope_changed')
    group=result.get('images')or[];aux=result.get('auxiliary_artifacts')or[]
    if len(group)!=4 or [a.get('role')for a in group]!=['cover','section','section','section']or {a.get('kind')for a in aux}!={'rights','render_manifest'} or len(aux)!=2:
        raise ValueError('visual_revision_actual_four_image_group_required')
    prefix='/srv/ai-self-media-tools/data/artifacts/'+JOB+'/visual-5cffe4cff1ef401c5a120b9f/'
    owned={a['path']:a for a in history['artifacts']}
    for item in [*group,*aux]:
        path=Path(item.get('path')or'');row=owned.get(str(path));checksum=item.get('checksum')
        if not str(path).startswith(prefix) or not row or checksum!=row['checksum']or hashlib.sha256(path.read_bytes()).hexdigest()!=checksum:
            raise ValueError('visual_revision_saved_current_group_artifact_changed')
    if len({a['path']for a in group})!=4:raise ValueError('visual_revision_four_distinct_existing_images_required')
    return result


def prepare_pixel_revision_plan(pipeline,job,task,original):
    original_ref=original['current_visual_plan_ref'];plan=private_read(original_ref['path'],original_ref['sha256'])
    revised=copy.deepcopy(plan)
    revised.update(renderer_version=RENDERER_VERSION,current_task_id=task,
                   pixel_revision_source_ref={k:original_ref[k]for k in('path','sha256')})
    ref=write_once(Path(pipeline.data_dir)/'quality_runtime'/('current-twitter-pixel-plan-'+task+'-'+JOB+'.private.json'),revised)
    probe=copy.deepcopy(job);probe['draft_meta']['current_visual_plan_ref']=ref
    pipeline.media._current_image_text_plan(probe)
    return ref

def validate_pixel_revision_result(result,plan_ref):
    if not isinstance(result,dict)or len(result.get('images')or[])!=4:raise ValueError('visual_revision_actual_four_image_group_required')
    actual=result.get('current_visual_plan_ref')or{}
    if any(actual.get(k)!=plan_ref.get(k)for k in('path','sha256')):raise ValueError('visual_revision_actual_pixel_plan_identity_changed')
    plan=private_read(plan_ref['path'],plan_ref['sha256'])
    if (plan.get('renderer_version')!=RENDERER_VERSION or type(actual.get('bytes'))is not int
            or actual['bytes']!=Path(plan_ref['path']).stat().st_size):raise ValueError('visual_revision_actual_pixel_plan_version_or_bytes_changed')
    if [x.get('role')for x in result['images']]!=['cover','section','section','section']:
        raise ValueError('visual_revision_actual_pixel_four_image_roles_required')
    directory=Path('/srv/ai-self-media-tools/data/artifacts')/JOB/('visual-'+plan_ref['sha256'][:24]+'-pixel-v2')
    if directory.name=='visual-5cffe4cff1ef401c5a120b9f':raise ValueError('visual_revision_old_successful_images_must_not_be_overwritten')
    for image in result['images']:
        p=Path(image.get('path')or'')
        if p.parent!=directory or p.is_symlink()or hashlib.sha256(p.read_bytes()).hexdigest()!=image.get('checksum'):
            raise ValueError('visual_revision_current_independent_pixel_file_required')

_ACTIVE={}

def _key(store,job_id):return (str(Path(store.path).resolve()),job_id)

def binding_step_name(store,job_id,platform):
    grant=_ACTIVE.get(_key(store,job_id))
    if grant is None:return 'bind_rendered_artifact_sources'
    expected_job=grant['proof']['job_id']if grant['proof'].get('version')==NORMAL_VISUAL_VERSION else JOB
    if job_id!=expected_job or platform!='twitter':raise PermissionError('visual_revision_binding_platform_scope_changed')
    grant['guard']()
    return 'bind_rendered_artifact_sources__visual_revision_'+grant['proof']['nonce']

def record_binding_reference(store,job_id,platform,manifest_ref):
    grant=_ACTIVE.get(_key(store,job_id))
    if grant is None:return None
    if grant['proof'].get('version')==NORMAL_VISUAL_VERSION:return _record_normal_visual_binding(store,job_id,platform,manifest_ref,grant)
    grant['guard']();name=binding_step_name(store,job_id,platform)
    rows=[row for row in store.workflow_steps(job_id)if row['platform']==platform and row['step_name']==name]
    if len(rows)!=1 or rows[0]['status']!='SUCCEEDED'or rows[0].get('output')!={'artifact_manifest':manifest_ref}:
        raise ValueError('visual_revision_actual_bound_row_required')
    source=private_read(manifest_ref['path'],manifest_ref['sha256'])
    if source.get('job_id')!=JOB or source.get('platform')!=platform or source.get('draft_version_id')!=184:
        raise ValueError('visual_revision_actual_source_owner_changed')
    proof=grant['proof'];record={'version':'actual_visual_revision_binding_v1','job_id':job_id,'platform':platform,'task_id':grant['task'],
        'nonce':proof['nonce'],'step_name':name,'row_id':rows[0]['id'],'row_sha256':digest(rows[0]),'manifest_ref':manifest_ref,
        'proof_ref':grant['proof_ref'],'no_publish':True}
    ref=write_once(Path(grant['proof_ref']['path']).parent/('visual-revision-'+proof['nonce']+'.binding-'+platform+'.private.json'),record)
    store.record_event(job_id,'current_visual_revision_binding',{'binding_receipt_ref':ref,'nonce':proof['nonce'],'platform':platform})
    grant['binding_receipt_ref']=ref
    return ref

def current_visual_binding(store,job_id,platform):
    grant=_ACTIVE.get(_key(store,job_id))
    if grant is not None:
        grant['guard']();ref=grant.get('binding_receipt_ref')
        if ref is None:return None
    else:
        rows=[json.loads(row['detail_json'])for row in store.events(job_id)if row.get('event')=='current_visual_revision_binding'
              and json.loads(row['detail_json']).get('platform')==platform]
        if not rows:return None
        ref=rows[-1].get('binding_receipt_ref')
    if not isinstance(ref,dict):raise ValueError('visual_revision_binding_receipt_missing')
    record=private_read(ref['path'],ref['sha256'])
    if record.get('version')==NORMAL_VISUAL_BINDING:return _normal_visual_current_binding(store,job_id,platform,record,ref)
    if record.get('version')!='actual_visual_revision_binding_v1'or record.get('job_id')!=job_id or record.get('platform')!=platform or record.get('no_publish')is not True:
        raise PermissionError('visual_revision_binding_receipt_owner_invalid')
    proofref=record['proof_ref'];proof=private_read(proofref['path'],proofref['sha256'])
    if proof.get('version')not in {VERSION,REFSHAPE_VERSION,PREVIOUS_VERSION} or proof.get('nonce')!=record['nonce']or proof.get('job_id')!=job_id or proof.get('no_publish')is not True:
        raise ValueError('visual_revision_actual_binding_proof_changed')
    expected=Path(proofref['path']).parent/('visual-revision-'+record['nonce']+'.binding-'+platform+'.private.json')
    if Path(ref['path'])!=expected:raise PermissionError('visual_revision_bound_receipt_path_invalid')
    invocation=private_read(Path(proofref['path']).parent/('visual-revision-'+record['nonce']+'.invocation.private.json'))
    if invocation.get('task_id')!=record['task_id']or invocation.get('proof_sha256')!=proofref['sha256']or invocation.get('no_publish')is not True:
        raise ValueError('visual_revision_actual_scope_consumption_changed')
    history=private_read(proof['history_ref']['path'],proof['history_ref']['sha256'],limit=16777216)
    current={r['id']:r for r in store.workflow_steps(job_id)}
    for original in history['steps']:
        if current.get(original['id'])!=original:raise ValueError('visual_revision_old_workflow_history_changed')
    row=current.get(record['row_id'])
    if (not row or row.get('status')!='SUCCEEDED'or row.get('step_name')!=record['step_name']or row.get('platform')!=platform
            or digest(row)!=record['row_sha256']or row.get('output')!={'artifact_manifest':record['manifest_ref']}):
        raise ValueError('visual_revision_actual_bound_row_changed')
    source=private_read(record['manifest_ref']['path'],record['manifest_ref']['sha256'])
    if source.get('job_id')!=job_id or source.get('platform')!=platform or source.get('draft_version_id')!=184:raise ValueError('visual_revision_current_source_owner_invalid')
    job=store.get_job(job_id)
    if digest({'title':job['title'],'body':job['body']})!=BODY_SHA or read_target_adaptation(job,platform)['caption_sha256']!=CAPTION_SHA:raise ValueError('visual_revision_binding_current_candidate_changed')
    return {'row':row,'manifest_ref':record['manifest_ref'],'binding_receipt_ref':ref}

def _run_legacy_visual_candidate_revision(pipeline,proof_path,proof_sha256):
    from .native_quality_runner import current_active_role
    from .workflow_runtime import WorkflowStepRunner,WorkflowBlocked,strict_workflow_lock
    home,task,_=current_active_role(600)
    if task==ORIGIN or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':raise PermissionError('visual_revision_new_no_publish_scope_required')
    seconds=registered_current_scope(home,task)
    if seconds<600:raise PermissionError('visual_revision_current_900_budget_insufficient')
    proof=private_read(proof_path,proof_sha256);store=pipeline.store;validate(pipeline,proof)
    configured=(pipeline.config.get('media')or{}).get('image',{}).get('real_scene_pool_ref')
    if configured!=proof['scene_pool_ref']:raise ValueError('visual_revision_exact_current_config_pool_required')
    owner=pipeline._worker_id();workflow='wf_'+JOB;deadline=time.monotonic()+seconds;suffix='__visual_revision_'+proof['nonce']
    def guard():
        _,current,_=current_active_role(0);job=store.get_job(JOB)
        if (current!=task or time.monotonic()>=deadline or job.get('state')!='generating'or job.get('lease_owner')!=owner
                or datetime.fromisoformat(job['lease_expires_at'].replace('Z','+00:00')).timestamp()<=time.time()):raise PermissionError('visual_revision_current_role_or_original_lease_deadline_required')
        validate(pipeline,proof,initial=False)
    class Runner(WorkflowStepRunner):
        def _map(self,name):return name+suffix
        def _deps(self,names):return[self._map('generate_visual_pixel_revision_images'if n=='generate_or_collect_images'else n)for n in(names or[])]
        def run(self,name,func,required=True,depends_on=None,require_output=False,input_payload=None):
            if name not in{'prepare_current_twitter_pixel_plan','generate_visual_pixel_revision_images','validate_image_requirements'}:
                raise PermissionError('visual_revision_source_primary_target_regeneration_forbidden')
            def bounded():guard();value=func();guard();return value
            return super().run(self._map(name),bounded,required,self._deps(depends_on),require_output,input_payload)
        def succeeded(self,name,output=None,required=True,depends_on=None,message=''):
            guard();return super().succeeded(self._map(name),output,required,self._deps(depends_on),message)
        def block(self,name,code,message,gate_result=None,depends_on=None):guard();return super().block(self._map(name),code,message,gate_result,self._deps(depends_on))
        def skipped(self,name,code,message,required=False,depends_on=None):guard();return super().skipped(self._map(name),code,message,required,self._deps(depends_on))
    with strict_workflow_lock(store,owner,workflow,seconds,pipeline.strict_serial):
        validate(pipeline,proof)
        proof_ref={'path':str(proof_path),'sha256':proof_sha256}
        write_once(Path(proof_path).parent/('visual-revision-'+proof['nonce']+'.invocation.private.json'),
                   {'version':VERSION,'job_id':JOB,'task_id':task,'proof_sha256':proof_sha256,'no_publish':True,'automatic_replay':False})
        if not store.claim(JOB,{'failed'},owner,max(1,math.floor(deadline-time.monotonic())),'generating'):raise PermissionError('visual_revision_already_claimed')
        _ACTIVE[_key(store,JOB)]={'proof':proof,'proof_ref':proof_ref,'task':task,'guard':guard}
        runner=Runner(store,workflow,JOB,notifier=pipeline.notifier)
        try:
            job=store.get_job(JOB);draft={k:copy.deepcopy(job[k])for k in('title','body','draft_meta','prompt_version')}
            # New layout revision has its own current plan and artifact directory.
            # It preserves every original photo, role source, literal caption and old image.
            original=validate_existing_visual_group(store,private_read(proof['history_ref']['path'],proof['history_ref']['sha256'],limit=16777216))
            plan_ref=runner.run('prepare_current_twitter_pixel_plan',lambda:prepare_pixel_revision_plan(pipeline,job,task,original),require_output=True)
            draft['draft_meta']['current_visual_plan_ref']=plan_ref
            result=pipeline._generate_optional_media(JOB,'image',runner,['prepare_current_twitter_pixel_plan'],step_name='generate_visual_pixel_revision_images',draft=draft)
            validate_pixel_revision_result(result,plan_ref)
            pipeline._validate_image_requirements(JOB,runner,result)
            return pipeline.continue_rendered_candidate(JOB,owner,runner,result,{},[])
        except WorkflowBlocked as error:
            if store.get_job(JOB).get('lease_owner')==owner:return pipeline._hydrate(store.release_claim(JOB,owner,'blocked','visual_revision_quality_blocked',error,detail={'step':error.step,'reason_code':error.reason_code,'nonce':proof['nonce']}))
            raise
        except BaseException as error:
            if store.get_job(JOB).get('lease_owner')==owner:store.release_claim(JOB,owner,'failed','visual_revision_execution_failed',str(error))
            raise
        finally:_ACTIVE.pop(_key(store,JOB),None)

NORMAL_VISUAL_VERSION='normal-visual-content-revision-v1'
NORMAL_VISUAL_BINDING='normal-visual-content-revision-binding-v1'

def _validate_visual_content_review(context,result,review,usage,session,raw,draft_id):
    checksum=hashlib.sha256(json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    names=context.get('required_checks',{}).get('vlm')or[];checks=review.get('checks')or[]
    if (context.get('draft_version_id')!=draft_id or result.get('passed')is not False
            or result.get('state')!='required_native_channel_failed'or result.get('failed_channel')!='vlm'
            or result.get('job_id')!=context.get('job_id')or result.get('platform')!=context.get('platform')
            or result.get('context_sha256')!=checksum or review.get('context_sha256')!=checksum or review.get('channel')!='vlm'
            or result.get('completed_channels')!=['auto','vlm']or result.get('remaining_channels_not_executed')!=[]
            or len(checks)!=len(names)or {r.get('name')for r in checks}!=set(names)
            or any(type(r.get('passed'))is not bool or r.get('verdict')not in {'passed','failed'}or(r['verdict']=='passed')!=r['passed']for r in checks)
            or not any(r['passed']is False for r in checks)
            or set(result.get('failures')or[])!={r['name']for r in checks if r['passed']is False}
            or usage.get('completed')is not True or any(usage.get(k)is not False for k in ('failed','partial','interrupted'))
            or usage.get('session_id')!=session.get('id')or not session.get('ended_at')
            or type(session.get('api_call_count'))is not int or session['api_call_count']<=0
            or json.loads(raw)!=review):
        raise PermissionError('normal_visual_known_completed_content_failure_required')
    return True

def _normal_visual_failure_snapshot(store,job_id,origin_task_id,draft_id,attempt_path=None):
    from .native_quality_resume import digest as actual_digest
    from .factual_candidate_revision import current_generation_records
    from .target_adaptation import native_session
    from .native_quality_runner import strict_review
    from .mandatory_quality_context import verify_native_quality_execution
    root=Path(store.path).parent/'quality_runtime'/job_id/'twitter';home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+origin_task_id)
    sessions=current_generation_records(home)
    if not sessions or any(not r.get('ended_at')for r in sessions):raise PermissionError('normal_visual_original_unknown_or_running_rejected')
    attempts=[Path(attempt_path)]if attempt_path else[p.parent for p in root.glob('attempts/*/result.json')]
    stage=Path('/srv/hermes-worker-media/jobs')/origin_task_id
    registration=private_read(stage/'registered-driver-invocation.private.json')
    invocation=private_read(stage/'hard-factual-invocation.private.json')
    terminal=private_read(stage/'hard-factual-result.private.json')
    if (registration.get('schema')!='root-registered-driver-invocation-v1'or registration.get('job_id')!=origin_task_id or registration.get('no_publish')is not True
            or invocation.get('schema')!='hard-factual-invocation-v1'or invocation.get('task_id')!=origin_task_id or invocation.get('job_id')!=job_id
            or invocation.get('budget_seconds')!=900 or invocation.get('no_publish')is not True or invocation.get('automatic_replay')is not False
            or abs(invocation['deadline_unix']-invocation['original_invocation_started_at']-900)>0.01
            or terminal.get('schema')!='hard-factual-result-v1'or terminal.get('task_id')!=origin_task_id or terminal.get('job_id')!=job_id
            or terminal.get('state')!='failed'or terminal.get('returncode')!=1 or terminal.get('no_publish')is not True or terminal.get('automatic_replay')is not False
            or terminal.get('proof_sha256')!=invocation.get('proof_sha256')or terminal.get('deadline_unix')!=invocation.get('deadline_unix')
            or not invocation['original_invocation_started_at']<=terminal['finished_at_unix']<invocation['deadline_unix']
            or any(not invocation['original_invocation_started_at']<=r['started_at']<r['ended_at']<=terminal['finished_at_unix']for r in sessions)
            or(stage/'registered-internal-delivery.private.json').exists()):raise PermissionError('normal_visual_original_registered_terminal_failure_required')
    scope_refs=[{'path':str(stage/name),'sha256':hashlib.sha256((stage/name).read_bytes()).hexdigest()}for name in ['registered-driver-invocation.private.json','hard-factual-invocation.private.json','hard-factual-result.private.json']]
    matched=[]
    for attempt in attempts:
        if attempt.parent!=root/'attempts'or not attempt.name.startswith('native-'):raise PermissionError('normal_visual_original_attempt_scope_invalid')
        names=['prepared-context.json','result.json','vlm.actual-model-result.json','vlm.usage.json','vlm.native-stdout.log','auto.actual-model-result.json','auto.usage.json']
        if any(not(attempt/n).is_file()for n in names):continue
        context=private_read(attempt/names[0]);result=private_read(attempt/names[1]);review=private_read(attempt/names[2]);usage=private_read(attempt/names[3]);auto=private_read(attempt/names[5]);au=private_read(attempt/names[6])
        if context.get('draft_version_id')!=draft_id or result.get('failed_channel')!='vlm':continue
        if context.get('job_id')!=job_id or context.get('platform')!='twitter':raise ValueError('normal_visual_original_context_owner_changed')
        session,messages,raw=native_session(home,usage['session_id'])
        _validate_visual_content_review(context,result,review,usage,session,raw,draft_id)
        strict_review(review,context,'vlm');strict_review(auto,context,'auto')
        if any(r['passed']is not True for r in auto['checks'])or au.get('completed')is not True or any(au.get(k)is not False for k in ('failed','partial','interrupted')):raise PermissionError('normal_visual_original_full_auto_completed_required')
        auto_session,auto_messages,auto_raw=native_session(home,au['session_id'])
        if not auto_session.get('ended_at')or json.loads(auto_raw)!=auto or raw.strip()!=(attempt/names[4]).read_text().strip():raise ValueError('normal_visual_original_native_response_changed')
        execution_records=private_read(attempt/'actual-execution-records.json')
        auto_records=(execution_records.get('checks')or{}).get('auto')or{}
        if set(auto_records)!=set(context['required_checks']['auto']):raise PermissionError('normal_visual_original_full_auto_execution_records_required')
        for index,name in enumerate(context['required_checks']['auto']):
            subset={part:context['parts'][part]for part in context['check_parts'][name]}
            verify_native_quality_execution(auto_records[name],'auto-'+str(index),context,subset,channel='auto',check_name=name)
        names=names+['actual-execution-records.json']
        refs=[{'path':str(attempt/n),'sha256':hashlib.sha256((attempt/n).read_bytes()).hexdigest()}for n in names]
        for parts in context['parts'].values():
            for ref in parts:private_read(ref['path'],ref['sha256'])if Path(ref['path']).suffix=='.json'else _normal_visual_file(ref)
        matched.append({'attempt':str(attempt),'files':refs,'registered_scope_files':scope_refs,'session_sha256':actual_digest(session),'messages_sha256':actual_digest(messages),'auto_session_sha256':actual_digest(auto_session),'auto_messages_sha256':actual_digest(auto_messages),'context_sha256':result['context_sha256']})
    if len(matched)!=1:raise PermissionError('normal_visual_one_actual_current_content_failure_required')
    return matched[0]

def _normal_visual_file(ref):
    from .visual_policy_gate import file_record
    return file_record(ref['path'],ref['sha256'])

def _validate_normal_visual_history(store,history,*,initial=False,new_plan_ref=None):
    from .native_quality_resume import validate_saved_candidate
    original=history['job'];job_id=original['id'];current=store.get_job(job_id);artifacts=store.artifacts(job_id)
    old={r['id']:r for r in history['artifacts']};now={r['id']:r for r in artifacts}
    if any(now.get(i)!=r for i,r in old.items()):raise ValueError('normal_visual_original_artifact_row_changed')
    # These are the only extra mutable fields authorized by this new visual action.
    checked=copy.deepcopy(current)
    for field in ('current_visual_plan_ref','cover_design','normal_visual_revision'):
        if field in original['draft_meta']:checked['draft_meta'][field]=copy.deepcopy(original['draft_meta'][field])
        else:checked['draft_meta'].pop(field,None)
    validate_saved_candidate(history,checked,store.draft_versions(job_id),[r for r in artifacts if r['id']in old],initial=initial)
    steps={r['id']:r for r in store.workflow_steps(job_id)};events={r['id']:r for r in store.events(job_id)}
    if any(steps.get(r['id'])!=r for r in history['steps'])or any(events.get(r['id'])!=r for r in history['events']):raise ValueError('normal_visual_original_history_changed')
    added=[r for r in artifacts if r['id']not in old]
    if added:
        ref=new_plan_ref or current['draft_meta'].get('current_visual_plan_ref')or{}
        if ref==original['draft_meta'].get('current_visual_plan_ref'):raise ValueError('normal_visual_new_assets_without_new_plan')
        plan=private_read(ref['path'],ref['sha256']);directory=Path(store.path).parent/'artifacts'/job_id/('visual-'+ref['sha256'][:24]+'-pixel-v3')
        expected={'cover.png':'cover','section-01.png':'image','section-02.png':'image','section-03.png':'image','rights.private.json':'rights','render_manifest.private.json':'render_manifest','section_image_map.json':'section_image_map'}
        if (plan.get('job_id')!=job_id or plan.get('renderer_version')!='current_image_text_pixel_layout_v3'or len(added)!=7
                or {Path(r['path']).name for r in added}!=set(expected)):raise ValueError('normal_visual_independent_new_seven_asset_group_required')
        for row in added:
            if Path(row['path']).parent!=directory or row['kind']!=expected[Path(row['path']).name]:raise ValueError('normal_visual_new_asset_scope_invalid')
            _normal_visual_file({'path':row['path'],'sha256':row['checksum']})
    return current

def _validate_normal_visual_proof(store,proof,*,initial=True,new_plan_ref=None):
    if (set(proof)!={'version','job_id','origin_task_id','nonce','no_publish','budget_seconds','scene_pool_ref','history_ref','code_pins'}
            or proof.get('version')!=NORMAL_VISUAL_VERSION or proof.get('no_publish')is not True or proof.get('budget_seconds')!=900
            or not re.fullmatch('[a-f0-9]{16}',str(proof.get('job_id')or''))
            or any(not re.fullmatch('[a-f0-9]{32}',str(proof.get(k)or''))for k in ('origin_task_id','nonce'))):raise PermissionError('normal_visual_new_exact_revision_contract_required')
    history=private_read(proof['history_ref']['path'],proof['history_ref']['sha256'],limit=16777216);job=history['job'];job_id=proof['job_id']
    if (job.get('id')!=job_id or job.get('state')!='blocked'or job.get('lease_owner')or job.get('platforms')!=['twitter']
            or not job.get('title')or not job.get('body')or not history.get('draft_versions')
            or (job.get('draft_meta')or{}).get('content_form')not in {'image_text','image_text_post'}):raise PermissionError('normal_visual_actual_blocked_saved_unpublished_required')
    if initial and store.platform_outputs(job_id):raise PermissionError('normal_visual_existing_outputs_not_revisable')
    _validate_normal_visual_history(store,history,initial=initial,new_plan_ref=new_plan_ref)
    if _normal_visual_failure_snapshot(store,job_id,proof['origin_task_id'],history['draft_versions'][-1]['id'],history['content_failure']['attempt'])!=history['content_failure']:raise ValueError('normal_visual_original_content_failure_changed')
    required={'visual_candidate_revision.py','current_twitter_visual_plan_producer.py','media.py','native_quality_resume.py','pipeline.py','store.py','native_quality_runner.py','mandatory_release_gate.py','mandatory_quality_context.py','target_adaptation.py','current_strategy_refresh.py'}
    pins=proof['code_pins']
    required={'/srv/ai-self-media-tools/content_platform/'+name for name in required}
    if len({r['path']for r in pins})!=len(pins)or not required<={r['path']for r in pins}:raise PermissionError('normal_visual_current_deployed_code_pins_required')
    for ref in pins:_normal_visual_file(ref)
    return history

def prepare_visual_content_revision(store,job_id,origin_task_id,nonce,directory,code_pins,scene_pool_ref):
    if not re.fullmatch('[a-f0-9]{16}',job_id)or any(not re.fullmatch('[a-f0-9]{32}',v)for v in (origin_task_id,nonce)):raise PermissionError('normal_visual_identifiers_invalid')
    directory=Path(directory)
    if directory!=Path(store.path).parent/'quality_runtime':raise PermissionError('normal_visual_owned_preparation_directory_required')
    history={'job':store.get_job(job_id),'draft_versions':store.draft_versions(job_id),'artifacts':store.artifacts(job_id),'steps':store.workflow_steps(job_id),'events':store.events(job_id)}
    if not history['draft_versions']:raise PermissionError('normal_visual_saved_draft_required')
    history['content_failure']=_normal_visual_failure_snapshot(store,job_id,origin_task_id,history['draft_versions'][-1]['id'])
    history_ref=write_once(directory/('visual-revision-'+nonce+'.history.private.json'),history)
    proof={'version':NORMAL_VISUAL_VERSION,'job_id':job_id,'origin_task_id':origin_task_id,'nonce':nonce,'no_publish':True,'budget_seconds':900,'scene_pool_ref':scene_pool_ref,'history_ref':history_ref,'code_pins':code_pins}
    _validate_normal_visual_proof(store,proof)
    return write_once(directory/('visual-revision-'+nonce+'.proof.private.json'),proof)

def _normal_visual_current_binding(store,job_id,platform,record,ref):
    proofref=record['proof_ref'];proof=private_read(proofref['path'],proofref['sha256']);history=_validate_normal_visual_proof(store,proof,initial=False)
    if (record.get('version')!=NORMAL_VISUAL_BINDING or record.get('job_id')!=job_id or record.get('platform')!=platform
            or record.get('no_publish')is not True or proof.get('job_id')!=job_id or proof.get('nonce')!=record.get('nonce')
            or Path(ref['path'])!=Path(proofref['path']).parent/('visual-revision-'+record['nonce']+'.binding-'+platform+'.private.json')):raise PermissionError('normal_visual_current_binding_identity_invalid')
    invocation=private_read(Path(proofref['path']).parent/('visual-revision-'+record['nonce']+'.invocation.private.json'))
    if invocation.get('task_id')!=record.get('task_id')or invocation.get('proof_sha256')!=proofref['sha256']or invocation.get('job_id')!=job_id or invocation.get('no_publish')is not True:raise ValueError('normal_visual_actual_scope_consumption_changed')
    row=next((r for r in store.workflow_steps(job_id)if r['id']==record['row_id']),None)
    if not row or row['status']!='SUCCEEDED'or row['platform']!=platform or row['step_name']!='bind_rendered_artifact_sources__visual_revision_'+proof['nonce']or digest(row)!=record['row_sha256']or row.get('output')!={'artifact_manifest':record['manifest_ref']}:raise ValueError('normal_visual_actual_bound_row_changed')
    source=private_read(record['manifest_ref']['path'],record['manifest_ref']['sha256'])
    if source.get('job_id')!=job_id or source.get('platform')!=platform or source.get('draft_version_id')!=store.draft_versions(job_id)[-1]['id']:raise ValueError('normal_visual_current_saved_draft_binding_changed')
    from .intelligence import prepare_generation_strategy_inputs
    from .task_source_inputs import project_task_source_brief
    job=store.get_job(job_id);prepare_generation_strategy_inputs(job['topic'],project_task_source_brief(job['brief'],platform))
    return {'row':row,'manifest_ref':record['manifest_ref'],'binding_receipt_ref':ref}

def _record_normal_visual_binding(store,job_id,platform,manifest_ref,grant):
    grant['guard']();name=binding_step_name(store,job_id,platform)
    rows=[r for r in store.workflow_steps(job_id)if r.get('platform')==platform and r.get('step_name')==name]
    if len(rows)!=1 or rows[0]['status']!='SUCCEEDED'or rows[0].get('output')!={'artifact_manifest':manifest_ref}:raise ValueError('normal_visual_actual_bound_row_required')
    source=private_read(manifest_ref['path'],manifest_ref['sha256'])
    if source.get('job_id')!=job_id or source.get('platform')!=platform or source.get('draft_version_id')!=store.draft_versions(job_id)[-1]['id']:raise ValueError('normal_visual_actual_bound_draft_required')
    record={'version':NORMAL_VISUAL_BINDING,'job_id':job_id,'platform':platform,'task_id':grant['task'],'nonce':grant['proof']['nonce'],'row_id':rows[0]['id'],'row_sha256':digest(rows[0]),'manifest_ref':manifest_ref,'proof_ref':grant['proof_ref'],'no_publish':True}
    ref=write_once(Path(grant['proof_ref']['path']).parent/('visual-revision-'+record['nonce']+'.binding-'+platform+'.private.json'),record)
    store.record_event(job_id,'current_visual_revision_binding',{'platform':platform,'binding_receipt_ref':ref,'nonce':record['nonce']});grant['binding_receipt_ref']=ref
    return ref
def _run_normal_visual_content_revision(pipeline,proof_path,proof_sha256):
    from .native_quality_runner import current_active_role
    from .workflow_runtime import WorkflowStepRunner,WorkflowBlocked,strict_workflow_lock
    from .platform_workflow_context import load_platform_workflow_context
    from .current_strategy_refresh import refresh_current_strategy_inputs
    from .task_source_inputs import persist_task_source_inputs,refresh_task_source_contexts
    from .native_quality_resume import FACT_FIELDS
    from .current_twitter_visual_plan_producer import prepare_current_twitter_visual_plan
    home,task,route=current_active_role(600);proof=private_read(proof_path,proof_sha256);store=pipeline.store
    history=_validate_normal_visual_proof(store,proof);job_id=proof['job_id']
    if (task==proof['origin_task_id']or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0'
            or(pipeline.config.get('delivery')or{}).get('auto_stage_review_required')is not False):raise PermissionError('normal_visual_new_no_publish_scope_required')
    seconds=registered_current_scope(home,task)
    if not 600<=seconds<=900:raise PermissionError('normal_visual_original_900_scope_required')
    expected=Path(store.path).parent/'quality_runtime'/('visual-revision-'+proof['nonce']+'.proof.private.json')
    if Path(proof_path)!=expected:raise PermissionError('normal_visual_owned_proof_required')
    if(pipeline.config.get('media')or{}).get('image',{}).get('real_scene_pool_ref')!=proof['scene_pool_ref']:raise ValueError('normal_visual_exact_current_pool_required')
    owner=pipeline._worker_id();workflow='wf_'+job_id;deadline=time.monotonic()+seconds;suffix='__visual_revision_'+proof['nonce'];new_plan={}
    def guard():
        _,active,_=current_active_role(0);job=store.get_job(job_id)
        if active!=task or time.monotonic()>=deadline or job.get('state')!='generating'or job.get('lease_owner')!=owner or datetime.fromisoformat(job['lease_expires_at'].replace('Z','+00:00')).timestamp()<=time.time():raise PermissionError('normal_visual_current_identity_lease_deadline_required')
        _validate_normal_visual_history(store,history,new_plan_ref=new_plan.get('ref'))
    class Runner(WorkflowStepRunner):
        def _name(self,name):return name+suffix
        def _deps(self,names):return[self._name('generate_visual_content_revision_images'if n=='generate_or_collect_images'else n)for n in names or[]]
        def run(self,name,func,required=True,depends_on=None,require_output=False,input_payload=None):
            if name not in {'collect_current_strategy_accounts','collect_current_strategy_platform_research','prepare_current_twitter_visual_plan','generate_visual_content_revision_images'}and not name.startswith(('validate_current_strategy_raw[','distill_current_strategy_same_lane[','prepare_current_strategy[')):raise PermissionError('normal_visual_source_primary_target_regeneration_forbidden')
            def bounded():guard();result=func();guard();return result
            return super().run(self._name(name),bounded,required,self._deps(depends_on),require_output,input_payload)
        def succeeded(self,name,output=None,required=True,depends_on=None,message=''):
            guard();return super().succeeded(self._name(name),output,required,self._deps(depends_on),message)
        def block(self,name,code,message,gate_result=None,depends_on=None):
            guard();return super().block(self._name(name),code,message,gate_result,self._deps(depends_on))
        def skipped(self,name,code,message,required=False,depends_on=None):
            guard();return super().skipped(self._name(name),code,message,required,self._deps(depends_on))
    with strict_workflow_lock(store,owner,workflow,seconds,pipeline.strict_serial):
        _validate_normal_visual_proof(store,proof)
        write_once(expected.with_name('visual-revision-'+proof['nonce']+'.invocation.private.json'),{'version':NORMAL_VISUAL_VERSION,'task_id':task,'job_id':job_id,'proof_sha256':proof_sha256,'no_publish':True,'automatic_replay':False})
        if not store.claim(job_id,{'blocked'},owner,max(1,math.floor(deadline-time.monotonic())),'generating'):raise PermissionError('normal_visual_already_claimed')
        grant={'guard':guard,'proof':proof,'proof_ref':{'path':str(proof_path),'sha256':proof_sha256},'task':task};_ACTIVE[_key(store,job_id)]=grant
        runner=Runner(store,workflow,job_id,notifier=pipeline.notifier)
        try:
            job=store.get_job(job_id);owned=pipeline._enrich_brief(job);feedback=owned.get('historical_feedback')or{}
            if feedback.get('schema')!='owned_feedback_v1'or feedback.get('status')not in {'verified','unavailable'}:raise PermissionError('normal_visual_owned_feedback_required')
            strategy_job=copy.deepcopy(job)
            for field in ('historical_feedback','platform_historical_feedback','topic_historical_feedback','cluster_memory','legacy_feedback_reference'):strategy_job['brief'][field]=copy.deepcopy(owned[field])
            contexts={p:load_platform_workflow_context(p,plan=strategy_job['brief'])for p in job['platforms']}
            refreshed=refresh_current_strategy_inputs(store,pipeline.config,strategy_job,contexts,runner);prepared=refreshed['brief'];oldbrief=history['job']['brief']
            for field in FACT_FIELDS:
                if prepared.get(field)!=oldbrief.get(field):raise ValueError('normal_visual_original_facts_changed')
            for platform,scoped in refreshed['platform_briefs'].items():
                original=oldbrief['platform_workflow_inputs'][platform]
                if any(scoped.get(field)!=original.get(field)for field in FACT_FIELDS):raise ValueError('normal_visual_scoped_original_facts_changed')
            audit=copy.deepcopy(oldbrief['source_collection_audit']);audit['current_strategy_refresh_audit']=refreshed['strategy_refresh_audit'];prepared['source_collection_audit']=audit
            for scoped in refreshed['platform_briefs'].values():scoped['source_collection_audit']=copy.deepcopy(audit)
            prepared['platform_workflow_inputs']=copy.deepcopy(refreshed['platform_briefs']);job=persist_task_source_inputs(store,job,owner,prepared);contexts=refresh_task_source_contexts(contexts,prepared)
            scoped={p:pipeline._bind_platform_source_inputs(job_id,b,p,contexts[p],owner)for p,b in refreshed['platform_briefs'].items()}
            prepared['platform_workflow_inputs']=copy.deepcopy(scoped);job=persist_task_source_inputs(store,job,owner,prepared)
            draft={k:copy.deepcopy(job[k])for k in ('title','body','draft_meta','prompt_version')};meta=draft['draft_meta'];current_strategy=scoped['twitter']
            for field in ('account_analysis','same_lane_intelligence','strategy_evidence','strategy_evidence_gate','strategy_observation_ref','viral_collection','viral_breakdown','hot_work_parameter_pack','platform_intelligence_constraints','historical_feedback','platform_historical_feedback','topic_historical_feedback','cluster_memory','legacy_feedback_reference'):
                if field in current_strategy:meta[field]=copy.deepcopy(current_strategy[field])
            for field in ('quality_gate','platform_quality_gates','native_quality','final_quality_evidence'):meta.pop(field,None)
            from .humanize import _score,quality_gate
            scores=_score(job['body'],meta);meta.update(quality_scores=scores,quality_gate=quality_gate(scores))
            meta['normal_visual_revision']={'version':NORMAL_VISUAL_VERSION,'nonce':proof['nonce'],'origin_task_id':proof['origin_task_id'],'current_task_id':task,'original_draft_version_id':history['draft_versions'][-1]['id'],'original_primary_replayed':False,'original_target_replayed':False,'original_photo_source_replayed':False,'old_quality_inherited':False}
            plan_ref=runner.run('prepare_current_twitter_visual_plan',lambda:prepare_current_twitter_visual_plan(pipeline,job,draft),require_output=True)
            new_plan['ref']=plan_ref;meta['current_visual_plan_ref']=plan_ref
            generated=pipeline._generate_optional_media(job_id,'image',runner,['prepare_current_twitter_visual_plan'],step_name='generate_visual_content_revision_images',draft=draft)
            if not isinstance(generated,dict)or len(generated.get('images')or[])!=4 or len(generated.get('auxiliary_artifacts')or[])!=2:raise ValueError('normal_visual_actual_new_four_images_required')
            pipeline._validate_image_requirements(job_id,runner,generated)
            store.save_draft(job_id,draft['title'],draft['body'],job['risk_level'],job['risk'],draft['prompt_version'],meta)
            guard()
            return pipeline.continue_rendered_candidate(job_id,owner,runner,generated,{})
        except WorkflowBlocked as exc:
            if store.get_job(job_id).get('lease_owner')==owner:store.release_claim(job_id,owner,'blocked','normal_visual_revision_blocked',str(exc),detail={'reason_code':exc.reason_code})
            raise
        except Exception as exc:
            if store.get_job(job_id).get('lease_owner')==owner:store.release_claim(job_id,owner,'failed','normal_visual_revision_failed',str(exc))
            raise
        finally:_ACTIVE.pop(_key(store,job_id),None)

def run_visual_candidate_revision(pipeline,proof_path,proof_sha256):
    proof=private_read(proof_path,proof_sha256)
    if proof.get('version')==NORMAL_VISUAL_VERSION:return _run_normal_visual_content_revision(pipeline,proof_path,proof_sha256)
    return _run_legacy_visual_candidate_revision(pipeline,proof_path,proof_sha256)
