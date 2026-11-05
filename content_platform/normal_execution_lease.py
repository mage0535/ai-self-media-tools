"""只把已核验正常首轮作业租约同步到原生执行预算；不续旧失败或修改截止。"""
import hashlib,json,math,os,re,time
from pathlib import Path

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def _claim_seconds(job,control,created,run_map,create_map,receipt,invocation,deadline,worker,now):
    cid=control.get('job_id');create_id=control.get('payload',{}).get('create_control_job_id');mid=job.get('id')
    if (control.get('task_type')!='media_run' or control.get('status')!='running'
            or control.get('worker_id')!=worker or control.get('claim_lane')!='media'
            or type(control.get('lease_until'))not in(int,float) or control['lease_until']<=now
            or set(control.get('payload',{}))!={'create_control_job_id'}
            or receipt.get('task_id')!=cid or receipt.get('profile_id')!=cid
            or receipt.get('business_budget_seconds')!=1800
            or job.get('state')!='created' or job.get('attempts')!=0 or job.get('lease_owner') or job.get('lease_expires_at')):
        raise PermissionError('normal_first_run_actual_scope_required')
    if (created.get('job_id')!=create_id or created.get('task_type')!='media_create' or created.get('status')!='completed'
            or created.get('result',{}).get('ok')is not True or created['result'].get('reason')!='created_not_run'
            or created['result'].get('media_id')!=mid
            or create_map.get('control_id')!=create_id or create_map.get('task_type')!='media_create'
            or create_map.get('phase')!='finished' or create_map.get('media_id')!=mid
            or create_map.get('payload')!=created.get('payload')
            or create_map.get('result')!={key:value for key,value in created['result'].items()
                                         if key not in {'controller_artifact','artifact_sha256'}}
            or run_map.get('control_id')!=cid or run_map.get('task_type')!='media_run'
            or run_map.get('phase')!='run_intent' or run_map.get('create_control_job_id')!=create_id or run_map.get('media_id')!=mid
            or job.get('topic')!=created['payload'].get('topic','').strip()
            or job.get('platforms')!=created['payload'].get('platforms')):
        raise PermissionError('normal_store_created_control_mapping_changed')
    route=created['payload'].get('text_route')or{}
    binding=receipt.get('current_runtime_binding')
    if binding is not None:
        if (binding.get('schema')!='media_current_sdk_route_binding_v1'or binding.get('job_id')!=cid
                or binding.get('budget_seconds')!=1800 or binding.get('payload_sha256')!=hashlib.sha256(canonical(control['payload'])).hexdigest()
                or binding.get('source_snapshot_sha256')!=receipt.get('source_snapshot_sha256')
                or not re.fullmatch('[a-f0-9]{64}',str(binding.get('signature','')))):
            raise PermissionError('normal_current_scope_runtime_binding_changed')
        bound=binding.get('route')or{}
        if (bound.get('requested_provider')!=receipt.get('requested_provider')
                or any(bound.get(k)!=receipt.get('provenance',{}).get(k)for k in('provider','model','endpoint','api_mode'))):
            raise PermissionError('normal_current_sdk_route_provenance_changed')
        if binding.get('route_source')in {'current_root_default','current_native_live_turn'}:
            route={'provider':bound['requested_provider'],'model':bound['model']}
        elif binding.get('route_source')!='accepted_origin_route':raise PermissionError('normal_current_route_source_unknown')
    if route.get('provider')!=receipt.get('requested_provider') or route.get('model')!=receipt.get('provenance',{}).get('model'):
        raise PermissionError('normal_actual_sdk_route_changed')
    if (invocation.get('schema')!='media-authority-stage-boundary-v1' or invocation.get('native_run_invoked')is not True
            or invocation.get('approved_budget_seconds')!=1800 or invocation.get('home')!=receipt.get('home')
            or invocation.get('snapshot_sha256')!=receipt.get('source_snapshot_sha256')):
        raise PermissionError('normal_native_budget_boundary_changed')
    remaining=math.floor(deadline-now)
    if not 0<remaining<=1800:raise PermissionError('normal_original_execution_budget_exhausted_or_changed')
    return remaining

def _private(path):
    path=Path(path);st=path.stat()
    if path.is_symlink()or st.st_uid!=0 or st.st_mode&0o777!=0o600 or st.st_nlink!=1 or not 0<st.st_size<=65536:
        raise PermissionError('normal_execution_private_source_required')
    return json.loads(path.read_bytes()),st

def normal_job_claim_seconds(store,job_id):
    return normal_job_claim(store,job_id)[0]

def normal_job_claim(store,job_id):
    """(seconds, renewable). Only the plain fixed 900 s claim may be renewed by its live owner (MED46); deadline-bound,
    historical and migration-held claims are exact."""
    home=Path(os.environ.get('HERMES_HOME','/unavailable'))
    if home.parent!=Path('/srv/hermes-worker/authority-runtime-homes'):
        return 900,True
    receipt,_=_private(home/'old-runtime-authority.private.json')
    cid=receipt.get('task_id')
    # Historical metadata roles and migration-held execution retain their exact 900-second contract.
    if not re.fullmatch('[a-f0-9]{32}',str(cid or '')):return 900,False
    if store.migration_held(job_id):return 900,False
    import sys,urllib.request
    if '/srv/hermes-worker'not in sys.path:sys.path.insert(0,'/srv/hermes-worker')
    from current_task_runtime import official_verify_current
    from new_media_authority_consumer_r5 import require_role
    raw=(home/'old-runtime-authority.private.json').read_bytes();receipt['authority_receipt_sha256']=hashlib.sha256(raw).hexdigest()
    proof=official_verify_current(receipt);require_role(receipt,proof,0)
    if (proof.get('canonical_auth_reads')!=0 or proof.get('network_attempts')!=0
            or proof.get('official_sdk_global_fallback_none')is not True or proof.get('refresh_grant_present')is not False
            or proof.get('actual_access_sha256')!=receipt.get('access_sha256')or proof.get('provenance')!=receipt.get('provenance')):
        raise PermissionError('normal_claim_actual_sdk_scope_not_verified')
    base=os.environ.get('HERMES_WORKER_CONTROL_URL');worker=os.environ.get('HERMES_WORKER_ID');token=os.environ.get('HERMES_WORKER_CONTROL_TOKEN')
    if base!='http://127.0.0.1:22120'or not worker or not token:raise PermissionError('normal_claim_live_control_missing')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise PermissionError('normal_claim_control_redirect_forbidden')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def control_job(identifier):
        if not re.fullmatch('[a-f0-9]{32}',str(identifier or '')):raise PermissionError('normal_claim_control_id_invalid')
        req=urllib.request.Request(base+'/v1/jobs/'+identifier,headers={'X-Hermes-Worker-Token':token})
        with opener.open(req,timeout=12)as response:
            if response.status!=200:raise PermissionError('normal_claim_control_unavailable')
            raw=response.read(65537)
        if not 0<len(raw)<=65536:raise PermissionError('normal_claim_control_size_invalid')
        return json.loads(raw)
    control=control_job(cid)
    if control.get('task_type')=='channel_cycle':
        if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':raise PermissionError('normal_cycle_NoPub_required')
        stage=Path('/srv/hermes-worker-media/jobs')/cid
        ready,_=_private(stage/'media-authority-ready.private.json')
        job=store.get_job(job_id);origin=(job.get('brief')or{}).get('legacy_channel_origin')or{}
        root=Path('/srv/channel-runtime/.hermes/data/channel-cycle-normal')/hashlib.sha256(str(control.get('request_id')).encode()).hexdigest()
        journal,_=_private(root/(hashlib.sha256(b'twitter_50152965').hexdigest()+'.json'))
        original,_=_private(stage/'channel-input.json')
        if (original.get('job',{}).get('job_id')!=cid or original['job'].get('payload')!=control.get('payload')
                or not re.fullmatch('[a-f0-9]{64}',str(original.get('token','')))):
            raise PermissionError('normal_cycle_original_writer_input_changed')
        check={'job_id':cid,'worker_id':worker,'token':original['token'],'ownership_epoch':control['payload']['ownership_epoch']}
        req=urllib.request.Request(base+'/v1/channel-cycle/writer/check',data=canonical(check),
            headers={'X-Hermes-Worker-Token':token,'Content-Type':'application/json'})
        with opener.open(req,timeout=12)as response:fence=json.load(response)
        if fence!={'ok':True,'owner':'heros','ownership_epoch':check['ownership_epoch']}:
            raise PermissionError('normal_cycle_live_writer_fence_unconfirmed')
        return _channel_claim_seconds(job,control,ready,receipt,journal,worker,time.time()),False
    if control.get('task_type')!='media_run':return 900,True
    created=control_job(control.get('payload',{}).get('create_control_job_id'))
    root=Path('/srv/hermes-worker-media/jobs');stage=root/cid;parent=root/created['job_id']
    for directory in(root,stage,parent,home):
        if directory.is_symlink()or directory.resolve()!=directory:raise PermissionError('normal_claim_stage_binding_invalid')
    run_map,_=_private(stage/'media-run-mapping.json');create_map,_=_private(parent/'media-create-mapping.json')
    invocation,stamp=_private(stage/'media-authority-native-invocation.private.json')
    ready,_=_private(stage/'media-authority-ready.private.json')
    if (ready.get('job_id')!=cid or ready.get('home')!=str(home)or ready.get('snapshot_sha256')!=receipt['source_snapshot_sha256']
            or ready.get('payload_sha256')!=hashlib.sha256(canonical(control['payload'])).hexdigest()
            or run_map.get('payload_sha256')!=ready.get('payload_sha256')
            or create_map.get('payload_sha256')!=hashlib.sha256(canonical(created['payload'])).hexdigest()):
        raise PermissionError('normal_claim_original_authority_journal_changed')
    receipt['current_runtime_binding']=ready.get('current_runtime_binding')
    # Root-owned invocation marker is created immediately before the existing 1800-second CLI call.
    # This earlier bound can shorten the native budget; it can never create grace or extend it.
    return _claim_seconds(store.get_job(job_id),control,created,run_map,create_map,receipt,invocation,
                          stamp.st_mtime+1800,worker,time.time()),False

def _channel_claim_seconds(job,control,ready,receipt,journal,worker,now):
    cid=control.get('job_id');payload=control.get('payload')or{};brief=job.get('brief')or{}
    origin=brief.get('legacy_channel_origin')or{};binding=ready.get('current_runtime_binding')or{}
    if (control.get('task_type')!='channel_cycle' or control.get('status')!='running'
            or worker!='heros' or control.get('worker_id')!=worker or control.get('claim_lane')!='media'
            or type(control.get('lease_until'))not in(int,float) or control['lease_until']<=now
            or receipt.get('task_id')!=cid or receipt.get('profile_id')!=cid or receipt.get('business_budget_seconds')!=3600
            or job.get('state')!='created' or job.get('attempts')!=0 or job.get('lease_owner') or job.get('lease_expires_at')
            or brief.get('source_control_job_id')!=cid or brief.get('source_control_request_id')!=control.get('request_id')
            or origin.get('request_id')!=control.get('request_id') or origin.get('account')!='twitter_50152965'
            or origin.get('stage')!='content_generator' or not re.fullmatch('[a-f0-9]{64}',str(origin.get('source_sha256','')))
            or brief.get('native_account_id')!='50152965' or brief.get('account_id')!='main'):
        raise PermissionError('normal_first_cycle_actual_scope_required')
    if (journal.get('phase')!='run_intent' or journal.get('job_id')!=job.get('id')
            or journal.get('control_id')!=cid or journal.get('origin')!=origin
            or (journal.get('account')or{}).get('account_id')!='50152965'
            or (journal.get('account')or{}).get('internal_account_alias')!='main'
            or (journal.get('account')or{}).get('platform')!='twitter'):
        raise PermissionError('normal_cycle_actual_create_mapping_changed')
    if (binding.get('schema')!='media_current_sdk_route_binding_v1' or binding.get('job_id')!=cid
            or binding.get('source_kind')!='signed_channel_cycle_policy_writer' or binding.get('budget_seconds')!=3600
            or binding.get('payload_sha256')!=hashlib.sha256(canonical(payload)).hexdigest()
            or binding.get('source_snapshot_sha256')!=receipt.get('source_snapshot_sha256')
            or not re.fullmatch('[a-f0-9]{64}',str(binding.get('signature','')))
            or ready.get('job_id')!=cid or ready.get('snapshot_sha256')!=receipt.get('source_snapshot_sha256')):
        raise PermissionError('normal_cycle_current_signed_runtime_changed')
    deadline=binding.get('execution_deadline_unix')
    if type(deadline)not in(int,float) or not math.isfinite(deadline):
        raise PermissionError('normal_cycle_original_deadline_invalid')
    remaining=math.floor(deadline-now)
    if not 0<remaining<=3600:raise PermissionError('normal_cycle_original_deadline_exhausted')
    return remaining
