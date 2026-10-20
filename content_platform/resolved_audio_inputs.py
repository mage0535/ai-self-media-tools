"""Bind B resolver's exact admitted input files; never select another track."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from .run_contract import validate_audio_plan

def bind_resolved_audio(plan,output_dir):
    if plan.get('status')!='resolved' or not validate_audio_plan(plan,require_bgm=True)['passed']:
        raise ValueError('resolved_native_audio_plan_required')
    output=Path(output_dir)
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents):raise ValueError('audio_output_path_untrusted')
    output.mkdir(parents=True,exist_ok=True)
    for field,name,digest in [('audio_path','bgm.mp3',plan.get('fingerprint')),
                              ('source_record_path','bgm_source.json',plan.get('source_record_sha256'))]:
        source=Path(plan.get(field) or '')
        target=output/name
        if source.is_symlink() or any(parent.is_symlink() for parent in source.parents) or not source.is_file() or not digest:
            raise ValueError('planned_audio_input_missing_or_untrusted')
        actual=hashlib.sha256(source.read_bytes()).hexdigest()
        if actual!=digest or target.is_symlink():raise ValueError('planned_audio_input_hash_mismatch')
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            raise ValueError('renderer_audio_input_conflict')
        if not target.exists():shutil.copyfile(source,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('audio_binding_changed')
    return {'fingerprint':plan['fingerprint'],'source_record_sha256':plan['source_record_sha256']}


def verify_rendered_audio_binding(plan,output_dir,video,*,platform):
    """Require renderer-written stems bound to this final file and admitted music."""
    if (plan.get('status')!='resolved' or not validate_audio_plan(plan,require_bgm=True)['passed']
            or platform not in (plan.get('rights_scope') or {}).get('platforms',[])):
        raise ValueError('rendered_audio_platform_or_plan_mismatch')
    root=Path(output_dir).resolve();video=Path(video).resolve()
    if not video.is_file() or not video.is_relative_to(root):raise ValueError('rendered_audio_video_path_invalid')
    for name,digest in [('bgm.mp3',plan.get('fingerprint')),('bgm_source.json',plan.get('source_record_sha256'))]:
        file=root/name
        if file.is_symlink() or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
            raise ValueError('rendered_audio_input_hash_mismatch')
    evidence_path=root/'audio_release_evidence.json'
    if evidence_path.is_symlink() or not evidence_path.is_file():raise ValueError('rendered_audio_stem_evidence_required')
    evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
    candidate=hashlib.sha256(video.read_bytes()).hexdigest()
    if (evidence.get('version')!='audio_release_evidence_v1' or evidence.get('candidate_sha256')!=candidate
            or evidence.get('route')!=plan['route']):raise ValueError('rendered_audio_candidate_or_route_mismatch')
    stems=[row for row in evidence.get('stems') or [] if row.get('role')=='background_music']
    if len(stems)!=1 or stems[0].get('sha256')!=plan['fingerprint'] or Path(stems[0].get('path') or '').resolve()!=root/'bgm.mp3':
        raise ValueError('rendered_audio_actual_stem_mismatch')
    return {'audio_sha256':plan['fingerprint'],'source_record_sha256':plan['source_record_sha256'],
        'candidate_sha256':candidate,'audio_release_sha256':hashlib.sha256(evidence_path.read_bytes()).hexdigest()}


def actual_audio_render_changes(output_dir,video,plan):
    """Derive credit changes only from the renderer's successful actual mix command."""
    root=Path(output_dir).resolve();path=root/'audio_mix_evidence.json'
    revision=root/'audio_mix_revision_binding.json'
    if revision.exists():
        if any(p.is_symlink() for target in (Path(output_dir),Path(video)) for p in (target,*target.parents)):
            raise ValueError('audio_revision_output_path_untrusted')
        return _preserved_revision_changes(root,Path(video),plan,revision)
    if path.is_symlink() or not path.is_file():raise ValueError('native_audio_mix_evidence_required')
    proof=json.loads(path.read_text(encoding='utf-8'));command=proof.get('command')
    if (proof.get('version')!='native_audio_mix_v1' or proof.get('returncode')!=0 or proof.get('bgm_sha256')!=plan.get('fingerprint')
            or not isinstance(command,list) or not command or Path(str(command[0])).name not in {'ffmpeg','ffmpeg.exe'}):
        raise ValueError('native_audio_mix_binding_invalid')
    output=Path(proof.get('output') or '').resolve()
    if not output.is_file() or not output.is_relative_to(root) or hashlib.sha256(output.read_bytes()).hexdigest()!=proof.get('output_sha256'):
        raise ValueError('native_audio_mix_output_changed')
    if '-i' not in command or str(root/'bgm.mp3') not in [str(Path(command[index+1]).resolve()) for index,item in enumerate(command[:-1]) if item=='-i']:
        raise ValueError('native_audio_mix_input_not_bound')
    filters=command[command.index('-filter_complex')+1] if '-filter_complex' in command else ''
    if 'amix=' not in filters or 'volume=' not in filters or '-stream_loop' not in command:
        raise ValueError('native_audio_mix_operations_missing')
    return ['mixed_with_narration','trimmed_or_looped','volume_adjusted']


def _preserved_revision_changes(root,video,plan,path):
    """Keep the actual original mix receipt and verify a copied AAC timeline."""
    if (any(p.is_symlink() for target in (root,video,path) for p in (target,*target.parents))
            or path.stat().st_uid!=0 or path.stat().st_mode&0o077 or path.stat().st_size>16384):
        raise ValueError('audio_revision_private_binding_required')
    value=json.loads(path.read_bytes())
    if (value.get('version')!='same940c_preserved_audio_revision_v1'
            or value.get('job_id')!='940c5334ccb445a0'
            or value.get('candidate_sha256')!='733d65daee0843636d29efb67c69ddb7e6d5b6fd2e10cf91575870ea05615e55'
            or hashlib.sha256(video.read_bytes()).hexdigest()!=value['candidate_sha256']
            or not video.is_relative_to(root)
            or not root.is_relative_to(Path('/srv/ai-self-media-tools/data/artifacts/940c5334ccb445a0'))):
        raise ValueError('audio_revision_exact_same_entity_required')
    source=Path(value['original_mix_evidence_path']);original=Path(value['original_video_path'])
    if any(p.is_symlink() for target in (source,original) for p in (target,*target.parents)):
        raise ValueError('audio_revision_original_path_untrusted')
    source=source.resolve();original=original.resolve()
    if (source.parent/'audio_mix_revision_binding.json').exists():
        raise ValueError('audio_revision_original_must_have_native_mix_only')
    if (source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!='9e3c1142b68c56338293bd1fbf2756180922844b576bd8532cf8bd2f4f3c5b28'
            or original.parent!=source.parent
            or hashlib.sha256(original.read_bytes()).hexdigest()!='acf0c79bc08e976aef38c46a67cc1239abf5556135acfed3be0b8f89d0554004'):
        raise ValueError('audio_revision_original_mix_or_movie_changed')
    # Read the successful command in its real original directory, without
    # relabeling its command/output paths or claiming another mix execution.
    changes=actual_audio_render_changes(source.parent,original,plan)
    mixed=Path(json.loads(source.read_bytes())['output']).resolve()
    if hashlib.sha256(mixed.read_bytes()).hexdigest()!='794f1af34ef2d41688f389eb16079d9e8be0538abde8ade400dab66cb3c009c7':
        raise ValueError('audio_revision_original_mixed_output_changed')
    for movie in (mixed,original,video):
        audio=subprocess.check_output(['ffmpeg','-v','error','-i',str(movie),'-map','0:a:0','-c','copy','-f','adts','pipe:1'],timeout=30)
        packets=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a','-show_packets',
            '-show_entries','packet=pts,dts,duration,size','-of','json',str(movie)],timeout=30))['packets']
        timeline=hashlib.sha256(json.dumps(packets,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if (hashlib.sha256(audio).hexdigest()!='5e1167bfb8f840bc86af413ca4737250e68b0d76174ee7b63fbba2fb8a028d47'
                or len(packets)!=3149 or timeline!='4aec7af349fdae16f3aed9095908276412c0de552c7d511b521cb9319df5b224'):
            raise ValueError('audio_revision_stream_or_timeline_changed')
    for cue in (source.parent/'subtitle_cue_manifest.json',root/'subtitle_cue_manifest.json'):
        if hashlib.sha256(cue.read_bytes()).hexdigest()!='44897adf742b55d9e805be4d7755db36b51e7a4b825dd77f4120d3ff52f2586e':
            raise ValueError('audio_revision_cue_changed')
    verify_rendered_audio_binding(plan,root,video,platform='kuaishou')
    return changes
