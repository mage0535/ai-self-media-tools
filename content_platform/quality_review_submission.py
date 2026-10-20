"""当前原生审核的类型化提交；工具只验证并返回回执。"""
import hashlib
import json
import os
import threading
import asyncio
import functools
import re
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

PROTOCOL = 'typed_quality_submission_v1'
TOOL_NAME = 'submit_quality_review'
RECEIPT_VERSION = 'typed_quality_submission_receipt_v1'
SCOPE_VERSION = 'native_quality_submission_scope_v1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def strict_loads(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('typed_submission_duplicate_json_key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def validate_submission(value, context, channel):
    from .native_quality_runner import strict_review
    if not isinstance(value, dict) or set(value) != {
            'context_sha256', 'channel', 'checks', 'skill_executions'}:
        raise ValueError('typed_submission_exact_arguments_required')
    strict_review(value, context, channel)
    for row in value['checks']:
        if (set(row) != {'name', 'passed', 'verdict', 'observations', 'failures'}
                or not isinstance(row['observations'], str) or not row['observations'].strip()
                or not isinstance(row['failures'], list)
                or any(not isinstance(item, str) for item in row['failures'])
                or row['passed'] and row['failures']):
            raise ValueError('typed_submission_check_arguments_invalid')
    for row in value['skill_executions']:
        if (set(row) != {'skill_id', 'skill_sha256', 'passed', 'verdict', 'applied_checks', 'observations'}
                or not isinstance(row['observations'], str) or not row['observations'].strip()
                or not isinstance(row['applied_checks'], list)
                or any(not isinstance(item, str) for item in row['applied_checks'])):
            raise ValueError('typed_submission_skill_arguments_invalid')
    return value


def schema_for_context(context, channel):
    verdict = {'type': 'string', 'enum': ['passed', 'failed', 'unknown']}
    check = {'type': 'object', 'additionalProperties': False,
        'properties': {'name': {'type': 'string', 'enum': context['required_checks'][channel]},
            'passed': {'type': 'boolean'}, 'verdict': verdict,
            'observations': {'type': 'string'},
            'failures': {'type': 'array', 'items': {'type': 'string'}}},
        'required': ['name', 'passed', 'verdict', 'observations', 'failures']}
    skill = {'type': 'object', 'additionalProperties': False,
        'properties': {'skill_id': {'type': 'string', 'enum': list(context['skills'])},
            'skill_sha256': {'type': 'string'}, 'passed': {'type': 'boolean'},
            'verdict': verdict, 'observations': {'type': 'string'},
            'applied_checks': {'type': 'array', 'items': {'type': 'string',
                'enum': context['required_checks'][channel]}}},
        'required': ['skill_id', 'skill_sha256', 'passed', 'verdict', 'applied_checks', 'observations']}
    # Official registry accepts strict only inside the function schema. Some
    # transports omit it, so the same validation is mandatory in the handler.
    return {'name': TOOL_NAME, 'description': '完成当前真实审核后唯一一次提交全部检查与技能应用；这不是要求通过。',
        'strict': True, 'parameters': {'type': 'object', 'additionalProperties': False,
            'properties': {'context_sha256': {'type': 'string', 'enum': [digest(context)]},
                'channel': {'type': 'string', 'enum': [channel]},
                'checks': {'type': 'array', 'items': check},
                'skill_executions': {'type': 'array', 'items': skill}},
            'required': ['context_sha256', 'channel', 'checks', 'skill_executions']}}


def load_scope(path, sha256):
    from .factual_candidate_revision import private_read
    scope = private_read(path, sha256)
    if (not isinstance(scope, dict) or set(scope) != {'version', 'task_job_id', 'channel',
            'context_sha256', 'context_ref', 'handler_source_ref', 'registration_nonce','current_role_route'}
            or scope['version'] != SCOPE_VERSION):
        raise ValueError('typed_submission_scope_contract_invalid')
    context = private_read(scope['context_ref']['path'], scope['context_ref']['sha256'])
    if (digest(context) != scope['context_sha256']
            or scope['channel'] not in context['required_checks']
            or not isinstance(scope['registration_nonce'], str)
            or len(scope['registration_nonce']) != 64):
        raise ValueError('typed_submission_scope_context_changed')
    route=scope['current_role_route']
    if (not isinstance(route,dict)or set(route)!={'provider','model','api_mode','endpoint'}
            or any(not isinstance(route.get(k),str)or not route[k]for k in('provider','model'))
            or any(route.get(k)is not None and not isinstance(route[k],str)for k in('api_mode','endpoint'))):
        raise ValueError('typed_submission_current_role_route_required')
    source = scope['handler_source_ref']
    if (source.get('path') != str(Path(__file__).resolve())
            or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source.get('sha256')):
        raise ValueError('typed_submission_handler_source_changed')
    return scope, context


def submission_handler_from_scope(path, sha256):
    scope, context = load_scope(path, sha256)
    lock = threading.Lock()
    calls = 0
    def handler(arguments, **unused):
        nonlocal calls
        with lock:
            calls += 1
            sequence = calls
        receipt = {'version': RECEIPT_VERSION, 'scope_sha256': sha256,
            'context_sha256': scope['context_sha256'], 'channel': scope['channel'],
            'submission_count': sequence, 'accepted': False}
        try:
            if sequence != 1:
                raise ValueError('typed_submission_must_be_unique')
            if os.environ.get('HERMES_TASK_JOB_ID') != scope['task_job_id']:
                raise ValueError('typed_submission_current_task_mismatch')
            value = validate_submission(arguments, context, scope['channel'])
            receipt.update(accepted=True, submission_sha256=digest(value))
        except (ValueError, TypeError, KeyError) as error:
            receipt['reason'] = str(error)
        return json.dumps({'success': receipt['accepted'], 'receipt': receipt}, ensure_ascii=False)
    return handler


def register_current_quality_submission(path, sha256):
    install_current_vision_route_guard(path,sha256)
    from tools.registry import registry
    scope, context = load_scope(path, sha256)
    registry.register(name=TOOL_NAME, toolset='vision',
        schema=schema_for_context(context, scope['channel']),
        handler=submission_handler_from_scope(path, sha256), check_fn=lambda: True, emoji='✅')


def _vision_endpoint_digest(value):
    if value is None or value=='':return None
    parsed=urlsplit(str(value).strip())
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('qc_current_vision_endpoint_invalid')
    host=(parsed.hostname or'').casefold();port=parsed.port
    if ':'in host:host='['+host+']'
    authority=host+(':'+str(port)if port is not None and not(parsed.scheme.casefold()=='https'and port==443)and not(parsed.scheme.casefold()=='http'and port==80)else'')
    normalized=urlunsplit((parsed.scheme.casefold(),authority,parsed.path.rstrip('/'),parsed.query,''))
    return hashlib.sha256(normalized.encode()).hexdigest()


def _current_role_vision_factory(route,canonical_provider,auxiliary,runtime_resolver,record,transport_verifier=None):
    """A QC-child-only public factory: no auto route or provider vision default."""
    expected_endpoint=_vision_endpoint_digest(route['endpoint'])
    def guarded(provider=None,model=None,*,base_url=None,api_key=None,async_mode=False,main_runtime=None):
        evidence={'version':'current_role_vision_client_selection_v1','role_provider':route['provider'],
            'role_model':route['model'],'api_mode':route['api_mode'],'role_endpoint_sha256':expected_endpoint,
            'async_mode':async_mode,'probe_only':False,'route_verified':False,'state':'unknown'}
        try:
            automatic=provider in(None,'','auto')
            if not automatic and provider not in{route['provider'],canonical_provider}:raise RuntimeError('qc_current_vision_other_provider_forbidden')
            if not automatic and model not in(None,'','auto',route['model']):raise RuntimeError('qc_current_vision_other_model_forbidden')
            if base_url and _vision_endpoint_digest(base_url)!=expected_endpoint:raise RuntimeError('qc_current_vision_other_endpoint_forbidden')
            runtime=runtime_resolver(requested=route['provider'],target_model=route['model'],explicit_base_url=route['endpoint']or None)
            if runtime.get('provider')!=canonical_provider or runtime.get('api_mode')!=route['api_mode']:
                raise RuntimeError('qc_current_vision_resolved_role_changed')
            if expected_endpoint is not None and _vision_endpoint_digest(runtime.get('base_url'))!=expected_endpoint:
                raise RuntimeError('qc_current_vision_resolved_endpoint_changed')
            actual_key=runtime.get('api_key')
            if api_key is not None and api_key!=actual_key:raise RuntimeError('qc_current_vision_other_credentials_forbidden')
            runtime=dict(runtime,model=route['model'],requested_provider=route['provider'])
            client,selected=auxiliary._get_cached_client(provider=route['provider'],model=route['model'],async_mode=async_mode,
                base_url=route['endpoint']or runtime.get('base_url'),api_key=actual_key,api_mode=route['api_mode'],main_runtime=runtime,is_vision=True,task='vision')
            if client is None:raise RuntimeError('qc_current_vision_client_unavailable')
            evidence.update(selected_provider=canonical_provider,selected_model=selected)
            if selected!=route['model']:raise RuntimeError('qc_current_vision_selected_model_changed')
            probe=auxiliary._aux_probe_active();evidence.update(probe_only=probe,client_available=True)
            if probe:
                evidence['state']='availability_probe_only';record(evidence);return canonical_provider,client,selected
            actual_endpoint=None
            for candidate in(client,getattr(client,'_client',None),getattr(client,'client',None)):
                if candidate is not None:
                    value=getattr(candidate,'base_url',None)
                    if value:actual_endpoint=_vision_endpoint_digest(value);break
            evidence['client_endpoint_sha256']=actual_endpoint
            if expected_endpoint is not None and actual_endpoint!=expected_endpoint:raise RuntimeError('qc_current_vision_client_endpoint_changed')
            if transport_verifier is not None:client=transport_verifier(client)
            evidence.update(state='configured_client',selected_provider=canonical_provider,selected_model=selected,
                client_endpoint_sha256=actual_endpoint,route_verified=True,sdk_auto_default_model_replaced=automatic and model not in(None,'','auto',route['model']))
            record(evidence);return canonical_provider,client,selected
        except Exception as error:
            evidence.update(state='unknown',route_verified=False,reason=str(error)if str(error).startswith('qc_current_vision_')else'qc_current_vision_official_factory_failed',error_type=type(error).__name__)
            record(evidence)
            raise RuntimeError(evidence['reason'])from None
    return guarded


def install_current_vision_route_guard(path,sha256):
    """Install only inside this fresh QC child, before model_tools availability probes."""
    from .mandatory_quality_context import _native_task_home
    from agent import auxiliary_client as auxiliary
    from hermes_cli.runtime_provider import resolve_runtime_provider
    import inspect
    scope,context=load_scope(path,sha256);home,route,provenance=_native_task_home(scope['task_job_id'])
    expected={k:route.get(k)for k in('provider','model','api_mode','endpoint')}
    if scope['current_role_route']!=expected or os.environ.get('HERMES_TASK_JOB_ID')!=scope['task_job_id']:
        raise ValueError('qc_current_vision_scope_role_mismatch')
    existing=getattr(auxiliary.resolve_vision_provider_client,'_qc_scope_sha256',None)
    if existing is not None:
        if existing!=sha256:raise ValueError('qc_current_vision_other_scope_already_installed')
        if getattr(auxiliary._ladder_provider_fallback,'_qc_scope_sha256',None)!=sha256:raise ValueError('qc_current_vision_failure_rung_not_guarded')
        if any(getattr(getattr(auxiliary,name),'_qc_scope_sha256',None)!=sha256 for name in('_call_llm_impl','_async_call_llm_impl')):raise ValueError('qc_current_vision_transport_not_serialized')
        return
    sources={}
    for name,function in(('factory',auxiliary.resolve_provider_client),('runtime_resolver',resolve_runtime_provider)):
        source=Path(inspect.getsourcefile(function)).resolve()
        sources[name]={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    lock=threading.Lock();sequence=0
    def record(value):
        nonlocal sequence
        with lock:
            sequence+=1;number=sequence
        value=dict(value,scope_ref={'path':str(path),'sha256':sha256},task_job_id=scope['task_job_id'],
            context_sha256=scope['context_sha256'],sequence=number,official_sources=sources,guard_source_ref=scope['handler_source_ref'])
        destination=Path(path).with_name(scope['channel']+'.vision-route-selection-'+str(number).zfill(6)+'.private.json')
        fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb')as output:output.write(canonical(value));output.flush();os.fsync(output.fileno())
    from .media_transport_runtime import activate_sdk_child,bind_current_role_client_transport
    transport=activate_sdk_child(expected,provenance['provider'],home)
    guard=_current_role_vision_factory(expected,provenance['provider'],auxiliary,resolve_runtime_provider,record,
        transport_verifier=lambda client:bind_current_role_client_transport(client,expected,provenance['provider'],home))
    guard._qc_scope_sha256=sha256
    auxiliary.resolve_vision_provider_client=guard
    fallback_guard=_current_role_no_vision_fallback(auxiliary._ladder_provider_fallback)
    fallback_guard._qc_scope_sha256=sha256
    auxiliary._ladder_provider_fallback=fallback_guard
    sync,asynchronous=_current_vision_serial_transport(auxiliary._call_llm_impl,auxiliary._async_call_llm_impl)
    sync._qc_scope_sha256=sha256;asynchronous._qc_scope_sha256=sha256
    auxiliary._call_llm_impl=sync;auxiliary._async_call_llm_impl=asynchronous


def _current_vision_serial_transport(sync_original,async_original):
    """QC-child only; public SDK aliases resolve these globals for actual transport."""
    gate=threading.Lock()
    def vision(args,kwargs):return (args[0]if args else kwargs.get('task'))=='vision'
    @functools.wraps(sync_original)
    def synchronous(*args,**kwargs):
        if not vision(args,kwargs):return sync_original(*args,**kwargs)
        if kwargs.get('stream'):
            def streaming():
                with gate:
                    yield from sync_original(*args,**kwargs)
            return streaming()
        with gate:return sync_original(*args,**kwargs)
    @functools.wraps(async_original)
    async def asynchronous(*args,**kwargs):
        if not vision(args,kwargs):return await async_original(*args,**kwargs)
        while not gate.acquire(blocking=False):await asyncio.sleep(0.01)
        try:return await async_original(*args,**kwargs)
        finally:gate.release()
    return synchronous,asynchronous


def _last_current_visual_observations(messages,calls,submission_query,required):
    """Choose by actual call order; retain superseded errors as immutable evidence."""
    message_ids=[row['id']for row in messages]
    if (any(type(i)is not int for i in message_ids)or message_ids!=sorted(set(message_ids))):
        raise ValueError('typed_submission_message_order_ambiguous')
    if not required:raise ValueError('typed_submission_all_current_visuals_required')
    grouped={source:[]for source in required}
    for source_query,source_call,source_name,source_args,raw_args in calls:
        if source_name not in {'vision_analyze','video_analyze'}:continue
        source=source_args.get('image_url')or source_args.get('video_url')
        rows=[row for row in messages if row.get('role')=='tool'and row.get('tool_call_id')==source_call['id']]
        if (source not in required or len(rows)!=1 or rows[0].get('tool_name')!=source_name
                or not source_query['id']<rows[0]['id']<submission_query['id']):
            raise ValueError('typed_submission_current_visual_observation_required')
        previous=grouped[source]
        if previous and previous[-1]['result_message_id']>=source_query['id']:
            raise ValueError('typed_submission_visual_attempt_order_ambiguous')
        raw_result=rows[0]['content']
        entry={'query_message_id':source_query['id'],'result_message_id':rows[0]['id'],
            'tool_call_id':source_call['id'],'tool_name':source_name,'source_ref':required[source],
            'arguments_sha256':hashlib.sha256(raw_args.encode()).hexdigest(),
            'result_sha256':hashlib.sha256(raw_result.encode()).hexdigest()}
        try:
            actual=strict_loads(raw_result)
            if not isinstance(actual,dict):raise ValueError('nonobject')
            analysis=actual.get('analysis')
            entry.update(result_json=True,reported_success=actual.get('success'),error=actual.get('error'),
                analysis_sha256=hashlib.sha256(analysis.encode()).hexdigest()if isinstance(analysis,str)else None)
            valid=actual.get('success')is True and isinstance(analysis,str)and bool(analysis.strip())and not actual.get('error')
        except (ValueError,TypeError):
            entry.update(result_json=False,reported_success=None,error='invalid_JSON_tool_result',analysis_sha256=None);valid=False
        entry['usable_analysis']=valid;previous.append(entry)
    selected=[];prior=[]
    for source,attempts in grouped.items():
        if not attempts:raise ValueError('typed_submission_all_current_visuals_required')
        if not attempts[-1]['usable_analysis']:raise ValueError('typed_submission_current_visual_analysis_missing')
        selected.append(attempts[-1]);prior.extend(attempts[:-1])
    return {'version':'typed_current_visual_observations_v1','selected':selected,'prior_attempts':prior}


def _current_role_no_vision_fallback(original):
    def guarded(first_error,route):
        if getattr(route,'task',None)=='vision':raise RuntimeError('qc_current_vision_provider_fallback_forbidden')
        return(yield from original(first_error,route))
    return guarded


def current_vision_route_selection_refs(scope_pin):
    from .factual_candidate_revision import private_read
    scope,unused=load_scope(scope_pin['path'],scope_pin['sha256']);parent=Path(scope_pin['path']).parent
    refs=[]
    for path in sorted(parent.glob(scope['channel']+'.vision-route-selection-*.private.json')):
        if not re.fullmatch(re.escape(scope['channel'])+r'\.vision-route-selection-\d{6}\.private\.json',path.name):
            raise ValueError('qc_current_vision_record_filename_changed')
        pin={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        private_read(path,pin['sha256']);refs.append(pin)
    return refs


def verify_current_vision_route_selections(refs,scope_pin,context,route,canonical_provider,home,*,require_real):
    from .factual_candidate_revision import private_read
    scope,saved=load_scope(scope_pin['path'],scope_pin['sha256'])
    if saved!=context or scope['current_role_route']!={k:route.get(k)for k in('provider','model','api_mode','endpoint')}:
        raise ValueError('qc_current_vision_record_role_or_context_changed')
    actual=current_vision_route_selection_refs(scope_pin)
    if not isinstance(refs,list)or refs!=actual:raise ValueError('qc_current_vision_record_set_missing_or_changed')
    expected_sources={}
    for name,relative in(('factory','agent/auxiliary_client.py'),('runtime_resolver','hermes_cli/runtime_provider.py')):
        source=(Path(home)/'hermes-agent'/relative).resolve()
        expected_sources[name]={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    endpoint=_vision_endpoint_digest(route['endpoint']);real=0
    for sequence,pin in enumerate(actual,1):
        value=private_read(pin['path'],pin['sha256'])
        if (value.get('version')!='current_role_vision_client_selection_v1'or value.get('scope_ref')!=scope_pin
                or value.get('task_job_id')!=scope['task_job_id']or value.get('context_sha256')!=digest(context)
                or type(value.get('sequence'))is not int or value['sequence']!=sequence
                or value.get('official_sources')!=expected_sources or value.get('guard_source_ref')!=scope['handler_source_ref']
                or value.get('role_provider')!=route['provider']or value.get('role_model')!=route['model']
                or value.get('api_mode')!=route['api_mode']or value.get('role_endpoint_sha256')!=endpoint
                or type(value.get('async_mode'))is not bool or type(value.get('probe_only'))is not bool):
            raise ValueError('qc_current_vision_record_scope_source_or_role_changed')
        if value['probe_only']:
            if value.get('state')!='availability_probe_only'or value.get('route_verified')is not False:
                raise ValueError('qc_current_vision_probe_cannot_claim_actual_route')
            continue
        if (value.get('state')!='configured_client'or value.get('route_verified')is not True
                or value.get('client_available')is not True or value.get('selected_provider')!=canonical_provider
                or value.get('selected_model')!=route['model']
                or(endpoint is not None and value.get('client_endpoint_sha256')!=endpoint)):
            raise ValueError('qc_current_vision_actual_selection_unknown_or_changed')
        real+=1
    if require_real and not real:raise ValueError('qc_current_vision_nonprobe_actual_selection_required')
    return {'actual_configured_clients':real,'availability_probes':len(actual)-real,'all_actual_routes_verified':True}


def _call(call):
    function = call.get('function') or {}
    raw = function.get('arguments')
    if not isinstance(raw, str):
        raise ValueError('typed_submission_original_arguments_required')
    arguments = strict_loads(raw)
    name = function.get('name')
    if name == 'tool_call':
        inner = arguments.get('calls') if isinstance(arguments, dict) else None
        if not isinstance(inner, list) or len(inner) != 1 or not isinstance(inner[0], dict):
            raise ValueError('typed_submission_wrapper_ambiguous')
        name, arguments = inner[0].get('name'), inner[0].get('arguments')
    if not isinstance(arguments, dict):
        raise ValueError('typed_submission_arguments_object_required')
    return name, arguments, raw


def read_session_submission(messages, session, context, channel, scope_pin):
    scope, saved_context = load_scope(scope_pin['path'], scope_pin['sha256'])
    if saved_context != context or scope['channel'] != channel:
        raise ValueError('typed_submission_current_context_required')
    if (not session.get('ended_at') or type(session.get('api_call_count')) is not int
            or session['api_call_count'] <= 0 or type(session.get('tool_call_count')) is not int
            or session['tool_call_count'] <= 0):
        raise ValueError('typed_submission_actual_native_usage_required')
    if any(row.get('session_id') != session['id'] for row in messages):
        raise ValueError('typed_submission_other_native_session')
    calls, ids = [], set()
    for row in messages:
        if row.get('role') != 'assistant' or not row.get('tool_calls'):
            continue
        for call in strict_loads(row['tool_calls']):
            identity = call.get('id')
            if not isinstance(identity, str) or not identity or identity in ids:
                raise ValueError('typed_submission_tool_call_identity_ambiguous')
            ids.add(identity)
            name, arguments, raw = _call(call)
            calls.append((row, call, name, arguments, raw))
    submissions = [row for row in calls if row[2] == TOOL_NAME]
    if len(submissions) != 1 or calls[-1] is not submissions[0]:
        raise ValueError('typed_submission_one_last_call_required')
    query, call, name, arguments, raw = submissions[0]
    validate_submission(arguments, context, channel)
    results = [row for row in messages if row.get('role') == 'tool'
        and row.get('tool_call_id') == call['id']]
    if (len(results) != 1 or results[0].get('tool_name') != TOOL_NAME
            or results[0]['id'] <= query['id']):
        raise ValueError('typed_submission_actual_tool_result_required')
    result = results[0]
    received = strict_loads(result['content'])
    expected = {'version': RECEIPT_VERSION, 'scope_sha256': scope_pin['sha256'],
        'context_sha256': digest(context), 'channel': channel, 'submission_count': 1,
        'accepted': True, 'submission_sha256': digest(arguments)}
    if received != {'success': True, 'receipt': expected}:
        raise ValueError('typed_submission_tool_receipt_not_accepted')
    # No tool may execute after submission, or in parallel before its dependencies.
    if any(row.get('role') == 'tool' and row['id'] > result['id'] for row in messages):
        raise ValueError('typed_submission_not_last_tool_result')
    if channel == 'vlm':
        from .mandatory_quality_context import VISUAL_PARTS, _pin
        required = {pin['path']: pin for part, pins in context['parts'].items()
            if part in VISUAL_PARTS for pin in pins}
        for pin in required.values():_pin(pin,'typed_submission_current_visual')
        visual_observations=_last_current_visual_observations(messages,calls[:-1],query,required)
    for row in messages:
        if row.get('role') != 'assistant' or row.get('tool_calls') or row['id'] <= result['id']:
            continue
        try: value = strict_loads(row.get('content') or '')
        except (ValueError, TypeError): continue
        if isinstance(value, dict) and set(arguments) <= set(value) and value != arguments:
            raise ValueError('typed_submission_conflicting_final_review')
    observation = {'query_message_id': query['id'], 'result_message_id': result['id'],
        'tool_call_id': call['id'], 'tool_name': TOOL_NAME}
    if channel=='vlm':observation['visual_observations']=visual_observations
    return {'review': arguments, 'raw_arguments': raw, 'receipt': received,
        'observation': observation, 'scope': scope, 'raw_receipt': result['content']}
