"""Deterministic local WeChat cover title composition and real OCR admission."""
import argparse
import copy
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import os
import tempfile
import unicodedata
import shutil

from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZE=(1880,800)  # Exact 2.35:1, with enough pixels for Chinese title OCR.
# Per output size: white title panel, title start x, max line width, allowed title-box bounds, vertical band
# the lines are centred in, max total text height. Bounds sit inside cover_quality's safe zone (4%/5%/82%).
LAYOUTS={
    SIZE:{'panel':(0,0,950,800),'x':70,'width':810,'bounds':(40,40,910,760),'band':(0,800),'text_height':580},
    # Juejin/Zhihu (16:9) and Xiaohongshu (3:4): a top title band of ~30%, so the background stays the main
    # picture (cover_quality fails >45% flat near-white pixels as background_crushed_to_solid).
    (1920,1080):{'panel':(0,0,1920,330),'x':96,'width':1728,'bounds':(78,56,1842,322),'band':(56,322),'text_height':260},
    (1200,1600):{'panel':(0,0,1200,500),'x':60,'width':1080,'bounds':(50,82,1150,492),'band':(82,492),'text_height':400},
}
PLATFORM_SIZES={'wechat':SIZE,'juejin':(1920,1080),'zhihu':(1920,1080),'xiaohongshu':(1200,1600)}
FONT_FACE=2  # Installed Noto Sans CJK TTC: SC face, not default JP face 0.


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _owned_file(path,root):
    path=Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('wechat_cover_symlink_rejected')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('wechat_cover_file_missing_or_outside_job')
    return path.resolve()


def _layout(title,font_path,size_key=SIZE):
    layout=LAYOUTS[size_key];width=layout['width']
    probe=ImageDraw.Draw(Image.new('RGB',size_key))
    for size in range(96,47,-2):
        font=ImageFont.truetype(str(font_path),size,index=FONT_FACE)
        lines=[];line='';fits=True
        for phrase in re.findall(r'[^:：,，;；。.!！?？、]+[:：,，;；。.!！?？、]*',title):
            if probe.textbbox((0,0),phrase,font=font)[2]>width:
                fits=False;break
            if probe.textbbox((0,0),line+phrase,font=font)[2]>width:
                lines.append(line);line=phrase
            else:line+=phrase
        if line:lines.append(line)
        height=size+28
        if fits and len(lines)<=4 and len(lines)*height<=layout['text_height']:return font,lines,height
    raise ValueError('wechat_cover_title_overflow')


def _normalized(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))


class CoverTitleOCRError(ValueError):
    def __init__(self,evidence):
        super().__init__('wechat_cover_title_ocr_mismatch')
        self.evidence=evidence


OCR_ATTEMPTS=((7,'chi_sim+eng'),(7,'chi_sim'),(13,'chi_sim+eng'),(13,'chi_sim'))
MIN_CJK_SIMILARITY=0.9


def _folded(value):
    # Capital I and lowercase l are the same glyph in Noto Sans CJK Bold; OCR cannot tell them apart.
    return value.replace('l','I').replace('|','I')


def _title_matches(expected,text):
    """Digits/Latin must match exactly; the rendered string is ours, so the remaining tolerance only
    absorbs Tesseract glyph confusions (measured 11-01: exact match passed 15/20 correct covers)."""
    expected,text=_folded(expected),_folded(text)
    if not expected or not text:return False
    tokens=lambda value:re.findall(r'[0-9A-Za-z.%]+',value)
    return expected==text or (tokens(expected)==tokens(text) and abs(len(expected)-len(text))<=1
        and difflib.SequenceMatcher(None,expected,text).ratio()>=MIN_CJK_SIMILARITY)


def _ocr_line(path,line):
    target=_folded(_normalized(line));reads=[]
    for psm,language in OCR_ATTEMPTS:
        result=subprocess.run(['tesseract',str(path),'stdout','-l',language,'--psm',str(psm)],
                              capture_output=True,text=True,timeout=30,check=False)
        if not result.returncode:reads.append((_normalized(result.stdout or ''),psm,language))
    if not reads:return '',None
    best=max(reads,key=lambda read:difflib.SequenceMatcher(None,target,_folded(read[0])).ratio())
    return best[0],{'psm':best[1],'language':best[2]}


def _ocr(line_paths,title):
    """One crop per rendered line; whole-title comparison."""
    reads=[_ocr_line(path,line) for path,line in line_paths]
    text=''.join(read for read,_ in reads)
    target=_normalized(title)
    evidence={'checked':True,'matched':_title_matches(target,text),'text':text,
            'line_reads':[{'text':read,'attempt':attempt} for read,attempt in reads],
            'expected_normalized':target,
            'normalization':'NFKC+whitespace; I/l folded; digits/Latin exact; CJK similarity>=0.9, length +-1',
            'language':'chi_sim+eng|chi_sim','psm':[7,13]}
    if not evidence['matched']:raise CoverTitleOCRError(evidence)
    return evidence


def _top(layout,lines,line_height):
    start,end=layout['band']
    return start+(end-start-len(lines)*line_height)//2


def verify_cover_title(path,expected,proof,*,diagnostic_dir=None):
    """For trusted native render proof only; independently remeasure boxes and OCR ROI."""
    path=Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):raise ValueError('wechat_cover_symlink_rejected')
    if not isinstance(proof,dict):raise ValueError('wechat_cover_trusted_proof_required')
    if proof.get('output_sha256')!=_sha(path) or proof.get('title_text')!=expected or proof.get('renderer_sha256')!=_sha(__file__):
        raise ValueError('wechat_cover_proof_binding_invalid')
    font_path=Path(proof.get('font_path') or '')
    if not font_path.is_file() or _sha(font_path)!=proof.get('font_sha256') or proof.get('font_face')!=FONT_FACE:
        raise ValueError('wechat_cover_font_binding_invalid')
    size_key=tuple(proof.get('dimensions') or ())
    if size_key not in LAYOUTS:raise ValueError('wechat_cover_dimensions_invalid')
    layout=LAYOUTS[size_key];left,upper,right,lower=layout['bounds']
    face,lines,line_height=_layout(expected,font_path,size_key)
    top=_top(layout,lines,line_height)
    with Image.open(path) as source:
        if source.size!=size_key:raise ValueError('wechat_cover_dimensions_invalid')
        draw=ImageDraw.Draw(source)
        boxes=[list(draw.textbbox((layout['x'],top+index*line_height),line,font=face)) for index,line in enumerate(lines)]
        if boxes!=proof.get('title_boxes') or lines!=proof.get('title_lines') or any(
            box[0]<left or box[1]<upper or box[2]>right or box[3]>lower or box[0]>=box[2] or box[1]>=box[3] for box in boxes):
            raise ValueError('wechat_cover_title_box_invalid')
        roi=[min(box[0] for box in boxes)-20,min(box[1] for box in boxes)-20,
             max(box[2] for box in boxes)+20,max(box[3] for box in boxes)+20]
        with tempfile.TemporaryDirectory(prefix='.cover-ocr-',dir=path.parent) as temporary:
            roi_path=Path(temporary)/'title.png'
            source.crop(tuple(roi)).save(roi_path,format='PNG')
            line_paths=[]
            for index,(box,line) in enumerate(zip(boxes,lines)):
                line_path=Path(temporary)/f'line-{index}.png'
                source.crop((box[0]-20,box[1]-20,box[2]+20,box[3]+20)).save(line_path,format='PNG')
                line_paths.append((line_path,line))
            try:result=_ocr(line_paths,expected)
            except CoverTitleOCRError as error:
                error.evidence.update({'roi':roi,'roi_sha256':_sha(roi_path),'full_image_sha256':_sha(path)})
                if diagnostic_dir is not None:
                    directory=Path(diagnostic_dir)
                    if directory.is_symlink() or any(parent.is_symlink() for parent in directory.parents):
                        raise ValueError('wechat_cover_diagnostic_directory_untrusted') from error
                    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
                    failed=Path(tempfile.mkdtemp(prefix='ocr-failed-',dir=directory))
                    shutil.copyfile(path,failed/'cover.png');shutil.copyfile(roi_path,failed/'title-roi.png')
                    (failed/'ocr.json').write_text(json.dumps(error.evidence,ensure_ascii=False,indent=2),encoding='utf-8')
                    (failed/'render-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
                    for file in failed.iterdir():file.chmod(0o600)
                    error.evidence['diagnostic_path']=str(failed)
                raise
            result.update({'roi':roi,'roi_sha256':_sha(roi_path),'full_image_sha256':_sha(path)})
    return result


def render_wechat_cover(background_path,output_path,*,artifact_root,draft_title,
                        cover_design=None,provider_result=None,font_path=None,diagnostic_dir=None,platform='wechat'):
    """Caller supplies validated draft/config and invokes only for WeChat cover.

    Return a new path/provider result and measured cover-design facts. Caller must
    semantically review the NEW pixels, then hash/provenance/register as usual.
    """
    root=Path(artifact_root)
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise ValueError('wechat_cover_root_untrusted')
    root=root.resolve(strict=True)
    if diagnostic_dir is not None:
        diagnostic_dir=Path(diagnostic_dir)
        if diagnostic_dir.is_symlink() or any(parent.is_symlink() for parent in diagnostic_dir.parents) or not diagnostic_dir.resolve().is_relative_to(root):
            raise ValueError('wechat_cover_diagnostic_directory_outside_fixture')
    background=_owned_file(background_path,root)
    output=Path(output_path)
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents) or not output.resolve().is_relative_to(root):
        raise ValueError('wechat_cover_output_outside_job')
    if output.resolve()==background:raise ValueError('wechat_cover_background_must_be_preserved')
    design=copy.deepcopy(cover_design or {})
    for key in ('semantic_match_score','semantic_match','manual_visual_review'):
        design.pop(key,None)
    title=str(design.get('title_text') or draft_title or '').strip()
    if not title or any(ord(char)<32 for char in title):raise ValueError('wechat_cover_title_invalid')
    font=Path(font_path or '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc')
    if not font.is_file():raise ValueError('wechat_cover_local_font_missing')
    size_key=PLATFORM_SIZES[platform];layout=LAYOUTS[size_key];left,upper,right,lower=layout['bounds']
    face,lines,line_height=_layout(title,font,size_key)
    background_sha=_sha(background)
    input_sha=hashlib.sha256(json.dumps({'background_sha256':background_sha,'title':title,
        'font_sha256':_sha(font),'font_face':FONT_FACE,'renderer_sha256':_sha(__file__),
        **({} if size_key==SIZE else {'dimensions':list(size_key)})},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    proof=output.with_suffix('.render.json')
    reused=False
    if output.exists() or proof.exists():
        if proof.is_symlink() or not output.is_file() or not proof.is_file():raise ValueError('wechat_cover_output_conflict')
        evidence=json.loads(proof.read_text(encoding='utf-8'))
        if evidence.get('input_sha256')!=input_sha:raise ValueError('wechat_cover_output_conflict')
        evidence['ocr']=verify_cover_title(output,title,evidence,diagnostic_dir=diagnostic_dir)
        reused=True
    with Image.open(background) as source:
        image=ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'),size_key,method=Image.Resampling.LANCZOS)
    draw=ImageDraw.Draw(image)
    # A solid high-contrast local title panel, not a substituted AI background.
    draw.rectangle(layout['panel'],fill='#ffffff')
    top=_top(layout,lines,line_height)
    boxes=[]
    for index,line in enumerate(lines):
        position=(layout['x'],top+index*line_height)
        box=draw.textbbox(position,line,font=face)
        if box[0]<left or box[1]<upper or box[2]>right or box[3]>lower:
            raise ValueError('wechat_cover_title_overflow')
        draw.text(position,line,font=face,fill='#132b3c');boxes.append(list(box))
    output.parent.mkdir(parents=True,exist_ok=True)
    if not reused:
        with tempfile.TemporaryDirectory(prefix='.cover-render-',dir=output.parent) as temporary:
            candidate=Path(temporary)/'cover.png';image.save(candidate,format='PNG')
            evidence={'version':'wechat_cover_render_v2','background_path':str(background),
                'background_sha256':background_sha,'output_sha256':_sha(candidate),'dimensions':list(size_key),
                'font_path':str(font.resolve()),'font_sha256':_sha(font),'font_face':FONT_FACE,'title_text':title,
                'title_boxes':boxes,'title_lines':lines,'input_sha256':input_sha,'renderer_sha256':_sha(__file__)}
            evidence['ocr']=verify_cover_title(candidate,title,evidence,diagnostic_dir=diagnostic_dir)
            staged_proof=Path(temporary)/'proof.json'
            staged_proof.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            os.link(staged_proof,proof)
            try:os.link(candidate,output)
            except BaseException:
                proof.unlink(missing_ok=True)
                raise
    result=copy.deepcopy(provider_result or {})
    for key in ('semantic_match_score','semantic_match','checksum','sha256','dimensions'):
        result.pop(key,None)
    result.update({'path':str(output),'checksum':evidence['output_sha256'],
        'dimensions':list(size_key),'cover_render_evidence':evidence,
        'cover_render_evidence_path':str(proof),'requires_semantic_review':True})
    design.update({'title_text':title,'title_present':True,'title_readable':True,
                   'title_no_overflow':True,'cover_sha256':evidence['output_sha256'],
                   'title_render_evidence_sha256':_sha(proof)})
    return {'path':str(output),'provider_result':result,'cover_design':design,
            'evidence_path':str(proof),'evidence_sha256':_sha(proof)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--background',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--artifact-root',required=True);parser.add_argument('--title',required=True)
    parser.add_argument('--font')
    parser.add_argument('--diagnostic-dir',help='Explicit private technical-fixture directory; failed OCR still blocks')
    args=parser.parse_args()
    print(json.dumps(render_wechat_cover(args.background,args.output,artifact_root=args.artifact_root,
        draft_title=args.title,font_path=args.font,diagnostic_dir=args.diagnostic_dir),ensure_ascii=False))


if __name__=='__main__':main()
