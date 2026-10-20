"""Checks actual audio and final-track alignment; plans are never review evidence."""
from __future__ import annotations
import hashlib,json,math,re,subprocess
from pathlib import Path
from typing import Any,Callable

AUDIO_REVIEW_CHECKS=('voice_present','script_complete','pronunciation_correct','natural_timbre','pace_and_pauses_appropriate','no_noise_or_clipping','head_tail_complete','subtitles_synchronized','bgm_does_not_mask_voice')

def _sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _file(value:Any,label:str)->Path:
    path=Path(str(value or ''))
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size==0:
        raise ValueError(label+'_file_missing')
    return path

def _normalize(text:Any)->str:
    return ''.join(c.casefold() for c in str(text or '') if c.isalnum())

def _number(value:Any,label:str)->float:
    if isinstance(value,bool):raise ValueError(label+'_invalid')
    try:n=float(value)
    except (ValueError,TypeError):raise ValueError(label+'_invalid')
    if not math.isfinite(n):raise ValueError(label+'_invalid')
    return n

def _time(value:float)->str:
    ms=round(value*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

def align_final_narration(audio:Path,display_texts:list[str],tts_texts:list[str],duration:float,
                          runner:Callable,report_path:Path)->dict:
    """Runner is injected by the current Hermes audio capability, never a fixed model."""
    audio=_file(audio,'narration');before=_sha(audio)
    if not callable(runner):raise RuntimeError('voice_final_alignment_capability_missing')
    report=runner(audio_path=str(audio),audio_sha256=before,display_texts=list(display_texts),
                  tts_texts=list(tts_texts),duration_seconds=duration)
    if not isinstance(report,dict):raise RuntimeError('voice_final_alignment_report_invalid')
    if _sha(audio)!=before:raise RuntimeError('voice_final_alignment_audio_changed')
    if report.get('method') not in {'asr','forced_alignment'} or not str(report.get('engine') or '').strip():
        raise RuntimeError('voice_actual_alignment_required')
    if report.get('passed') is not True or report.get('audio_sha256')!=before or report.get('audio_path')!=str(audio):
        raise RuntimeError('voice_final_alignment_audio_binding_failed')
    if abs(_number(report.get('duration_seconds'),'alignment_duration')-duration)>0.05:
        raise RuntimeError('voice_final_alignment_duration_mismatch')
    rows=report.get('segments')
    if not isinstance(rows,list) or len(rows)!=len(display_texts) or len(tts_texts)!=len(display_texts):
        raise RuntimeError('voice_final_alignment_segment_count_mismatch')
    if len(rows)==0:raise RuntimeError('voice_final_alignment_empty')
    lines=[];previous=0.;ends=[];last_word_end=0.
    for i,(row,display,spoken) in enumerate(zip(rows,display_texts,tts_texts)):
        if not isinstance(row,dict) or row.get('index')!=i:
            raise RuntimeError('voice_final_alignment_segment_index_invalid')
        if row.get('display_text')!=display or _normalize(row.get('recognized_text'))!=_normalize(spoken):
            raise RuntimeError('voice_final_alignment_text_mismatch')
        start=_number(row.get('start'),'segment_start');end=_number(row.get('end'),'segment_end')
        if not previous<=start<end<=duration+0.02:raise RuntimeError('voice_final_alignment_time_invalid')
        words=row.get('words')
        if not isinstance(words,list) or not words:raise RuntimeError('voice_actual_word_alignment_required')
        word_prev=start
        for word in words:
            if not isinstance(word,dict):raise RuntimeError('voice_final_alignment_word_invalid')
            a=_number(word.get('start'),'word_start');b=_number(word.get('end'),'word_end')
            if not word_prev<=a<b<=end+0.02:raise RuntimeError('voice_final_alignment_word_time_invalid')
            word_prev=b
        if _normalize(''.join(str(w.get('word') or '') for w in words))!=_normalize(spoken):
            raise RuntimeError('voice_final_alignment_word_text_mismatch')
        cues=row.get('subtitle_cues')
        if not isinstance(cues,list) or not cues:
            raise RuntimeError('voice_actual_subtitle_alignment_required')
        cue_previous=start;display_parts=[]
        for cue in cues:
            ca=_number(cue.get('start'),'cue_start');cb=_number(cue.get('end'),'cue_end')
            caption=str(cue.get('text') or '')
            if not cue_previous<=ca<cb<=end+0.02 or not caption.strip():
                raise RuntimeError('voice_actual_subtitle_clock_invalid')
            caption_lines=caption.splitlines()
            if len(caption_lines)>2 or any(len(line)>18 for line in caption_lines):
                raise RuntimeError('voice_subtitle_readability_limit_exceeded')
            lines.append(f'{len(lines)+1}\n{_time(ca)} --> {_time(cb)}\n{caption}\n')
            cue_previous=cb;display_parts.append(caption.replace('\n',''))
        if ''.join(display_parts)!=display.replace('\n',''):
            raise RuntimeError('voice_actual_subtitle_display_text_mismatch')
        previous=end;ends.append(end);last_word_end=word_prev
    # Full final track is the source of segment durations, including actual gaps/tail.
    boundaries=[0.]+[(ends[i]+float(rows[i+1]['start']))/2 for i in range(len(rows)-1)]+[duration]
    measured=[boundaries[i+1]-boundaries[i] for i in range(len(rows))]
    if any(n<=0 for n in measured):raise RuntimeError('voice_final_alignment_segment_duration_invalid')
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'srt':'\n'.join(lines),'segment_durations':measured,'report_path':str(report_path),
            'report_sha256':_sha(report_path),'last_word_end':last_word_end}

def _load_report(ref:Any,label:str,bindings:dict[str,Any])->dict:
    if not isinstance(ref,dict):raise ValueError(label+'_reference_missing')
    path=_file(ref.get('path'),label)
    if ref.get('sha256')!=_sha(path):raise ValueError(label+'_report_sha_mismatch')
    report=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(report,dict) or report.get('passed') is not True:raise ValueError(label+'_not_passed')
    for key,value in bindings.items():
        if value in ('',None):raise ValueError('audio_expected_'+key+'_missing')
        if report.get(key)!=value:raise ValueError(label+'_'+key+'_mismatch')
    return report

def _subtitle_cues(path:Path)->list[dict]:
    raw=path.read_text(encoding="utf-8-sig").replace("\r\n","\n")
    cues=[]
    def sec(value:str)->float:
        h,m,rest=value.split(":");return int(h)*3600+int(m)*60+float(rest.replace(",","."))
    for block in re.split(r"\n\s*\n",raw.strip()):
        lines=block.splitlines()
        if len(lines)<3 or not lines[0].isdigit():raise ValueError("audio_subtitle_cue_invalid")
        match=re.fullmatch(r"(\d{2}:\d{2}:\d{2}[,.]\d{3}) --> (\d{2}:\d{2}:\d{2}[,.]\d{3})",lines[1])
        if not match:raise ValueError("audio_subtitle_time_invalid")
        cues.append({"start":sec(match[1]),"end":sec(match[2]),"text":"\n".join(lines[2:])})
    if not cues:raise ValueError("audio_subtitle_empty")
    return cues

def _validate_final_transcript(asr:dict,alignment:dict,subtitle:Path,expected:list,duration:float)->None:
    if not isinstance(expected,list) or not expected or any(not isinstance(t,str) or not t.strip() for t in expected):
        raise ValueError("audio_expected_script_missing")
    rows=asr.get("segments");aligned=alignment.get("segments")
    if not isinstance(rows,list) or not isinstance(aligned,list) or len(rows)!=len(expected) or len(aligned)!=len(expected):
        raise ValueError("final_audio_transcript_segment_count_mismatch")
    cues=_subtitle_cues(subtitle)
    proposed=[cue for row in aligned for cue in (row.get("subtitle_cues") or [])]
    if len(cues)!=len(proposed) or not proposed:raise ValueError("final_audio_subtitle_cue_count_mismatch")
    for cue,actual in zip(proposed,cues):
        if abs(actual["start"]-_number(cue.get("start"),"cue_start"))>0.02 or abs(actual["end"]-_number(cue.get("end"),"cue_end"))>0.02:
            raise ValueError("audio_subtitle_actual_clock_mismatch")
        if actual["text"]!=cue.get("text"):raise ValueError("audio_subtitle_actual_text_mismatch")
    previous=0.
    for i,(spoken,row,aligned_row) in enumerate(zip(expected,rows,aligned)):
        if _normalize(row.get("recognized_text"))!=_normalize(spoken):raise ValueError("final_asr_actual_text_mismatch")
        if _normalize(aligned_row.get("recognized_text"))!=_normalize(spoken):raise ValueError("final_alignment_actual_text_mismatch")
        a=_number(aligned_row.get("start"),"aligned_start");b=_number(aligned_row.get("end"),"aligned_end")
        if not previous<=a<b<=duration+0.02:raise ValueError("final_alignment_actual_clock_invalid")
        row_cues=aligned_row.get("subtitle_cues") or []
        if not row_cues or "".join(str(c.get("text") or "").replace("\n","") for c in row_cues)!=str(aligned_row.get("display_text") or "").replace("\n",""):
            raise ValueError("audio_subtitle_actual_display_text_mismatch")
        cue_previous=a
        for cue in row_cues:
            x=_number(cue.get("start"),"aligned_cue_start");y=_number(cue.get("end"),"aligned_cue_end")
            if not cue_previous<=x<y<=b+0.02:raise ValueError("audio_subtitle_actual_clock_invalid")
            text_lines=str(cue.get("text") or "").splitlines()
            if len(text_lines)>2 or any(len(line)>18 for line in text_lines):raise ValueError("audio_subtitle_readability_limit_exceeded")
            cue_previous=y
        words=aligned_row.get("words")
        if not isinstance(words,list) or not words:raise ValueError("final_audio_word_alignment_missing")
        if _normalize("".join(str(w.get("word") or "") for w in words))!=_normalize(spoken):raise ValueError("final_audio_word_transcript_mismatch")
        word_previous=a
        for word in words:
            x=_number(word.get("start"),"aligned_word_start");y=_number(word.get("end"),"aligned_word_end")
            if not word_previous<=x<y<=b+0.02:raise ValueError("final_audio_word_clock_invalid")
            word_previous=y
        previous=b

def _checked_pin(pin:Any,label:str)->dict:
    if not isinstance(pin,dict):raise ValueError(label+'_pin_missing')
    path=_file(pin.get('path'),label)
    if pin.get('sha256')!=_sha(path):raise ValueError(label+'_pin_sha_mismatch')
    return {'path':str(path),'sha256':pin['sha256']}

def _prepared_context(expected:dict)->dict:
    return {key:value for key,value in expected.items() if key not in {'skill_executions','check_executions'}}

def _canonical(value:Any)->str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _source_script_tts_texts(script_pins:list[dict])->list[str]:
    """Actual renderer Markdown and compiled JSON; metadata never supplies text."""
    source_texts=None;compiled=None
    for pin in script_pins:
        path=Path(pin['path']);raw=path.read_text(encoding='utf-8-sig')
        if path.suffix.casefold() in {'.md','.txt'}:
            # This is the actual normal renderer's blank-line segmentation.
            import re
            strings=[row.strip() for row in re.split(r'\n\s*\n',raw) if row.strip()]
            if not strings:raise ValueError('audio_actual_script_empty')
            if source_texts is not None and source_texts!=strings:raise ValueError('audio_source_scripts_conflict')
            source_texts=strings;continue
        try:obj=json.loads(raw)
        except (ValueError,UnicodeError):raise ValueError('audio_source_script_schema_unknown')
        if not isinstance(obj,dict):raise ValueError('audio_source_script_schema_unknown')
        # Preflight is pinned metadata, never the narrator text source.
        if path.name=='video_preflight.json':continue
        strings=obj.get('segments')
        if isinstance(strings,list) and strings and all(isinstance(t,str) and t.strip() for t in strings):
            if source_texts is not None and source_texts!=strings:raise ValueError('audio_source_scripts_conflict')
            source_texts=list(strings)
        rows=obj.get('tts_segments') or obj.get('records')
        if rows is None and obj.get('version')=='tts_config_current_hermes_v2':rows=obj.get('segments')
        if isinstance(rows,list) and rows and all(isinstance(r,dict) and isinstance(r.get('tts_text'),str) and r['tts_text'].strip() for r in rows):
            pair=[(r.get('display_text') or r.get('source_text'),r['tts_text']) for r in rows]
            if any(not isinstance(display,str) or not display.strip() for display,_ in pair):raise ValueError('audio_compiled_source_display_text_missing')
            if compiled is not None and compiled!=pair:raise ValueError('audio_compiled_source_scripts_conflict')
            compiled=pair
        elif not (isinstance(strings,list) and strings and all(isinstance(t,str) and t.strip() for t in strings)):
            raise ValueError('audio_source_script_schema_unknown')
    if compiled is not None:
        if source_texts is not None and source_texts!=[p[0] for p in compiled]:raise ValueError('audio_compiled_source_script_mismatch')
        return [p[1] for p in compiled]
    if source_texts is not None:return source_texts
    raise ValueError('audio_source_script_schema_unknown')

def adapt_mandatory_audio_context(expected:dict,*,actual_tts_texts:list[str]|None=None)->dict:
    """Pure trusted-caller adaptation. Never reads packet/context/report claims."""
    if not isinstance(expected,dict) or expected.get('version')!='fix_quality_context_20261013' or expected.get('phase')!='release':
        raise ValueError('audio_mandatory_caller_context_missing')
    if actual_tts_texts is not None and (not isinstance(actual_tts_texts,list) or not actual_tts_texts or any(not isinstance(t,str) or not t.strip() for t in actual_tts_texts)):
        raise ValueError('audio_actual_source_script_texts_invalid')
    parts=expected.get('parts')
    if not isinstance(parts,dict):raise ValueError('audio_actual_parts_missing')
    def single(role):
        pins=parts.get(role)
        if not isinstance(pins,list) or len(pins)!=1:raise ValueError('audio_actual_'+role+'_ambiguous_or_missing')
        return _checked_pin(pins[0],'actual_'+role)
    target=single('video') if parts.get('video') else single('narration')
    narration=single('narration');subtitle=single('subtitles')
    scripts=parts.get('source_script')
    if not isinstance(scripts,list) or not scripts:raise ValueError('audio_actual_source_script_missing')
    script_pins=[_checked_pin(pin,'actual_source_script') for pin in scripts]
    derived_tts=_source_script_tts_texts(script_pins)
    if actual_tts_texts is not None and derived_tts!=actual_tts_texts:raise ValueError('audio_caller_script_does_not_match_actual_source_parts')
    # Root supplies tts_texts from the normal renderer/compiler source, tied to these actual source pins.
    # They may not come from the audio report or a model-chosen packet.
    rulebook=_checked_pin(expected.get('rulebook'),'actual_rulebook')
    skills=expected.get('skills')
    if not isinstance(skills,dict) or not skills:raise ValueError('audio_actual_skills_missing')
    skill_hashes={name:_checked_pin(pin,'actual_skill_'+name)['sha256'] for name,pin in skills.items()}
    for key in ('job_id','platform','revision_id'):
        if not isinstance(expected.get(key),str) or not expected[key].strip():raise ValueError('audio_actual_'+key+'_missing')
    return {'job_id':expected['job_id'],'platform':expected['platform'],'content_revision':expected['revision_id'],
            'rulebook_sha256':rulebook['sha256'],'skills_sha256':skill_hashes,'target_artifact':target['path'],
            'candidate_sha256':target['sha256'],'narration_path':narration['path'],'narration_sha256':narration['sha256'],
            'subtitle_path':subtitle['path'],'subtitle_sha256':subtitle['sha256'],'tts_texts':derived_tts,
            'source_script_pins':script_pins,'mandatory_context_sha256':_canonical(_prepared_context(expected))}

def _verify_native_listening_context(expected:dict)->None:
    if not isinstance(expected,dict) or expected.get('version')!='fix_quality_context_20261013':
        raise ValueError('audio_trusted_native_listening_context_missing')
    try:
        from .mandatory_quality_context import verify_native_quality_execution
    except ImportError as exc:
        raise ValueError('audio_native_listening_verifier_unavailable') from exc
    prepared=_prepared_context(expected)
    mandatory={'voice_intelligibility','voice_naturalness','voice_controls_and_pronunciation'}
    applicable=set((prepared.get('required_checks') or {}).get('watch') or [])
    if not mandatory<=applicable:raise ValueError('audio_native_listening_required_checks_missing')
    selected=mandatory | ({'complete_playback','audio_subtitle_sync','bgm_mix_audibility'} & applicable)
    execution_pins=((expected.get('check_executions') or {}).get('watch') or {})
    for check_name in sorted(selected):
        pin=execution_pins.get(check_name)
        if not isinstance(pin,dict):raise ValueError('audio_native_listening_execution_missing:'+check_name)
        names=(prepared.get('check_parts') or {}).get(check_name)
        if not isinstance(names,list) or not names:raise ValueError('audio_native_listening_scope_missing:'+check_name)
        subset={name:prepared['parts'][name] for name in names}
        verify_native_quality_execution(pin,'audio_'+check_name,prepared,subset,channel='watch',check_name=check_name)

def validate_final_audio_evidence(packet:dict,*,expected_context:dict|None=None,actual_tts_texts:list[str]|None=None)->dict:
    """Hard gate for final rendered audio. Root passes independently compiled context."""
    failures=[];details={}
    try:
        if not isinstance(expected_context,dict):raise ValueError('audio_expected_context_missing')
        context=adapt_mandatory_audio_context(expected_context,actual_tts_texts=actual_tts_texts)
        for key in ('job_id','content_revision','platform','rulebook_sha256','skills_sha256','tts_texts'):
            if key not in context or context[key] in ('',None,{},[]):raise ValueError('audio_expected_'+key+'_missing')
        evidence=packet.get('audio_quality_evidence')
        if not isinstance(evidence,dict):raise ValueError('audio_quality_evidence_missing')
        target=_file(evidence.get('target_artifact'),'target_artifact')
        narration=_file(evidence.get('narration_path'),'narration')
        subtitle=_file(evidence.get('subtitle_path'),'subtitle')
        hashes={'candidate_sha256':_sha(target),'narration_sha256':_sha(narration),'subtitle_sha256':_sha(subtitle)}
        for key,value in hashes.items():
            if evidence.get(key)!=value:raise ValueError('audio_'+key+'_mismatch')
        if context.get('candidate_sha256')!=hashes['candidate_sha256']:
            raise ValueError('audio_expected_candidate_sha256_mismatch')
        if str(context.get('target_artifact') or '')!=str(target):raise ValueError('audio_expected_target_artifact_mismatch')
        if context['narration_path']!=str(narration) or context['narration_sha256']!=hashes['narration_sha256']:raise ValueError('audio_expected_narration_binding_mismatch')
        if context['subtitle_path']!=str(subtitle) or context['subtitle_sha256']!=hashes['subtitle_sha256']:raise ValueError('audio_expected_subtitle_binding_mismatch')
        if any(evidence.get(k) for k in ('fallback_used','degraded','controls_dropped')):
            raise ValueError('audio_degraded_not_deliverable')
        duration=_number(evidence.get('duration_seconds'),'audio_duration')
        if duration<=0:raise ValueError('audio_duration_invalid')
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type:format=duration','-of','json',str(target)],capture_output=True,text=True,timeout=20)
        if probe.returncode!=0:raise ValueError('audio_target_probe_failed')
        payload=json.loads(probe.stdout)
        if not any(s.get('codec_type')=='audio' for s in payload.get('streams',[])):
            raise ValueError('audio_voice_stream_missing')
        if abs(_number(payload.get('format',{}).get('duration'),'probe_duration')-duration)>0.15:
            raise ValueError('audio_target_duration_mismatch')
        bindings={**context,**hashes,'target_artifact':str(target),'narration_path':str(narration),'subtitle_path':str(subtitle)}
        asr=_load_report(evidence.get('final_asr'),'final_asr',bindings)
        if asr.get('method')!='asr' or not str(asr.get('engine') or '').strip():raise ValueError('final_asr_actual_method_missing')
        if asr.get('checks',{}).get('script_complete') is not True or not asr.get('segments'):
            raise ValueError('final_asr_script_coverage_missing')
        alignment=_load_report(evidence.get('subtitle_alignment'),'subtitle_alignment',bindings)
        if alignment.get('method') not in {'asr','forced_alignment'}:raise ValueError('subtitle_alignment_actual_method_missing')
        if alignment.get('checks',{}).get('subtitles_synchronized') is not True or not alignment.get('segments'):
            raise ValueError('subtitle_alignment_evidence_missing')
        _validate_final_transcript(asr,alignment,subtitle,context.get('tts_texts'),duration)
        _verify_native_listening_context(expected_context)
        details={'audio_stream_present':True,'final_asr_verified':True,'final_alignment_verified':True,'actual_listening_review_verified':True,**hashes}
    except (ValueError,TypeError,KeyError,OSError,AttributeError,json.JSONDecodeError,subprocess.SubprocessError) as exc:
        failures.append(str(exc))
    return {'passed':not failures,'failures':failures,**details}
