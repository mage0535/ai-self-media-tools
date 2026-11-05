"""Bind frozen beat intent to native, one-shot pixel review; never synthesize quality."""
import copy
import hashlib
import json
import math
from pathlib import Path

from .asset_ledger import MIN_SEMANTIC_SCORE


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_requirement(requirement):
    if not isinstance(requirement,dict) or set(requirement)!={'intent','sha256'}:raise ValueError('semantic_requirement_fields_invalid')
    intent=requirement['intent']
    required={'beat_id','claim','semantic_subject','asset_role','content_match_reason','visual_mode','template_id','group_motion'}
    if (not isinstance(intent,dict) or set(intent)!=required or any(not intent.get(field) for field in required)
            or intent['asset_role']!='illustration' or intent['semantic_subject']!=intent['claim']
            or digest(intent)!=requirement['sha256']):raise ValueError('semantic_requirement_intent_changed')
    return copy.deepcopy(requirement)


def build_requirements(script,scenes):
    beats=[line.strip() for line in str(script).splitlines() if line.strip()]
    if len(beats)!=8 or not isinstance(scenes,list) or len(scenes)!=8:raise ValueError('semantic_requirement_beat_count')
    ids=[str(scene.get('beat_id') or scene.get('scene_id') or '').strip() for scene in scenes]
    if any(not value for value in ids) or len(set(ids))!=8:raise ValueError('semantic_requirement_beat_identity')
    result=[]
    for beat,identity,scene in zip(beats,ids,scenes):
        intent={'beat_id':identity,'claim':beat,'semantic_subject':beat,'asset_role':'illustration',
            'content_match_reason':'illustrate this exact reviewed beat without claiming operational success',
            'visual_mode':scene.get('visual_mode'),'template_id':scene.get('template_id'),'group_motion':scene.get('group_motion')}
        result.append(validate_requirement({'intent':intent,'sha256':digest(intent)}))
    return result


def requirement_tag(requirement):return 'asset-requirement:'+validate_requirement(requirement)['sha256']


def review_context(topic,requirement):
    requirement=validate_requirement(requirement)
    return {'topic':str(topic),'section':requirement['intent']['beat_id'],'semantic_requirement':requirement}


def admit_review(path,topic,requirement,review):
    from .asset_semantic_review import parse_response,validate,verify_session,session_database,verify_normal_asset_session,normal_asset_evidence_identity
    requirement=validate_requirement(requirement);path=Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not path.is_file():raise ValueError('semantic_asset_path_untrusted')
    score=review.get('score')
    if (review.get('status')!='evaluated' or review.get('requirement_match') is not True
            or type(score) not in (int,float) or not math.isfinite(score) or score<MIN_SEMANTIC_SCORE
            or review.get('image_observed') is not True):
        # The evidence travels with the block so a run report can tell a strict gate from a bad image.
        raise ValueError(f"semantic_asset_match_rejected:beat={requirement['intent']['beat_id']}:score={score}"
                         f":match={review.get('requirement_match')}:observed={review.get('image_observed')}"
                         f":why={' '.join(str(review.get('reason') or '').split())[:200]}")
    context=review_context(topic,requirement)
    if review.get('native_context'):
        identity=review['native_context']
        context=dict(context,current_policy_sources=review.get('current_policy_sources'),
            normal_job_id=identity.get('job_id'),original_knowledge_ref=identity.get('original_knowledge_ref'))
    if (review.get('image_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()
            or review.get('context_sha256')!=digest(context)
            or review.get('semantic_requirement_sha256')!=requirement['sha256']):raise ValueError('semantic_asset_review_binding_changed')
    captured={}
    for field in ('query','stdout'):
        record=review.get(field) or {};file=Path(record.get('path') or '')
        if (file.is_symlink() or not file.is_file() or file.parent.resolve()!=path.parent.resolve()
                or hashlib.sha256(file.read_bytes()).hexdigest()!=record.get('sha256')):
            raise ValueError('semantic_asset_'+field+'_capture_changed')
        captured[field]=file.read_text(encoding='utf-8')
    if json.loads(captured['query'].split('UNTRUSTED_DATA:\n',1)[1])!=context:
        raise ValueError('semantic_asset_actual_query_mismatch')
    route=review.get('route') or {};response,session=parse_response(captured['stdout'],route.get('model'))
    actual=validate(response,requirement=True)
    if any(review.get(field)!=value for field,value in actual.items()):raise ValueError('semantic_asset_response_changed')
    if review.get('inherited_review'):
        from .media_revision import inherited_review_database
        database=inherited_review_database(path,review)
    elif review.get('native_context'):
        home,actual_route,record=normal_asset_evidence_identity(review.get('native_execution_ref'),image_path=path)
        for field in ('query','stdout','route','execution','normal_observation','context_sha256','semantic_requirement_sha256','current_policy_sources'):
            if review.get(field)!=record.get(field):raise ValueError('semantic_asset_actual_execution_event_changed')
        database=home/'state.db'
    else:database=session_database()
    execution=verify_session(session,route,database)
    if review.get('native_context'):
        observed=verify_normal_asset_session(session,route,database,captured['query'],response,path)
        if observed!=review.get('normal_observation'):raise ValueError('semantic_asset_normal_observation_changed')
    if execution!=review.get('execution'):raise ValueError('semantic_asset_session_changed')
    return requirement_tag(requirement)


def validate_assignments(scenes,assignments):
    required=[scene for scene in scenes if scene.get('semantic_requirement')]
    if not required:return
    by_beat={str(row.get('beat_id') or ''):row for row in assignments}
    if len(by_beat)!=len(assignments):raise ValueError('semantic_asset_duplicate_beat')
    for scene in required:
        requirement=validate_requirement(scene['semantic_requirement']);identity=requirement['intent']['beat_id']
        if scene.get('beat_id')!=identity or scene.get('required_semantic_tag')!=requirement_tag(requirement):
            raise ValueError('semantic_scene_intent_changed')
        if any(scene.get(field)!=requirement['intent'][field] for field in ('visual_mode','template_id','group_motion')):
            raise ValueError('semantic_scene_mode_changed_after_freeze')
        row=by_beat.get(identity) or {}
        if row.get('semantic_requirement')!=requirement:raise ValueError('semantic_asset_cross_beat_or_intent_reuse')
        tag=admit_review(row.get('source_image') or row.get('background_image'),row.get('review_topic') or '',requirement,row.get('semantic_review') or {})
        tags=[value for value in row.get('semantic_tags') or [] if str(value).startswith('asset-requirement:')]
        if tags!=[tag]:raise ValueError('semantic_asset_unverified_requirement_tag')
        background=Path(row.get('background_image') or '')
        if not background.is_file() or hashlib.sha256(background.read_bytes()).hexdigest()!=(row.get('semantic_review') or {}).get('image_sha256'):
            raise ValueError('semantic_background_bytes_changed')


def bind_requirements(store,job_id,brief,script,scenes,platform,owner):
    from .video_planning_producer import read_bound_video_planning
    from .stage_input_refs import resolve_stage_payload,bind_stage_payload
    from .workflow_runtime import STEP_SUCCEEDED
    # The pet lane and the overnight lanes (MED38: beats frozen from the body) have no source video planning; their
    # 8 beats are bound by the narration receipt check below. Native lanes must match their bound planning.
    overnight=bool(brief.get('platform_source_matrix') and brief.get('hot_viral_samples'))
    if platform!='douyin_pet' and not overnight:
        planned=read_bound_video_planning(store,job_id,brief)
        if script!=planned['video_script']:raise ValueError('semantic_script_not_frozen')
    receipt=None
    for event in store.events(job_id):
        if event['event']=='native_platform_narrations_validated':
            receipt=json.loads(event['detail_json']).get(platform)
    if (not receipt or receipt.get('script_sha256')!=hashlib.sha256(script.encode()).hexdigest()
            or not (receipt.get('claims') or {}).get('passed') or (receipt.get('risk') or {}).get('level')=='block'
            or (receipt.get('compliance') or {}).get('level')=='block'):
        raise ValueError('semantic_factual_safety_receipt_required')
    steps={row['step_name']:row for row in store.workflow_steps(job_id)}
    for name in ('validate_factual_claims','run_safety_gate'):
        if (steps.get(name) or {}).get('status')!=STEP_SUCCEEDED:raise ValueError('semantic_native_gate_not_complete:'+name)
    requirements=build_requirements(script,scenes)
    payload=brief.get('_final_bounded_model_input') or brief['bounded_model_input']
    full=resolve_stage_payload(store,job_id,brief['run_contract'],'generate',payload)
    blueprint=dict(full.get('content_blueprint') or {},video_asset_requirements=requirements)
    full=dict(full,content_blueprint=blueprint)
    bounded=bind_stage_payload(store,job_id,brief['run_contract'],'generate',full,lease_owner=owner,force_reference=True)
    brief['content_blueprint']=blueprint;brief['bounded_model_input']=bounded;brief.pop('_final_bounded_model_input',None)
    return requirements


def read_requirements(store,job_id,brief,plan):
    from .stage_input_refs import resolve_stage_payload,has_stage_refs
    payload=brief.get('bounded_model_input')
    if not has_stage_refs(payload):raise ValueError('semantic_requirements_store_binding_required')
    full=resolve_stage_payload(store,job_id,brief['run_contract'],'generate',payload)
    requirements=(full.get('content_blueprint') or {}).get('video_asset_requirements')
    if requirements!=plan.get('video_asset_requirements'):raise ValueError('semantic_requirements_plan_changed')
    for requirement in requirements or []:validate_requirement(requirement)
    if not requirements:raise ValueError('semantic_requirements_missing')
    scenes=plan.get('visual_contract') or []
    if len(scenes)!=len(requirements):raise ValueError('semantic_requirements_scene_count_changed')
    for scene,requirement in zip(scenes,requirements):
        if (scene.get('semantic_requirement')!=requirement or scene.get('beat_id')!=requirement['intent']['beat_id']
                or any(scene.get(field)!=requirement['intent'][field] for field in ('visual_mode','template_id','group_motion'))):
            raise ValueError('semantic_requirements_scene_changed')
    return copy.deepcopy(requirements)
