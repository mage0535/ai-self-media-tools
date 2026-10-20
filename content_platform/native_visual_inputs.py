"""Read raw user visual inputs; admit every new beat through real native review."""
from __future__ import annotations
import copy, hashlib, json, os, re, shutil
from pathlib import Path
from PIL import Image

CELLS=('compare_counts_and_ids','inspect_repeated_rows','retain_baseline','count_matching_ids',
       'find_missing_id','separate_duplicate_missing','stop_unreviewed_deletion','handoff_four_files','independent_cover_hook')
PURPOSE='orders_id_check_visual_inputs'

def _file(record):
    if not isinstance(record,dict) or set(record)!={'path','sha256'}:
        raise ValueError('user_visual_file_pin_invalid')
    p=Path(record['path'])
    if (not p.is_absolute() or '..' in p.parts or p.is_symlink() or any(x.is_symlink() for x in p.parents)
            or not p.is_file() or not re.fullmatch('[a-f0-9]{64}',str(record['sha256']))
            or hashlib.sha256(p.read_bytes()).hexdigest()!=record['sha256']):
        raise ValueError('user_visual_file_changed')
    return p

def _source(source):
    if (not isinstance(source,dict) or set(source)!={'provider','model_identity','prompt','generation_call'}
            or source['provider']!='builtin_imagegen' or source['model_identity']!='not_exposed_by_builtin_tool'
            or not re.fullmatch(r'exec-[a-f0-9-]{36}',str(source['generation_call']))):
        raise ValueError('user_visual_generation_source_invalid')
    if not _file(source['prompt']).read_text(encoding='utf8').strip():
        raise ValueError('user_visual_prompt_empty')

def _asset(row,name,atlas=False):
    fields={'name','file','width','height','source_kind','source','rights_provenance'}
    fields|={'grid','cells'} if atlas else {'illustrative_scene_not_customer_data'}
    if not isinstance(row,dict) or set(row)!=fields or row['name']!=name:
        raise ValueError('user_visual_asset_fields_invalid')
    expected_kind='generated_functional_role_atlas' if atlas else 'generated_photographic_scene'
    if (row['source_kind']!=expected_kind or type(row['width']) is not int or type(row['height']) is not int
            or min(row['width'],row['height'])<500 or not row['rights_provenance']
            or (not atlas and row['illustrative_scene_not_customer_data'] is not True)):
        raise ValueError('user_visual_asset_metadata_invalid')
    p=_file(row['file']);_source(row['source'])
    with Image.open(p) as im:
        im.load()
        if im.size!=(row['width'],row['height']):raise ValueError('user_visual_dimensions_changed')
        if atlas and ('A' not in im.getbands() or im.getchannel('A').getextrema()[0]>=255):
            raise ValueError('user_visual_atlas_transparency_required')
    if atlas and (row['grid']!=[3,3] or row['cells']!=list(CELLS)):
        raise ValueError('user_visual_atlas_cells_changed')
    return row

def read_user_visual_materials_inputs(ref):
    p=_file(ref)
    value=json.loads(p.read_text(encoding='utf8'))
    if (not isinstance(value,dict) or set(value)!={'version','purpose','backgrounds','cover','functional_role_atlas'}
            or value['version']!='user_visual_materials_inputs_v1' or value['purpose']!=PURPOSE
            or not isinstance(value['backgrounds'],list) or len(value['backgrounds'])!=8):
        raise ValueError('user_visual_materials_schema_invalid')
    for i,row in enumerate(value['backgrounds'],1):_asset(row,f'scene{i:02}')
    _asset(value['cover'],'cover');_asset(value['functional_role_atlas'],'functional-role-atlas',True)
    hashes=[r['file']['sha256'] for r in value['backgrounds']]+[value['cover']['file']['sha256']]
    if len(set(hashes))!=9:raise ValueError('user_visual_nine_distinct_backgrounds_required')
    return copy.deepcopy(value)

def functional_role_markup(record,index,*,size=400):
    """Compose the original bitmap as a CSS sprite; never modify its pixels."""
    import base64
    from html import escape
    _asset(record,'functional-role-atlas',True)
    if type(index) is not int or not 0<=index<9:raise ValueError('functional_role_cell_invalid')
    width=float(size);col=index%3;row=index//3
    cell_width=record['width']/3;cell_height=record['height']/3
    source_x=col*cell_width;source_y=row*cell_height
    # The actual generated atlas has heads above the last row's nominal edge;
    # source pixels stay unchanged, only the native sprite viewport is placed.
    if row==2:source_y-=30
    if index==1:source_x+=38;cell_width-=38
    scale=width/cell_width;height=cell_height*scale
    b64=base64.b64encode(_file(record['file']).read_bytes()).decode()
    return ('<div class="functional-role-sprite" data-visual-role="functional-character" '
        'data-semantic-key="'+escape(CELLS[index])+'" data-source-sha256="'+record['file']['sha256']+'" '
        'data-source-rect="'+','.join(str(round(v,3)) for v in (source_x,source_y,cell_width,cell_height))+'" '
        'style="width:'+str(width)+'px;height:'+str(height)+'px;background-image:url(data:image/png;base64,'+b64+');'
        'background-size:'+str(record['width']*scale)+'px '+str(record['height']*scale)+'px;'
        'background-position:'+str(-source_x*scale)+'px '+str(-source_y*scale)+'px;background-repeat:no-repeat"></div>')

def prepare_native_user_assets(job,output_dir,plan,store):
    from .video_asset_semantics import validate_requirement,admit_review,validate_assignments
    from .asset_semantic_review import review_asset
    ref=plan.get('user_visual_materials_source');inputs=read_user_visual_materials_inputs(ref)
    if store is None or Path(store.path)!=Path('/srv/ai-self-media-tools/data/state.db'):
        raise ValueError('user_visual_canonical_store_required')
    actual=store.get_job(job['id'])
    if (actual.get('state')!='generating' or not actual.get('lease_owner') or actual.get('lease_owner')!=job.get('lease_owner')
            or (actual.get('brief') or {}).get('user_visual_materials_source')!=ref):
        raise ValueError('user_visual_actual_store_lease_required')
    requirements=[validate_requirement(x) for x in plan.get('video_asset_requirements') or []]
    scenes=plan.get('visual_contract') or []
    if len(requirements)!=8 or len(scenes)!=8:raise ValueError('user_visual_exact_beat_requirements_required')
    directory=Path(output_dir)/'video-semantic-assets';directory.mkdir(parents=True,exist_ok=True)
    assignments=[];topic=str(job.get('topic') or job.get('title') or '')
    for i,(asset,requirement) in enumerate(zip(inputs['backgrounds'],requirements),1):
        target=directory/f'user-scene{i:02}.png'
        shutil.copy2(_file(asset['file']),target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=asset['file']['sha256']:
            raise ValueError('user_visual_copied_background_changed')
        review=review_asset(str(target),topic,requirement['intent']['beat_id'],semantic_requirement=requirement,
            native_context={'store':store,'job_id':job['id'],'lease_owner':actual['lease_owner'],
                            'original_knowledge_ref':(actual.get('brief') or {}).get('original_knowledge_ref')})
        tag=admit_review(target,topic,requirement,review)
        row={'path':str(target),'sha256':asset['file']['sha256'],'source_image':str(target),'background_image':str(target),
             'scene':i,'beat_id':requirement['intent']['beat_id'],'reused':False,'review_topic':topic,
             'source_kind':asset['source_kind'],'origin':'ai_generated',
             'source_url':'generated:builtin_imagegen:'+asset['source']['generation_call'],
             'license':'user_generated_for_authorized_project','rights_provenance':asset['rights_provenance'],
             'generation_evidence':dict(copy.deepcopy(asset['source']),model=asset['source']['model_identity'],
                                        prompt_sha256=asset['source']['prompt']['sha256'],role='illustrative_scene_background'),
             'dimensions':{'width':asset['width'],'height':asset['height']},
             'semantic_requirement':requirement,'semantic_review':review,'semantic_match_score':review['score'],
             'match_reason':review['reason'],'semantic_tags':[tag],'user_visual_materials_source':copy.deepcopy(ref)}
        assignments.append(row)
    validate_assignments(scenes,assignments)
    for key in ('cover','functional_role_atlas'):
        asset=copy.deepcopy(inputs[key]);target=directory/('user-cover.png' if key=='cover' else 'functional-role-atlas.png')
        shutil.copy2(_file(asset['file']),target);asset['file']={'path':str(target),'sha256':asset['file']['sha256']}
        inputs[key]=asset
    result={'source':'media.native_user_visual_inputs','image_count':8,'scene_count':8,'assignments':assignments,
            'user_visual_materials_source':copy.deepcopy(ref),'independent_cover_record':inputs['cover'],
            'functional_role_atlas_record':inputs['functional_role_atlas']}
    (directory/'native_user_visual_inputs.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result

def bind_materialized_user_assets(plan,visual_assets,materialized):
    """Bind only a freshly reviewed assignment to the exact renderer file."""
    if not plan.get('user_visual_materials_source'):return plan
    if (visual_assets.get('source')!='media.native_user_visual_inputs'
            or visual_assets.get('user_visual_materials_source')!=plan['user_visual_materials_source']
            or len(materialized)!=8):raise ValueError('native_user_assets_not_prepared')
    result=copy.deepcopy(plan);scenes=result.get('visual_contract') or []
    if len(scenes)!=8:raise ValueError('native_user_assets_scene_count')
    atlas=visual_assets['functional_role_atlas_record'];_asset(atlas,'functional-role-atlas',True)
    for i,(scene,assignment,row) in enumerate(zip(scenes,visual_assets['assignments'],materialized)):
        pin={'path':row['path'],'sha256':assignment['sha256']};_file(pin)
        scene['body_copy']=dict(scene.get('body_copy') or {},
            real_scene_background_record=dict(pin,source_kind=assignment['source_kind']),
            functional_role_atlas_record=copy.deepcopy(atlas),functional_role_cell_index=i)
    cover=visual_assets['independent_cover_record'];_asset(cover,'cover')
    result.update(cover_background_path=cover['file']['path'],cover_background_source=cover['source_kind'],
                  independent_cover_record=copy.deepcopy(cover),functional_role_atlas_record=copy.deepcopy(atlas))
    return result
