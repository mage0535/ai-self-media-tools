"""原生采集与同任务Store门禁→不可变视频preflight，不接受模型计数/通过marker。"""
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urldefrag,urlsplit
from datetime import datetime,timezone


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _sha256(value):
    return isinstance(value,str) and len(value)==64 and all(char in '0123456789abcdef' for char in value)


def _url_identity(value):
    url=str(value or '').strip()
    if urlsplit(url).scheme not in {'http','https'}:return None
    return ('url',hashlib.sha256(urldefrag(url)[0].encode()).hexdigest())


def research_attempts(trends,public):
    rows=[]
    for group,report in (('trends',trends),('public',public)):
        for source in report.get('sources') or []:
            name=str(source.get('source') or '')
            if not name:continue
            status=source.get('status')
            if status not in {'ok','failed','empty','degraded','rejected'}:continue
            provenance=source.get('fetch_provenance') or {}
            identities=set()
            if group=='trends':
                execution=[row for row in provenance.get('attempts') or [] if row.get('transport')=='http'
                    and row.get('status') in {'ok','failed'} and _sha256(row.get('request_sha256'))]
                if provenance.get('version')!='native_trend_fetch_v1' or not execution:continue
                identities.update(('http_request',row['request_sha256']) for row in execution)
                fresh=provenance.get('result_kind')=='live_http' and int(provenance.get('fresh_item_count') or 0)>0 and any(
                    row.get('status')=='ok' and _sha256(row.get('response_sha256')) and int(row.get('bytes') or 0)>0 for row in execution)
                if fresh:identities.update(('url',value) for value in provenance.get('source_url_sha256s') or [] if _sha256(value))
            else:
                imported=any(report.get('research_only') is True and source in (report.get('sources') or []) for report in public.get('reports') or [])
                if imported:continue
                # 原public原生adapter不返回cache；research_only导入从不作为实际采集成功。
                fresh=not source.get('research_only') and not source.get('source_unavailable') and not source.get('fallback')
                platform=str(source.get('platform') or '').strip();content_id=str(source.get('content_id') or '').strip()
                if platform and content_id:identities.add(('public_content',platform,content_id))
                linked=[source]+[item for item in report.get('items') or [] if platform and content_id
                    and str(item.get('platform') or '')==platform and str(item.get('content_id') or '')==content_id]
                for item in linked:
                    identity=_url_identity(item.get('canonical_url') or item.get('url'))
                    if identity:identities.add(identity)
            if not identities:continue
            report_sha=digest(source)
            candidate={'identity':[list(value) for value in sorted(identities)],'status':status,'count':int(source.get('count') or 0),
                'report_row_sha256':report_sha,'report_row_sha256s':[report_sha],'successful':fresh and status=='ok' and int(source.get('count') or 0)>0}
            matches=[index for index,row in enumerate(rows) if identities.intersection(map(tuple,row['identity']))]
            if not matches:rows.append(candidate);continue
            # 同一实际请求或来源URL只有一个计数；失败后真实成功可升级，所有原报告SHA保留。
            merged=[rows[index] for index in matches]+[candidate]
            for row in merged:identities.update(map(tuple,row['identity']))
            candidate=copy.deepcopy(min(merged,key=lambda row:(not row['successful'],row['report_row_sha256'])))
            candidate['identity']=[list(value) for value in sorted(identities)]
            candidate['report_row_sha256s']=sorted({value for row in merged for value in row['report_row_sha256s']})
            first=matches[0]
            for index in reversed(matches):rows.pop(index)
            rows.insert(first,candidate)
    return rows


def bind_research_snapshot(store,job,trends,public,workflows,collected_at):
    current=store.get_job(job['id'])
    if current.get('state')!='generating' or not current.get('lease_owner') or current.get('lease_owner')!=job.get('lease_owner'):
        raise ValueError('native_research_collection_lease_required')
    attempts=research_attempts(trends,public)
    if len(attempts)<5 or sum(row['successful'] for row in attempts)<3:
        raise ValueError('native_video_research_attempts_or_successes_insufficient')
    payload={'version':'native_video_research_snapshot_v1','job_id':job['id'],'collected_at':collected_at,
        'trends':trends,'public':public,'attempts':attempts,
        'technical_only':any(row.get('license_scope')=='technical_fixture' for row in public.get('items') or []),
        'production_verified':False,
        'topics':{platform:brief.get('topic_selection') or {} for platform,brief in workflows.items()}}
    root=store.path.parent/'jobs'/job['id']/'video-preflight';root.mkdir(parents=True,exist_ok=True)
    path=root/'native_research_snapshot.json';encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if path.exists() and path.read_bytes()!=encoded:raise ValueError('native_research_snapshot_immutable_conflict')
    if not path.exists():
        with path.open('xb') as stream:stream.write(encoded)
    ref={'job_id':job['id'],'path':str(path),'sha256':hashlib.sha256(encoded).hexdigest(),'producer':'native.collect_task_source_inputs'}
    store.record_event(job['id'],'native_video_research_snapshot_bound',ref)
    return ref


def read_bound_file(store,job_id,ref,event,platform=None):
    if not isinstance(ref,dict) or ref.get('job_id')!=job_id:raise ValueError('native_preflight_ref_job_mismatch')
    path=Path(ref.get('path') or '');root=store.path.parent/'jobs'/job_id/'video-preflight'
    if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=ref.get('sha256')):
        raise ValueError('native_preflight_file_or_sha_untrusted')
    matches=[json.loads(row['detail_json']) for row in store.events(job_id) if row['event']==event]
    if not any(row==ref for row in matches):raise ValueError('native_preflight_store_receipt_required')
    payload=json.loads(path.read_text(encoding='utf-8'))
    if payload.get('job_id')!=job_id or platform and payload.get('platform')!=platform:raise ValueError('native_preflight_payload_owner_mismatch')
    return payload


def _step(store,job_id,name):
    from .workflow_runtime import STEP_SUCCEEDED
    matches=[row for row in store.workflow_steps(job_id) if row['step_name']==name]
    if len(matches)!=1 or matches[0]['status']!=STEP_SUCCEEDED:
        if name=='generate_content' and len(matches)==1 and matches[0]['status']=='FAILED_FINAL':
            events=[json.loads(row['detail_json']) for row in store.events(job_id) if row['event']=='qualified_supplement_generation_receipt_bound']
            if len(events)!=1:raise ValueError('original_generation_supplement_receipt_required')
            event=events[0]
            import os
            scope_ref_path=os.environ.get('MEDIA_QUALIFIED_VISION_SCOPE_PATH')
            if scope_ref_path:
                from .original_knowledge import _bytes
                scope_ref=json.loads(_bytes(scope_ref_path,private=True))
                if scope_ref!=event['original_knowledge_ref']:
                    continued=[json.loads(row['detail_json']) for row in store.events(job_id)
                        if row['event']=='qualified_supplement_generation_receipt_continued']
                    continued=[row for row in continued if row.get('original_knowledge_ref')==scope_ref]
                    if (len(continued)!=1 or continued[0].get('parent_event_sha256')!=digest(event)
                            or continued[0].get('original_step_sha256')!=event['original_step_sha256']
                            or continued[0].get('output_sha256')!=event['output_sha256']):
                        raise ValueError('original_generation_continuation_parent_changed')
                    event=continued[0]
            from .original_knowledge import read_original_inputs
            proof=read_original_inputs(store,job_id,event['original_knowledge_ref'])
            if not proof.get('supplement') or event['original_step_sha256']!=digest(matches[0]):raise ValueError('original_generation_failed_row_changed')
            value,receipt=_step(store,job_id,'generate_content__official_cli_scope_continuation')
            if event['output_sha256']!=digest(value):raise ValueError('original_generation_supplement_output_changed')
            return value,receipt
        if name=='collect_native_source_inputs' and len(matches)==1 and matches[0]['status']=='BLOCKED':
            if matches[0].get('reason_code')=='source_original_knowledge_incomplete':
                events=[json.loads(row['detail_json']) for row in store.events(job_id)
                    if row['event']=='native_original_source_continuation_bound']
                if len(events)!=1:raise ValueError('original_source_continuation_receipt_required')
                event=events[0]
                from .original_knowledge import read_original_inputs
                read_original_inputs(store,job_id,event['original_knowledge_ref'])
                if event['original_step_sha256']!=digest(matches[0]):
                    raise ValueError('original_source_failed_row_changed')
                value,receipt=_step(store,job_id,event['alias'])
                if event['output_sha256']!=digest(value):
                    raise ValueError('original_source_continuation_output_changed')
                return value,receipt
            return store.resolve_source_repair_step(job_id,name)
        raise ValueError('native_preflight_gate_not_complete:'+name)
    row=matches[0];value=copy.deepcopy(row.get('output')) if isinstance(row.get('output'),dict) else json.loads(row.get('output_json') or '{}')
    return value,{'id':row['id'],'step_name':name,'output_sha256':digest(value),
        'finished_at':row.get('finished_at')}


def plan_contract(plan):
    result={key:plan.get(key) for key in ('visual_contract','video_asset_requirements','audio_plan','selected_pipeline','template_family')}
    if plan.get('content_mode')=='original_knowledge':
        result.update(content_mode='original_knowledge',original_knowledge_ref=plan.get('original_knowledge_ref'))
    return result


def bind_original_research_snapshot(store,job,brief,collected_at):
    from .original_knowledge import read_original_inputs
    proof=read_original_inputs(store,job['id'],brief['original_knowledge_ref'])
    payload={'version':'original_knowledge_research_snapshot_v1','content_mode':'original_knowledge',
        'job_id':job['id'],'collected_at':collected_at,'original_knowledge_ref':brief['original_knowledge_ref'],
        'topics':{'kuaishou':brief['topic_selection']},'production_verified':False,'technical_only':False}
    path=store.path.parent/'jobs'/job['id']/'video-preflight'/'original_research_snapshot.json'
    from .original_knowledge import _write,encoded
    record=_write(path,encoded(payload))
    ref={'job_id':job['id'],'path':record['path'],'sha256':record['sha256'],'producer':'native.collect_task_source_inputs'}
    store.record_event(job['id'],'native_video_research_snapshot_bound',ref)
    return ref


def bind_video_preflight(store,job,platform,brief,plan,script,owner):
    from .stage_input_refs import resolve_stage_payload
    from .video_planning_producer import read_bound_video_planning
    from .hot_viral_intelligence import build_hot_viral_intelligence
    job_id=job['id'];current=store.get_job(job_id)
    try:
        expiry=datetime.fromisoformat(current.get('lease_expires_at') or '')
        active_lease=expiry.tzinfo is not None and expiry>datetime.now(timezone.utc)
    except (ValueError,TypeError):active_lease=False
    supplement_ref=plan.get('original_knowledge_ref')
    supplement=bool(isinstance(supplement_ref,dict) and supplement_ref.get('producer')=='native.original_qualified_supplement')
    if supplement:
        from .original_knowledge import read_original_inputs
        supplement_proof=read_original_inputs(store,job_id,supplement_ref)
        if owner!='root-original-render-recovery' or current.get('state')!='failed' or current.get('lease_owner'):
            raise ValueError('native_supplement_failed_parent_required')
    elif not isinstance(owner,str) or not owner.strip() or current.get('state')!='generating' or current.get('lease_owner')!=owner or not active_lease:
        raise ValueError('native_preflight_job_lease_required')
    full=resolve_stage_payload(store,job_id,brief['run_contract'],'generate',brief['bounded_model_input'])
    blueprint=full.get('content_blueprint') or {}
    ref=blueprint.get('native_video_research_ref')
    snapshot=read_bound_file(store,job_id,ref,'native_video_research_snapshot_bound')
    original=blueprint.get('original_knowledge_ref')
    if supplement:
        from .original_knowledge import _bytes
        recipe=json.loads(_bytes(supplement_proof['supplement']['recipe_path'],supplement_proof['supplement']['recipe_sha256'],private=True))
        if original!=recipe['parent_original_knowledge_ref'] or snapshot.get('original_knowledge_ref')!=original:
            raise ValueError('native_supplement_parent_research_changed')
        blueprint=copy.deepcopy(blueprint);blueprint['original_knowledge_ref']=supplement_ref
        snapshot=copy.deepcopy(snapshot);snapshot['original_knowledge_ref']=supplement_ref
        original=supplement_ref
    if original:
        from .original_knowledge import read_original_inputs
        proof=read_original_inputs(store,job_id,original)
        if snapshot.get('content_mode')!='original_knowledge' or snapshot.get('original_knowledge_ref')!=original:
            raise ValueError('original_research_snapshot_changed')
        attempted=[{'successful':True,'identity':['official_fact_document',row['url']]} for row in proof['documents']]
    else:
        attempted=research_attempts(snapshot['trends'],snapshot['public'])
        if attempted!=snapshot['attempts']:raise ValueError('native_preflight_actual_attempts_changed')
    if supplement:
        planned=copy.deepcopy(blueprint.get('video_source_planning') or {})
        audit=planned.get('video_planning_audit') or {}
        if (audit.get('producer')!='native.original_knowledge_planner_v1'
                or audit.get('original_knowledge_ref')!=recipe['parent_original_knowledge_ref']
                or audit.get('script_sha256')!=hashlib.sha256(script.encode()).hexdigest()
                or planned.get('narration_script')!=script or planned.get('hot_viral_samples')
                or planned.get('hot_viral_source_statuses') or audit.get('execution_evidence_accepted') is not False):
            raise ValueError('native_supplement_frozen_planning_changed')
    else:
        planned=read_bound_video_planning(store,job_id,brief)
    if planned['video_script']!=script:raise ValueError('native_preflight_frozen_narration_changed')
    intelligence=({'status':'original_fact_ready','native_verified':False} if original else
        build_hot_viral_intelligence(target_platform=platform,lane=brief.get('lane') or 'real_world_ai_implementation',
            samples=planned['hot_viral_samples'],source_statuses=planned['hot_viral_source_statuses']))
    native=intelligence.get('native_verified') is True and intelligence.get('status')=='native_ready'
    topic=(snapshot.get('topics') or {}).get(platform) or {}
    if (topic!=brief.get('topic_selection') or topic.get('selected_topic')!=job['topic'] or topic.get('requested_topic')!=job['topic']
            or not topic.get('selection_reason')):raise ValueError('native_preflight_topic_not_bound')
    receipts={};outputs={}
    required_steps=('collect_native_source_inputs','run_content_hygiene','generate_content','validate_factual_claims','run_safety_gate','run_quality_gate')
    if original:required_steps+=('original_copy_dedup',)
    for name in required_steps:
        outputs[name],receipts[name]=_step(store,job_id,name)
    if outputs['run_content_hygiene'].get('status') not in {'pass','review'}:raise ValueError('native_preflight_topic_hygiene_not_validated')
    claims=outputs['validate_factual_claims'];risk=outputs['run_safety_gate'];quality=outputs['run_quality_gate']
    allow=claims.get('passed') is True and risk.get('level') in {'pass','review'} and quality.get('passed') is True
    narration=None
    for event in store.events(job_id):
        if event['event']=='native_platform_narrations_validated':narration=json.loads(event['detail_json']).get(platform)
    script_sha=hashlib.sha256(script.encode()).hexdigest()
    if (not narration or narration.get('script_sha256')!=script_sha or not (narration.get('claims') or {}).get('passed')
            or (narration.get('risk') or {}).get('level')=='block' or (narration.get('compliance') or {}).get('level')=='block'):
        raise ValueError('native_preflight_exact_script_safety_receipt_required')
    technical=any(row.get('license_scope')=='technical_fixture' for row in planned['hot_viral_samples'])
    payload={'version':'native_video_preflight_v1','job_id':job_id,'platform':platform,'technical_only':technical,'production_verified':False,
        'research_pack':{'attempted_sources':len(attempted),'successful_sources':sum(row['successful'] for row in attempted),
            'platform_native_verified':native,'native_intelligence_sha256':digest(intelligence),'native_research_ref':ref},
        'topic_selection':{'selected':True,'reason':topic['selection_reason'],'topic':topic['selected_topic'],'source_selection_sha256':digest(topic)},
        'content_brief':blueprint,'asset_plan':plan_contract(plan),'quality_gates':{'allow_render':allow,'native_step_receipts':receipts},
        'script_sha256':script_sha,'plan_contract_sha256':digest(plan_contract(plan))}
    if original:
        if plan.get('content_mode')!='original_knowledge' or plan.get('original_knowledge_ref')!=original:
            raise ValueError('original_render_plan_binding_changed')
        payload.update(content_mode='original_knowledge',original_knowledge_ref=original,
            original_facts={'official_document_count':len(proof['documents']),'self_created_execution_count':1})
    root=store.path.parent/'jobs'/job_id/'video-preflight';root.mkdir(parents=True,exist_ok=True);path=root/(platform+('-supplement-'+supplement_ref['sha256'][:16]+'.json' if supplement else '.json'))
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if path.exists() and path.read_bytes()!=encoded:raise ValueError('native_video_preflight_immutable_conflict')
    if not path.exists():
        with path.open('xb') as stream:stream.write(encoded)
    bound={'job_id':job_id,'platform':platform,'path':str(path),'sha256':hashlib.sha256(encoded).hexdigest()}
    store.record_event(job_id,'native_video_preflight_bound',bound)
    return bound


OVERNIGHT_PREFLIGHT_STEPS=('run_content_hygiene','generate_content','validate_factual_claims','run_safety_gate','run_quality_gate')


def bind_overnight_video_preflight(store,job,platform,brief,plan,script):
    """Overnight video lanes (11-03 r90: douyin_pet reached film_renderer for the first time and was refused
    'video_preflight.json missing'; only the native Kuaishou source step ever wrote one). The research pack is the
    overnight benchmark matrix in the brief; cross-platform evidence counts only when labelled with its source
    platform (owner rule 11-02). Same immutability, store receipt and step receipts as bind_video_preflight."""
    job_id=job['id'];matrix=brief.get('platform_source_matrix') or {}
    if str(matrix.get('platform') or '')!=platform:raise ValueError('overnight_preflight_matrix_platform_mismatch')
    scope=matrix.get('evidence_scope');labelled=str(matrix.get('candidate_source') or brief.get('cross_platform_source') or '')
    if scope not in {'platform_native','cross_platform'} or scope=='cross_platform' and not labelled:
        raise ValueError('overnight_preflight_evidence_scope_unlabelled')
    samples=brief.get('hot_viral_samples') or [];topic=str(brief.get('content_blueprint',{}).get('selected_topic') or '')
    if not samples or topic!=job['topic']:raise ValueError('overnight_preflight_topic_or_samples_not_bound')
    receipts={};outputs={}
    for name in OVERNIGHT_PREFLIGHT_STEPS:outputs[name],receipts[name]=_step(store,job_id,name)
    claims=outputs['validate_factual_claims'];risk=outputs['run_safety_gate'];quality=outputs['run_quality_gate']
    allow=(outputs['run_content_hygiene'].get('status') in {'pass','review'} and claims.get('passed') is True
        and risk.get('level') in {'pass','review'} and quality.get('passed') is True)
    script_sha=hashlib.sha256(script.encode()).hexdigest()
    payload={'version':'overnight_video_preflight_v1','job_id':job_id,'platform':platform,'production_verified':False,
        'research_pack':{'attempted_sources':int(matrix.get('sources_attempted') or 0),'successful_sources':int(matrix.get('sources_succeeded') or 0),
            'platform_native_verified':scope=='platform_native','evidence_scope':scope,'cross_platform_source':labelled if scope=='cross_platform' else '',
            'hot_viral_sample_count':len(samples),'hot_viral_samples_sha256':digest(samples),'source_matrix_sha256':digest(matrix)},
        'topic_selection':{'selected':True,'reason':str(matrix.get('platform_fit_reason') or ''),'topic':topic},
        'content_brief':brief.get('content_blueprint'),'asset_plan':plan_contract(plan),
        'quality_gates':{'allow_render':allow,'native_step_receipts':receipts},
        'script_sha256':script_sha,'plan_contract_sha256':digest(plan_contract(plan))}
    root=store.path.parent/'jobs'/job_id/'video-preflight';root.mkdir(parents=True,exist_ok=True);path=root/(platform+'.json')
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if path.exists() and path.read_bytes()!=encoded:raise ValueError('native_video_preflight_immutable_conflict')
    if not path.exists():
        with path.open('xb') as stream:stream.write(encoded)
    bound={'job_id':job_id,'platform':platform,'path':str(path),'sha256':hashlib.sha256(encoded).hexdigest()}
    store.record_event(job_id,'native_video_preflight_bound',bound)
    return bound


def materialize_video_preflight(store,job,plan,script,output_dir):
    from .video_preflight import validate_video_preflight
    platforms=job.get('platforms') or []
    if len(platforms)!=1:raise ValueError('native_preflight_single_platform_required')
    platform=platforms[0];ref=plan.get('video_preflight_ref')
    payload=read_bound_file(store,job['id'],ref,'native_video_preflight_bound',platform)
    if payload.get('script_sha256')!=hashlib.sha256(script.encode()).hexdigest() or payload.get('plan_contract_sha256')!=digest(plan_contract(plan)):
        raise ValueError('native_preflight_render_inputs_changed')
    for name,record in payload['quality_gates']['native_step_receipts'].items():
        value,actual=_step(store,job['id'],name)
        if actual!=record:raise ValueError('native_preflight_store_gate_revision_changed')
    path=Path(output_dir)/'video_preflight.json';encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if path.exists() and path.read_bytes()!=encoded:raise ValueError('route_native_preflight_conflict')
    if not path.exists():
        with path.open('xb') as stream:stream.write(encoded)
    validate_video_preflight(Path(output_dir),platform,store=store)
    return {'path':str(path),'sha256':hashlib.sha256(encoded).hexdigest()}
