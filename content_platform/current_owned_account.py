"""Current owned X observation through the existing collector and native Store APIs.

Authority remains with the existing registered caller. This leaf does not create a
role, alter a deadline, authenticate, publish, or retry any started observation.
"""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
import copy,fcntl,hashlib,json,math,os,re,sqlite3,stat,time
PROJECT=Path('/srv/ai-self-media-tools')
ORIGINAL_COOKIE=Path('/srv/hermes-runtime/data/cookies/twitter.json')
COOKIE_PRIVATE_ROOT=Path('/srv/hermes-runtime')
ORIGINAL_COLLECTOR_SHA='73911661120ed3b631f13ded9348421a48ce0ae76add9f148dcacde2de6678d9'
sha=lambda value:hashlib.sha256(value).hexdigest()

def _private(path,limit=2*1024*1024):
    path=Path(path)
    if not path.is_absolute()or'..'in path.parts or any(p.is_symlink()for p in(path,*path.parents)):raise ValueError('owned_account_nonlink_original_required')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode)or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or info.st_size>limit:raise ValueError('owned_account_private_bounded_original_required')
    raw=path.read_bytes()
    if len(raw)>limit or path.stat().st_ino!=info.st_ino or path.stat().st_mtime_ns!=info.st_mtime_ns:raise ValueError('owned_account_original_changed_during_read')
    return raw

def _original_cookie(path):
    # This existing registered source predates the 0600 capture-file contract.
    # Its unchanged Root0644 bytes are private behind the actual Root0700
    # runtime boundary; no arbitrary input or global header/raw flag is added.
    path=Path(path)
    if path!=ORIGINAL_COOKIE or not path.is_relative_to(COOKIE_PRIVATE_ROOT):raise ValueError('owned_account_original_cookie_locator_changed')
    for node in(path,*path.parents):
        if node.is_symlink():raise ValueError('owned_account_original_cookie_symlink')
        metadata=node.stat()
        if metadata.st_uid!=0 or metadata.st_mode&0o022:raise PermissionError('owned_account_original_cookie_foreign_writable')
    boundary=COOKIE_PRIVATE_ROOT.stat()
    if not stat.S_ISDIR(boundary.st_mode)or stat.S_IMODE(boundary.st_mode)!=0o700:raise PermissionError('owned_account_original_cookie_private_boundary_changed')
    metadata=path.stat()
    if not stat.S_ISREG(metadata.st_mode)or stat.S_IMODE(metadata.st_mode)not in{0o600,0o644}or metadata.st_nlink!=1 or metadata.st_size>2*1024*1024:raise ValueError('owned_account_original_cookie_file_changed')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        first=os.fstat(fd);raw=os.read(fd,2*1024*1024+1);last=os.fstat(fd)
    finally:os.close(fd)
    if (first.st_dev,first.st_ino,first.st_size,first.st_mtime_ns)!=(last.st_dev,last.st_ino,last.st_size,last.st_mtime_ns)or path.stat().st_ino!=first.st_ino or len(raw)>2*1024*1024:raise ValueError('owned_account_original_cookie_bytes_changed')
    return raw

def _once(path,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return {'path':str(path),'sha256':sha(raw)}

def _parent(path):
    path=Path(path)
    for node in(path,*path.parents):
        if node.is_symlink():raise ValueError('owned_account_runtime_parent_symlink')
        if node.exists()and(node.stat().st_uid!=0 or node.stat().st_mode&0o022):raise PermissionError('owned_account_root_runtime_parent_required')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    if stat.S_IMODE(path.stat().st_mode)!=0o700:raise PermissionError('owned_account_runtime_directory_private_required')

def _observation(reference,expected_profile_url,expected_account_id):
    # Integrity is checked before the original age gate. Expiry never hides a
    # changed raw body, foreign identity, or producer; no synthetic fresh clock.
    from . import twitter_native_source as native
    if not isinstance(reference,dict)or set(reference)!={'path','sha256'}:raise ValueError('owned_account_exact_immutable_reference_required')
    path=Path(reference['path']);raw_header=_private(path,16384)
    if sha(raw_header)!=reference['sha256']:raise ValueError('owned_account_original_header_sha_changed')
    header=json.loads(raw_header)
    if header.get('version')!='native_x_account_snapshot_v1':raise ValueError('owned_account_header_version_invalid')
    program=header.get('capture_program')or{};program_path=Path(native.__file__).resolve();actual_sha=sha(program_path.read_bytes())
    if program.get('path')!=str(program_path)or program.get('sha256')!=actual_sha:
        # Root reviewed and deployed only the benchmark sampler delta for this exact pair.
        # Historical capture bytes stay immutable; only the original expiry result may renew them.
        registered_expired_pair=(program.get('path')==str(program_path)
            and(program.get('sha256'),actual_sha)in{
                ('567b715fc5046bf7a0541d7b12ca225298922f63c2c0801223681c2c6b457b5e','4706b67ca595b7f668cae993d1131bfaebe51ff0780e45107a65dc7448ffc3ff'),
                ('4706b67ca595b7f668cae993d1131bfaebe51ff0780e45107a65dc7448ffc3ff','9745d9200fb6524a0885338933e59befaf950760f0b71ef2bea6c9140a94311a')})
        if not registered_expired_pair:raise ValueError('owned_account_capture_program_changed')
        try:
            native.read_native_account_snapshot(reference,expected_profile_url=expected_profile_url)
        except ValueError as error:
            if str(error)!='native_account_snapshot_observation_expired':raise
        else:
            raise ValueError('owned_account_capture_program_changed')
    raw=_private(header['raw_response_path']);handle=native._profile_handle(expected_profile_url)
    if sha(raw)!=header.get('raw_response_hash'):raise ValueError('owned_account_original_raw_sha_changed')
    normalized=native.normalize_account_response(raw,requested_handle=handle,response_url=header['api_response_url'],http_status=header['http_status'],observed_at=header['collected_at'])
    users=[x for x in native._walk(json.loads(raw))if x.get('__typename')=='User'and str((x.get('core')or{}).get('screen_name')or(x.get('legacy')or{}).get('screen_name')or'').casefold()==handle.casefold()]
    if len(users)!=1 or str(users[0].get('rest_id'))!=expected_account_id:raise ValueError('owned_account_unique_native_identity_mismatch')
    if header.get('account_metrics')!=normalized['account_metrics']or str(header.get('account')or'').casefold()!=handle.casefold():raise ValueError('owned_account_declared_metric_or_handle_changed')
    return header,normalized

def _persist(project,binding,snapshot,control_task_id):
    from .store import Store
    from .admin_store import AdminStore
    store=object.__new__(Store);store.path=project/'data/state.db'
    transaction=sqlite3.connect(store.path,timeout=15);transaction.row_factory=sqlite3.Row
    transaction.execute('PRAGMA foreign_keys=ON');transaction.execute('BEGIN IMMEDIATE')
    @contextmanager
    def same_transaction():yield transaction
    store.connect=same_transaction;admin=AdminStore(store.path);admin.connect=same_transaction
    try:
        current=admin.get_binding_by_key('twitter','main')
        if current!=binding:raise ValueError('owned_account_binding_compare_and_swap_conflict')
        existing_tables={row[0]for row in transaction.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        preserved={table:[(row['__original_rowid'],{k:row[k]for k in row.keys()if k!='__original_rowid'})for row in transaction.execute('SELECT rowid AS __original_rowid,* FROM '+table)]
                   for table in ['jobs','account_snapshots','platform_accounts','publish_receipts','publication_identities','performance']if table in existing_tables}
        fingerprint='native_owned_refresh:'+control_task_id+':'+snapshot['header_ref']['sha256']
        if transaction.execute('SELECT 1 FROM jobs WHERE topic_fingerprint=?',(fingerprint,)).fetchone():raise ValueError('owned_account_existing_intent_no_replay')
        job=store.create_job('Owned X account observation '+snapshot['observed_at'],['twitter'],{'source':'owned_account_native_snapshot','analytics_only':True,'strategy_eligible':False,'account_id':snapshot['account_id'],'internal_account_alias':'main','control_task_id':control_task_id},topic_fingerprint=fingerprint)
        store.save_account_snapshots(job['id'],[snapshot])
        if store.account_snapshots(job['id'])[0]['payload']!=snapshot:raise ValueError('owned_account_snapshot_readback_mismatch')
        config=copy.deepcopy(binding['config']);config.update(native_account_snapshot_ref=snapshot['header_ref'],raw_ref=snapshot['raw_ref'],collected_at=snapshot['observed_at'])
        payload={k:binding[k]for k in['account_key','display_name','auth_type','status','credentials_ref','track','current_status','notes','enabled']};payload['config']=config
        updated=admin.upsert_binding('twitter',payload)
        if updated['config']!=config or any(updated[k]!=binding[k]for k in payload if k!='config'):raise ValueError('owned_account_locator_or_config_changed')
        store.transition(job['id'],{'created'},'completed','owned_account_snapshot_recorded',{'analytics_only':True,'control_task_id':control_task_id,'header_sha256':snapshot['header_ref']['sha256'],'publication_or_content_completed':False})
        if store.get_job(job['id'])['state']!='completed':raise ValueError('owned_account_analytics_job_not_terminal')
        for table,originals in preserved.items():
            for rowid,original in originals:
                after=transaction.execute('SELECT * FROM '+table+' WHERE rowid=?',(rowid,)).fetchone()
                if after is None:raise ValueError('owned_account_original_business_row_removed')
                after=dict(after)
                if table=='platform_accounts'and original['id']==binding['id']:
                    if any(after[k]!=v for k,v in original.items()if k not in {'config_json','updated_at'}):raise ValueError('owned_account_original_locator_changed')
                    if json.loads(after['config_json'])!=config:raise ValueError('owned_account_native_pointer_readback_failed')
                elif after!=original:raise ValueError('owned_account_original_business_row_changed')
        transaction.commit()
    except BaseException:transaction.rollback();raise
    finally:transaction.close()
    return updated,job['id']

def ensure_current_native_account_binding(project_root,binding,*,expected_account_id,expected_profile_url,control_task_id,deadline_unix):
    project=Path(project_root)
    if project!=PROJECT or project.resolve()!=project or os.geteuid()!=0:raise PermissionError('owned_account_formal_project_root_required')
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':raise PermissionError('owned_account_managed_nopub_required')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',str(control_task_id))or not isinstance(deadline_unix,(int,float))or isinstance(deadline_unix,bool)or not math.isfinite(deadline_unix)or deadline_unix-time.time()>3600:raise ValueError('owned_account_current_task_deadline_required')
    from .admin_store import AdminStore
    from .twitter_native_source import read_native_account_snapshot
    from .performance_collectors import collect_platform_metrics
    current=AdminStore(project/'data/state.db').get_binding_by_key('twitter','main')
    if current!=binding:raise ValueError('owned_account_input_binding_not_current')
    config=binding.get('config')or{}
    if (binding.get('platform')!='twitter'or binding.get('account_key')!='main'or config.get('account_id')!=str(expected_account_id)
            or config.get('internal_account_alias')!='main'or config.get('identity_source')!='native_x_official_User_rest_id'):raise ValueError('owned_account_original_identity_binding_required')
    reference=config.get('native_account_snapshot_ref')or{}
    _observation(reference,expected_profile_url,str(expected_account_id))
    try:
        read_native_account_snapshot(reference,expected_profile_url=expected_profile_url)
        return binding
    except ValueError as error:
        if str(error)!='native_account_snapshot_observation_expired':raise
    if deadline_unix-time.time()<75:raise TimeoutError('owned_account_original_deadline_insufficient')
    collector_path=project/'secrets/performance-collector.json';cfg_raw=_private(collector_path);
    if sha(cfg_raw)!=ORIGINAL_COLLECTOR_SHA:raise ValueError('owned_account_original_collector_config_changed')
    cfg=json.loads(cfg_raw);account=cfg.get('x')or cfg.get('twitter')or{}
    if account.get('public_profile_url')!=expected_profile_url:raise ValueError('owned_account_original_collector_profile_mismatch')
    cookie=Path(account.get('state_file')or account.get('cookie_file')or'');cookie_raw=_original_cookie(cookie);cookie_stamp=cookie.stat().st_mtime_ns
    base=project/'data/intel/owned-account-refresh';_parent(base)
    lock=os.open(base/'twitter-main.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # A completed independent writer may have refreshed the binding while
        # this caller waited. No foreign binding is silently overwritten.
        if AdminStore(project/'data/state.db').get_binding_by_key('twitter','main')!=binding:raise ValueError('owned_account_binding_changed_before_capture')
        attempt=base/str(control_task_id);attempt.mkdir(mode=0o700)
        _once(attempt/'started.private.json',{'state':'started_no_replay','control_task_id':control_task_id,'deadline_unix':deadline_unix,'started_at':datetime.now(timezone.utc).isoformat(),'old_header_ref':reference,'collector_config_sha256':sha(cfg_raw),'cookie_sha256':sha(cookie_raw),'model_calls':0,'publish_calls':0})
        try:
            fresh_cfg=copy.deepcopy(cfg);key='x'if cfg.get('x')else'twitter';fresh_cfg[key]['native_account_snapshot']={'path':str(attempt/'latest.private.json')}
            report=collect_platform_metrics(['x'],fresh_cfg,output=attempt/'collection.private.json')
            item=(report.get('platforms')or{}).get('x')or(report.get('platforms')or{}).get('twitter')or{}
            if item.get('status')!='ok':raise ValueError('owned_account_current_capture_unavailable')
            latest=attempt/'latest.private.json';latest_raw=_private(latest,16384);header=json.loads(latest_raw)
            raw_path=Path(header['raw_response_path']);immutable=raw_path.parent/(sha(latest_raw)+'.json')
            if not raw_path.is_relative_to(attempt)or not immutable.is_relative_to(attempt):raise ValueError('owned_account_capture_escaped_current_attempt')
            new_reference={'path':str(immutable),'sha256':sha(latest_raw)}
            captured,normalized=_observation(new_reference,expected_profile_url,str(expected_account_id))
            fresh=read_native_account_snapshot(new_reference,expected_profile_url=expected_profile_url)
            if deadline_unix-time.time()<15:raise TimeoutError('owned_account_original_deadline_exhausted_before_write')
            if _original_cookie(cookie)!=cookie_raw or cookie.stat().st_mtime_ns!=cookie_stamp or _private(collector_path)!=cfg_raw:raise ValueError('owned_account_original_cookie_or_config_changed')
            snapshot={'schema':'owned_account_native_snapshot_v1','platform':'twitter','account_id':str(expected_account_id),'internal_account_alias':'main','account_handle':fresh['account'],'display_name':'verified configured owned X account','metric_scope':'account_snapshot','metrics':normalized['account_metrics'],'missing_metrics':fresh['missing_metrics'],'observed_at':captured['collected_at'],'header_ref':new_reference,'raw_ref':{'path':str(raw_path),'sha256':sha(_private(raw_path))},'collection_ref':{'path':str(attempt/'collection.private.json'),'sha256':sha(_private(attempt/'collection.private.json'))},'control_task_id':control_task_id,'publication_identity_created':False,'strategy_eligible':False,'sample_count':1}
            updated,job_id=_persist(project,binding,snapshot,str(control_task_id))
            _once(attempt/'result.private.json',{'state':'native_owned_account_snapshot_persisted','control_task_id':control_task_id,'analytics_job_id':job_id,'header_ref':new_reference,'raw_ref':snapshot['raw_ref'],'observed_at':snapshot['observed_at'],'metrics':snapshot['metrics'],'missing_metrics':snapshot['missing_metrics'],'cookie_and_config_unchanged':True,'model_calls':0,'publish_calls':0,'automatic_retry':False})
            return updated
        except BaseException as error:
            _once(attempt/'failed.private.json',{'state':'failed_or_unknown_no_replay','error_type':type(error).__name__,'reason_sha256':sha(str(error).encode()),'control_task_id':control_task_id,'automatic_retry':False})
            raise
    finally:os.close(lock)
