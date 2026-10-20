"""Native-only measured evidence for pre-delivery WeChat phase gates."""
import hashlib
import html
import json
import re
from pathlib import Path
from html.parser import HTMLParser


class _VisibleArticle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.stack=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs);style=(values.get('style') or '').replace(' ','').lower()
        hidden=bool(self.stack and self.stack[-1][1]) or tag in {'head','script','style','template'} or 'hidden' in values or any(value in style for value in ('display:none','visibility:hidden','opacity:0','font-size:0'))
        if tag not in {'img','br','hr','meta','link','input','source','wbr'}:self.stack.append((tag,hidden))
        if not hidden and tag in {'p','div','section','h1','h2','h3','h4','h5','h6','li','br'}:self.parts.append('\n')
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                hidden=self.stack[index][1];del self.stack[index:]
                if not hidden and tag in {'p','div','section','h1','h2','h3','h4','h5','h6','li'}:self.parts.append('\n')
                break
    def handle_data(self,data):
        if not self.stack or not self.stack[-1][1]:self.parts.append(data)


def _visible_parts(value):
    parser=_VisibleArticle();parser.feed(value);parser.close()
    return ''.join(parser.parts)


def _source_paragraphs(value):
    if re.search(r'<(?:p|div|section|h[1-6])\b',value,re.I):value=_visible_parts(value)
    value=re.sub(r'!\[[^]]*\]\([^)]*\)','',value)
    value=re.sub(r'\[([^]]+)\]\([^)]*\)',r'\1',value)
    value=re.sub(r'^\s*#{1,6}\s+','',value,flags=re.M)
    value=re.sub(r'^\s*[-*]\s+','',value,flags=re.M)
    value=re.sub(r'(\*\*|__|`)(.*?)\1',r'\2',value)
    return [''.join(part.split()) for part in re.split(r'\n\s*\n|\n',value) if part.strip()]


def _narrative_matches(source,rendered):
    visible=''.join(_visible_parts(rendered).split());cursor=0
    paragraphs=_source_paragraphs(source)
    if not paragraphs:return False
    for paragraph in paragraphs:
        position=visible.find(paragraph,cursor)
        if position<0:return False
        cursor=position+len(paragraph)
    return True


def _knowledge_card_html(renderer, section, paragraphs, background, index):
    from urllib.parse import quote
    card={'type':'content','heading':html.escape(section,quote=True),
          'body':[html.escape(value,quote=True) for value in paragraphs]}
    value=renderer.render_card_html(card,index+1,renderer.PALETTES[index%len(renderer.PALETTES)],
                                    'hero',quote(background.as_posix(),safe='/:'),4)
    value=re.sub(r'@import\s+url\([^)]*\)\s*;','',value)
    value=value.replace('<head>','<head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src file:; style-src \'unsafe-inline\'; font-src \'none\'; script-src \'none\'">')
    return value


def _capture_knowledge_card(page, path):
    from playwright.sync_api import Error
    card=page.locator('.card')
    if card.count()!=1:raise ValueError('knowledge_card_container_not_unique')
    card.wait_for(state='visible',timeout=15000)
    for attempt in range(2):
        card.evaluate(r"""async (element) => {
            await document.fonts.ready;
            const background = getComputedStyle(element).backgroundImage;
            const match = /^url\([\"']?(.*?)[\"']?\)$/.exec(background);
            if (!match) throw new Error('knowledge_card_background_missing');
            const image = new Image(); image.src = match[1];
            let timer;
            try {
                await Promise.race([image.decode(), new Promise((_, reject) => {
                    timer = setTimeout(() => reject(new Error('knowledge_card_background_decode_timeout')), 10000);
                })]);
            } finally { clearTimeout(timer); }
            if (!image.naturalWidth || !image.naturalHeight)
                throw new Error('knowledge_card_background_not_decoded');
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""",timeout=15000)
        try:
            card.screenshot(path=str(path),timeout=15000,animations='disabled')
            return
        except Error as exc:
            if attempt or 'Page.captureScreenshot' not in str(exc) or 'Unable to capture screenshot' not in str(exc):
                raise


def render_wechat_knowledge_cards(store,data_dir,job_id,draft,config):
    """Execute the installed content-card renderer; never use its cover/CTA or search."""
    import importlib.util
    from .paths import agent_home,agent_scripts_dir
    manifest=(draft.get('draft_meta') or {}).get('tool_invocation_manifest') or {}
    if 'knowledge_card_designer' not in (manifest.get('planned_tools') or {}):
        return {'selected':False}
    cfg=(config.get('media') or {}).get('knowledge_cards') or {}
    renderer_path=Path(cfg.get('renderer_path') or agent_scripts_dir()/'wechat_image_post_cards_v2.py')
    skill_path=Path(cfg.get('skill_path') or agent_home()/'skills/content/knowledge-card-designer/SKILL.md')
    if not renderer_path.is_file() or not skill_path.is_file():raise ValueError('knowledge_card_runtime_missing')
    spec=importlib.util.spec_from_file_location('_native_content_cards',renderer_path)
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    root=(Path(data_dir)/'artifacts'/str(job_id)).resolve(strict=True)
    mapping=root/'section_image_map.json'
    if not mapping.is_file():mapping=root/'cards/section_image_map.json'
    rows=json.loads(mapping.read_text(encoding='utf-8'))
    images={row['checksum']:row for row in store.artifacts(job_id) if row['kind']=='image'}
    sections=dict(renderer.split_sections(str(draft.get('body') or ''),str(draft.get('title') or '')))
    plans=[]
    for row in rows[:3]:
        section=str(row.get('section') or '')
        paragraphs=sections.get(section)
        artifact=images.get(row.get('asset_hash'))
        if not paragraphs or not artifact:raise ValueError('knowledge_card_section_binding_missing')
        background=Path(artifact['path'])
        if background.is_symlink() or any(p.is_symlink() for p in background.parents):raise ValueError('knowledge_card_background_untrusted')
        background=background.resolve(strict=True)
        if not background.is_relative_to(root) or hashlib.sha256(background.read_bytes()).hexdigest()!=artifact['checksum']:
            raise ValueError('knowledge_card_background_changed')
        # Complete reviewed paragraphs, not generated summaries or fabricated claims.
        plans.append((section,paragraphs[:1],background))
    if len(plans)!=3:raise ValueError('knowledge_card_sections_missing')
    output=root/'knowledge_cards';output.mkdir(exist_ok=True)
    if output.is_symlink():raise ValueError('knowledge_card_output_untrusted')
    proof={'skill_sha256':hashlib.sha256(skill_path.read_bytes()).hexdigest(),
           'renderer_sha256':hashlib.sha256(renderer_path.read_bytes()).hexdigest(),'cards':[]}
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(args=['--no-sandbox'])
        try:
            page=browser.new_page(viewport={'width':renderer.CARD_W,'height':renderer.CARD_H},device_scale_factor=1)
            for index,(section,paragraphs,background) in enumerate(plans):
                document=output/f'card_{index+1}.html';png=output/f'card_{index+1}.png'
                value=_knowledge_card_html(renderer,section,paragraphs,background,index)
                document.write_text(value,encoding='utf-8')
                allowed={document.as_uri(),background.as_uri()}
                page.route('**/*',lambda route:route.continue_() if route.request.url in allowed else route.abort())
                page.goto(document.as_uri(),wait_until='load');page.evaluate('document.fonts.ready')
                if page.locator('.content').evaluate('(e)=>e.scrollHeight>e.clientHeight'):
                    raise ValueError('knowledge_card_text_overflow')
                _capture_knowledge_card(page,png);page.unroute('**/*')
                from PIL import Image
                with Image.open(png) as image:
                    image.verify()
                checksum=hashlib.sha256(png.read_bytes()).hexdigest()
                store.add_artifact(job_id,'knowledge_card',png,checksum)
                store.add_artifact(job_id,'knowledge_card_html',document,hashlib.sha256(document.read_bytes()).hexdigest())
                proof['cards'].append({'section':section,'path':str(png),'sha256':checksum,
                    'html_sha256':hashlib.sha256(document.read_bytes()).hexdigest(),
                    'input_sha256':hashlib.sha256(json.dumps({'section':section,'paragraphs':paragraphs,'background_sha256':hashlib.sha256(background.read_bytes()).hexdigest()},ensure_ascii=False,sort_keys=True).encode()).hexdigest()})
        finally:browser.close()
    proof_path=output/'execution.json';proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    draft['draft_meta']['rendered_knowledge_cards']=proof['cards']
    manifest.setdefault('invocations',{})['knowledge_card_designer']={'status':'generated','output':str(proof_path),
        'sha256':hashlib.sha256(proof_path.read_bytes()).hexdigest(),**proof}
    return proof


def render_wechat_local_article(store,data_dir,job_id,draft,config):
    """Run the original renderer after native section assets exist."""
    from .gzh_design import format_for_wechat,validate_html
    from .theme_registry import select_theme,resolve_wechat_theme
    root=Path(data_dir)/'artifacts'/str(job_id)
    mapping=root/'section_image_map.json'
    if not mapping.is_file():mapping=root/'cards/section_image_map.json'
    if mapping.is_symlink():raise ValueError('wechat_local_mapping_untrusted')
    rows=json.loads(mapping.read_text(encoding='utf-8'))
    images={row.get('checksum'):row for row in store.artifacts(job_id) if row.get('kind')=='image'}
    body=str(draft.get('body') or '')
    # Existing native article fixtures can be HTML. Convert layout to Markdown
    # without trusting provider image URLs; actual images come from Store below.
    body=re.sub(r'<h([1-6])\b[^>]*>(.*?)</h\1>',lambda match:'\n'+'#'*int(match.group(1))+' '+re.sub(r'<[^>]+>','',match.group(2))+'\n',body,flags=re.I|re.S)
    body=re.sub(r'<img\b[^>]*>','',body,flags=re.I)
    body=re.sub(r'</(?:p|div|section)>','\n\n',body,flags=re.I)
    body=html.unescape(re.sub(r'<[^>]+>','',body))
    headings=list(re.finditer(r'^#{1,6}\s+(.+)$',body,re.M))
    if len(rows)<3 or len(headings)<3:raise ValueError('wechat_local_section_assets_missing')
    inserts=[]
    for index,row in enumerate(rows):
        artifact=images.get(row.get('asset_hash'))
        if not artifact or index>=len(headings):raise ValueError('wechat_local_section_binding_missing')
        path=Path(artifact['path']).resolve(strict=True)
        if not path.is_relative_to(root.resolve(strict=True)) or hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['checksum']:
            raise ValueError('wechat_local_section_asset_changed')
        labels=[str(row.get('adjacent_to_text') or ''),str(row.get('section') or '')]
        matches=[item for item in headings if item.group(1).strip() in labels]
        if len(matches)!=1:raise ValueError('wechat_local_section_anchor_missing_or_ambiguous')
        heading=matches[0]
        inserts.append((heading.end(),'\n\n![]('+path.as_posix()+')\n'))
    registered={row['checksum']:row for row in store.artifacts(job_id) if row['kind']=='knowledge_card'}
    for card in (draft.get('draft_meta') or {}).get('rendered_knowledge_cards',[]):
        artifact=registered.get(card.get('sha256'))
        matches=[item for item in headings if item.group(1).strip()==card.get('section')]
        if not artifact or len(matches)!=1:raise ValueError('knowledge_card_embedding_binding_missing')
        path=Path(artifact['path']).resolve(strict=True)
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=card['sha256']:
            raise ValueError('knowledge_card_embedding_changed')
        inserts.append((matches[0].end(),'\n\n![]('+path.as_posix()+')\n'))
    for offset,image in sorted(inserts,reverse=True):body=body[:offset]+image+body[offset:]
    selection=select_theme('wechat',str(draft.get('title') or '')+' '+body,
                           str((draft.get('draft_meta') or {}).get('content_form') or 'article'),
                           (draft.get('draft_meta') or {}).get('recent_theme_ids') or [])
    cfg=(config.get('media') or {}).get('wechat_format') or {}
    theme=cfg.get('default_theme') or resolve_wechat_theme(selection)
    output=root/'wechat_review.html'
    result=format_for_wechat(markdown='# '+str(draft.get('title') or '')+'\n\n'+body,
                             theme=theme,title=str(draft.get('title') or ''),output_path=str(output))
    produced=Path(result.get('html_path') or '')
    if not result.get('ok') or not produced.is_file():
        raise ValueError('wechat_native_local_renderer_failed')
    if produced.is_symlink() or not produced.resolve().is_relative_to(root.resolve(strict=True)):
        raise ValueError('wechat_native_local_renderer_output_untrusted')
    # The original renderer uses 15px prose while the native gate requires 16px.
    # Correct the actual output, then rerun the unchanged native skill validator.
    rendered=produced.read_text(encoding='utf-8')
    rendered=re.sub(r'(font-size\s*:\s*)15px',r'\g<1>16px',rendered,flags=re.I)
    output.write_text(rendered,encoding='utf-8')
    if validate_html(str(output)).get('ok') is not True:raise ValueError('wechat_native_local_renderer_validation_failed')
    for card in (draft.get('draft_meta') or {}).get('rendered_knowledge_cards',[]):
        if not re.search(r'<img\b[^>]*\bsrc=["\x27][^"\x27]*'+re.escape(Path(card['path']).name)+r'[^"\x27]*["\x27]',rendered,re.I):
            raise ValueError('knowledge_card_not_embedded_in_article')
    mapping.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    store.add_artifact(job_id,'wechat_format',output,hashlib.sha256(output.read_bytes()).hexdigest())
    return {'path':str(output),'theme':theme,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}


def _measure_cover_title_review(evidence,actual,title,dimensions):
    import math
    import unicodedata
    render=evidence.get('cover_render_evidence') or {}
    ocr=render.get('ocr') or {}
    semantic=evidence.get('semantic_review') or {}
    execution=semantic.get('execution') or {}
    score=semantic.get('score')
    boxes=render.get('title_boxes') or []
    expected=re.sub(r'\s+','',unicodedata.normalize('NFKC',title))
    valid=(render.get('output_sha256')==actual and render.get('title_text')==title
        and render.get('dimensions')==list(dimensions) and dimensions[0]*100==dimensions[1]*235
        and bool(render.get('background_sha256')) and bool(render.get('font_sha256')) and render.get('font_face')==2 and bool(render.get('renderer_sha256'))
        and bool(boxes) and all(isinstance(box,list) and len(box)==4
            and all(type(value) in (int,float) and math.isfinite(value) for value in box)
            and 0<=box[0]<box[2]<=dimensions[0] and 0<=box[1]<box[3]<=dimensions[1] for box in boxes)
        and ocr.get('checked') is True and ocr.get('matched') is True and ocr.get('returncode')==0
        and ocr.get('language')=='chi_sim+eng' and ocr.get('psm')==6
        and bool(expected) and expected==re.sub(r'\s+','',unicodedata.normalize('NFKC',str(ocr.get('text') or '')))
        and ocr.get('full_image_sha256')==actual and bool(ocr.get('roi_sha256'))
        and isinstance(ocr.get('roi'),list) and len(ocr['roi'])==4
        and all(type(value) is int for value in ocr['roi'])
        and 0<=ocr['roi'][0]<ocr['roi'][2]<=dimensions[0] and 0<=ocr['roi'][1]<ocr['roi'][3]<=dimensions[1]
        and semantic.get('status')=='evaluated' and semantic.get('image_sha256')==actual
        and semantic.get('image_observed') is True and type(score) in (int,float) and math.isfinite(score) and .72<=score<=1
        and bool(execution.get('session_id')) and execution.get('tool_call_count')==0 and execution.get('api_call_count')==1)
    return {'passed':bool(valid),'cover_sha256':actual,'title_text':title,
            'auto_visual_review':{'passed':bool(valid),'semantic_score':score,'session_id':execution.get('session_id')},
            'human_approval_asserted':False}


def measure_wechat_local_assets(store, data_dir, job_id, draft):
    root=Path(data_dir)/'artifacts'/str(job_id)
    failures=[];counts={'cover':0,'image':0};checksums={};image_paths=[];probe={};cover_review={}
    try:
        if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):raise ValueError('symlink')
        root=root.resolve(strict=True)
        provenance_path=root/'asset_provenance.json'
        if provenance_path.is_symlink():raise ValueError('symlink')
        provenance=json.loads(provenance_path.read_text(encoding='utf-8'))
        rows={str(Path(row['path']).resolve()):row for row in provenance.get('assets',[])}
        for artifact in store.artifacts(job_id):
            kind=artifact.get('kind')
            if kind not in counts:continue
            path=Path(artifact['path'])
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):raise ValueError('symlink')
            path=path.resolve(strict=True)
            if not path.is_relative_to(root):raise ValueError('outside artifact root')
            actual=hashlib.sha256(path.read_bytes()).hexdigest()
            if actual!=artifact.get('checksum'):raise ValueError('checksum')
            from PIL import Image
            with Image.open(path) as image:image.verify()
            evidence=rows.get(str(path),{})
            if not evidence.get('source_url') or not evidence.get('license') or float(evidence.get('semantic_match_score') or 0)<0.72:
                raise ValueError('provenance')
            if kind=='cover':
                with Image.open(path) as image:dimensions=image.size
                title=str((draft.get('draft_meta') or {}).get('cover_design',{}).get('title_text') or draft.get('title') or '').strip()
                cover_review=_measure_cover_title_review(evidence,actual,title,dimensions)
                if not cover_review['passed']:raise ValueError('cover_title_or_semantic_binding_invalid')
            counts[kind]+=1;checksums[str(path)]=actual
            if kind=='image':image_paths.append(str(path))
        mapping=root/'section_image_map.json'
        if not mapping.is_file():mapping=root/'cards/section_image_map.json'
        if mapping.is_symlink() or any(parent.is_symlink() for parent in mapping.parents):raise ValueError('symlink')
        mappings=json.loads(mapping.read_text(encoding='utf-8'))
        if not isinstance(mappings,list) or len(mappings)<3:raise ValueError('mapping')
        if any(not isinstance(row,dict) for row in mappings):raise ValueError('mapping')
        if len({row.get('section') for row in mappings})!=len(mappings) or len({row.get('asset_hash') for row in mappings})!=len(mappings):
            raise ValueError('duplicate section or image binding')
        for row in mappings:
            if not row.get('section') or row.get('asset_hash') not in checksums.values():raise ValueError('mapping binding')
        manifest_path=root/'article_artifact_manifest.json'
        if manifest_path.is_symlink():raise ValueError('symlink')
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        packet_hash=hashlib.sha256(json.dumps({'title':draft.get('title'),'body':draft.get('body')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if str(manifest.get('job_id') or '')!=str(job_id) or manifest.get('binding',{}).get('packet_hash')!=packet_hash:
            raise ValueError('copy binding')
        html_rows=[row for row in store.artifacts(job_id) if row.get('kind')=='wechat_format']
        html_rows=[row for row in html_rows if Path(row['path']).name=='wechat_review.html']
        if len(html_rows)!=1:raise ValueError('formatted HTML missing')
        html_path=Path(html_rows[0]['path'])
        if html_path.is_symlink() or any(parent.is_symlink() for parent in html_path.parents) or not html_path.resolve().is_relative_to(root):raise ValueError('formatted HTML untrusted')
        if hashlib.sha256(html_path.read_bytes()).hexdigest()!=html_rows[0].get('checksum'):
            raise ValueError('formatted HTML changed')
        rendered=html_path.read_text(encoding='utf-8')
        if not _narrative_matches(str(draft.get('title') or '')+'\n\n'+str(draft.get('body') or ''),rendered):
            raise ValueError('rendered article narrative missing or reordered')
        sources=re.findall(r'<img\b[^>]*\bsrc=["\x27]([^"\x27]+)',rendered,re.I)
        linked=0
        for row in mappings:
            paths=[path for path in image_paths if checksums[path]==row.get('asset_hash')]
            if len(paths)!=1:raise ValueError('section image binding')
            target=Path(paths[0]).name
            tag=re.search(r'<img\b[^>]*\bsrc=["\x27][^"\x27]*'+re.escape(target)+r'[^"\x27]*["\x27]',rendered,re.I)
            label=str(row.get('adjacent_to_text') or row.get('section') or '')
            if tag and label and label in rendered[max(0,tag.start()-1500):tag.start()]:linked+=1
        from .media_quality import _text_length
        prose_styles=[value for value in re.findall(r'<(?:section|p)\b[^>]*style=["\x27]([^"\x27]*)',rendered,re.I) if 'line-height' in value]
        prose_styles.extend(re.findall(r'body\s*\{([^}]*)\}',rendered,re.I))
        font_sizes=[int(value) for style in prose_styles for value in re.findall(r'font(?:-size)?\s*:[^;{}]*?([0-9]+)px',style,re.I)]
        probe={'word_count':_text_length(_visible_parts(rendered)),
               'inline_image_count':len(sources),'adjacent_inline_image_count':linked,
               'theme_css_inlined':bool(re.search(r'(?:style=["\x27]|<style\b)',rendered,re.I)),
               'body_font_px':min(font_sizes) if font_sizes else 0}
        if not (1200<=probe['word_count']<=3000 and len(sources)>=3 and linked>=3
                and probe['theme_css_inlined'] and probe['body_font_px']>=16):raise ValueError('rendered article metrics')
    except (OSError,ValueError,KeyError,TypeError):failures.append('local_assets_or_provenance_invalid')
    if counts['cover']<1:failures.append('cover_missing')
    if counts['image']<3:failures.append('inline_images_missing')
    return {'passed':not failures,'failures':failures,'counts':counts,'checksums':checksums,'article_probe':probe,'cover_title_review':cover_review}


def read_wechat_delivery_evidence(data_dir,job_id,external_id):
    root=Path(data_dir)/'runtime/wechat_adapter'/str(job_id)
    try:
        path=root/'result.json'
        if path.is_symlink():raise ValueError('symlink')
        result=json.loads(path.read_text(encoding='utf-8'))
        proof=Path(result.get('evidence_path') or '')
        if proof.is_symlink() or any(parent.is_symlink() for parent in proof.parents):raise ValueError('symlink')
        proof=proof.resolve(strict=True)
        if not proof.is_relative_to(root.resolve(strict=True)):raise ValueError('outside receipt root')
        evidence=json.loads(proof.read_text(encoding='utf-8'))
        return {'passed':result.get('ok') is True and str(result.get('media_id') or result.get('external_id') or '')==str(external_id)
                and bool(external_id) and result.get('postcheck',{}).get('passed') is True
                and evidence.get('postcheck',{}).get('passed') is True and evidence.get('cover_uploaded') is True
                and int(evidence.get('inline_image_count') or 0)>=3,
                'cover_uploaded':evidence.get('cover_uploaded') is True,
                'postcheck':result.get('postcheck') or {},'external_id':str(external_id)}
    except (OSError,ValueError,TypeError):return {'passed':False,'failure':'native_delivery_receipt_missing_or_invalid'}
