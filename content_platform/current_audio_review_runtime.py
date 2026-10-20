"""Full acoustic input through the current signed Hermes route and official client.
No transcript replacement, fallback, retry, provider/model default or quality self-approval.
"""
from __future__ import annotations
import base64,hashlib,json,os,time,re,subprocess,math,shutil
from pathlib import Path
from typing import Callable

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write_private(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())

def analyze_current_audio(audio_path,audio_sha256,prompt,*,current_modal_resolver:Callable,
                          credential_resolver:Callable|None=None,output_dir,network_proxy=None,quality_scope_ref=None):
    import httpx
    modal=current_modal_resolver()
    factory=getattr(current_modal_resolver,'audio_review_runtime',None)
    if not callable(factory):raise RuntimeError('audio_review_signed_runtime_factory_required')
    path=Path(audio_path)
    if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():
        raise RuntimeError('audio_review_actual_input_missing')
    data=path.read_bytes()
    if sha(data)!=audio_sha256 or not data or len(data)>15*1024*1024:
        raise RuntimeError('audio_review_actual_input_hash_or_size_invalid')
    mime={'.wav':'audio/wav','.mp3':'audio/mpeg','.m4a':'audio/mp4','.mp4':'video/mp4','.ogg':'audio/ogg','.flac':'audio/flac'}.get(path.suffix.lower())
    if not mime:raise RuntimeError('audio_review_actual_input_format_unsupported')
    fmt=path.suffix.lower()[1:]
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>22000:
        raise RuntimeError('audio_review_actual_prompt_invalid')
    blind=None
    if quality_scope_ref is not None:
        blind=_blind_material(quality_scope_ref,path,audio_sha256,task_id=os.environ.get('HERMES_TASK_JOB_ID'))
        prompt=_blind_audio_prompt(blind['measurement']['duration_seconds'],blind['scope']['context_sha256'])
    route=factory()
    if route.get('api_mode') not in {'chat_completions','google_generate_content','google_interactions'}:
        raise RuntimeError('audio_review_actual_protocol_not_supported_'+str(route.get('api_mode')))
    client=route['client'];out=Path(output_dir)
    if not out.is_absolute() or out.is_symlink() or any(p.is_symlink() for p in out.parents):
        _close_route(route);raise RuntimeError('audio_review_output_directory_unsafe')
    identity={'schema':'current_signed_audio_review_execution_v2','provider':route['provider'],'model':route['model'],
        'api_mode':route['api_mode'],'selection_source':route['selection_source'],
        'current_modal_sha256':modal.get('current_modal_sha256'),'source_config_sha256':modal.get('config_sha256'),
        'normal_profile_job_id':modal.get('normal_profile_job_id'),'authority_receipt_sha256':route.get('authority_receipt_sha256'),
        'source_snapshot_sha256':route.get('source_snapshot_sha256'),'input_audio_path':str(path),
        'input_audio_sha256':audio_sha256,'input_audio_bytes':len(data),'input_audio_format':fmt,'prompt_sha256':sha(prompt.encode()),
        'retry':False,'fallback':False,'automatic_replay':False,'business_quality_passed':False,'formal_native_session_registered':False}
    if blind is not None:
        role=blind['scope']['current_role_route']
        if route.get('selection_source')!='signed_current_main_route' or route['provider']!=role['provider'] or route['model']!=role['model'] or (role.get('api_mode') is not None and route['api_mode']!=role['api_mode']):
            _close_route(route);raise PermissionError('blind_audio_exact_current_main_route_required')
        from .quality_review_submission import _vision_endpoint_digest
        base=route.get('base_url') or str(getattr(client,'base_url',''))
        endpoint_sha=_vision_endpoint_digest(base)
        if role.get('endpoint') and endpoint_sha!=_vision_endpoint_digest(role['endpoint']):
            _close_route(route);raise PermissionError('blind_audio_exact_current_endpoint_required')
        identity.update(evidence_mode='scoped_blind_full_audio_v2',blind_scope_ref=quality_scope_ref,blind_current_route={'provider':route['provider'],'model':route['model'],'api_mode':route['api_mode'],'endpoint_sha256':endpoint_sha,'role_route_sha256':sha(canonical(role))})
    try:out.mkdir(mode=0o700,parents=True,exist_ok=False)
    except FileExistsError:
        _close_route(route)
        intent=out/'intent.private.json'
        if intent.is_symlink() or not intent.is_file() or json.loads(intent.read_bytes())!=identity:
            raise RuntimeError('audio_review_existing_attempt_identity_mismatch')
        result=out/'execution-receipt.private.json'
        if result.is_symlink():raise RuntimeError('audio_review_existing_receipt_unsafe')
        if result.is_file():
            value=json.loads(result.read_bytes())
            if any(value.get(k)!=v for k,v in identity.items()):raise RuntimeError('audio_review_existing_receipt_identity_mismatch')
            return value
        return dict(identity,status='unknown',reason='original_attempt_incomplete_only_inspect',generation_attempts=None)
    write_private(out/'intent.private.json',canonical(identity)+b'\n')
    if route['api_mode'] in {'google_generate_content','google_interactions'}:
        return _analyze_native_google(path,blind['wire_bytes']if blind else data,('audio/'+('mpeg'if blind['wire_format']=='mp3'else'wav'))if blind else mime,prompt,route,out,identity,blind=blind)
    whole_deadline=time.monotonic()+route['timeout_seconds']
    wire_data,fmt,decode=(blind['wire_bytes'],blind['wire_format'],blind['measurement'])if blind else _complete_chat_audio(path,data,out,whole_deadline)
    body={'model':route['model'],'messages':[{'role':'user','content':[{'type':'text','text':prompt},
        {'type':'input_audio','input_audio':{'data':base64.b64encode(wire_data).decode(),'format':fmt}}]}],
        'max_tokens':route['max_output_tokens'],'stream':False}
    write_private(out/'logical-request.private.json',canonical(body)+b'\n')
    receipt=dict(identity,status='unknown',generation_attempts=0,http_attempts=0,wire_audio_sha256=sha(wire_data),wire_audio_bytes=len(wire_data))
    if decode:receipt['audio_decode']=decode
    started=time.monotonic();attempts=[];responses=[]
    transport=client._client;before=list(transport.event_hooks.get('request',[]));before_response=list(transport.event_hooks.get('response',[]))
    def observe_request(request):
        attempts.append({'at_unix':time.time(),'method':request.method})
        if len(attempts)>1:raise RuntimeError('audio_review_second_http_attempt_forbidden')
        if request.method!='POST':raise RuntimeError('audio_review_actual_http_method_invalid')
        actual=request.content;value=json.loads(actual)
        if blind is not None:
            expected_url=str(client.base_url).rstrip('/')+'/chat/completions'
            if str(request.url)!=expected_url:raise RuntimeError('blind_audio_actual_endpoint_changed')
            receipt['blind_wire_endpoint_sha256']=sha(expected_url.encode())
        if (value.get('model')!=body['model'] or value.get('messages')!=body['messages']
                or value.get('tools') or value.get('stream') is not False):
            raise RuntimeError('audio_review_actual_wire_audio_or_identity_changed')
        write_private(out/'actual-request.private.json',actual)
        receipt['request_sha256']=sha(actual)
    def observe_response(response):responses.append(response)
    transport.event_hooks['request']=before+[observe_request]
    transport.event_hooks['response']=before_response+[observe_response]
    try:
        write_private(out/'transport-started.private.json',canonical({'at_unix':time.time(),'automatic_replay':False})+b'\n')
        remaining=whole_deadline-time.monotonic()
        if remaining<=0:raise RuntimeError('audio_review_original_decode_and_request_budget_elapsed')
        bounded=client.with_options(max_retries=0,timeout=remaining)
        raw=bounded.with_raw_response.chat.completions.create(**body)
        response=raw.http_response;response.read()
        value=response.json()
        if response.status_code!=200:receipt.update(status='failed',reason='audio_review_provider_http_rejected')
        else:
            usage=value.get('usage') or {};details=usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
            audio_tokens=details.get('audio_tokens')
            text=''.join(c.get('message',{}).get('content','') or '' for c in value.get('choices',[]) if not c.get('message',{}).get('tool_calls'))
            if any(c.get('message',{}).get('tool_calls') for c in value.get('choices',[])):
                receipt.update(status='failed',reason='audio_review_unexpected_tool_call')
            elif blind is not None and text and all(c.get('finish_reason')=='stop'for c in value.get('choices',[])):
                receipt.update(status='pending_blind_evidence',raw_analysis_text=text)
            elif type(audio_tokens) is not int or audio_tokens<=0:
                receipt.update(status='unverified_audio_input',reason='provider_did_not_prove_audio_input_usage')
            elif not text or any(c.get('finish_reason') not in ('stop',) for c in value.get('choices',[])):
                receipt.update(status='failed',reason='audio_review_native_response_incomplete')
            else:receipt.update(status='completed',raw_analysis_text=text)
            receipt.update(usage=usage,audio_input_tokens=audio_tokens,returned_model=value.get('model'),
                raw_analysis_text=text,analysis_observation_state='unreviewed_model_output')
    except Exception as exc:
        # Retain native HTTP status/body below; exception strings can contain credentials.
        receipt.update(status='unknown' if not responses else 'failed',error_type=type(exc).__name__,reason='audio_review_native_request_not_completed')
    finally:
        if responses:
            response=responses[-1]
            try:
                response.read();write_private(out/'actual-response.private.json',response.content)
                receipt.update(http_status=response.status_code,response_sha256=sha(response.content))
            except Exception as exc:receipt.update(status='unknown',response_capture_error=type(exc).__name__)
        if sha(path.read_bytes())!=audio_sha256:receipt.update(status='failed',reason='audio_changed_during_review')
        transport.event_hooks['request']=before;transport.event_hooks['response']=before_response
        client.close()
    receipt.update(generation_attempts=1,http_attempts=len(attempts),elapsed_seconds=round(time.monotonic()-started,6))
    _finish_blind_audio(receipt,blind,out)
    write_private(out/'execution-receipt.private.json',canonical(receipt)+b'\n')
    return receipt



def _close_route(route):
    client=route.get('client')
    if client is not None:client.close()


def _complete_chat_audio(path,data,out,deadline):
    """Decode the whole original single audio track to uncompressed PCM; never a sample."""
    if path.suffix.lower() in {'.wav','.mp3'}:return data,path.suffix.lower()[1:],None
    def binary(name):
        value=shutil.which(name)
        if not value:raise RuntimeError('audio_review_complete_decode_binary_missing_'+name)
        return value
    def run(args,seconds):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise RuntimeError('audio_review_original_decode_budget_elapsed')
        result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=min(seconds,remaining),check=False)
        if result.returncode:
            write_private(out/('decode-failure-'+sha(canonical(args))[:12]+'.private.log'),result.stderr)
            raise RuntimeError('audio_review_complete_track_decode_failed')
        return result.stdout
    probe=binary('ffprobe');ffmpeg=binary('ffmpeg')
    def inspect(p,label):
        raw=run([probe,'-v','error','-protocol_whitelist','file,pipe','-show_entries',
            'stream=codec_type,codec_name,sample_fmt,bits_per_sample,bits_per_raw_sample,duration,sample_rate,channels:format=duration','-of','json',str(p)],10)
        write_private(out/(label+'.ffprobe.private.json'),raw);value=json.loads(raw)
        tracks=[x for x in value.get('streams',[]) if x.get('codec_type')=='audio']
        if len(tracks)!=1:raise RuntimeError('audio_review_exact_single_complete_audio_track_required')
        track=tracks[0]
        try:duration=float(track.get('duration') or value.get('format',{}).get('duration'))
        except (ValueError,TypeError):raise RuntimeError('audio_review_full_audio_duration_missing')
        if not math.isfinite(duration)or duration<=0:raise RuntimeError('audio_review_full_audio_duration_invalid')
        return track,duration,sha(raw)
    track,duration,source_probe=inspect(path,'source-complete')
    decoded=out/'complete-decoded-audio.wav'
    command=[ffmpeg,'-nostdin','-v','error','-n','-protocol_whitelist','file,pipe','-i',str(path),
        '-map','0:a:0','-vn','-c:a','pcm_s32le',str(decoded)]
    run(command,30)
    output,output_duration,decoded_probe=inspect(decoded,'decoded-complete')
    if output.get('codec_name')!='pcm_s32le' or output.get('sample_fmt')!='s32' or output.get('bits_per_sample')!=32:
        raise RuntimeError('audio_review_complete_decode_pcm_format_changed')
    if abs(duration-output_duration)>0.1 or any(str(track.get(k))!=str(output.get(k)) for k in('channels','sample_rate')):
        raise RuntimeError('audio_review_complete_decode_duration_or_channels_changed')
    if sha(path.read_bytes())!=sha(data):raise RuntimeError('audio_review_source_changed_during_complete_decode')
    # No lossy re-encode, trim, seek, speed, resampling, channel reduction, or silence removal.
    raw=decoded.read_bytes()
    receipt={'version':'whole_audio_pcm_decode_v1','original_path':str(path),'original_sha256':sha(data),
        'decoded_path':str(decoded),'decoded_sha256':sha(raw),'decoded_bytes':len(raw),
        'source_duration_seconds':duration,'decoded_duration_seconds':output_duration,'channels':track.get('channels'),
        'sample_rate':track.get('sample_rate'),'source_probe_sha256':source_probe,'decoded_probe_sha256':decoded_probe,
        'command_sha256':sha(canonical(command)),'codec':output['codec_name'],'sample_fmt':output['sample_fmt'],
        'decoded_bits_per_sample':output['bits_per_sample'],'whole_track':True,
        'trim':False,'speed_change':False,'resampling':False,'channel_reduction':False}
    write_private(out/'complete-audio-decode-receipt.private.json',canonical(receipt)+b'\n')
    return raw,'wav',receipt


def _analyze_native_google(path,data,mime,prompt,route,out,identity,*,blind=None):
    """Retain both original native protocols with current signed selection, official key."""
    import httpx
    from urllib.parse import quote
    bridge=route.get('native_audio_capability')
    if bridge:
        from .normal_modal_runtime import verify_native_bridge_audio_wire
        verify_native_bridge_audio_wire(route)
    elif route['provider'] not in {'google','gemini'} or route['base_url']!='https://generativelanguage.googleapis.com/v1beta':
        raise RuntimeError('audio_review_native_google_signed_endpoint_required')
    encoded=base64.b64encode(data).decode();mode=route['api_mode']
    if mode=='google_generate_content':
        endpoint=route['base_url']+'/models/'+quote(route['model'],safe='-._')+':generateContent'
        body={'contents':[{'role':'user','parts':[{'text':prompt},{'inlineData':{'mimeType':mime,'data':encoded}}]}],
            'generationConfig':{'responseMimeType':'application/json','temperature':0.1,'maxOutputTokens':route['max_output_tokens']}}
    else:
        endpoint=route['base_url']+'/interactions'
        body={'model':route['model'],'store':False,'input':[{'type':'text','text':prompt},
            {'type':'video' if mime.startswith('video/') else 'audio','mime_type':mime,'data':encoded}],
            'generation_config':{'temperature':0.1,'max_output_tokens':route['max_output_tokens']}}
    if mode=='google_interactions' and route.get('thinking_level'):body['generation_config']['thinking_level']=route['thinking_level']
    request=canonical(body);write_private(out/'logical-request.private.json',request)
    write_private(out/'actual-request.private.json',request)
    receipt=dict(identity,status='unknown',generation_attempts=1,http_attempts=0,
        request_sha256=sha(request),wire_audio_sha256=sha(data),wire_audio_bytes=len(data),
        input_audio_mime_type=mime,credential_runtime_api_mode=route.get('credential_runtime_api_mode'))
    client=route['client']._client if bridge else httpx.Client(trust_env=False,proxy=route.get('network_proxy'),follow_redirects=False)
    headers=route['native_transport_headers'] if bridge else {'x-goog-api-key':route['api_key'],'Content-Type':'application/json'}
    if bridge:receipt['native_audio_capability']=bridge
    headers={**headers,'Content-Type':'application/json'}
    started=time.monotonic()
    try:
        write_private(out/'transport-started.private.json',canonical({'at_unix':time.time(),'automatic_replay':False})+b'\n')
        receipt['http_attempts']=1
        if blind is not None:receipt['blind_wire_endpoint_sha256']=sha(endpoint.encode())
        response=client.post(endpoint,headers=headers,content=request,timeout=route['timeout_seconds'],follow_redirects=False)
        write_private(out/'actual-response.private.json',response.content)
        receipt.update(http_status=response.status_code,response_sha256=sha(response.content))
        value=response.json()
        if response.status_code!=200:receipt.update(status='failed',reason='audio_review_provider_http_rejected')
        else:
            if mode=='google_generate_content':
                usage=value.get('usageMetadata')or{}
                counts=[v['tokenCount']for v in usage.get('promptTokensDetails',[])if v.get('modality')=='AUDIO'and type(v.get('tokenCount'))is int]
                audio_tokens=sum(counts)if counts else None
                text=''.join(p.get('text','')for c in value.get('candidates',[])for p in c.get('content',{}).get('parts',[])if not p.get('thought'))
                complete=bool(text)and all(c.get('finishReason')in(None,'STOP')for c in value.get('candidates',[]))
                if any('functionCall'in p for c in value.get('candidates',[])for p in c.get('content',{}).get('parts',[])):complete=False
                receipt['returned_model']=value.get('modelVersion')
            else:
                usage=value.get('usage')or{}
                counts=[v['tokens']for v in usage.get('input_tokens_by_modality',[])if v.get('modality')=='audio'and type(v.get('tokens'))is int]
                audio_tokens=sum(counts)if counts else None
                outputs=value.get('outputs')or value.get('output')or[]
                text=''.join(v.get('text','')for v in outputs if isinstance(v,dict)and v.get('type')=='text')
                complete=value.get('status')=='completed'and bool(text)and not any('call'in str(v.get('type',''))for v in outputs if isinstance(v,dict))
                receipt.update(returned_model=value.get('model'),raw_outputs=outputs)
            receipt.update(usage=usage,audio_input_tokens=audio_tokens,raw_analysis_text=text,
                analysis_observation_state='unreviewed_model_output')
            if blind is not None and complete:receipt.update(status='pending_blind_evidence')
            elif type(audio_tokens)is not int or audio_tokens<=0:receipt.update(status='unverified_audio_input',reason='provider_did_not_prove_audio_input_usage')
            elif not complete:receipt.update(status='failed',reason='audio_review_native_response_incomplete')
            else:receipt.update(status='completed',raw_analysis_text=text)
    except httpx.RequestError as exc:receipt.update(status='unknown',error_type=type(exc).__name__,reason='audio_review_native_request_not_completed')
    except Exception as exc:receipt.update(status='failed'if receipt.get('http_status')else'unknown',error_type=type(exc).__name__,reason='audio_review_native_request_not_completed')
    finally:
        if bridge:_close_route(route)
        else:client.close()
    if sha(path.read_bytes())!=identity['input_audio_sha256']:receipt.update(status='failed',reason='audio_changed_during_review')
    receipt['elapsed_seconds']=round(time.monotonic()-started,6)
    _finish_blind_audio(receipt,blind,out)
    write_private(out/'execution-receipt.private.json',canonical(receipt)+b'\n')
    return receipt

def _normal_modal(*,native_audio_capability=None):
    from hermes_constants import get_hermes_home
    home=Path(get_hermes_home())
    from content_platform.normal_modal_runtime import current_normal_modal_resolver
    resolver=current_normal_modal_resolver(native_audio_capability=native_audio_capability);jid=resolver()['normal_profile_job_id']
    return resolver,home,jid

def check_audio_review_requirements():
    try:
        resolver,_,_=_normal_modal();role=resolver().get('auxiliary_audio_review') or {}
        return role.get('enabled',True) is True and callable(getattr(resolver,'audio_review_runtime',None))
    except Exception:return False

def audio_analyze_tool(audio_path:str,prompt:str,audio_sha256:str,context_sha256:str,*,native_audio_capability=None,quality_scope_ref=None)->str:
    try:
        if not re.fullmatch('[a-f0-9]{64}',str(context_sha256)):
            raise PermissionError('audio_review_current_quality_context_required')
        resolver,home,jid=_normal_modal(native_audio_capability=native_audio_capability)
        path=Path(audio_path)
        if '..' in path.parts:raise PermissionError('audio_review_actual_path_escape_forbidden')
        if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise PermissionError('audio_review_actual_regular_input_required')
        path=path.resolve()
        if not (path.is_relative_to(Path('/srv/ai-self-media-tools').resolve()) or path.is_relative_to((Path('/srv/hermes-worker-media/jobs')/jid).resolve()) or path.is_relative_to((Path('/srv/hermes-worker/jobs')/jid).resolve())):
            raise PermissionError('audio_review_input_outside_normal_business_artifacts')
        if not re.fullmatch('[a-f0-9]{64}',str(audio_sha256)):
            raise PermissionError('audio_review_current_audio_hash_required')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>20000:
            raise PermissionError('audio_review_actual_check_prompt_required')
        # Context identity is included in the actual provider request, not only a report.
        bound_prompt='当前质量上下文 SHA256：'+context_sha256+'。\n'+prompt
        if quality_scope_ref is not None:
            from .quality_review_submission import load_scope
            scope,_=load_scope(quality_scope_ref['path'],quality_scope_ref['sha256'])
            if scope['context_sha256']!=context_sha256 or scope['task_job_id']!=jid or scope['channel']!='watch':
                raise PermissionError('blind_audio_current_watch_scope_required')
            # Stable preselected mode; do the complete acoustic read once in analyze_current_audio.
            bound_prompt='scoped_blind_full_audio_v2:'+context_sha256+':'+audio_sha256
        from content_platform.current_audio_review_runtime import analyze_current_audio
        # The current factory owns official credentials, endpoint and protocol resolution.
        # Stable attempt identity prevents a repeated native tool call from replaying unknown work.
        attempt=hashlib.sha256(json.dumps({'job_id':jid,'audio_sha256':audio_sha256,
            'context_sha256':context_sha256,'prompt':bound_prompt},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        out=home/'audio-review-executions'/attempt
        receipt=analyze_current_audio(str(path),audio_sha256,bound_prompt,current_modal_resolver=resolver,output_dir=str(out),quality_scope_ref=quality_scope_ref)
        completed=receipt.get('status')=='completed' and receipt.get('http_status')==200
        analysis=receipt.get('raw_analysis_text') or receipt.get('raw_outputs')
        return json.dumps({'success':bool(completed and analysis),'analysis':analysis if completed else None,
            'context_sha256':context_sha256,'audio_path':str(path),'audio_sha256':audio_sha256,
            'auxiliary_execution':receipt,'execution_receipt_path':str(out/'execution-receipt.private.json'),
            'quality_passed':False,'reason':None if completed else 'current_audio_review_incomplete_or_unknown'},ensure_ascii=False)
    except Exception as exc:
        # Do not echo response exceptions containing keys, proxy credentials, or URL query.
        return json.dumps({'success':False,'analysis':None,'quality_passed':False,
            'error_type':type(exc).__name__,'reason':str(exc) if re.fullmatch(r'[a-z][a-z0-9_]{1,180}',str(exc)) else 'actual_audio_review_failed'},ensure_ascii=False)

SCHEMA={'name':'audio_analyze','description':'使用当前 Hermes 已签角色主模型或其显式专选真实听取完整音频；不能以转录代替听感。失败或未知不通过。',
 'parameters':{'type':'object','properties':{
    'audio_path':{'type':'string','description':'当前实际本地完整音频文件绝对路径。'},
    'audio_sha256':{'type':'string','description':'当前实际音频字节 SHA256。'},
    'context_sha256':{'type':'string','description':'受信调用方给出的当前强制质量上下文 SHA256。'},
    'prompt':{'type':'string','description':'当前完整实听检查要求，输出严格 JSON 和具体声音观察；不能仅根据稿件推断。'}},
  'required':['audio_path','audio_sha256','context_sha256','prompt'],'additionalProperties':False}}
def register_current_audio_tool(*,native_audio_capability=None,quality_scope_ref=None):
    """This normal review child only; official public registration, no SDK disk edits."""
    from tools.registry import registry
    blind_paths=set()
    if quality_scope_ref is not None:
        from .quality_review_submission import load_scope
        scope,context=load_scope(quality_scope_ref['path'],quality_scope_ref['sha256'])
        if scope['channel']=='watch':
            views=[json.loads(_blind_read(ref))for ref in context['parts'].get('render_manifest',[])]
            if any(isinstance(v,dict)and v.get('version')=='native_actual_audio_materials_v1'for v in views):
                blind_paths={ref['path']for role in('narration','voice_segments','bgm','video')for ref in context['parts'].get(role,[])}
    if blind_paths:
        preflight=[]
        for path in sorted(blind_paths):
            pin=next(r for key in('narration','voice_segments','bgm','video')for r in context['parts'].get(key,[])if r['path']==path)
            material=_blind_material(quality_scope_ref,path,pin['sha256'],scope['context_sha256'],scope['task_job_id'])
            if material['wire_format']=='wav':_blind_wave(material['wire_bytes'])
            preflight.append({'audio_ref':material['audio_ref'],'track_kind':material['track_kind'],
                'wire_sha256':material['wire_sha256'],'wire_bytes':len(material['wire_bytes']),
                'wire_format':material['wire_format'],'measurement':material['measurement']})
        record={'version':'scoped_complete_audio_preflight_v1','scope_ref':quality_scope_ref,
            'context_sha256':scope['context_sha256'],'task_job_id':scope['task_job_id'],'tracks':preflight,
            'model_called':False,'quality_passed':False}
        path=Path(quality_scope_ref['path']).parent/'watch-complete-audio-preflight.private.json';raw=canonical(record)+b'\n'
        if path.exists():
            if path.is_symlink()or path.read_bytes()!=raw:raise ValueError('blind_audio_existing_preflight_changed')
        else:write_private(path,raw)
    import threading
    serial=threading.Lock()
    def handler(args,**kw):
        # Enclose the actual transport, not just client construction. Scope expiry is re-read after waiting.
        with serial:
            return audio_analyze_tool(**args,native_audio_capability=native_audio_capability,
                quality_scope_ref=quality_scope_ref if args.get('audio_path')in blind_paths else None)
    registry.register(name='audio_analyze',toolset='vision',schema=SCHEMA,
        handler=handler,check_fn=check_audio_review_requirements,emoji='🔊')


def _spoken_key(text):
    import unicodedata
    if not isinstance(text,str):raise ValueError('blind_audio_original_spoken_text_required')
    return ''.join(c for i,c in enumerate(text) if not c.isspace() and not (
        unicodedata.category(c).startswith('P') and not
        ((i>0 and text[i-1].isdigit()) or (i+1<len(text) and text[i+1].isdigit()))))


def _blind_audio_prompt(duration,context_sha256):
    return ('Listen to the ENTIRE supplied waveform; no tools and no external information. '
        'Do not infer speech from the hash. Return only JSON with exactly heard_full_audio (true only if fully heard), '
        'language, segments. segments must continuously cover 0 through '+repr(duration)+' seconds, including silence. '
        'Each segment has exactly start_seconds,end_seconds,kind (speech, music, sound or silence),text (verbatim heard speech; empty for silence),'
        'pace,stress,naturalness,observations. Also allow kind=music or sound with text empty and concrete acoustic observations. Give specific audible pace, emphasis, pauses/breath and naturalness observations. '
        'Never invent unheard content. If anything is inaudible or uncertain say unknown; do not claim full hearing. '
        'Opaque current context SHA256: '+context_sha256)


def _blind_read(pin):
    from .mandatory_quality_context import _pin
    checked=_pin(pin,'blind_audio_current_original')
    raw=Path(checked['path']).read_bytes()
    if sha(raw)!=checked['sha256']:raise ValueError('blind_audio_original_changed')
    return raw


def _blind_material(scope_ref,audio_path,audio_sha256,context_sha256=None,task_id=None):
    from .quality_review_submission import load_scope
    scope,context=load_scope(scope_ref['path'],scope_ref['sha256'])
    if (scope['channel']!='watch' or not context.get('required_checks',{}).get('watch')
            or(task_id is not None and scope['task_job_id']!=task_id)
            or(context_sha256 is not None and scope['context_sha256']!=context_sha256)):
        raise ValueError('blind_audio_current_watch_scope_required')
    parts=context['parts'];views=[]
    for ref in parts.get('render_manifest',[]):
        value=_blind_json(_blind_read(ref))
        if isinstance(value,dict)and value.get('version')=='native_actual_audio_materials_v1':views.append((ref,value))
    if len(views)!=1:raise ValueError('blind_audio_unique_actual_material_view_required')
    view_ref,view=views[0]
    if view.get('job_id')!=context['job_id']or view.get('platform')!=context['platform']:
        raise ValueError('blind_audio_actual_material_scope_mismatch')
    expected={(r['file_ref']['path'],r['file_ref']['sha256']) for r in view['materials']}
    actual={(r['path'],r['sha256'])for key in('voice_segments','narration','bgm','video')for r in parts.get(key,[])}
    if not expected or expected!=actual:raise ValueError('blind_audio_all_actual_tracks_required')
    matches=[r for r in view['materials']if r['file_ref']['path']==str(audio_path)and r['file_ref']['sha256']==audio_sha256]
    if len(matches)!=1:raise ValueError('blind_audio_one_current_actual_track_required')
    row=matches[0];source_ref=view['source_script_ref'];script=_blind_read(source_ref).decode('utf-8-sig')
    script_sources=[source_ref]+view.get('source_script_auxiliary_refs',[])
    expected_scripts={(r['path'],r['sha256'])for r in script_sources}
    actual_scripts={(r['path'],r['sha256'])for r in parts.get('source_script',[])}
    if (len(expected_scripts)!=len(script_sources)or len(parts.get('source_script',[]))!=len(script_sources)
            or actual_scripts!=expected_scripts):
        raise ValueError('blind_audio_unique_current_original_script_required')
    modern=view.get('prepared_schema')=='current_hermes_prosody_execution_v1'
    prepared=read_prepared_audio_records(view['prepared_ref'],tts_records_ref=view['tts_records_ref']if modern else None);tts=_blind_json(_blind_read(view['tts_records_ref']))
    if _spoken_key(prepared['source_text'])!=_spoken_key(script)or len(tts)!=len(prepared['records']):
        raise ValueError('blind_audio_complete_source_records_changed')
    for record,controls in zip(prepared['records'],tts):
        if (controls.get('display_text')!=record['source_text']or controls.get('tts_text')!=record['tts_text']
                or controls.get('audio_sha256')!=record['audio_ref']['sha256']or controls.get('voice')!=record['voice']
                or (not modern and float(controls.get('rate','nan'))!=record['speed'])):
            raise ValueError('blind_audio_actual_source_pronunciation_controls_changed')
    if row['kind']=='voice_segment':
        record=prepared['records'][row['prepared_record_index']]
        if any(record['audio_ref'].get(k)!=row['file_ref'][k]for k in('path','sha256')):raise ValueError('blind_audio_segment_record_binding_changed')
        spoken=record['tts_text'];source=record['source_text']
    elif row['kind']=='background_music':spoken='';source=''
    else:spoken=prepared['tts_text'];source=script
    # Historical alignment is unproven, not a license to infer offsets or to skip whole-track hearing.
    for name in('trusted_manifest_ref','tts_config_ref','original_render_contract_ref'):_blind_read(view[name])
    for name in('alignment_ref','rights_ref','mix_ref'):
        if name in row:_blind_read(row[name])
    raw=_blind_read(row['file_ref'])
    if not raw or len(raw)>15*1024*1024:raise ValueError('audio_review_actual_input_hash_or_size_invalid')
    measure,samples,wire,fmt=_blind_complete_audio(Path(audio_path),raw)
    return {'scope_ref':scope_ref,'scope':scope,'context':context,'audio_ref':row['file_ref'],
        'script_ref':source_ref,'voice_plan_ref':view['tts_records_ref'],'material_view_ref':view_ref,
        'track_kind':row['kind'],'script':spoken,'source_text':source,'voice_plan':tts,
        'measurement':measure,'samples':samples,'wire_bytes':wire,'wire_format':fmt,
        'wire_sha256':sha(wire)}


def _blind_mp3_metadata(data):
    # Only standard technical encoder tags; no lyrics, title, comments, user text or opaque attachments.
    if b'APETAGEX'in data or data[-128:-125]==b'TAG':raise ValueError('blind_audio_MP3_content_metadata_forbidden')
    if not data.startswith(b'ID3'):return
    version=data[3]
    if version not in(3,4)or data[5]!=0:raise ValueError('blind_audio_MP3_unknown_metadata_forbidden')
    size=data[6:10]
    if len(size)!=4 or any(v&128 for v in size):raise ValueError('blind_audio_MP3_invalid_metadata')
    limit=10+sum(v<<(7*(3-i))for i,v in enumerate(size));offset=10
    if limit>len(data):raise ValueError('blind_audio_MP3_truncated_metadata')
    while offset<limit:
        if data[offset:limit].strip(b'\x00')==b'':break
        if offset+10>limit:raise ValueError('blind_audio_MP3_truncated_metadata')
        tag=data[offset:offset+4];length=data[offset+4:offset+8];flags=data[offset+8:offset+10]
        n=int.from_bytes(length,'big')if version==3 else sum(v<<(7*(3-i))for i,v in enumerate(length))
        value=data[offset+10:offset+10+n]
        if (tag not in(b'TSSE',b'TENC')or flags!=b'\x00\x00'or n<2 or len(value)!=n
                or value[0]not in(0,3)or not re.fullmatch(rb'(?:Lavf|Lavc|LAME)[0-9]{1,5}(?:\.[0-9]{1,5}){1,5}\x00*',value[1:])):
            raise ValueError('blind_audio_MP3_content_metadata_forbidden')
        offset+=10+n
    if offset>limit:raise ValueError('blind_audio_MP3_truncated_metadata')


def _blind_complete_audio(path,data):
    if path.suffix.lower()=='.wav':
        measure,samples=_blind_wave(data);return measure,samples,data,'wav'
    if path.suffix.lower()=='.mp3':_blind_mp3_metadata(data)
    elif path.suffix.lower()!='.mp4':raise ValueError('blind_audio_actual_track_format_unsupported')
    # Independent complete acoustic decode. Original MP3 stays compressed on the wire.
    def run(args):
        result=subprocess.run(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=False)
        if result.returncode:raise ValueError('blind_audio_complete_acoustic_decode_failed')
        return result.stdout
    probe=json.loads(run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries',
        'stream=codec_type,sample_rate,channels,duration:format=duration','-of','json',str(path)]))
    tracks=[r for r in probe.get('streams',[])if r.get('codec_type')=='audio']
    if len(tracks)!=1:raise ValueError('blind_audio_unique_complete_audio_stream_required')
    track=tracks[0];rate=int(track['sample_rate']);channels=int(track['channels'])
    pcm=run(['ffmpeg','-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(path),
        '-map','0:a:0','-vn','-c:a','pcm_s32le','-f','s32le','pipe:1'])
    if not pcm or len(pcm)%(4*channels)or sha(path.read_bytes())!=sha(data):raise ValueError('blind_audio_complete_decoded_track_changed')
    frames=len(pcm)//(4*channels);duration=frames/rate
    source_duration=float(track.get('duration')or probe['format']['duration'])
    # Compressed packet padding is retained; never trim to force a predeclared duration.
    if abs(duration-source_duration)>0.1:raise ValueError('blind_audio_incomplete_acoustic_decode')
    import array,sys,struct
    samples=array.array('i');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    measurement={'frames':frames,'rate':rate,'channels':channels,'sample_width':4,
        'duration_seconds':duration,'pcm_sha256':sha(pcm),'original_sha256':sha(data),
        'source_duration_seconds':source_duration,'whole_track':True,'trim':False,'speed_change':False,
        'resampling':False,'channel_reduction':False}
    if path.suffix.lower()=='.mp3':return measurement,samples,data,'mp3'
    fmt=struct.pack('<HHIIHH',1,channels,rate,rate*channels*4,channels*4,32)
    wave=b'RIFF'+struct.pack('<I',36+len(pcm))+b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(pcm))+pcm
    return measurement,samples,wave,'wav'


def _blind_wave(data):
    import array,io,sys,wave
    if data[:4]!=b'RIFF'or data[8:12]!=b'WAVE'or int.from_bytes(data[4:8],'little')+8!=len(data):
        raise ValueError('blind_audio_complete_RIFF_required')
    offset=12;seen_chunks=set()
    while offset<len(data):
        if offset+8>len(data):raise ValueError('blind_audio_truncated_RIFF_chunk')
        kind=data[offset:offset+4];size=int.from_bytes(data[offset+4:offset+8],'little');payload=data[offset+8:offset+8+size]
        if len(payload)!=size:raise ValueError('blind_audio_truncated_RIFF_chunk')
        if kind in(b'fmt ',b'data',b'fact'):
            if kind in seen_chunks:raise ValueError('blind_audio_duplicate_technical_chunk')
            seen_chunks.add(kind)
        if kind==b'fact':
            if size!=4:raise ValueError('blind_audio_fact_technical_layout_required')
        elif kind==b'fmt ':
            if size not in(16,18)or int.from_bytes(payload[:2],'little')!=1 or (size==18 and payload[16:18]!=b'\x00\x00'):
                raise ValueError('blind_audio_fmt_technical_layout_required')
        elif kind==b'LIST':
            # Permit only non-content software-version metadata; never title/comment/transcript tags.
            if payload[:8]!=b'INFOISFT'or len(payload)<12:raise ValueError('blind_audio_text_metadata_forbidden')
            length=int.from_bytes(payload[8:12],'little');label=payload[12:12+length].rstrip(b'\x00')
            if len(payload)>12+length+1 or not re.fullmatch(rb'[A-Za-z]{1,20}[0-9]{1,5}(?:\.[0-9]{1,5}){1,5}',label):
                raise ValueError('blind_audio_content_metadata_forbidden')
        elif kind in(b'JUNK',b'PAD '):
            if any(payload):raise ValueError('blind_audio_nonzero_padding_metadata_forbidden')
        elif kind not in(b'fmt ',b'data',b'fact'):raise ValueError('blind_audio_unknown_metadata_forbidden')
        offset+=8+size+(size%2)
    if offset!=len(data):raise ValueError('blind_audio_truncated_RIFF_padding')
    with wave.open(io.BytesIO(data),'rb')as stream:
        frames=stream.getnframes();rate=stream.getframerate();channels=stream.getnchannels();width=stream.getsampwidth()
        if stream.getcomptype()!='NONE'or width not in(2,4) or channels not in(1,2)or not frames or rate<=0:
            raise ValueError('blind_audio_complete_PCM16_or_PCM32_WAV_required')
        pcm=stream.readframes(frames)
    if len(pcm)!=frames*channels*width:raise ValueError('blind_audio_truncated_WAV')
    offset=12
    while offset<len(data):
        size=int.from_bytes(data[offset+4:offset+8],'little')
        if data[offset:offset+4]==b'fact'and int.from_bytes(data[offset+8:offset+12],'little')!=frames:
            raise ValueError('blind_audio_fact_frame_count_changed')
        offset+=8+size+(size%2)
    samples=array.array('h'if width==2 else'i');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    return {'frames':frames,'rate':rate,'channels':channels,'sample_width':width,'duration_seconds':frames/rate,'pcm_sha256':sha(pcm)},samples


def _blind_validate(report,material):
    if (not isinstance(report,dict)or set(report)!={'heard_full_audio','language','segments'}
            or report['heard_full_audio']is not True or not isinstance(report['language'],str)
            or not report['language'].strip()or any(x in report['language'].casefold()for x in('unknown','未知','不确定'))or not isinstance(report['segments'],list)
            or not 0<len(report['segments'])<=400):raise ValueError('blind_audio_full_observation_required')
    measure=material['measurement'];samples=material['samples'];cursor=0;spoken=[];acoustics=[]
    for segment in report['segments']:
        if not isinstance(segment,dict)or set(segment)!={'start_seconds','end_seconds','kind','text','pace','stress','naturalness','observations'}:
            raise ValueError('blind_audio_exact_time_segment_required')
        if any(type(segment[k])not in(int,float)or not math.isfinite(segment[k])for k in('start_seconds','end_seconds')):
            raise ValueError('blind_audio_finite_time_required')
        start=round(segment['start_seconds']*measure['rate']);end=round(segment['end_seconds']*measure['rate'])
        if not 0<=segment['start_seconds']<segment['end_seconds']<=measure['duration_seconds']or start!=cursor or not start<end<=measure['frames']:raise ValueError('blind_audio_full_track_time_coverage_required')
        values=samples[start*measure['channels']:end*measure['channels']];peak=max(abs(v)for v in values)
        if segment['kind']=='speech':
            for name in('text','pace','stress','naturalness','observations'):
                value=segment[name]
                if not isinstance(value,str)or not value.strip()or any(x in value.casefold()for x in('unknown','inaudible','unobservable','cannot hear','cannot determine','无法判断','无法听','未听','不确定','未知','听不清','无法观察')):
                    raise ValueError('blind_audio_actual_acoustic_observation_unknown')
            if not peak:raise ValueError('blind_audio_speech_on_digital_silence')
            spoken.append(segment['text'])
        elif segment['kind']in('music','sound'):
            if segment['text']!=''or not peak:raise ValueError('blind_audio_non_speech_contradicts_actual_waveform')
            for name in('pace','stress','naturalness','observations'):
                value=segment[name]
                if not isinstance(value,str)or not value.strip()or any(x in value.casefold()for x in('unknown','未知','不确定','cannot hear')):
                    raise ValueError('blind_audio_actual_acoustic_observation_unknown')
        elif segment['kind']=='silence':
            if segment['text']!=''or peak:raise ValueError('blind_audio_silence_contradicts_actual_waveform')
        else:raise ValueError('blind_audio_observation_kind_unknown')
        acoustics.append({'start_frame':start,'end_frame':end,'peak_sample':peak,
            'rms_sample':math.sqrt(sum(v*v for v in values)/len(values)),
            'characters_per_second':len(segment['text'])/((end-start)/measure['rate'])})
        cursor=end
    if cursor!=measure['frames']or _spoken_key(''.join(spoken))!=_spoken_key(material['script']):
        raise ValueError('blind_audio_full_heard_script_mismatch')
    return {'full_transcript_matches_actual_tts_text':True,'original_voice_plan_ref':material['voice_plan_ref'],
        'measurement':measure,'segment_measurements':acoustics,'business_quality_passed':False,
        'voice_style_quality_requires_independent_WATCH':True}


def _blind_json(text):
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('blind_audio_duplicate_JSON_key')
            value[key]=item
        return value
    return json.loads(text,object_pairs_hook=pairs)


def _blind_request_text_and_audio(value,mode):
    if mode=='chat_completions':
        if set(value)!={'model','messages','max_tokens','stream'}or value.get('stream')is not False:raise ValueError('blind_audio_extra_wire_context_forbidden')
        if len(value.get('messages',[]))!=1 or value['messages'][0].get('role')!='user' or value.get('tools'):
            raise ValueError('blind_audio_fresh_toolless_messages_required')
        parts=value['messages'][0]['content']
        if len(parts)!=2 or [x.get('type')for x in parts]!=['text','input_audio']:
            raise ValueError('blind_audio_exact_wire_parts_required')
        return parts[0]['text'],base64.b64decode(parts[1]['input_audio']['data'],validate=True)
    if mode=='google_generate_content':
        if set(value)!={'contents','generationConfig'}:raise ValueError('blind_audio_extra_wire_context_forbidden')
        if len(value.get('contents',[]))!=1 or value['contents'][0].get('role')!='user' or value.get('tools')or value.get('systemInstruction'):
            raise ValueError('blind_audio_fresh_toolless_messages_required')
        parts=value['contents'][0]['parts']
        if len(parts)!=2 or set(parts[0])!={'text'}or set(parts[1])!={'inlineData'}:
            raise ValueError('blind_audio_exact_wire_parts_required')
        return parts[0]['text'],base64.b64decode(parts[1]['inlineData']['data'],validate=True)
    if mode=='google_interactions':
        if set(value)!={'model','store','input','generation_config'}or value.get('store')is not False:raise ValueError('blind_audio_extra_wire_context_forbidden')
        parts=value['input']
        if len(parts)!=2 or [x.get('type')for x in parts]!=['text','audio']or value.get('tools')or value.get('previous_interaction_id'):
            raise ValueError('blind_audio_fresh_toolless_messages_required')
        return parts[0]['text'],base64.b64decode(parts[1]['data'],validate=True)
    raise ValueError('blind_audio_current_protocol_unknown')


def _finish_blind_audio(receipt,material,out):
    if material is None or receipt.get('status')!='pending_blind_evidence':return
    try:
        report=_blind_json(receipt['raw_analysis_text']);validation=_blind_validate(report,material)
        request=Path(out/'actual-request.private.json').read_bytes();response=Path(out/'actual-response.private.json').read_bytes()
        text,wire=_blind_request_text_and_audio(json.loads(request),receipt['api_mode'])
        if text!=_blind_audio_prompt(material['measurement']['duration_seconds'],material['scope']['context_sha256'])or sha(wire)!=material['wire_sha256']:
            raise ValueError('blind_audio_wire_or_prompt_leaked_or_changed')
        evidence={'version':'scoped_full_audio_blind_observation_v2','scope_ref':material['scope_ref'],
            'task_job_id':material['scope']['task_job_id'],'context_sha256':material['scope']['context_sha256'],
            'audio_ref':material['audio_ref'],'script_ref':material['script_ref'],'voice_plan_ref':material['voice_plan_ref'],
            'request_ref':{'path':str(out/'actual-request.private.json'),'sha256':sha(request)},
            'response_ref':{'path':str(out/'actual-response.private.json'),'sha256':sha(response)},
            'reader_source_ref':{'path':str(Path(__file__).resolve()),'sha256':sha(Path(__file__).read_bytes())},
            'report':report,'validation':validation,'route':receipt['blind_current_route']}
        raw=canonical(evidence)+b'\n';target=out/'blind-evidence.private.json';write_private(target,raw)
        receipt.update(status='completed',blind_evidence_ref={'path':str(target),'sha256':sha(raw)})
    except (ValueError,TypeError,KeyError,UnicodeError)as error:
        receipt.update(status='unverified_audio_input',reason=str(error)if re.fullmatch('[a-z_0-9]+',str(error))else'blind_audio_evidence_invalid')


def verify_scoped_blind_audio(tool_result,context,args,task_id,scope_ref):
    from .factual_candidate_revision import private_read
    receipt=tool_result['auxiliary_execution']
    if receipt.get('evidence_mode')not in{'scoped_blind_full_WAV_v1','scoped_blind_full_audio_v2'}:return
    actual=private_read(tool_result['execution_receipt_path'],sha(canonical(receipt)+b'\n'))
    if actual!=receipt or receipt.get('status')!='completed'or receipt.get('http_status')!=200:
        raise ValueError('blind_audio_actual_completed_receipt_required')
    material=_blind_material(scope_ref,args['audio_path'],args['audio_sha256'],sha(canonical(context)),task_id)
    evidence=private_read(receipt['blind_evidence_ref']['path'],receipt['blind_evidence_ref']['sha256'])
    if (not isinstance(evidence,dict)or set(evidence)!={'version','scope_ref','task_job_id','context_sha256','audio_ref','script_ref','voice_plan_ref','request_ref','response_ref','reader_source_ref','report','validation','route'}
            or evidence.get('version')!='scoped_full_audio_blind_observation_v2'or evidence.get('scope_ref')!=scope_ref or evidence.get('task_job_id')!=task_id
            or evidence.get('context_sha256')!=sha(canonical(context))or evidence.get('audio_ref')!=material['audio_ref']
            or evidence.get('script_ref')!=material['script_ref']or evidence.get('voice_plan_ref')!=material['voice_plan_ref']
            or evidence.get('reader_source_ref')!={'path':str(Path(__file__).resolve()),'sha256':sha(Path(__file__).read_bytes())}
            or evidence.get('validation')!=_blind_validate(evidence['report'],material)):
        raise ValueError('blind_audio_current_scope_or_original_evidence_changed')
    request=_blind_read(evidence['request_ref']);response=_blind_read(evidence['response_ref'])
    request_value=json.loads(request)
    text,wire=_blind_request_text_and_audio(request_value,receipt['api_mode'])
    if receipt['api_mode']in{'chat_completions','google_interactions'}and request_value['model']!=receipt['model']:raise ValueError('blind_audio_wire_model_changed')
    if (text!=_blind_audio_prompt(material['measurement']['duration_seconds'],material['scope']['context_sha256'])
            or sha(wire)!=material['wire_sha256']or sha(request)!=receipt.get('request_sha256')
            or sha(response)!=receipt.get('response_sha256')or _blind_json(tool_result['analysis'])!=evidence['report']):
        raise ValueError('blind_audio_actual_request_or_result_changed')
    value=json.loads(response)
    if receipt['api_mode']=='chat_completions':raw=''.join(c.get('message',{}).get('content','')or''for c in value.get('choices',[]))
    elif receipt['api_mode']=='google_generate_content':raw=''.join(p.get('text','')for c in value.get('candidates',[])for p in c.get('content',{}).get('parts',[])if not p.get('thought'))
    else:raw=''.join(x.get('text','')for x in value.get('outputs',value.get('output',[]))if x.get('type')=='text')
    if _blind_json(raw)!=evidence['report']:raise ValueError('blind_audio_original_model_response_changed')
    role=material['scope']['current_role_route'];route=evidence['route']
    from .quality_review_submission import _vision_endpoint_digest
    if (role.get('endpoint')and route['endpoint_sha256']!=_vision_endpoint_digest(role['endpoint']))or(role.get('api_mode')is not None and route['api_mode']!=role['api_mode']):
        raise ValueError('blind_audio_current_role_endpoint_changed')
    if role.get('endpoint')and receipt['api_mode']=='chat_completions'and receipt.get('blind_wire_endpoint_sha256')!=sha((role['endpoint'].rstrip('/')+'/chat/completions').encode()):
        raise ValueError('blind_audio_wire_endpoint_changed')
    if (route!=receipt.get('blind_current_route')or route['role_route_sha256']!=sha(canonical(role))
            or route['provider']!=role['provider']or route['model']!=role['model']):
        raise ValueError('blind_audio_current_role_route_changed')


def read_prepared_audio_records(prepared_ref,*,tts_records_ref=None):
    """Read the existing prepared-record schema. This is material, never QA or authority."""
    raw=_blind_read(prepared_ref);value=_blind_json(raw.decode('utf-8-sig'))
    if isinstance(value,dict)and value.get('schema')=='current_hermes_prosody_execution_v1':
        return _read_current_prosody_records(value,prepared_ref,tts_records_ref)
    if (not isinstance(value,dict)or not isinstance(value.get('records'),list)
            or not 0<len(value['records'])<=400):raise ValueError('prepared_audio_original_records_required')
    result=[];seen_ids=set();seen_paths=set();total=0.0
    required={'beat_id','source_text','source_text_sha256','tts_text','path','audio_sha256',
        'duration_seconds','sample_rate','provider','voice','speed','fallback_used'}
    for index,row in enumerate(value['records']):
        if not isinstance(row,dict)or not required<=set(row):raise ValueError('prepared_audio_actual_record_schema_required')
        if (not isinstance(row['beat_id'],str)or not row['beat_id']or row['beat_id']in seen_ids
                or not isinstance(row['path'],str)or not Path(row['path']).is_absolute()or row['path']in seen_paths):
            raise ValueError('prepared_audio_unique_original_record_required')
        if any(not isinstance(row[k],str)or not row[k].strip()for k in('source_text','tts_text','provider','voice')):
            raise ValueError('prepared_audio_actual_text_and_voice_required')
        if sha(row['source_text'].encode())!=row['source_text_sha256']or not re.fullmatch('[a-f0-9]{64}',str(row['audio_sha256'])):
            raise ValueError('prepared_audio_source_text_or_audio_SHA_changed')
        if (row['fallback_used']is not False or type(row['duration_seconds'])not in(int,float)
                or not math.isfinite(row['duration_seconds'])or row['duration_seconds']<=0
                or type(row['sample_rate'])is not int or row['sample_rate']<=0
                or type(row['speed'])not in(int,float)or not math.isfinite(row['speed'])or row['speed']<=0):
            raise ValueError('prepared_audio_actual_controls_required')
        audio_ref={'path':row['path'],'sha256':row['audio_sha256']};audio=_blind_read(audio_ref)
        measure,_=_blind_wave(audio)
        if measure['rate']!=row['sample_rate']or abs(measure['duration_seconds']-row['duration_seconds'])>1/measure['rate']:
            raise ValueError('prepared_audio_actual_duration_or_rate_changed')
        identity=_spoken_key(row['source_text'])==_spoken_key(row['tts_text'])
        result.append({'index':index,'beat_id':row['beat_id'],'audio_ref':audio_ref,
            'source_text':row['source_text'],'source_text_sha256':row['source_text_sha256'],
            'tts_text':row['tts_text'],'tts_text_sha256':sha(row['tts_text'].encode()),
            'voice':row['voice'],'speed':row['speed'],'measurement':measure,
            'source_and_spoken_identity':identity,'independent_equivalence_review_required':not identity})
        seen_ids.add(row['beat_id']);seen_paths.add(row['path']);total+=measure['duration_seconds']
    if (type(value.get('duration_seconds'))not in(int,float)or not math.isfinite(value['duration_seconds'])
            or abs(total-value['duration_seconds'])>max(1/r['measurement']['rate']for r in result)):
        raise ValueError('prepared_audio_complete_ordered_duration_changed')
    return {'version':'existing_prepared_audio_material_view_v1','prepared_ref':prepared_ref,'records':result,
        'source_text':''.join(r['source_text']for r in result),'tts_text':''.join(r['tts_text']for r in result),
        'duration_seconds':total,'qualification':'material_only_current_scope_binding_and_independent_equivalence_still_required'}


def _read_current_prosody_records(value,prepared_ref,tts_records_ref):
    """Actual normal_film_audio v2 records; never reinterpret them as legacy prepared rows."""
    if tts_records_ref is None:raise ValueError('current_prosody_actual_film_records_required')
    film=_blind_json(_blind_read(tts_records_ref));records=value.get('records');capability=value.get('capability')or{}
    if (not isinstance(records,list)or len(records)!=8 or not isinstance(film,list)or len(film)!=8
            or not re.fullmatch('[a-f0-9]{64}',str(capability.get('hermes_config_sha256')or''))):
        raise ValueError('current_prosody_complete_eight_records_required')
    plan_refs=[r.get('voice_plan_source')for r in film]
    if (any(not isinstance(r,dict)or not {'path','sha256'}<=set(r)for r in plan_refs)
            or len({(r['path'],r['sha256'])for r in plan_refs})!=1):
        raise ValueError('current_prosody_unique_original_voice_plan_required')
    source_plan=_blind_json(_blind_read(plan_refs[0]))
    from .voice_plan import build_voice_plan
    declared=build_voice_plan([r.get('text')for r in records],segment_styles=source_plan.get('voice_plan'))
    result=[];seen=set();total=0.0
    for index,(original,padded)in enumerate(zip(records,film)):
        if (any(original.get(k)!=declared[index].get(k)for k in('text','style','semantic_direction'))
                or original.get('requested_controls')!={k:declared[index][k]for k in('rate','pitch','pause_after_ms')}):
            raise ValueError('current_prosody_original_voice_plan_controls_changed')
        if (not isinstance(original,dict)or not isinstance(padded,dict)or original.get('index')!=index
                or padded.get('index')!=index or not isinstance(original.get('text'),str)or not original['text'].strip()
                or sha(original['text'].encode())!=original.get('source_text_sha256')or original.get('fallback_used')is not False):
            raise ValueError('current_prosody_actual_text_or_index_changed')
        controls=original.get('requested_controls')or{};performed=original.get('performed_provider_controls')or{}
        if (set(controls)!={'rate','pitch','pause_after_ms'}or set(performed)!={'rate','pitch'}
                or any(not isinstance(controls[k],str)or not controls[k]or controls[k]!=performed[k]for k in('rate','pitch'))
                or type(controls['pause_after_ms'])not in(int,float)or not math.isfinite(controls['pause_after_ms'])or controls['pause_after_ms']<0):
            raise ValueError('current_prosody_performed_controls_required')
        required_same=('text','source_text_sha256','voice','provider','style','semantic_direction','requested_controls',
            'performed_provider_controls','decoded_audio_path','decoded_audio_sha256','decoded_duration_seconds',
            'provider_word_boundaries','word_boundary_method','fallback_used')
        if (any(padded.get(k)!=original.get(k)for k in required_same)
                or padded.get('tts_text')!=original['text']or padded.get('display_text')!=original['text']
                or any(padded.get(k)!=controls[k]for k in('rate','pitch','pause_after_ms'))
                or not isinstance(original.get('voice'),str)or not original['voice']
                or not isinstance(original.get('provider'),str)or not original['provider']or original.get('voice')!=capability.get('voice')):
            raise ValueError('current_prosody_film_source_controls_or_words_changed')
        for label in('audio','decoded_audio'):
            _blind_read({'path':original[label+'_path'],'sha256':original[label+'_sha256']})
        decoded,_=_blind_wave(_blind_read({'path':original['decoded_audio_path'],'sha256':original['decoded_audio_sha256']}))
        ref={'path':padded['audio_path'],'sha256':padded['audio_sha256']}
        measurement,_=_blind_wave(_blind_read(ref))
        if (ref['path']in seen or abs(decoded['duration_seconds']-original['decoded_duration_seconds'])>1/decoded['rate']
                or abs(measurement['duration_seconds']-padded['duration_seconds'])>1/measurement['rate']
                or abs(measurement['duration_seconds']-decoded['duration_seconds']-controls['pause_after_ms']/1000)>0.03):
            raise ValueError('current_prosody_complete_padded_audio_changed')
        words=original.get('provider_word_boundaries')
        if not isinstance(words,list)or not words or original.get('word_boundary_method')!='provider_events':
            raise ValueError('current_prosody_actual_provider_words_required')
        cursor=-1.0;heard=[]
        for word in words:
            if (not isinstance(word,dict)or not isinstance(word.get('word'),str)or not word['word']
                    or any(type(word.get(k))not in(int,float)or not math.isfinite(word[k])for k in('start','end'))
                    or not 0<=word['start']<word['end']<=original['duration_seconds']+0.02 or word['start']<cursor-0.02):
                raise ValueError('current_prosody_actual_provider_word_time_invalid')
            heard.append(word['word']);cursor=word['end']
        if _spoken_key(''.join(heard))!=_spoken_key(original['text']):raise ValueError('current_prosody_actual_provider_word_text_changed')
        result.append({'index':index,'audio_ref':ref,'source_text':original['text'],'source_text_sha256':original['source_text_sha256'],
            'tts_text':padded['tts_text'],'tts_text_sha256':sha(padded['tts_text'].encode()),'voice':original['voice'],
            'requested_controls':controls,'performed_provider_controls':performed,'provider_word_boundaries':words,
            'original_audio_ref':{'path':original['audio_path'],'sha256':original['audio_sha256']},
            'decoded_audio_ref':{'path':original['decoded_audio_path'],'sha256':original['decoded_audio_sha256']},
            'measurement':measurement,'source_and_spoken_identity':True,'independent_equivalence_review_required':True})
        seen.add(ref['path']);total+=measurement['duration_seconds']
    whole={'path':value['audio_path'],'sha256':value['audio_sha256']};measurement,_=_blind_wave(_blind_read(whole))
    if (type(value.get('duration_seconds'))not in(int,float)or not math.isfinite(value['duration_seconds'])
            or abs(measurement['duration_seconds']-value['duration_seconds'])>1/measurement['rate']
            or abs(measurement['duration_seconds']-total)>0.03 or value.get('decode_exit')!=0):
        raise ValueError('current_prosody_complete_narration_duration_changed')
    return {'version':'current_prosody_audio_material_view_v1','prepared_ref':prepared_ref,'tts_records_ref':tts_records_ref,
        'original_schema':value['schema'],'records':result,'source_text':''.join(r['source_text']for r in result),
        'tts_text':''.join(r['tts_text']for r in result),'full_narration_ref':whole,'duration_seconds':measurement['duration_seconds'],
        'qualification':'material_only_current_scope_binding_and_independent_equivalence_still_required'}
