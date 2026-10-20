"""Current audio capability from the same verified normal task authority receipt.

No packet/model-supplied context, canonical credential fallback, or stale profile defaults.
Producer writes the current-modal pin while materializing the verified runtime bundle.
"""
from __future__ import annotations
import hashlib,json,math,os,time
from pathlib import Path
from typing import Callable

def _sha(raw:bytes)->str:return hashlib.sha256(raw).hexdigest()
def _canonical(value)->bytes:return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def _private_read(path:Path,expected:str)->bytes:
 if not path.is_absolute() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):raise ValueError('current_modal_path_not_regular')
 before=path.stat()
 if not path.is_file() or before.st_mode&0o077:raise ValueError('current_modal_private_file_required')
 raw=path.read_bytes();after=path.stat()
 if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns) or _sha(raw)!=expected:raise ValueError('current_modal_authority_pin_changed')
 return raw

def current_modal_metadata(native_config:dict,*,source_config_sha256:str,captured_at_unix:float)->dict:
 """Called only by current authority exporter after its native config read.
 Projection is private but excludes credentials; chat model never substitutes TTS/STT.
 """
 if not isinstance(native_config,dict) or not isinstance(source_config_sha256,str) or len(source_config_sha256)!=64:raise ValueError('current_native_config_identity_required')
 def sanitized(value):
  if isinstance(value,dict):
   return {k:sanitized(v) for k,v in value.items() if not any(s in k.casefold() for s in ('api_key','apikey','token','secret','password','credential','authorization'))}
  if isinstance(value,list):return [sanitized(v) for v in value]
  if value is None or type(value) in (str,int,float,bool):return value
  raise ValueError('current_modal_config_type_invalid')
 auxiliary=native_config.get('auxiliary') or {}
 aux=auxiliary.get('tts_audio_tags') or {}
 audio_review=auxiliary.get('audio_review') or {}
 return {'schema':'hermes_current_modal_v1','authority_source':'old-root-current-native-config','source_config_path':'/root/.hermes/config.yaml','source_config_sha256':source_config_sha256,'captured_at_unix':captured_at_unix,'tts':sanitized(native_config.get('tts') or {}),'stt':sanitized(native_config.get('stt') or {}),'auxiliary_tts_audio_tags':sanitized(aux),'auxiliary_audio_review':sanitized(audio_review)}

def validate_current_modal_snapshot(snapshot:dict,*,now:float)->dict|None:
    if 'current_modal' not in snapshot:return None
    value=snapshot['current_modal']
    allowed={'schema','authority_source','source_config_path','source_config_sha256','captured_at_unix','tts','stt','auxiliary_tts_audio_tags'}
    if not isinstance(value,dict) or not allowed<=set(value) or set(value)-allowed-{'auxiliary_audio_review'}:raise ValueError('normal_current_modal_snapshot_fields_invalid')
    if (value['schema']!='hermes_current_modal_v1' or value['authority_source']!='old-root-current-native-config'
        or value['source_config_path']!='/root/.hermes/config.yaml' or value['source_config_sha256']!=snapshot.get('config_sha256')
        or value['captured_at_unix']!=snapshot.get('captured_at_unix') or type(value['captured_at_unix']) not in (int,float)
        or not 0<=now-value['captured_at_unix']<=120):raise ValueError('normal_current_modal_snapshot_source_invalid')
    if any(not isinstance(value[k],dict) for k in ('tts','stt','auxiliary_tts_audio_tags')):raise ValueError('normal_current_modal_snapshot_configs_invalid')
    def secrets(v):
        if isinstance(v,dict):return any(any(word in k.casefold() for word in ('api_key','apikey','token','secret','password','credential','authorization')) or secrets(x) for k,x in v.items())
        if isinstance(v,list):return any(secrets(x) for x in v)
        return False
    if 'auxiliary_audio_review' in value and not isinstance(value['auxiliary_audio_review'],dict):raise ValueError('normal_current_audio_review_config_invalid')
    if secrets(value):raise ValueError('normal_current_modal_credentials_forbidden')
    return value

def build_current_modal_resolver(runtime_receipt:dict,*,native_role_verifier:Callable[[dict],None],first_use_max_age_seconds:float=120)->Callable[[],dict]:
 """runtime_receipt is the normal producer's verified receipt, never packet data.
 native_role_verifier is the existing actual SDK role verifier supplied by trusted caller.
 """
 if not callable(native_role_verifier):raise ValueError('normal_native_role_verifier_required')
 native_role_verifier(runtime_receipt)
 home=Path(str(runtime_receipt.get('home') or ''));pin=runtime_receipt.get('current_modal_pin');job_id=runtime_receipt.get('job_id') or runtime_receipt.get('task_id') or runtime_receipt.get('profile_id')
 if not home.is_absolute() or not isinstance(pin,dict) or not job_id:raise ValueError('normal_current_modal_authority_missing')
 path=Path(str(pin.get('path') or ''))
 if path!=home/'current-modal-capability.private.json':raise ValueError('normal_current_modal_scope_mismatch')
 source_config_sha=runtime_receipt.get('current_modal_source_config_sha256')
 expected_sha=pin.get('sha256')
 if not isinstance(source_config_sha,str) or len(source_config_sha)!=64 or not isinstance(expected_sha,str) or len(expected_sha)!=64:raise ValueError('normal_current_modal_source_pin_missing')
 first=[True]
 def resolve():
  # The same normal role lifecycle remains authoritative; no canonical fallback.
  native_role_verifier(runtime_receipt)
  obj=json.loads(_private_read(path,expected_sha).decode('utf8'))
  if (obj.get('schema')!='hermes_current_modal_v1' or obj.get('authority_source')!='old-root-current-native-config' or obj.get('source_config_path')!='/root/.hermes/config.yaml' or obj.get('source_config_sha256')!=source_config_sha or obj.get('job_id')!=job_id):raise ValueError('normal_current_modal_authority_binding_failed')
  captured=obj.get('captured_at_unix')
  if type(captured) not in (int,float) or not math.isfinite(captured):raise ValueError('normal_current_modal_capture_invalid')
  if first[0] and not 0<=time.time()-captured<=first_use_max_age_seconds:raise ValueError('normal_current_modal_stale_before_first_use')
  first[0]=False
  tts=obj.get('tts');stt=obj.get('stt');aux=obj.get('auxiliary_tts_audio_tags')
  if not isinstance(tts,dict) or not isinstance(stt,dict) or not isinstance(aux,dict) or not str(tts.get('provider') or '').strip():raise ValueError('normal_current_modal_config_missing')
  return {'config_sha256':obj['source_config_sha256'],'tts':tts,'stt':stt,'auxiliary_tts_audio_tags':aux,'current_modal_sha256':expected_sha,'normal_profile_job_id':job_id,'auxiliary_audio_review':obj.get('auxiliary_audio_review') or {}}
 resolve();return resolve

def normal_voice_provider_options(runtime_receipt:dict,*,native_role_verifier:Callable[[dict],None],voice_plan:list[dict],alignment_runner:Callable)->dict:
 if not callable(alignment_runner):raise ValueError('normal_actual_alignment_runner_required')
 resolver=build_current_modal_resolver(runtime_receipt,native_role_verifier=native_role_verifier)
 return {'current_modal_resolver':resolver,'alignment_runner':alignment_runner,'voice_plan':voice_plan}


def bind_current_modal_to_receipt(receipt:dict,snapshot:dict,*,write_new:Callable)->dict:
    """Normal trusted materializer call after existing task/runtime authentication.
    Uses original O_EXCL/private writer and the original binding CAS, no new grant.
    """
    if not callable(write_new):raise ValueError('normal_private_writer_required')
    current=snapshot.get('current_modal');job=snapshot.get('task_id');profile=snapshot.get('profile_id')
    if (not isinstance(current,dict) or not job or job!=profile or current.get('schema')!='hermes_current_modal_v1'
        or current.get('source_config_sha256')!=snapshot.get('config_sha256')):
        raise ValueError('normal_current_modal_snapshot_binding_failed')
    home=Path(str(receipt.get('home') or ''));binding_path=home/'old-runtime-authority.private.json'
    old=_private_read(binding_path,receipt['authority_receipt_sha256']);binding=json.loads(old)
    doc=dict(current,job_id=job);target=home/'current-modal-capability.private.json';raw=_canonical(doc)+b'\n'
    write_new(target,raw)
    if target.is_symlink() or _sha(target.read_bytes())!=_sha(raw):raise ValueError('normal_current_modal_writeback_mismatch')
    pin={'path':str(target),'sha256':_sha(raw)};fields={'current_modal_pin':pin,'current_modal_source_config_sha256':current['source_config_sha256']}
    binding.update(fields);new=_canonical(binding)+b'\n';temporary=home/'binding.current-modal.private.tmp'
    write_new(temporary,new);_private_read(binding_path,receipt['authority_receipt_sha256']);os.replace(temporary,binding_path)
    return {**receipt,**fields,'authority_receipt_sha256':_sha(new)}
