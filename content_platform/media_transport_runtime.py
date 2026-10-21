"""媒体专用私有 Source 快照与 SDK 初始化后传输映射；导入没有外部副作用。"""
import contextlib
import hashlib
import ipaddress
import json
import math
import os
import re
import stat
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

RUNTIME=Path('/etc/hermes/channel-cycle-runtime.json')
LEGACY_LIMIT=65536
PRIVATE_LIMIT=262144
TASK_ROOTS=(Path('/srv/hermes-worker-media/jobs'),Path('/srv/hermes-worker/jobs'))
MEDIA_HOME_ROOT=Path('/srv/hermes-worker/authority-runtime-homes')
VERSION='hermes-media-transport-adapter-v1'
SNAPSHOT='hermes-media-access-snapshot-v1'
SHA=re.compile(r'[a-f0-9]{64}\Z')
JOB=re.compile(r'[a-f0-9]{32}\Z')
TOKEN_FIELDS={'access_token','expires_in','expiry_timestamp','project_id'}
# An account whose token cannot cover a child window is left out of the task scope instead of capping it.
MIN_ACCOUNT_SECONDS=1200
ACCOUNT_FIELDS={'id','email','priority','disabled','proxy_disabled','protected_models','validation_blocked',
                'validation_blocked_until','validation_url','live_limited_models','quota'}
QUOTA_FIELDS={'models','last_updated','is_forbidden','forbidden_reason','subscription_tier','model_forwarding_rules','quota_groups'}
MODEL_FIELDS={'name','percentage','reset_time','display_name','supports_images','supports_thinking','thinking_budget',
              'recommended','max_tokens','max_output_tokens','model','supported_mime_types'}
GROUP_FIELDS={'display_name','description','buckets'}
BUCKET_FIELDS={'bucket_id','window','remaining_fraction','reset_time','observed_at','cycle_tokens','display_name','description'}
LIMIT_FIELDS={'model','status','reason','until','detected_at','message'}
PROXIES=('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','ALL_PROXY','all_proxy')


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sha(raw):return hashlib.sha256(raw).hexdigest()


def _fail(reason):raise PermissionError(reason)


def strict_json(raw):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:_fail('media_transport_duplicate_json_key')
            out[key]=value
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: _fail('media_transport_nonfinite_json'))


def read_private(path,pin=None,*,maximum=1048576,allowed_modes=(0o600,)):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:_fail('media_transport_absolute_source_required')
    for parent in path.parents:
        info=parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            _fail('media_transport_source_parent_not_root_private')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)or info.st_uid!=0 or info.st_nlink!=1
                or stat.S_IMODE(info.st_mode)not in allowed_modes or not 0<info.st_size<=maximum):
            _fail('media_transport_source_identity_invalid')
        raw=os.read(fd,info.st_size+1)
        if len(raw)!=info.st_size or (pin is not None and sha(raw)!=pin):_fail('media_transport_source_sha_changed')
        after=os.fstat(fd)
        if (info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            _fail('media_transport_source_changed_during_read')
        return raw
    finally:os.close(fd)


def ref_bytes(ref,reader=read_private):
    if (not isinstance(ref,dict)or set(ref)-{'path','sha256','bytes'}or not {'path','sha256'}<=set(ref)
            or not isinstance(ref['path'],str)or not isinstance(ref['sha256'],str)or not SHA.fullmatch(ref['sha256'])
            or ('bytes'in ref and(type(ref['bytes'])is not int or ref['bytes']<=0))):
        _fail('media_transport_reference_invalid')
    raw=reader(ref['path'],ref['sha256'])
    if 'bytes'in ref and ref['bytes']!=len(raw):_fail('media_transport_reference_size_changed')
    return raw


def _loopback(value):
    if not isinstance(value,str)or any(ord(c)<=32 for c in value):_fail('media_transport_proxy_invalid')
    try:
        parsed=urlsplit(value);port=parsed.port
        if (parsed.scheme!='http'or parsed.hostname not in {'127.0.0.1','::1'}or port is None
                or not 0<port<65536 or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('','/v1')):_fail('media_transport_proxy_invalid')
    except ValueError:_fail('media_transport_proxy_invalid')
    return parsed


def adapter_choice(pointer,route,canonical_provider,reader=read_private):
    if pointer is None:return None
    doc=strict_json(ref_bytes(pointer,reader))
    required={'version','requested_provider','canonical_provider','api_mode','logical_endpoint_sha256','adapter_source_ref','accepted_formats'}
    if (not isinstance(doc,dict)or not required<=set(doc)or set(doc)-required-{'transport_proxy'}or doc['version']!=VERSION
            or any(not isinstance(doc[k],str)or not doc[k].strip()or doc[k]!=doc[k].strip()for k in ('requested_provider','canonical_provider','api_mode'))
            or not isinstance(doc['logical_endpoint_sha256'],str)or not SHA.fullmatch(doc['logical_endpoint_sha256'])):
        _fail('media_transport_adapter_invalid')
    formats=doc['accepted_formats']
    if (not isinstance(formats,list)or not formats or any(not isinstance(x,str)or not re.fullmatch('[a-z0-9][a-z0-9_+.-]*',x)for x in formats)
            or len(set(formats))!=len(formats)):_fail('media_transport_formats_invalid')
    ref_bytes(doc['adapter_source_ref'],reader)
    proxy=doc.get('transport_proxy')
    if proxy is not None:
        if (not isinstance(proxy,dict)or set(proxy)!={'url','upstream_url','allowed_methods','allowed_paths'}
                or proxy['allowed_methods']!=['POST']or proxy['allowed_paths']!=['/v1/chat/completions']):_fail('media_transport_proxy_invalid')
        _loopback(proxy['url']);_loopback(proxy['upstream_url'])
    endpoint=route.get('endpoint')
    applies=(doc['requested_provider']==route.get('provider')and doc['canonical_provider']==canonical_provider
             and doc['api_mode']==route.get('api_mode')and isinstance(endpoint,str)and bool(endpoint)
             and doc['logical_endpoint_sha256']==sha(endpoint.rstrip('/').encode()))
    return {'applies':applies,'adapter_ref':dict(pointer),'doc':doc}


def _project(value,fields):
    if not isinstance(value,dict):_fail('media_transport_source_object_required')
    return {k:value[k] for k in fields if k in value}


def project_account(value,expected_id,now):
    account=_project(value,ACCOUNT_FIELDS)
    if account.get('id')!=expected_id or not isinstance(account.get('email'),str)or not account['email']:
        _fail('media_transport_account_identity_changed')
    token=_project(value.get('token'),TOKEN_FIELDS)
    if (not isinstance(token.get('access_token'),str)or not token['access_token']
            or type(token.get('expiry_timestamp'))is not int or type(token.get('expires_in'))is not int
            or token['expires_in']<=0 or not isinstance(token.get('project_id'),str)or not token['project_id']):
        _fail('media_transport_access_snapshot_incomplete')
    for key in ('disabled','proxy_disabled','validation_blocked'):
        if key in account and type(account[key])is not bool:_fail('media_transport_account_state_invalid')
    if not account.get('disabled',False)and not account.get('proxy_disabled',False)and now>=token['expiry_timestamp']-300:
        _fail('media_transport_access_snapshot_expired')
    account['token']=token
    if 'quota'in account and account['quota']is not None:
        quota=_project(account['quota'],QUOTA_FIELDS)
        if 'models'in quota:quota['models']=[_project(x,MODEL_FIELDS)for x in quota['models']]
        if quota.get('quota_groups')is not None:
            quota['quota_groups']=[dict(_project(g,GROUP_FIELDS),buckets=[_project(b,BUCKET_FIELDS)for b in g['buckets']])for g in quota['quota_groups']]
        account['quota']=quota
    if 'live_limited_models'in account:
        account['live_limited_models']={k:_project(v,LIMIT_FIELDS)for k,v in account['live_limited_models'].items()}
    canonical(account)
    return account


def capture_private_snapshot(runtime,request,config_ref,*,deadline,reader=read_private,now=None):
    """只由已通过原前后租约验证的 fresh exporter 调用；不执行 OAuth/HTTP。"""
    now=time.time()if now is None else now
    config=strict_json(ref_bytes(config_ref,reader))
    fields={'version','adapter_ref','source_id','accounts','target_path'}
    if (not isinstance(config,dict)or set(config)!=fields or config['version']!='hermes-media-access-source-v1'
            or not isinstance(config['source_id'],str)or not re.fullmatch('[A-Za-z0-9_.:-]{1,100}',config['source_id'])
            or not isinstance(config['target_path'],str)or not PurePosixPath(config['target_path']).is_absolute()
            or not isinstance(config['accounts'],list)or not 0<=len(config['accounts'])<=64):
        _fail('media_transport_access_source_config_invalid')
    route={'provider':runtime['requested_provider'],'endpoint':runtime['provenance']['endpoint'],'api_mode':runtime['provenance']['api_mode']}
    choice=adapter_choice(config['adapter_ref'],route,runtime['provenance']['provider'],reader)
    if choice is None or not choice['applies']:return None
    job=request.get('task_id')
    if not isinstance(job,str)or not JOB.fullmatch(job)or runtime.get('task_id')!=job:_fail('media_transport_source_task_changed')
    rows=[];ids=set();paths=set()
    for selected in config['accounts']:
        if (not isinstance(selected,dict)or set(selected)!={'id','path'}or not isinstance(selected['id'],str)or not selected['id']
                or selected['id']in ids or selected['path']in paths):_fail('media_transport_account_selection_invalid')
        account_reader=read_account_source if reader is read_private else reader
        raw=account_reader(selected['path']);account=project_account(strict_json(raw),selected['id'],now)
        rows.append({'source_ref':{'path':selected['path'],'sha256':sha(raw)},'account':account})
        ids.add(selected['id']);paths.add(selected['path'])
    if type(deadline)not in(int,float)or not math.isfinite(deadline)or deadline<=now:_fail('media_transport_original_deadline_expired')
    def live(r):return not r['account'].get('disabled',False)and not r['account'].get('proxy_disabled',False)
    # 10-20: one of 4 tokens had 891 s left, so the whole scope got 591 s and the observer child was refused.
    usable=[r for r in rows if not live(r)or r['account']['token']['expiry_timestamp']-300-now>=MIN_ACCOUNT_SECONDS]
    if any(live(r)for r in usable):rows=usable
    snapshot={'schema':SNAPSHOT,'source_config_ref':dict(config_ref),'adapter_ref':dict(config['adapter_ref']),
              'source_id':config['source_id'],'task_id':job,'captured_at_unix':now,
              'expires_at_unix':min([deadline]+[r['account']['token']['expiry_timestamp']-300 for r in rows if not r['account'].get('disabled',False)and not r['account'].get('proxy_disabled',False)]),'accounts':rows}
    binding={'version':'hermes-media-access-binding-v1','sha256':sha(canonical(snapshot)),
             'adapter_ref':dict(config['adapter_ref']),'source_config_ref':dict(config_ref),'target_path':config['target_path']}
    return binding,snapshot


def validate_private_snapshot(binding,snapshot,job_id,*,now=None,fresh=True):
    now=time.time()if now is None else now
    if (not isinstance(binding,dict)or set(binding)!={'version','sha256','adapter_ref','source_config_ref','target_path'}
            or binding['version']!='hermes-media-access-binding-v1'or not isinstance(binding.get('sha256'),str)
            or not SHA.fullmatch(binding['sha256'])or binding['sha256']!=sha(canonical(snapshot))):
        _fail('media_transport_private_snapshot_binding_changed')
    if (not isinstance(snapshot,dict)or set(snapshot)!={'schema','source_config_ref','adapter_ref','source_id','task_id','captured_at_unix','expires_at_unix','accounts'}
            or snapshot['schema']!=SNAPSHOT or snapshot['task_id']!=job_id or not JOB.fullmatch(job_id)
            or snapshot['adapter_ref']!=binding['adapter_ref']or snapshot['source_config_ref']!=binding['source_config_ref']
            or type(snapshot['captured_at_unix'])not in (int,float)or not math.isfinite(snapshot['captured_at_unix'])
            or not 0<=now-snapshot['captured_at_unix'] or (fresh and now-snapshot['captured_at_unix']>120)
            or type(snapshot.get('expires_at_unix'))not in(int,float)or not math.isfinite(snapshot['expires_at_unix'])
            or now>=snapshot['expires_at_unix']or not isinstance(snapshot['accounts'],list)):
        _fail('media_transport_private_snapshot_scope_or_age_changed')
    ids=[]
    for row in snapshot['accounts']:
        if not isinstance(row,dict)or set(row)!={'source_ref','account'}:_fail('media_transport_private_account_invalid')
        account=row['account'];actual=project_account(account,account.get('id'),now)
        if actual!=account:_fail('media_transport_private_field_not_whitelisted')
        ids.append(account['id'])
    if len(ids)!=len(set(ids)):_fail('media_transport_private_duplicate_account')
    return snapshot


def write_new(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())


def install_private_snapshot(home,bundle,*,reader=read_private,now=None):
    runtime=bundle['runtime'];binding=runtime.get('media_transport_snapshot')
    private=bundle.get('media_transport_private_snapshot')
    if binding is None:
        if private is not None:_fail('media_transport_unbound_private_snapshot')
        return None
    snapshot=validate_private_snapshot(binding,private,runtime['task_id'],now=now)
    # 原角色权威已由原 materializer/SDK验完；本副本仅把私域接到相同 Source hash。
    authority=strict_json(reader(Path(home)/'old-runtime-authority.private.json'))
    if (authority.get('source_snapshot_sha256')!=sha(canonical(runtime))or authority.get('task_id')!=runtime['task_id']):
        _fail('media_transport_role_source_changed')
    envelope={'runtime':runtime,'private_snapshot':snapshot}
    path=Path(home)/'media-transport.snapshot.private.json';write_new(path,canonical(envelope))
    publish_private_snapshot(snapshot,binding,reader=reader)
    return {'path':str(path),'sha256':sha(canonical(envelope))}


def activate_sdk_child(route,canonical_provider,home,*,reader=read_private,runtime_path=RUNTIME,now=None,required_seconds=0):
    """必须在 SDK bootstrap/resolver 之后；仅当前 SDK child 调用，不改父进程或签名.env。"""
    home=Path(home)
    if home.parent!=MEDIA_HOME_ROOT or not re.fullmatch('media-[a-f0-9]{32}',home.name):return None
    authority=strict_json(reader(Path(home)/'old-runtime-authority.private.json'))
    qualification=current_channel_qualification(home,authority,reader,now=now)
    if qualification is None:return None
    config=strict_json(reader(runtime_path));choice=adapter_choice(config.get('media_transport_adapter_ref'),route,canonical_provider,reader)
    if choice is None or not choice['applies']or choice['doc'].get('transport_proxy')is None:return None
    endpoint=urlsplit(route['endpoint'])
    if endpoint.scheme!='http'or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        _fail('media_transport_only_plain_http_supported')
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0'or os.environ.get('HERMES_HOME')!=str(home):
        _fail('media_transport_current_sdk_child_required')
    authority=strict_json(reader(Path(home)/'old-runtime-authority.private.json'))
    refresh_sdk_authentication(home,reader=reader,runtime_path=runtime_path,now=now)
    envelope=current_private_envelope(home,reader=reader)
    snapshot=envelope['runtime'];provenance=snapshot.get('provenance')or{}
    if (authority.get('source_snapshot_sha256')!=envelope.get('original_source_sha256',sha(canonical(snapshot)))or authority.get('task_id')!=snapshot.get('task_id')
            or snapshot.get('requested_provider')!=route['provider']or provenance.get('provider')!=canonical_provider
            or any(provenance.get(k)!=route.get(k)for k in ('model','api_mode','endpoint'))):_fail('media_transport_current_role_source_changed')
    private=validate_private_snapshot(snapshot.get('media_transport_snapshot'),envelope['private_snapshot'],snapshot['task_id'],now=now,fresh=False)
    if private['expires_at_unix']>qualification['execution_deadline_unix']:_fail('media_transport_original_scope_deadline_changed')
    if private['adapter_ref']!=choice['adapter_ref']:_fail('media_transport_current_adapter_changed')
    if type(required_seconds)not in(int,float)or not math.isfinite(required_seconds)or required_seconds<0:
        _fail('media_transport_child_budget_invalid')
    if private['expires_at_unix']-(time.time()if now is None else now)<required_seconds:
        _fail('media_transport_access_lifetime_insufficient_for_child')
    # 安装时的原子当前快照也必须同scope；不把旧token或后继不同scope映射冒成本作用。
    current=strict_json(reader(snapshot['media_transport_snapshot']['target_path']))
    if current!=private:_fail('media_transport_current_access_snapshot_changed')
    import run_agent  # 完成官方懒初始化；环境只在此之后改变。
    proxy=choice['doc']['transport_proxy']['url']
    # 只返回受信映射；每个真实client实例显式绑定，不改进程Proxy或NO_PROXY。
    return {'version':'hermes-media-child-transport-v1','task_id':snapshot['task_id'],'adapter_ref':choice['adapter_ref'],
            'snapshot_sha256':sha(canonical(private)),'logical_endpoint_sha256':choice['doc']['logical_endpoint_sha256'],
            'proxy_authority':urlsplit(proxy).netloc,'credentials_logged':False}


def attach_optional_source(bundle,request,*,reader=read_private,runtime_path=RUNTIME,db_path=Path('/var/lib/hermes-worker-control/control.db'),now=None):
    """原 fresh exporter 的唯一新增接点；现 parent 在调用前后保原 lease/HMAC。"""
    if not Path(runtime_path).exists():return bundle
    config=strict_json(reader(runtime_path));pointer=config.get('media_transport_snapshot_source_ref')
    if pointer is None:return bundle
    import sqlite3
    import datetime
    now=time.time()if now is None else now
    job=request.get('task_id')
    if not isinstance(job,str)or not JOB.fullmatch(job):_fail('media_transport_original_task_required')
    with contextlib.closing(sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True))as connection:
        connection.row_factory=sqlite3.Row;connection.execute('PRAGMA query_only=ON')
        row=connection.execute('SELECT task_type,status,claim_lane,worker_id,lease_until FROM jobs WHERE job_id=?',(job,)).fetchone()
        if row is None or row['task_type']!='channel_cycle':return bundle
        if row['status']!='running'or row['claim_lane']!='media'or not row['worker_id']or type(row['lease_until'])not in(int,float)or row['lease_until']<=now:
            _fail('media_transport_original_media_lease_required')
        event=connection.execute("SELECT created_at FROM events WHERE job_id=? AND worker_id=? AND event_type='started' ORDER BY event_id LIMIT 1",(job,row['worker_id'])).fetchone()
        if event is None:_fail('media_transport_original_start_required')
        started=datetime.datetime.fromisoformat(str(event['created_at']).replace('Z','+00:00'))
        if started.tzinfo is None:_fail('media_transport_original_start_timezone_required')
        deadline=started.timestamp()+3600
    source_config=strict_json(ref_bytes(pointer,reader))
    if source_config.get('adapter_ref')!=config.get('media_transport_adapter_ref'):_fail('media_transport_source_adapter_config_changed')
    captured=capture_private_snapshot(bundle['runtime'],request,pointer,deadline=deadline,reader=reader,now=now)
    if captured is None:return bundle
    binding,snapshot=captured
    result=dict(bundle,runtime=dict(bundle['runtime'],media_transport_snapshot=binding),media_transport_private_snapshot=snapshot)
    validate_bundle_size(result,job,3600,len(canonical(result)),now=now)
    return result


def verify_sdk_child_transport(expected,route,canonical_provider,home,**kwargs):
    if expected is None:return
    actual=activate_sdk_child(route,canonical_provider,home,**kwargs)
    if actual!=expected:_fail('media_transport_active_binding_changed')


def read_account_source(path):
    # 原官方账号只读取数据，不执行；保持其原600/644权限，绝不chmod原件。
    return read_private(path,allowed_modes=(0o600,0o644))


def validate_bundle_size(bundle,job_id,budget,wire_bytes,*,now=None):
    """仅已绑定私域增加容量，剥离私域的原响应仍不超过64KiB。"""
    if type(wire_bytes)is not int or not 0<wire_bytes<=PRIVATE_LIMIT:_fail('media_transport_source_response_limit')
    runtime=bundle.get('runtime')if isinstance(bundle,dict)else None
    binding=runtime.get('media_transport_snapshot')if isinstance(runtime,dict)else None
    private=bundle.get('media_transport_private_snapshot')if isinstance(bundle,dict)else None
    if binding is None and private is None:
        if wire_bytes>LEGACY_LIMIT:_fail('media_transport_legacy_source_response_limit')
        return False
    if budget!=3600 or runtime.get('business_budget_seconds')!=3600 or runtime.get('task_id')!=job_id or runtime.get('profile_id')!=job_id:
        _fail('media_transport_channel_private_scope_required')
    validate_private_snapshot(binding,private,job_id,now=now)
    legacy=dict(bundle);legacy.pop('media_transport_private_snapshot',None)
    legacy['runtime']=dict(runtime);legacy['runtime'].pop('media_transport_snapshot',None)
    if len(canonical(legacy))>LEGACY_LIMIT:_fail('media_transport_legacy_source_response_limit')
    return True


def current_channel_qualification(home,authority,reader=read_private,*,now=None):
    # 资格来自原Root600角色/已签runtime ready；不使用.env或调用方裸flag。
    if authority.get('business_budget_seconds')!=3600:return None
    job=authority.get('task_id')
    if not isinstance(job,str)or not JOB.fullmatch(job)or authority.get('profile_id')!=job or home.name!='media-'+job:
        _fail('media_transport_original_role_identity_changed')
    ready=[]
    for root in TASK_ROOTS:
        try:raw=reader(root/job/'media-authority-ready.private.json')
        except FileNotFoundError:continue
        ready.append(strict_json(raw))
    if len(ready)!=1:_fail('media_transport_original_channel_ready_required')
    value=ready[0];binding=value.get('current_runtime_binding')or{}
    if (value.get('schema')!='media-original-authority-ready-v1'or value.get('job_id')!=job or value.get('home')!=str(home)
            or value.get('snapshot_sha256')!=authority.get('source_snapshot_sha256')
            or binding.get('schema')!='media_current_sdk_route_binding_v1'or binding.get('job_id')!=job
            or binding.get('source_snapshot_sha256')!=authority.get('source_snapshot_sha256')
            or binding.get('source_kind')!='signed_channel_cycle_policy_writer'or binding.get('budget_seconds')!=3600
            or not isinstance(binding.get('signature'),str)or not SHA.fullmatch(binding['signature'])):
        _fail('media_transport_original_channel_binding_changed')
    deadline=binding.get('execution_deadline_unix');now=time.time()if now is None else now
    if type(deadline)not in(int,float)or not math.isfinite(deadline)or not now<deadline:_fail('media_transport_original_channel_deadline_expired')
    return binding


def publish_private_snapshot(snapshot,binding,*,reader=read_private):
    # 共享隔离实例只接当前最新捕获；单文件原子替换，不删除历史每任务原件。
    import fcntl
    target=Path(binding['target_path'])
    if not target.is_absolute()or not target.parent.is_dir():_fail('media_transport_snapshot_target_invalid')
    for parent in (target.parent,*target.parents):
        info=parent.lstat()
        if stat.S_ISLNK(info.st_mode)or info.st_uid!=0 or info.st_mode&0o022:_fail('media_transport_snapshot_target_invalid')
    if stat.S_IMODE(target.parent.stat().st_mode)!=0o700:_fail('media_transport_snapshot_parent700_required')
    lock=os.open(str(target)+'.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(lock)
        if info.st_uid!=0 or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:_fail('media_transport_snapshot_lock_invalid')
        fcntl.flock(lock,fcntl.LOCK_EX)
        if target.exists():
            previous=strict_json(reader(target))
            if previous.get('captured_at_unix',float('inf'))>snapshot['captured_at_unix']:_fail('media_transport_snapshot_older_than_current')
            if previous.get('captured_at_unix')==snapshot['captured_at_unix']and previous!=snapshot:_fail('media_transport_snapshot_same_time_conflict')
        temporary=target.with_name(target.name+'.'+snapshot['task_id']+'.new')
        write_new(temporary,canonical(snapshot));os.replace(temporary,target)
        directory=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:os.close(lock)



_CHILD_REFRESHED=set()

def current_private_envelope(home,*,reader=read_private):
    original=strict_json(reader(Path(home)/'media-transport.snapshot.private.json'))
    pointer=Path(home)/'media-transport-auth-current.private.json'
    try:ref=strict_json(reader(pointer))
    except FileNotFoundError:return original
    value=strict_json(ref_bytes(ref,reader))
    if (value.get('version')!='hermes-media-auth-refresh-v1'
            or value.get('original_source_sha256')!=sha(canonical(original['runtime']))
            or not isinstance(value.get('bundle'),dict)):_fail('media_transport_refresh_origin_changed')
    compare_auth_refresh(original['runtime'],value['bundle']['runtime'])
    return {'runtime':value['bundle']['runtime'],'private_snapshot':value['bundle']['media_transport_private_snapshot'],
            'original_source_sha256':value['original_source_sha256']}


def compare_auth_refresh(original,current):
    # 只允许真实新捕获时点和私域access/配额投影轮换；主Role key/route/规则仍精同。
    def invariant(value):
        result=dict(value)
        for key in ('captured_at_unix','auth_before_sha256','auth_after_sha256','auth_file_identity_changed','media_transport_snapshot'):
            result.pop(key,None)
        if isinstance(result.get('current_modal'),dict):
            result['current_modal']=dict(result['current_modal']);result['current_modal'].pop('captured_at_unix',None)
        return result
    if invariant(original)!=invariant(current):_fail('media_transport_refresh_signed_role_or_rules_changed')
    captured=current.get('captured_at_unix')
    prior=original.get('captured_at_unix')
    if (type(captured)not in(int,float)or not math.isfinite(captured)or type(prior)not in(int,float)
            or not math.isfinite(prior)or captured<prior):_fail('media_transport_refresh_capture_time_invalid')


def refresh_sdk_authentication(home,*,reader=read_private,runtime_path=RUNTIME,now=None):
    key=(os.getpid(),str(home))
    if key in _CHILD_REFRESHED:return
    authority=strict_json(reader(Path(home)/'old-runtime-authority.private.json'))
    if current_channel_qualification(Path(home),authority,reader,now=now)is None:return
    config=strict_json(reader(runtime_path))
    if config.get('media_transport_adapter_ref')is None:return
    # 仍走4817原loopback认证Source/HMAC及两次lease门；不重新建Role或改签名.env。
    import sys
    stage=Path('/srv/hermes-worker/staging/old-authority-role-runtime-20261011-r1')
    source=stage/'new_media_authority_consumer_r5.py'
    pin=(config.get('normal_release_dependencies')or{}).get(str(source))
    if not isinstance(pin,str)or not SHA.fullmatch(pin)or sha(source.read_bytes())!=pin:
        _fail('media_transport_refresh_consumer_source_changed')
    if str(stage)not in sys.path:sys.path.insert(0,str(stage))
    import new_media_authority_consumer_r5 as consumer
    if Path(consumer.__file__).resolve()!=source:_fail('media_transport_refresh_consumer_import_changed')
    consumer.refresh_transport_authentication(Path(home))
    _CHILD_REFRESHED.add(key)


def _atomic_private_pointer(path,value):
    import uuid
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.new')
    write_new(temporary,canonical(value));os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def activate_installed_snapshot(home,bundle,*,reader=read_private,run=None,now=None):
    runtime=bundle['runtime'];binding=runtime.get('media_transport_snapshot')
    if binding is None:return None
    now=time.time()if now is None else now
    private=validate_private_snapshot(binding,bundle.get('media_transport_private_snapshot'),runtime['task_id'],now=now)
    config=strict_json(reader(RUNTIME));route={'provider':runtime['requested_provider'],**{k:runtime['provenance'][k]for k in('model','endpoint','api_mode')}}
    choice=adapter_choice(config.get('media_transport_adapter_ref'),route,runtime['provenance']['provider'],reader)
    if choice is None or not choice['applies']or choice['doc'].get('transport_proxy')is None:return None
    if strict_json(reader(binding['target_path']))!=private:_fail('media_transport_activation_snapshot_changed')
    import subprocess
    remaining=private['expires_at_unix']-time.time()
    if remaining<=0:_fail('media_transport_activation_deadline_expired')
    done=(run or subprocess.run)(['/bin/systemctl','start','--wait','hermes-media-isolated-activate.service'],
        capture_output=True,timeout=min(30.,remaining),check=False)
    if done.returncode:_fail('media_transport_fixed_activation_failed')
    receipt=strict_json(reader('/run/hermes-media-isolated/activation.private.json'))
    if (receipt.get('schema')!='hermes-media-isolated-activation-v1'or receipt.get('snapshot_sha256')!=sha(canonical(private))
            or receipt.get('task_id')!=runtime['task_id']or receipt.get('running')is not True
            or type(receipt.get('active_accounts'))is not int or receipt['active_accounts']<=0
            or not now<=receipt.get('checked_at_unix',0)<private['expires_at_unix']):
        _fail('media_transport_fixed_activation_not_verified')
    return {'schema':receipt['schema'],'snapshot_sha256':receipt['snapshot_sha256'],'task_id':runtime['task_id']}


def run_original_hermes_cli(arguments,route,home,*,required_seconds=0):
    import sys,traceback
    import hermes_cli.main as main
    import run_agent
    parser,subparsers=main._build_cli_parser()
    args=main._parse_cli_args(parser,subparsers,list(arguments))
    if not getattr(args,'oneshot',None):_fail('media_transport_only_original_oneshot_supported')
    if getattr(args,'provider',None)!=route['provider']or getattr(args,'model',None)!=route['model']:
        _fail('media_transport_cli_current_route_changed')
    main._prepare_agent_startup(args)
    main._confirm_startup_expensive_model_override(args)
    main._resolve_chat_session_args(args,use_tui=False)
    try:
        rc=run_current_media_oneshot(args.oneshot,model=args.model,provider=args.provider,
            toolsets=getattr(args,'toolsets',None),skills=getattr(args,'skills',None),usage_file=getattr(args,'usage_file',None),
            resume=getattr(args,'resume',None),reasoning=getattr(args,'reasoning',None),required_seconds=required_seconds)
    except KeyboardInterrupt:rc=130
    except SystemExit as exc:
        if exc.code is not None and not isinstance(exc.code,int):print(exc.code,file=sys.stderr);rc=1
        else:rc=exc.code
    except BaseException:
        traceback.print_exc();rc=1
    try:main._cleanup_oneshot_runtime()
    finally:main._exit_after_oneshot(rc)


def original_role_proxy(home,base,*,reader=read_private):
    import io
    from dotenv import dotenv_values
    from agent.proxy_bypass import PROXY_ENV_KEYS,should_bypass_proxy
    authority=strict_json(reader(Path(home)/'old-runtime-authority.private.json'))
    values=dotenv_values(stream=io.StringIO(reader(Path(home)/'.env',authority['profile_env_sha256']).decode('utf-8-sig')))
    bypass=','.join(str(values.get(key)or'')for key in('NO_PROXY','no_proxy'))
    if should_bypass_proxy(base,no_proxy_value=bypass):return None
    return next((str(values[key]).strip()for key in PROXY_ENV_KEYS if values.get(key)and str(values[key]).strip()),None)


def audio_transport_proxy(route,canonical_provider,home,*,modal,receipt,reader=read_private,runtime_path=RUNTIME,required_seconds=0):
    # 辅助音频允许原签current_modal的专用route；绝不硬套主Role的model。
    from .normal_modal_runtime import _selected_audio_route
    selected,_,source=_selected_audio_route(modal,receipt)
    if (selected.get('provider')!=route.get('provider')or selected.get('model')!=route.get('model')
            or any(selected.get(k)and selected[k]!=route.get(k)for k in('api_mode','endpoint'))):
        _fail('media_transport_audio_signed_selection_changed')
    config=strict_json(reader(runtime_path));choice=adapter_choice(config.get('media_transport_adapter_ref'),route,canonical_provider,reader)
    if choice is None or not choice['applies']or choice['doc'].get('transport_proxy')is None:
        return original_role_proxy(home,route['endpoint'],reader=reader)
    authority=strict_json(reader(Path(home)/'old-runtime-authority.private.json'))
    main_route={'provider':authority.get('requested_provider'),**{k:(authority.get('provenance')or{}).get(k)for k in('model','endpoint','api_mode')}}
    main_choice=adapter_choice(config.get('media_transport_adapter_ref'),main_route,(authority.get('provenance')or{}).get('provider'),reader)
    if main_choice is None or not main_choice['applies']:
        return original_role_proxy(home,route['endpoint'],reader=reader)
    # 映射资格仍来自真实channel ready和主Role原私域；只允许明确支持的chat协议。
    if route['api_mode']!='chat_completions':_fail('media_transport_audio_nonchat_adapter_forbidden')
    authority=strict_json(reader(Path(home)/'old-runtime-authority.private.json'))
    qualification=current_channel_qualification(Path(home),authority,reader)
    if qualification is None:return original_role_proxy(home,route['endpoint'],reader=reader)
    refresh_sdk_authentication(home,reader=reader,runtime_path=runtime_path)
    envelope=current_private_envelope(home,reader=reader);runtime=envelope['runtime']
    private=validate_private_snapshot(runtime.get('media_transport_snapshot'),envelope['private_snapshot'],runtime['task_id'],fresh=False)
    if type(required_seconds)not in(int,float)or not math.isfinite(required_seconds)or required_seconds<0:_fail('media_transport_audio_budget_invalid')
    if private['expires_at_unix']-time.time()<required_seconds:_fail('media_transport_audio_lifetime_insufficient')
    if private['adapter_ref']!=choice['adapter_ref']or strict_json(reader(runtime['media_transport_snapshot']['target_path']))!=private:
        _fail('media_transport_audio_current_snapshot_changed')
    return choice['doc']['transport_proxy']['url']


def bind_audio_client_transport(client,route,canonical_provider,home,*,modal,receipt,reader=read_private,runtime_path=RUNTIME,required_seconds=0):
    # 原签current_modal资格先验，再复制此真实官方client；不改全局工厂。
    if strict_json(reader(runtime_path)).get('media_transport_adapter_ref')is None:return client
    proxy=audio_transport_proxy(route,canonical_provider,home,modal=modal,receipt=receipt,reader=reader,runtime_path=runtime_path,required_seconds=required_seconds)
    return copy_official_client_proxy(client,proxy)


def copy_official_client_proxy(client,proxy):
    import httpx,ssl
    from openai import Omit
    original=getattr(client,'_client',None)
    asynchronous=isinstance(original,httpx.AsyncClient)
    if not isinstance(original,(httpx.Client,httpx.AsyncClient))or not callable(getattr(client,'with_options',None)):
        _fail('media_transport_explicit_http_client_required')
    # 读取官方实际endpoint所选transport，保其TLS上下文和连接池参数，绝不猜verify默认值。
    transport=original._transport_for_url(httpx.URL(str(client.base_url)))
    pool=getattr(transport,'_pool',None);verify=getattr(pool,'_ssl_context',None)
    if not isinstance(verify,ssl.SSLContext):_fail('media_transport_official_tls_context_required')
    limits={k:getattr(pool,k,None)for k in('_max_connections','_max_keepalive_connections','_keepalive_expiry')}
    if any(v is None for v in limits.values()):_fail('media_transport_official_pool_limits_required')
    cls=httpx.AsyncClient if asynchronous else httpx.Client
    replacement=cls(proxy=proxy,verify=verify,trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=limits['_max_keepalive_connections'],max_connections=limits['_max_connections'],keepalive_expiry=limits['_keepalive_expiry']),
        timeout=original.timeout,event_hooks={k:list(v)for k,v in original.event_hooks.items()})
    copied=client.with_options(http_client=replacement,timeout=client.timeout,max_retries=client.max_retries,set_default_headers=dict(client.default_headers))
    def wire_headers(value):return httpx.Headers({k:v for k,v in value.items()if not isinstance(v,Omit)})
    unchanged={'endpoint':str(copied.base_url)==str(client.base_url),'key':copied.api_key==client.api_key,
        'headers':wire_headers(copied.default_headers)==wire_headers(client.default_headers),'timeout':copied.timeout==client.timeout,
        'retry':copied.max_retries==client.max_retries}
    if not all(unchanged.values()):_fail('media_transport_client_identity_changed_'+','.join(k for k,v in unchanged.items()if not v))
    return copied


def bind_current_role_client_transport(client,route,canonical_provider,home,*,required_seconds=0,reader=read_private,runtime_path=RUNTIME):
    binding=activate_sdk_child(route,canonical_provider,home,required_seconds=required_seconds,reader=reader,runtime_path=runtime_path)
    if binding is None:return client
    choice=adapter_choice(strict_json(reader(runtime_path)).get('media_transport_adapter_ref'),route,canonical_provider,reader)
    if choice is None or not choice['applies']:_fail('media_transport_client_mapping_changed')
    if str(getattr(client,'base_url','')).rstrip('/')!=str(route['endpoint']).rstrip('/'):
        _fail('media_transport_client_logical_endpoint_changed')
    return copy_official_client_proxy(client,choice['doc']['transport_proxy']['url'])


def bind_current_agent_transport(agent,*,required_seconds=0):
    from .mandatory_quality_context import _native_task_home
    task=os.environ.get('HERMES_TASK_JOB_ID');home,route,provenance=_native_task_home(task)
    if activate_sdk_child(route,provenance['provider'],home,required_seconds=required_seconds)is None:return None
    if (getattr(agent,'model',None)!=route['model']or getattr(agent,'provider',None)!=provenance['provider']
            or getattr(agent,'api_mode',None)!=route['api_mode']):_fail('media_transport_agent_current_role_changed')
    original=agent.client
    copied=bind_current_role_client_transport(original,route,provenance['provider'],home,required_seconds=required_seconds)
    if copied is original:return None
    agent.client=copied
    if hasattr(agent,'_client_shared'):agent._client_shared=False
    factory=agent._create_request_openai_client
    def current_request_factory(*args,**kwargs):
        value=factory(*args,**kwargs)
        # 此请求可能晚于构造；不重置原总预算，只保证当前快照尚有效。
        return bind_current_role_client_transport(value,route,provenance['provider'],home)
    agent._create_request_openai_client=current_request_factory
    return {'task_id':task,'logical_endpoint_sha256':sha(route['endpoint'].rstrip('/').encode())}


def native_audio_network_proxy(base,home):
    # 原生Google等非chat专用协议保持签名.env的原网络策略，不能继承主chat的局部映射。
    config=strict_json(read_private(RUNTIME))
    if config.get('media_transport_adapter_ref')is None:
        from agent.process_bootstrap import _get_proxy_for_base_url
        return _get_proxy_for_base_url(base)
    return original_role_proxy(home,base)


def wrap_current_cli_command(command,timeout):
    home=Path(os.environ.get('HERMES_HOME','/unavailable'))
    if home.parent!=MEDIA_HOME_ROOT:return command
    authority=strict_json(read_private(home/'old-runtime-authority.private.json'))
    if current_channel_qualification(home,authority)is None:return command
    if strict_json(read_private(RUNTIME)).get('media_transport_adapter_ref')is None:return command
    from .native_quality_runner import current_active_role
    active,_,route=current_active_role(timeout)
    choice=adapter_choice(strict_json(read_private(RUNTIME)).get('media_transport_adapter_ref'),route,(authority.get('provenance')or{})['provider'])
    if choice is None or not choice['applies']or choice['doc'].get('transport_proxy')is None:return command
    if active!=home:_fail('media_transport_cli_original_home_changed')
    code=('import sys,json,pathlib;sys.path.insert(0,sys.argv[1]);'
        'from hermes_constants import set_hermes_home_override;set_hermes_home_override(pathlib.Path(sys.argv[2]));'
        'sys.path.insert(0,sys.argv[3]);from content_platform.media_transport_runtime import run_original_hermes_cli;'
        'run_original_hermes_cli(json.loads(sys.argv[4]),json.loads(sys.argv[5]),sys.argv[2],required_seconds=float(sys.argv[6]))')
    return ['/srv/hermes-agent/.venv/bin/python','-I','-B','-c',code,str((home/'hermes-agent').resolve()),str(home),
        str(Path(__file__).resolve().parents[1]),json.dumps(command[1:]),json.dumps(route),str(timeout)]


def _media_run_agent(
    prompt: str,
    model: str | None = None,
    provider: str | None = None,
    toolsets: object = None,
    use_config_toolsets: bool = True,
    skills: object = None,
    resume: str | None = None,
    reasoning: object = None,
    ledger: bool = False,
) -> tuple[str, dict]:
    """Build an AIAgent exactly like a normal CLI chat turn, run one conversation, and return
    ``(final_response, run_result)``. Imports are local to keep CLI startup cheap. *ledger* (set when
    ``--usage-file`` is requested) attaches this run's auxiliary usage to the result."""
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_with_fallback
    from hermes_cli.tools_config import _get_platform_tools
    from run_agent import AIAgent

    cfg = load_config()
    choice = _resolve_model_and_provider(cfg, model, provider)
    # Resume resolves BEFORE the runtime provider: the session's stored model/route must
    # replace the ambient config (see _apply_stored_session_runtime) and the ended row must
    # be reopened before the agent can stamp a new lifecycle boundary.
    session_db = _create_session_db_for_oneshot()
    resume_sid, conversation_history, resume_meta = _load_resume_target(session_db, resume)
    choice = _apply_stored_session_runtime(choice, resume_meta, explicit_model=bool((model or "").strip()))
    # Resolution-time fallback (#81209): a quota-exhausted/expired primary raises AuthError here, before
    # AIAgent (and its mid-session ``fallback_model`` wiring) exists, so walk the chain like the gateway.
    runtime, fallback_entry = resolve_runtime_with_fallback(
        cfg,
        requested=choice.provider,
        target_model=choice.model or None,
        explicit_base_url=choice.base_url,
        explicit_api_key=choice.api_key,
    )
    if fallback_entry is not None:
        # The chosen entry names the model that will be sent; the primary's stored api_mode no longer applies.
        choice = dataclasses.replace(choice, model=fallback_entry["model"], provider=runtime.get("provider"),
                                     api_mode=None)
    if choice.api_mode:
        runtime["api_mode"] = choice.api_mode

    from hermes_constants import parse_reasoning_effort, resolve_reasoning_config

    reasoning_config = resolve_reasoning_config(cfg, choice.model)
    if reasoning is not None and str(reasoning).strip():
        parsed_reasoning = parse_reasoning_effort(reasoning)
        if parsed_reasoning is None:
            logging.warning("Unknown --reasoning '%s', keeping the configured level", reasoning)
        else:
            reasoning_config = parsed_reasoning

    # sorted() gives stable ordering for config-derived sets; explicit values preserve user order.
    toolsets_list = _normalize_toolsets(toolsets)
    if toolsets_list is None and use_config_toolsets:
        toolsets_list = sorted(_get_platform_tools(cfg, "cli"))

    # Oneshot builds AIAgent directly, bypassing cli.py's MCP background discovery and
    # _init_agent's wait, so the construction-time tool snapshot would miss late MCP servers.
    # Idempotent start + bounded wait with the single-query bound (there is no later turn).
    # Ensure MCP tools are discovered before building the agent. This helper starts discovery if needed
    # (idempotent) and bounded-waits with the larger single-query bound (default 15s) because there is only
    # ONE turn and no between-turns late-binding refresh (#38448).
    from hermes_cli.mcp_startup import ensure_mcp_discovery_before_agent_build

    ensure_mcp_discovery_before_agent_build(logger=logging.getLogger(__name__), single_query=True)

    skills_prompt = _build_preloaded_skills_prompt(skills)

    # The try spans agent construction (not just ``chat``) so the store is always closed, even when
    # ``AIAgent(...)`` raises — the one-shot exit path hard-exits via os._exit and skips finalizers.
    agent = None
    try:
        agent = AIAgent(
            api_key=runtime.get("api_key"),
            base_url=runtime.get("base_url"),
            provider=runtime.get("provider"),
            requested_provider=runtime.get("requested_provider"),
            api_mode=runtime.get("api_mode"),
            model=choice.model,
            enabled_toolsets=toolsets_list,
            quiet_mode=True,
            platform="cli",
            session_db=session_db,
            session_id=resume_sid,
            credential_pool=runtime.get("credential_pool"),
            fallback_model=get_fallback_chain(cfg) or None,
            ephemeral_system_prompt=skills_prompt,
            reasoning_config=reasoning_config,
            # The only interactive callback wired: no user sits at a terminal. Sudo prompts gate on
            # HERMES_INTERACTIVE (never set), hook approval via HERMES_ACCEPT_HOOKS=1, dangerous
            # commands via HERMES_YOLO_MODE=1, skill secret capture degrades gracefully.
            clarify_callback=_oneshot_clarify_callback,
        )
        bind_current_agent_transport(agent,required_seconds=_media_required_seconds)
        # Belt-and-braces: no streaming display callbacks may bypass our stdout capture.
        agent.suppress_status_output = True
        agent.stream_delta_callback = None
        agent.tool_gen_callback = None

        aux_before = _auxiliary_usage(session_db, resume_sid) if ledger else {}
        result = agent.run_conversation(prompt, conversation_history=conversation_history or None)
        if ledger:
            _attach_auxiliary_usage(result, session_db, aux_before,
                                    fallback_session_id=agent.session_id or resume_sid)
        return (result.get("final_response") or "", result)
    finally:
        _close_agent(agent, session_db)

def run_current_media_oneshot(*args,required_seconds=0,**kwargs):
    """官方oneshot代码原样，私有globals副本只指向项目受管构造，不写SDK模块全局。"""
    import inspect,types
    from hermes_cli import oneshot as native
    source=Path(inspect.getsourcefile(native._run_agent)).resolve()
    if sha(source.read_bytes())!='b6c683e73edfec2622a44078ea44dc5eb82226f67133952b625914c89fe91e53':
        _fail('media_transport_official_oneshot_source_changed')
    from hermes_cli.config import load_config
    from hermes_cli.fallback_config import get_fallback_chain
    from .mandatory_quality_context import _native_task_home
    home,route,provenance=_native_task_home(os.environ.get('HERMES_TASK_JOB_ID'))
    choice=adapter_choice(strict_json(read_private(RUNTIME)).get('media_transport_adapter_ref'),route,provenance['provider'])
    if choice is None or not choice['applies']or choice['doc'].get('transport_proxy')is None:return native.run_oneshot(*args,**kwargs)
    if get_fallback_chain(load_config()):_fail('media_transport_implicit_fallback_forbidden')
    context=dict(native._run_agent.__globals__,bind_current_agent_transport=bind_current_agent_transport,_media_required_seconds=required_seconds)
    construction=types.FunctionType(_media_run_agent.__code__,context,argdefs=_media_run_agent.__defaults__)
    context=dict(native.run_oneshot.__globals__,_run_agent=construction)
    official=types.FunctionType(native.run_oneshot.__code__,context,argdefs=native.run_oneshot.__defaults__,closure=native.run_oneshot.__closure__)
    official.__kwdefaults__=native.run_oneshot.__kwdefaults__
    return official(*args,**kwargs)
