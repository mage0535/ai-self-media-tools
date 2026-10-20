"""Exact native WeChat HTML revision; explicit assets, no private log packaging."""
import base64
import hashlib
import html
from html.parser import HTMLParser
from pathlib import Path
import re
import json
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

MAX_HTML = 24 * 1024 * 1024
IMAGE_ROLES = {'cover', 'image', 'knowledge_card'}
RENDERER_SHA256 = '2f01d5d48afdf41c291790601a974703fa1e88b743804118cec1668fc902f3e2'
IMG = re.compile(r'(<img\b[^>]*?(?<![\w:-])src\s*=\s*)(["\x27])(.*?)(\2)', re.I | re.S)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SafeArticle(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag.lower() in {'script','iframe','object','embed','form','input','base','link'}:
            raise ValueError('native_article_active_content_forbidden')
        names=[key.lower() for key,_ in attrs]
        if len(names)!=len(set(names)) or tag.lower()=='img' and names.count('src')!=1:
            raise ValueError('native_article_duplicate_or_missing_attribute')
        for key,value in attrs:
            if key.lower().startswith('on') or key.lower() in {'srcdoc','srcset'}:
                raise ValueError('native_article_active_attribute_forbidden')
            if value and ('javascript:' in value.casefold() or key.lower() == 'style' and re.search(r'url\s*\(',value,re.I)):
                raise ValueError('native_article_external_active_content_forbidden')


def safe_html(text):
    if not isinstance(text,str) or not text.strip() or len(text.encode()) > MAX_HTML:
        raise ValueError('native_article_html_missing_or_oversize')
    parser=SafeArticle(convert_charrefs=True);parser.feed(text);parser.close()
    if re.search(r'<style\b[^>]*>.*?(?:@import|url\s*\()',text,re.I|re.S):
        raise ValueError('native_article_external_css_forbidden')
    if '.private.' in text or 'semantic_review' in text:
        raise ValueError('native_article_private_audit_forbidden')


def bound_file(row, root):
    path=Path(row['path'])
    if not isinstance(row.get('artifact_id'),int) or not row['artifact_id'] or not path.is_absolute():
        raise ValueError('native_article_artifact_identity_missing')
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('native_article_artifact_path_unsafe')
    if '.private.' in path.name or path.suffix.lower() not in {'.html','.png','.jpg','.jpeg','.webp'}:
        raise ValueError('native_article_artifact_type_forbidden')
    data=path.read_bytes()
    if sha(data)!=row.get('checksum'):
        raise ValueError('native_article_artifact_changed')
    return path,data


def from_bundle(bundle, data_dir, media_id):
    rows=bundle.get('artifacts') or []
    articles=[row for row in rows if row.get('role')=='article_html']
    if not articles:
        if any(row.get('role')=='knowledge_card' for row in rows):
            raise ValueError('native_article_html_binding_missing')
        return None  # Previously reviewed legacy packets retain their old path.
    if bundle.get('ready') is not True or bundle.get('platform')!='wechat' or len(articles)!=1:
        raise ValueError('native_article_revision_not_ready_or_ambiguous')
    revision=bundle.get('content_revision')
    if not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{64}',revision):
        raise ValueError('native_article_revision_missing')
    root=Path(data_dir)/'artifacts'/media_id
    article,raw=bound_file(articles[0],root)
    text=raw.decode('utf-8');safe_html(text)
    assets={}
    cards=[]
    for row in rows:
        if row.get('role') not in IMAGE_ROLES:continue
        path,data=bound_file(row,root)
        if row['role']=='knowledge_card':
            if path.suffix.lower()!='.png' or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('native_knowledge_card_not_png')
            cards.append(row['checksum'])
        assets[str(path.resolve())]={'artifact_id':row['artifact_id'],'role':row['role'],
                                   'path':str(path),'sha256':row['checksum']}
    if len(set(cards))<3:raise ValueError('native_knowledge_cards_incomplete')
    references=[]
    for match in IMG.finditer(text):
        src=html.unescape(match[3]);parsed=urlparse(src)
        if parsed.scheme not in {'','file'} or parsed.netloc:
            raise ValueError('native_article_unbound_image_source')
        path=Path(url2pathname(parsed.path) if parsed.scheme=='file' else unquote(parsed.path))
        if not path.is_absolute():path=article.parent/path
        asset=assets.get(str(path.resolve()))
        if asset is None:raise ValueError('native_article_image_not_bound')
        references.append(dict(asset,src=src))
    if not set(cards).issubset({row['sha256'] for row in references}):
        raise ValueError('native_article_knowledge_card_not_in_html')
    result={'schema':'wechat_native_article_v1','content_revision':revision,
            'artifact_id':articles[0]['artifact_id'],'source_sha256':sha(raw),'html':text,
            'images':references}
    covers=[row for row in rows if row.get('role')=='cover']
    if len(covers)!=1:raise ValueError('native_article_bound_cover_ambiguous')
    cover=covers[0]
    proof=(cover.get('provenance') or {}).get('cover_render_evidence')
    provenance_path=root/'asset_provenance.json'
    if provenance_path.exists():
        if provenance_path.is_symlink() or provenance_path.stat().st_size>2*1024*1024:
            raise ValueError('native_cover_provenance_untrusted')
        provenance=json.loads(provenance_path.read_text(encoding='utf-8'))
        records=[row for row in provenance.get('assets',[]) if row.get('path')==cover['path'] and row.get('sha256')==cover['checksum']]
        if len(records)>1:raise ValueError('native_cover_provenance_ambiguous')
        file_proof=records[0].get('cover_render_evidence') if records else None
        if proof is not None and file_proof is not None and proof!=file_proof:
            raise ValueError('native_cover_proof_conflict')
        proof=proof if proof is not None else file_proof
    if proof is not None:
        if not isinstance(proof,dict) or proof.get('output_sha256')!=cover['checksum'] or proof.get('renderer_sha256')!=RENDERER_SHA256:
            raise ValueError('native_cover_render_binding_invalid')
        title=str(bundle['copy']['content'].get('title') or '').strip()
        if proof.get('title_text')!=title:raise ValueError('native_cover_actual_article_title_mismatch')
        keys=('version','background_sha256','output_sha256','dimensions','font_path','font_sha256','font_face',
              'title_text','title_boxes','title_lines','input_sha256','renderer_sha256')
        result['cover_render_evidence']={key:proof[key] for key in keys if key in proof}
        result['cover_artifact_id']=cover['artifact_id']
        result['cover_sha256']=cover['checksum']
    return result


def bind_packet(packet, bundle, data_dir, media_id, expected_revision=None):
    """Both review hashing and publish transport use this verified binding."""
    if 'native_article' in packet:raise ValueError('caller_native_article_not_admitted')
    native=from_bundle(bundle,data_dir,media_id)
    if native is None:
        if 'native_article' in packet:raise ValueError('unverified_native_article_field')
        return packet,None
    if expected_revision is not None and native['content_revision']!=expected_revision:
        raise ValueError('approved_native_revision_changed')
    if packet.get('platform_payload')!=bundle['copy']['content']:
        raise ValueError('native_article_platform_copy_changed')
    packet=strip_private(json.loads(json.dumps(packet)))
    rows=[row for row in bundle['artifacts'] if row['role'] in IMAGE_ROLES]
    covers=[row for row in rows if row['role']=='cover']
    if len(covers)!=1:raise ValueError('native_article_bound_cover_ambiguous')
    cover=covers[0]
    # The authoritative role/artifact ID selects the cover, not a basename or
    # generator plan hash. Pixel provenance stays in its existing audit record.
    packet['cover_design']=dict(packet.get('cover_design') or {},path=cover['path'],asset_hash=cover['checksum'])
    images=[row for row in rows if row['role']=='image']
    # The model draft's old section map is a plan, not produced-asset evidence.
    # Read the fixed native mapping emitted beside the bound article, then bind
    # every entry to this verified revision's image artifacts by actual hash.
    map_path=Path(data_dir)/'artifacts'/media_id/'section_image_map.json'
    if map_path.is_symlink() or not map_path.is_file() or map_path.stat().st_size>2*1024*1024:
        raise ValueError('native_article_authoritative_mapping_missing')
    raw_map=map_path.read_bytes()
    mappings=json.loads(raw_map)
    if not isinstance(mappings,list) or len(mappings)<3:
        raise ValueError('native_article_section_mapping_missing')
    for item in mappings:
        matches=[row for row in images if row['checksum']==item.get('asset_hash')]
        if len(matches)!=1:raise ValueError('native_article_section_hash_missing_or_ambiguous')
        declared=str(item.get('image') or '')
        if Path(declared).is_absolute() and Path(declared)!=Path(matches[0]['path']):
            raise ValueError('native_article_section_path_conflict')
        item['image']=matches[0]['path']
        if 'path' in item:item['path']=matches[0]['path']
        if matches[0]['checksum'] not in {row['sha256'] for row in native['images']}:
            raise ValueError('native_article_section_not_in_bound_html')
    packet['section_image_map']=strip_private(mappings)
    native['section_map_sha256']=sha(raw_map)
    by_id={row['artifact_id']:row for row in rows}
    assets=[]
    for item in packet.get('artifacts') or []:
        if item.get('kind') in {'cover','cover_image','image','knowledge_card'}:
            bound=by_id.get(item.get('id'))
            if bound is None:raise ValueError('native_article_packet_image_unowned')
            item=dict(item,path=bound['path'],checksum=bound['checksum'])
        assets.append(item)
    packet['artifacts']=assets
    return packet,native


def replace_sources(text, replacements):
    seen=set()
    def replace(match):
        src=html.unescape(match[3])
        if src not in replacements:raise ValueError('native_article_image_replacement_missing')
        seen.add(src)
        return match[1]+match[2]+html.escape(replacements[src],quote=True)+match[4]
    result=IMG.sub(replace,text)
    if set(replacements)!=seen:raise ValueError('native_article_unused_image_replacement')
    return result


def review_bytes(article):
    replacements={}
    for row in article['images']:
        path=Path(row['path']);data=path.read_bytes()
        if path.is_symlink() or sha(data)!=row['sha256']:raise ValueError('native_article_review_asset_changed')
        mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}[path.suffix.lower()]
        replacements[row['src']]='data:'+mime+';base64,'+base64.b64encode(data).decode('ascii')
    text=replace_sources(article['html'],replacements)
    csp='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
    if re.search(r'<html\b[^>]*>',text,re.I):
        if re.search(r'<head\b[^>]*>',text,re.I):
            text=re.sub(r'(<head\b[^>]*>)',lambda m:m[1]+csp,text,count=1,flags=re.I)
        else:
            head='<head><meta charset="utf-8">'+csp+'</head>'
            text=re.sub(r'(<html\b[^>]*>)',lambda m:m[1]+head,text,count=1,flags=re.I)
        text=text.lstrip('\ufeff \t\r\n')
        doctype=re.match(r'<!doctype\s+html\b[^>]*>',text,re.I)
        text='<!doctype html>'+text[doctype.end():] if doctype else '<!doctype html>'+text
    else:
        text='<!doctype html><html><head><meta charset="utf-8">'+csp+'</head><body>'+text+'</body></html>'
    data=text.encode('utf-8')
    if len(data)>MAX_HTML:raise ValueError('native_article_review_oversize')
    return data


def context_summary(article):
    # Never put HTML/base64 into a model context. Attachments carry the full view.
    text=re.sub(r'<style\b[^>]*>.*?</style>','',article['html'],flags=re.I|re.S)
    text=html.unescape(re.sub(r'<[^>]+>',' ',text))
    text=re.sub(r'\s+',' ',text).strip()[:300]
    return '微信原生排版送审，尚未发布。正文摘要：'+text+'；修订：'+article['content_revision']+'；附件含原生排版及已绑定知识卡。'


def strip_private(value):
    if isinstance(value,dict):
        return {key:strip_private(item) for key,item in value.items() if key not in {'semantic_review','stdout','stderr','process_log','provider_result'}}
    if isinstance(value,list):return [strip_private(item) for item in value]
    if isinstance(value,str) and '.private.' in value:raise ValueError('private_audit_reference_in_packet')
    return value


def validate_transport(article):
    if not isinstance(article,dict) or article.get('schema')!='wechat_native_article_v1' or not re.fullmatch('[a-f0-9]{64}',str(article.get('content_revision',''))):
        raise ValueError('native_article_bound_contract_invalid')
    if sha(str(article.get('html','')).encode())!=article.get('transport_sha256'):
        raise ValueError('native_article_transport_changed')
    safe_html(article['html'])
    images=article.get('images')
    if not isinstance(images,list) or not 3<=len(images)<=64:
        raise ValueError('native_article_bound_images_invalid')
    replacements={}
    for row in images:
        path=Path(row['path'])
        if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file() or sha(path.read_bytes())!=row.get('sha256'):
            raise ValueError('native_article_publish_asset_changed')
        if row['src'] in replacements and replacements[row['src']]!=row['path']:
            raise ValueError('native_article_source_binding_ambiguous')
        replacements[row['src']]=row['path']
    replace_sources(article['html'],replacements)


def publication_html(article, upload_image):
    """No body/CSS transformation is permitted at the old endpoint."""
    validate_transport(article)
    replacements={}
    for row in article['images']:
        if row['src'] in replacements:continue
        path=Path(row['path']);data=path.read_bytes()
        if path.is_symlink() or sha(data)!=row['sha256']:raise ValueError('native_article_publish_asset_changed')
        url=upload_image(path)
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in {'mmbiz.qpic.cn','mmbiz.qlogo.cn'}:
            raise ValueError('native_article_platform_image_url_invalid')
        replacements[row['src']]=url
    # No rendering, generation, copy rewrite or inferred HTML asset selection.
    return replace_sources(article['html'],replacements),list(replacements.values())


def publish_exact_html(article, upload_image, create_draft):
    """Old credential-owning adapter supplies the two actual API functions."""
    text,_=publication_html(article,upload_image)
    return create_draft(text)
