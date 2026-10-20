"""Normal active-task current modal factory; uses the shared pinned authority resolver."""
from __future__ import annotations
import hashlib,json,os,time
from pathlib import Path
from typing import Callable
from .current_modal_resolver import build_current_modal_resolver
def _sha(raw):return hashlib.sha256(raw).hexdigest()

def current_normal_modal_resolver(*,native_audio_capability=None)->Callable[[],dict]:
    """Trusted normal subprocess factory from current HERMES_HOME and live lease.
    No model argument, packet receipt, stale role, or canonical home fallback.
    """
    import re,sys,urllib.request
    from hermes_constants import get_hermes_home
    home=Path(get_hermes_home())
    if home.is_symlink() or home.parent!=Path('/srv/hermes-worker/authority-runtime-homes'):
        raise PermissionError('normal_current_modal_isolated_task_home_required')
    binding=home/'old-runtime-authority.private.json'
    if binding.is_symlink() or not binding.is_file() or binding.stat().st_mode&0o077:
        raise PermissionError('normal_current_modal_private_binding_required')
    raw=binding.read_bytes();receipt=json.loads(raw);receipt['authority_receipt_sha256']=_sha(raw)
    jid=receipt.get('task_id') or receipt.get('job_id')
    if not re.fullmatch('[a-f0-9]{32}',str(jid or '')) or receipt.get('home')!=str(home):
        raise PermissionError('normal_current_modal_original_job_required')
    if '/srv/hermes-worker' not in sys.path:sys.path.insert(0,'/srv/hermes-worker')
    from current_task_runtime import official_verify_current
    from new_media_authority_consumer_r5 import require_role
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise PermissionError('normal_current_modal_lease_redirect_forbidden')
    def verify(value):
        base=os.environ.get('HERMES_WORKER_CONTROL_URL','')
        worker=os.environ.get('HERMES_WORKER_ID','');token=os.environ.get('HERMES_WORKER_CONTROL_TOKEN','')
        if base!='http://127.0.0.1:22120' or not worker or not token:
            raise PermissionError('normal_current_modal_live_worker_authority_missing')
        req=urllib.request.Request(base+'/v1/jobs/'+jid,headers={'X-Hermes-Worker-Token':token})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        with opener.open(req,timeout=12) as response:
            if response.status!=200:raise PermissionError('normal_current_modal_live_job_unavailable')
            data=response.read(65537)
        if not 0<len(data)<=65536:raise PermissionError('normal_current_modal_live_job_response_invalid')
        job=json.loads(data)
        if (job.get('job_id')!=jid or job.get('status')!='running' or job.get('worker_id')!=worker
                or type(job.get('lease_until')) not in (int,float) or job['lease_until']<=time.time()):
            raise PermissionError('normal_current_modal_original_job_not_active')
        proof=official_verify_current(value);require_role(value,proof,0)
    budget=receipt.get('business_budget_seconds')
    if type(budget) not in (int,float) or not 0<budget<=21600:
        raise PermissionError('normal_current_modal_original_business_budget_required')
    # Materialization already checked capture <=120s; later native tools use the
    # same live active lease and pinned task lifetime, not a newly chosen route.
    resolver=build_current_modal_resolver(receipt,native_role_verifier=verify,first_use_max_age_seconds=budget)
    def audio_runtime():
        return _audio_runtime_for_current_task(resolver,receipt,verify,native_audio_capability=native_audio_capability)
    resolver.audio_review_runtime=audio_runtime
    return resolver


def _selected_audio_route(modal,receipt):
    """Only the verified current Role and its signed native auxiliary projection."""
    main=receipt.get('current_route')
    if (not isinstance(main,dict) or any(not isinstance(main.get(k),str) or not main[k].strip()
            for k in ('provider','model')) or main['provider'].strip().lower()=='auto'):
        raise PermissionError('audio_review_signed_current_main_route_required')
    role=modal.get('auxiliary_audio_review') or {}
    if not isinstance(role,dict):raise PermissionError('audio_review_native_selection_invalid')
    if role.get('enabled',True) is not True:raise PermissionError('audio_review_explicitly_disabled')
    selected=dict(main);source='signed_current_main_route'
    explicit={k:role.get(k) for k in ('provider','model','api_mode','base_url') if role.get(k)}
    if explicit:
        provider=str(role.get('provider') or '').strip()
        model=str(role.get('model') or '').strip()
        if provider.lower() in ('','auto'):
            provider=main['provider']
        if not model:model=main['model'] if provider==main['provider'] else ''
        if not model:raise PermissionError('audio_review_explicit_provider_requires_model')
        selected={'provider':provider,'model':model}
        if role.get('api_mode'):selected['api_mode']=role['api_mode']
        if role.get('base_url'):selected['endpoint']=role['base_url']
        source='signed_current_native_audio_review_selection'
    return selected,role,source


def _resolve_audio_runtime(modal,receipt,verify,*,native_audio_capability=None):
    """Credentials/client stay in this process; no defaults, alternate route or SDK ladder."""
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from agent.auxiliary_client import resolve_provider_client
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':
        raise PermissionError('audio_review_original_no_publication_required')
    verify(receipt)
    route,role,source=_selected_audio_route(modal,receipt)
    bridge=_bridge_native_audio_binding(native_audio_capability,route)
    if bridge and source!='signed_current_main_route':raise PermissionError('audio_review_native_bridge_requires_current_primary')
    kwargs={'requested':route['provider'],'target_model':route['model']}
    if route.get('endpoint'):kwargs['explicit_base_url']=route['endpoint']
    runtime=resolve_runtime_provider(**kwargs)
    if (not isinstance(runtime,dict) or not runtime.get('provider') or not runtime.get('base_url')
            or not runtime.get('api_key')):
        raise PermissionError('audio_review_current_runtime_credentials_missing')
    native_google=route.get('api_mode') in {'google_generate_content','google_interactions'}
    mode=route.get('api_mode') if native_google else runtime.get('api_mode')
    if not isinstance(mode,str) or not mode:raise PermissionError('audio_review_current_protocol_missing')
    if not native_google and route.get('api_mode') and mode!=route['api_mode']:
        raise PermissionError('audio_review_current_protocol_changed')
    base=str(runtime['base_url']).rstrip('/')
    if route.get('endpoint') and base!=str(route['endpoint']).rstrip('/'):
        raise PermissionError('audio_review_current_endpoint_changed')
    if native_google:
        # This is the original signed native-audio protocol, never a fallback from Chat.
        # Official runtime resolution supplies credentials; the selected native protocol
        # is not replaced by that resolver's OpenAI-compatible auxiliary surface.
        if route['provider'] not in {'google','gemini'} or runtime['provider']!='gemini' or base!='https://generativelanguage.googleapis.com/v1beta':
            raise PermissionError('audio_review_native_google_signed_endpoint_required')
    elif mode!='chat_completions':
        raise PermissionError('audio_review_actual_protocol_not_supported_'+str(mode))
    timeout=role.get('timeout',90);tokens=role.get('max_output_tokens',1800)
    if type(timeout) not in (int,float) or not 0<timeout<=90 or type(tokens) is not int or not 0<tokens<=1800:
        raise PermissionError('audio_review_native_limits_invalid')
    # The parent process retains its original hard deadline. Never extend signed expiry.
    for field in ('cycle_execution_deadline_unix','expires_at_unix'):
        deadline=receipt.get(field)
        if type(deadline) in (int,float) and deadline>0:timeout=min(timeout,deadline-time.time())
    if timeout<=0:raise PermissionError('audio_review_original_deadline_elapsed')
    if native_google:
        from .media_transport_runtime import native_audio_network_proxy
        if not isinstance(runtime['api_key'],str):raise PermissionError('audio_review_native_google_key_type_unsupported')
        return {'provider':route['provider'],'model':route['model'],'api_mode':mode,'base_url':base,
            'client':None,'api_key':runtime['api_key'],'network_proxy':native_audio_network_proxy(base,receipt['home']),
            'selection_source':source,'timeout_seconds':timeout,'max_output_tokens':tokens,
            'credential_runtime_api_mode':runtime.get('api_mode'),'thinking_level':role.get('thinking_level'),
            'authority_receipt_sha256':receipt.get('authority_receipt_sha256'),
            'source_snapshot_sha256':receipt.get('source_snapshot_sha256')}
    client,model=resolve_provider_client(
        provider=runtime.get('requested_provider') or route['provider'],model=route['model'],
        explicit_base_url=runtime['base_url'],explicit_api_key=runtime['api_key'],
        api_mode=mode,main_runtime=runtime,task='audio_review')
    if client is None or model!=route['model']:
        if client is not None and hasattr(client,'close'):client.close()
        raise PermissionError('audio_review_official_client_model_changed_or_missing')
    if str(getattr(client,'base_url','')).rstrip('/')!=base:
        if hasattr(client,'close'):client.close()
        raise PermissionError('audio_review_official_client_endpoint_changed')
    if (not callable(getattr(client,'with_options',None)) or not hasattr(client,'with_raw_response')
            or not hasattr(getattr(client,'_client',None),'event_hooks')):
        if hasattr(client,'close'):client.close()
        raise PermissionError('audio_review_actual_client_has_no_lossless_audio_transport')
    from .media_transport_runtime import bind_audio_client_transport
    client=bind_audio_client_transport(client,{**route,'api_mode':mode,'endpoint':base},runtime['provider'],receipt['home'],modal=modal,receipt=receipt,required_seconds=timeout)
    if bridge:
        # Preserve the exact official client credentials and custom headers in memory.
        # No SDK retry/call ladder and no secondary Google credential resolution.
        if (not isinstance(runtime['api_key'],str) or getattr(client,'api_key',None)!=runtime['api_key']):
            client.close();raise PermissionError('audio_review_native_bridge_same_primary_credential_required')
        headers=_primary_native_headers(client)
        from httpx import Headers
        if Headers(headers).get('authorization')!='Bearer '+runtime['api_key']:
            client.close();raise PermissionError('audio_review_native_bridge_same_primary_header_required')
        return {'provider':route['provider'],'model':route['model'],'api_mode':'google_generate_content',
            'base_url':bridge['native_base_url'],'client':client,'native_transport_headers':headers,
            'native_audio_capability':bridge,'selection_source':'signed_current_primary_explicit_native_audio_protocol',
            'timeout_seconds':timeout,'max_output_tokens':tokens,'credential_runtime_api_mode':mode,
            'authority_receipt_sha256':receipt.get('authority_receipt_sha256'),
            'source_snapshot_sha256':receipt.get('source_snapshot_sha256')}
    return {'provider':route['provider'],'model':route['model'],'api_mode':mode,'base_url':base,
        'client':client,'selection_source':source,'timeout_seconds':timeout,'max_output_tokens':tokens,
        'authority_receipt_sha256':receipt.get('authority_receipt_sha256'),
        'source_snapshot_sha256':receipt.get('source_snapshot_sha256')}


def _audio_runtime_for_current_task(resolver,receipt,verify,*,native_audio_capability=None):
    # current_route is an in-memory convenience, not part of the persistent Role schema.
    # Use the same native ready + profile + authority getter as current_active_role.
    from .mandatory_quality_context import _native_task_home
    modal=resolver()
    task=receipt.get('task_id') or receipt.get('job_id')
    home,route,provenance=_native_task_home(task)
    expected={'provider':receipt.get('requested_provider'),
        'model':(receipt.get('provenance')or{}).get('model'),
        'api_mode':(receipt.get('provenance')or{}).get('api_mode'),
        'endpoint':(receipt.get('provenance')or{}).get('endpoint')}
    if (receipt.get('profile_id')!=task or Path(receipt.get('home')or'')!=home
            or home.name!='media-'+str(task) or route!=expected or provenance!=receipt.get('provenance')):
        raise PermissionError('audio_review_same_current_role_route_required')
    derived={**receipt,'current_route':dict(route)}
    # Verification still receives the untouched persistent binding, never a rewritten file.
    return _resolve_audio_runtime(modal,derived,lambda value:verify(receipt),native_audio_capability=native_audio_capability)


# Root-reviewed immutable protocol declaration; opt-in only, never a route fallback.
ROOT_NATIVE_AUDIO_CAPABILITY={'schema': 'root_same_primary_native_audio_protocol_v1', 'purpose': 'explicit_current_primary_audio_capability_diagnosis_no_quality_pass', 'provider': 'custom:antigravity-tools', 'primary_api_mode': 'chat_completions', 'primary_base_url': 'http://127.0.0.1:8045/v1', 'native_api_mode': 'google_generate_content', 'native_path': '/v1beta', 'current_model': 'exact_verified_signed_primary_no_model_override', 'credential_source': 'same_official_resolved_primary_client', 'bridge_image_digest': 'sha256:43a25583ee6922d8c6bd4a7068c763a937e4fe2015beae8219ed17c2f22e4b83', 'bridge_tag': 'v4.9.6', 'bridge_source_commit': 'b601f5e7375343343922ccab5e50653bc3450c3b', 'server_sha256': '83152089103021e9746de5308c045cc1fb69671db773697f70c2bdc5170b25ab', 'handler_sha256': '742fc85f4539ef6861e51565d0f477faa0e0a076a3c45130302da1f47b8b4828', 'wrapper_sha256': '75145e16e81a0c74d0b99b3e4f4ee958f24be99ff820ebc895dce7d0f35a5a86', 'collector_sha256': 'b4be4305dfa6b8a626f36f926ca0fc71143f577396fe6992933fa70d750d496a', 'auth_sha256': '61d1407fced615688c71aca6a57f8aba03297739e50846964e19b26bbe27dca9', 'caddy_sha256': '34f45df9a2f3d4b30042843a33cd209389c3a0e2d19329be85b1a2d95b2a5501'}
ROOT_NATIVE_AUDIO_CAPABILITY_SHA256='bf91a8ca6ddbb70527f43766de21d2194120a107ce3e1dd3ec45f276fdcaae39'

def _bridge_native_audio_binding(capability,route):
    if capability is None:return None
    expected=_sha(json.dumps(ROOT_NATIVE_AUDIO_CAPABILITY,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    if capability!=ROOT_NATIVE_AUDIO_CAPABILITY_SHA256 or expected!=ROOT_NATIVE_AUDIO_CAPABILITY_SHA256:
        raise PermissionError('audio_review_root_native_protocol_declaration_required')
    d=ROOT_NATIVE_AUDIO_CAPABILITY
    from urllib.parse import urlsplit,urlunsplit
    base=str(route.get('endpoint')or'').rstrip('/');u=urlsplit(base)
    if (route.get('provider')!=d['provider']or route.get('api_mode')!=d['primary_api_mode']
            or base!=d['primary_base_url']or u.scheme!='http'or u.hostname!='127.0.0.1'or u.port!=8045
            or u.username or u.password or u.query or u.fragment or u.path!='/v1'
            or not isinstance(route.get('model'),str)or not route['model'].strip()):
        raise PermissionError('audio_review_native_bridge_exact_current_primary_required')
    return {'schema':'same_primary_native_audio_binding_v1','declaration_sha256':expected,
        'signed_primary_route':dict(route),'native_api_mode':d['native_api_mode'],
        'native_base_url':urlunsplit((u.scheme,u.netloc,d['native_path'],'',''))}

def _primary_native_headers(client):
    # OpenAI's public Omit sentinel is an intentional header removal, not a value.
    from openai import Omit
    headers={k:v for k,v in client.default_headers.items()if not isinstance(v,Omit)}
    if any(not isinstance(k,str)or not isinstance(v,(str,bytes))for k,v in headers.items()):
        raise PermissionError('audio_review_native_bridge_actual_headers_invalid')
    return headers

def verify_native_bridge_audio_wire(route):
    binding=route.get('native_audio_capability')
    if not isinstance(binding,dict):raise PermissionError('audio_review_native_bridge_binding_required')
    expected=_bridge_native_audio_binding(binding.get('declaration_sha256'),binding.get('signed_primary_route')or{})
    if (binding!=expected or route.get('provider')!=expected['signed_primary_route']['provider']
            or route.get('model')!=expected['signed_primary_route']['model']
            or route.get('api_mode')!=expected['native_api_mode']or route.get('base_url')!=expected['native_base_url']
            or route.get('selection_source')!='signed_current_primary_explicit_native_audio_protocol'
            or str(getattr(route.get('client'),'base_url','')).rstrip('/')!=expected['signed_primary_route']['endpoint']):
        raise PermissionError('audio_review_native_bridge_wire_changed')
    from httpx import Headers
    client=route['client'];key=getattr(client,'api_key',None)
    headers=route.get('native_transport_headers')
    if (not isinstance(key,str)or not key or not isinstance(headers,dict)
            or headers!=_primary_native_headers(client)
            or Headers(headers).get('authorization')!='Bearer '+key):
        raise PermissionError('audio_review_native_bridge_same_primary_header_required')
    return expected
