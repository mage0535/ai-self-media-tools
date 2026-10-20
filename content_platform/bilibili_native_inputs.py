"""Bili normal data inputs: original native account reads and complete source-media observation.
No public publisher, login, cross-account credential, model fallback or retry.
Only a current signed normal control may call effectful functions.
"""
from pathlib import Path
from datetime import datetime,timezone
from contextlib import contextmanager
import asyncio,base64,collections,copy,fcntl,hashlib,inspect,json,math,os,re,sqlite3,stat,subprocess,sys,time,types,urllib.request,urllib.parse,urllib.error
from urllib.parse import urlsplit,parse_qs
PROJECT=Path('/srv/ai-self-media-tools')
LEGACY='bilibili_44cdba01468a44d4a925f445bc3cba3a'
METRICS=('followers','following','posts','views','likes','comments','shares','saves','ctr','completion','watchtime','conversion','revenue')
ORIGINAL_READER_SHA='648b2e7f15b78ea938e3eaf8104c5ed827afe0252cbea1d7b74c0e5b2afc7df4'
ORIGINAL_CAPTURE_SHA='a49595bc04be93234851f63e1725b757c2d89e367f8205b18f3e952bd204d0fe'
POINTER='normal_bilibili_owned_account_report_ref'
class BiliInputsBlocked(ValueError):pass
class BiliSourceExcluded(BiliInputsBlocked):pass
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def private(path,limit=32*1024*1024):
 p=Path(path);s=p.lstat()
 if(not p.is_absolute()or any(x.is_symlink()for x in(p,*p.parents))or not stat.S_ISREG(s.st_mode)or s.st_uid!=0 or s.st_nlink!=1 or s.st_mode&0o077 or s.st_size<=0 or(limit is not None and s.st_size>limit)):raise BiliInputsBlocked('bili_original_private_file_required')
 raw=p.read_bytes();t=p.stat()
 if(s.st_dev,s.st_ino,s.st_mtime_ns,s.st_size)!=(t.st_dev,t.st_ino,t.st_mtime_ns,t.st_size):raise BiliInputsBlocked('bili_original_changed_during_read')
 return raw
def reference(path,limit=None):
 raw=private(path,limit);return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}
def read_ref(ref):
 raw=private(ref['path'],None)
 if sha(raw)!=ref['sha256']or('bytes'in ref and len(raw)!=ref['bytes']):raise BiliInputsBlocked('bili_original_reference_changed')
 return raw
def once(path,value,*,raw=False):
 path=Path(path);body=value if raw else canonical(value);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb')as f:f.write(body);f.flush();os.fsync(f.fileno())
 return {'path':str(path),'sha256':sha(body),'bytes':len(body)}
def fingerprint(path):
 p=Path(path);s=p.lstat()
 if(not p.is_absolute()or any(x.is_symlink()for x in(p,*p.parents))or not stat.S_ISREG(s.st_mode)or s.st_uid!=0 or s.st_nlink!=1 or s.st_mode&0o022):raise BiliInputsBlocked('bili_original_managed_source_required')
 raw=p.read_bytes();t=p.stat()
 if(s.st_dev,s.st_ino,s.st_mtime_ns,s.st_size)!=(t.st_dev,t.st_ino,t.st_mtime_ns,t.st_size):raise BiliInputsBlocked('bili_original_changed_during_read')
 return {'path':str(p),'sha256':sha(raw),'bytes':len(raw),'mtime_ns':s.st_mtime_ns,'inode':s.st_ino,'device':s.st_dev}
def current_guard(store,control):
 from .task_source_inputs import _normal_cycle_source_guard
 guard=_normal_cycle_source_guard(store,control_id=control)
 if LEGACY not in guard['payload']['accounts']:raise BiliInputsBlocked('bili_original_registered_account_not_in_scope')
 return guard


def validate_originals(result,nav_raw,card_raw,headers):
 if result.get('state')!='observation_returned' or result.get('before_after_equal')is not True:raise ValueError('successful_original_capture_required')
 nav=json.loads(nav_raw);card=json.loads(card_raw);n=nav.get('data')or{};data=card.get('data')or{};profile=data.get('card')or{}
 mid=str(n.get('mid')or'')
 if nav.get('code')!=0 or card.get('code')!=0 or n.get('isLogin')is not True or not mid.isdigit()or mid.startswith('0')or str(profile.get('mid'))!=mid:raise ValueError('same_authenticated_native_mid_required')
 if len(headers)!=2:raise ValueError('two_original_headers_required')
 expected_paths=('/x/web-interface/nav','/x/web-interface/card')
 for index,(header,raw)in enumerate(zip(headers,(nav_raw,card_raw))):
  parsed=urlsplit(header['url']);stamp=datetime.fromisoformat(header['observed_at'].replace('Z','+00:00'))
  if(header.get('http_status')!=200 or header.get('response_complete')is not True or header.get('method')!='GET'
     or parsed.scheme!='https' or parsed.hostname!='api.bilibili.com' or parsed.port not in(None,443)
     or parsed.username is not None or parsed.password is not None or parsed.path!=expected_paths[index]
     or header.get('actual_url')!=header['url']or header['raw_ref'].get('sha256')!=sha(raw)
     or header['raw_ref'].get('bytes')!=len(raw)or stamp.tzinfo is None):raise ValueError('original_native_HTTP_raw_or_time_changed')
 if parse_qs(urlsplit(headers[1]['url']).query)!= {'mid':[mid]}:raise ValueError('original_card_query_account_changed')
 metrics={k:None for k in METRICS};fields={'followers':('data.card.fans',profile.get('fans')),'following':('data.card.attention',profile.get('attention')),'posts':('data.archive_count',data.get('archive_count')),'likes':('data.like_num',data.get('like_num'))}
 for key,(field,value)in fields.items():
  if type(value)is not int or value<0:raise ValueError('native_nonnegative_integer_required:'+field)
  metrics[key]=value
 actual=result.get('native_original_interpretation')or{}
 if actual.get('native_account_id')!=mid or actual.get('metrics')!=metrics or actual.get('registered_object_identity_verified')is not False:raise ValueError('captured_native_interpretation_changed')
 if result.get('raw_responses')!=headers or result.get('intent',{}).get('original_registry_object')!=LEGACY:raise ValueError('original_capture_intent_or_headers_changed')
 return {'schema':'owned_account_native_snapshot_v1','platform':'bilibili','account_id':mid,'native_account_id':mid,
   'account_handle':mid,'account_handle_kind':'native_mid_as_stable_local_locator','display_name':str(profile.get('name')or n.get('uname')or mid),
   'sample_count':1,'metric_scope':'account_snapshot','source_metric_scope':'current_lifetime_account_snapshot',
   'metrics':metrics,'metric_source_fields':{k:v[0]for k,v in fields.items()},'missing_metrics':[k for k,v in metrics.items()if v is None],
   'observed_at':headers[1]['observed_at'],'observation_started_at':headers[0]['observed_at'],'metric_window':None,
   'growth_conclusion':'not_available_from_single_capture','strategy_eligible':False,'publication_identity_created':False,
   'registered_object_identity_verified':False,'legacy_registered_object':LEGACY,'legacy_crosswalk_status':'unknown_direct_locator_not_proven',
   'identity_source':'original_normal_collector_cookie_authenticated_nav_and_same_mid_card','raw_refs':[h['raw_ref']for h in headers]}

def number(value):
 if isinstance(value,int)and not isinstance(value,bool)and value>=0:return value
 if isinstance(value,str)and re.fullmatch(r'\d+',value):return int(value)
 return None

def interpret_originals(platform,rows):
 out={'status':'unavailable','native_account_id':None,'metrics':{k:None for k in METRICS},'strategy_eligible':False,
      'registered_object_identity_verified':False,'metric_scope':'current_lifetime_account_snapshot','missing_is_zero':False}
 try:
  if platform=='bilibili':
   nav=[r for r in rows if urllib.parse.urlsplit(r['url']).path=='/x/web-interface/nav'];cards=[r for r in rows if urllib.parse.urlsplit(r['url']).path=='/x/web-interface/card']
   if len(nav)!=1 or len(cards)!=1:return out
   a=json.loads(nav[0]['raw'].decode('utf-8'));b=json.loads(cards[0]['raw'].decode('utf-8'));data=a.get('data')or{};v=b.get('data')or{};card=v.get('card')or{}
   identity=str(data.get('mid')or'')
   if a.get('code')!=0 or b.get('code')!=0 or data.get('isLogin')is not True or not re.fullmatch('[1-9][0-9]*',identity)or str(card.get('mid')or'')!=identity:return out
   out.update(status='observed_native_account',native_account_id=identity,identity_provenance='original_authenticated_nav_and_same_mid_card')
   out['metrics'].update(followers=number(card.get('fans')),following=number(card.get('attention')),posts=number(v.get('archive_count')if 'archive_count'in v else card.get('videos')),likes=number(v.get('like_num')if 'like_num'in v else card.get('likes')))
  elif platform=='youtube':
   if len(rows)!=1:return out
   text=rows[0]['raw'].decode('utf-8');matches=[]
   for marker in ('var ytInitialData =','window["ytInitialData"] =','ytInitialData ='):
    start=text.find(marker)
    if start>=0:
     raw=text[start+len(marker):].lstrip()
     try:body,_=json.JSONDecoder().raw_decode(raw)
     except ValueError:continue
     renderer=(body.get('metadata')or{}).get('channelMetadataRenderer')or{};identity=renderer.get('externalId')
     if isinstance(identity,str)and re.fullmatch(r'UC[A-Za-z0-9_-]{22}',identity):matches.append(identity)
   if len(set(matches))!=1:return out
   out.update(status='observed_native_public_profile',native_account_id=matches[0],identity_provenance='original_primary_ytInitialData_channelMetadataRenderer',public_profile_is_not_authenticated_ownership=True)
 except (ValueError,TypeError,KeyError,UnicodeError):return out
 out['missing_metrics']=[k for k,v in out['metrics'].items()if v is None]
 return out

def https_origin(url):
 parsed=urllib.parse.urlsplit(url)
 if (parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None
     or parsed.port not in (None,443)):
  raise ValueError('native_read_https_443_origin_required')
 return ('https',parsed.hostname,443)

def require_same_origin(original,actual):
 if https_origin(original)!=https_origin(actual):raise ValueError('native_read_redirect_origin_changed')

class SameHostRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  try:require_same_origin(req.full_url,newurl)
  except ValueError:raise urllib.error.HTTPError(req.full_url,code,'native_read_redirect_origin_changed',headers,fp)from None
  return super().redirect_request(req,fp,code,msg,headers,newurl)

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  raise urllib.error.HTTPError(req.full_url,code,'bili_original_redirect_not_a_second_account_read',headers,fp)


def read_owned_report(ref,expected_mid,proof_ref,*,now=None):
    """Integrity precedes TTL: an expired corrupt original cannot be washed by a new read."""
    report=json.loads(read_ref(ref));capture=json.loads(read_ref(report['capture_result_ref']));headers=capture['raw_responses']
    if len(headers)!=2:raise BiliInputsBlocked('bili_original_nav_card_pair_required')
    nav=read_ref(headers[0]['raw_ref']);card=read_ref(headers[1]['raw_ref']);original=validate_originals(capture,nav,card,headers)
    if(original['native_account_id']!=expected_mid or report.get('native_account_id')!=expected_mid or report.get('registered_account_id')!=LEGACY
            or report.get('registered_identity_proof_ref')!=proof_ref or report.get('metrics')!=original['metrics']
            or report.get('raw_refs')!=original['raw_refs']or report.get('observed_at')!=original['observed_at']):
        raise BiliInputsBlocked('bili_original_owned_identity_or_values_changed')
    clock=time.time()if now is None else now
    ages=[clock-datetime.fromisoformat(row['observed_at'].replace('Z','+00:00')).timestamp()for row in headers]
    if any(age<0 for age in ages):raise BiliInputsBlocked('bili_original_observation_in_future')
    return report,max(ages)<=900


def _latest_original_report(store,expected_mid,proof_ref):
    connection=sqlite3.connect(store.path.as_uri()+'?mode=ro',uri=True);connection.row_factory=sqlite3.Row;connection.execute('PRAGMA query_only=ON')
    try:
        rows=connection.execute("SELECT job_id,payload_json FROM account_snapshots WHERE platform='bilibili' ORDER BY id DESC").fetchall()
        for row in rows:
            payload=json.loads(row['payload_json'])
            if(payload.get('schema')!='owned_account_native_snapshot_v1'or payload.get('native_account_id')!=expected_mid
                    or payload.get('registered_account_id')!=LEGACY or payload.get('registered_identity_proof_ref')!=proof_ref):continue
            artifacts=connection.execute("SELECT path,checksum FROM artifacts WHERE job_id=? AND kind='owned_account_report_json'",(row['job_id'],)).fetchall()
            matching=[{'path':a['path'],'sha256':a['checksum']}for a in artifacts if json.loads(private(a['path']))==payload and sha(private(a['path']))==a['checksum']]
            if len(matching)!=1:raise BiliInputsBlocked('bili_original_account_report_missing_or_ambiguous')
            return matching[0]
    finally:connection.close()
    return None


def _capture_original_owned(config,binding,directory,deadline):
    from . import performance_collectors as collector
    source=Path(collector.__file__);config_path=PROJECT/'secrets/performance-collector.json';cookie=Path(config['cookie_file'])
    if cookie!=PROJECT/'external/social-auto-upload/cookies/bilibili_main.json':raise BiliInputsBlocked('bili_original_alias_cookie_locator_required')
    private(config_path);private(cookie)
    before=[fingerprint(path)for path in(config_path,source,cookie)];observed=[]
    end=min(float(deadline),time.time()+60)
    if end-time.time()<40:raise BiliInputsBlocked('bili_original_two_GET_budget_insufficient')
    def capture(url,timeout=15,headers=None):
        if len(observed)>=2 or time.time()>=end:raise BiliInputsBlocked('bili_original_two_GET_deadline_or_count')
        parsed=urlsplit(url);https_origin(url)
        if parsed.hostname!='api.bilibili.com'or parsed.path not in('/x/web-interface/nav','/x/web-interface/card'):raise BiliInputsBlocked('bili_original_native_endpoint_required')
        request_headers={'User-Agent':'Mozilla/5.0 (compatible; ContentPlatformMetrics/1.0)'};request_headers.update(headers or{})
        request=urllib.request.Request(url,headers=request_headers,method='GET');error=None
        try:response=urllib.request.build_opener(NoRedirect()).open(request,timeout=min(float(timeout),max(0.01,end-time.time())))
        except urllib.error.HTTPError as e:response=e;error=e
        with response:
            raw=response.read(16*1024*1024+1);status=response.code;actual=response.geturl();safe_headers={k:response.headers[k]for k in('Content-Type','Content-Length','Retry-After')if k in response.headers}
        label='response-'+str(len(observed)+1).zfill(2);ref=once(directory/(label+'.raw'),raw,raw=True)
        record={'url':url,'actual_url':actual,'method':'GET','http_status':status,'content_type':safe_headers.get('Content-Type',''),'headers':safe_headers,'observed_at':datetime.now(timezone.utc).isoformat(),'raw_ref':ref,'response_complete':len(raw)<=16*1024*1024}
        once(directory/(label+'.private.json'),record);observed.append({'url':url,'raw':raw,'record':record})
        require_same_origin(url,actual)
        if error is not None or status!=200 or not record['response_complete']:raise BiliInputsBlocked('bili_native_HTTP_failure_query_only')
        return raw.decode('utf-8',errors='replace')
    original=collector._bilibili(config,capture)
    after=[fingerprint(path['path'])for path in before]
    if after!=before:raise BiliInputsBlocked('bili_original_cookie_or_configuration_changed_during_read')
    interpretation=interpret_originals('bilibili',observed)
    result={'state':'observation_returned','original_native_result':original,'native_original_interpretation':interpretation,'raw_responses':[r['record']for r in observed],'before_after_equal':True,
        'intent':{'schema':'existing-owned-http-account-observation-v1','original_registry_object':LEGACY,'control_id':binding['control_id'],'before':before,'model_calls':0,'publication':False,'automatic_replay':False},'publication':False,'model_calls':0,'database_import':False,'automatic_replay':False}
    result_ref=once(directory/'capture-result.private.json',result)
    if len(observed)!=2:raise BiliInputsBlocked('bili_current_authenticated_nav_and_card_required')
    snapshot=validate_originals(result,observed[0]['raw'],observed[1]['raw'],result['raw_responses'])
    if snapshot['native_account_id']!=binding['account_id']:raise BiliInputsBlocked('bili_current_native_MID_changed')
    snapshot.update(registered_object_identity_verified=True,registered_account_id=LEGACY,internal_account_alias=binding['internal_account_alias'],registered_identity_proof_ref=binding['registered_identity_proof_ref'],capture_result_ref=result_ref)
    return snapshot


def _persist_owned_and_pointer(store,binding,original_row,snapshot,directory,control):
    """One original Store transaction; only the existing binding observation pointer may change."""
    connection=sqlite3.connect(store.path,timeout=15);connection.row_factory=sqlite3.Row;connection.execute('PRAGMA foreign_keys=ON');connection.execute('BEGIN IMMEDIATE');old=store.connect
    @contextmanager
    def same():yield connection
    store.connect=same
    try:
        current=connection.execute('SELECT * FROM platform_accounts WHERE id=?',(binding['binding_id'],)).fetchone()
        if current is None or dict(current)!=original_row:raise BiliInputsBlocked('bili_original_binding_CAS_changed')
        fingerprint_value='normal-bili-owned:'+control+':'+snapshot['capture_result_ref']['sha256']
        if connection.execute('SELECT 1 FROM jobs WHERE topic_fingerprint=?',(fingerprint_value,)).fetchone():raise BiliInputsBlocked('bili_observation_already_imported_inspect_only')
        job=store.create_job('B站原生累计账号观察 '+snapshot['observed_at'],['bilibili'],{'source':'owned_account_native_snapshot','analytics_only':True,'account_id':binding['account_id'],'registered_account_id':LEGACY,'strategy_eligible':False,'publication_authorized':False},topic_fingerprint=fingerprint_value)
        store.save_account_snapshots(job['id'],[snapshot]);saved=store.account_snapshots(job['id'])
        if len(saved)!=1 or saved[0]['payload']!=snapshot:raise BiliInputsBlocked('bili_current_account_native_readback_changed')
        report=once(directory/'account-report.private.json',snapshot)
        text='# B站原生累计账号观察\n\n原生MID：'+binding['account_id']+'\n观测时间：'+snapshot['observed_at']+'\n\n'+json.dumps(snapshot['metrics'],ensure_ascii=False,sort_keys=True)+'\n\n仅为账号累计快照；缺项保持未知，不作为外部爆款、成熟窗口或发布完成。'
        md=once(directory/'account-report.private.md',text.encode(),raw=True)
        for kind,ref in(('owned_account_report_json',report),('owned_account_report_md',md)):store.add_artifact(job['id'],kind,ref['path'],ref['sha256'])
        config=json.loads(original_row['config_json']);config[POINTER]=report
        changed=connection.execute('UPDATE platform_accounts SET config_json=? WHERE id=? AND config_json=?',(json.dumps(config,ensure_ascii=False,sort_keys=True),binding['binding_id'],original_row['config_json'])).rowcount
        if changed!=1:raise BiliInputsBlocked('bili_pointer_CAS_failed')
        now=dict(connection.execute('SELECT * FROM platform_accounts WHERE id=?',(binding['binding_id'],)).fetchone());expected=dict(original_row,config_json=json.dumps(config,ensure_ascii=False,sort_keys=True))
        if now!=expected:raise BiliInputsBlocked('bili_original_binding_fields_changed')
        store.transition(job['id'],{'created'},'completed','owned_account_snapshot_recorded',{'analytics_only':True,'publication':False,'control_id':control})
        connection.commit();return report
    except BaseException:connection.rollback();raise
    finally:store.connect=old;connection.close()


def ensure_current_bilibili_owned(store,binding,*,control_task_id,deadline_unix):
    guard=current_guard(store,control_task_id)
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0'or time.time()>=float(deadline_unix)or float(deadline_unix)>guard['deadline_unix']+0.02:raise BiliInputsBlocked('bili_original_NoPub_scope_deadline_required')
    lock_dir=store.path.parent/'intel/owned-account-refresh';lock_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    if any(p.is_symlink()for p in(lock_dir,*lock_dir.parents)):raise BiliInputsBlocked('bili_owned_refresh_symlink')
    lock_path=lock_dir/('bilibili-'+binding['account_id']+'.lock');fd=os.open(lock_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+b')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        connection=sqlite3.connect(store.path.as_uri()+'?mode=ro',uri=True);connection.row_factory=sqlite3.Row;connection.execute('PRAGMA query_only=ON')
        try:row=connection.execute('SELECT * FROM platform_accounts WHERE id=?',(binding['binding_id'],)).fetchone();original=dict(row)if row else None
        finally:connection.close()
        if not original:raise BiliInputsBlocked('bili_original_binding_missing')
        directory=lock_dir/('bilibili-'+binding['account_id']+'-'+control_task_id)
        if directory.exists():
            done=directory/'completed.private.json'
            if not done.exists()or(directory/'failed_or_unknown.private.json').exists():raise BiliInputsBlocked('bili_original_control_attempt_exists_inspect_only')
            receipt=json.loads(private(done))
            if receipt.get('control_id')!=control_task_id:raise BiliInputsBlocked('bili_original_receipt_control_changed')
            _,fresh=read_owned_report(receipt['report_ref'],binding['account_id'],binding['registered_identity_proof_ref'])
            if not fresh:raise BiliInputsBlocked('bili_original_current_control_observation_expired_no_replay')
            if time.time()>=float(deadline_unix):raise BiliInputsBlocked('bili_original_deadline_after_cached_read')
            return receipt['report_ref']
        config=json.loads(original['config_json']);ref=config.get(POINTER)or _latest_original_report(store,binding['account_id'],binding['registered_identity_proof_ref'])
        if ref:
            _,fresh=read_owned_report(ref,binding['account_id'],binding['registered_identity_proof_ref'])
            if fresh:return ref
        directory.mkdir(mode=0o700)
        once(directory/'started.private.json',{'control_id':control_task_id,'original_report_ref':ref,'binding_id':binding['binding_id'],'native_account_id':binding['account_id'],'deadline_unix':deadline_unix,'publication':False,'automatic_replay':False})
        try:
            performance=json.loads(private(PROJECT/'secrets/performance-collector.json'));account=performance.get('bilibili')or{}
            snapshot=_capture_original_owned(account,dict(binding,control_id=control_task_id),directory,deadline_unix)
            current_guard(store,control_task_id)
            if time.time()>=float(deadline_unix):raise BiliInputsBlocked('bili_original_deadline_after_observation')
            report=_persist_owned_and_pointer(store,binding,original,snapshot,directory,control_task_id)
            once(directory/'completed.private.json',{'control_id':control_task_id,'report_ref':report,'publication':False,'model_calls':0});return report
        except BaseException as error:
            once(directory/'failed_or_unknown.private.json',{'control_id':control_task_id,'error_type':type(error).__name__,'error_sha256':sha(str(error).encode()),'automatic_replay':False,'publication':False});raise


def no_vision_recovery(original):
    """Fresh source-observation child only; an upstream error never starts another request."""
    def guarded(first_err,**kwargs):
        if kwargs.get('task')=='vision':raise first_err
        yield from original(first_err,**kwargs)
    return guarded


def _strict_json(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise BiliInputsBlocked('bili_source_duplicate_json_key')
            out[key]=value
        return out
    return json.loads(text,object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in()).throw(BiliInputsBlocked('bili_source_nonfinite_json')))


def decode_observation_response(text,identities):
    value=_strict_json(text)
    if(not isinstance(value,dict)or set(value)!={'items'}or not isinstance(value['items'],list)
            or [row.get('opaque_id')for row in value['items']if isinstance(row,dict)]!=identities):
        raise BiliInputsBlocked('bili_source_all_complete_inputs_required_in_original_order')
    return value['items']


def _adts_payload_records(data):
    if not isinstance(data,bytes)or not data:raise BiliInputsBlocked('bili_source_complete_ADTS_required')
    records=[];offset=0
    while offset<len(data):
        header=data[offset:offset+7]
        if(len(header)!=7 or header[0]!=255 or header[1]&246!=240 or header[6]&3):raise BiliInputsBlocked('bili_source_ADTS_header_or_outer_metadata_changed')
        header_bytes=7 if header[1]&1 else 9;length=((header[3]&3)<<11)|(header[4]<<3)|(header[5]>>5)
        if length<=header_bytes or offset+length>len(data):raise BiliInputsBlocked('bili_source_ADTS_complete_frame_required')
        payload=data[offset+header_bytes:offset+length];records.append({'bytes':len(payload),'sha256':sha(payload)});offset+=length
    return records


def _aac_packet_records(probe):
    packets=probe.get('packets');records=[]
    if not isinstance(packets,list)or not packets:raise BiliInputsBlocked('bili_source_original_AAC_packets_required')
    for packet in packets:
        digest=re.fullmatch(r'SHA256:([0-9a-fA-F]{64})',str(packet.get('data_hash','')));size=int(packet.get('size',0))
        if digest is None or size<=0:raise BiliInputsBlocked('bili_source_original_AAC_packet_unknown')
        records.append({'bytes':size,'sha256':digest[1].lower()})
    return records


def _verify_original_audio_transport(material):
    if not material.get('transport_audio_ref')and not material.get('transport_audio_proof_ref'):
        return None
    proof=_strict_json(read_ref(material['transport_audio_proof_ref']).decode('utf8'))
    if(proof.get('version')!='bilibili_original_AAC_stream_copy_transport_v1'or material.get('audio_format')!='aac'
            or proof.get('original_video_ref')!=material['video_ref']or proof.get('original_WAV_ref')!=material['audio_ref']
            or proof.get('transport_audio_ref')!=material['transport_audio_ref']or proof.get('current_native_scope_ref')!=material['native_scope_ref']):raise BiliInputsBlocked('bili_source_original_AAC_transport_binding_changed')
    for pin in(proof['original_video_ref'],proof['original_WAV_ref'],proof['transport_audio_ref']):read_ref(pin)
    if fingerprint(proof['producer_source_ref']['path'])!=proof['producer_source_ref']:raise BiliInputsBlocked('bili_source_AAC_transport_current_producer_changed')
    packets=_aac_packet_records(_strict_json(read_ref(proof['original_packets_ref']).decode('utf8')))
    actual_wire=read_ref(proof['transport_audio_ref'])
    if 'audio_wire'in material:
        try:submitted=base64.b64decode(material['audio_wire'],validate=True)
        except (ValueError,TypeError)as error:raise BiliInputsBlocked('bili_source_AAC_actual_wire_changed')from error
        if submitted!=actual_wire:raise BiliInputsBlocked('bili_source_AAC_actual_wire_changed')
    if _adts_payload_records(actual_wire)!=packets:raise BiliInputsBlocked('bili_source_AAC_original_payload_sequence_changed')
    from .current_audio_review_runtime import _blind_wave
    original,_=_blind_wave(read_ref(material['audio_ref']));frames=_strict_json(read_ref(proof['decoded_frames_ref']).decode('utf8')).get('frames')
    if not isinstance(frames,list)or not frames or any(type(x.get('nb_samples'))is not int or x['nb_samples']<=0 for x in frames):raise BiliInputsBlocked('bili_source_AAC_complete_decoded_frames_required')
    count=sum(x['nb_samples']for x in frames);digest=read_ref(proof['decoded_PCM_hash_ref']).decode('ascii').strip()
    source_probe=_strict_json(read_ref(proof['original_stream_probe_ref']).decode('utf8'));original_tracks=[x for x in source_probe.get('streams')or[]if x.get('codec_type')=='audio']
    if(len(original_tracks)!=1 or original_tracks[0].get('codec_name')!='aac'or int(original_tracks[0].get('sample_rate',0))!=material['sample_rate']
            or original_tracks[0].get('channels')!=material['channels']):raise BiliInputsBlocked('bili_source_AAC_original_stream_metadata_changed')
    probe=_strict_json(read_ref(proof['transport_probe_ref']).decode('utf8'));tracks=[x for x in probe.get('streams')or[]if x.get('codec_type')=='audio']
    if(len(tracks)!=1 or tracks[0].get('codec_name')!='aac'or int(tracks[0].get('sample_rate',0))!=material['sample_rate']
            or tracks[0].get('channels')!=material['channels']or count!=material['frames']or digest!='SHA256='+material['pcm_sha256']
            or original['pcm_sha256']!=material['pcm_sha256']or original['frames']!=count
            or original['rate']!=material['sample_rate']or original['channels']!=material['channels']):raise BiliInputsBlocked('bili_source_AAC_full_PCM_samples_changed')
    return {'pcm_sha256':original['pcm_sha256'],'frames':count,'sample_rate':original['rate'],'channels':original['channels']}



MEDIA_TRANSPORT_RUNTIME=Path('/etc/hermes/channel-cycle-runtime.json')

def _audio_transport_declaration(pointer,route,canonical_provider):
    result={'use_original_aac':False,'reason':'no_adapter_declaration','adapter_ref':None,'adapter_source_ref':None}
    if pointer is None:return result
    def checked_ref(value):
        if (not isinstance(value,dict)or not {'path','sha256'}<=set(value)or set(value)-{'path','sha256','bytes'}
                or not isinstance(value.get('path'),str)or not isinstance(value.get('sha256'),str)
                or re.fullmatch('[0-9a-f]{64}',value['sha256'])is None
                or('bytes'in value and(type(value['bytes'])is not int or value['bytes']<=0))):raise BiliInputsBlocked('bili_audio_adapter_reference_invalid')
        return read_ref(value)
    raw=checked_ref(pointer);doc=_strict_json(raw.decode('utf8'))
    required={'version','requested_provider','canonical_provider','api_mode','logical_endpoint_sha256','adapter_source_ref','accepted_formats'}
    if (not isinstance(doc,dict)or not required<=set(doc)or set(doc)-required-{'transport_proxy'}
            or doc.get('version')!='hermes-media-transport-adapter-v1'
            or any(not isinstance(doc.get(k),str)or not doc[k].strip()or doc[k]!=doc[k].strip()for k in('requested_provider','canonical_provider','api_mode'))
            or not isinstance(doc.get('logical_endpoint_sha256'),str)or re.fullmatch('[0-9a-f]{64}',doc['logical_endpoint_sha256'])is None):raise BiliInputsBlocked('bili_audio_adapter_declaration_invalid')
    formats=doc['accepted_formats']
    if (not isinstance(formats,list)or not formats or any(not isinstance(x,str)or re.fullmatch('[a-z0-9][a-z0-9_+.-]*',x)is None for x in formats)
            or len(set(formats))!=len(formats)):raise BiliInputsBlocked('bili_audio_adapter_formats_invalid')
    checked_ref(doc['adapter_source_ref'])
    proxy=doc.get('transport_proxy')
    if proxy is not None:
        if not isinstance(proxy,dict)or set(proxy)!={'url','upstream_url','allowed_methods','allowed_paths'}:raise BiliInputsBlocked('bili_audio_adapter_proxy_invalid')
        if proxy['allowed_methods']!=['POST']or proxy['allowed_paths']!=['/v1/chat/completions']:raise BiliInputsBlocked('bili_audio_adapter_proxy_invalid')
        for field in('url','upstream_url'):
            if not isinstance(proxy[field],str):raise BiliInputsBlocked('bili_audio_adapter_proxy_invalid')
            parsed=urlsplit(proxy[field])
            try:port=parsed.port
            except ValueError as error:raise BiliInputsBlocked('bili_audio_adapter_proxy_invalid')from error
            if (parsed.scheme!='http'or parsed.hostname not in{'127.0.0.1','::1'}or port is None or not 0<port<65536
                    or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in('','/v1')):raise BiliInputsBlocked('bili_audio_adapter_proxy_invalid')
    endpoint=route.get('endpoint')
    applies=(doc['requested_provider']==route.get('provider')and doc['canonical_provider']==canonical_provider
        and doc['api_mode']==route.get('api_mode')and isinstance(endpoint,str)and bool(endpoint)
        and doc['logical_endpoint_sha256']==sha(endpoint.rstrip('/').encode()))
    result.update(adapter_ref=dict(pointer),adapter_source_ref=dict(doc['adapter_source_ref']),reason='adapter_not_applicable')
    if applies:result.update(use_original_aac='aac'in formats,reason='AAC_accepted'if'aac'in formats else'AAC_not_accepted')
    return result

def _audio_transport_adapter_choice(route,canonical_provider):
    runtime_ref=reference(MEDIA_TRANSPORT_RUNTIME);runtime=_strict_json(read_ref(runtime_ref).decode('utf8'))
    if not isinstance(runtime,dict):raise BiliInputsBlocked('bili_audio_adapter_runtime_invalid')
    decision=_audio_transport_declaration(runtime.get('media_transport_adapter_ref'),route,canonical_provider)
    return dict(decision,version='bili_current_audio_transport_choice_v1',runtime_ref=runtime_ref,
        current_role_route={k:route.get(k)for k in('provider','model','api_mode','endpoint')},canonical_provider=canonical_provider)

def _verify_audio_transport_choice(choice,route,canonical_provider,*,current=False):
    if not isinstance(choice,dict):raise BiliInputsBlocked('bili_audio_adapter_current_choice_required')
    if current:expected=_audio_transport_adapter_choice(route,canonical_provider)
    else:
        runtime_ref=choice.get('runtime_ref')or{}
        if (runtime_ref.get('path')!=str(MEDIA_TRANSPORT_RUNTIME)or not isinstance(runtime_ref.get('sha256'),str)
                or re.fullmatch('[0-9a-f]{64}',runtime_ref['sha256'])is None):raise BiliInputsBlocked('bili_audio_adapter_runtime_reference_invalid')
        decision=_audio_transport_declaration(choice.get('adapter_ref'),route,canonical_provider)
        expected=dict(decision,version='bili_current_audio_transport_choice_v1',runtime_ref=runtime_ref,
            current_role_route={k:route.get(k)for k in('provider','model','api_mode','endpoint')},canonical_provider=canonical_provider)
    if choice!=expected:raise BiliInputsBlocked('bili_audio_adapter_choice_or_current_route_changed')
    return expected

VIDEO_TRANSPORT_MIN_BYTES=8*1024*1024
VIDEO_TRANSPORT_TARGET_BYTES=5*1024*1024


def _prepare_video_transport(material,directory,deadline):
    # B05 2026-10-19: the OLD<->NEW model tunnel moves ~0.5-1.4 MB/s, so three original videos (~93 MB, ~124 MB as
    # base64) cannot reach the model inside the 180 s group budget. Send a full-duration, full-audio, low-bitrate copy;
    # the original file stays the evidence and the proof binds both.
    directory=Path(directory);source=Path(material['video_ref']['path']);read_ref(material['video_ref'])
    if material['video_ref']['bytes']<VIDEO_TRANSPORT_MIN_BYTES:return material
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    duration=float(material.get('video_duration_seconds',material['duration_seconds']))
    if duration<=0:raise BiliInputsBlocked('bili_source_video_duration_unknown')
    video_kbps=int(max(80,min(800,VIDEO_TRANSPORT_TARGET_BYTES*8/1000/duration-32)))
    target=directory/'full-duration-transport.mp4'
    argv=['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(source),'-map','0:v:0','-map','0:a:0?',
          '-vf','scale=w=854:h=854:force_original_aspect_ratio=decrease:force_divisible_by=2','-r','5',
          '-c:v','libx264','-preset','veryfast','-b:v',str(video_kbps)+'k','-maxrate',str(video_kbps*2)+'k','-bufsize',str(video_kbps*4)+'k',
          '-c:a','aac','-b:a','32k','-ac','1','-movflags','+faststart','-map_metadata','-1','-f','mp4',str(target)]
    result=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=_remaining(deadline,240),check=False)
    stderr=once(directory/'video-transport.stderr.private.bin',result.stderr,raw=True)
    if result.returncode:raise BiliInputsBlocked('bili_source_video_transport_encode_failed')
    os.chmod(target,0o600)
    probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(target)],stdin=subprocess.DEVNULL,
        capture_output=True,timeout=60,check=False)
    derived=float(_strict_json(probe.stdout.decode('utf8'))['format']['duration'])if probe.returncode==0 else -1
    if abs(derived-duration)>0.5:raise BiliInputsBlocked('bili_source_video_transport_duration_changed')
    transport_ref=reference(target);read_ref(material['video_ref'])
    proof={'version':'bilibili_full_duration_video_transport_v1','original_video_ref':material['video_ref'],'transport_video_ref':transport_ref,
        'current_native_scope_ref':material['native_scope_ref'],'producer_source_ref':fingerprint(Path(__file__)),'argv':argv,'stderr_ref':stderr,
        'original_duration_seconds':duration,'transport_duration_seconds':derived,'video_kbps':video_kbps}
    material=dict(material,transport_video_ref=transport_ref,transport_video_proof_ref=once(directory/'video-transport-proof.private.json',proof))
    return material


def _verify_video_transport(material):
    if not material.get('transport_video_ref')and not material.get('transport_video_proof_ref'):return None
    proof=_strict_json(read_ref(material['transport_video_proof_ref']).decode('utf8'))
    if(proof.get('version')!='bilibili_full_duration_video_transport_v1'or proof.get('original_video_ref')!=material['video_ref']
            or proof.get('transport_video_ref')!=material['transport_video_ref']or proof.get('current_native_scope_ref')!=material['native_scope_ref']
            or abs(proof['transport_duration_seconds']-proof['original_duration_seconds'])>0.5):raise BiliInputsBlocked('bili_source_video_transport_binding_changed')
    read_ref(proof['original_video_ref']);read_ref(proof['transport_video_ref'])
    return proof


def _prepare_original_audio_transport(material,directory,deadline):
    # Preserve original compressed AAC frames; the canonical WAV/PCM remains the acoustic evidence.
    directory=Path(directory);read_ref(material['video_ref']);read_ref(material['audio_ref'])
    def run(label,argv,output=None):
        result=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE if output is None else output,
            stderr=subprocess.PIPE,timeout=_remaining(deadline,60),check=False)
        stderr=once(directory/('AAC-'+label+'.stderr.private.bin'),result.stderr,raw=True)
        once(directory/('AAC-'+label+'.command.private.json'),{'argv':argv,'exit_code':result.returncode,'stderr_ref':stderr})
        if result.returncode:raise BiliInputsBlocked('bili_source_AAC_stream_copy_or_full_decode_failed')
        return result.stdout
    source=Path(material['video_ref']['path']);prefix=['ffprobe','-v','error','-protocol_whitelist','file,pipe']
    source_probe=_strict_json(run('source-probe',prefix+['-show_streams','-show_format','-of','json',str(source)]).decode('utf8'))
    tracks=[x for x in source_probe.get('streams')or[]if x.get('codec_type')=='audio']
    if len(tracks)!=1 or not isinstance(tracks[0].get('codec_name'),str)or tracks[0]['codec_name'].casefold()in{'','unknown','none','n/a'}:raise BiliInputsBlocked('bili_source_actual_audio_codec_unknown')
    if tracks[0]['codec_name']!='aac':return material
    if int(tracks[0].get('sample_rate',0))!=material['sample_rate']or tracks[0].get('channels')!=material['channels']:raise BiliInputsBlocked('bili_source_AAC_original_stream_metadata_changed')
    source_probe_ref=once(directory/'AAC-original-stream-probe.private.json',source_probe)
    packet_data=run('original-packets',prefix+['-select_streams','a:0','-show_packets','-show_data_hash','sha256','-show_entries','packet=size,data_hash','-of','json',str(source)])
    packet_ref=once(directory/'AAC-original-packets.private.json',packet_data,raw=True);packets=_aac_packet_records(_strict_json(packet_data.decode('utf8')))
    target=directory/'anonymous-original-full-track.aac';fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb')as output:
        run('stream-copy',['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(source),'-map','0:a:0','-map_metadata','-1','-c:a','copy','-threads','1','-f','adts','pipe:1'],output)
    transport_ref=reference(target);wire=read_ref(transport_ref)
    if _adts_payload_records(wire)!=packets:raise BiliInputsBlocked('bili_source_AAC_original_payload_sequence_changed')
    transport_probe=once(directory/'AAC-transport-stream-probe.private.json',run('transport-probe',prefix+['-show_streams','-show_format','-of','json',str(target)]),raw=True)
    frame_ref=once(directory/'AAC-full-decoded-frames.private.json',run('full-frame-probe',prefix+['-select_streams','a:0','-show_frames','-show_entries','frame=nb_samples','-of','json',str(target)]),raw=True)
    pcm_hash_ref=once(directory/'AAC-full-decoded-PCM-hash.private.txt',run('full-PCM-hash',['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(target),'-map','0:a:0','-c:a','pcm_s32le','-threads','1','-f','hash','-hash','sha256','-']),raw=True)
    read_ref(material['video_ref']);read_ref(material['audio_ref'])
    proof={'version':'bilibili_original_AAC_stream_copy_transport_v1','original_video_ref':material['video_ref'],'original_WAV_ref':material['audio_ref'],
        'transport_audio_ref':transport_ref,'current_native_scope_ref':material['native_scope_ref'],'producer_source_ref':fingerprint(Path(__file__)),'original_stream_probe_ref':source_probe_ref,
        'original_packets_ref':packet_ref,'transport_probe_ref':transport_probe,'decoded_frames_ref':frame_ref,'decoded_PCM_hash_ref':pcm_hash_ref,
        'duration_authority':'original_full_decoded_PCM_frames_not_ADTS_bitrate_estimate','metadata_policy':'whole_ADTS_frames_only_no_outer_tags_or_source_title'}
    proof_ref=once(directory/'AAC-full-original-transport-proof.private.json',proof)
    result=dict(material,transport_audio_ref=transport_ref,transport_audio_proof_ref=proof_ref,audio_wire=base64.b64encode(wire).decode('ascii'),audio_format='aac')
    _verify_original_audio_transport(result)
    return result


def complete_media_packets(materials,*,maximum_video_bytes):
    """Two ordered packets. The blind audio packet has no URL, title, transcript or filename."""
    if not materials or len({m['opaque_id']for m in materials})!=len(materials):raise BiliInputsBlocked('bili_source_unique_materials_required')
    video_prompt=('Observe the ENTIRE supplied videos independently. Return only {"items":[...]}, in input order. '
        'Each item has exactly opaque_id,watched_full_video,segments. Each segment has exactly '
        'start_seconds,end_seconds,visual,copy_or_script,motion_combination,transition_combination. '
        'Continuously cover each complete timeline, including still frames. Copy/script is only verbatim visible or heard words; '
        'never infer from metadata. For spoken clips this field is the complete verbatim narration, excluding extra UI labels; '
        'for unspoken clips it is the complete visible copy. Describe concrete scene changes, cursor/action movement and transitions. '
        'If any part was not observable say unknown and watched_full_video=false. These are research references, not licensed production assets. ')
    audio_prompt=('Listen independently to the ENTIRE anonymous audio parts, in input order. No tools or outside information. '
        'Return only {"items":[...]}. Each item has exactly opaque_id,heard_full_audio,language,segments. '
        'Each segment has exactly start_seconds,end_seconds,kind,text,pace,stress,naturalness,observations. '
        'Continuously cover zero through the stated full duration including silence. kind is speech,music,sound,or silence. '
        'text is verbatim audible speech, otherwise empty. Give concrete audible pauses, emphasis, pace, timbre and naturalness. '
        'Unheard/uncertain content must remain unknown; never infer speech from an identifier. ')
    video_order=[{'opaque_id':m['opaque_id'],'wire_sha256':m.get('transport_video_ref',m['video_ref'])['sha256'],'duration_seconds':m.get('video_duration_seconds',m['duration_seconds'])}for m in materials]
    audio_order=[{'opaque_id':m['opaque_id'],'wire_sha256':m.get('transport_audio_ref',m['audio_ref'])['sha256'],'duration_seconds':m['duration_seconds']}for m in materials]
    video=[{'type':'text','text':video_prompt+json.dumps(video_order,separators=(',',':'))}]
    audio=[{'type':'text','text':audio_prompt+json.dumps(audio_order,separators=(',',':'))}]
    for m in materials:
        video.append({'type':'video_url','video_url':{'url':m['video_wire']}})
        audio.append({'type':'input_audio','input_audio':{'data':m['audio_wire'],'format':m['audio_format']}})
    # The SDK cap is per video data URL. Use the same number as a conservative local whole-group bound.
    if any(len(m['video_wire'])>maximum_video_bytes for m in materials):raise BiliInputsBlocked('bili_source_original_single_video_cap_exceeded')

    return [{'role':'user','content':video}],[{'role':'user','content':audio}]


def _concrete(value):
    if(not isinstance(value,str)or not value.strip()or any(word in value.casefold()for word in
        ('unknown','inaudible','unobservable','cannot hear','cannot determine','未知','不确定','未听','听不清','无法观察'))):
        raise BiliInputsBlocked('bili_source_actual_full_observation_unknown')
    return value


def _timeline(segments,duration,fields):
    if not isinstance(segments,list)or not 0<len(segments)<=400:raise BiliInputsBlocked('bili_source_complete_timeline_required')
    cursor=0.0
    for segment in segments:
        if not isinstance(segment,dict)or set(segment)!=set(fields):raise BiliInputsBlocked('bili_source_exact_segment_schema_required')
        start,end=segment['start_seconds'],segment['end_seconds']
        if(any(type(v)not in(int,float)or not math.isfinite(v)for v in(start,end))
                or abs(start-cursor)>0.001 or not 0<=start<end<=duration+0.001):raise BiliInputsBlocked('bili_source_full_track_coverage_required')
        cursor=end
    if abs(cursor-duration)>0.001:raise BiliInputsBlocked('bili_source_complete_tail_required')


def validate_complete_observations(material,video,audio):
    if(not isinstance(video,dict)or set(video)!={'opaque_id','watched_full_video','segments'}or video['watched_full_video']is not True
            or not isinstance(audio,dict)or set(audio)!={'opaque_id','heard_full_audio','language','segments'}or audio['heard_full_audio']is not True
            or video['opaque_id']!=material['opaque_id']or audio['opaque_id']!=material['opaque_id']):raise BiliInputsBlocked('bili_source_complete_actual_video_and_audio_required')
    _concrete(audio['language']);duration=material['duration_seconds']
    _timeline(video['segments'],material.get('video_duration_seconds',duration),('start_seconds','end_seconds','visual','copy_or_script','motion_combination','transition_combination'))
    _timeline(audio['segments'],duration,('start_seconds','end_seconds','kind','text','pace','stress','naturalness','observations'))
    visible=[]
    for segment in video['segments']:
        for field in('visual','motion_combination','transition_combination'):_concrete(segment[field])
        if not isinstance(segment['copy_or_script'],str):raise BiliInputsBlocked('bili_source_verbatim_script_required')
        if segment['copy_or_script'].strip():visible.append(_concrete(segment['copy_or_script']))
    spoken=[];measures=[];samples=material['samples'];rate=material['sample_rate'];channels=material['channels']
    cursor=0
    for segment in audio['segments']:
        first=round(segment['start_seconds']*rate);last=round(segment['end_seconds']*rate)
        if first!=cursor or not first<last<=material['frames']:raise BiliInputsBlocked('bili_source_complete_acoustic_frame_coverage_required')
        values=samples[first*channels:last*channels];peak=max(abs(v)for v in values)
        if segment['kind']=='speech':
            for field in('text','pace','stress','naturalness','observations'):_concrete(segment[field])
            if not peak:raise BiliInputsBlocked('bili_source_speech_on_actual_digital_silence')
            spoken.append(segment['text'])
        elif segment['kind']in('music','sound'):
            if segment['text']!=''or not peak:raise BiliInputsBlocked('bili_source_non_speech_changed')
            for field in('pace','stress','naturalness','observations'):_concrete(segment[field])
        elif segment['kind']=='silence':
            if segment['text']!=''or peak:raise BiliInputsBlocked('bili_source_silence_changed')
        else:raise BiliInputsBlocked('bili_source_audio_kind_unknown')
        measures.append({'start_frame':first,'end_frame':last,'peak_sample':peak,'rms_sample':math.sqrt(sum(v*v for v in values)/len(values))});cursor=last
    if cursor!=material['frames']:raise BiliInputsBlocked('bili_source_incomplete_audio_tail')
    text=''.join(spoken);visible_text=''.join(visible)
    key=lambda value:''.join(c for c in value.casefold()if c.isalnum())
    # The independent complete-video observation may include captions; no caption is invented for a silent source.
    if not text.strip()and not visible_text.strip():raise BiliInputsBlocked('bili_source_actual_copy_or_script_unobservable')
    if text.strip()and visible_text.strip()and key(text)!=key(visible_text):raise BiliInputsBlocked('bili_source_independent_heard_and_visible_script_mismatch')
    return {'copy_or_script':text or visible_text,'visual_evidence':{'full_video':True,'segments':video['segments'],'source_video_ref':material['video_ref']},
        'voiceover':{'whole_track':True,'segments':audio['segments'],'source_audio_ref':material['audio_ref'],'acoustic_checks':measures,'audio_tokens':None},
        'motion_combination':{'observed_segments':[{'start_seconds':r['start_seconds'],'end_seconds':r['end_seconds'],'observation':r['motion_combination']}for r in video['segments']]},
        'transition_combination':{'observed_segments':[{'start_seconds':r['start_seconds'],'end_seconds':r['end_seconds'],'observation':r['transition_combination']}for r in video['segments']]},
        'research_grants_reuse_rights':False,'business_quality_passed':False}


def _remaining(deadline,maximum):
    remaining=min(float(maximum),float(deadline)-time.time())
    if remaining<=0:raise BiliInputsBlocked('bili_source_original_budget_elapsed')
    return remaining


def _single_native_video_binding(row,raw_refs,guard):
    """Only original current native video records can establish a one-page/CID identity."""
    bvid=row['content_id'];author=str(row['author_id']);url='https://www.bilibili.com/video/'+bvid
    if row.get('canonical_url')!=url:raise BiliInputsBlocked('bili_source_original_canonical_URL_changed')
    records=[]
    def walk(value):
        if isinstance(value,dict):
            yield value
            for child in value.values():yield from walk(child)
        elif isinstance(value,list):
            for child in value:yield from walk(child)
    for pin in raw_refs:
        path=Path(pin.get('path',''))
        if (not path.is_relative_to(guard['scope'])or not path.name.startswith('source-'+guard['control_id']+'.bilibili-response-')
                or not path.name.endswith('.private.json')):continue
        raw=read_ref(pin);doc=_strict_json(raw.decode('utf-8'))
        if not isinstance(doc,dict)or doc.get('code')!=0:continue
        for native in walk(doc.get('data')):
            if native.get('bvid')!=bvid:continue
            owner=(native.get('owner')or{}).get('mid')
            if owner is None:owner=native.get('mid')
            if owner is None or str(owner)!=author:continue
            pages=native.get('pages');count=native.get('videos');cid=native.get('cid');duration=native.get('duration')
            if isinstance(pages,list):
                if count is not None and count!=len(pages):raise BiliInputsBlocked('bili_source_native_page_count_conflict')
                count=len(pages)
                if count==1:
                    page=pages[0]
                    if not isinstance(page,dict)or page.get('page')!=1:raise BiliInputsBlocked('bili_source_native_single_page_identity_changed')
                    if cid is not None and cid!=page.get('cid'):raise BiliInputsBlocked('bili_source_native_CID_conflict')
                    cid=page.get('cid')
                    if duration is not None and page.get('duration')is not None and duration!=page['duration']:raise BiliInputsBlocked('bili_source_native_duration_conflict')
                    duration=page.get('duration',duration)
            if type(count)is int and count>1:return None
            if type(count)is not int or count!=1 or type(cid)is not int or cid<=0 or type(duration)is not int or duration<=0:continue
            records.append({'identity':{'bvid':bvid,'cid':cid,'author_id':author,'canonical_url':url,'page_count':1,'native_duration_seconds':duration},'raw_ref':dict(pin)})
    if not records:return None
    identities={sha(canonical(record['identity']))for record in records}
    if len(identities)!=1:raise BiliInputsBlocked('bili_source_native_single_video_records_conflict')
    return {'version':'bilibili_native_single_video_scope_v1','identity':records[0]['identity'],'original_raw_refs':[record['raw_ref']for record in records]}

def _select_complete_native_rows(rows,raw_refs,guard,directory):
    # Search metadata may omit pages/CID. The same official extractor proves these before media download.
    candidates=[];seen=set()
    for row in rows:
        if row['content_id']in seen:continue
        seen.add(row['content_id']);candidates.append(row)
    once(Path(directory)/'native-single-source-selection.private.json',{'control_id':guard['control_id'],
        'candidate_ids':[row['content_id']for row in candidates],'order':'original_input_rank',
        'scope_proof_stage':'same_official_extractor_metadata_before_download','selected_ids':[],
        'search_metadata_missing_CID_is_not_disqualification':True})
    if len({str(row['author_id'])for row in candidates})<3:raise BiliInputsBlocked('bili_source_three_distinct_external_native_authors_required')
    return candidates
def _validate_download_identity(info,row,binding):
    identity=binding['identity'];bvid=identity['bvid'];actual=str(info.get('id'));url=identity['canonical_url']
    # This is an explicit one-page alias, never suffix stripping from an unknown/multipart work.
    if (identity['page_count']!=1 or str(info.get('uploader_id'))!=identity['author_id']or actual not in(bvid,bvid+'_p1')
            or info.get('webpage_url')not in(url,url+'/',url+'?p=1',url+'/?p=1')
            or type(info.get('duration'))not in(int,float)or not math.isfinite(info['duration'])
            or info['duration']<=0 or math.ceil(info['duration'])!=identity['native_duration_seconds']
            or(info.get('cid')is not None and str(info['cid'])!=str(identity['cid']))):
        raise BiliInputsBlocked('bili_source_actual_single_native_identity_changed')
    if row['content_id']!=bvid or str(row['author_id'])!=identity['author_id']or row['canonical_url']!=url:
        raise BiliInputsBlocked('bili_source_current_native_binding_changed')

def grouped_complete_media_packets(materials,maximum_video_bytes):
    """Preserve the original two complete multipart requests; the official cap is per video."""
    if len(materials)!=3 or len({m['opaque_id']for m in materials})!=3:raise BiliInputsBlocked('bili_source_three_complete_distinct_inputs_required')
    packets=complete_media_packets(materials,maximum_video_bytes=maximum_video_bytes)
    identities=[m['opaque_id']for m in materials]
    # B05: the video group carries all three complete videos over a ~0.3-1.4 MB/s tunnel; scale its window with the bytes.
    wire=sum(len(m.get('video_wire')or'')for m in materials)
    return [('video',identities,packets[0],int(min(600,max(180,90+wire/300000)))),('blind-audio',identities,packets[1],90)]


def _decode_complete_request_groups(requests,materials):
    expected=[m['opaque_id']for m in materials];by_id={m['opaque_id']:m for m in materials};found={'video':[],'blind-audio':[]};outputs={'video':[],'blind-audio':[]}
    for request in requests:
        kind=request.get('kind');ids=request.get('input_ids',expected)
        if kind not in found or not isinstance(ids,list)or not ids or len(set(ids))!=len(ids)or any(i not in by_id for i in ids):raise BiliInputsBlocked('bili_source_complete_group_ids_changed')
        packet=json.loads(read_ref(request['request_ref']))
        if not isinstance(packet,list)or len(packet)!=1 or set(packet[0])!={'role','content'}or packet[0]['role']!='user':raise BiliInputsBlocked('bili_source_complete_request_envelope_changed')
        parts=packet[0]['content'];group=[by_id[i]for i in ids]
        empty=[dict(m,video_wire='',audio_wire='',audio_format='wav')for m in group];prompt=complete_media_packets(empty,maximum_video_bytes=50*1024*1024)[0 if kind=='video'else 1][0]['content'][0]
        if not isinstance(parts,list)or len(parts)!=len(ids)+1 or parts[0]!=prompt:raise BiliInputsBlocked('bili_source_full_anonymous_prompt_changed')
        for material,part in zip(group,parts[1:]):
            if kind=='video':
                if set(part)!={'type','video_url'}or part['type']!='video_url'or set(part['video_url'])!={'url'}or not part['video_url']['url'].startswith('data:video/mp4;base64,'):raise BiliInputsBlocked('bili_source_complete_video_wire_changed')
                encoded=part['video_url']['url'].split(',',1)[1];pin=material['transport_video_ref']if _verify_video_transport(material)is not None else material['video_ref']
                if len(part['video_url']['url'])>50*1024*1024:raise BiliInputsBlocked('bili_source_original_single_video_cap_exceeded')
            else:
                if set(part)!={'type','input_audio'}or part['type']!='input_audio'or set(part['input_audio'])!={'data','format'}:raise BiliInputsBlocked('bili_source_complete_audio_wire_changed')
                if part['input_audio']['format']=='aac':
                    context_pin=request.get('source_context_ref')
                    if not isinstance(context_pin,dict):raise BiliInputsBlocked('bili_audio_adapter_source_context_required')
                    context=_strict_json(read_ref(context_pin).decode('utf8'));choice=context.get('audio_transport_choice')
                    if (not isinstance(choice,dict)or choice.get('use_original_aac')is not True
                            or context.get('current_role_route')!=choice.get('current_role_route')):raise BiliInputsBlocked('bili_audio_adapter_AAC_not_admitted')
                    _verify_audio_transport_choice(choice,context['current_role_route'],choice.get('canonical_provider'))
                    scoped=[v for v in context.get('inputs',[])if isinstance(v,dict)and v.get('opaque_id')==material['opaque_id']]
                    if (len(scoped)!=1 or any(scoped[0].get(k)!=material.get(k)for k in('video_ref','audio_ref','transport_audio_ref','transport_audio_proof_ref','native_scope_ref'))):raise BiliInputsBlocked('bili_audio_adapter_current_material_changed')
                    if _verify_original_audio_transport(material)is None:raise BiliInputsBlocked('bili_source_admitted_original_AAC_transport_required')
                    pin=material['transport_audio_ref']
                elif part['input_audio']['format']=='wav'and not material.get('transport_audio_ref')and not material.get('transport_audio_proof_ref'):pin=material['audio_ref']
                else:raise BiliInputsBlocked('bili_source_complete_audio_wire_changed')
                encoded=part['input_audio']['data']
            try:raw=base64.b64decode(encoded,validate=True)
            except(ValueError,TypeError)as error:raise BiliInputsBlocked('bili_source_full_wire_base64_changed')from error
            if sha(raw)!=pin['sha256']or len(raw)!=pin['bytes']:raise BiliInputsBlocked('bili_source_full_wire_SHA_or_length_changed')
        response=json.loads(read_ref(request['response_ref']));choices=response.get('choices')or[];message=choices[0].get('message')if len(choices)==1 else None
        if not isinstance(message,dict)or not isinstance(message.get('content'),str):raise BiliInputsBlocked('bili_source_actual_final_content_changed')
        outputs[kind].extend(decode_observation_response(message['content'],ids));found[kind].extend(ids)
    if any(found[kind]!=expected for kind in found):raise BiliInputsBlocked('bili_source_all_three_full_views_and_tracks_required')
    return outputs['video'],outputs['blind-audio']

def _check_extractor_pagelist(value,binding):
    identity=binding['identity'];pages=value.get('data')if isinstance(value,dict)and value.get('code')==0 else None
    if(not isinstance(pages,list)or len(pages)!=1 or not isinstance(pages[0],dict)
            or pages[0].get('page')!=1 or pages[0].get('cid')!=identity['cid']
            or pages[0].get('duration')!=identity['native_duration_seconds']):
        raise BiliInputsBlocked('bili_source_download_actual_single_CID_required')
    return value


def _install_extractor_scope_guard(downloader,row,directory):
    """Capture the official extractor's existing pagelist call, before any media download."""
    extractor=downloader.get_info_extractor('BiliBili');original=extractor._download_json;seen=[]
    def scoped(url,*args,**kwargs):
        value=original(url,*args,**kwargs);parsed=urlsplit(str(url));query=kwargs.get('query')or{}
        if parsed.scheme=='https'and parsed.hostname=='api.bilibili.com'and parsed.path=='/x/player/pagelist':
            if query.get('bvid')!=row['content_id']:raise BiliInputsBlocked('bili_source_extractor_BVID_changed')
            pin=once(Path(directory)/('actual-extractor-pagelist-'+str(len(seen)+1)+'.private.json'),value);seen.append(pin)
            pages=value.get('data')if isinstance(value,dict)and value.get('code')==0 else None
            if not isinstance(pages,list)or not pages:raise BiliInputsBlocked('bili_source_official_pagelist_unknown_no_retry')
            if len(pages)>1:raise BiliSourceExcluded('bili_source_actual_native_multipart_excluded')
        return value
    extractor._download_json=scoped
    return seen


def _bind_actual_metadata_scope(row,info,pagelist_ref,directory):
    once(Path(directory)/'metadata-only-extractor-result.private.json',__import__('yt_dlp').YoutubeDL.sanitize_info(info))
    # All fields come from the original current search identity and the actual official metadata stage.
    doc=json.loads(read_ref(pagelist_ref));pages=doc.get('data')if isinstance(doc,dict)and doc.get('code')==0 else None
    if not isinstance(pages,list)or not pages:raise BiliInputsBlocked('bili_source_official_pagelist_unknown_no_retry')
    if len(pages)!=1:raise BiliSourceExcluded('bili_source_actual_native_multipart_excluded')
    page=pages[0]
    if(not isinstance(page,dict)or page.get('page')!=1 or type(page.get('cid'))is not int or page['cid']<=0
            or type(page.get('duration'))is not int or page['duration']<=0):raise BiliInputsBlocked('bili_source_actual_CID_or_full_duration_unknown')
    if info.get('_type','video')!='video'or 'entries'in info:raise BiliSourceExcluded('bili_source_actual_metadata_not_one_video')
    binding={'version':'bilibili_official_single_video_scope_v1','identity':{'bvid':row['content_id'],'cid':page['cid'],
        'author_id':str(row['author_id']),'canonical_url':row['canonical_url'],'page_count':1,'native_duration_seconds':page['duration']},
        'original_search_metadata_ref':{'path':row['raw_response_path'],'sha256':row['raw_response_hash']},
        'actual_pagelist_ref':pagelist_ref,'proof_stage':'same_official_extractor_metadata_before_media_download'}
    _validate_download_identity(info,row,binding);_check_extractor_pagelist(doc,binding)
    return binding

def _reject_prior_complete_download(row,guard):
    # Never implicitly repeat a past source download. An explicit authenticated original-file reuse is a separate decision.
    for intent in guard['scope'].parent.glob('*/native-topic-source-bilibili/complete-video-observation/clip-*/download-intent.private.json'):
        prior_scope=intent.parents[3]
        if prior_scope==guard['scope']or not re.fullmatch('[0-9a-f]{64}',prior_scope.name):continue
        value=_strict_json(private(intent).decode('utf8'))
        if value.get('native_content_id')==row['content_id']:
            raise BiliSourceExcluded('bili_source_prior_download_intent_requires_explicit_original_reuse')


def _capture_source_archive(ref):
    # Only the original managed producer path and the existing bounded Root release layout.
    from itertools import islice
    expected=ref.get('sha256');original=Path(ref.get('path',''))
    if original!=Path(__file__) and original!=PROJECT/'content_platform/bilibili_native_inputs.py':
        raise BiliSourceExcluded('bili_source_prior_capture_producer_path_changed')
    paths=[original];archives=list(islice(Path('/srv/hermes-worker/staging').glob('*/candidate/NEW/bilibili_native_inputs.py'),129))
    if len(archives)>128:raise BiliSourceExcluded('bili_source_prior_capture_archive_discovery_bound')
    for path in paths+archives:
        try:raw=private(path)
        except (OSError,BiliInputsBlocked):continue
        if sha(raw)==expected:return reference(path)
    raise BiliSourceExcluded('bili_source_prior_capture_original_producer_archive_missing')


def _read_official_source_preflight_failure(directory,request,producer_ref):
    """仅原代码中SDK来源指纹在首AV请求前失败；不是泛unknown准入。"""
    import ast
    if (directory/'preflight.private.json').exists():raise BiliSourceExcluded('bili_source_preflight_failure_already_returned')
    error_ref=reference(directory.with_suffix('.stderr.private.bin'));raw=read_ref(error_ref)
    if not 0<len(raw)<=16384:raise BiliSourceExcluded('bili_source_preflight_failure_trace_bound')
    trace=raw.decode('utf8');source=read_ref(producer_ref).decode('utf8');tree=ast.parse(source)
    functions=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)and n.name=='_observe_packets']
    if len(functions)!=1:raise BiliSourceExcluded('bili_source_preflight_original_code_unknown')
    function=functions[0];targets=[]
    for node in ast.walk(function):
        if isinstance(node,ast.Dict):
            targets.extend(value for key,value in zip(node.keys,node.values)if isinstance(key,ast.Constant)and key.value=='SDK_video_source_ref')
    if len(targets)!=1 or ast.unparse(targets[0])!='fingerprint(Path(vision_tools.__file__))':
        raise BiliSourceExcluded('bili_source_preflight_original_source_statement_changed')
    target=targets[0]
    model_calls=[n for n in ast.walk(function)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='async_call_llm']
    starts=[n for n in ast.walk(function)if isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id=='once'and n.args and '-started.private.json'in ast.unparse(n.args[0])]
    if not model_calls or not starts or any(n.lineno<=target.lineno for n in model_calls+starts):
        raise BiliSourceExcluded('bili_source_preflight_no_effect_order_unproven')
    frames=re.findall(r'  File "([^"\n]+)", line ([0-9]+), in ([^\n]+)',trace)
    expected=(request.get('module_ref',{}).get('path'),str(target.lineno),'_observe_packets')
    if (trace.count('Traceback (most recent call last):')!=1 or expected not in frames
            or 'fingerprint(Path(vision_tools.__file__))'not in trace
            or not trace.rstrip().endswith('BiliInputsBlocked: bili_original_managed_source_required')
            or any(name=='async_call_llm'for path,line,name in frames)):
        raise BiliSourceExcluded('bili_source_preflight_exact_original_trace_required')
    return {'stderr_ref':error_ref,'original_producer_snapshot_ref':producer_ref,
        'failed_statement_line':target.lineno,'phase':'official_SDK_source_reference_before_first_AV_started',
        'AV_model_results_reused':False,'effect_absence':'original_source_order_and_no_started_markers'}

def _read_completed_capture_intent(intent,row):
    value=_strict_json(private(intent).decode('utf8'));clip=intent.parent;directory=clip.parent;scope=directory.parent.parent
    fail=directory/'failed_or_unknown.private.json';complete=directory/'completed.private.json'
    if fail.exists():
        failed=_strict_json(private(fail).decode('utf8'))
        known=('bili_source_original_single_video_cap_exceeded','bili_source_three_distinct_fully_scoped_single_videos_required','bili_source_complete_group_requests_original_budget_insufficient')
        if (failed.get('error_type')!='BiliInputsBlocked'or failed.get('error_sha256')not in {sha(code.encode())for code in known+('bili_original_managed_source_required',)}
                or list(directory.glob('video-*-started.private.json'))or list(directory.glob('blind-audio-*-started.private.json'))):
            raise BiliSourceExcluded('bili_source_prior_capture_unknown_effect_not_reusable')
    elif not complete.exists():raise BiliSourceExcluded('bili_source_prior_capture_not_terminal_or_complete')
    start_ref=reference(directory/'started.private.json');start=_strict_json(read_ref(start_ref).decode('utf8'))
    if(start.get('version')!='normal_bilibili_complete_source_observation_v1'or start.get('NoPub')is not True
            or start.get('retry')is not False or start.get('fallback')is not False):raise BiliSourceExcluded('bili_source_prior_capture_original_scope_changed')
    prior_authority=_strict_json(read_ref(start['authority_ref']).decode('utf8'));bound=prior_authority.get('current_runtime_binding')or{}
    if(prior_authority.get('job_id')!=start['control_id']or bound.get('job_id')!=start['control_id']
            or bound.get('source_kind')!='signed_channel_cycle_policy_writer'or bound.get('budget_seconds')!=3600):raise BiliSourceExcluded('bili_source_prior_capture_authority_changed')
    request=_strict_json(private(directory.with_suffix('.request.private.json')).decode('utf8'))
    if(request.get('control_id')!=start['control_id']or request.get('directory')!=str(directory)
            or(fail.exists()and failed.get('control_id')!=start['control_id'])):raise BiliSourceExcluded('bili_source_prior_capture_request_scope_changed')
    if complete.exists():
        finished=_strict_json(private(complete).decode('utf8'))
        if(finished.get('version')!='normal_bilibili_complete_source_observation_v1'or finished.get('control_id')!=start['control_id']
                or finished.get('authority_ref')!=start['authority_ref']or fail.exists()):raise BiliSourceExcluded('bili_source_prior_capture_terminal_conflict')
    marker=clip/'capture-complete.private.json'
    if marker.exists():
        marker_ref=reference(marker);record=_strict_json(read_ref(marker_ref).decode('utf8'))
        if(record.get('version')!='normal_bilibili_complete_capture_v1'or record.get('control_id')!=start['control_id']
                or record.get('authority_ref')!=start['authority_ref']or record.get('model_observation_reused')is not False):
            raise BiliSourceExcluded('bili_source_prior_complete_capture_marker_changed')
        producer_ref=record['producer_snapshot_ref'];read_ref(producer_ref);material=record['material'];kind='versioned_complete_capture'
        if(Path(producer_ref['path'])!=clip/'capture-producer-source.private.py'or producer_ref['sha256']!=request.get('module_ref',{}).get('sha256')):raise BiliSourceExcluded('bili_source_prior_capture_producer_snapshot_changed')
        original_rows=[r for r in request.get('rows')or[]if r.get('content_id')==row['content_id']]
        captured=datetime.fromisoformat(record['captured_at'].replace('Z','+00:00'));observed=datetime.fromisoformat(record['original_source_observed_at'].replace('Z','+00:00'))
        if(record['native_source_observed_at']!=record['original_source_observed_at']or len(original_rows)!=1
                or original_rows[0].get('observed_at')!=record['original_source_observed_at']or captured.tzinfo is None or observed.tzinfo is None
                or not observed<=captured or captured.timestamp()>start['deadline_unix']or record['original_effect_deadline_unix']!=start['deadline_unix']):
            raise BiliSourceExcluded('bili_source_prior_capture_time_changed')
    else:
        if fail.exists()and failed.get('error_sha256')==sha(b'bili_original_managed_source_required'):
            raise BiliSourceExcluded('bili_source_preflight_reuse_versioned_capture_required')
        marker_ref=reference(directory/'source-observation-context.private.json');record=_strict_json(read_ref(marker_ref).decode('utf8'))
        selection_ref=reference(directory/'single-native-final-selection.private.json');selection=_strict_json(read_ref(selection_ref).decode('utf8'))
        request=_strict_json(private(directory.with_suffix('.request.private.json')).decode('utf8'))
        if(record.get('version')!='normal_bilibili_complete_observation_context_v1'or record.get('control_id')!=start['control_id']
                or record.get('authority_ref')!=start['authority_ref']or selection.get('control_id')!=start['control_id']
                or request.get('control_id')!=start['control_id']or request.get('module_ref',{}).get('sha256')!=record.get('producer_source_ref',{}).get('sha256')):
            raise BiliSourceExcluded('bili_source_prior_complete_capture_context_changed')
        matches=[m for m in record.get('inputs')or[]if m.get('native_content_id')==row['content_id']]
        done=[m for m in selection.get('decisions')or[]if m.get('content_id')==row['content_id']and m.get('state')=='complete_native_single_video']
        if(len(matches)!=1 or len(done)!=1 or (selection.get('selected_ids')or[]).count(row['content_id'])!=1
                or matches[0]['native_scope_ref']!=done[0]['native_scope_ref']):raise BiliSourceExcluded('bili_source_prior_full_capture_return_chain_missing')
        material=matches[0];producer_ref=_capture_source_archive(record['producer_source_ref']);kind='original_v1_complete_return_chain'
    preflight_failure=None
    if fail.exists()and failed.get('error_sha256')==sha(b'bili_original_managed_source_required'):
        preflight_failure=_read_official_source_preflight_failure(directory,request,producer_ref)
    measured_ref=reference(clip/'full-media-measurement.private.json');measured=_strict_json(read_ref(measured_ref).decode('utf8'))
    required={'video_ref','audio_ref','duration_seconds','video_duration_seconds','frames','sample_rate','channels','pcm_sha256','source_metadata_ref','decode_measurement','native_scope_ref','actual_pagelist_ref','download_transport_counts_ref'}
    if not required<=set(measured)or not required<=set(material)or any(material.get(k)!=v for k,v in measured.items()):raise BiliSourceExcluded('bili_source_prior_complete_measurement_changed')
    video=material['video_ref'];video_path=Path(video['path'])
    if not video_path.is_relative_to(clip)or type(video.get('bytes'))is not int or video['bytes']!=video_path.stat().st_size:
        raise BiliSourceExcluded('bili_source_prior_complete_video_size_changed')
    if 4*((video['bytes']+2)//3)+len('data:video/mp4;base64,')>50*1024*1024:
        raise BiliSourceExcluded('bili_source_original_single_video_cap_exceeded')
    for pin in(material['video_ref'],material['audio_ref'],material['source_metadata_ref'],material['native_scope_ref'],material['actual_pagelist_ref']):
        if not Path(pin['path']).is_relative_to(clip):raise BiliSourceExcluded('bili_source_prior_capture_cross_scope_file')
        read_ref(pin)
    binding=_strict_json(read_ref(material['native_scope_ref']).decode('utf8'));identity=binding['identity']
    if(value.get('native_content_id')!=row['content_id']or str(value.get('native_author_id'))!=identity['author_id']or identity['bvid']!=row['content_id']or identity['author_id']!=str(row['author_id'])
            or identity['canonical_url']!=row['canonical_url']or identity['page_count']!=1
            or binding['actual_pagelist_ref']!=material['actual_pagelist_ref']):raise BiliSourceExcluded('bili_source_prior_capture_native_identity_changed')
    if(binding.get('version')!='bilibili_official_single_video_scope_v1'or binding.get('proof_stage')!='same_official_extractor_metadata_before_media_download'):raise BiliSourceExcluded('bili_source_prior_capture_whole_native_scope_missing')
    if not Path(binding['original_search_metadata_ref']['path']).is_relative_to(directory.parent):raise BiliSourceExcluded('bili_source_prior_capture_native_raw_scope_changed')
    read_ref(binding['original_search_metadata_ref'])
    _validate_download_identity(_strict_json(read_ref(material['source_metadata_ref']).decode('utf8')),row,binding)
    _check_extractor_pagelist(_strict_json(read_ref(material['actual_pagelist_ref']).decode('utf8')),binding)
    from .current_audio_review_runtime import _blind_wave
    decode=material['decode_measurement']
    if(decode.get('whole_track')is not True or any(decode.get(k)is not False for k in('channel_reduction','resampling','speed_change','trim'))
            or decode.get('original_sha256')!=material['video_ref']['sha256']or decode.get('pcm_sha256')!=material['pcm_sha256']
            or decode.get('sample_width')!=4):raise BiliSourceExcluded('bili_source_prior_capture_full_track_decode_missing')
    audio,samples=_blind_wave(read_ref(material['audio_ref']))
    if(audio['pcm_sha256']!=material['pcm_sha256']or audio['frames']!=material['frames']or audio['rate']!=material['sample_rate']
            or audio['channels']!=material['channels']):raise BiliSourceExcluded('bili_source_prior_capture_complete_PCM_changed')
    keys=('video_ref','audio_ref','duration_seconds','video_duration_seconds','frames','sample_rate','channels','pcm_sha256',
        'source_metadata_ref','decode_measurement','native_scope_ref','actual_pagelist_ref','download_transport_counts_ref')
    return {'version':'normal_bilibili_capture_only_admission_v1','original_control_id':start['control_id'],'original_authority_ref':start['authority_ref'],
        'original_effect_deadline_unix':start['deadline_unix'],'original_capture_time':record.get('captured_at'),'capture_marker_kind':kind,
        'original_start_ref':start_ref,'capture_record_ref':marker_ref,'measurement_ref':measured_ref,'producer_archive_ref':producer_ref,
        'native_identity':identity,'material':{key:copy.deepcopy(material[key])for key in keys},'model_observation_reused':False,
        **({'original_source_preflight_failure_proof':preflight_failure}if preflight_failure is not None else {})}


def _read_completed_prior_capture(row,guard):
    matches=[]
    for intent in guard['scope'].parent.glob('*/native-topic-source-bilibili/complete-video-observation/clip-*/download-intent.private.json'):
        scope=intent.parents[3]
        if scope==guard['scope']or not re.fullmatch('[0-9a-f]{64}',scope.name):continue
        value=_strict_json(private(intent).decode('utf8'))
        if value.get('native_content_id')==row['content_id']:
            try:matches.append(_read_completed_capture_intent(intent,row))
            except BiliSourceExcluded:raise
            except (OSError,ValueError,KeyError,TypeError)as error:raise BiliSourceExcluded('bili_source_prior_capture_missing_or_invalid_evidence')from error
    if not matches:return None
    identities={sha(canonical({'identity':m['native_identity'],'video':m['material']['video_ref']['sha256'],'audio':m['material']['audio_ref']['sha256']}))for m in matches}
    if len(identities)!=1:raise BiliSourceExcluded('bili_source_prior_capture_conflicting_originals')
    return matches[0]


def _validate_capture_reuse_identity(reuse,binding):
    if(reuse.get('version')!='normal_bilibili_capture_only_admission_v1'or reuse.get('model_observation_reused')is not False
            or reuse.get('native_identity')!=binding.get('identity')):raise BiliInputsBlocked('bili_source_current_metadata_changed_from_original_capture')


def _capture_complete_media(row,directory,config,deadline,*,reuse_material=None):
    """The installed official yt-dlp extractor, one intent, full original stream; no sampling."""
    import yt_dlp,http.cookiejar
    identity=row['content_id'];url='https://www.bilibili.com/video/'+identity
    if not re.fullmatch(r'BV[A-Za-z0-9]{10}',identity)or row['canonical_url']!=url:raise BiliInputsBlocked('bili_source_native_canonical_BVID_required')
    original_cookie=PROJECT/'external/social-auto-upload/cookies/bilibili_main.json'
    if Path(config['cookie_file'])!=original_cookie:raise BiliInputsBlocked('bili_source_original_cookie_alias_required')
    cookie_before=fingerprint(original_cookie);cookies=_strict_json(private(original_cookie).decode('utf-8'))
    if isinstance(cookies,dict):
        if 'cookie_info'in cookies:
            info=cookies['cookie_info']
            if (not isinstance(info,dict)or not info or not all(isinstance(k,str)and k and isinstance(v,str)for k,v in info.items())):
                raise BiliInputsBlocked('bili_source_original_cookie_info_mapping_required')
            # The original header state has no domain metadata. Scope only this temporary extractor jar to Bili HTTPS.
            cookies=[{'name':k,'value':v,'domain':'.bilibili.com','path':'/','secure':True}for k,v in info.items()]
        else:cookies=cookies.get('cookies')
    if not isinstance(cookies,list):raise BiliInputsBlocked('bili_source_original_cookie_layout_unknown')
    cookie_file=directory/'original-scoped-cookies.private.txt';jar=http.cookiejar.MozillaCookieJar(str(cookie_file))
    for c in cookies:
        domain=c.get('domain')or''
        if domain.lstrip('.').casefold()!='bilibili.com':continue
        if not all(isinstance(c.get(k),str)for k in('name','value')):raise BiliInputsBlocked('bili_source_original_cookie_layout_unknown')
        expires=c.get('expires');expires=int(expires)if isinstance(expires,(int,float))and expires>0 else None
        jar.set_cookie(http.cookiejar.Cookie(0,c['name'],c['value'],None,False,domain,True,domain.startswith('.'),c.get('path')or'/',True,bool(c.get('secure')),expires,expires is None,None,None,{},False))
    if not len(jar):raise BiliInputsBlocked('bili_source_original_bilibili_cookie_jar_empty')
    fd=os.open(cookie_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd);jar.save(ignore_discard=True,ignore_expires=False)
    messages=[]
    class Logger:
        def debug(self,text):messages.append(str(text))
        def warning(self,text):messages.append(str(text))
        def error(self,text):messages.append(str(text))
    def progress(value):_remaining(deadline,1)
    options={'cookiefile':str(cookie_file),'noplaylist':True,'retries':0,'fragment_retries':0,'extractor_retries':0,'file_access_retries':0,
        'socket_timeout':min(15,_remaining(deadline,15)),'concurrent_fragment_downloads':1,'continuedl':False,'overwrites':False,
        'format':'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]','merge_output_format':'mp4','outtmpl':str(directory/'complete.%(ext)s'),
        'writeinfojson':True,'writethumbnail':False,'writesubtitles':False,'writeautomaticsub':False,
        'logger':Logger(),'progress_hooks':[progress],'postprocessor_hooks':[progress],'quiet':True,'no_warnings':False}
    once(directory/'metadata-intent.private.json',{'canonical_url':url,'native_content_id':identity,'native_author_id':row['author_id'],
        'original_cookie_fingerprint':cookie_before,'extractor_source_ref':fingerprint(inspect.getfile(yt_dlp.YoutubeDL)),
        'deadline_unix':deadline,'retry':False,'full_video':True,'media_is_reference_only':True})
    transport={'official_urlopen_started':0,'official_urlopen_completed':0,'official_urlopen_failed':0,'physical_HTTP_count':None};reused=None
    try:
        with yt_dlp.YoutubeDL(options)as downloader:
            actual_pages=_install_extractor_scope_guard(downloader,row,directory)
            original_urlopen=downloader.urlopen
            def counted_urlopen(*args,**kwargs):
                transport['official_urlopen_started']+=1
                try:value=original_urlopen(*args,**kwargs)
                except BaseException:
                    transport['official_urlopen_failed']+=1;raise
                transport['official_urlopen_completed']+=1;return value
            downloader.urlopen=counted_urlopen
            # Raw video IE result: do not invoke its download processing until its actual native scope is proven.
            info=downloader.extract_info(url,download=False,process=False)
            if not isinstance(info,dict):raise BiliInputsBlocked('bili_source_official_metadata_unknown_no_retry')
            if len(actual_pages)!=1:raise BiliInputsBlocked('bili_source_one_actual_extractor_pagelist_required')
            binding=_bind_actual_metadata_scope(row,info,actual_pages[0],directory)
            native_scope_ref=once(directory/'native-whole-video-scope.private.json',binding)
            if reuse_material is not None:
                _validate_capture_reuse_identity(reuse_material,binding)
                reused=copy.deepcopy(reuse_material['material']);reused.update(native_scope_ref=native_scope_ref,actual_pagelist_ref=actual_pages[0],
                    source_metadata_ref=reference(directory/'metadata-only-extractor-result.private.json'))
                reused['capture_reuse_ref']=once(directory/'capture-reuse.private.json',{'version':'normal_bilibili_capture_only_reuse_v1',
                    'current_native_scope_ref':native_scope_ref,'current_native_source_observed_at':row['observed_at'],
                    'original_capture':reuse_material,'media_download_performed':False,'model_observation_reused':False})
            else:
                once(directory/'download-intent.private.json',{'canonical_url':url,'native_content_id':identity,
                    'native_author_id':row['author_id'],'native_scope_ref':native_scope_ref,'original_cookie_fingerprint':cookie_before,
                    'deadline_unix':deadline,'retry':False,'full_video':True,'media_is_reference_only':True})
                info=downloader.process_ie_result(info,download=True)
    finally:
        once(directory/'download-transport-counts.private.json',transport)
        once(directory/'download-log.private.txt','\n'.join(messages).encode(),raw=True)
    if fingerprint(original_cookie)!=cookie_before:raise BiliInputsBlocked('bili_source_original_cookie_changed')
    if reused is not None:
        from .current_audio_review_runtime import _blind_wave
        _,samples=_blind_wave(read_ref(reused['audio_ref']));reused['current_metadata_transport_counts_ref']=reference(directory/'download-transport-counts.private.json')
        return dict(reused,samples=samples,audio_wire=base64.b64encode(read_ref(reused['audio_ref'])).decode(),audio_format='wav')
    once(directory/'extractor-result.private.json',yt_dlp.YoutubeDL.sanitize_info(info))
    _validate_download_identity(info,row,binding)
    if len(actual_pages)!=1:raise BiliInputsBlocked('bili_source_one_actual_extractor_pagelist_required')
    candidates=[p for p in directory.glob('complete.*')if p.suffix.lower()=='.mp4']
    if len(candidates)!=1:raise BiliInputsBlocked('bili_source_one_complete_native_video_required')
    path=candidates[0];path.chmod(0o600);ref=reference(path)
    def run(arguments):
        value=subprocess.run(arguments,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=_remaining(deadline,60),check=False)
        once(directory/('process-'+sha(canonical(arguments))[:16]+'.stderr.private.bin'),value.stderr,raw=True)
        if value.returncode:raise BiliInputsBlocked('bili_source_complete_media_decode_failed')
        return value.stdout
    probe=json.loads(run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_streams','-show_format','-of','json',str(path)]))
    once(directory/'complete-probe.private.json',probe)
    videos=[v for v in probe['streams']if v.get('codec_type')=='video'];audios=[v for v in probe['streams']if v.get('codec_type')=='audio']
    if len(videos)!=1 or len(audios)!=1:raise BiliInputsBlocked('bili_source_unique_full_video_and_audio_stream_required')
    # Decode the entire original visual stream to EOF; this is integrity, not a substitute for viewing it.
    run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(path),'-map','0:v:0','-an','-f','null','-'])
    from .current_audio_review_runtime import _blind_complete_audio,_blind_wave
    measure,samples,wire,fmt=_blind_complete_audio(path,read_ref(ref))
    _blind_wave(wire) # MP4 -> complete original-rate/channel PCM32, no filename or semantic tags.
    audio_ref=once(directory/'anonymous-full-track.wav',wire,raw=True)
    result={'video_ref':ref,'audio_ref':audio_ref,'duration_seconds':measure['duration_seconds'],
        'video_duration_seconds':float(videos[0].get('duration')or probe['format']['duration']),
        'frames':measure['frames'],'sample_rate':measure['rate'],'channels':measure['channels'],'pcm_sha256':measure['pcm_sha256'],
        'source_metadata_ref':reference(directory/'extractor-result.private.json'),'decode_measurement':measure,
        'native_scope_ref':native_scope_ref,'actual_pagelist_ref':actual_pages[0],'download_transport_counts_ref':reference(directory/'download-transport-counts.private.json')}
    once(directory/'full-media-measurement.private.json',result)
    if sha(path.read_bytes())!=ref['sha256']:raise BiliInputsBlocked('bili_source_original_media_changed_after_decode')
    return dict(result,samples=samples,audio_wire=base64.b64encode(wire).decode(),audio_format=fmt)



# Root R15/R16只读已验官方源码；此精pin由本producer自身Source SHA传递绑定。
_OFFICIAL_SDK_REFERENCE_PINS={
 '/srv/hermes-agent/source/root/.hermes/hermes-agent/agent/auxiliary_client.py':'8ccec9237ad4511756d8d3089a9f4e3f62d7245274388eaaee96453d00dd34b0',
 '/srv/hermes-agent/source/root/.hermes/hermes-agent/hermes_cli/runtime_provider.py':'8fa2057fb1ed993a3d4f3495dfa9d8b474b17e8fd141ad423129b09e2ad824e2',
 '/srv/hermes-agent/source/root/.hermes/hermes-agent/tools/vision_tools.py':'54186c31cd1add92907759014d97304863447f9d57b456edc3f68d1cb9023dc9'}

def _official_sdk_reference(path):
    """仅两精pin的官方SDK引用承认Root同权限组；通用fingerprint完全不动。"""
    p=Path(path);expected=_OFFICIAL_SDK_REFERENCE_PINS.get(str(p))
    if expected is None:return fingerprint(p)
    import pwd,grp
    users=pwd.getpwall();root_group=grp.getgrgid(0)
    if any(u.pw_uid!=0 and(u.pw_gid==0 or u.pw_name in root_group.gr_mem)for u in users):
        raise BiliInputsBlocked('bili_official_sdk_nonroot_group_writer')
    # 未能解析的显式成员亦不能推定为UID0。
    root_names={u.pw_name for u in users if u.pw_uid==0}
    if any(name not in root_names for name in root_group.gr_mem):raise BiliInputsBlocked('bili_official_sdk_unknown_root_group_member')
    before=[]
    def identity(st):return tuple(getattr(st,key)for key in('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    for q in(p,*p.parents):
        st=q.lstat()
        if (q.is_symlink()or st.st_uid!=0 or st.st_gid!=0 or st.st_mode&0o002
                or any(name.startswith('system.posix_acl_')for name in os.listxattr(q,follow_symlinks=False))):
            raise BiliInputsBlocked('bili_official_sdk_root_only_writer_required')
        if q==p:
            if not stat.S_ISREG(st.st_mode)or st.st_nlink!=1 or st.st_size>4*1024*1024:raise BiliInputsBlocked('bili_official_sdk_regular_source_required')
        elif not stat.S_ISDIR(st.st_mode):raise BiliInputsBlocked('bili_official_sdk_managed_parent_required')
        before.append((q,identity(st)))
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        first=identity(os.fstat(fd))
        if first!=before[0][1]:raise BiliInputsBlocked('bili_official_sdk_open_identity_changed')
        chunks=[];left=first[6]+1
        while left:
            chunk=os.read(fd,left)
            if not chunk:break
            chunks.append(chunk);left-=len(chunk)
        raw=b''.join(chunks)
        if len(raw)!=first[6]or identity(os.fstat(fd))!=first:raise BiliInputsBlocked('bili_official_sdk_read_identity_changed')
    finally:os.close(fd)
    if hashlib.sha256(raw).hexdigest()!=expected:raise BiliInputsBlocked('bili_official_sdk_exact_source_sha_changed')
    if any(identity(q.lstat())!=same for q,same in before):raise BiliInputsBlocked('bili_official_sdk_parent_identity_changed')
    return {'path':str(p),'sha256':expected,'bytes':len(raw)}

def _source_child_route(guard,directory):
    """Only called in a new project child. No shared SDK or long-lived worker mutation."""
    from .mandatory_quality_context import _native_task_home
    from .quality_review_submission import _current_role_vision_factory
    home,route,provenance=_native_task_home(guard['control_id'])
    if home!=guard['home']:raise BiliInputsBlocked('bili_source_current_role_home_changed')
    sdk=(home/'hermes-agent').resolve()
    if str(sdk)not in sys.path:sys.path.insert(0,str(sdk))
    from agent import auxiliary_client as auxiliary
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from tools import vision_tools
    from .media_transport_runtime import activate_sdk_child, verify_sdk_child_transport
    transport_binding=activate_sdk_child(route,provenance['provider'],home)
    original_source_call=auxiliary.async_call_llm
    async def mapped_source_call(*args,**kwargs):
        verify_sdk_child_transport(transport_binding,route,provenance['provider'],home,required_seconds=kwargs['timeout'])
        result=await original_source_call(*args,**kwargs)
        verify_sdk_child_transport(transport_binding,route,provenance['provider'],home)
        return result
    auxiliary.async_call_llm=mapped_source_call
    selections=[];original_cache=auxiliary._get_cached_client
    def no_retry_client(*args,**kwargs):
        client,model=original_cache(*args,**kwargs)
        if auxiliary._aux_probe_active():raise BiliInputsBlocked('bili_source_av_probe_not_real_observation')
        if client is None or not callable(getattr(client,'with_options',None)):raise BiliInputsBlocked('bili_source_official_no_retry_client_unknown')
        client=client.with_options(max_retries=0)
        from .media_transport_runtime import bind_current_role_client_transport
        client=bind_current_role_client_transport(client,route,provenance['provider'],home,required_seconds=0)
        if getattr(client,'max_retries',None)!=0:raise BiliInputsBlocked('bili_source_official_no_retry_client_unknown')
        return client,model
    auxiliary._get_cached_client=no_retry_client
    def record(value):
        value=dict(value,task_job_id=guard['control_id'],authority_ref=guard['authority_ref'],source_context_ref=guard['source_context_ref'],
            route_source_refs={name:(_official_sdk_reference(inspect.getfile(fn))if name in {'official_runtime_resolver','official_client_factory'}else fingerprint(inspect.getfile(fn)))for name,fn in
                [('official_runtime_resolver',resolve_runtime_provider),('official_client_factory',original_cache),('project_route_guard',_current_role_vision_factory)]})
        ref=once(directory/('route-selection-'+str(len(selections)+1).zfill(3)+'.private.json'),value);selections.append((value,ref))
    auxiliary.resolve_vision_provider_client=_current_role_vision_factory(route,provenance['provider'],auxiliary,resolve_runtime_provider,record)
    auxiliary._aux_recovery_ladder=no_vision_recovery(auxiliary._aux_recovery_ladder)
    original_retry=auxiliary._should_retry_same_provider
    auxiliary._should_retry_same_provider=lambda task,*args,**kwargs:False if task=='vision'else original_retry(task,*args,**kwargs)
    return auxiliary,vision_tools,selections,route


def _response_value(response):
    if response is None or type(response)in(str,int,float,bool):return response
    if hasattr(response,'model_dump'):return _response_value(response.model_dump(mode='json'))
    if isinstance(response,types.SimpleNamespace):return _response_value(vars(response))
    if isinstance(response,dict):return {key:_response_value(value)for key,value in response.items()}
    if isinstance(response,(list,tuple)):return [_response_value(value)for value in response]
    raise BiliInputsBlocked('bili_source_official_response_not_archivable')


async def _observe_packets(guard,directory,materials,deadline):
    guard=dict(guard)
    auxiliary,vision_tools,selections,route=_source_child_route(guard,directory)
    from .mandatory_quality_context import _native_task_home
    home,current_route,provenance=_native_task_home(guard['control_id'])
    if home!=guard['home']or current_route!=route:raise BiliInputsBlocked('bili_source_current_role_home_changed')
    canonical_provider=provenance['provider']
    choice=_audio_transport_adapter_choice(route,canonical_provider)
    for index,material in enumerate(materials):
        # Reused captures are physical bytes only; old derived transport is never an admission.
        material=dict(material)
        for key in('transport_audio_ref','transport_audio_proof_ref','transport_video_ref','transport_video_proof_ref'):material.pop(key,None)
        material['audio_format']='wav'
        if choice['use_original_aac']:
            material=_prepare_original_audio_transport(material,Path(directory)/material['opaque_id'],deadline)
        material=_prepare_video_transport(material,Path(directory)/material['opaque_id'],deadline)
        materials[index]=material
        _verify_original_audio_transport(material)
    context=once(directory/'source-observation-context.private.json',{'version':'normal_bilibili_complete_observation_context_v1',
        'control_id':guard['control_id'],'authority_ref':guard['authority_ref'],'producer_source_ref':fingerprint(Path(__file__)),
        'current_role_route':route,'audio_transport_choice':choice,
        'inputs':[{k:v for k,v in material.items()if k not in('samples','audio_wire','video_wire')}for material in materials]})
    guard['source_context_ref']=context
    for material in materials:material['video_wire']=vision_tools._video_to_base64_data_url(Path(material.get('transport_video_ref',material['video_ref'])['path']))
    groups=grouped_complete_media_packets(materials,vision_tools._MAX_VIDEO_BASE64_BYTES)
    outputs={'video':[],'blind-audio':[]};evidence=[];prepared=[]
    # Every complete file and every packet is constructed/pinned before the first model request.
    for index,(name,identities,packet,maximum)in enumerate(groups,1):
        label=name+'-'+str(index).zfill(3);pin=once(directory/(label+'-request.private.json'),packet)
        prepared.append((label,name,identities,packet,pin,maximum))
    planned=sum(group[3]for group in groups)
    once(directory/'preflight.private.json',{'source_context_ref':context,
        'request_groups':[{'kind':name,'input_ids':ids,'request_ref':pin,'timeout_maximum':maximum}for label,name,ids,packet,pin,maximum in prepared],
        'sdk_single_video_data_URL_cap_bytes':vision_tools._MAX_VIDEO_BASE64_BYTES,
        'provider_aggregate_request_cap_bytes':None,
        'SDK_video_source_ref':_official_sdk_reference(Path(vision_tools.__file__)),
        'inputs':[{'opaque_id':m['opaque_id'],'video_duration_seconds':m['video_duration_seconds'],'audio_duration_seconds':m['duration_seconds'],
            'original_video_bytes':m['video_ref']['bytes'],'whole_audio_wire_bytes':m['audio_ref']['bytes'],'pcm_sha256':m['pcm_sha256']}for m in materials],
        'remaining_seconds':deadline-time.time(),'planned_SDK_calls':len(groups),'sum_timeout_maxima_seconds':planned,
        'physical_HTTP_count':None,'audio_body_limit_bytes':None,'batch_acceptance':'unknown_until_actual_response',
        'no_trimming_resampling_or_retry':not any(m.get('transport_video_ref')for m in materials),
        'full_duration_video_transport_refs':[m.get('transport_video_proof_ref')for m in materials]})
    if deadline-time.time()<planned:raise BiliInputsBlocked('bili_source_complete_group_requests_original_budget_insufficient')
    for label,name,identities,packet,pin,maximum in prepared:
        _native=__import__(__package__+'.mandatory_quality_context',fromlist=['_native_task_home'])
        if _native._native_task_home(guard['control_id'])[1]!=route:raise BiliInputsBlocked('bili_source_route_changed_before_effect')
        _verify_audio_transport_choice(choice,route,canonical_provider,current=True)
        before=len(selections);start=time.time()
        once(directory/(label+'-started.private.json'),{'task_job_id':guard['control_id'],'request_ref':pin,'started_at_unix':start,
            'deadline_unix':deadline,'route':route,'tools':[],'retry':False,'fallback':False,'complete_inputs':identities,'SDK_calls_started':1})
        response=await asyncio.wait_for(auxiliary.async_call_llm(task='vision',model=route['model'],messages=packet,tools=None,
            temperature=0,timeout=_remaining(deadline,maximum)),timeout=_remaining(deadline,maximum))
        actual=_response_value(response);response_ref=once(directory/(label+'-response.private.json'),actual)
        choices=actual.get('choices')or[];message=choices[0].get('message')if len(choices)==1 else None
        content=message.get('content')if isinstance(message,dict)else None
        if not isinstance(content,str)or not content.strip():raise BiliInputsBlocked('bili_source_no_actual_final_content_unknown_no_retry')
        records=selections[before:]
        if not records or any(v.get('route_verified')is not True or v.get('probe_only')is not False or v.get('state')!='configured_client'for v,r in records):raise BiliInputsBlocked('bili_source_actual_current_role_selection_required')
        outputs[name].extend(decode_observation_response(content,identities))
        usage=actual.get('usage');evidence.append({'request_ref':pin,'response_ref':response_ref,'kind':name,'input_ids':identities,'elapsed_seconds':time.time()-start,
            'route_selection_refs':[r for v,r in records],'source_context_ref':context,'usage_original':usage,'audio_tokens':(usage.get('prompt_tokens_details')or{}).get('audio_tokens')if isinstance(usage,dict)else None,
            'SDK_calls_started':1,'SDK_calls_completed':1,'HTTP_request_count':None,'native_session_id':None,
            'session_accounting':'official_auxiliary_without_invented_Session','automatic_replay':False})
    outputs=[outputs['video'],outputs['blind-audio']]
    return outputs,evidence


def observe_bilibili_sources_child(store,control,rows,directory,deadline,native_raw_refs=()):
    guard=current_guard(store,control)
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0'or deadline>guard['deadline_unix']:raise BiliInputsBlocked('bili_source_NoPub_original_deadline_required')
    directory=Path(directory)
    if not directory.is_relative_to(guard['scope'])or directory.exists():raise BiliInputsBlocked('bili_source_current_private_once_directory_required')
    directory.mkdir(mode=0o700);deadline=min(float(deadline),time.time()+900)
    once(directory/'started.private.json',{'version':'normal_bilibili_complete_source_observation_v1','control_id':control,'authority_ref':guard['authority_ref'],
        'native_content_ids':[r['content_id']for r in rows],'deadline_unix':deadline,'retry':False,'fallback':False,'NoPub':True})
    try:
        candidates=_select_complete_native_rows(rows,native_raw_refs,guard,directory)
        sdk=(Path(guard['home'])/'hermes-agent').resolve()
        if str(sdk)not in sys.path:sys.path.insert(0,str(sdk))
        from tools import vision_tools
        config=json.loads(private(PROJECT/'secrets/performance-collector.json'))['bilibili'];materials=[];rows=[];authors=set();decisions=[]
        for index,row in enumerate(candidates):
            if str(row['author_id'])in authors:continue
            try:
                reuse=_read_completed_prior_capture(row,guard)
                if reuse is None:_reject_prior_complete_download(row,guard)
                sub=directory/('clip-'+str(index+1).zfill(3));sub.mkdir(mode=0o700)
                material=_capture_complete_media(row,sub,config,deadline,reuse_material=reuse)
                if reuse is None:
                    snapshot=once(sub/'capture-producer-source.private.py',Path(__file__).read_bytes(),raw=True)
                    material['capture_complete_ref']=once(sub/'capture-complete.private.json',{'version':'normal_bilibili_complete_capture_v1',
                        'control_id':control,'authority_ref':guard['authority_ref'],'captured_at':datetime.now(timezone.utc).isoformat(),
                        'native_source_observed_at':row['observed_at'],'original_source_observed_at':row['observed_at'],
                        'original_effect_deadline_unix':deadline,'producer_snapshot_ref':snapshot,
                        'material':{k:v for k,v in material.items()if k not in('samples','audio_wire','audio_format')},'model_observation_reused':False})
            except BiliSourceExcluded as error:
                decisions.append({'content_id':row['content_id'],'state':'excluded_before_media_download','reason':str(error)})
                once(directory/('candidate-excluded-'+str(index+1).zfill(3)+'.private.json'),decisions[-1]);continue
            material.update(opaque_id='clip-'+str(index+1).zfill(3),native_content_id=row['content_id'],native_author_id=row['author_id'],
                metadata_raw_ref={'path':row['raw_response_path'],'sha256':row['raw_response_hash']})
            if any(not math.isfinite(material[k])or material[k]<=0 for k in('duration_seconds','video_duration_seconds')):raise BiliInputsBlocked('bili_source_actual_duration_unknown')
            # Exact byte length of the pinned SDK data URL, without retaining another full base64 copy.
            mime=vision_tools._detect_video_mime_type(Path(material['video_ref']['path']))or'video/mp4'
            wire_bytes=len('data:'+mime+';base64,')+4*((len(read_ref(material['video_ref']))+2)//3)
            if wire_bytes>vision_tools._MAX_VIDEO_BASE64_BYTES:
                decisions.append({'content_id':row['content_id'],'state':'excluded_after_complete_capture',
                    'reason':'bili_source_original_single_video_cap_exceeded','video_ref':material['video_ref'],
                    'audio_ref':material['audio_ref'],'native_scope_ref':material['native_scope_ref'],
                    'actual_video_data_URL_bytes':wire_bytes,'sdk_single_video_data_URL_cap_bytes':vision_tools._MAX_VIDEO_BASE64_BYTES,
                    'sdk_video_source_ref':{'path':str(Path(vision_tools.__file__).resolve()),'sha256':sha(Path(vision_tools.__file__).read_bytes())}})
                once(directory/('candidate-excluded-'+str(index+1).zfill(3)+'.private.json'),decisions[-1]);continue
            decisions.append({'content_id':row['content_id'],'state':'complete_native_single_video','native_scope_ref':material['native_scope_ref']})
            materials.append(material);rows.append(row);authors.add(str(row['author_id']))
            if len(materials)==3:break
        once(directory/'single-native-final-selection.private.json',{'control_id':control,'decisions':decisions,'selected_ids':[r['content_id']for r in rows]})
        if len(materials)!=3 or len(authors)!=3:raise BiliInputsBlocked('bili_source_three_distinct_fully_scoped_single_videos_required')
        outputs,evidence=asyncio.run(_observe_packets(guard,directory,materials,deadline));observations=[]
        from .hot_work_intelligence import analyze_work
        for row,material,video,audio in zip(rows,materials,*outputs):
            actual=validate_complete_observations(material,video,audio);text=actual['copy_or_script'];patterns=analyze_work('',text)
            current=dict(row,**actual);current.update(content_form='tutorial_video',writing_style={'observed_text':text,'patterns':patterns['copy_style']},
                content_structure={'observed_segments':video['segments'],'patterns':patterns['structure_types']},topic_direction={'observed_text':text},
                asset_analysis={'count':1,'kind':'complete_reference_video','source_ref':material['video_ref'],'licensed_for_generation':False},
                theme_template={'observed_text':text,'patterns':patterns['hook_types']},metadata_raw_ref={'path':row['raw_response_path'],'sha256':row['raw_response_hash']},
                source_observation={'control_id':control,'native_content_id':row['content_id'],'author_id':row['author_id'],'observed_at':datetime.now(timezone.utc).isoformat(),
                    'model_evidence':evidence,'complete_media':{k:v for k,v in material.items()if k not in('samples','video_wire','audio_wire')}})
            for field in('voiceover','motion_combination','transition_combination'):current[field]['status']='verified'
            # Metadata metrics retain their original capture time; watching never refreshes a native metric window.
            ref=once(directory/(material['opaque_id']+'-observed.private.json'),current);projected=dict(current,raw_snapshot_ref=ref,raw_response_hash=ref['sha256'],raw_response_path=ref['path'])
            observations.append(projected)
        current_guard(store,control)
        result={'version':'normal_bilibili_complete_source_observation_v1','control_id':control,'authority_ref':guard['authority_ref'],
            'items':observations,'requests':evidence,'deadline_unix':deadline,'completed_at':datetime.now(timezone.utc).isoformat(),'publication':False,'business_quality_passed':False}
        return once(directory/'completed.private.json',result)
    except BaseException as error:
        once(directory/'failed_or_unknown.private.json',{'control_id':control,'error_type':type(error).__name__,'error_sha256':sha(str(error).encode()),'automatic_replay':False});raise


def observe_bilibili_sources(store,guard,rows,directory,*,native_raw_refs=()):
    """Parent seam used by normal Source; all SDK modifications are in a fresh child."""
    if current_guard(store,guard['control_id'])['authority_ref']!=guard['authority_ref']:raise BiliInputsBlocked('bili_source_authority_changed')
    request=once(Path(directory).with_suffix('.request.private.json'),{'store':str(store.path),'control_id':guard['control_id'],
        'rows':rows,'native_raw_refs':list(native_raw_refs),'directory':str(directory),'deadline_unix':min(guard['deadline_unix'],time.time()+900),'module_ref':fingerprint(Path(__file__))})
    code="import sys;sys.path.insert(0,'/srv/ai-self-media-tools');from content_platform.bilibili_native_inputs import run_observation_child;run_observation_child(sys.argv[1])"
    timeout=_remaining(guard['deadline_unix'],900)
    result=subprocess.run([sys.executable,'-I','-B','-c',code,request['path']],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=timeout,check=False)
    once(Path(directory).with_suffix('.stdout.private.bin'),result.stdout,raw=True);once(Path(directory).with_suffix('.stderr.private.bin'),result.stderr,raw=True)
    if result.returncode:raise BiliInputsBlocked('bili_source_complete_observer_failed_or_unknown_inspect_only')
    ref=reference(Path(directory)/'completed.private.json');value=json.loads(read_ref(ref))
    if value.get('control_id')!=guard['control_id']or value.get('authority_ref')!=guard['authority_ref']or len(value.get('items')or[])!=3:raise BiliInputsBlocked('bili_source_complete_observer_scope_changed')
    return value,ref


def validate_source_observation_bundle(ref,guard):
    value=json.loads(read_ref(ref))
    if(value.get('version')!='normal_bilibili_complete_source_observation_v1'or value.get('control_id')!=guard['control_id']
            or value.get('authority_ref')!=guard['authority_ref']or time.time()>min(value['deadline_unix'],guard['deadline_unix'])
            or not Path(ref['path']).is_relative_to(guard['scope'])):raise BiliInputsBlocked('bili_source_complete_bundle_current_scope_required')
    items=value.get('items')or[]
    if len(items)!=3 or len({r['author_id']for r in items})!=3:raise BiliInputsBlocked('bili_source_complete_three_authors_changed')
    identities=[];videos=audios=None
    from .current_audio_review_runtime import _blind_wave
    from .mandatory_quality_context import _native_task_home
    from .quality_review_submission import _vision_endpoint_digest
    _,route,provenance=_native_task_home(guard['control_id']);endpoint=_vision_endpoint_digest(route.get('endpoint'))
    for row in items:
        original=json.loads(read_ref(row['raw_snapshot_ref']))
        if any(row.get(k)!=original.get(k)for k in('platform','source','content_id','author','author_id','canonical_url','published_at','observed_at','metrics',
                'copy_or_script','visual_evidence','voiceover','motion_combination','transition_combination')):raise BiliInputsBlocked('bili_source_complete_row_changed')
        captured=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00')).timestamp()
        if not 0<=time.time()-captured<=900:raise BiliInputsBlocked('bili_source_original_native_metrics_expired')
        evidence=row['source_observation'];material=evidence['complete_media'];identity=material['opaque_id'];identities.append(identity)
        if(evidence['control_id']!=guard['control_id']or evidence['native_content_id']!=row['content_id']or evidence['author_id']!=row['author_id']):raise BiliInputsBlocked('bili_source_complete_native_identity_changed')
        for pin in(material['video_ref'],material['audio_ref'],material['source_metadata_ref'],row['metadata_raw_ref']):read_ref(pin)
        binding=json.loads(read_ref(material['native_scope_ref']))
        if(binding.get('version')!='bilibili_official_single_video_scope_v1'
                or binding.get('proof_stage')!='same_official_extractor_metadata_before_media_download'
                or binding.get('actual_pagelist_ref')!=material['actual_pagelist_ref']
                or binding.get('original_search_metadata_ref')!=row['metadata_raw_ref']
                or not Path(material['native_scope_ref']['path']).is_relative_to(guard['scope'])
                or not Path(material['actual_pagelist_ref']['path']).is_relative_to(guard['scope'])):raise BiliInputsBlocked('bili_source_native_scope_binding_changed')
        _validate_download_identity(json.loads(read_ref(material['source_metadata_ref'])),row,binding)
        _check_extractor_pagelist(json.loads(read_ref(material['actual_pagelist_ref'])),binding)
        measurement,samples=_blind_wave(read_ref(material['audio_ref']))
        if(measurement['pcm_sha256']!=material['pcm_sha256']or measurement['frames']!=material['frames']or measurement['rate']!=material['sample_rate']or measurement['channels']!=material['channels']):raise BiliInputsBlocked('bili_source_complete_acoustic_identity_changed')
        if videos is None:
            requests=value['requests']
            if not 2<=len(requests)<=6:raise BiliInputsBlocked('bili_source_complete_request_groups_required')
            responses=[]
            for request in requests:
                read_ref(request['request_ref']);response=json.loads(read_ref(request['response_ref']));message=response['choices'][0]['message']
                context=json.loads(read_ref(request['source_context_ref']))
                if(context.get('control_id')!=guard['control_id']or context.get('authority_ref')!=guard['authority_ref']
                        or fingerprint(context['producer_source_ref']['path'])!=context['producer_source_ref']):raise BiliInputsBlocked('bili_source_observer_context_changed')
                if not isinstance(message.get('content'),str):raise BiliInputsBlocked('bili_source_actual_final_content_changed')
                if not request['route_selection_refs']:raise BiliInputsBlocked('bili_source_actual_route_selection_missing')
                for selection_ref in request['route_selection_refs']:
                    selection=json.loads(read_ref(selection_ref))
                    if(selection.get('task_job_id')!=guard['control_id']or selection.get('authority_ref')!=guard['authority_ref']
                            or selection.get('source_context_ref')!=request['source_context_ref']
                            or selection.get('route_verified')is not True or selection.get('probe_only')is not False or selection.get('state')!='configured_client'
                            or selection.get('selected_provider')!=provenance['provider']or selection.get('selected_model')!=route['model']
                            or any(selection.get(name)!=route[key]for name,key in(('role_provider','provider'),('role_model','model'),('api_mode','api_mode')))
                            or selection.get('role_endpoint_sha256')!=endpoint or(endpoint is not None and selection.get('client_endpoint_sha256')!=endpoint)):
                        raise BiliInputsBlocked('bili_source_actual_current_route_changed')
                    for source_ref in selection['route_source_refs'].values():
                        if fingerprint(source_ref['path'])!=source_ref:raise BiliInputsBlocked('bili_source_observer_dependency_changed')
                responses.append(message['content'])
            ids=[r['source_observation']['complete_media']['opaque_id']for r in items]
            videos,audios=_decode_complete_request_groups(requests,[r['source_observation']['complete_media']for r in items])
        index=len(identities)-1;recomputed=validate_complete_observations(dict(material,samples=samples),videos[index],audios[index])
        for field in('copy_or_script','visual_evidence','voiceover','motion_combination','transition_combination'):
            left=copy.deepcopy(row[field]);right=copy.deepcopy(recomputed[field])
            if field in('voiceover','motion_combination','transition_combination'):left.pop('status',None)
            if left!=right:raise BiliInputsBlocked('bili_source_full_observation_recomputation_changed')
    return value


def run_observation_child(request_path):
    request=json.loads(private(request_path))
    if fingerprint(Path(__file__))!=request['module_ref']:raise BiliInputsBlocked('bili_source_observer_code_changed')
    from .store import Store
    store=object.__new__(Store);store.path=Path(request['store']) # no constructor/migration during source observation
    observe_bilibili_sources_child(store,request['control_id'],request['rows'],request['directory'],request['deadline_unix'],request.get('native_raw_refs',()))
