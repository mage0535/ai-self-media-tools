"""Typed Mastodon originals for owned analytics and public research; no network or publisher."""
import hashlib,json,os,re,stat
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qs,urlencode

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(value).hexdigest()
def _object(raw):
    def pairs(values):
        result={}
        for k,v in values:
            if k in result:raise ValueError('mastodon_duplicate_JSON_key')
            result[k]=v
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in()).throw(ValueError('mastodon_invalid_number')))
def _origin(value):
    u=urlsplit(str(value))
    if (u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in(None,443)
            or u.query or u.fragment or u.path not in('','/')):
        raise ValueError('mastodon_HTTPS_instance_origin_required')
    return 'https://'+u.netloc.casefold().removesuffix(':443')
def _private(path,expected=None,limit=8*1024*1024):
    p=Path(path)
    if not p.is_absolute()or '..'in p.parts or any(q.is_symlink()for q in(p,*p.parents)):raise PermissionError('mastodon_Root_private_original_path_required')
    i=p.stat()
    if(not stat.S_ISREG(i.st_mode)or i.st_uid!=0 or i.st_mode&0o777!=0o600 or i.st_nlink!=1 or not 0<i.st_size<=limit):raise PermissionError('mastodon_Root600_bounded_original_required')
    raw=p.read_bytes();end=p.stat()
    if((i.st_dev,i.st_ino,i.st_size,i.st_mtime_ns)!=(end.st_dev,end.st_ino,end.st_size,end.st_mtime_ns)
            or(expected is not None and digest(raw)!=expected)):raise ValueError('mastodon_original_bytes_changed')
    return raw
def _time(value):
    t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('mastodon_native_aware_timestamp_required')
    return t
def _metric(value):return value if type(value)is int and value>=0 else None
def _id(value):return isinstance(value,str)and value.isascii()and value.isdigit()and 0<len(value)<=64 and int(value)>0
class _Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):self.parts.append(data)
    def handle_starttag(self,tag,attrs):
        if tag in{'p','div','br','li'}:self.parts.append('\n')
        if tag=='img':
            alt=dict(attrs).get('alt')
            if alt:self.parts.append(alt)
    def handle_endtag(self,tag):
        if tag in{'p','div','li'}:self.parts.append('\n')
def plain_text(value):
    p=_Text();p.feed(value);p.close()
    return '\n'.join(line.strip()for line in ''.join(p.parts).splitlines()if line.strip())

def normalize_mastodon_statuses(raw,*,response_url,http_status,observed_at,raw_path,exclude_account_ids=()):
    u=urlsplit(response_url)
    if(u.scheme!='https'or not u.hostname or u.username or u.password or u.port not in(None,443)
            or u.fragment or u.path not in{'/api/v1/trends/statuses','/api/v1/timelines/public','/api/v2/search'}):
        raise ValueError('mastodon_official_public_endpoint_required')
    if http_status!=200:raise ValueError('mastodon_native_HTTP_not_success')
    observed=_time(observed_at);rows=_object(raw)
    search_parameters=None
    if u.path=='/api/v2/search':
        search_parameters=parse_qs(u.query,keep_blank_values=True,strict_parsing=True)
        if (set(search_parameters)!={'q','type','resolve','limit'}or any(len(v)!=1 for v in search_parameters.values())
                or search_parameters['type']!=['statuses']or search_parameters['resolve']!=['false']
                or not search_parameters['q'][0].strip()or len(search_parameters['q'][0])>200
                or not search_parameters['limit'][0].isdigit()or not 1<=int(search_parameters['limit'][0])<=40):
            raise ValueError('mastodon_directed_status_search_exact_parameters_required')
        if not isinstance(rows,dict)or not isinstance(rows.get('statuses'),list):raise ValueError('mastodon_official_search_status_array_required')
        rows=rows['statuses']
        if len(rows)>int(search_parameters['limit'][0]):raise ValueError('mastodon_search_returned_over_requested_limit')
    if not isinstance(rows,list)or len(rows)>40:raise ValueError('mastodon_native_status_array_max40_required')
    excluded=set(map(str,exclude_account_ids));seen={};items=[];rejected=[]
    for row in rows:
        if not isinstance(row,dict)or not _id(row.get('id')):raise ValueError('mastodon_native_status_id_required')
        rid=row['id'];encoded=canonical(row)
        if rid in seen:
            if seen[rid]!=encoded:raise ValueError('mastodon_duplicate_native_id_content_changed')
            continue
        seen[rid]=encoded;account=row.get('account')or{}
        if row.get('reblog')is not None or row.get('visibility')!='public':
            rejected.append({'native_id':rid,'reason':'not_original_public_status'});continue
        if str(account.get('id'))in excluded:
            rejected.append({'native_id':rid,'reason':'own_account_not_external_research'});continue
        if not _id(account.get('id'))or not isinstance(account.get('acct'),str)or not account['acct']:
            rejected.append({'native_id':rid,'reason':'native_author_missing'});continue
        published=_time(row.get('created_at'))
        if published>observed:raise ValueError('mastodon_publish_after_observation')
        body=row.get('content');text=plain_text(body)if isinstance(body,str)else''
        uri=row.get('url')or row.get('uri');parsed=urlsplit(str(uri))
        author_url=urlsplit(str(account.get('url')or''))
        if (not text or parsed.scheme!='https'or not parsed.hostname or parsed.username or parsed.password
                or author_url.scheme!='https'or not author_url.hostname or author_url.username or author_url.password):
            rejected.append({'native_id':rid,'reason':'native_full_body_or_public_URL_missing'});continue
        native={k:_metric(row.get(k))for k in('favourites_count','reblogs_count','replies_count')}
        metrics={'likes':native['favourites_count'],'shares':native['reblogs_count'],'comments':native['replies_count']}
        items.append({'platform':'mastodon','source':'native.mastodon_rest','observer_instance':'https://'+u.netloc,
            'content_id':rid,'canonical_url':uri,'uri':row.get('uri'),'author':account['acct'],'author_id':account['id'],
            'author_canonical_url':account['url'],'title':text,'body_html':body,'body':text,'published_at':row['created_at'],
            'observed_at':observed_at,'visibility':row['visibility'],'language':row.get('language'),
            'sensitive':row.get('sensitive'),'spoiler_text':row.get('spoiler_text'),'native_metrics':native,'metrics':metrics,
            'metric_window':'native_lifetime_counters_observed_at_capture','missing_metrics':[k for k,v in metrics.items()if v is None],
            'unprovided_metrics':['views','impressions','saves','CTR','watchtime','completion','conversion','revenue'],
            'raw_response_path':str(raw_path),'raw_response_hash':digest(raw),'official_api_path':u.path,
            'media_attachments':row.get('media_attachments')or[],
            'rights':{'use':'analysis_only_no_republish','asset_reuse_authorized':False},
            'trending_endpoint_observed':u.path=='/api/v1/trends/statuses','viral_qualified':False,'learning_eligible':False})
        if search_parameters is not None:items[-1]['native_search_query']=search_parameters['q'][0]
    result={'schema':'mastodon_native_public_status_observations_v1','platform':'mastodon',
        'source_family':'mastodon','observed_at':observed_at,'source_scope':u.path,'raw_count':len(rows),
        'items':items,'rejected':rejected,'sample_qualification':'must_pass_existing_Source_and_same_lane_gates',
        'independent_source_count':1,'model_calls':0,'publish_calls':0}
    if search_parameters is not None:result['native_search_parameters']={k:v[0]for k,v in search_parameters.items()}
    return result

def read_owned_mastodon_binding(binding,runtime):
    config=binding.get('config')or{};alias=binding.get('account_key')
    credential=(runtime.get('credentials')or{}).get(alias)or{}
    instance=_origin(config.get('instance'));actual=_origin(credential.get('instance')if '://'in str(credential.get('instance'))else'https://'+str(credential.get('instance')))
    key=credential.get('token')
    if(binding.get('platform')!='mastodon'or alias not in(runtime.get('unified_accounts')or[])or actual!=instance
            or binding.get('credentials_ref')!='/etc/hermes/channel-cycle-runtime.json#credentials.'+str(alias)
            or config.get('internal_account_alias')!=alias or not _id(config.get('account_id'))
            or config.get('identity_source')!='native_accounts_verify_credentials'or not isinstance(key,str)or not key):
        raise PermissionError('mastodon_same_registered_account_binding_required')
    ref=config.get('native_account_snapshot_ref')or{}
    if set(ref)!={'path','sha256'}:raise PermissionError('mastodon_original_owned_snapshot_reference_required')
    saved=_object(_private(ref['path'],ref['sha256']))
    rawref=saved.get('identity_raw_ref')or{}
    raw=_private(rawref['path'],rawref['sha256']);who=_object(raw)
    capture=Path(rawref['path'])
    if capture.name!='00.response.body.private.raw':raise PermissionError('mastodon_original_capture_name_required')
    metadata=_object(_private(capture.with_name('00.response.metadata.private.json')))
    started=_object(_private(capture.with_name('started.private.json')))
    endpoint=instance+'/api/v1/accounts/verify_credentials'
    if(metadata.get('method')!='GET'or metadata.get('status')!=200 or metadata.get('url')!=endpoint
            or metadata.get('actual_url')!=endpoint or metadata.get('raw_ref')!=rawref
            or started.get('original_key_sha256')!=digest(key.encode())
            or started.get('runtime_sha256')!=saved.get('source_runtime_sha256')
            or saved.get('schema')!='mastodon_original_native_identity_v1' or saved.get('platform')!='mastodon'
            or saved.get('registered_operating_object')!=alias or saved.get('internal_account_alias')!=alias
            or saved.get('native_account_id')!=who.get('id')or who.get('id')!=config['account_id']
            or any(saved.get(k)!=who.get(k)for k in('username','acct'))
            or saved.get('canonical_url')!=who.get('url')or saved.get('observed_at')!=metadata.get('captured_at')):
        raise ValueError('mastodon_original_native_identity_or_credential_changed')
    _time(saved['observed_at'])
    if urlsplit(who['url']).scheme!='https'or urlsplit(who['url']).netloc!=urlsplit(instance).netloc:
        raise ValueError('mastodon_owned_profile_wrong_instance')
    native={k:_metric(who.get(k))for k in('followers_count','following_count','statuses_count')}
    if native!=saved.get('native_metrics'):raise ValueError('mastodon_owned_metrics_not_original_native_values')
    metrics={'followers':native['followers_count'],'following':native['following_count'],'posts':native['statuses_count']}
    return {'status':'backend_signal','platform':'mastodon','account_id':who['id'],'internal_account_alias':alias,
        'instance':instance,'profile_url':who['url'],'account_metrics':metrics,'native_metrics':native,'observed_at':saved['observed_at'],
        'source':'native.mastodon_accounts_verify_credentials','raw_ref':rawref,'snapshot_ref':ref,
        'missing_metrics':[k for k,v in metrics.items()if v is None],
        'unprovided_metrics':saved.get('unprovided_account_metrics')or[],
        'observation_scope':'original cumulative snapshot; capture time unchanged; no current freshness claim',
        'binding_enabled':binding.get('enabled'),'generation_authorized_by_analytics_binding':False,
        'learning_eligible':False,'collector_HTTP_calls':0}

# Reuse the tested Mastodon normalizer and owned-proof reader; expose its already-verified profile URL for exclusion.
import copy,time,sqlite3,sys,math
from contextlib import contextmanager

PROJECT=Path('/srv/ai-self-media-tools')

def _blocked(reason, **details):
    from .task_source_inputs import SourceInputsBlocked
    raise SourceInputsBlocked(reason,details)

def _json_ref(ref):
    if not isinstance(ref,dict)or not re.fullmatch('[a-f0-9]{64}',str(ref.get('sha256')or'')):
        _blocked('unified_original_pinned_reference_required')
    raw=_private(ref.get('path',''),ref['sha256'])
    if 'bytes'in ref and(type(ref['bytes'])is not int or ref['bytes']!=len(raw)):_blocked('unified_original_ref_size_changed')
    return _object(raw)

def _readonly_store(path=None):
    from .store import Store
    store=object.__new__(Store);store.path=Path(path or PROJECT/'data/state.db')
    @contextmanager
    def read():
        c=sqlite3.connect(store.path.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('PRAGMA temp_store=MEMORY')
        try:yield c
        finally:c.close()
    store.connect=read
    return store

def _binding(store,alias):
    with store.connect()as c:
        row=c.execute('SELECT *FROM platform_accounts WHERE platform=?AND account_key=?',('mastodon',alias)).fetchone()
    if row is None:_blocked('unified_original_native_account_not_verified',account=alias)
    result=dict(row);result['config']=json.loads(result['config_json']);return result

def _dependencies(runtime):
    deps=runtime.get('normal_release_dependencies')or{}
    module=Path(__file__).resolve()
    if not isinstance(deps,dict)or deps.get(str(module))!=digest(module.read_bytes()):
        _blocked('unified_adapter_source_not_registered')
    for name,sha in deps.items():
        q=Path(name)
        if not q.is_absolute()or any(x.is_symlink()for x in[q,*q.parents])or not q.is_file()or digest(q.read_bytes())!=sha:
            _blocked('unified_current_source_dependency_changed',path=name)

def _registered_input(runtime,alias):
    item=(runtime.get('normal_unified_sources')or{}).get(alias)
    if(not isinstance(item,dict)or set(item) not in ({'platform','language','content_form','lane','fresh_source'},{'platform','language','content_form','lane','fresh_source','directed_search'})
        or item.get('platform')!='mastodon'or item.get('fresh_source')!='mastodon_official_current_v1'
        or any(not isinstance(item.get(k),str)or not item[k]for k in('language','content_form','lane'))):
        _blocked('unified_current_automatic_native_source_registration_missing',account=alias)
    return item

def _directed_search_specs(registration,owned):
    if 'directed_search'not in registration:return []
    configured=registration['directed_search']
    if(not isinstance(configured,dict)or set(configured)!={'queries','limit','budget_seconds'}
            or type(configured['limit'])is not int or not 1<=configured['limit']<=40
            or type(configured['budget_seconds'])is not int or configured['budget_seconds']!=45
            or not isinstance(configured['queries'],list)or not 1<=len(configured['queries'])<=3
            or any(not isinstance(q,str)or not q.strip()or len(q)>200 for q in configured['queries'])
            or len(set(configured['queries']))!=len(configured['queries'])):
        _blocked('unified_directed_Root_registered_query_contract_required')
    _origin(owned['instance'])
    return [{'query':query,'endpoint_path':'/api/v2/search?'+urlencode(
        {'q':query,'type':'statuses','resolve':'false','limit':configured['limit']})}for query in configured['queries']]


def _directed_search_budget(deadline):
    import contextlib,signal
    @contextlib.contextmanager
    def bounded():
        remaining=deadline-time.time()
        if remaining<=0:_blocked('unified_directed_original_budget_exhausted')
        if not hasattr(signal,'setitimer')or signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):
            _blocked('unified_directed_original_hard_budget_not_available')
        previous=signal.getsignal(signal.SIGALRM)
        def expired(*args):raise TimeoutError('unified_directed_original45s_exhausted')
        signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,remaining)
        try:yield
        finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
    return bounded()


def _directed_work_observations(rows):
    # Preserve original pages order: trends first, then the original query order.
    # Counts are observations at different times, never sums or retroactive edits.
    by_uri={};result=[]
    immutable=('content_id','canonical_url','uri','author','author_id','author_canonical_url','title','body_html','published_at','language','media_attachments','sensitive','spoiler_text')
    for row in rows:
        uri=row.get('uri')or row['canonical_url'];current=by_uri.get(uri)
        if current is None:
            current=copy.deepcopy(row);current['native_observations']=[]
            current['native_observation_selection']='original_pages_order_first_observation_no_metric_sum'
            by_uri[uri]=current;result.append(current)
        elif any(current.get(key)!=row.get(key)for key in immutable):
            _blocked('unified_directed_same_work_immutable_native_facts_conflict')
        observation=copy.deepcopy(row)
        observation.pop('native_observations',None);observation.pop('native_observation_selection',None)
        if observation not in current['native_observations']:current['native_observations'].append(observation)
    return result


def _research(runtime,alias,owned,registration,*,reader=None):
    from .real_world_ai_policy import classify_discovery_text
    read=reader or _json_ref;rows=[];pages=[];by_uri={};ids={}
    for entry in registration['research_pages']:
        if not isinstance(entry,dict)or set(entry)!={'raw_ref','metadata_ref'}:_blocked('unified_original_research_page_refs_required')
        meta=read(entry['metadata_ref']);raw=_private(entry['raw_ref']['path'],entry['raw_ref']['sha256'])
        if (meta.get('method')!='GET'or meta.get('status')!=200 or meta.get('requested_url')!=meta.get('actual_url')
                or meta.get('raw_ref')!=entry['raw_ref']or meta.get('received_body_complete_under_limit')is not True
                or('bytes'in entry['raw_ref']and entry['raw_ref']['bytes']!=len(raw))or urlsplit(str(meta.get('requested_url')or'')).netloc!=urlsplit(owned['instance']).netloc):
            _blocked('unified_same_registered_instance_original_response_required')
        observed=meta.get('observed_at');normalized=normalize_mastodon_statuses(raw,response_url=meta['requested_url'],http_status=meta['status'],
            observed_at=observed,raw_path=entry['raw_ref']['path'],exclude_account_ids=[owned['account_id']])
        pages.append({'raw_ref':entry['raw_ref'],'metadata_ref':entry['metadata_ref'],'observed_at':observed,'response_url':meta['requested_url'],
            'raw_count':normalized['raw_count'],'source_family':normalized['source_family']})
        for item in normalized['items']:
            # An ActivityPub URI/canonical URL is the cross-instance dedup key; no handle matching.
            uri=item.get('uri')or item['canonical_url']
            if item['author_canonical_url']==(owned.get('profile_url')or''):_blocked('unified_owned_account_not_external_research')
            if item['content_id']in ids and ids[item['content_id']]!=uri:_blocked('unified_observer_local_ID_collision_requires_reconciliation')
            ids[item['content_id']]=uri
            if 'directed_search'in registration:
                item=copy.deepcopy(item);item['native_mastodon_capture_ref']=entry['metadata_ref'];rows.append(item);continue
            facts={k:item.get(k)for k in('canonical_url','uri','author_id','author_canonical_url','title','body_html','published_at','native_metrics')}
            if uri in by_uri:
                if by_uri[uri]!=facts:_blocked('unified_same_native_URI_conflicting_original_facts')
                continue
            by_uri[uri]=facts;item=copy.deepcopy(item);item['native_mastodon_capture_ref']=entry['metadata_ref'];rows.append(item)
    if 'directed_search'in registration:rows=_directed_work_observations(rows)
    decisions=[classify_discovery_text(row['title'])for row in rows]
    reasons={}
    for decision in decisions:
        if decision.get('accepted')is not True:
            code=decision.get('reason')or decision.get('reason_code')or'canonical_rejected';reasons[code]=reasons.get(code,0)+1
    return {'rows':rows,'pages':pages,'raw_total':sum(p['raw_count']for p in pages),'unique_originals':len(rows),
        'distinct_authors':len({r['author_canonical_url']for r in rows}),
        'strong_accepted':sum(d.get('accepted')is True for d in decisions),'canonical_reject_reasons':reasons,
        'source_family_count':len({p['source_family']for p in pages}),'decisions':decisions}

def inspect_unified_mastodon_account(store,runtime,alias,roster_entry,*,context_loader=None,capture_ref=None,guard=None,require_fresh=True):
    if alias not in runtime.get('unified_accounts',[])or not isinstance(roster_entry,dict)or roster_entry.get('enabled')is not True or roster_entry.get('pipeline')!='direct':
        _blocked('unified_original_registered_native_object_required',account=alias)
    if roster_entry.get('type')!='mastodon':_blocked('unified_platform_native_Source_adapter_not_implemented',account=alias,platform=roster_entry.get('type'))
    registration=_registered_input(runtime,alias);binding=_binding(store,alias);owned=read_owned_mastodon_binding(binding,runtime)
    from .run_contract import build_run_contract,validate_run_contract
    from .pipeline import load_platform_workflow_context
    contract=build_run_contract('mastodon')
    if not validate_run_contract(contract).get('passed'):_blocked('unified_current_complete_rule_contract_invalid')
    lane=(contract.get('channel_rules')or{}).get('lane')
    if registration['content_form']not in(contract.get('channel_rules')or{}).get('primary_types',[]):_blocked('unified_current_platform_declared_content_form_required')
    if lane!=registration['lane']:_blocked('unified_original_account_direction_current_contract_mismatch')
    plan={'run_contract':contract,'account_id':alias,'internal_account_alias':alias,'native_account_id':owned['account_id'],
        'language':registration['language'],'content_form':registration['content_form'],'lane':lane,'account_lane':lane}
    context=(context_loader or load_platform_workflow_context)('mastodon',plan=plan)
    if(context.get('loaded')is not True or(context.get('content_quality_reference_gate')or{}).get('passed')is not True
        or((context.get('strategy')or{}).get('compiled_gate')or{}).get('passed')is not True):
        _blocked('unified_current_complete_platform_rules_or_strategy_not_loaded')
    base={'binding':{'platform':'mastodon','account_id':owned['account_id'],'internal_account_alias':alias,
        'lane':lane,'language':registration['language'],'content_form':registration['content_form']},'account_binding':binding,
        'owned':owned,'registration':registration,'context':context}
    if capture_ref is None:return dict(base,ready=False,reasons=['unified_current_automatic_capture_not_yet_obtained'],research=None)
    fresh=_read_fresh_capture(capture_ref,guard,runtime,alias,binding,registration,owned,require_fresh=require_fresh)
    research=_research(runtime,alias,fresh['owned'],dict(registration,research_pages=fresh['research_pages']));reasons=[]
    # Literal discovery words are diagnostics, never a substitute for the existing native semantic review.
    # This readiness is complete Source input readiness only; selection still requires three qualified references.
    if not research['rows']:reasons.append('unified_complete_native_source_pool_missing')
    return dict(base,owned=fresh['owned'],research=research,ready=not reasons,reasons=reasons,
        generation_ready=False,semantic_review_required=True,fresh_capture_ref=capture_ref)

def _current_configuration(native):
    from .native_quality_runner import current_active_role
    from .cli import load_config
    home,task,route=current_active_role(0)
    if task!=native.runtime.get('normal_control_task_id')or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':
        _blocked('unified_current_official_role_or_NoPub_mismatch')
    native.normal_deadline();config=load_config(PROJECT/'config.json',PROJECT/'data/state.db')
    config.setdefault('generator',{}).update(provider='hermes-cli',hermes_command='/srv/hermes-agent/.venv/bin/hermes',
        hermes_provider=route['provider'],hermes_model=route['model'],allow_fallback=False)
    config.setdefault('delivery',{})['auto_stage_review_required']=False
    return config,home,task,route

def run_unified_normal_generation(native,ns):
    roster=ns.get('CHANNEL_ROSTER');accounts=native.runtime.get('unified_accounts')
    if not isinstance(roster,dict)or not isinstance(accounts,list)or len(accounts)!=len(set(accounts))or any(a not in roster or a not in native.payload['accounts']for a in accounts):
        raise ValueError('unified_original_signed_roster_changed')
    native._normal_account_specs={key:dict(value,platform=value.get('platform')or value.get('type'))for key,value in roster.items()if isinstance(value,dict)}
    try:_dependencies(native.runtime)
    except (ValueError,PermissionError,OSError)as exc:
        for alias in accounts:native.block_account(alias,'unified_source_dependencies:'+str(exc)[:180])
        return
    store=_readonly_store()
    for alias in accounts:
        if alias in native.blocked_accounts:continue
        if native.journal.held_account(alias):native.block_account(alias,'unified_historical_unknown_query_only_no_replay');continue
        try:
            checked=inspect_unified_mastodon_account(store,native.runtime,alias,roster[alias])
            config,home,task,route=_current_configuration(native)
            capture_ref=ensure_fresh_unified_source(store,config,native.payload,checked)
            from .task_source_inputs import _normal_cycle_source_guard
            source_guard=_normal_cycle_source_guard(store,payload=native.payload)
            checked=inspect_unified_mastodon_account(store,native.runtime,alias,roster[alias],capture_ref=capture_ref,guard=source_guard)
            if not checked['ready']:
                native.block_account(alias,'unified_normal_preflight:'+json.dumps({'reasons':checked['reasons'],
                    'strong_accepted':checked['research']['strong_accepted'],'unique_originals':checked['research']['unique_originals'],
                    'source_family_count':checked['research']['source_family_count']},ensure_ascii=False,sort_keys=True));continue
            selection=select_unified_mastodon_topic(store,config,native.payload,checked)
            from .pipeline import Pipeline
            from .store import Store
            pipeline=Pipeline(Store(PROJECT/'data/state.db'),copy.deepcopy(config))
            spec=dict(roster[alias],id=alias,platform='mastodon',lang=checked['binding']['language'])
            result=native.prepare_normal_candidate(spec,selection['topic'],pipeline,
                account_reader=lambda _:checked['binding'],source_selection=selection)
            if result.get('passed')is not True:native.block_account(alias,'unified_normal_generation:'+str(result.get('reason')))
        except (OSError,ValueError,PermissionError,RuntimeError,KeyError,TypeError,ImportError)as exc:
            native.block_account(alias,'unified_normal_blocked:'+str(exc)[:500])

def _scope_ref(ref,scope):
    p=Path(ref.get('path')or'')
    if not p.is_relative_to(scope):_blocked('unified_original_evidence_outside_current_control_scope')
    return _json_ref(ref)

def mastodon_candidate_pool(topics,bundle):
    pool=[];by_id={}
    for entry in topics:
        row=entry['selected_candidate'];identity=row['content_id']
        if row.get('platform')!='mastodon'or row.get('source')!='mastodon:native_rest':_blocked('unified_ranked_topic_must_be_original_Mastodon_REST')
        if identity in by_id:_blocked('unified_duplicate_ranked_native_identity')
        current=dict(entry,topic_candidate=True,provenance=[]);pool.append(current);by_id[identity]=current
    for origin,rows in(('query',bundle['trends']['items']),('public',bundle['public'].get('items')or[])):
        for row in rows:
            if row.get('platform')!='mastodon'or row.get('source')!='mastodon:native_rest':continue
            identity=row.get('content_id')
            if not _id(identity):_blocked('unified_original_native_identity_required')
            current=by_id.get(identity)
            if current is None:
                current={'selected_candidate':row,'topic_candidate':False,'provenance':[]};pool.append(current);by_id[identity]=current
            if any(current['selected_candidate'].get(k)!=row.get(k)for k in('title','author','author_id','canonical_url','uri','metrics')):
                _blocked('unified_same_native_identity_full_facts_changed')
            proof={'pool':origin,'original_candidate':row}
            if proof not in current['provenance']:current['provenance'].append(proof)
    for entry in pool:
        if not entry['provenance']or(entry['topic_candidate']and not any(v['pool']=='query'for v in entry['provenance'])):
            _blocked('unified_ranked_topic_not_original_current_source')
    return pool

def mastodon_selected_raw(selected,scope):
    ref={'path':selected['raw_response_path'],'sha256':selected['raw_response_hash']}
    body=_scope_ref(ref,scope);meta=_scope_ref(selected['native_mastodon_capture_ref'],scope)
    if(meta.get('raw_ref')!=ref or meta.get('method')!='GET'or meta.get('status')!=200 or meta.get('requested_url')!=meta.get('actual_url')
            or meta.get('observed_at')!=selected.get('observed_at')):_blocked('unified_original_native_response_receipt_changed')
    original_meta=_json_ref(meta['original_response_metadata_ref']);expected_meta=dict(original_meta,raw_ref=ref,original_response_metadata_ref=meta['original_response_metadata_ref'])
    if(meta!=expected_meta or original_meta.get('raw_ref',{}).get('sha256')!=ref['sha256']or original_meta.get('received_body_complete_under_limit')is not True):_blocked('unified_copied_native_receipt_not_original_metadata')
    raw=_private(ref['path'],ref['sha256']);normalized=normalize_mastodon_statuses(raw,response_url=meta['requested_url'],http_status=200,
        observed_at=meta['observed_at'],raw_path=ref['path'])
    found=[row for row in normalized['items']if row['content_id']==selected.get('content_id')]
    if len(found)!=1:_blocked('unified_original_native_status_not_unique')
    original=found[0]
    for key in original:
        if key=='source':
            if selected.get(key)!='mastodon:native_rest'or selected.get('native_source_label')!=original[key]:_blocked('unified_native_label_projection_changed')
        elif selected.get(key)!=original[key]:_blocked('unified_original_native_full_metadata_changed',field=key)
    originals=body.get('statuses')if isinstance(body,dict)else body
    exact=[row for row in originals if row.get('id')==selected['content_id']]
    if len(exact)!=1:_blocked('unified_original_native_status_conflict')
    return {'raw_ref':ref,'content_id':selected['content_id'],'exact_native_status':exact[0],
        'exact_source_text':original['title'],'use':'external_observation_for_topic_analysis_not_own_business_outcome'}

def mastodon_native_pool(pool,scope):
    result=[]
    from .task_source_inputs import _normal_actual_candidate_freshness
    for entry in pool:
        current=dict(entry);selected=entry['selected_candidate'];source=mastodon_selected_raw(selected,scope)
        for row in [selected]+[v['original_candidate']for v in entry['provenance']]:
            observations=row.get('native_observations')
            if observations is not None or 'native_observation_selection'in row:
                if not isinstance(observations,list)or not observations:_blocked('unified_directed_original_observations_required')
                rebuilt=_directed_work_observations(observations)
                if len(rebuilt)!=1 or any(row.get(k)!=v for k,v in rebuilt[0].items()):
                    _blocked('unified_directed_ranking_not_original_first_observation')
            else:observations=[row]
            for observation in observations:
                mastodon_selected_raw(observation,scope);_normal_actual_candidate_freshness(observation)
        meta=_scope_ref(selected['native_mastodon_capture_ref'],scope)
        native=source['exact_native_status'];media=native.get('media_attachments')
        types=[v.get('type')for v in media]if isinstance(media,list)and all(isinstance(v,dict)for v in media)else None
        form=None
        if types is not None and all(t in{'image','video','gifv','audio'}for t in types):
            form=('text_post'if not types else'image_text'if set(types)=={'image'}else
                'native_video'if set(types)<={'video','gifv'}else'native_audio'if set(types)=={'audio'}else'native_mixed_media')
        hot=form is not None and any(type(v)is int and v>0 for v in selected['metrics'].values())
        current['source']=source;current['native_heat_evidence']={
            'status':'native_mastodon_cumulative_metric_candidate'if hot else'unknown','topic_support':'supported'if hot else'unknown',
            'platform':'mastodon','heat_contract':'native_mastodon_metrics_plus_attributed_finite_cohort',
            'content_id':selected['content_id'],'raw_ref':source['raw_ref'],'native_capture_ref':selected['native_mastodon_capture_ref'],
            'native_selection_parameters':{'official_api_path':urlsplit(meta['requested_url']).path,'query':urlsplit(meta['requested_url']).query},
            'metrics':copy.deepcopy(selected['metrics']),'published_at':selected['published_at'],'observed_at':selected['observed_at'],
            'language':selected.get('language'),'native_form':form,'native_media_types':types,'publication_window_utc':_time(selected['published_at']).astimezone(timezone.utc).date().isoformat(),
            'metric_scope':'lifetime_count_at_capture_not_24h_increment','baseline_maturity':'unknown','verified_viral_effect':False,
            'reason':'official_original_cumulative_metrics_require_semantic_same_lane_and_strict_peer_comparison_not_Top_or_viral_effect'if hot else'native_attention_metrics_or_observed_media_form_missing'}
        result.append(current)
    return result

def _load_runtime():
    return _object(_private('/etc/hermes/channel-cycle-runtime.json'))

def _current_checked(store,alias,*,require_ready=True,guard=None,capture_ref=None):
    runtime=_load_runtime()
    if guard is None:_blocked('unified_current_capture_original_guard_required')
    if capture_ref is None:capture_ref=_fresh_completed_ref(guard,alias)
    checked=inspect_unified_mastodon_account(store,runtime,alias,_original_roster(runtime).get(alias),
        capture_ref=capture_ref,guard=guard,require_fresh=require_ready)
    if require_ready and not checked['ready']:_blocked('unified_current_native_Source_not_ready',reasons=checked['reasons'])
    return checked

def _collect_mastodon_inputs(store,config,payload,checked):
    from . import task_source_inputs as src
    guard=src._normal_cycle_source_guard(store,payload=payload)
    alias=checked['binding']['internal_account_alias']
    if alias not in guard['payload']['accounts']:_blocked('unified_account_not_in_original_signed_payload')
    # Re-read exact authenticated identity, complete rules, and original response facts before intent.
    current=_current_checked(store,alias,guard=guard,capture_ref=checked['fresh_capture_ref'])
    if(any(current[k]!=checked[k]for k in('binding','account_binding','owned','registration','research'))
            or current['context']['strategy']['sha256']!=checked['context']['strategy']['sha256']):_blocked('unified_preflight_changed_before_source_intent')
    observer=_unified_observer(guard,alias,'native-topic-source');observer.save('intent',{'control_id':guard['control_id'],'request_id':payload['request_id'],'fresh_capture_ref':checked['fresh_capture_ref'],'automatic_replay':False});rows=[];refs=[];responses=[];pages=[]
    for i,page in enumerate(checked['research']['pages']):
        original=page['raw_ref'];raw=_private(original['path'],original['sha256'])
        copied=observer.write(observer.directory/(observer.prefix+'.mastodon-'+str(i)+'.private.raw'),raw)
        pin={k:copied[k]for k in('path','sha256')};meta=_json_ref(page['metadata_ref'])
        source_meta=copy.deepcopy(meta);source_meta['raw_ref']=pin;source_meta['original_response_metadata_ref']=page['metadata_ref']
        capture_ref=observer.save('mastodon-'+str(i)+'-response',source_meta)
        refs.append(dict(copied,observed_at=page['observed_at']));responses.append(dict(capture_ref,observed_at=page['observed_at']))
        normalized=normalize_mastodon_statuses(raw,response_url=page['response_url'],http_status=200,observed_at=page['observed_at'],
            raw_path=pin['path'],exclude_account_ids=[checked['owned']['account_id']])
        pages.append({'original_raw_ref':original,'original_metadata_ref':page['metadata_ref'],'raw_ref':pin,'metadata_ref':capture_ref})
        for row in normalized['items']:
            if row['author_canonical_url']==checked['owned']['profile_url']:continue
            projected=dict(row,native_source_label=row['source'],source='mastodon:native_rest',native_mastodon_capture_ref=capture_ref)
            if 'directed_search'in checked['registration']:
                rows.append(projected);continue
            prior=next((v for v in rows if(v.get('uri')or v['canonical_url'])==(projected.get('uri')or projected['canonical_url'])),None)
            if prior is not None:continue
            rows.append(projected)
    if 'directed_search'in checked['registration']:rows=_directed_work_observations(rows)
    source_rows=[{'source':'mastodon:native_rest','status':'ok','collected_at':p['observed_at'],
        'count':p['raw_count'],'original_response_ref':p['raw_ref']}for p in checked['research']['pages']]
    budget=min(45,max(0,guard['deadline_unix']-time.time()-180))
    if budget<1:_blocked('unified_original_budget_insufficient_for_current_source_matrix')
    # Reuse the already-managed current background collectors. Their original platforms stay unchanged.
    background_settings=copy.deepcopy(config.get('trends')or{})
    if 'mastodon'in(background_settings.get('direct_sources')or{}):
        background_settings['direct_sources']['mastodon']=dict(background_settings['direct_sources']['mastodon'],enabled=False)
    background=src._collect_observed_background(background_settings,observer,budget)
    background_ref=observer.save('background-original-report',background)
    background=copy.deepcopy(background)
    background['items']=[row for row in background.get('items')or[]if row.get('source')!='legacy_cache']
    background['sources']=[row for row in background.get('sources')or[]if row.get('source')!='legacy_cache']
    for report in background['sources']:
        attempts=(report.get('fetch_provenance')or{}).get('attempts')or[]
        captured={row['sha256']for row in observer.responses}
        if(report.get('status')in{'ok','success'}and not any(a.get('status')=='ok'and a.get('response_sha256')in captured
                and type(a.get('bytes'))is int and a['bytes']>0 for a in attempts)):
            report.update(original_source_status=report['status'],status='unverified',current_http_success_evidence_missing=True)
    trends=dict(background,status='ok',items=rows+background['items'],sources=source_rows+background['sources'],
        collected_at=min(row['observed_at']for row in rows),original_background_report_ref=background_ref,
        legacy_cache_excluded_from_current_source_gate=True)
    public={'status':'ok','items':rows,'sources':source_rows,'independent_source_count':1,
        'claim_boundary':'original_native_observation_not_verified_viral_result','source_family':'mastodon'}
    owned=checked['owned'];account={'status':'ok','collected_at':owned['observed_at'],'platforms':{'mastodon':copy.deepcopy(owned)}}
    policies=src._normal_source_policies(guard,checked['context'])
    # Replace the Twitter-specific parser pin for this explicit Mastodon branch only.
    policies=[p for p in policies if p['path']!=str(PROJECT/'content_platform/twitter_native_source.py')]
    policies.append(src._normal_source_ref(Path(__file__)))
    bundle={'version':'normal_cycle_mastodon_inputs_v1','control_id':guard['control_id'],'request_id':payload['request_id'],
        'payload_sha256':src._digest(payload),'authority_ref':guard['authority_ref'],'cycle_policy_ref':guard['cycle_policy_ref'],
        'deadline_unix':guard['deadline_unix'],'started_at_unix':time.time(),'collected_at':datetime.now(timezone.utc).isoformat(),
        'policies':policies,'binding':checked['binding'],'account_admission':checked['account_binding'],
        'account_report':account,'registration':checked['registration'],'fresh_capture_ref':checked['fresh_capture_ref'],'pages':pages,'raw_refs':refs,'responses':responses,
        'trends':trends,'public':public,'background_original_report_ref':background_ref,'queries':[p['response_url']for p in checked['research']['pages']]}
    bundle['responses'].extend(observer.responses)
    ref=observer.save('mastodon-bundle',bundle)
    return {'binding':checked['binding'],'trends':trends,'source_bundle_ref':ref,'queries':bundle['queries']}

def select_unified_mastodon_topic(store,config,payload,checked):
    from . import task_source_inputs as src
    from .profiles import resolve_profile
    from .trends import rank_trends
    from .overnight_batch import _candidate_has_native_source,_platform_evidence_matrix,build_due_tasks
    from .source_quality import source_is_rankable,source_quality_gate
    from .trend_candidate import build_trend_candidate,validate_trend_candidate
    collected=_collect_mastodon_inputs(store,config,payload,checked);report=collected['trends'];context=checked['context'];binding=checked['binding']
    profile=resolve_profile(config.get('profiles')or{},'default',{'language':binding['language'],'content_form':binding['content_form']})
    from .real_world_ai_policy import classify_discovery_text
    excluded={'excluded_tool_prompt_or_industry_news','excluded_model_news_or_ranking'}
    eligible=[row for row in report['items']if row.get('platform')=='mastodon'and row.get('source')=='mastodon:native_rest'and _candidate_has_native_source('mastodon',row)and source_is_rankable(row)
        and classify_discovery_text(row['title']).get('reason')not in excluded]
    ranked=rank_trends(eligible,profile,store.used_topics(lookback_days=7),200,{})
    strategy={'status':'ok','compiled_strategy':context['strategy']['compiled']};topics=[];diagnostics=[]
    for row in ranked:
        matrix=_platform_evidence_matrix('mastodon',row,report['sources'],strategy,report_path=collected['source_bundle_ref']['path'])
        candidate=build_trend_candidate(platform='mastodon',topic=row['title'],direction=row.get('direction')or row['title'],
            source_report=report['sources'],platform_signal='official same-instance native response, no verified viral result',
            platform_adaptation_reason='current Mastodon account platform strategy',heat_score=float(row.get('score')or 0),
            freshness_score=float(row.get('freshness_score')or 0),platform_fit_score=float(row.get('platform_fit_score')or row.get('score')or 0))
        gate=validate_trend_candidate(candidate);quality=source_quality_gate(row)
        diagnostics.append({'content_id':row['content_id'],'evidence_gate':gate,'source_quality':quality,'platform_source_matrix':matrix})
        if matrix['real_platform_collection_verified']and gate.get('passed')and quality.get('passed'):
            src._normal_actual_candidate_freshness(row);topics.append({'selected_candidate':row,'platform_source_matrix':matrix})
    if not topics:
        src.record_normal_cycle_topic_plan(collected['source_bundle_ref'],{'tasks':[],'diagnostics':diagnostics})
        _blocked('unified_no_current_qualified_native_source',diagnostics=diagnostics)
    bundle=_json_ref(collected['source_bundle_ref'])
    # Complete-pool semantic screening and exact three-reference admission run inside the existing analysis below.
    pool=mastodon_candidate_pool(topics,bundle)
    slot={'platform':'mastodon','content_form':binding['content_form'],'topic_keywords':profile.get('keywords')or[],
        'audience':profile.get('audience')or'operators','account_id':binding['internal_account_alias'],'language':binding['language']}
    analysis=src._obtain_normal_topic_analysis(store,config,payload,context,collected,slot,pool)
    selected=analysis['selected_candidate'];slot['scenario_contract']=analysis['scenario_contract']
    planned=build_due_tasks([slot],items=report['items'],source_report=report['sources'],rank_for_platform=lambda *args:[selected],
        growth_strategy_status={'mastodon':strategy},strict_trend_evidence=True,trend_evidence_mode='enforce',
        runtime_capabilities=context.get('runtime_capabilities'),stage_payload_binder=lambda contract,stage,full:
        src.bind_normal_cycle_planning_payload(store,payload,collected['source_bundle_ref'],contract,stage,full))
    src.qualify_normal_cycle_topic_plan_freshness(planned,selected);ref=src.record_normal_cycle_topic_plan(collected['source_bundle_ref'],planned)
    tasks=planned.get('tasks')or[]
    if len(tasks)!=1 or tasks[0].get('state')!='ready_for_plan':_blocked('unified_current_complete_native_plan_not_ready')
    return {'topic':selected['title'],'plan':tasks[0],'source_report':report,'source_bundle_ref':collected['source_bundle_ref'],
        'plan_ref':ref,'analysis_ref':analysis['record_ref'],'queries':collected['queries'],
        'owned_ranking_context':{'status':'unavailable','reason':'original cumulative snapshots are not mature learning windows'}}

def adopt_unified_mastodon_inputs(store,config,job,contexts):
    from . import task_source_inputs as src
    brief=job.get('brief')or{};ref=brief.get('cycle_native_source_selection_ref')
    if ref is None:return None
    if job.get('platforms')!=['mastodon']:_blocked('unified_Source_exact_platform_required')
    guard=src._normal_cycle_source_guard(store,control_id=brief.get('source_control_job_id'))
    document=_scope_ref(ref,guard['scope']);selection=document['selection'];pin=selection['source_bundle_ref'];bundle=_scope_ref(pin,guard['scope'])
    origin=document.get('origin')or{};alias=(bundle.get('binding')or{}).get('internal_account_alias')
    if(bundle.get('version')!='normal_cycle_mastodon_inputs_v1'or document.get('control_id')!=guard['control_id']
        or origin!=brief.get('legacy_channel_origin')or origin.get('account')!=alias or origin.get('request_id')!=guard['payload']['request_id']
        or bundle.get('control_id')!=guard['control_id']or bundle.get('request_id')!=guard['payload']['request_id']
        or bundle.get('payload_sha256')!=src._digest(guard['payload'])or bundle.get('authority_ref')!=guard['authority_ref']
        or bundle.get('cycle_policy_ref')!=guard['cycle_policy_ref']or bundle.get('deadline_unix')!=guard['deadline_unix']
        or brief.get('source_control_request_id')!=guard['payload']['request_id']or selection.get('topic')!=job['topic']
        or selection.get('queries')!=bundle.get('queries')or not 0<=time.time()-bundle['started_at_unix']<=900):
        _blocked('unified_Source_original_scope_lineage_or_deadline_changed')
    checked=_current_checked(store,alias,guard=guard,capture_ref=bundle['fresh_capture_ref'])
    if(checked['binding']!=bundle['binding']or checked['account_binding']!=bundle['account_admission']
        or checked['registration']!=bundle['registration']or checked['owned']['account_id']!=document.get('native_account_id')):
        _blocked('unified_Source_current_account_or_source_registration_changed')
    expected=src._normal_source_policies(guard,contexts['mastodon'])
    expected=[p for p in expected if p['path']!=str(PROJECT/'content_platform/twitter_native_source.py')]+[src._normal_source_ref(Path(__file__))]
    if bundle.get('policies')!=expected:_blocked('unified_Source_current_complete_policy_set_changed')
    for policy in expected:
        if src._normal_source_ref(policy['path'])!=policy:_blocked('unified_Source_current_policy_changed')
    for response in bundle['raw_refs']+bundle['responses']:
        p=Path(response['path']);raw=_private(p,response['sha256'])
        if not p.is_relative_to(Path(pin['path']).parent)or not 0<=time.time()-_time(response['observed_at']).timestamp()<=900:
            _blocked('unified_Source_original_capture_not_current')
    plan_document=_scope_ref(selection['plan_ref'],guard['scope']);tasks=plan_document['planned']['tasks']
    if(plan_document.get('source_bundle_ref')!=pin or len(tasks)!=1 or tasks[0].get('state')!='ready_for_plan'
            or tasks[0]!=selection['plan']or tasks[0].get('topic')!=job['topic']):_blocked('unified_Source_original_plan_changed')
    src.validate_normal_cycle_planning_payload(guard,pin,tasks[0])
    record=_scope_ref(selection['analysis_ref'],guard['scope'])
    if record.get('version')!='normal_control_topic_analysis_record_v2':_blocked('unified_Source_actual_semantic_record_required')
    analysis=src._adopt_normal_semantic_topic_analysis(dict(guard,store=store,config=config),selection,pin,contexts['mastodon'],record,
        platform='mastodon',binding=bundle['binding'])
    if analysis['selected_candidate']['author_canonical_url']==checked['owned']['profile_url']:_blocked('unified_owned_work_not_external_benchmark')
    return {'account_report':bundle['account_report'],'trends':bundle['trends'],'public':bundle['public'],'source_bundle_ref':pin,**analysis}

def _original_roster(runtime):
    import ast
    p=Path(runtime['scripts'])/'unified_pipeline.py'
    if not p.is_absolute()or p.is_symlink()or not p.is_relative_to(Path(runtime['home'])):_blocked('unified_original_roster_path_unsafe')
    info=p.stat();raw=p.read_bytes();expected=(runtime.get('dependency_sha256')or{}).get('.hermes/scripts/unified_pipeline.py')
    if(not stat.S_ISREG(info.st_mode)or info.st_uid!=0 or info.st_mode&0o022 or not expected or digest(raw)!=expected):
        _blocked('unified_original_roster_pin_changed')
    tree=ast.parse(raw.decode('utf8'));assigned={t.id:n.value for n in tree.body if isinstance(n,ast.Assign)for t in n.targets if isinstance(t,ast.Name)}
    def literal(node,seen=()):
        if isinstance(node,ast.Name):
            if node.id in seen or node.id not in assigned:raise ValueError('original_roster_constant_not_resolvable')
            return literal(assigned[node.id],seen+(node.id,))
        if isinstance(node,ast.Dict):return {literal(k,seen):literal(v,seen)for k,v in zip(node.keys,node.values)}
        if isinstance(node,(ast.List,ast.Tuple)):return [literal(v,seen)for v in node.elts]
        return ast.literal_eval(node)
    values=[]
    for node in tree.body:
        if isinstance(node,ast.Assign)and any(isinstance(v,ast.Name)and v.id=='CHANNEL_ROSTER'for v in node.targets):
            try:values.append(literal(node.value))
            except (ValueError,TypeError):_blocked('unified_original_roster_not_literal_requires_native_proof')
    if len(values)!=1 or not isinstance(values[0],dict):_blocked('unified_original_roster_not_unique')
    return values[0]

def _mastodon_copy_text(copy):
    if not isinstance(copy,dict)or copy.get('platform')!='mastodon'or copy.get('kind')!='short' or not isinstance(copy.get('text'),str)or not copy['text'].strip():
        raise ValueError('unified_mastodon_formal_copy_required')
    return 'Mastodon 正式正文：\n'+copy['text']+'\n\n发布说明：\n仅内部送审、未外部发布。'

def prepare_unified_internal_delivery(job,directory,deadline):
    directory=Path(directory)
    if(directory.name!=job['job_id']or any(p.is_symlink()for p in(directory,*directory.parents))
            or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0'):
        raise ValueError('unified_internal_delivery_original_NoPub_scope_required')
    runtime=_load_runtime()
    from .task_source_inputs import normal_cycle_scope
    from .mandatory_release_gate import mandatory_release_gate
    root=normal_cycle_scope(job['request_id'],expected_home=runtime['home']);plans=[];store=_readonly_store()
    for alias in runtime.get('unified_accounts')or[]:
        if alias not in job['payload']['accounts']:continue
        journal=root/(digest(alias.encode())+'.json')
        if not journal.exists():continue
        journal_raw=_private(journal);saved=_object(journal_raw);binding=saved.get('release_binding')or{}
        if saved.get('phase')!='qualified_internal_handoff_pending_ACK':continue
        origin=saved.get('origin')or{}
        if(saved.get('control_id')!=job['job_id']or origin.get('request_id')!=job['request_id']
            or origin.get('account')!=alias or origin.get('stage')!='unified_pipeline'or binding.get('legacy_origin')!=origin
            or binding.get('platform')!='mastodon'or binding.get('internal_account_alias')!=alias
            or time.time()>=float(deadline)or saved.get('delivery_acknowledged')is not False):
            raise ValueError('unified_internal_delivery_original_lineage_changed')
        current=store.get_job(binding['job_id']);brief=current.get('brief')or{}
        if(brief.get('legacy_channel_origin')!=origin or brief.get('source_control_job_id')!=job['job_id']
            or brief.get('source_control_request_id')!=job['request_id']or brief.get('native_account_id')!=binding['account_id']
            or brief.get('internal_account_alias')!=alias):raise ValueError('unified_internal_current_job_scope_changed')
        selection_document=_scope_ref(brief['cycle_native_source_selection_ref'],root)
        selection=selection_document['selection'];source_ref=selection['source_bundle_ref'];source=_scope_ref(source_ref,root)
        delivery_guard={'control_id':job['job_id'],'payload':job['payload'],'scope':root,'authority_ref':source['authority_ref'],'cycle_policy_ref':source['cycle_policy_ref'],'deadline_unix':source['deadline_unix']}
        checked=_current_checked(store,alias,require_ready=False,guard=delivery_guard,capture_ref=source['fresh_capture_ref'])
        if any(binding.get(k)!=checked['binding'][k]for k in('platform','account_id','internal_account_alias','language','content_form','lane')):raise ValueError('unified_internal_delivery_current_native_account_changed')
        if(source.get('control_id')!=job['job_id']or source.get('request_id')!=job['request_id']
            or source.get('binding')!=checked['binding']or source.get('payload_sha256')!=digest(canonical(job['payload']))):
            raise ValueError('unified_internal_original_Source_binding_changed')
        bundle=store.platform_output_bundle(binding['job_id'],'mastodon')
        if(bundle.get('ready')is not True or digest(canonical(bundle))!=saved.get('qualified_bundle_sha256')
            or bundle.get('content_revision')!=binding.get('content_revision')
            or mandatory_release_gate(store,store.path.parent,binding['job_id'],'mastodon',phase='deliver').get('passed')is not True):
            raise ValueError('unified_internal_current_full_quality_not_qualified')
        copy_value=bundle['copy']['content']
        from .task_source_inputs import project_task_source_job
        from .formatters import _plain
        projected=project_task_source_job(current,'mastodon')
        expected_copy=_plain(projected['title'].strip())+'\n\n'+_plain(projected['body'].strip())
        if copy_value.get('text')!=expected_copy:raise ValueError('unified_current_mastodon_formal_copy_truncation_or_mismatch')
        text=_mastodon_copy_text(copy_value)
        if len(text.encode())>65536:raise ValueError('unified_internal_complete_copy_transport_limit')
        handoff_path=Path(saved['handoff_path'])
        if not handoff_path.resolve(strict=True).is_relative_to((store.path.parent/'internal-handoff'/binding['job_id']).resolve(strict=True)):
            raise ValueError('unified_internal_original_handoff_path_changed')
        handoff=_object(_private(handoff_path));quality=handoff.get('quality_binding')or{}
        artifact_pins=[{'artifact_id':row['artifact_id'],'path':row['path'],'checksum':row['checksum']}for row in bundle['artifacts']]
        if(handoff.get('job_id')!=binding['job_id']or handoff.get('platform')!='mastodon'or handoff.get('status')!='handoff_pending'
            or handoff.get('internal_handoff')is not True or handoff.get('live_publish')is not False or handoff.get('delivery_acknowledged')is not False
            or quality.get('job_id')!=binding['job_id']or quality.get('platform')!='mastodon'
            or quality.get('content_revision')!=bundle['content_revision']or quality.get('draft_version_id')!=bundle['draft_version_id']
            or quality.get('copy_sha256')!=digest(canonical(copy_value))or quality.get('artifacts')!=artifact_pins):
            raise ValueError('unified_internal_original_handoff_quality_changed')
        files=[];source_root=(store.path.parent/'artifacts'/binding['job_id']).resolve(strict=True)
        # Include the actual qualified artifacts. No Twitter four-image inventory is inherited.
        for row in bundle['artifacts']:
            path=Path(row['path'])
            if not path.resolve(strict=True).is_relative_to(source_root):raise ValueError('unified_internal_artifact_outside_job')
            info=path.stat()
            if any(p.is_symlink()for p in(path,*path.parents))or info.st_uid!=0 or info.st_mode&0o022 or info.st_nlink!=1:
                raise ValueError('unified_internal_immutable_artifact_owner_required')
            raw=path.read_bytes()
            if not 0<len(raw)<=48*1024*1024 or digest(raw)!=row['checksum']:raise ValueError('unified_internal_actual_artifact_changed')
            filename='mastodon-'+binding['job_id']+'-'+str(row['artifact_id'])+path.suffix.lower()
            files.append({'filename':filename,'role':row['role'],'size':len(raw),'sha256':row['checksum'],'data':raw})
        inventory=[{k:row[k]for k in('filename','role','size','sha256')}for row in files]
        if len({row['filename']for row in inventory})!=len(inventory)or sum(row['size']for row in inventory)>48*1024*1024:
            raise ValueError('unified_internal_artifact_inventory_invalid')
        proof={'version':'qualified_mastodon_native_origin_v1','control_job_id':job['job_id'],'request_id':job['request_id'],
            'native_account_id':binding['account_id'],'internal_account_alias':alias,'legacy_origin':origin,
            'business_job_id':binding['job_id'],'content_revision':bundle['content_revision'],
            'qualified_bundle_sha256':saved['qualified_bundle_sha256'],'source_bundle_ref':source_ref,
            'source_payload_sha256':source['payload_sha256'],'copy_sha256':digest(canonical(copy_value)),
            'handoff_sha256':digest(_private(handoff_path)),'journal_sha256':digest(journal_raw),'no_publish':True,'files':inventory}
        direct={'version':'qualified_mastodon_internal_copy_v1','text':text,'sha256':digest(text.encode()),'copy':copy_value,
            'control_job_id':job['job_id'],'request_id':job['request_id'],'business_job_id':binding['job_id'],'platform':'mastodon',
            'content_revision':bundle['content_revision'],'qualified_bundle_sha256':saved['qualified_bundle_sha256'],
            'native_origin_proof':proof,'native_origin_proof_sha256':digest(canonical(proof)),'files':inventory}
        plans.append({'files':files,'direct':direct,'journal_sha256':digest(journal_raw)})
    return plans

def queue_unified_internal_delivery(job,directory,plans,outbox,deadline):
    from worker_attachments import bundle_requests
    directory=Path(directory);results=[]
    for plan in plans:
        identity={k:v for k,v in plan.items()if k!='files'};identity['files']=plan['direct']['files'];key=plan['direct']['business_job_id']
        started=directory/('normal-mastodon-'+key+'-transfer.started.private.json')
        done=directory/('normal-mastodon-'+key+'-transfer.completed.private.json')
        delivery={'state':'transfer_queued','acknowledged':False,'direct_chat_text':plan['direct']}
        if started.exists():
            if not done.exists():raise RuntimeError('unified_unknown_internal_transfer_no_replay')
            if _object(_private(done)).get('identity')!=identity:raise ValueError('unified_internal_transfer_receipt_changed')
        else:
            def once(path,raw):
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
            target=directory/('normal-mastodon-'+key+'-bundle');target.mkdir(mode=0o700)
            for row in plan['files']:once(target/row['filename'],row['data'])
            chunks=[]
            for row in plan['files']:
                for chunk in bundle_requests(directory,[{'role':row['role'],'path':str((target/row['filename']).relative_to(directory))}],allow_partial=True):
                    if any(chunk[k]!=row[k]for k in('filename','role','size','sha256')):raise ValueError('unified_internal_attachment_transport_changed')
                    chunks.append(chunk)
            once(started,canonical(identity))
            for chunk in chunks:
                if time.time()>=float(deadline):raise ValueError('unified_original_internal_delivery_deadline_exhausted')
                outbox.put('/v1/jobs/'+job['job_id']+'/attachment-part',dict(chunk,worker_id='heros'))
            once(done,canonical({'identity':identity}))
        results.append({'control_job_id':job['job_id'],'attachments':identity['files'],'internal_delivery':delivery})
    return results


def _unified_observer(guard,alias,purpose):
    from . import task_source_inputs as src
    if purpose not in{'fresh-capture','native-topic-source'}or not re.fullmatch('[a-f0-9]{32}',str(guard.get('control_id')or'')):
        _blocked('unified_original_control_scope_required')
    if alias not in guard['payload']['accounts']or guard['scope']!=src.normal_cycle_scope(guard['payload']['request_id']):
        _blocked('unified_source_account_not_original_guard_scope')
    directory=guard['scope']/('unified-'+purpose)/(digest(alias.encode())[:16])
    if any(p.is_symlink()for p in(directory,*directory.parents)):_blocked('unified_source_observer_path_unsafe')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    observer=object.__new__(src._NativeSourceObservation);observer.directory=directory
    observer.prefix='source-'+guard['control_id'];observer.responses=[];observer.failure=None
    return observer

def _fresh_completed_ref(guard,alias):
    directory=guard['scope']/'unified-fresh-capture'/digest(alias.encode())[:16]
    p=directory/('source-'+guard['control_id']+'.completed.private.json')
    if not p.is_file():_blocked('unified_original_current_capture_not_completed_no_replay')
    raw=_private(p)
    return {'path':str(p),'sha256':digest(raw),'bytes':len(raw)}

def _open_mastodon_once(request,timeout):
    from urllib.request import build_opener,HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,request,response,code,message,headers,newurl):return None
    # The normal managed environment's proxy/TLS policy remains in force; no route fallback.
    return build_opener(NoRedirect()).open(request,timeout=timeout)

def _capture_native_get(observer,label,owned,credential,deadline,*,http_open=None,search_spec=None,operation_deadline=None):
    from urllib.request import Request
    from urllib.error import HTTPError
    instance=_origin(owned['instance']);other=credential.get('instance')
    other=_origin(other if '://'in str(other)else'https://'+str(other))
    token=credential.get('token')
    if other!=instance or not isinstance(token,str)or not token:_blocked('unified_HTTP_same_original_instance_credential_required')
    endpoints={'owned':'/api/v1/accounts/verify_credentials','trends':'/api/v1/trends/statuses?limit=40'}
    if search_spec is not None:
        if (label not in {'search-0','search-1','search-2'}or not isinstance(search_spec,dict)
                or set(search_spec)!={'query','endpoint_path'}):_blocked('unified_HTTP_original_directed_spec_required')
        parsed=urlsplit(search_spec['endpoint_path']);params=parse_qs(parsed.query,keep_blank_values=True,strict_parsing=True)
        if (parsed.scheme or parsed.netloc or parsed.fragment or parsed.path!='/api/v2/search'
                or set(params)!={'q','type','resolve','limit'}or params['q']!=[search_spec['query']]
                or params['type']!=['statuses']or params['resolve']!=['false']
                or len(params['limit'])!=1 or not params['limit'][0].isdigit()or not 1<=int(params['limit'][0])<=40):
            _blocked('unified_HTTP_fixed_directed_endpoint_required')
        endpoints[label]=search_spec['endpoint_path']
    if label not in endpoints:_blocked('unified_HTTP_fixed_official_endpoint_required')
    end=float(deadline)-45
    if operation_deadline is not None:
        if type(operation_deadline)not in (int,float)or not float('-inf')<operation_deadline<float('inf'):_blocked('unified_directed_original_budget_required')
        end=min(end,operation_deadline)
    remaining=end-time.time()
    if remaining<1:_blocked('unified_original_Source_deadline_insufficient_before_HTTP')
    url=instance+endpoints[label]
    request=Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json','User-Agent':'Hermes-Native-Source/1.0'},method='GET')
    response=None;body=b'';status=None;actual=None;headers={};error_type=None;complete=False;limit=8*1024*1024
    try:
        try:response=(http_open or _open_mastodon_once)(request,timeout=min(25,remaining))
        except HTTPError as error:response=error
        status=getattr(response,'status',None)
        if status is None:status=getattr(response,'code',None)
        actual=response.geturl()
        headers={str(k).casefold():str(v)for k,v in response.headers.items()if str(k).casefold()in{
            'content-type','content-length','date','retry-after','x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset','x-request-id'}}
        while len(body)<=limit:
            if time.time()>=end:raise TimeoutError('original_Source_deadline_exhausted_during_body')
            read=getattr(response,'read1',None)or response.read
            block=read(min(65536,limit+1-len(body)))
            if not isinstance(block,bytes):raise TypeError('native_HTTP_body_bytes_required')
            if not block:complete=True;break
            body+=block
        declared=headers.get('content-length')
        if declared is not None and(not declared.isascii()or not declared.isdigit()or int(declared)!=len(body)):complete=False
        if len(body)>limit:complete=False
    except Exception as error:
        error_type=type(error).__name__
        partial=getattr(error,'partial',None)
        if isinstance(partial,bytes):body=(body+partial)[:limit+1]
        complete=False
    finally:
        if response is not None:
            try:response.close()
            except Exception as error:
                complete=False;error_type=error_type or type(error).__name__
    observed=datetime.now(timezone.utc).isoformat(timespec='microseconds')
    raw_ref=observer.write(observer.directory/(observer.prefix+'.'+label+'.response.private.raw'),body)if body else None
    meta={'method':'GET','requested_url':url,'actual_url':actual,'status':status,'observed_at':observed,
        'headers':headers,'raw_ref':raw_ref,'received_body_complete_under_limit':complete,'body_read_error_type':error_type,
        'auth_value_recorded':False,'automatic_replay':False}
    metadata_ref=observer.save(label+'-response-metadata',meta)
    if status!=200 or actual!=url or not complete or raw_ref is None or error_type is not None:
        _blocked('unified_original_native_HTTP_response_not_success_no_replay',response_metadata_ref=metadata_ref)
    return {'raw_ref':raw_ref,'metadata_ref':metadata_ref}

def ensure_fresh_unified_source(store,config,payload,checked,*,http_open=None):
    from . import task_source_inputs as src
    # This official guard is deliberately first: no directory, credential use, or HTTP beforehand.
    guard=src._normal_cycle_source_guard(store,payload=payload)
    alias=checked['binding']['internal_account_alias'];runtime=_load_runtime()
    registration=_registered_input(runtime,alias);binding=_binding(store,alias);owned=read_owned_mastodon_binding(binding,runtime)
    if(alias not in guard['payload']['accounts']or registration!=checked['registration']or binding!=checked['account_binding']
        or owned!=checked['owned']or checked.get('fresh_capture_ref')is not None):_blocked('unified_fresh_Source_original_admission_changed')
    _dependencies(runtime)
    search_specs=_directed_search_specs(registration,owned)
    observer=_unified_observer(guard,alias,'fresh-capture')
    intent_path=observer.directory/(observer.prefix+'.intent.private.json')
    done_path=observer.directory/(observer.prefix+'.completed.private.json')
    if intent_path.exists():
        if not done_path.exists():_blocked('unified_native_Source_previous_attempt_unknown_or_failed_no_replay')
        ref=_fresh_completed_ref(guard,alias)
        _read_fresh_capture(ref,guard,runtime,alias,binding,registration,owned)
        return ref
    if done_path.exists():_blocked('unified_native_Source_orphan_completion_rejected')
    credential=(runtime.get('credentials')or{}).get(alias)or{}
    intent_ref=observer.save('intent',{'version':'unified_native_current_capture_intent_v1','control_id':guard['control_id'],
        'request_id':payload['request_id'],'payload_sha256':src._digest(payload),'account':alias,'native_account_id':owned['account_id'],
        'instance':owned['instance'],'authority_ref':guard['authority_ref'],'deadline_unix':guard['deadline_unix'],
        'endpoint_order':['/api/v1/accounts/verify_credentials','/api/v1/trends/statuses?limit=40']+[v['endpoint_path']for v in search_specs],
        'credential_sha256':digest(credential['token'].encode()),'started_at':datetime.now(timezone.utc).isoformat(timespec='microseconds'),'automatic_replay':False,'no_publish':True})
    try:
        current_owned=_capture_native_get(observer,'owned',owned,credential,guard['deadline_unix'],http_open=http_open)
        body=_json_ref(current_owned['raw_ref'])
        if(not isinstance(body,dict)or body.get('id')!=owned['account_id']
            or urlsplit(str(body.get('url')or'')).scheme!='https'
            or _origin('https://'+urlsplit(str(body.get('url')or'')).netloc)!=owned['instance']
            or not isinstance(body.get('username'),str)or not body['username']or not isinstance(body.get('acct'),str)or not body['acct']):
            _blocked('unified_current_authenticated_native_UID_not_original_account')
        current_trends=_capture_native_get(observer,'trends',owned,credential,guard['deadline_unix'],http_open=http_open)
        raw=_private(current_trends['raw_ref']['path'],current_trends['raw_ref']['sha256']);meta=_json_ref(current_trends['metadata_ref'])
        normalize_mastodon_statuses(raw,response_url=meta['requested_url'],http_status=200,observed_at=meta['observed_at'],
            raw_path=current_trends['raw_ref']['path'],exclude_account_ids=[owned['account_id']])
        directed=None
        if search_specs:
            search_started=time.time();search_deadline=min(search_started+45,guard['deadline_unix']-45,_time(_json_ref(intent_ref)['started_at']).timestamp()+900)
            searches=[]
            with _directed_search_budget(search_deadline):
                for i,spec in enumerate(search_specs):
                    entry=_capture_native_get(observer,'search-'+str(i),owned,credential,guard['deadline_unix'],http_open=http_open,search_spec=spec,operation_deadline=search_deadline)
                    raw_search=_private(entry['raw_ref']['path'],entry['raw_ref']['sha256']);metadata=_json_ref(entry['metadata_ref'])
                    normalize_mastodon_statuses(raw_search,response_url=metadata['requested_url'],http_status=200,observed_at=metadata['observed_at'],raw_path=entry['raw_ref']['path'],exclude_account_ids=[owned['account_id']])
                    searches.append(dict(entry,query=spec['query']))
                    if metadata.get('headers',{}).get('x-ratelimit-remaining')=='0'and i<len(search_specs)-1:
                        _blocked('unified_directed_rate_limit_exhausted_no_replay')
            directed={'specs':search_specs,'started_at_unix':search_started,'deadline_unix':search_deadline,'responses':searches}
        receipt={'version':'unified_current_mastodon_source_capture_v2'if directed is not None else'unified_current_mastodon_source_capture_v1','control_id':guard['control_id'],'request_id':payload['request_id'],
            'payload_sha256':src._digest(payload),'authority_ref':guard['authority_ref'],'cycle_policy_ref':guard['cycle_policy_ref'],
            'deadline_unix':guard['deadline_unix'],'account':alias,'native_account_id':owned['account_id'],'instance':owned['instance'],
            'registration_sha256':digest(canonical(registration)),'original_account_binding_sha256':digest(canonical(binding)),
            'original_identity_snapshot_ref':owned['snapshot_ref'],'credential_sha256':digest(credential['token'].encode()),
            'capture_program_ref':{'path':str(Path(__file__)),'sha256':digest(Path(__file__).read_bytes())},'intent_ref':intent_ref,
            'owned':current_owned,'trends':current_trends,'no_publish':True,'automatic_replay':False,'model_calls':0,'publish_calls':0}
        if directed is not None:receipt['directed_search']=directed
        ref=observer.save('completed',receipt)
        _read_fresh_capture(ref,guard,runtime,alias,binding,registration,owned)
        return ref
    except BaseException as error:
        observer.save('failed',{'control_id':guard['control_id'],'request_id':payload['request_id'],
            'reason_type':type(error).__name__,'automatic_replay':False,'no_publish':True,'may_have_HTTP_effect':True})
        raise

def _read_fresh_capture(ref,guard,runtime,alias,binding,registration,original_owned,*,require_fresh=True):
    if guard is None:_blocked('unified_fresh_capture_original_control_guard_required')
    p=Path(ref['path']);expected=guard['scope']/'unified-fresh-capture'/digest(alias.encode())[:16]/('source-'+guard['control_id']+'.completed.private.json')
    if p!=expected:_blocked('unified_fresh_capture_exact_original_control_path_required')
    receipt=_json_ref(ref);credential=(runtime.get('credentials')or{}).get(alias)or{}
    search_specs=_directed_search_specs(registration,original_owned)
    expected_fields={'version','control_id','request_id','payload_sha256','authority_ref','cycle_policy_ref','deadline_unix','account',
        'native_account_id','instance','registration_sha256','original_account_binding_sha256','original_identity_snapshot_ref',
        'credential_sha256','capture_program_ref','intent_ref','owned','trends','no_publish','automatic_replay','model_calls','publish_calls'}
    if search_specs:expected_fields.add('directed_search')
    expected_version='unified_current_mastodon_source_capture_v2'if search_specs else'unified_current_mastodon_source_capture_v1'
    if(set(receipt)!=expected_fields or receipt.get('version')!=expected_version
        or receipt.get('control_id')!=guard['control_id']or receipt.get('request_id')!=guard['payload']['request_id']
        or receipt.get('payload_sha256')!=digest(canonical(guard['payload']))or receipt.get('authority_ref')!=guard['authority_ref']
        or receipt.get('cycle_policy_ref')!=guard['cycle_policy_ref']or receipt.get('deadline_unix')!=guard['deadline_unix']
        or receipt.get('account')!=alias or receipt.get('native_account_id')!=original_owned['account_id']
        or receipt.get('instance')!=original_owned['instance']or receipt.get('registration_sha256')!=digest(canonical(registration))
        or receipt.get('original_account_binding_sha256')!=digest(canonical(binding))or receipt.get('original_identity_snapshot_ref')!=original_owned['snapshot_ref']
        or receipt.get('credential_sha256')!=digest(str(credential.get('token')or'').encode())
        or receipt.get('capture_program_ref')!={'path':str(Path(__file__)),'sha256':digest(Path(__file__).read_bytes())}
        or receipt.get('no_publish')is not True or receipt.get('automatic_replay')is not False or receipt.get('model_calls')!=0 or receipt.get('publish_calls')!=0):
        _blocked('unified_fresh_capture_original_role_account_or_source_changed')
    intent_ref=receipt['intent_ref'];intent_path=p.parent/('source-'+guard['control_id']+'.intent.private.json')
    if Path(intent_ref['path'])!=intent_path:_blocked('unified_fresh_capture_original_intent_path_changed')
    intent=_json_ref(intent_ref)
    expected_intent={'version':'unified_native_current_capture_intent_v1','control_id':guard['control_id'],'request_id':guard['payload']['request_id'],
        'payload_sha256':digest(canonical(guard['payload'])),'account':alias,'native_account_id':original_owned['account_id'],'instance':original_owned['instance'],
        'authority_ref':guard['authority_ref'],'deadline_unix':guard['deadline_unix'],
        'endpoint_order':['/api/v1/accounts/verify_credentials','/api/v1/trends/statuses?limit=40']+[v['endpoint_path']for v in search_specs],
        'credential_sha256':digest(str(credential.get('token')or'').encode()),'started_at':intent.get('started_at'),'automatic_replay':False,'no_publish':True}
    if intent!=expected_intent:_blocked('unified_fresh_capture_original_intent_binding_changed')
    intent_at=_time(intent['started_at']).timestamp()
    documents={};metas={}
    entries=[('owned','/api/v1/accounts/verify_credentials',receipt['owned']),('trends','/api/v1/trends/statuses?limit=40',receipt['trends'])]
    research_pages=[receipt['trends']]
    if search_specs:
        directed=receipt.get('directed_search')
        if (not isinstance(directed,dict)or set(directed)!={'specs','started_at_unix','deadline_unix','responses'}
                or directed['specs']!=search_specs or type(directed['started_at_unix'])not in(int,float)
                or type(directed['deadline_unix'])not in(int,float)
                or not intent_at<=directed['started_at_unix']<directed['deadline_unix']<=min(directed['started_at_unix']+45,intent_at+900,float(guard['deadline_unix'])-45)
                or not isinstance(directed['responses'],list)or len(directed['responses'])!=len(search_specs)):
            _blocked('unified_directed_original_queries_or_budget_changed')
        for i,(spec,response)in enumerate(zip(search_specs,directed['responses'])):
            if not isinstance(response,dict)or set(response)!={'query','raw_ref','metadata_ref'}or response['query']!=spec['query']:
                _blocked('unified_directed_original_query_response_changed')
            entry={k:response[k]for k in('raw_ref','metadata_ref')};research_pages.append(entry)
            entries.append(('search-'+str(i),spec['endpoint_path'],entry))
    for label,suffix,entry in entries:
        if set(entry)!={'raw_ref','metadata_ref'}:_blocked('unified_fresh_capture_original_raw_and_metadata_required')
        rp=Path(entry['raw_ref']['path']);mp=Path(entry['metadata_ref']['path'])
        if rp.parent!=p.parent or mp.parent!=p.parent:_blocked('unified_fresh_capture_original_response_outside_job')
        raw=_private(rp,entry['raw_ref']['sha256']);meta=_json_ref(entry['metadata_ref']);expected_url=original_owned['instance']+suffix
        if(meta.get('method')!='GET'or meta.get('requested_url')!=expected_url or meta.get('actual_url')!=expected_url
            or meta.get('status')!=200 or meta.get('raw_ref')!=entry['raw_ref']or entry['raw_ref'].get('bytes')!=len(raw)
            or meta.get('received_body_complete_under_limit')is not True or meta.get('body_read_error_type')is not None
            or meta.get('auth_value_recorded')is not False or meta.get('automatic_replay')is not False):_blocked('unified_fresh_original_HTTP_response_changed')
        observed=_time(meta.get('observed_at'))
        if not intent_at<=observed.timestamp()<float(guard['deadline_unix']):_blocked('unified_fresh_capture_observation_not_within_original_intent_budget')
        if(require_fresh and not 0<=time.time()-observed.timestamp()<=900):_blocked('unified_current_native_Source_capture_expired')
        if label.startswith('search-'):
            if not directed['started_at_unix']<=observed.timestamp()<=directed['deadline_unix']:_blocked('unified_directed_observation_outside_original_query_budget')
            normalize_mastodon_statuses(raw,response_url=meta['requested_url'],http_status=200,observed_at=meta['observed_at'],raw_path=str(rp),exclude_account_ids=[original_owned['account_id']])
        documents[label]=_object(raw);metas[label]=meta
    if _time(metas['owned']['observed_at'])>_time(metas['trends']['observed_at']):_blocked('unified_fresh_original_response_order_changed')
    who=documents['owned']
    if not isinstance(who,dict):_blocked('unified_current_authenticated_native_account_object_required')
    url=urlsplit(str(who.get('url')or''))
    if(not isinstance(who,dict)or who.get('id')!=original_owned['account_id']or url.scheme!='https'
        or 'https://'+url.netloc!=original_owned['instance']or not isinstance(who.get('username'),str)or not who['username']
        or not isinstance(who.get('acct'),str)or not who['acct']):_blocked('unified_current_authenticated_native_UID_mismatch')
    native={k:_metric(who.get(k))for k in('followers_count','following_count','statuses_count')}
    owned=dict(original_owned,profile_url=who['url'],native_metrics=native,
        account_metrics={'followers':native['followers_count'],'following':native['following_count'],'posts':native['statuses_count']},
        observed_at=metas['owned']['observed_at'],raw_ref=receipt['owned']['raw_ref'],snapshot_ref=ref,
        original_identity_snapshot_ref=original_owned['snapshot_ref'],source='native.mastodon_accounts_verify_credentials_current_job',
        missing_metrics=[k for k,v in {'followers':native['followers_count'],'following':native['following_count'],'posts':native['statuses_count']}.items()if v is None],
        observation_scope='actual current job authenticated native account observation; not a mature metric window',collector_HTTP_calls=2,
        generation_authorized_by_analytics_binding=False,learning_eligible=False)
    return {'receipt':receipt,'owned':owned,'research_pages':research_pages}
