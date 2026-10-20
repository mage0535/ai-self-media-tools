"""Current Hermes platform copy, bound to native messages and the original long draft."""
import hashlib,json,os,re,sqlite3
from pathlib import Path
from .factual_candidate_revision import digest,private_read,write_once,current_generation_records

VERSION='twitter-native-target-adaptation-v1'
NORMALIZED='499741e1e77470353f7ed83f1c9ea0bd9d344152e30dc75b9e97b8ffc63b0518'
GENSHA='c0dc812e7cbd8394c3dfae3fc1c48fe39455a38ad162edfd2bd54ee3bdfb838f'
JOB='25110343c3354385'

def parse_target(raw):
    if not isinstance(raw,str):raise ValueError('target_native_final_text_required')
    text=raw.strip()
    if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
    value=json.loads(text)
    if not isinstance(value,dict)or set(value)!={'caption','cta','hashtags'}:raise ValueError('target_exact_caption_schema_required')
    caption=value['caption'];cta=value['cta'];tags=value['hashtags']
    if not isinstance(caption,str)or caption!=caption.strip()or not 8<=len(caption)<=275:raise ValueError('target_caption_8_to_275_required')
    if not isinstance(cta,str)or not cta.strip()or cta not in caption:raise ValueError('target_literal_answerable_cta_required')
    if (not isinstance(tags,list)or not 1<=len(tags)<=2 or len(set(tags))!=len(tags)
            or any(not isinstance(tag,str)or not re.fullmatch(r'#[A-Za-z][A-Za-z0-9_]*',tag)or tag not in caption for tag in tags)
            or re.findall(r'(?<!\w)#[A-Za-z][A-Za-z0-9_]*',caption)!=tags):raise ValueError('target_one_or_two_literal_hashtags_required')
    return value

def native_session(home,sid):
    db=Path(home)/'state.db'
    if any(p.is_symlink()for p in(db,*db.parents)):raise PermissionError('target_native_session_symlink_rejected')
    with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)as conn:
        conn.row_factory=sqlite3.Row
        row=conn.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
        if row is None:raise ValueError('target_native_session_missing')
        session=dict(row);messages=[dict(r)for r in conn.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id',(sid,))]
    finals=[r for r in messages if r.get('role')=='assistant'and not r.get('tool_calls')and isinstance(r.get('content'),str)and r['content'].strip()]
    if not finals:raise ValueError('target_native_final_assistant_missing')
    return session,messages,finals[-1]['content']

def _read_legacy_target_adaptation(job,platform):
    if str(platform).casefold()not in{'twitter','x'}or job.get('id')!=JOB:raise PermissionError('target_supported_source_job_required')
    if digest({'title':job.get('title'),'body':job.get('body')})!=NORMALIZED:raise ValueError('target_original_long_draft_changed')
    ref=(job.get('draft_meta')or{}).get('target_adaptation_ref')
    if not isinstance(ref,dict)or set(ref)!={'path','sha256'}:raise ValueError('target_native_copy_reference_required')
    record=private_read(ref['path'],ref['sha256'])
    task=record.get('task_id')
    if not isinstance(task,str)or not re.fullmatch('[a-f0-9]{32}',task):raise PermissionError('target_current_scope_reference_invalid')
    root=Path('/srv/hermes-worker-media/jobs')/task
    if Path(ref['path'])!=root/'twitter-target-copy.private.json':raise PermissionError('target_owned_copy_reference_required')
    if (record.get('version')!=VERSION or record.get('job_id')!=JOB or record.get('platform')!='twitter'
            or record.get('source_long_sha256')!=NORMALIZED or record.get('source_generation_ref',{}).get('sha256')!=GENSHA
            or record.get('no_publish')is not True):raise ValueError('target_native_source_binding_invalid')
    source=record['source_generation_ref'];original=private_read(source['path'],source['sha256'])
    if original.get('normalized_generation_sha256')!=NORMALIZED:raise ValueError('target_source_generation_changed')
    contextref=record['context_ref']
    if Path(contextref['path'])!=root/'twitter-target-context.private.json':raise PermissionError('target_owned_context_reference_required')
    context=private_read(contextref['path'],contextref['sha256'])
    if (context.get('job_id')!=JOB or context.get('source_generation_ref')!=source
            or digest(context.get('long_draft'))!=NORMALIZED or context.get('no_publish')is not True):raise ValueError('target_model_context_changed')
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+task)
    session,messages,raw=native_session(home,record['session_id'])
    if (session.get('model')!=record.get('model')or not session.get('ended_at')or type(session.get('api_call_count'))is not int
            or session['api_call_count']<=0 or session['api_call_count']!=record.get('api_call_count')
            or digest(session)!=record.get('session_sha256')or digest(messages)!=record.get('messages_sha256')
            or hashlib.sha256(raw.encode()).hexdigest()!=record.get('native_final_sha256')):raise ValueError('target_actual_native_session_changed')
    prompt=context.get('prompt')
    if (not isinstance(prompt,str)or hashlib.sha256(prompt.encode()).hexdigest()!=context.get('prompt_sha256')
            or not any(r.get('role')=='user'and isinstance(r.get('content'),str)and prompt in r['content'] for r in messages)):
        raise ValueError('target_native_user_context_not_bound')
    target=parse_target(raw)
    if target!=record.get('target')or hashlib.sha256(target['caption'].encode()).hexdigest()!=record.get('caption_sha256'):
        raise ValueError('target_caption_not_native_final')
    return dict(target,caption_sha256=record['caption_sha256'],target_copy_ref=ref,
                adaptation_session_ref={'task_id':task,'session_id':session['id'],'model':session['model'],
                                        'api_call_count':session['api_call_count'],'native_final_sha256':record['native_final_sha256']},
                source_generation_ref=source)

def _generate_legacy_target_adaptation(pipeline,job,draft,prepared,runner):
    from .native_quality_runner import current_active_role
    home,task,route=current_active_role(600)
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':raise PermissionError('target_no_publication_scope_required')
    if job.get('id')!=JOB or digest({'title':draft['title'],'body':draft['body']})!=NORMALIZED:raise ValueError('target_original_long_draft_required')
    source=draft.get('draft_meta',{}).get('factual_revision_generation_ref')
    if not isinstance(source,dict)or source.get('sha256')!=GENSHA:raise ValueError('target_original_generation_reference_required')
    source_record=private_read(source['path'],source['sha256'])
    if source_record.get('normalized_generation_sha256')!=NORMALIZED:raise ValueError('target_original_generation_reference_changed')
    if (pipeline.generator.config.get('hermes_provider')!=route['provider']or pipeline.generator.config.get('hermes_model')!=route['model']
            or pipeline.generator.config.get('allow_fallback')is not False):raise ValueError('target_actual_current_route_required')
    context={'job_id':JOB,'platform':'twitter','production_intent':prepared.get('production_intent'),
             'long_draft':{'title':draft['title'],'body':draft['body']},'source_generation_ref':source,
             'claim_ledger':prepared.get('claim_ledger')or[],'outcome':'verification_required','no_publish':True,
             'requirements':{'caption_max_chars':275,'hashtags_min':1,'hashtags_max':2,'complete_caption':True,'no_truncation':True}}
    instruction=('Return only JSON with exactly caption, cta, hashtags. Write one complete English Twitter caption, 8..275 characters total including '
                 'one or two hashtags and a concrete answerable CTA verbatim. The intent is checking report delivery receipts, matching the intended file, '
                 'version and recipient before marking delivery verified. Use the long draft only as research; it is a proposed method, not lived experience '
                 'or measured results. Do not invent numbers, firsthand operations, outcomes, future episodes, or publication commitments. '
                 'Include three short concrete checks with line breaks: task ID, file version, recipient; missing evidence stays unconfirmed. Do not paraphrase unrelated TikTok marketing material. Preserve missing evidence as unconfirmed. Do not call tools or publish.\n')
    prompt=instruction+json.dumps(context,ensure_ascii=False,sort_keys=True)
    context['prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest();context['prompt']=prompt
    root=Path('/srv/hermes-worker-media/jobs')/task
    contextref=write_once(root/'twitter-target-context.private.json',context)
    before={r['id']for r in current_generation_records(home,allow_absent=True)}
    returned=pipeline.generator._call_hermes_text(prompt,prepared)
    parsed=parse_target(returned)
    new=[r for r in current_generation_records(home)if r['id']not in before and not r.get('parent_session_id')]
    if len(new)!=1:raise ValueError('target_unique_new_native_session_required')
    session,messages,raw=native_session(home,new[0]['id'])
    if (session.get('model')!=route['model']or not session.get('ended_at')or type(session.get('api_call_count'))is not int
            or session['api_call_count']<=0 or parse_target(raw)!=parsed
            or not any(r.get('role')=='user'and isinstance(r.get('content'),str)and prompt in r['content'] for r in messages)):raise ValueError('target_current_native_final_route_or_content_invalid')
    _,current,_=current_active_role(0)
    if current!=task:raise PermissionError('target_current_role_changed')
    record={'version':VERSION,'job_id':JOB,'platform':'twitter','task_id':task,'model':session['model'],
            'session_id':session['id'],'api_call_count':session['api_call_count'],'started_at':session['started_at'],'ended_at':session['ended_at'],
            'session_sha256':digest(session),'messages_sha256':digest(messages),'native_final_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'source_generation_ref':source,'source_long_sha256':NORMALIZED,'context_ref':contextref,'target':parsed,
            'caption_sha256':hashlib.sha256(parsed['caption'].encode()).hexdigest(),'no_publish':True,'semantic_review_required':True}
    ref=write_once(root/'twitter-target-copy.private.json',record)
    return ref

NORMAL_PRIMARY='normal-native-primary-generation-v1'
NORMAL_TARGET='normal-twitter-native-target-adaptation-v2'

def _normal_root(task,job_id):
    if not isinstance(job_id,str)or not re.fullmatch('[A-Za-z0-9_-]{1,128}',job_id):
        raise ValueError('normal_target_job_identifier_invalid')
    if not isinstance(task,str)or not re.fullmatch('[a-f0-9]{32}',task):
        raise ValueError('normal_target_task_identifier_invalid')
    return Path('/srv/hermes-worker-media/jobs')/task

def _normal_guard(pipeline,job_id,task=None,owner=None):
    from .native_quality_runner import current_active_role
    from datetime import datetime,timezone
    home,current,route=current_active_role(0)
    if task is not None and current!=task:raise PermissionError('normal_target_current_role_changed')
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':
        raise PermissionError('normal_target_no_publication_required')
    job=pipeline.store.get_job(job_id);actual_owner=job.get('lease_owner')or''
    if (job.get('state')!='generating'or not actual_owner.startswith(str(os.getpid())+'-')
            or(owner is not None and actual_owner!=owner)):
        raise PermissionError('normal_target_actual_generation_lease_required')
    expiry=datetime.fromisoformat((job.get('lease_expires_at')or'').replace('Z','+00:00'))
    if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):
        raise PermissionError('normal_target_original_lease_expired')
    cfg=pipeline.generator.config
    if (cfg.get('provider')!='hermes-cli'or cfg.get('hermes_provider')!=route['provider']
            or cfg.get('hermes_model')!=route['model']or cfg.get('allow_fallback')is not False):
        raise PermissionError('normal_target_current_sdk_route_required')
    return home,current,route,actual_owner

def generate_normal_twitter_draft(pipeline,job_id,topic,platform,prepared):
    """Normal primary generation with actual SID/final/normalization provenance."""
    home,task,route,owner=_normal_guard(pipeline,job_id)
    root=_normal_root(task,job_id)
    prepared_ref=write_once(root/('normal-primary-'+job_id+'-twitter.input.private.json'),prepared)
    before={row['id']for row in current_generation_records(home,allow_absent=True)}
    pipeline.generator._last_provider_normalization=None
    draft=pipeline.generator.generate(topic,prepared,stage_job_id=job_id)
    _normal_guard(pipeline,job_id,task,owner)
    new=[row for row in current_generation_records(home)if row['id']not in before and not row.get('parent_session_id')]
    if len(new)!=1:raise ValueError('normal_primary_unique_native_session_required')
    session,messages,raw=native_session(home,new[0]['id'])
    normalized=pipeline.generator._last_provider_normalization
    if (session.get('model')!=route['model']or not session.get('ended_at')
            or type(session.get('api_call_count'))is not int or session['api_call_count']<=0
            or not isinstance(normalized,dict)or normalized.get('provider')!='hermes-cli'
            or normalized.get('stage_job_id')!=job_id
            or normalized.get('normalized_title')!=draft.get('title')
            or normalized.get('normalized_body')!=draft.get('body')):
        raise ValueError('normal_primary_current_native_normalization_required')
    parsed=pipeline.generator._coerce_provider_draft(pipeline.generator._bounded_provider_content(raw,prepared),topic)
    observed={'title':str(parsed.get('title')or''),'body':str(parsed.get('body')or'')}
    if observed!=normalized.get('provider_input'):
        raise ValueError('normal_primary_native_final_normalization_mismatch')
    record={'version':NORMAL_PRIMARY,'job_id':job_id,'platform':'twitter','task_id':task,
        'provider':route['provider'],'model':session['model'],'session_id':session['id'],
        'api_call_count':session['api_call_count'],'session_sha256':digest(session),
        'messages_sha256':digest(messages),'native_final_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'provider_input_sha256':digest(observed),'prepared_input_ref':prepared_ref,
        'normalized_generation_sha256':digest({'title':draft['title'],'body':draft['body']}),
        'no_publish':True,'generation_stage_only':True}
    ref=write_once(root/('normal-primary-'+job_id+'-twitter.private.json'),record)
    draft.setdefault('draft_meta',{})['normal_generation_source_ref']=ref
    return draft

def _normal_primary_record(job):
    if (job.get('draft_meta') or {}).get('caption_revision_source_ref'):
        from .native_stage_resume import caption_revision_source
        return caption_revision_source(job)
    job_id=job.get('id');meta=job.get('draft_meta')or{}
    if meta.get('normal_factual_revision_ref'):
        from .native_stage_resume import read_factual_revision_source
        return read_factual_revision_source(job)
    ref=meta.get('normal_generation_source_ref')
    if not isinstance(ref,dict)or set(ref)!={'path','sha256'}:
        raise ValueError('normal_primary_native_source_reference_required')
    record=private_read(ref['path'],ref['sha256'])
    root=_normal_root(record.get('task_id'),job_id)
    if (Path(ref['path'])!=root/('normal-primary-'+job_id+'-twitter.private.json')
            or record.get('version')!=NORMAL_PRIMARY or record.get('job_id')!=job_id
            or record.get('platform')!='twitter'or record.get('no_publish')is not True
            or record.get('normalized_generation_sha256')!=digest({'title':job.get('title'),'body':job.get('body')})):
        raise ValueError('normal_primary_current_long_draft_binding_invalid')
    inputref=record['prepared_input_ref']
    if Path(inputref['path'])!=root/('normal-primary-'+job_id+'-twitter.input.private.json'):
        raise ValueError('normal_primary_input_reference_invalid')
    private_read(inputref['path'],inputref['sha256'],limit=4194304)
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+record['task_id'])
    session,messages,raw=native_session(home,record['session_id'])
    if (session.get('model')!=record.get('model')or not session.get('ended_at')
            or type(session.get('api_call_count'))is not int or session['api_call_count']<=0
            or session['api_call_count']!=record.get('api_call_count')
            or digest(session)!=record.get('session_sha256')or digest(messages)!=record.get('messages_sha256')
            or hashlib.sha256(raw.encode()).hexdigest()!=record.get('native_final_sha256')):
        raise ValueError('normal_primary_actual_native_record_changed')
    return ref,record

def _generate_normal_target(pipeline,job,draft,prepared,runner):
    job_id=job['id'];home,task,route,owner=_normal_guard(pipeline,job_id)
    current=dict(job,title=draft['title'],body=draft['body'],draft_meta=draft.get('draft_meta')or{})
    source,original=_normal_primary_record(current)
    long_sha=digest({'title':draft['title'],'body':draft['body']})
    context={'job_id':job_id,'platform':'twitter','production_intent':prepared.get('production_intent'),
        'content_blueprint':prepared.get('content_blueprint'),'language':prepared.get('language')or draft.get('draft_meta',{}).get('language'),
        'long_draft':{'title':draft['title'],'body':draft['body']},'source_generation_ref':source,
        'claim_ledger':prepared.get('claim_ledger')or[],'no_publish':True,
        'requirements':{'caption_max_chars':275,'hashtags_min':1,'hashtags_max':2,'complete_caption':True,'no_truncation':True}}
    instruction=('Return JSON with exactly caption, cta, hashtags. Produce a complete Twitter caption in the current language, '
        '8..275 characters total including one or two hashtags and a specific answerable CTA verbatim. '
        'Use only the current topic, scenario, source-backed facts and blueprint below. The long draft is research, not the publication copy. '
        'Preserve uncertainty, boundaries, and missing verification. Do not invent metrics, first-person experience or completed outcomes. '
        'Do not copy reference posts, truncate a long article, call tools or publish.\n')
    intent=prepared.get('production_intent')or{};topic=str(intent.get('topic')or job.get('topic')or'')
    if re.search(r'报表|report',topic,re.I)and re.search(r'回执|delivery\s+receipt',topic,re.I):
        instruction+=('For this report delivery receipt scene, include a short heading followed by three lines beginning exactly '
            '"Task ID:", "File version:", and "Recipient:". Each is a concrete comparison that remains match or unconfirmed, '
            'not a claim of a verified delivery. Keep the heading distinct from those three field lines.\n')
    revision_ref=(draft.get('draft_meta')or{}).get('caption_revision_source_ref')
    if revision_ref:
        from .native_stage_resume import validate_caption_revision
        proof,history=validate_caption_revision(pipeline.store,revision_ref,child_id=job_id,live=True)
        context['caption_revision']={'intent':proof['intent'],'instruction':proof['instruction'],
            'original_caption':history['old_target']['caption'],'parent_draft_id':proof['parent_draft_id'],
            'new_action':True,'original_success_replayed':False,'facts_observed_at_unchanged':True}
    prompt=instruction+json.dumps(context,ensure_ascii=False,sort_keys=True)
    context.update(prompt=prompt,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
    root=_normal_root(task,job_id)
    contextref=write_once(root/('twitter-target-'+job_id+'.context.private.json'),context)
    before={row['id']for row in current_generation_records(home,allow_absent=True)}
    revision_ref=(draft.get('draft_meta')or{}).get('caption_revision_source_ref')
    budget={}
    if revision_ref:
        from .native_stage_resume import validate_caption_revision,caption_revision_stage_budget
        proof,history=validate_caption_revision(pipeline.store,revision_ref,child_id=job_id,live=True)
        budget={'bounded_budget_seconds':caption_revision_stage_budget(pipeline.store,job_id,120)}
    returned=pipeline.generator._call_hermes_text(prompt,prepared,bounded_stage='target_caption',**budget);target=parse_target(returned)
    if revision_ref and target['caption']==history['old_target']['caption']:
        raise ValueError('caption_revision_new_caption_change_required')
    _normal_guard(pipeline,job_id,task,owner)
    new=[row for row in current_generation_records(home)if row['id']not in before and not row.get('parent_session_id')]
    if len(new)!=1:raise ValueError('normal_target_unique_new_native_session_required')
    session,messages,raw=native_session(home,new[0]['id'])
    if (session.get('model')!=route['model']or not session.get('ended_at')
            or type(session.get('api_call_count'))is not int or session['api_call_count']<=0
            or parse_target(raw)!=target
            or not any(row.get('role')=='user'and isinstance(row.get('content'),str)and prompt in row['content']for row in messages)):
        raise ValueError('normal_target_actual_current_native_final_required')
    record={'version':NORMAL_TARGET,'job_id':job_id,'platform':'twitter','task_id':task,
        'provider':route['provider'],'model':session['model'],'session_id':session['id'],
        'api_call_count':session['api_call_count'],'session_sha256':digest(session),'messages_sha256':digest(messages),
        'native_final_sha256':hashlib.sha256(raw.encode()).hexdigest(),'source_generation_ref':source,
        'source_long_sha256':long_sha,'context_ref':contextref,'target':target,
        'caption_sha256':hashlib.sha256(target['caption'].encode()).hexdigest(),'no_publish':True,'semantic_review_required':True}
    return write_once(root/('twitter-target-'+job_id+'.copy.private.json'),record)

def _read_normal_target(job,ref,record):
    job_id=job.get('id');root=_normal_root(record.get('task_id'),job_id)
    if (Path(ref['path'])!=root/('twitter-target-'+job_id+'.copy.private.json')
            or record.get('job_id')!=job_id or record.get('platform')!='twitter'or record.get('no_publish')is not True
            or record.get('source_long_sha256')!=digest({'title':job.get('title'),'body':job.get('body')})):
        raise ValueError('normal_target_current_candidate_binding_invalid')
    source,_=_normal_primary_record(job)
    if source!=record.get('source_generation_ref'):raise ValueError('normal_target_primary_source_changed')
    contextref=record['context_ref']
    if Path(contextref['path'])!=root/('twitter-target-'+job_id+'.context.private.json'):
        raise ValueError('normal_target_context_reference_invalid')
    context=private_read(contextref['path'],contextref['sha256'],limit=4194304)
    if (context.get('job_id')!=job_id or context.get('source_generation_ref')!=source
            or digest(context.get('long_draft'))!=record['source_long_sha256']or context.get('no_publish')is not True):
        raise ValueError('normal_target_native_context_changed')
    home=Path('/srv/hermes-worker/authority-runtime-homes')/('media-'+record['task_id'])
    session,messages,raw=native_session(home,record['session_id'])
    prompt=context.get('prompt')
    if (session.get('model')!=record.get('model')or not session.get('ended_at')
            or type(session.get('api_call_count'))is not int or session['api_call_count']<=0
            or session['api_call_count']!=record.get('api_call_count')
            or digest(session)!=record.get('session_sha256')or digest(messages)!=record.get('messages_sha256')
            or hashlib.sha256(raw.encode()).hexdigest()!=record.get('native_final_sha256')
            or not isinstance(prompt,str)or hashlib.sha256(prompt.encode()).hexdigest()!=context.get('prompt_sha256')
            or not any(row.get('role')=='user'and isinstance(row.get('content'),str)and prompt in row['content']for row in messages)):
        raise ValueError('normal_target_actual_native_context_or_session_changed')
    target=parse_target(raw)
    if target!=record.get('target')or hashlib.sha256(target['caption'].encode()).hexdigest()!=record.get('caption_sha256'):
        raise ValueError('normal_target_caption_not_native_final')
    return dict(target,caption_sha256=record['caption_sha256'],target_copy_ref=ref,
        adaptation_session_ref={'task_id':record['task_id'],'session_id':session['id'],'model':session['model'],
            'api_call_count':session['api_call_count'],'native_final_sha256':record['native_final_sha256']},
        source_generation_ref=source)

def read_target_adaptation(job,platform):
    if job.get('_caption_revision_historical_ref'):
        from .native_stage_resume import caption_revision_historical_target
        return caption_revision_historical_target(job)
    if (job.get('draft_meta')or{}).get('normal_completed_target_checkpoint_ref'):
        from .native_stage_resume import read_completed_target_source_projection
        job=read_completed_target_source_projection(job)
    if str(platform).casefold()not in{'twitter','x'}:raise PermissionError('target_twitter_platform_required')
    ref=(job.get('draft_meta')or{}).get('target_adaptation_ref')
    if isinstance(ref,dict)and set(ref)=={'path','sha256'}:
        record=private_read(ref['path'],ref['sha256'])
        if record.get('version')==NORMAL_TARGET:return _read_normal_target(job,ref,record)
    return _read_legacy_target_adaptation(job,platform)

def generate_target_adaptation(pipeline,job,draft,prepared,runner):
    if ((draft.get('draft_meta')or{}).get('normal_generation_source_ref')
            or (draft.get('draft_meta')or{}).get('caption_revision_source_ref')):
        return _generate_normal_target(pipeline,job,draft,prepared,runner)
    return _generate_legacy_target_adaptation(pipeline,job,draft,prepared,runner)
