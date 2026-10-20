"""Fail-closed quality audit for self-owned performance observations."""
from __future__ import annotations

from typing import Any, Iterable


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def audit_owned_performance_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Separate reviewable owned metrics from implausible or unmapped rows."""
    eligible: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw) if isinstance(raw, dict) else {}
        reasons: list[str] = []
        title = str(row.get("title") or "").strip()
        content_id = str(row.get("platform_content_id") or row.get("content_id") or "").strip()
        job_id = str(row.get("job_id") or "").strip()
        if not job_id and not title and not content_id:
            reasons.append("owned_work_identity_missing")
        views, likes = _number(row.get("views")), _number(row.get("likes"))
        if views > 0 and likes >= views:
            reasons.append("likes_not_less_than_views")
        if any(_number(row.get(field)) < 0 for field in ("views", "likes", "comments", "shares", "saves", "follows")):
            reasons.append("negative_metric")
        if reasons:
            quarantined.append({**row, "reason_codes": reasons})
        else:
            eligible.append(row)
    return {
        "version": "owned_performance_audit_v1",
        "eligible_count": len(eligible),
        "quarantined_count": len(quarantined),
        "eligible": eligible,
        "quarantined": quarantined,
    }

# 原生历史身份准入只解释既有认证观察，不执行网络、发布或指标窗口。
def _native_history_json_ref(reference):
    from pathlib import Path
    import hashlib,json,os,re,stat
    if (not isinstance(reference,dict) or not isinstance(reference.get('path'),str)
            or not re.fullmatch('[a-f0-9]{64}',str(reference.get('sha256')or''))):
        raise ValueError('native_history_pinned_json_reference_required')
    path=Path(reference['path'])
    if not path.is_absolute() or any(p.is_symlink() for p in(path,*path.parents)):
        raise ValueError('native_history_reference_path_not_trusted')
    before=path.stat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid!=0 or before.st_mode&0o077
            or before.st_nlink!=1 or not 0<before.st_size<=16*1024*1024):
        raise ValueError('native_history_private_bounded_original_required')
    raw=path.read_bytes();after=path.stat()
    if ((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
            !=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
            or hashlib.sha256(raw).hexdigest()!=reference['sha256']
            or ('bytes'in reference and (type(reference['bytes'])is not int or reference['bytes']!=len(raw)))):
        raise ValueError('native_history_original_bytes_changed')
    return json.loads(raw)


def audit_native_publication_history(binding,snapshot_rows,*,account_response_metadata_ref,page_commit_refs=(),read_json_ref=None,
                                     native_work_evidence=None,read_text_ref=None):
    """从已登记snapshot及原认证API证据导出身份；不创造publisher回执/本地已发job。"""
    if isinstance(binding,dict)and binding.get('platform')=='bilibili':
        if page_commit_refs:raise ValueError('bilibili_history_Mastodon_page_commits_not_applicable')
        return _audit_bilibili_native_publication_history(binding,snapshot_rows,
            account_response_metadata_ref=account_response_metadata_ref,native_work_evidence=native_work_evidence,
            read_json_ref=read_json_ref,read_text_ref=read_text_ref)
    if native_work_evidence is not None or read_text_ref is not None:
        raise ValueError('native_history_platform_specific_evidence_mismatch')
    import hashlib,json,re
    from datetime import datetime
    from urllib.parse import urlsplit,parse_qsl
    reader=read_json_ref or _native_history_json_ref;cache={}
    def read(ref):
        if not isinstance(ref,dict):raise ValueError('native_history_evidence_reference_required')
        key=(ref.get('path'),ref.get('sha256'))
        if key not in cache:cache[key]=reader(ref)
        return cache[key]
    def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    def timestamp(value):
        if not isinstance(value,str):raise ValueError('native_history_actual_timestamp_required')
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:raise ValueError('native_history_timezone_required')
        return parsed
    if not isinstance(binding,dict)or binding.get('platform')!='mastodon':
        raise ValueError('native_history_supported_authenticated_platform_required')
    cfg=binding.get('config')or{};alias=binding.get('account_key');account=cfg.get('account_id')
    if (not isinstance(alias,str)or not re.fullmatch('[A-Za-z0-9_-]{1,80}',alias)
            or cfg.get('internal_account_alias')!=alias
            or not isinstance(account,str)or not re.fullmatch('[0-9]{1,80}',account)
            or cfg.get('identity_source')!='native_accounts_verify_credentials'):
        raise ValueError('native_history_registered_native_account_required')
    instance=cfg.get('instance');origin=urlsplit(instance if isinstance(instance,str)else'')
    if (origin.scheme!='https'or not origin.netloc or origin.username or origin.password
            or origin.path not in{'','/'}or origin.query or origin.fragment):
        raise ValueError('native_history_registered_https_instance_required')
    def endpoint(meta,path,*,statuses=False):
        if (not isinstance(meta,dict)or meta.get('method')!='GET'or type(meta.get('status'))is not int
                or meta['status']!=200 or not isinstance(meta.get('authentication'),str)
                or not meta['authentication'] or meta.get('actual_url')!=meta.get('url')):
            raise ValueError('native_history_original_authenticated_HTTP200_required')
        u=urlsplit(str(meta.get('url')or''))
        if u.scheme!='https'or u.netloc!=origin.netloc or u.username or u.password or u.fragment or u.path!=path:
            raise ValueError('native_history_original_endpoint_account_mismatch')
        pairs=parse_qsl(u.query,keep_blank_values=True);q=dict(pairs)
        if len(q)!=len(pairs):raise ValueError('native_history_duplicate_query_parameters')
        if statuses:
            if (set(q)-{'limit','exclude_reblogs','max_id','min_id','since_id'}
                    or q.get('exclude_reblogs')!='true'or not str(q.get('limit','')).isdigit()
                    or not 1<=int(q['limit'])<=40
                    or any(not re.fullmatch('[0-9]{1,80}',v)for k,v in q.items()if k in{'max_id','min_id','since_id'})):
                raise ValueError('native_history_original_statuses_query_mismatch')
        elif q:raise ValueError('native_history_identity_endpoint_query_forbidden')
        timestamp(meta.get('captured_at'))
    proof_ref=cfg.get('native_account_snapshot_ref');proof=read(proof_ref);account_meta=read(account_response_metadata_ref)
    endpoint(account_meta,'/api/v1/accounts/verify_credentials')
    if (not isinstance(proof,dict)or proof.get('schema')!='mastodon_original_native_identity_v1'
            or proof.get('status')!='observed'or proof.get('platform')!='mastodon'
            or proof.get('native_account_id')!=account or proof.get('internal_account_alias')!=alias
            or proof.get('registered_operating_object')!=alias
            or proof.get('observed_at')!=account_meta.get('captured_at')
            or (proof.get('identity_raw_ref')or{}).get('sha256')!=(account_meta.get('raw_ref')or{}).get('sha256')):
        raise ValueError('native_history_registered_account_proof_mismatch')
    actual_account=read(proof['identity_raw_ref'])
    if (not isinstance(actual_account,dict)or actual_account.get('id')!=account
            or actual_account.get('username')!=proof.get('username')
            or actual_account.get('url')!=proof.get('canonical_url')):
        raise ValueError('native_history_actual_authenticated_account_mismatch')
    profile=urlsplit(str(actual_account.get('url')or''))
    if profile.scheme!='https'or profile.netloc!=origin.netloc or profile.username or profile.password or profile.fragment:
        raise ValueError('native_history_account_profile_instance_mismatch')
    catalog_ref=cfg.get('native_statuses_observation_ref')
    if isinstance(catalog_ref,dict):
        catalog=read(catalog_ref)
        if isinstance(catalog,dict)and catalog.get('schema')=='mastodon_original_visible_statuses_full_observation_v1':
            return _audit_mastodon_full_visible_publication_history(binding,snapshot_rows,
                account_response_metadata_ref=account_response_metadata_ref,page_commit_refs=page_commit_refs,
                read=read,digest=digest,timestamp=timestamp,origin=origin,proof_ref=proof_ref,
                proof=proof,catalog_ref=catalog_ref,catalog=catalog,cache=cache)
    commits={}
    if not isinstance(page_commit_refs,(list,tuple))or len(page_commit_refs)>1000:
        raise ValueError('native_history_bounded_page_commits_required')
    for ref in page_commit_refs:
        commit=read(ref)
        if not isinstance(commit,dict):raise ValueError('native_history_page_commit_required')
        key=(commit.get('result_ref')or{}).get('sha256')
        if not isinstance(key,str)or key in commits:raise ValueError('native_history_page_commit_duplicate_or_unbound')
        timestamp(commit.get('committed_at'));commits[key]=(commit,ref)
    if not isinstance(snapshot_rows,list)or not 1<=len(snapshot_rows)<=1000:
        raise ValueError('native_history_bounded_existing_snapshots_required')
    identities=[];seen=set();urls=set()
    for row in snapshot_rows:
        if not isinstance(row,dict)or type(row.get('id'))is not int or row['id']<=0 or row.get('platform')!='mastodon':
            raise ValueError('native_history_existing_platform_snapshot_required')
        p=row.get('payload')
        if p is None:
            try:p=json.loads(row['payload_json'])
            except(KeyError,TypeError,ValueError)as exc:raise ValueError('native_history_existing_snapshot_payload_required')from exc
        if (not isinstance(p,dict)or p.get('kind')!='native_owned_post_lifetime_snapshot'
                or p.get('platform')!='mastodon'or p.get('native_account_id')!=account
                or p.get('account_id')!=account or p.get('internal_account_alias')!=alias
                or p.get('learning_eligible')is not False or p.get('strategy_eligible')is not False
                or p.get('mature_metric_window')is not None):
            raise ValueError('native_history_owned_lifetime_snapshot_scope_mismatch')
        content_id=p.get('platform_content_id')
        if not isinstance(content_id,str)or not re.fullmatch('[0-9]{1,80}',content_id)or content_id in seen:
            raise ValueError('native_history_exact_unique_native_content_id_required')
        seen.add(content_id);meta=read(p.get('header_ref'));endpoint(meta,'/api/v1/accounts/'+account+'/statuses',statuses=True)
        if ((meta.get('raw_ref')or{}).get('sha256')!=(p.get('raw_ref')or{}).get('sha256')
                or p.get('observed_at')!=meta.get('captured_at')):
            raise ValueError('native_history_response_raw_or_capture_mismatch')
        raw=read(p['raw_ref']);result=read(p.get('native_result_ref'))
        if not isinstance(raw,list)or not raw or len(raw)>40:
            raise ValueError('native_history_complete_native_status_array_required')
        if (not isinstance(result,dict)or result.get('schema')!='mastodon_original_native_statuses_v1'
                or result.get('status')!='observed'or result.get('platform')!='mastodon'
                or result.get('native_account_id')!=account or result.get('registered_operating_object')!=alias
                or (result.get('account_identity_ref')or{}).get('sha256')!=proof_ref['sha256']
                or result.get('observed_status_count')!=len(raw)):
            raise ValueError('native_history_original_normalized_page_mismatch')
        result_sha=p['native_result_ref']['sha256'];commit_ref=None
        if result_sha!=(cfg.get('native_statuses_observation_ref')or{}).get('sha256'):
            if result_sha not in commits:raise ValueError('native_history_subsequent_page_commit_required')
            commit,commit_ref=commits[result_sha]
            if ((commit.get('raw_ref')or{}).get('sha256')!=p['raw_ref']['sha256']
                    or commit.get('url')!=meta.get('url')
                    or timestamp(commit['committed_at'])<timestamp(p['observed_at'])):
                raise ValueError('native_history_page_commit_source_mismatch')
        found=[x for x in raw if isinstance(x,dict)and x.get('id')==content_id]
        normalized=[x for x in(result.get('posts')or[])if isinstance(x,dict)and x.get('platform_content_id')==content_id]
        if len(found)!=1 or len(normalized)!=1:raise ValueError('native_history_original_native_id_not_unique_in_page')
        native=found[0]
        if (not isinstance(native.get('account'),dict)or native['account'].get('id')!=account
                or native.get('reblog')is not None or native.get('visibility')not in{'public','unlisted'}):
            raise ValueError('native_history_owned_public_or_unlisted_original_required')
        required={'canonical_url':native.get('url')or native.get('uri'),'content_html':native.get('content'),
                  'published_at':native.get('created_at'),'visibility':native.get('visibility'),
                  'native_account_id':account,'observed_at':meta['captured_at'],
                  'native_metrics':{key:native.get(key)for key in('favourites_count','reblogs_count','replies_count')}}
        if any(p.get(k)!=v or normalized[0].get(k)!=v for k,v in required.items()):
            raise ValueError('native_history_original_content_identity_or_metrics_changed')
        if not isinstance(required['content_html'],str)or not required['content_html'].strip():
            raise ValueError('native_history_actual_content_missing')
        for value in required['native_metrics'].values():
            if value is not None and(type(value)is not int or value<0):raise ValueError('native_history_native_metric_type_invalid')
        if timestamp(required['published_at'])>timestamp(p['observed_at']):
            raise ValueError('native_history_publish_after_observation')
        url=required['canonical_url'];u=urlsplit(url if isinstance(url,str)else'')
        if (u.scheme!='https'or u.netloc!=origin.netloc or u.username or u.password or u.fragment
                or not u.path or url in urls):raise ValueError('native_history_actual_owned_url_invalid_or_duplicate')
        urls.add(url)
        metadata={'evidence_type':'authenticated_native_status_history','visibility':required['visibility'],
            'source_snapshot_id':row['id'],'snapshot_recording_job_id':row.get('job_id'),
            'source_snapshot_payload_sha256':digest(p),'observed_at':p['observed_at'],
            'account_proof_ref':proof_ref,'account_response_metadata_ref':account_response_metadata_ref,
            'raw_ref':p['raw_ref'],'response_metadata_ref':p['header_ref'],'native_result_ref':p['native_result_ref'],
            'content_html_sha256':hashlib.sha256(required['content_html'].encode()).hexdigest(),
            'not_a_publisher_ack':True,'mature_metric_window':None,'learning_eligible':False,'strategy_eligible':False}
        if commit_ref is not None:metadata['page_commit_ref']=commit_ref
        identities.append({'platform':'mastodon','account_id':account,'internal_account_alias':alias,
            'platform_content_id':content_id,'canonical_url':url,'published_at':required['published_at'],
            'verification_level':'native_verified','identity_source':'native_owned_history_snapshot','metadata':metadata})
    return {'version':'native_publication_history_audit_v1','identities':identities,'identity_count':len(identities),
            'native_proof_files_read':len(cache),'publisher_ack_created':False,'metric_windows_created':0,
            'learning_eligible':False,'strategy_eligible':False}


def _native_history_private_text_ref(reference):
    from pathlib import Path
    import hashlib,re,stat
    if (not isinstance(reference,dict)or not isinstance(reference.get('path'),str)
            or not re.fullmatch('[a-f0-9]{64}',str(reference.get('sha256')or''))):
        raise ValueError('bilibili_history_pinned_original_text_required')
    p=Path(reference['path'])
    if not p.is_absolute()or '..'in p.parts or any(q.is_symlink()for q in(p,*p.parents)):
        raise ValueError('bilibili_history_original_text_path_not_trusted')
    s=p.stat()
    if (not stat.S_ISREG(s.st_mode)or s.st_uid!=0 or s.st_mode&0o077 or s.st_nlink!=1
            or not 0<s.st_size<=16384):raise ValueError('bilibili_history_private_bounded_original_text_required')
    raw=p.read_bytes();t=p.stat()
    if ((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns,t.st_ctime_ns)
            or hashlib.sha256(raw).hexdigest()!=reference['sha256']
            or 'bytes'in reference and(type(reference['bytes'])is not int or reference['bytes']!=len(raw))):
        raise ValueError('bilibili_history_original_text_changed')
    return raw.decode('utf8','strict')


def _audit_bilibili_native_publication_history(binding,snapshot_rows,*,account_response_metadata_ref,
                                               native_work_evidence,read_json_ref=None,read_text_ref=None):
    import hashlib,json,re
    from datetime import datetime,timezone
    from urllib.parse import urlsplit,parse_qsl
    reader=read_json_ref or _native_history_json_ref;cache={}
    def read(ref):
        if not isinstance(ref,dict):raise ValueError('bilibili_history_pinned_evidence_required')
        key=(ref.get('path'),ref.get('sha256'))
        if key not in cache:cache[key]=reader(ref)
        return cache[key]
    def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    def sha(text):return hashlib.sha256(text.encode()).hexdigest()
    def time(value):
        if not isinstance(value,str):raise ValueError('bilibili_history_original_timestamp_required')
        v=datetime.fromisoformat(value.replace('Z','+00:00'))
        if v.tzinfo is None:raise ValueError('bilibili_history_timestamp_timezone_required')
        return v
    def uint(v,positive=False):
        if type(v)is not int or v<(1 if positive else 0):raise ValueError('bilibili_history_native_integer_required')
        return v
    def http(meta):
        if (not isinstance(meta,dict)or meta.get('method')!='GET'or type(meta.get('http_status'))is not int
                or meta['http_status']!=200 or meta.get('response_complete')is not True or meta.get('error')is not None):
            raise ValueError('bilibili_history_complete_original_HTTP200_required')
        time(meta.get('observed_at'))
    cfg=binding.get('config')or{};alias=binding.get('account_key');account=cfg.get('account_id');registered=cfg.get('registered_account_id')
    if (binding.get('platform')!='bilibili'or not isinstance(alias,str)or not re.fullmatch('[A-Za-z0-9_-]{1,80}',alias)
            or cfg.get('internal_account_alias')!=alias or not isinstance(account,str)or not re.fullmatch('[0-9]{1,80}',account)
            or not isinstance(registered,str)or not registered or cfg.get('identity_source')!='root_verified_original_account_identity_v1'):
        raise ValueError('bilibili_history_registered_original_account_required')
    proof_ref=cfg.get('registered_identity_proof_ref');proof=read(proof_ref)
    if (proof.get('schema')!='registered_account_identity_v1'or proof.get('platform')!='bilibili'
            or proof.get('native_account_id')!=account or proof.get('internal_account_alias')!=alias
            or proof.get('registered_account_id')!=registered or proof.get('evidence_kind')!='original_operator_profile_uid'):
        raise ValueError('bilibili_history_registered_proof_mismatch')
    auth=read(account_response_metadata_ref)
    if (account_response_metadata_ref!=cfg.get('identity_native_capture_ref')or auth.get('state')!='observation_returned'
            or auth.get('publication')is not False):raise ValueError('bilibili_history_original_authenticated_capture_required')
    refs={}
    for ref in proof.get('evidence_refs')or[]:
        kind=ref.get('kind')
        if kind in refs:raise ValueError('bilibili_history_ambiguous_account_proof')
        refs[kind]={k:v for k,v in ref.items()if k!='kind'}
    authref=refs.get('original_authenticated_native_capture')or{}
    if any(authref.get(k)!=account_response_metadata_ref.get(k)for k in('path','sha256')):
        raise ValueError('bilibili_history_account_capture_proof_unbound')
    for kind,path in [('original_native_nav','/x/web-interface/nav'),('original_native_card','/x/web-interface/card')]:
        entries=[m for m in auth.get('raw_responses')or[]if(m.get('raw_ref')or{}).get('sha256')==(refs.get(kind)or{}).get('sha256')]
        if len(entries)!=1:raise ValueError('bilibili_history_auth_response_not_unique')
        meta=entries[0];http(meta);u=urlsplit(str(meta.get('url')or''))
        if (u.scheme!='https'or u.netloc!='api.bilibili.com'or u.path!=path or u.fragment
                or meta.get('actual_url')!=meta.get('url')or u.username or u.password):raise ValueError('bilibili_history_original_auth_endpoint_mismatch')
        query=parse_qsl(u.query,keep_blank_values=True)
        if query!=([('mid',account)]if kind=='original_native_card'else[]):raise ValueError('bilibili_history_auth_query_mismatch')
        raw=read(meta['raw_ref'])
        if type(raw.get('code'))is not int or raw['code']!=0:raise ValueError('bilibili_history_auth_native_code_not_zero')
        data=raw.get('data')or{}
        if kind=='original_native_nav':
            if data.get('isLogin')is not True or type(data.get('mid'))is not int or str(data['mid'])!=account:
                raise ValueError('bilibili_history_authenticated_MID_mismatch')
        elif str((data.get('card')or{}).get('mid'))!=account:raise ValueError('bilibili_history_native_card_MID_mismatch')
    ev=native_work_evidence
    if (not isinstance(ev,dict)or ev.get('schema')!='bilibili_owned_history_evidence_v1'
            or set(ev)!={'schema','capture_ref','capture_receipt_ref','header_refs','original_creator_receipt_ref',
                         'original_creator_metadata_ref','original_creator_nav_metadata_ref','original_creator_request_url_ref'}):
        raise ValueError('bilibili_history_typed_work_evidence_required')
    capture_ref=ev.get('capture_ref');capture=read(capture_ref);receipt=read(ev.get('capture_receipt_ref'))
    if (capture.get('schema')!='bili_original29_current_cumulative_capture_v1'or capture.get('native_account_id')!=account
            or capture.get('strategy_eligible')is not False or capture.get('metric_window_hours')is not None
            or receipt.get('state')!='native_current29_captured_not_imported'or receipt.get('capture_ref')!=capture_ref
            or receipt.get('request_id')!=capture.get('request_id')or receipt.get('database_written')is not False):
        raise ValueError('bilibili_history_original_work_capture_mismatch')
    context=capture.get('context')or{}
    if (context.get('binding_id')!=binding.get('id')or context.get('native_MID')!=account
            or context.get('registered_identity_proof_ref')!=proof_ref):raise ValueError('bilibili_history_capture_actor_mismatch')
    original=read(ev.get('original_creator_receipt_ref'));original_meta=read(ev.get('original_creator_metadata_ref'));navmeta=read(ev.get('original_creator_nav_metadata_ref'))
    if (original.get('auth_or_rate_or_budget_stop')is not False or original.get('no_click_login_upload_or_challenge')is not True
            or sum(m==original_meta for m in original.get('response_records')or[])!=1
            or sum(m==navmeta for m in original.get('response_records')or[])!=1):raise ValueError('bilibili_history_original_creator_receipt_mismatch')
    http(original_meta);http(navmeta)
    if original_meta.get('api_path')!='/x/web/archives'or navmeta.get('api_path')!='/x/web-interface/nav':raise ValueError('bilibili_history_original_creator_endpoint_mismatch')
    nav=read(navmeta.get('raw_ref'))
    if type(nav.get('code'))is not int or nav['code']!=0 or(nav.get('data')or{}).get('isLogin')is not True or str(nav['data'].get('mid'))!=account:
        raise ValueError('bilibili_history_original_creator_authenticated_MID_required')
    urlref=ev.get('original_creator_request_url_ref')
    if original_meta.get('url_ref')!=urlref:raise ValueError('bilibili_history_original_creator_URL_reference_mismatch')
    text=(read_text_ref or _native_history_private_text_ref)(urlref);u=urlsplit(text);pairs=parse_qsl(u.query,keep_blank_values=True,strict_parsing=True);q=dict(pairs)
    if (u.scheme!='https'or u.netloc!='member.bilibili.com'or u.path!='/x/web/archives'or u.username or u.password or u.fragment
            or len(q)!=len(pairs)or set(q)!={'client_type','coop','interactive','pn','ps','status','x-bili-device-req-json','x-bili-locale-json'}
            or any(q.get(k)!=v for k,v in{'pn':'1','ps':'10','status':'is_pubing,pubed,not_pubed','coop':'1','interactive':'1'}.items())):
        raise ValueError('bilibili_history_original_creator_request_URL_mismatch')
    total=uint(capture.get('directory_count'),True);works=capture.get('works');headerrefs=ev.get('header_refs')
    if (total>1000 or not isinstance(works,list)or len(works)!=total or not isinstance(headerrefs,list)
            or len(headerrefs)!=(total+9)//10 or not isinstance(snapshot_rows,list)or len(snapshot_rows)!=total):
        raise ValueError('bilibili_history_complete_bounded_capture_and_snapshots_required')
    headers=[read(ref)for ref in headerrefs]
    if headers!=capture.get('headers'):raise ValueError('bilibili_history_original_headers_unbound')
    archives={};seen_aids=set();page_by_id={}
    for pn,meta in enumerate(headers,1):
        http(meta);url,n=re.subn(r'(?<=[?&])pn=1(?=&|$)','pn='+str(pn),text)
        if n!=1 or meta.get('page_number')!=pn or meta.get('request_url_sha256')!=sha(url)or meta.get('actual_url_sha256')!=sha(url):
            raise ValueError('bilibili_history_original_page_endpoint_or_redirect_mismatch')
        doc=read(meta.get('raw_ref'));data=doc.get('data')or{};page=data.get('page')or{};rows=data.get('arc_audits')
        if (type(doc.get('code'))is not int or doc['code']!=0 or any(type(page.get(k))is not int for k in('pn','ps','count'))
                or page!={'pn':pn,'ps':10,'count':total}or not isinstance(rows,list)or len(rows)!=min(10,total-(pn-1)*10)):
            raise ValueError('bilibili_history_complete_native_directory_page_required')
        for item in rows:
            a=item.get('Archive')or{};aid=uint(a.get('aid'),True);bvid=a.get('bvid')
            if (type(a.get('mid'))is not int or str(a['mid'])!=account or not isinstance(bvid,str)
                    or not re.fullmatch('BV[0-9A-Za-z]{10}',bvid)or bvid in archives or aid in seen_aids):raise ValueError('bilibili_history_unique_native_MID_AID_BVID_required')
            if (type(a.get('state'))is not int or a['state']!=0 or type(a.get('no_public'))is not int or a['no_public']!=0
                    or type(a.get('is_only_self'))is not int or a['is_only_self']!=0 or type((a.get('attrs')or{}).get('is_owner'))is not int
                    or a['attrs']['is_owner']!=1 or type(a.get('had_passed'))is not bool
                    or not isinstance(a.get('state_desc'),str)or not a['state_desc'].strip()):raise ValueError('bilibili_history_original_open_owned_state_required')
            ptime=uint(a.get('ptime'),True)
            if datetime.fromtimestamp(ptime,timezone.utc)>time(meta['observed_at']):raise ValueError('bilibili_history_publish_after_observation')
            archives[bvid]=item;page_by_id[bvid]=(pn,meta,headerrefs[pn-1]);seen_aids.add(aid)
    if len(archives)!=total:raise ValueError('bilibili_history_incomplete_native_catalog')
    workmap={w.get('native_content_id'):w for w in works if isinstance(w,dict)}
    if len(workmap)!=total or set(workmap)!=set(archives):raise ValueError('bilibili_history_normalized_native_catalog_mismatch')
    identities=[];selected=set();keys=('view','like','danmaku','reply','coin','favorite','share');detail_used=False
    for row in snapshot_rows:
        if not isinstance(row,dict)or type(row.get('id'))is not int or row['id']<=0 or row.get('platform')!='bilibili':raise ValueError('bilibili_history_existing_snapshot_required')
        p=row.get('payload')
        if p is None:p=json.loads(row['payload_json'])
        if not isinstance(p,dict):raise ValueError('bilibili_history_snapshot_object_required')
        bvid=p.get('platform_content_id');w=workmap.get(bvid)
        if (w is None or bvid in selected or p.get('platform')!='bilibili'or p.get('account_id')!=account
                or p.get('native_account_id')!=account or p.get('internal_account_alias')!=alias or p.get('registered_account_id')!=registered
                or p.get('registered_identity_proof_ref')!=proof_ref or p.get('observation_type')!='native_current29_cumulative_refresh'
                or p.get('strategy_eligible')is not False or p.get('metric_window_hours')is not None
                or p.get('mature_window_hours')is not None or p.get('publication_verified')is not False
                or p.get('publisher_ack_recovered')is not False or any(p.get(k)!=v for k,v in w.items())):
            raise ValueError('bilibili_history_owned_original_snapshot_scope_mismatch')
        selected.add(bvid);item=archives[bvid];a=item['Archive'];stats=item.get('stat')or{};pn,meta,headerref=page_by_id[bvid]
        base=p.get('original_current_creator_snapshot')or p
        exact={'native_content_id':bvid,'native_account_id':account,'aid':a['aid'],'ptime':a['ptime'],'title':a.get('title'),
               'duration':a.get('duration'),'native_state':a['state'],'native_state_desc':a['state_desc'],'had_passed':a['had_passed'],
               'source_page_number':pn,'observed_at':meta['observed_at'],'source_raw_ref':meta['raw_ref']}
        if any(base.get(k)!=v for k,v in exact.items()):raise ValueError('bilibili_history_native_Archive_snapshot_mismatch')
        if not isinstance(a.get('title'),str)or not a['title'].strip():raise ValueError('bilibili_history_native_title_missing')
        uint(a.get('duration'));stat_aid=uint(stats.get('aid'))
        if stat_aid not in{0,a['aid']}:raise ValueError('bilibili_history_stat_AID_mismatch')
        native={k:stats.get(k)for k in keys}
        for value in native.values():
            if value is not None:uint(value)
        if (base.get('native_raw_metric_values')!=native or base.get('metrics')!=(native if stat_aid==a['aid']else{k:None for k in keys})
                or base.get('native_stat_aid')!=stat_aid):raise ValueError('bilibili_history_original_counter_values_changed')
        detail_ref=p.get('detail_header_ref')
        if p.get('original_current_creator_snapshot')is not None:
            if detail_used or detail_ref!=capture.get('detail_header_ref'):raise ValueError('bilibili_history_bounded_original_detail_required')
            detail_used=True;dm=read(detail_ref);http(dm);url='https://api.bilibili.com/x/web-interface/view?bvid='+bvid
            if dm.get('api_path')!='/x/web-interface/view'or dm.get('request_URL_sha256')!=sha(url)or dm.get('actual_URL_sha256')!=sha(url):raise ValueError('bilibili_history_original_public_view_endpoint_mismatch')
            detail=read(dm.get('raw_ref'));d=detail.get('data')or{};ds=d.get('stat')or{}
            if (type(detail.get('code'))is not int or detail['code']!=0 or d.get('bvid')!=bvid or d.get('aid')!=a['aid']
                    or type((d.get('owner')or{}).get('mid'))is not int or str(d['owner']['mid'])!=account
                    or type(d.get('state'))is not int or d['state']!=0 or type(d.get('pubdate'))is not int
                    or d['pubdate']!=a['ptime']or type(ds.get('aid'))is not int or ds['aid']!=a['aid']):raise ValueError('bilibili_history_native_public_view_identity_mismatch')
            native={k:ds.get(k)for k in keys}
            for value in native.values():
                if value is not None:uint(value)
            if p.get('observed_at')!=dm['observed_at']or p.get('raw_ref')!=dm['raw_ref']or p.get('metrics')!=native:raise ValueError('bilibili_history_original_detail_snapshot_mismatch')
        elif stat_aid!=a['aid']or p.get('raw_ref')!=meta['raw_ref']or p.get('observed_at')!=meta['observed_at']:raise ValueError('bilibili_history_native_identity_unbound')
        if p.get('native_metrics')!=native or p.get('metric_identity_verified')is not True:raise ValueError('bilibili_history_metric_identity_or_missing_values_changed')
        published=datetime.fromtimestamp(a['ptime'],timezone.utc).isoformat()
        if p.get('native_ptime_epoch')!=a['ptime']or p.get('native_ptime_UTC')!=published:raise ValueError('bilibili_history_native_publish_time_changed')
        metadata={'evidence_type':'authenticated_native_creator_history','visibility':'native_open_browse','native_state':a['state'],
            'native_state_desc':a['state_desc'],'native_had_passed':a['had_passed'],'native_no_public':a['no_public'],
            'source_snapshot_id':row['id'],'snapshot_recording_job_id':row.get('job_id'),'source_snapshot_payload_sha256':digest(p),
            'observed_at':p['observed_at'],'account_proof_ref':proof_ref,'account_response_metadata_ref':account_response_metadata_ref,
            'creator_capture_ref':capture_ref,'creator_capture_receipt_ref':ev['capture_receipt_ref'],'creator_raw_ref':meta['raw_ref'],
            'creator_response_metadata_ref':headerref,'raw_ref':p['raw_ref'],'native_work_evidence':ev,
            'native_AID':a['aid'],'native_ptime_epoch':a['ptime'],'published_at_source':'native_Archive.ptime',
            'original_snapshot_publication_verified':p['publication_verified'],'original_publisher_ack_recovered':p['publisher_ack_recovered'],
            'title_sha256':sha(a['title']),'not_a_publisher_ack':True,'mature_metric_window':None,'learning_eligible':False,'strategy_eligible':False}
        if detail_ref is not None:metadata['detail_response_metadata_ref']=detail_ref
        identities.append({'platform':'bilibili','account_id':account,'internal_account_alias':alias,'platform_content_id':bvid,
            'canonical_url':'https://www.bilibili.com/video/'+bvid,'published_at':published,'verification_level':'native_verified',
            'identity_source':'native_owned_history_snapshot','metadata':metadata})
    if bool(capture.get('detail_header_ref'))!=detail_used:raise ValueError('bilibili_history_original_detail_not_accounted')
    return {'version':'native_publication_history_audit_v1','identities':identities,'identity_count':len(identities),
            'native_proof_files_read':len(cache)+1,'publisher_ack_created':False,'metric_windows_created':0,'learning_eligible':False,'strategy_eligible':False}


def _audit_mastodon_full_visible_publication_history(binding,snapshot_rows,*,account_response_metadata_ref,
        page_commit_refs,read,digest,timestamp,origin,proof_ref,proof,catalog_ref,catalog,cache):
    """Interpret only the typed full-status schema; true-filter legacy history stays separate."""
    import hashlib,re
    from urllib.parse import urlsplit,parse_qsl
    cfg=binding['config'];account=cfg['account_id'];alias=binding['account_key'];status_path='/api/v1/accounts/'+account+'/statuses'
    scope=catalog.get('scope')or{}
    if(catalog.get('platform')!='mastodon'or catalog.get('native_account_id')!=account or catalog.get('internal_account_alias')!=alias
        or catalog.get('account_identity_ref')!=proof_ref or catalog.get('status')!='token_visible_catalog_complete'
        or catalog.get('next_url')is not None or scope.get('token_visible_catalog_complete')is not True
        or scope.get('endpoint_filter')!={'limit':40,'exclude_reblogs':False,'exclude_replies':False}
        or scope.get('full_account_all_visibility_coverage_verified')is not False):
        raise ValueError('native_full_history_registered_complete_catalog_required')
    def page_endpoint(meta):
        if(not isinstance(meta,dict)or meta.get('method')!='GET'or type(meta.get('status'))is not int or meta['status']!=200
            or meta.get('actual_url')!=meta.get('url')or not isinstance(meta.get('authentication'),str)or not meta['authentication']
            or meta.get('response_complete_under_limit')is not True or meta.get('body_read_error_type')is not None):
            raise ValueError('native_full_history_complete_authenticated_HTTP200_required')
        timestamp(meta.get('captured_at'));return page_url(meta['url'])
    def page_url(url):
        u=urlsplit(str(url));pairs=parse_qsl(u.query,keep_blank_values=True);q=dict(pairs)
        if(u.scheme!='https'or u.netloc!=origin.netloc or u.username or u.password or u.fragment or u.path!=status_path
            or len(q)!=len(pairs)or set(q)-{'limit','max_id','exclude_reblogs','exclude_replies'}or q.get('limit')!='40'
            or any(q.get(k,'false')!='false'for k in('exclude_reblogs','exclude_replies'))
            or('max_id'in q and re.fullmatch('[0-9]{1,80}',q['max_id'])is None)):
            raise ValueError('native_full_history_original_false_filter_endpoint_required')
        return(u.scheme,u.netloc,u.path,tuple(sorted(dict(q,exclude_reblogs='false',exclude_replies='false').items())))
    def next_link(meta):
        header=next((v for k,v in(meta.get('headers')or{}).items()if k.lower()=='link'),'')
        found=re.findall(r'<([^>]+)>\s*;\s*rel="next"',header)
        if len(found)>1:raise ValueError('native_full_history_ambiguous_next_Link')
        if not found:return None
        page_url(found[0]);return found[0]
    def native_id(v):return isinstance(v,str)and re.fullmatch('[0-9]{1,80}',v)is not None
    if not isinstance(page_commit_refs,(list,tuple))or not 1<=len(page_commit_refs)<=1000:
        raise ValueError('native_full_history_all_page_commits_required')
    commits={}
    for ref in page_commit_refs:
        commit=read(ref);key=(commit.get('result_ref')or{}).get('sha256')if isinstance(commit,dict)else None
        if not isinstance(key,str)or key in commits:raise ValueError('native_full_history_unique_page_commit_required')
        timestamp(commit.get('committed_at'));commits[key]=(commit,ref)
    pages=catalog.get('pages');all_normalized=catalog.get('statuses')
    if(not isinstance(pages,list)or not 1<=len(pages)<=1000 or len(pages)!=len(commits)
       or not isinstance(all_normalized,list)):
        raise ValueError('native_full_history_complete_page_inventory_required')
    expected_url=origin.geturl().rstrip('/')+status_path+'?limit=40&exclude_reblogs=false&exclude_replies=false'
    used_urls=set();seen_ids=set();posts={};normalized_all=[]
    for number,page in enumerate(pages,1):
        if not isinstance(page,dict)or page.get('page')!=number:raise ValueError('native_full_history_original_page_order_required')
        result_ref=page.get('result_ref');result_sha=result_ref.get('sha256')if isinstance(result_ref,dict)else None
        if result_sha not in commits:raise ValueError('native_full_history_missing_page_commit')
        commit,commit_ref=commits[result_sha];meta_ref=page.get('metadata_ref');meta=read(meta_ref)
        signature=page_endpoint(meta)
        if expected_url is None or page.get('url')!=expected_url or meta.get('url')!=expected_url or signature in used_urls:
            raise ValueError('native_full_history_actual_Link_chain_or_cycle_mismatch')
        used_urls.add(signature)
        if commit!=page or timestamp(commit['committed_at'])<timestamp(meta['captured_at']):raise ValueError('native_full_history_original_page_commit_mismatch')
        raw_ref=page.get('raw_ref')
        if raw_ref!=meta.get('raw_ref'):raise ValueError('native_full_history_page_raw_binding_mismatch')
        raw=read(raw_ref);result=read(result_ref)
        if not isinstance(raw,list)or len(raw)>40:raise ValueError('native_full_history_complete_raw_array_required')
        if(not isinstance(result,dict)or result.get('schema')!='mastodon_full_original_statuses_page_v1'
            or result.get('account_id')!=account or result.get('raw_ref')!=raw_ref or result.get('native_count')!=len(raw)
            or page.get('native_count')!=len(raw)or not isinstance(result.get('posts'),list)or len(result['posts'])!=len(raw)):
            raise ValueError('native_full_history_typed_normalized_page_required')
        following=next_link(meta)
        if(result.get('next_url')!=following or page.get('next_url')!=following
            or page.get('terminal_boundary_confirmed')is not(following is None and len(raw)<40)):
            raise ValueError('native_full_history_original_cursor_boundary_mismatch')
        if number<len(pages)and following is None:raise ValueError('native_full_history_page_after_terminal_forbidden')
        if number==len(pages)and(following is not None or len(raw)>=40):raise ValueError('native_full_history_missing_terminal_boundary')
        for native,normalized in zip(raw,result['posts']):
            if(not isinstance(native,dict)or not native_id(native.get('id'))or native['id']in seen_ids
                or not isinstance(native.get('account'),dict)or native['account'].get('id')!=account
                or not isinstance(normalized,dict)):
                raise ValueError('native_full_history_unique_own_top_level_status_required')
            content_id=native['id'];seen_ids.add(content_id);boost=native.get('reblog')is not None
            if boost and not isinstance(native['reblog'],dict):raise ValueError('native_full_history_native_reblog_object_required')
            reply=native.get('in_reply_to_id');reply_account=native.get('in_reply_to_account_id')
            if(reply is not None and not native_id(reply))or(reply_account is not None and not native_id(reply_account)):
                raise ValueError('native_full_history_native_reply_relationship_required')
            metrics={k:native.get(k)for k in('favourites_count','reblogs_count','replies_count')}
            if any(v is not None and(type(v)is not int or v<0)for v in metrics.values()):raise ValueError('native_full_history_native_metric_type_invalid')
            required={'kind':'native_owned_status_lifetime_snapshot','platform':'mastodon','native_account_id':account,'internal_account_alias':alias,
                'platform_content_id':content_id,'canonical_url':native.get('url')or native.get('uri'),'published_at':native.get('created_at'),
                'observed_at':meta['captured_at'],'visibility':native.get('visibility'),'content_html':native.get('content'),'language':native.get('language'),
                'native_url':native.get('url'),'native_uri':native.get('uri'),'is_reblog':boost,
                'reblog_target_id':(native.get('reblog')or{}).get('id'),'reblog_target_native_account_id':((native.get('reblog')or{}).get('account')or{}).get('id'),
                'in_reply_to_id':reply,'in_reply_to_account_id':reply_account,'native_metrics':metrics,
                'missing_native_metrics':[k for k,v in metrics.items()if v is None],'raw_ref':raw_ref,'learning_eligible':False,'mature_metric_window':None}
            if digest(normalized)!=digest(required)or type(normalized.get('is_reblog'))is not bool:
                raise ValueError('native_full_history_original_raw_and_full_normalization_mismatch')
            if timestamp(required['published_at'])>timestamp(meta['captured_at']):raise ValueError('native_full_history_publish_after_capture')
            normalized_all.append(normalized);posts[content_id]=(native,normalized,meta,meta_ref,result_ref,raw_ref,commit_ref)
        expected_url=following
    if(normalized_all!=all_normalized or catalog.get('observed_unique_statuses')!=len(seen_ids)
        or catalog.get('authored_original_including_replies_count')!=sum(not p['is_reblog']for p in normalized_all)
        or catalog.get('reblog_wrapper_count')!=sum(p['is_reblog']for p in normalized_all)
        or catalog.get('authored_reply_count')!=sum(not p['is_reblog']and p['in_reply_to_id']is not None for p in normalized_all)
        or catalog.get('authored_nonreply_count')!=sum(not p['is_reblog']and p['in_reply_to_id']is None for p in normalized_all)):
        raise ValueError('native_full_history_complete_catalog_count_or_classification_mismatch')
    if not isinstance(snapshot_rows,list)or not 1<=len(snapshot_rows)<=1000:raise ValueError('native_history_bounded_existing_snapshots_required')
    identities=[];seen=set();urls=set()
    for row in snapshot_rows:
        if not isinstance(row,dict)or type(row.get('id'))is not int or row['id']<=0 or row.get('platform')!='mastodon':
            raise ValueError('native_history_existing_platform_snapshot_required')
        p=row.get('payload')
        if p is None:
            import json
            try:p=json.loads(row['payload_json'])
            except(KeyError,ValueError,TypeError)as exc:raise ValueError('native_history_existing_snapshot_payload_required')from exc
        if(not isinstance(p,dict)or p.get('kind')!='native_owned_post_lifetime_snapshot'or p.get('platform')!='mastodon'
            or p.get('native_account_id')!=account or p.get('account_id')!=account or p.get('internal_account_alias')!=alias
            or p.get('learning_eligible')is not False or p.get('strategy_eligible')is not False or p.get('mature_metric_window')is not None):
            raise ValueError('native_history_owned_lifetime_snapshot_scope_mismatch')
        content_id=p.get('platform_content_id')
        if not native_id(content_id)or content_id in seen or content_id not in posts:raise ValueError('native_history_exact_unique_native_content_id_required')
        seen.add(content_id);native,normalized,meta,meta_ref,result_ref,raw_ref,commit_ref=posts[content_id]
        if native.get('reblog')is not None or native.get('visibility')not in{'public','unlisted'}:
            raise ValueError('native_history_owned_public_or_unlisted_original_required')
        expected=dict(normalized);expected['kind']='native_owned_post_lifetime_snapshot'
        if(not set(expected)<=set(p)or digest({k:p[k]for k in expected})!=digest(expected)
            or p.get('raw_ref')!=raw_ref or p.get('header_ref')!=meta_ref or p.get('native_result_ref')!=result_ref):
            raise ValueError('native_full_history_existing_snapshot_original_evidence_mismatch')
        body=native.get('content');url=native.get('url')or native.get('uri');u=urlsplit(url if isinstance(url,str)else'')
        if(not isinstance(body,str)or not body.strip()or u.scheme!='https'or u.netloc!=origin.netloc or u.username or u.password or u.query or u.fragment
            or u.path.rstrip('/').split('/')[-1]!=content_id or url in urls):
            raise ValueError('native_full_history_actual_owned_content_URL_or_native_ID_mismatch')
        urls.add(url)
        is_reply=native.get('in_reply_to_id')is not None
        metadata={'evidence_type':'authenticated_native_status_history','native_evidence_schema':'mastodon_original_visible_statuses_full_observation_v1',
            'native_publication_kind':'authored_reply'if is_reply else'authored_post','in_reply_to_id':native.get('in_reply_to_id'),
            'in_reply_to_account_id':native.get('in_reply_to_account_id'),'visibility':native['visibility'],
            'source_snapshot_id':row['id'],'snapshot_recording_job_id':row.get('job_id'),'source_snapshot_payload_sha256':digest(p),'observed_at':p['observed_at'],
            'account_proof_ref':proof_ref,'account_response_metadata_ref':account_response_metadata_ref,'catalog_ref':catalog_ref,
            'raw_ref':raw_ref,'response_metadata_ref':meta_ref,'native_result_ref':result_ref,'page_commit_ref':commit_ref,
            'content_html_sha256':hashlib.sha256(body.encode()).hexdigest(),'not_a_publisher_ack':True,'mature_metric_window':None,'learning_eligible':False,'strategy_eligible':False}
        identities.append({'platform':'mastodon','account_id':account,'internal_account_alias':alias,'platform_content_id':content_id,'canonical_url':url,
            'published_at':native['created_at'],'verification_level':'native_verified','identity_source':'native_owned_history_snapshot','metadata':metadata})
    return {'version':'native_publication_history_audit_v1','identities':identities,'identity_count':len(identities),'native_proof_files_read':len(cache),
        'publisher_ack_created':False,'metric_windows_created':0,'learning_eligible':False,'strategy_eligible':False}
