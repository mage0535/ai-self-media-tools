"""Finite current-role review of already produced bytes; no generation replay."""
import copy,hashlib,json,math,os,re,time
from datetime import datetime
from pathlib import Path
from .factual_candidate_revision import private_read,write_once,registered_current_scope,digest
JOB='25110343c3354385'
NORMALIZED='499741e1e77470353f7ed83f1c9ea0bd9d344152e30dc75b9e97b8ffc63b0518'
GENREF={'path':'/srv/hermes-worker-media/jobs/42f5bbd84ef64a75a37673d621acc559/factual-revision-363f142632b082635779fd983ae2a313.generation.private.json','sha256':'c0dc812e7cbd8394c3dfae3fc1c48fe39455a38ad162edfd2bd54ee3bdfb838f'}
from .target_adaptation import read_target_adaptation

VERSION='twitter-existing-rendered-candidate-review-v1'
ORIGIN='ba31bdec03b2450abc37bb809ab85b7f'
OLD_NONCE='e0df3d591160c3e76573a1a027f7c10d'
CAPTION_SHA='c32286380fcd4a4752d05ac2960a67608f92ccebb8851c72ed516cd1c9dd5d49'
SID='20261014_201355_f5e626'
EXPECTED={5421:'adapt_twitter_target_copy',5432:'validate_target_publication_copy',5433:'run_quality_gate',5435:'generate_illustration',5437:'generate_or_collect_images',5439:'validate_image_requirements',5442:'generate_cover'}

def snapshot(store):
    return {'job':store.get_job(JOB),'steps':store.workflow_steps(JOB),'events':store.events(JOB),
            'draft_versions':store.draft_versions(JOB),'artifacts':store.artifacts(JOB)}

def prepare_rendered_candidate_proof(store,nonce,directory,code_pins):
    if not re.fullmatch('[a-f0-9]{32}',nonce)or nonce==OLD_NONCE:raise PermissionError('rendered_tail_new_nonce_required')
    directory=Path(directory)
    if directory!=store.path.parent/'quality_runtime':raise PermissionError('rendered_tail_Root_owned_preparation_required')
    history=snapshot(store)
    history_ref=write_once(directory/('rendered-tail-'+nonce+'.history.private.json'),history)
    proof={'version':VERSION,'job_id':JOB,'origin_task_id':ORIGIN,'nonce':nonce,'history_ref':history_ref,
           'no_publish':True,'budget_seconds':900,'code_pins':code_pins}
    validate(type('RootRO',(),{'store':store,'data_dir':str(store.path.parent)})(),proof)
    return write_once(directory/('rendered-tail-'+nonce+'.proof.private.json'),proof)

def validate(pipeline,proof,initial=True):
    if (proof.get('version')!=VERSION or proof.get('job_id')!=JOB or proof.get('origin_task_id')!=ORIGIN
            or not re.fullmatch('[a-f0-9]{32}',str(proof.get('nonce')or''))or proof['nonce']==OLD_NONCE
            or proof.get('no_publish')is not True or proof.get('budget_seconds')!=900):raise PermissionError('rendered_tail_exact_contract_required')
    history=private_read(proof['history_ref']['path'],proof['history_ref']['sha256'],limit=16777216)
    store=pipeline.store;steps={r['id']:r for r in store.workflow_steps(JOB)};events={r['id']:r for r in store.events(JOB)}
    for row in history['steps']:
        if steps.get(row['id'])!=row:raise ValueError('rendered_tail_original_step_changed')
    for row in history['events']:
        if events.get(row['id'])!=row:raise ValueError('rendered_tail_original_event_changed')
    for identifier,name in EXPECTED.items():
        row=steps.get(identifier)or{}
        if row.get('status')!='SUCCEEDED'or row.get('step_name')!=name+'__same_draft_'+OLD_NONCE:
            raise PermissionError('rendered_tail_successful_generation_prefix_changed')
    audio=steps.get(5440)or{}
    if (audio.get('step_name')!='generate_audio__same_draft_'+OLD_NONCE or audio.get('status')!='FAILED_RETRYABLE'
            or audio.get('reason_code')!='exception' or audio.get('message')!='voice_plan_missing'):raise PermissionError('rendered_tail_original_audio_failure_changed')
    previous=private_read(Path('/srv/ai-self-media-tools/data/quality_runtime')/('same-draft-'+OLD_NONCE+'.invocation.private.json'))
    if previous.get('task_id')!=ORIGIN or previous.get('job_id')!=JOB or previous.get('no_publish')is not True:
        raise PermissionError('rendered_tail_previous_nonce_not_consumed')
    failure=events.get(7583)or{}
    if failure.get('event')!='same_draft_suffix_failed'or json.loads(failure.get('detail_json')or'{}').get('error')!='required_platform_audio_unowned':raise PermissionError('rendered_tail_exact_known_last_failure_required')
    if any(row.get('event')in{'native_mandatory_quality_attempt','native_mandatory_quality_result'}for row in history['events']):raise PermissionError('rendered_tail_previous_native_quality_effect_unknown')
    original=history['job'];job=store.get_job(JOB)
    if digest({'title':job['title'],'body':job['body']})!=NORMALIZED:raise ValueError('rendered_tail_original_long_candidate_changed')
    target=read_target_adaptation(job,'twitter')
    if (target['caption_sha256']!=CAPTION_SHA or target['adaptation_session_ref'].get('task_id')!=ORIGIN
            or target['adaptation_session_ref'].get('session_id')!=SID or target['adaptation_session_ref'].get('api_call_count')!=1
            or target['source_generation_ref']!=GENREF):raise ValueError('rendered_tail_actual_target_generation_changed')
    if store.platform_outputs(JOB):raise PermissionError('rendered_tail_original_outputs_not_empty')
    if len(history['draft_versions'])!=1 or history['draft_versions'][0].get('id')!=184 or history['draft_versions'][0].get('risk_level')!='unreviewed' or store.draft_versions(JOB)!=history['draft_versions']:
        raise ValueError('rendered_tail_saved_unreviewed_draft_version_changed')
    current={r['id']:r for r in store.artifacts(JOB)}
    original_ids={r['id']for r in history['artifacts']}
    if len(history['artifacts'])!=6 or not original_ids<=set(current):raise ValueError('rendered_tail_exact_existing_artifact_set_required')
    appended=[row for identifier,row in current.items()if identifier not in original_ids]
    if initial and appended:raise ValueError('rendered_tail_initial_foreign_artifact_required')
    if appended:
        from .formatters import format_for_platform
        from .task_source_inputs import project_task_source_job
        caption_object=format_for_platform(project_task_source_job(job,'twitter'),'twitter')
        raw=__import__('json').dumps(caption_object,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        sha=hashlib.sha256(raw).hexdigest()
        expected_path=Path(pipeline.data_dir).resolve()/'artifacts'/JOB/'platforms'/'twitter'/'quality_source_bytes'/('publication_copy-'+sha+'.txt')
        if (len(appended)!=1 or appended[0].get('kind')!='platform_copy'or appended[0].get('path')!=str(expected_path)
                or appended[0].get('checksum')!=sha or any(p.is_symlink()for p in(expected_path,*expected_path.parents))
                or expected_path.read_bytes()!=raw):raise ValueError('rendered_tail_only_exact_native_publication_copy_append_allowed')
    for row in history['artifacts']:
        now=current[row['id']]
        if any(now.get(k)!=row.get(k)for k in('id','job_id','kind','path','checksum')):raise ValueError('rendered_tail_original_artifact_identity_changed')
        path=Path(row['path'])
        if any(p.is_symlink()for p in(path,*path.parents))or not path.is_file()or not path.resolve().is_relative_to(Path(pipeline.data_dir).resolve()):
            raise PermissionError('rendered_tail_original_artifact_owned_path_required')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['checksum']:raise ValueError('rendered_tail_original_artifact_bytes_changed')
    required={'/srv/ai-self-media-tools/content_platform/'+name+'.py'for name in('rendered_candidate_resume','target_adaptation','pipeline','formatters','generator','content_depth')}
    pins=proof.get('code_pins')or[]
    if len(pins)!=len(required)or {r.get('path')for r in pins}!=required:raise PermissionError('rendered_tail_exact_six_code_pins_required')
    for pin in pins:
        if hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()!=pin['sha256']:raise ValueError('rendered_tail_deployed_code_changed')
    if initial and (job!=original or job.get('state')!='failed'or job.get('attempts')!=8
                    or job.get('last_error')!='required_platform_audio_unowned'or job.get('lease_owner')
                    or store.workflow_steps(JOB)!=history['steps']or store.events(JOB)!=history['events']):
        raise PermissionError('rendered_tail_only_known_post_generation_failure_required')
    image=copy.deepcopy(steps[5437]['output']);cover=copy.deepcopy(steps[5442]['output'])
    children=list(image.get('images')or[])
    if image.get('kind')=='cover':children.append(image)
    shared=[] if any(str(row.get('role')or row.get('kind')or'').casefold()=='cover'and row.get('path')==cover.get('path')for row in children) else [('cover',cover)]
    return job,image,{},shared

def run_rendered_candidate_resume(pipeline,proof_path,proof_sha256):
    from .native_quality_runner import current_active_role
    from .workflow_runtime import WorkflowStepRunner,WorkflowBlocked,strict_workflow_lock
    home,task,_=current_active_role(600)
    if task==ORIGIN or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':raise PermissionError('rendered_tail_new_current_no_publish_scope_required')
    seconds=registered_current_scope(home,task)
    if seconds<600:raise PermissionError('rendered_tail_original_budget_insufficient')
    proof=private_read(proof_path,proof_sha256);store=pipeline.store;validate(pipeline,proof)
    owner=pipeline._worker_id();workflow='wf_'+JOB;suffix='__rendered_tail_'+proof['nonce'];deadline=time.monotonic()+seconds
    def guard():
        _,current,_=current_active_role(0);job=store.get_job(JOB)
        if (current!=task or time.monotonic()>=deadline or job.get('state')!='generating'or job.get('lease_owner')!=owner
                or datetime.fromisoformat(job['lease_expires_at'].replace('Z','+00:00')).timestamp()<=time.time()):
            raise PermissionError('rendered_tail_original_900_deadline_or_current_lease_required')
        validate(pipeline,proof,initial=False)
    class Runner(WorkflowStepRunner):
        def _map(self,name):return name+suffix
        def _deps(self,names):
            return ['validate_image_requirements__same_draft_'+OLD_NONCE if n=='validate_image_requirements'else self._map(n)for n in(names or[])]
        def run(self,name,func,required=True,depends_on=None,require_output=False,input_payload=None):
            if name.startswith(('generate_','adapt_','collect_')):raise PermissionError('rendered_tail_all_successful_generation_replay_forbidden')
            def bounded():guard();value=func();guard();return value
            return super().run(self._map(name),bounded,required,self._deps(depends_on),require_output,input_payload)
        def succeeded(self,name,output=None,required=True,depends_on=None,message=''):
            guard();return super().succeeded(self._map(name),output,required,self._deps(depends_on),message)
        def block(self,name,code,message,gate_result=None,depends_on=None):guard();return super().block(self._map(name),code,message,gate_result,self._deps(depends_on))
        def skipped(self,name,code,message,required=False,depends_on=None):guard();return super().skipped(self._map(name),code,message,required,self._deps(depends_on))
    with strict_workflow_lock(store,owner,workflow,seconds,pipeline.strict_serial):
        _,images,videos,shared=validate(pipeline,proof)
        write_once(Path(proof_path).parent/('rendered-tail-'+proof['nonce']+'.invocation.private.json'),
                   {'version':VERSION,'task_id':task,'job_id':JOB,'proof_sha256':proof_sha256,'no_publish':True,'automatic_replay':False})
        if not store.claim(JOB,{'failed'},owner,max(1,math.floor(deadline-time.monotonic())),'generating'):raise PermissionError('rendered_tail_already_claimed')
        runner=Runner(store,workflow,JOB,notifier=pipeline.notifier)
        try:
            guard();result=pipeline.continue_rendered_candidate(JOB,owner,runner,images,videos,shared)
            return result
        except WorkflowBlocked as error:
            if store.get_job(JOB).get('lease_owner')==owner:return pipeline._hydrate(store.release_claim(JOB,owner,'blocked','rendered_tail_review_blocked',error,detail={'step':error.step,'reason_code':error.reason_code,'nonce':proof['nonce']}))
            raise
        except BaseException as error:
            if store.get_job(JOB).get('lease_owner')==owner:store.release_claim(JOB,owner,'failed','rendered_tail_review_failed',str(error))
            raise
