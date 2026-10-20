"""Register complete actual renderer files before native mandatory review.
Registration is identity evidence only; it never issues a quality verdict.
"""
from __future__ import annotations
import hashlib,json,os,re,subprocess,uuid,wave
from pathlib import Path

def _sha(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def _file(path,root):
    p=Path(path)
    if not p.is_absolute() or p.is_symlink() or any(x.is_symlink() for x in p.parents):
        raise ValueError('native_render_part_symlink_or_relative_path')
    if not p.is_file() or not p.resolve(strict=True).is_relative_to(root):
        raise ValueError('native_render_part_missing_or_outside_job:'+p.name)
    if p.stat().st_size<=0:raise ValueError('native_render_part_empty:'+p.name)
    return p

def _json(path,root):return json.loads(_file(path,root).read_text(encoding='utf-8-sig'))
def _pin(path):return {'path':str(path),'sha256':_sha(path),'bytes':path.stat().st_size}

def bind_actual_video_parts(store,data_dir,job_id,platform,artifact):
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',str(job_id)) or not re.fullmatch('[a-z0-9_-]{1,40}',str(platform)):
        raise ValueError('native_render_original_owner_required')
    base=Path(data_dir)
    if not base.is_absolute() or base.is_symlink() or any(x.is_symlink() for x in base.parents):
        raise ValueError('native_render_data_root_untrusted')
    root=base/'artifacts'/str(job_id)
    if root.is_symlink() or not root.is_dir():raise ValueError('native_render_original_job_root_required')
    root=root.resolve(strict=True);video=_file(artifact.get('path') or '',root);video_sha=_sha(video)
    if video.suffix.casefold()!='.mp4' or artifact.get('kind')!='video' or artifact.get('checksum')!=video_sha:
        raise ValueError('native_render_original_video_sha_mismatch')
    registered=[r for r in store.artifacts(job_id) if r.get('kind')=='video' and r.get('path')==str(video)]
    if len(registered)!=1 or registered[0].get('checksum')!=video_sha or registered[0].get('job_id')!=job_id:
        raise ValueError('native_render_original_video_row_missing_or_changed')

    legacy=artifact.get('render_manifest')
    if isinstance(legacy,dict)and (legacy.get('audio_evidence')or{}).get('version')=='audio_release_evidence_v1':
        # Existing rendered material only. No legacy checker flag is imported as QA.
        def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        producers=[]
        for step in store.workflow_steps(job_id):
            output=step.get('output')or{}
            if (step.get('status')=='SUCCEEDED'and step.get('platform')in('',platform)
                    and output.get('kind')=='video'and output.get('checksum')==video_sha
                    and output.get('render_manifest')==legacy):
                if _sha(_file(output.get('path')or'',root))!=video_sha:raise ValueError('native_render_legacy_producer_video_changed')
                producers.append(step)
        if len(producers)!=1:raise ValueError('native_render_legacy_unique_actual_producer_required')
        actual_output=_file(legacy.get('output')or'',root)
        if _sha(actual_output)!=video_sha or legacy['audio_evidence'].get('candidate_sha256')!=video_sha:
            raise ValueError('native_render_legacy_candidate_changed')
        job=store.get_job(job_id);dm=job.get('draft_meta')or{};revision=dm.get('native_metadata_revision')or{}
        trusted_path=_file(legacy.get('trusted_run_manifest')or'',root);trusted=_json(trusted_path,root)
        if (revision.get('video_sha256')!=video_sha or revision.get('trusted_sha256')!=_sha(trusted_path)
                or trusted.get('artifact_set_sha256')!=legacy.get('artifact_set_sha256')
                or (trusted.get('artifact_sha256')or{}).get('video')!=video_sha):
            raise ValueError('native_render_legacy_saved_manifest_binding_changed')
        out=actual_output.parent;contract_path=_file(out/'render_contract.json',root);contract=_json(contract_path,root)
        source=base.parent/'scripts/film_renderer.py'
        if not re.fullmatch('[a-f0-9]{64}',str(contract.get('renderer_source_sha256')or'')):
            raise ValueError('native_render_legacy_original_renderer_source_identity_missing')
        # This is the historical declared renderer, not a claim about the current program or QA.
        script=_file(out/'script.md',root);script_raw=script.read_bytes()
        if (contract.get('script_sha256')!=_sha(script)or not isinstance(dm.get('narration_script'),str)
                or script_raw!=dm['narration_script'].encode()):
            raise ValueError('native_render_legacy_current_original_script_changed')
        audio_steps=[x for x in store.workflow_steps(job_id)if x.get('status')=='SUCCEEDED'
            and x.get('step_name')=='generate_audio'and (x.get('output')or{}).get('prepared_audio_manifest')]
        if len(audio_steps)!=1:raise ValueError('native_render_legacy_unique_audio_producer_required')
        audio_output=audio_steps[0]['output'];prepared_path=_file(audio_output['prepared_audio_manifest'],root)
        narration=_file(audio_output.get('path')or'',root)
        if audio_output.get('checksum')!=_sha(narration):raise ValueError('native_render_legacy_narration_changed')
        from .current_audio_review_runtime import read_prepared_audio_records
        view=read_prepared_audio_records(_pin(prepared_path))
        if ''.join(view['source_text'].split())!=''.join(dm['narration_script'].split()):
            raise ValueError('native_render_legacy_complete_script_records_mismatch')
        tts_path=_file(out/'tts_records.json',root);tts=_json(tts_path,root)
        cfg_path=_file(out/'tts_config.json',root);cfg=_json(cfg_path,root)
        if not isinstance(tts,list)or len(tts)!=len(view['records'])or cfg.get('segments')!=tts:
            raise ValueError('native_render_legacy_actual_tts_records_changed')
        for record,actual in zip(view['records'],tts):
            if (actual.get('display_text')!=record['source_text']or actual.get('tts_text')!=record['tts_text']
                    or actual.get('audio_sha256')!=record['audio_ref']['sha256']or actual.get('voice')!=record['voice']
                    or float(actual.get('rate','nan'))!=record['speed']or not isinstance(actual.get('pitch'),str)
                    or not isinstance(actual.get('applied_rules'),list)or not isinstance(actual.get('unhandled_latin_tokens'),list)):
                raise ValueError('native_render_legacy_tts_source_controls_changed')
        stems=legacy['audio_evidence'].get('stems')or[]
        if len(stems)!=2 or {x.get('role')for x in stems}!={'voiceover','background_music'}:
            raise ValueError('native_render_legacy_actual_audio_stems_required')
        stem_files={}
        for row in stems:
            path=_file(row.get('path')or'',root)
            if row.get('sha256')!=_sha(path):raise ValueError('native_render_legacy_actual_stem_changed')
            stem_files[row['role']]=path
        bgm=stem_files['background_music'];rights_path=_file(bgm.parent/'bgm_source.json',root);rights=_json(rights_path,root)
        if rights.get('sha256')!=_sha(bgm)or not rights.get('source_url')or not rights.get('license'):
            raise ValueError('native_render_legacy_actual_music_rights_missing')
        subtitle_path=_file(out/'subtitle_cue_manifest.json',root);subtitles=_json(subtitle_path,root)
        if not isinstance(subtitles,list)or len(subtitles)!=len(view['records']):raise ValueError('native_render_legacy_full_subtitles_missing')
        for index,(cue,record)in enumerate(zip(subtitles,view['records'])):
            if cue.get('segment')!=index+1 or cue.get('source')!=record['source_text']or not cue.get('cues'):
                raise ValueError('native_render_legacy_subtitle_source_changed')
        alignment_path=_file(out/'av_alignment_evidence.json',root)
        mix_path=_file(out/'audio_mix_evidence.json',root)
        # Window/fit reports do not establish original->aligned sample transforms.
        materials=[{'kind':'voice_segment','role':'voice_segment','file_ref':r['audio_ref'],
            'prepared_record_index':r['index'],'source_text_sha256':r['source_text_sha256'],
            'tts_text_sha256':r['tts_text_sha256']}for r in view['records']]
        materials += [
            {'kind':'narration','role':'narration','file_ref':_pin(narration),'prepared_ref':_pin(prepared_path)},
            {'kind':'aligned_narration','role':'narration','file_ref':_pin(stem_files['voiceover']),
                'alignment_ref':_pin(alignment_path),'original_transform_state':'unknown'},
            {'kind':'background_music','role':'bgm','file_ref':_pin(bgm),'rights_ref':_pin(rights_path)},
            {'kind':'final_mix','role':'video','file_ref':_pin(video),'mix_ref':_pin(mix_path)}]
        payload={'version':'native_actual_audio_materials_v1','job_id':job_id,'platform':platform,
            'producer_step_id':producers[0]['id'],'audio_producer_step_id':audio_steps[0]['id'],
            'current_video_ref':_pin(video),'trusted_manifest_ref':_pin(trusted_path),
            'prepared_ref':_pin(prepared_path),'tts_records_ref':_pin(tts_path),
            'tts_config_ref':_pin(cfg_path),'source_script_ref':_pin(script),
            'original_render_contract_ref':_pin(contract_path),'materials':materials,'quality_passed':False}
        raw=canonical(payload);folder=out/'quality_source_bytes';folder.mkdir(mode=0o700,exist_ok=True)
        if folder.is_symlink():raise ValueError('native_render_legacy_source_folder_untrusted')
        target=folder/('actual-audio-materials-'+hashlib.sha256(raw).hexdigest()+'.json')
        try:fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            if target.is_symlink()or target.read_bytes()!=raw:raise ValueError('native_render_legacy_source_sidecar_changed')
        else:
            with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        items=[('narration',narration),('narration',stem_files['voiceover']),('bgm',bgm),
            ('source_script',script),('subtitles',subtitle_path),('rights',rights_path),
            ('render_manifest',prepared_path),('render_manifest',tts_path),('render_manifest',cfg_path),
            ('render_manifest',contract_path),('render_manifest',trusted_path),('render_manifest',alignment_path),
            ('render_manifest',mix_path),('render_manifest',target)]
        items += [('voice_segment',_file(r['audio_ref']['path'],root))for r in view['records']]
        for digest in contract.get('backgrounds_sha256')or[]:
            rows=[r for r in store.artifacts(job_id)if r.get('checksum')==digest and r.get('kind')in('image','background')]
            paths={r['path']for r in rows}
            if len(paths)!=1:raise ValueError('native_render_legacy_actual_background_owner_missing')
            items.append(('background',_file(next(iter(paths)),root)))
        if not contract.get('backgrounds_sha256'):raise ValueError('native_render_legacy_actual_backgrounds_missing')
        pinned=[(role,path,_sha(path))for role,path in items];result=[]
        for role,path,digest in pinned:
            rows=[r for r in store.artifacts(job_id)if r.get('kind')==role and r.get('path')==str(path)]
            if rows and(len(rows)!=1 or rows[0].get('checksum')!=digest):raise ValueError('native_render_legacy_registered_part_changed')
        for role,path,digest in pinned:
            rows=[r for r in store.artifacts(job_id)if r.get('kind')==role and r.get('path')==str(path)]
            if not rows:store.add_artifact(job_id,role,str(path),digest)
            rows=[r for r in store.artifacts(job_id)if r.get('kind')==role and r.get('path')==str(path)]
            if len(rows)!=1 or rows[0].get('job_id')!=job_id or rows[0].get('checksum')!=digest or _sha(_file(path,root))!=digest:
                raise ValueError('native_render_legacy_registered_original_changed')
            result.append((role,rows[0]['id'],digest,{'producer_step':producers[0]['step_name'],
                'actual_audio_materials':_pin(target),'actual_part':_pin(path),'quality_passed':False}))
        return result

    out=video.parent
    manifest_path=out/'video_toolchain_runner_manifest.json';run=_json(manifest_path,root)
    if not isinstance(run,dict) or run.get('dry_run') is not False or run.get('returncode')!=0:
        raise ValueError('native_render_actual_runner_execution_required')
    command=run.get('renderer_command')
    if not isinstance(command,list) or not command or any(not isinstance(x,str) for x in command):
        raise ValueError('native_render_actual_renderer_command_required')
    source=base.parent/'scripts/film_renderer.py'
    declared=[run.get('renderer'),(run.get('toolchain') or {}).get('renderer') if isinstance(run.get('toolchain'),dict) else None]
    if any(v is not None and Path(str(v))!=source for v in declared):raise ValueError('native_render_declared_renderer_source_mismatch')
    if command.count(str(source))!=1:raise ValueError('native_render_actual_renderer_source_not_in_command')
    if source!=base.parent/'scripts/film_renderer.py' or source.is_symlink() or not source.is_file() or any(x.is_symlink() for x in source.parents):
        raise ValueError('native_render_actual_renderer_source_required')
    def arg(name):
        if command.count(name)!=1:raise ValueError('native_render_actual_command_argument_required:'+name)
        i=command.index(name)
        if i+1>=len(command):raise ValueError('native_render_actual_command_argument_missing:'+name)
        return command[i+1]
    if str(source) not in command or Path(arg('--video-dir'))!=out or arg('--platform')!=platform:
        raise ValueError('native_render_actual_renderer_owner_mismatch')
    contract_path=out/'render_contract.json';contract=_json(contract_path,root)
    if not isinstance(contract,dict) or contract.get('renderer_source_sha256')!=_sha(source):
        raise ValueError('native_render_renderer_source_contract_changed')
    script=_file(Path(arg('--script')) if '--script' in command else out/'script.md',root)
    if contract.get('script_sha256')!=_sha(script):raise ValueError('native_render_actual_script_contract_changed')
    preflight=_file(out/'video_preflight.json',root);cfg_path=_file(out/'tts_config.json',root);cfg=_json(cfg_path,root)
    records_path=_file(out/'tts_records.json',root);records=_json(records_path,root)
    if not isinstance(records,list) or len(records)!=8 or [r.get('index') for r in records]!=list(range(8)):
        raise ValueError('native_render_complete_actual_voice_segments_required')
    if not isinstance(cfg,dict) or cfg.get('segments')!=records or not re.fullmatch('[a-f0-9]{64}',str(cfg.get('source_config_sha256') or '')):
        raise ValueError('native_render_actual_tts_config_records_mismatch')
    prosody_path=_file(cfg.get('execution_manifest') or '',root);prosody=_json(prosody_path,root)
    if not isinstance(prosody,dict) or len(prosody.get('records') or [])!=8:
        raise ValueError('native_render_actual_prosody_incomplete')
    if (prosody.get('capability') or {}).get('hermes_config_sha256')!=cfg['source_config_sha256']:
        raise ValueError('native_render_actual_prosody_config_source_changed')
    original_narration=_file(prosody.get('audio_path') or '',root)
    if prosody.get('audio_sha256')!=_sha(original_narration):raise ValueError('native_render_actual_prosody_audio_changed')
    segments=[]
    for i,record in enumerate(records):
        if not record.get('text') or record.get('fallback_used') or record.get('text')!=prosody['records'][i].get('text'):
            raise ValueError('native_render_actual_voice_record_untrusted')
        audio=_file(record.get('audio_path') or '',root)
        if record.get('audio_sha256')!=_sha(audio):raise ValueError('native_render_actual_voice_segment_sha_mismatch')
        original=prosody['records'][i]
        for name,pin in [('audio_path','audio_sha256'),('decoded_audio_path','decoded_audio_sha256')]:
            original_path=_file(original.get(name) or '',root)
            if original.get(pin)!=_sha(original_path):raise ValueError('native_render_actual_prosody_segment_changed')
        words=record.get('provider_word_boundaries')
        if not isinstance(words,list) or not words:raise ValueError('native_render_actual_voice_word_events_missing')
        segments.append(audio)
    subtitle_path=_file(out/'subtitle_cue_manifest.json',root);subtitles=_json(subtitle_path,root)
    if not isinstance(subtitles,list) or len(subtitles)!=8 or [x.get('segment') for x in subtitles]!=list(range(1,9)):
        raise ValueError('native_render_actual_subtitles_incomplete')
    for row,record in zip(subtitles,records):
        if row.get('source')!=record['text'] or not row.get('cues') or ''.join(line for cue in row['cues'] for line in cue.get('lines',[]))!=record['text']:
            raise ValueError('native_render_actual_subtitles_text_or_events_missing')
    bg_files=[p for p in (out/'backgrounds').glob('bg_*') if p.suffix.casefold() in {'.jpg','.jpeg','.png','.webp'}]
    if len(bg_files)!=8:raise ValueError('native_render_actual_backgrounds_missing_or_changed')
    backgrounds=[]
    for i in range(1,9):
        scene=[p for p in bg_files if p.stem==f'bg_{i:02d}']
        if len(scene)!=1:raise ValueError('native_render_actual_background_scene_missing_or_ambiguous')
        backgrounds.append(_file(scene[0],root))
    if contract.get('backgrounds_sha256')!=[_sha(p) for p in backgrounds]:
        raise ValueError('native_render_actual_backgrounds_missing_or_changed')
    rights_path=_file(out/'bgm_source.json',root);rights=_json(rights_path,root);bgm=_file(out/'bgm.mp3',root)
    if not isinstance(rights,dict) or not (rights.get('source_url') or rights.get('url')) or not (rights.get('license') or rights.get('license_type')):
        raise ValueError('native_render_actual_bgm_rights_source_missing')
    if rights.get('sha256')!=_sha(bgm):raise ValueError('native_render_actual_bgm_rights_audio_changed')
    # Decode the entire final muxed track; it includes actual BGM when present.
    final_audio=out/('final-audio-'+video_sha+'.wav');receipt_path=out/('final-audio-'+video_sha+'.decode.private.json')
    for p in [final_audio,receipt_path]:
        if p.is_symlink() or any(x.is_symlink() for x in p.parents):raise ValueError('native_render_decode_target_untrusted')
    exists=final_audio.exists()
    if exists:
        old=_json(receipt_path,root)
        if old.get('source_video_sha256')!=video_sha or old.get('decoded_audio_sha256')!=_sha(final_audio) or old.get('exit_code')!=0:
            raise ValueError('native_render_existing_final_audio_binding_changed')
    elif receipt_path.exists():raise ValueError('native_render_orphan_decode_receipt')
    # Every call actually decodes; an existing self-reported receipt is insufficient.
    tmp=out/('.final-audio-'+uuid.uuid4().hex+'.wav')
    cmd=['ffmpeg','-nostdin','-v','error','-n','-i',str(video),'-map','0:a:0','-vn','-c:a','pcm_s16le',str(tmp)]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
    decode={'source_video_path':str(video),'source_video_sha256':video_sha,'command':cmd,'exit_code':result.returncode,'stderr':result.stderr[-2000:],'quality_passed':False}
    if result.returncode or not tmp.is_file() or tmp.stat().st_size<=44:
        failed=out/('final-audio-'+video_sha+'.failed-'+uuid.uuid4().hex+'.json');failed.write_text(json.dumps(decode,ensure_ascii=False));failed.chmod(0o600)
        raise ValueError('native_render_actual_final_audio_decode_failed')
    with wave.open(str(tmp),'rb') as w:
        frames=w.getnframes();rate=w.getframerate()
        if frames<=0 or rate<=0:raise ValueError('native_render_actual_final_audio_empty')
        decode.update(decoded_frames=frames,sample_rate=rate,duration_seconds=frames/rate,channels=w.getnchannels(),sample_width=w.getsampwidth())
    if _sha(video)!=video_sha:raise ValueError('native_render_video_changed_during_decode')
    if exists:
        if _sha(tmp)!=_sha(final_audio):raise ValueError('native_render_existing_audio_differs_from_actual_decode')
        tmp.unlink();receipt_path=out/('final-audio-'+video_sha+'.recheck-'+uuid.uuid4().hex+'.decode.private.json')
    else:
        os.link(tmp,final_audio);tmp.unlink();final_audio.chmod(0o600)
    decode['decoded_audio_sha256']=_sha(final_audio)
    fd=os.open(receipt_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(decode,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    # Normal renderer v2: retain its exact prosody/word events, not legacy source_text rows.
    from .current_audio_review_runtime import read_prepared_audio_records, _spoken_key
    for row in records:
        plan_ref=row.get('voice_plan_source')or{};plan_path=_file(plan_ref.get('path')or'',root)
        if _sha(plan_path)!=plan_ref.get('sha256'):raise ValueError('native_render_current_original_voice_plan_changed')
    material_view=read_prepared_audio_records(_pin(prosody_path),tts_records_ref=_pin(records_path))
    if _spoken_key(material_view['source_text'])!=_spoken_key(script.read_text(encoding='utf-8-sig')):
        raise ValueError('native_render_current_prosody_complete_script_changed')
    release_path=_file(out/'audio_release_evidence.json',root);release=_json(release_path,root)
    if release.get('version')!='audio_release_evidence_v1'or release.get('candidate_sha256')!=video_sha:
        raise ValueError('native_render_current_release_audio_source_changed')
    stems=release.get('stems')or[]
    if len(stems)!=2 or {r.get('role')for r in stems}!={'voiceover','background_music'}:
        raise ValueError('native_render_current_complete_audio_stems_required')
    stem_files={}
    for row in stems:
        path=_file(row.get('path')or'',root)
        if _sha(path)!=row.get('sha256'):raise ValueError('native_render_current_actual_stem_changed')
        stem_files[row['role']]=path
    if stem_files['background_music']!=bgm:raise ValueError('native_render_current_actual_music_source_changed')
    materials=[{'kind':'voice_segment','role':'voice_segment','file_ref':r['audio_ref'],
        'prepared_record_index':r['index'],'source_text_sha256':r['source_text_sha256'],
        'tts_text_sha256':r['tts_text_sha256']}for r in material_view['records']]
    materials += [{'kind':'narration','role':'narration','file_ref':material_view['full_narration_ref']},
        {'kind':'aligned_narration','role':'narration','file_ref':_pin(stem_files['voiceover']),'alignment_ref':_pin(release_path)},
        {'kind':'final_mix_audio','role':'narration','file_ref':_pin(final_audio),'mix_ref':_pin(receipt_path)},
        {'kind':'background_music','role':'bgm','file_ref':_pin(bgm),'rights_ref':_pin(rights_path)},
        {'kind':'final_mix','role':'video','file_ref':_pin(video),'mix_ref':_pin(receipt_path)}]
    unique={}
    for row in materials:
        path=row['file_ref']['path']
        if path in unique:
            previous=unique[path]
            if previous['role']!=row['role']or previous['file_ref']['sha256']!=row['file_ref']['sha256']:
                raise ValueError('native_render_current_same_audio_conflicting_role')
            previous.setdefault('same_file_roles',[previous['kind']]).append(row['kind'])
        else:unique[path]=row
    materials=list(unique.values())
    payload={'version':'native_actual_audio_materials_v1','prepared_schema':'current_hermes_prosody_execution_v1',
        'job_id':job_id,'platform':platform,'current_video_ref':_pin(video),'trusted_manifest_ref':_pin(manifest_path),
        'prepared_ref':_pin(prosody_path),'tts_records_ref':_pin(records_path),'tts_config_ref':_pin(cfg_path),
        'source_script_ref':_pin(script),'source_script_auxiliary_refs':[_pin(preflight),_pin(cfg_path)],
        'original_render_contract_ref':_pin(contract_path),'materials':materials,'quality_passed':False}
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    folder=out/'quality_source_bytes';folder.mkdir(mode=0o700,exist_ok=True)
    if folder.is_symlink():raise ValueError('native_render_current_audio_view_directory_untrusted')
    target=folder/('actual-audio-materials-'+hashlib.sha256(raw).hexdigest()+'.json')
    try:fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:
        if target.is_symlink()or target.read_bytes()!=raw:raise ValueError('native_render_current_audio_view_changed')
    else:
        with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    items=[('narration',final_audio),('subtitles',subtitle_path),('source_script',script),('source_script',preflight),('source_script',cfg_path),('render_manifest',records_path),('render_manifest',prosody_path),('render_manifest',contract_path),('render_manifest',manifest_path),('render_manifest',receipt_path)]
    items += [('voice_segment',p) for p in segments]+[('background',p) for p in backgrounds]+[('bgm',bgm),('rights',rights_path)]
    for role,path in [('narration',_file(material_view['full_narration_ref']['path'],root)),
            ('narration',stem_files['voiceover']),('render_manifest',release_path),('render_manifest',target)]:
        if (role,path)not in items:items.append((role,path))
    provenance={'producer_step':f'generate_video[{platform}]','producer':f'generate_video[{platform}]','platform':platform,'original_video':_pin(video),'actual_renderer_source':_pin(source),'actual_run_manifest':_pin(manifest_path),'final_audio_decode':_pin(receipt_path)}
    # Validate all identities before registering any, then re-read real Store rows.
    pinned=[(role,p,_sha(p)) for role,p in items];output=[]
    for role,p,checksum in pinned:
        old=[r for r in store.artifacts(job_id) if r.get('kind')==role and r.get('path')==str(p)]
        if old and (len(old)!=1 or old[0].get('checksum')!=checksum):raise ValueError('native_render_existing_artifact_changed')
    for role,p,checksum in pinned:
        store.add_artifact(job_id,role,str(p),checksum)
        rows=[r for r in store.artifacts(job_id) if r.get('kind')==role and r.get('path')==str(p)]
        if len(rows)!=1 or rows[0].get('job_id')!=job_id or rows[0].get('checksum')!=checksum or _sha(_file(p,root))!=checksum:
            raise ValueError('native_render_registered_artifact_identity_mismatch')
        output.append((role,rows[0]['id'],checksum,dict(provenance,actual_part=_pin(p))))
    return output
