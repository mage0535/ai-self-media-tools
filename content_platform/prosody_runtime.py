"""Actual current-Hermes Edge prosody execution. Unsupported instructions stop early."""
from __future__ import annotations
import asyncio,hashlib,json,subprocess,uuid
from pathlib import Path
from typing import Callable
try:
 from .voice_plan import build_voice_plan
except ImportError:
 from voice_plan import build_voice_plan

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def duration(p:Path)->float:
 r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(p)],capture_output=True,text=True,timeout=15)
 if r.returncode!=0:raise RuntimeError('prosody_actual_audio_probe_failed')
 value=float(r.stdout.strip())
 if value<=0:raise RuntimeError('prosody_actual_audio_empty')
 return value

def capability(cfg:dict)->dict:
 tts=cfg.get('tts') or {};edge=tts.get('edge') or {};aux=cfg.get('auxiliary_tts_audio_tags') or {}
 if tts.get('provider')!='edge':raise RuntimeError('current_tts_provider_adapter_unsupported')
 voice=edge.get('voice')
 if not isinstance(voice,str) or not voice.strip() or not cfg.get('config_sha256'):raise RuntimeError('current_tts_voice_or_config_missing')
 return {'provider':'edge','voice':voice,'hermes_config_sha256':cfg['config_sha256'],
         'auxiliary_tts_audio_tags':aux,'supported_controls':['rate','pitch','pause_after_ms'],
         'freeform_instructions_supported':False}

async def synthesize_edge_plan(segments:list[str],plan:list[dict],output_dir:str,
                               current_capability_resolver:Callable[[],dict],*,proxy:str|None=None,connector_factory:Callable|None=None)->dict:
 import edge_tts,importlib.metadata
 rows=build_voice_plan(segments,segment_styles=plan)
 if any(row.get('instructions') or row.get('ssml') or row.get('emotion_prompt') for row in rows):
  raise RuntimeError('edge_freeform_instructions_unsupported')
 if proxy and connector_factory:raise RuntimeError('edge_proxy_and_connector_mutually_exclusive')
 initial=capability(current_capability_resolver());out=Path(output_dir)
 if not out.is_absolute() or out.is_symlink():raise RuntimeError('prosody_output_directory_invalid')
 out.mkdir(mode=0o700,parents=True,exist_ok=False)
 records=[]
 for index,row in enumerate(rows):
  current=capability(current_capability_resolver())
  if current!=initial:raise RuntimeError('current_tts_capability_changed_mid_task')
  target=out/f'segment-{index+1:02d}.mp3';words=[];chunks=[]
  connector=connector_factory() if connector_factory else None
  communicate=edge_tts.Communicate(row['text'],initial['voice'],rate=row['rate'],pitch=row['pitch'],
             boundary='WordBoundary',proxy=proxy,connector=connector,connect_timeout=15,receive_timeout=45)
  try:
   async for chunk in communicate.stream():
    if chunk['type']=='audio':chunks.append(chunk['data'])
    elif chunk['type']=='WordBoundary':words.append({'word':chunk['text'],'start':chunk['offset']/1e7,
                      'end':(chunk['offset']+chunk['duration'])/1e7})
  except Exception:
   target.with_suffix('.failed.mp3').write_bytes(b''.join(chunks))
   raise
  finally:
   if connector is not None:await connector.close()
  if not chunks:raise RuntimeError('edge_actual_audio_missing')
  target.write_bytes(b''.join(chunks));target.chmod(0o600);seconds=duration(target)
  if not words:raise RuntimeError('edge_actual_word_boundaries_missing')
  wave=out/f'segment-{index+1:02d}.wav'
  decode=subprocess.run(['ffmpeg','-v','error','-y','-i',str(target),'-ar','24000','-ac','1','-c:a','pcm_s16le',str(wave)],capture_output=True,text=True,timeout=20)
  if decode.returncode!=0:raise RuntimeError('edge_actual_audio_decode_failed')
  wave.chmod(0o600)
  record={'index':index,'text':row['text'],'source_text_sha256':hashlib.sha256(row['text'].encode()).hexdigest(),
          'style':row['style'],'semantic_direction':row['semantic_direction'],
          'requested_controls':{k:row[k] for k in ('rate','pitch','pause_after_ms')},
          'performed_provider_controls':{'rate':row['rate'],'pitch':row['pitch']},
          'voice':initial['voice'],'provider':'edge','audio_path':str(target),'audio_sha256':sha(target),
          'duration_seconds':seconds,'decoded_audio_path':str(wave),'decoded_audio_sha256':sha(wave),
          'decoded_duration_seconds':duration(wave),'provider_word_boundaries':words,'word_boundary_method':'provider_events',
          'final_asr_verified':False,'subjective_listening_verified':False,'fallback_used':False}
  records.append(record);(out/'PROGRESS.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
 inputs=[];filters=[];concat=[]
 for i,(record,row) in enumerate(zip(records,rows)):
  inputs+=['-i',record['decoded_audio_path']]
  filters.append(f'[{i}:a]apad=pad_dur={row["pause_after_ms"]/1000:.3f}[s{i}]');concat.append(f'[s{i}]')
 filters.append(''.join(concat)+f'concat=n={len(records)}:v=0:a=1[out]')
 final=out/'narration-prosody.wav';run=subprocess.run(['ffmpeg','-v','error','-y']+inputs+['-filter_complex',';'.join(filters),'-map','[out]','-ar','24000','-ac','1','-c:a','pcm_s16le',str(final)],capture_output=True,text=True,timeout=30)
 if run.returncode!=0 or not final.is_file():raise RuntimeError('prosody_full_audio_concat_failed')
 final.chmod(0o600);measured=duration(final);expected=sum(r['decoded_duration_seconds']+r['requested_controls']['pause_after_ms']/1000 for r in records)
 if abs(measured-expected)>0.03:raise RuntimeError('prosody_actual_pause_or_duration_mismatch')
 manifest={'schema':'current_hermes_prosody_execution_v1','capability':initial,'edge_tts_version':importlib.metadata.version('edge-tts'),
           'records':records,'audio_path':str(final),'audio_sha256':sha(final),'duration_seconds':measured,
           'actual_pause_total_seconds':sum(r['requested_controls']['pause_after_ms']/1000 for r in records),
           'concat_filter':';'.join(filters),'decode_exit':run.returncode,'final_asr_verified':False,
           'subjective_listening_verified':False,'quality_state':'awaiting_final_audio_review','publication_authorized':False}
 (out/'PROSODY-EXECUTION.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
 return manifest
