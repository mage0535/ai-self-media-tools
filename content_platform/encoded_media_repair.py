"""Finish one root-authorized pixel repair through the normal native release gates."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .media_revision import digest, file_record, verify_resume_originals, private_manifest, verify_parent

JOB = '940c5334ccb445a0'
ORIGIN = '2b3345a08c9a464abf6366724bfc825c'
SCOPE_ORIGIN = 'b7cbeb6a627041319e851ea6b87199e9'
AUDIO_ORIGIN = '535556ef492d4ad392277a51715523a6'
OLD_VIDEO = 'acf0c79bc08e976aef38c46a67cc1239abf5556135acfed3be0b8f89d0554004'
NEW_VIDEO = '733d65daee0843636d29efb67c69ddb7e6d5b6fd2e10cf91575870ea05615e55'
AUDIO = '5e1167bfb8f840bc86af413ca4737250e68b0d76174ee7b63fbba2fb8a028d47'

def audio_sha(path):
    raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','adts','pipe:1'],timeout=30)
    return hashlib.sha256(raw).hexdigest()

def encoded_evidence(path, expected):
    raw, _ = file_record(path, expected); info = Path(path).stat(); value = json.loads(raw)
    if os.geteuid()!=0 or info.st_uid!=0 or info.st_mode&0o077:
        raise PermissionError('root_private_encoded_repair_required')
    if (value.get('version')!='media_encoded_pixel_repair_v1' or value.get('job_id')!=JOB
            or (value.get('recovery_index'),value.get('origin_run_id'),len(value.get('original_steps',[]))) not in {(4,ORIGIN,17),(5,SCOPE_ORIGIN,18),(6,AUDIO_ORIGIN,21)}
            or value.get('create_control_job_id')!='570c368593a548e69289e7bc5bcbe844'
            or value.get('original_video',{}).get('sha256')!=OLD_VIDEO or value.get('candidate_video',{}).get('sha256')!=NEW_VIDEO
            or value.get('audio_adts_sha256')!=AUDIO
            or value.get('budget_seconds')!=1800 or value.get('no_publish_no_approval') is not True
            or value.get('video_frame_count')!=1815):
        raise ValueError('exact_known_encoded_pixel_repair_required')
    return value

def validate_encoded_inputs(store, path, expected):
    value = encoded_evidence(path, expected); job=store.get_job(JOB)
    index=value['recovery_index']
    if (job['state']!='failed' or job.get('lease_owner') or job['attempts']!=index or digest(job)!=value['job_sha256']):
        raise ValueError('encoded_repair_original_job_changed')
    verify_resume_originals(store,value)
    if index==6:
        steps={row['id']:row for row in value['original_steps']}
        if any(steps.get(i,{}).get('status')!='SUCCEEDED' for i in (5300,5302,5303)):
            raise ValueError('registered_audio_completion_original_success_required')
        if json.loads(value['original_events'][-1]['detail_json']).get('error')!='native_audio_mix_output_changed':
            raise ValueError('registered_audio_completion_exact_failure_required')
        for key,ident in [('registered_video',1079),('registered_cover',1080)]:
            item=value[key];file_record(item['path'],item['checksum'])
            if item['id']!=ident or item not in store.artifacts(JOB):raise ValueError('registered_audio_completion_artifact_changed')
        if store.platform_outputs(JOB):raise ValueError('registered_audio_completion_outputs_already_exist')
        if any(r['event']=='registered_audio_metadata_review_requested' for r in store.events(JOB)):
            raise ValueError('registered_audio_completion_already_finished')
        if value.get('failed_event_id')!=7353 or value.get('failed_step_count')!=5 or value.get('failed_step_id') is not None:
            raise ValueError('registered_audio_completion_failure_identity_changed')
        if any(digest(steps[i]['output'])!=value['successful_checkpoint_output_sha256'][str(i)] for i in (5300,5302,5303)):
            raise ValueError('registered_audio_completion_success_changed')
        return value
    failed=[row for row in value['original_steps'] if row['status']!='SUCCEEDED']
    expected_failure=(5296,'isolated_bright_flash') if index==4 else (5298,'original_native_store_scope_required')
    if (len(failed)!=index or any(row['status']!='FAILED_FINAL' for row in failed)
            or failed[-1]['id']!=expected_failure[0] or expected_failure[1] not in failed[-1]['message']):
        raise ValueError('encoded_repair_four_original_failures_required')
    for row in [value['original_video'],value['candidate_video'],value['patch_manifest']]:file_record(row['path'],row['sha256'])
    old=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',value['original_video']['path']]))
    new=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',value['candidate_video']['path']]))
    for a,b in zip(old['streams'],new['streams']):
        if any(a.get(k)!=b.get(k) for k in ('codec_type','duration','nb_frames','time_base','start_time')):
            raise ValueError('encoded_repair_timebase_changed')
    if old['format']['duration']!=new['format']['duration'] or audio_sha(value['original_video']['path'])!=AUDIO or audio_sha(value['candidate_video']['path'])!=AUDIO:
        raise ValueError('encoded_repair_audio_or_duration_changed')
    if store.platform_outputs(JOB) or any(row['kind']=='video' for row in store.artifacts(JOB)):
        raise ValueError('encoded_repair_already_registered')
    starts=[json.loads(row['detail_json']) for row in store.events(JOB) if row['event']=='encoded_pixel_repair_started']
    if (len(starts)!=index-4 or any(row.get('evidence_sha256')==expected for row in starts)
            or (index==5 and starts[0].get('evidence_sha256')!='a51154a124f88aaa5f053ed56f34ecfcd364b8b1d5ae51366a4954931d94eeec')):
        raise ValueError('encoded_repair_already_started_no_replay')
    reference=job['brief']['media_revision'];verify_parent(store,private_manifest(reference['manifest_path'],reference['manifest_sha256']))
    return value

def _write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def finalize_native_artifact(pipeline, evidence, owner, evidence_sha, technical_preview=False):
    """Measure the exact new video and call the existing production release runtime."""
    from .platform_video_run import build_platform_video_run
    from .video_generation_contract import compile_generation_contract
    from .video_run import RunState
    from .video_artifact import measure_motion_evidence, verify_artifact, verify_final_pixels
    from .video_release_runtime import release_rendered_candidate
    from scripts.film_renderer import (measure_luminance_flash_evidence,measure_spatial_motion_evidence,
        build_render_quality_evidence,build_audio_release_evidence,probe_audio_spec,validate_audio_spec)
    from scripts.video_toolchain_runner import _write_generated_cover_evidence, _run_cinema_visual_gate, _render_motion_evidence
    from scripts.gen_cover import generate_cover
    from .media import MediaBridge
    job=pipeline.store.get_job(JOB);metadata_only=evidence.get('recovery_index')==6
    source=Path(evidence['registered_video']['path']).parent if metadata_only else Path(evidence['original_video']['path']).parent
    run=build_platform_video_run(data_dir=pipeline.data_dir,job_id=JOB,platform='kuaishou',attempt_id='encoded-repair-'+evidence_sha[:16])
    output=run.output_dir;final=output/'final.mp4';cover=output/'cover.png'
    plan=json.loads((source/'video_toolchain_plan.json').read_bytes());plan['attempt_id']=run.attempt_id
    plan['revision']=int(plan.get('revision') or 1)+1;plan['canonical_output_name']='final.mp4';plan['canonical_cover_name']='cover.png'
    plan['job_id']=JOB;plan['platform_run_id']=run.platform_run_id
    inputs={'original_encoded_video':Path(evidence['original_video']['path']),
        'pixel_repair_manifest':Path(evidence['patch_manifest']['path']),'original_facts':Path(job['brief']['original_knowledge_ref']['path'])}
    if technical_preview:
        from .video_run import RunManifest,RunSpec,ArtifactSpec,ArtifactRole
        artifacts=tuple(ArtifactSpec(name=k,path=v,role=ArtifactRole.INPUT) for k,v in inputs.items())+(
            ArtifactSpec(name='video',path=final,role=ArtifactRole.OUTPUT),ArtifactSpec(name='cover',path=cover,role=ArtifactRole.OUTPUT))
        contract={'run_manifest':RunManifest.plan(RunSpec(run_id=JOB,revision=plan['revision'],attempt_id=run.attempt_id,artifacts=artifacts))}
    else:
        # Native compilation checks the exact Store, original facts, signed
        # continuation and current live lease before creating any output.
        if os.environ.get('NATIVE_VIDEO_STORE_PATH')!=str(pipeline.store.path.resolve()):
            raise ValueError('encoded_repair_native_store_environment_mismatch')
        contract=compile_generation_contract(plan,output_dir=output,input_paths=inputs)
    output.mkdir(parents=True,exist_ok=False)
    # Preserve exact inherited factual, audio and clip files; create an independent output version.
    for item in source.iterdir():
        if item.name in {'final.mp4','trusted_run_manifest.json','video_toolchain_runner_manifest.json','delivery_manifest.json','preview.mp4'}:continue
        if item.name in {'packet.json','audio_mix_revision_binding.json'}:continue
        if item.is_dir():shutil.copytree(item,output/item.name)
        elif metadata_only and item.suffix in {'.mp4','.png','.wav','.mp3'}:os.link(item,output/item.name)
        else:shutil.copy2(item,output/item.name)
    if metadata_only:os.link(evidence['registered_video']['path'],final)
    else:shutil.copy2(evidence['candidate_video']['path'],final)
    if file_record(final)[1]!=NEW_VIDEO:raise ValueError('encoded_repair_copy_changed')
    _write(output/'video_toolchain_plan.json',plan)
    runner=json.loads((source/'video_toolchain_runner_manifest.json').read_bytes())
    inherited={'path':str(source/'video_toolchain_runner_manifest.json'),'sha256':file_record(source/'video_toolchain_runner_manifest.json')[1],
               'original_video_sha256':OLD_VIDEO,'original_returncode':runner.get('returncode')}
    runner.pop('error',None);runner.pop('stderr_tail',None);runner.pop('stdout_tail',None)
    runner.update(output=str(final),ok=False,status='encoded_pixel_repair_checking',inherited_failed_attempt=inherited,
                  encoded_pixel_repair={'evidence_sha256':evidence_sha,'candidate_sha256':NEW_VIDEO,'models':0,'tts':0})
    flash=measure_luminance_flash_evidence(final);_write(output/'luminance_flash_evidence.json',flash)
    pixel=verify_final_pixels(final);_write(output/'final_pixel_gate.json',pixel)
    if not flash['passed'] or not pixel['passed']:raise ValueError('encoded_repair_real_pixel_gate_failed')
    spec=validate_audio_spec(probe_audio_spec(final));_write(output/'audio_quality_evidence.json',spec)
    if not spec['passed']:raise ValueError('encoded_repair_audio_spec_failed')
    audio=build_audio_release_evidence(final,output/'voice_aligned.wav',output/'bgm.mp3','embedded_licensed_bgm')
    _write(output/'audio_release_evidence.json',audio);runner['audio_evidence']=audio
    motion=measure_motion_evidence(final);spatial=measure_spatial_motion_evidence(final)
    # The source clips are physical, hash-bound prior render outputs. B clips are native frame-driven videos.
    records=[];segments=[]
    for index in range(1,9):
        bound=[]
        for suffix in 'AB':
            name='shot_%02d%s'%(index,suffix);clip=source/'shots'/(name+'.mp4')
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(clip)]))
            if int(probe['streams'][0]['nb_frames'])<2:raise ValueError('encoded_repair_prior_clip_empty')
            row={'name':name,'renderer':'playwright-frame-video' if suffix=='B' else 'inherited_static_establish',
                 'fallback':False,'reused':True,'inherited_path':str(clip),'sha256':file_record(clip)[1]}
            records.append(row);bound.append({'name':name,'path':str(clip),'sha256':row['sha256'],'renderer':row['renderer'],'reused':True,'fallback':False})
        scene=plan['visual_contract'][index-1]
        segments.append({'index':index,'move_id':scene['visual_mode'],'profile':'inherited-native-scene-%02d'%index,
                         'inherited_from_original_video_sha256':OLD_VIDEO,'pixel_repair_manifest_sha256':evidence['patch_manifest']['sha256'],
                         'shot_outputs':bound,'rendered':True,'reused':True})
    quality=build_render_quality_evidence(policy={'quality_profile':'high','motion_mode':'cinematic'},shot_records=records,motion=motion,spatial_motion=spatial)
    quality['candidate_sha256']=NEW_VIDEO;_write(output/'render_quality_evidence.json',quality)
    if not quality['passed']:raise ValueError('encoded_repair_cinema_quality_failed:'+','.join(quality['failures']))
    runner['render_quality_evidence']=quality;runner['motion_evidence']=_render_motion_evidence(final)
    if not runner['motion_evidence']['passed']:raise ValueError('encoded_repair_native_motion_probe_failed')
    segment={'receipt_version':'segment_motion_evidence_v2','segments':segments,'final_video_sha256':NEW_VIDEO,
             'lineage':'same_encoded_movie_pixel_repair','scene_contract_sha256':file_record(output/'scene_contract.json')[1]}
    _write(output/'segment_motion_evidence.json',segment);runner['segment_motion_evidence']=segment
    cards=output/'cards';cards.mkdir(exist_ok=True)
    alignment=json.loads((source/'av_alignment_evidence.json').read_bytes())
    for scene in alignment['segments']:
        at=scene['scene_start']+(.2 if scene['segment']==1 else .8)
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(at),'-i',str(final),'-frames:v','1',str(cards/('card_%02d.png'%scene['segment']))],capture_output=True,check=True,timeout=20)
    cinema=copy.deepcopy(runner['cinema_visual_gate']) if metadata_only else _run_cinema_visual_gate(output)
    runner['cinema_visual_gate']=cinema
    if not cinema['passed']:raise ValueError('encoded_repair_cinema_visual_gate_failed')
    from PIL import Image
    title='总数对上却漏单';cover=output/'cover.png'
    original_background=pipeline.data_dir/'artifacts'/JOB/'scene-01.png';background=output/'cover-background.png'
    canvas=Image.new('RGB',(1080,1920),(108,124,128))
    with Image.open(original_background) as image:
        canvas.paste(image.convert('RGB').crop((35,335,1046,804)),(35,940))
    if not metadata_only:canvas.save(background)
    provenance={'source_path':str(original_background),'source_sha256':file_record(original_background)[1],
        'crop_xyxy':[35,335,1046,804],'paste_xy':[35,940],'pixel_transform':'crop_and_placement_only'}
    _write(output/'cover-background-provenance.json',provenance)
    generated=str(cover) if metadata_only else generate_cover(title=title,highlight='<span style="font-size:88px;letter-spacing:0;text-shadow:none;color:white;">总数对上却漏单</span>',
        subtitle='',hook='',bg_image=str(background),output_path=str(cover),orientation='vertical',tag='',cta='',badge='',layout='premium_fintech')
    if not generated:raise RuntimeError('encoded_repair_cover_browser_failed')
    _write_generated_cover_evidence(cover_path=cover,evidence_path=output/'cover_evidence.json',platform='kuaishou',title=title,
        subtitle='',background_path=str(background),background_source='self_created_original_scene_crop',layout_key='premium_fintech',semantic_subject=job['topic'])
    cover_evidence=json.loads((output/'cover_evidence.json').read_bytes())
    cover_evidence['background_provenance'].update(provenance);_write(output/'cover_evidence.json',cover_evidence)
    if metadata_only:
        original=Path(evidence['original_video']['path'])
        binding={'version':'same940c_preserved_audio_revision_v1','job_id':JOB,'candidate_sha256':NEW_VIDEO,
            'original_mix_evidence_path':str(original.parent/'audio_mix_evidence.json'),'original_video_path':str(original)}
        _write(output/'audio_mix_revision_binding.json',binding);(output/'audio_mix_revision_binding.json').chmod(0o600)
        from .formatters import format_for_platform
        from .task_source_inputs import project_task_source_job
        from .resolved_audio_inputs import actual_audio_render_changes
        from .audio_attribution_formatter import bind_audio_attribution
        actual=actual_audio_render_changes(output,final,plan['audio_plan'])
        prepared=format_for_platform(project_task_source_job(job,'kuaishou'),'kuaishou',audio_phase='planning')
        prepared.pop('music_attribution_status',None)
        credit=bind_audio_attribution(prepared,plan['audio_plan'],platform='kuaishou',render_changes=actual,copy_limit=220)
        packet=copy.deepcopy(next(r for r in evidence['original_steps'] if r['id']==5300)['output']['render_packet'])
        packet.update(description=credit['caption'],music_attribution=credit['music_attribution'],video_sha256=NEW_VIDEO)
        _write(output/'packet.json',packet)
    state=contract['run_manifest'].advance(RunState.CONTRACT_VALIDATED).advance(RunState.ASSETS_VALIDATED)
    runner.update(cover=str(cover),subtitle={'width':1080,'height':1920},ok=True,status='technical_checked')
    _write(output/'video_toolchain_runner_manifest.json',runner)
    released=release_rendered_candidate(manifest=state,output_dir=output,candidate=final,cover=cover,
        cover_evidence=output/'cover_evidence.json',platform='kuaishou',render_manifest=runner,trusted_manifest_path=output/'trusted_run_manifest.json')
    delivery=json.loads((output/'delivery_manifest.json').read_bytes())
    runner.update(ok=True,status='handoff_ready',trusted_run_manifest=str(output/'trusted_run_manifest.json'),artifact_set_sha256=delivery['artifact_set_sha256'])
    _write(output/'video_toolchain_runner_manifest.json',runner)
    # Normal checker runtime owns HANDOFF_READY; no direct state/score override.
    MediaBridge._validate_trusted_video_manifest(output,expected_output=final)
    cues=json.loads((source/'subtitle_cue_manifest.json').read_bytes());render_contract=json.loads((source/'render_contract.json').read_bytes())
    if not all(row['complete'] for row in cues):raise ValueError('encoded_repair_subtitle_source_incomplete')
    max_chars=max(len(line) for row in cues for cue in row['cues'] for line in cue['lines'])
    max_lines=max(len(cue['lines']) for row in cues for cue in row['cues'])
    packet={'render_manifest':runner,'audio_probe':{'stream_count':1,'duration':float(probe_audio_spec(final).get('duration') or 73.08)},
        'subtitle':{'cue_count':sum(len(row['cues']) for row in cues)},
        'burned_captions':{'position':'lower_third','burned_in':True,'font_size':44,'max_chars_per_line':max_chars,'max_lines':max_lines,'margin_v':render_contract['subtitle_y_up']},
        'background_assets':runner.get('materialized_backgrounds',[]),'bgm_source':json.loads((source/'bgm_source.json').read_bytes())}
    return {'kind':'video','path':str(final),'checksum':NEW_VIDEO,'render_manifest':runner,'render_packet':packet,
            'resolved_video_toolchain_plan':plan,'producer_step':('finish_encoded_pixel_repair__resume_'+SCOPE_ORIGIN if evidence.get('recovery_index')==5 else 'finish_encoded_pixel_repair'),'cover':str(cover)}

def finish_encoded_revision(pipeline, job_id, path, pin):
    from .workflow_runtime import WorkflowStepRunner,strict_workflow_lock
    from .media_revision import _finish_registered_encoded
    if job_id!=JOB or os.environ.get('CONTENT_PLATFORM_NO_MODEL_CALLS')!='1' or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH')!='0':
        raise PermissionError('encoded_repair_no_model_no_publish_required')
    evidence=validate_encoded_inputs(pipeline.store,path,pin);store=pipeline.store;owner=pipeline._worker_id()
    with strict_workflow_lock(store,owner,'wf_'+JOB,1800,pipeline.strict_serial):
        validate_encoded_inputs(store,path,pin)
        if not store.claim(JOB,{'failed'},owner,1800,'generating'):raise RuntimeError('encoded_repair_claim_conflict')
        try:
            token_pin=digest({'manifest_sha256':evidence['input_manifest_sha256'],'resume_evidence_sha256':pin,'lease_owner':owner})
            token=pipeline.review_tokens.issue(JOB,'original_knowledge',ttl=1800,continuation_sha256=token_pin)
            token_path=Path(path).with_suffix('.token')
            with token_path.open('x') as stream:os.chmod(token_path,0o600);stream.write(token)
            store.record_event(JOB,'encoded_pixel_repair_started',{'origin_run_id':evidence['origin_run_id'],'evidence_sha256':pin,'source_models':0,'tts':0,'external_publish':False})
            store.record_event(JOB,'media_revision_authority_renewed',{'evidence_path':str(path),'evidence_sha256':pin,'lease_owner':owner,
                'token_path':str(token_path),'token_sha256':hashlib.sha256(token.encode()).hexdigest()})
            runner=WorkflowStepRunner(store,'wf_'+JOB,JOB,notifier=pipeline.notifier)
            step=('finish_registered_audio_metadata__resume_'+AUDIO_ORIGIN if evidence['recovery_index']==6 else
                'finish_encoded_pixel_repair__resume_'+SCOPE_ORIGIN if evidence['recovery_index']==5 else 'finish_encoded_pixel_repair')
            artifact=runner.run(step,lambda:finalize_native_artifact(pipeline,evidence,owner,pin),depends_on=['validate_image_requirements'],require_output=True)
            if evidence['recovery_index']==6:
                metadata_root=Path(artifact['path']).parent
                current=store.get_job(JOB);meta=copy.deepcopy(current['draft_meta'])
                meta['native_metadata_revision']={'path':str(metadata_root),'video_sha256':NEW_VIDEO,
                    'cover_path':evidence['registered_cover']['path'],'cover_sha256':evidence['registered_cover']['checksum'],
                    'trusted_sha256':file_record(metadata_root/'trusted_run_manifest.json')[1],
                    'delivery_sha256':file_record(metadata_root/'delivery_manifest.json')[1]}
                risk=next(r for r in evidence['original_steps'] if r['step_name']=='run_safety_gate')['output']
                store.save_draft(JOB,current['title'],current['body'],risk['level'],risk,current['prompt_version'],meta)
                old=copy.deepcopy(next(r for r in evidence['original_steps'] if r['id']==5300)['output'])
                images=copy.deepcopy(next(r for r in evidence['original_steps'] if r['step_name']=='generate_or_collect_images')['output'])
                images['images'].append({'kind':'cover','role':'cover','path':evidence['registered_cover']['path'],'checksum':evidence['registered_cover']['checksum']})
                gate=next(r for r in evidence['original_steps'] if r['id']==5303)['output']
                audio=next(r for r in evidence['original_steps'] if r['step_name']=='generate_audio')['output']
                pipeline._record_platform_outputs(JOB,gate,images,{'kuaishou':old},[('audio',audio)])
                if len(store.platform_outputs(JOB))!=13:raise ValueError('registered_metadata_normal_13_outputs_required')
                from scripts.video_toolchain_runner import _register_visual_recipe_use
                recipe=json.loads((metadata_root/'visual_recipe.json').read_bytes())
                _register_visual_recipe_use(recipe,artifact['resolved_video_toolchain_plan'],evidence['registered_video']['path'])
                result=pipeline._hydrate(store.release_claim(JOB,owner,'review_required','registered_audio_metadata_review_requested',detail={'origin_run_id':AUDIO_ORIGIN,'evidence_sha256':pin,'external_publish':False}))
                pipeline.notifier.send('review_required',result)
            else:result=_finish_registered_encoded(pipeline,evidence,owner,runner,artifact)
            verify_resume_originals(store,evidence);return result
        except Exception as exc:
            verify_resume_originals(store,evidence)
            if store.get_job(JOB).get('lease_owner')==owner:store.release_claim(JOB,owner,'failed','encoded_pixel_repair_failed',str(exc))
            raise
