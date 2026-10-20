"""Current native narration and captions from real provider word events."""
from __future__ import annotations
import asyncio,hashlib,json,re,subprocess,unicodedata,uuid
from pathlib import Path

def _sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _normalized(text):
    return ''.join(c.casefold() for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))

def source_plan(segments, path, expected_sha):
    p=Path(path)
    if not p.is_absolute() or p.is_symlink() or any(parent.is_symlink() for parent in p.parents) or not p.is_file() or _sha(p)!=expected_sha:
        raise ValueError('normal_voice_plan_source_changed')
    value=json.loads(p.read_text(encoding='utf8'))
    rows=value.get('voice_plan')
    from .voice_plan import build_voice_plan
    return build_voice_plan(segments,segment_styles=rows)

def synthesize_normal_film_audio(segments,out,plan_path,plan_sha):
    from .normal_modal_runtime import current_normal_modal_resolver
    from .current_audio_network import normal_proxy_options
    from .prosody_runtime import synthesize_edge_plan,duration
    if len(segments)!=8 or any(not s.strip() for s in segments):
        raise ValueError('normal_film_complete_narration_required')
    plan=source_plan(segments,plan_path,plan_sha)
    resolver=current_normal_modal_resolver()
    capability=resolver()
    location=Path(out)/('current-narration-'+uuid.uuid4().hex)
    actual=asyncio.run(synthesize_edge_plan(segments,plan,str(location),resolver,**normal_proxy_options()))
    if len(actual.get('records') or []) != 8 or any(not row.get('provider_word_boundaries') for row in actual['records']):
        raise ValueError('normal_film_complete_actual_word_audio_required')
    if actual['capability']['hermes_config_sha256']!=capability['config_sha256']:
        raise ValueError('normal_film_modal_source_changed')
    files=[];records=[]
    for i,(record,row) in enumerate(zip(actual['records'],plan)):
        source=Path(record['decoded_audio_path'])
        if _sha(source)!=record['decoded_audio_sha256'] or record['text']!=segments[i]:
            raise ValueError('normal_film_actual_narration_changed')
        padded=location/f'film-segment-{i+1:02d}.wav'
        result=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),
            '-af',f"apad=pad_dur={row['pause_after_ms']/1000:.3f}",'-ar','24000','-ac','1',
            '-c:a','pcm_s16le',str(padded)],capture_output=True,text=True,timeout=20)
        if result.returncode: raise ValueError('normal_film_declared_pause_failed')
        measured=duration(padded)
        if abs(measured-record['decoded_duration_seconds']-row['pause_after_ms']/1000)>0.03:
            raise ValueError('normal_film_declared_pause_mismatch')
        files.append(str(padded))
        records.append({**record,'tts_text':segments[i],'display_text':segments[i],
            'rate':row['rate'],'pitch':row['pitch'],'pause_after_ms':row['pause_after_ms'],
            'duration_seconds':measured,'audio_sha256':_sha(padded),'audio_path':str(padded),
            'provider_word_boundaries':record['provider_word_boundaries'],
            'applied_rules':[],'unhandled_latin_tokens':[],
            'voice_plan_source':{'path':str(Path(plan_path)),'sha256':plan_sha}})
    return {'files':files,'records':records,'provider':capability['tts']['provider'],
        'source_config_sha256':capability['config_sha256'],'execution_manifest':str(location/'PROSODY-EXECUTION.json'),
        'durations':[r['duration_seconds'] for r in records]}

def timed_caption_cues(text,words,*,start=0.0,max_chars_per_line=15,max_lines=2):
    if not isinstance(words,list) or not words: raise ValueError('actual_caption_word_events_required')
    normalized=_normalized(text)
    tokens=[_normalized(str(w.get('word') or '')) for w in words]
    if any(not t for t in tokens) or ''.join(tokens)!=normalized:
        raise ValueError('actual_caption_word_text_mismatch')
    positions=[i for i,c in enumerate(text) if _normalized(c)]
    spans=[];offset=0;last_end=-1.0
    for row,token in zip(words,tokens):
        st=float(row['start']);en=float(row['end'])
        if not 0<=st<en or st<last_end-0.02: raise ValueError('actual_caption_word_time_invalid')
        begin=0 if offset==0 else positions[offset]
        offset+=len(token);end=len(text) if offset==len(positions) else positions[offset]
        spans.append({'text':text[begin:end],'start':st,'end':en});last_end=en
    groups=[];current=[];count=0;limit=max_chars_per_line*max_lines
    for span in spans:
        if len(span['text'])>limit:raise ValueError('caption_single_word_exceeds_mobile_limit')
        if current and count+len(span['text'])>limit:
            groups.append(current);current=[];count=0
        current.append(span);count+=len(span['text'])
    if current:groups.append(current)
    cues=[]
    for group in groups:
        copy=''.join(row['text'] for row in group)
        lines=[copy[i:i+max_chars_per_line] for i in range(0,len(copy),max_chars_per_line)]
        cues.append({'start':round(start+group[0]['start'],3),'end':round(start+group[-1]['end'],3),
            'lines':lines,'timing_source':'actual_provider_word_events'})
    if ''.join(line for cue in cues for line in cue['lines'])!=text:
        raise ValueError('actual_caption_text_incomplete')
    return cues
