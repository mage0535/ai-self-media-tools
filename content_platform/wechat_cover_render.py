"""Deterministic local WeChat cover title composition and real OCR admission."""
import argparse
import copy
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


def _layout(title,font_path):
    probe=ImageDraw.Draw(Image.new('RGB',SIZE))
    for size in range(96,47,-2):
        font=ImageFont.truetype(str(font_path),size,index=FONT_FACE)
        lines=[];line='';fits=True
        for phrase in re.findall(r'[^:：,，;；。.!！?？、]+[:：,，;；。.!！?？、]*',title):
            if probe.textbbox((0,0),phrase,font=font)[2]>810:
                fits=False;break
            if probe.textbbox((0,0),line+phrase,font=font)[2]>810:
                lines.append(line);line=phrase
            else:line+=phrase
        if line:lines.append(line)
        height=size+28
        if fits and len(lines)<=4 and len(lines)*height<=580:return font,lines,height
    raise ValueError('wechat_cover_title_overflow')


def _normalized(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))


class CoverTitleOCRError(ValueError):
    def __init__(self,evidence):
        super().__init__('wechat_cover_title_ocr_mismatch')
        self.evidence=evidence


def _ocr(path,title):
    result=subprocess.run(['tesseract',str(path),'stdout','-l','chi_sim+eng','--psm','6'],
                          capture_output=True,text=True,timeout=30,check=False)
    text=_normalized(result.stdout or '')
    target=_normalized(title)
    evidence={'checked':True,'matched':bool(not result.returncode and target and target==text),
            'text':text,'raw_text':result.stdout or '', 'stderr':getattr(result,'stderr','') or '',
            'expected_normalized':target,
            'normalization':'NFKC+whitespace_only','returncode':result.returncode,
            'language':'chi_sim+eng','psm':6}
    if not evidence['matched']:raise CoverTitleOCRError(evidence)
    return evidence


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
    face,lines,line_height=_layout(expected,font_path)
    top=(800-len(lines)*line_height)//2
    with Image.open(path) as source:
        if source.size!=SIZE or proof.get('dimensions')!=list(SIZE):raise ValueError('wechat_cover_dimensions_invalid')
        draw=ImageDraw.Draw(source)
        boxes=[list(draw.textbbox((70,top+index*line_height),line,font=face)) for index,line in enumerate(lines)]
        if boxes!=proof.get('title_boxes') or lines!=proof.get('title_lines') or any(
            box[0]<40 or box[1]<40 or box[2]>910 or box[3]>760 or box[0]>=box[2] or box[1]>=box[3] for box in boxes):
            raise ValueError('wechat_cover_title_box_invalid')
        roi=[min(box[0] for box in boxes)-20,min(box[1] for box in boxes)-20,
             max(box[2] for box in boxes)+20,max(box[3] for box in boxes)+20]
        with tempfile.TemporaryDirectory(prefix='.cover-ocr-',dir=path.parent) as temporary:
            roi_path=Path(temporary)/'title.png'
            source.crop(tuple(roi)).save(roi_path,format='PNG')
            try:result=_ocr(roi_path,expected)
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
                        cover_design=None,provider_result=None,font_path=None,diagnostic_dir=None):
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
    face,lines,line_height=_layout(title,font)
    background_sha=_sha(background)
    input_sha=hashlib.sha256(json.dumps({'background_sha256':background_sha,'title':title,
        'font_sha256':_sha(font),'font_face':FONT_FACE,'renderer_sha256':_sha(__file__)},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    proof=output.with_suffix('.render.json')
    reused=False
    if output.exists() or proof.exists():
        if proof.is_symlink() or not output.is_file() or not proof.is_file():raise ValueError('wechat_cover_output_conflict')
        evidence=json.loads(proof.read_text(encoding='utf-8'))
        if evidence.get('input_sha256')!=input_sha:raise ValueError('wechat_cover_output_conflict')
        evidence['ocr']=verify_cover_title(output,title,evidence,diagnostic_dir=diagnostic_dir)
        reused=True
    with Image.open(background) as source:
        image=ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'),SIZE,method=Image.Resampling.LANCZOS)
    draw=ImageDraw.Draw(image)
    # A solid high-contrast local title panel, not a substituted AI background.
    draw.rectangle((0,0,950,800),fill='#ffffff')
    top=(800-len(lines)*line_height)//2
    boxes=[]
    for index,line in enumerate(lines):
        position=(70,top+index*line_height)
        box=draw.textbbox(position,line,font=face)
        if box[0]<40 or box[1]<40 or box[2]>910 or box[3]>760:
            raise ValueError('wechat_cover_title_overflow')
        draw.text(position,line,font=face,fill='#132b3c');boxes.append(list(box))
    output.parent.mkdir(parents=True,exist_ok=True)
    if not reused:
        with tempfile.TemporaryDirectory(prefix='.cover-render-',dir=output.parent) as temporary:
            candidate=Path(temporary)/'cover.png';image.save(candidate,format='PNG')
            evidence={'version':'wechat_cover_render_v2','background_path':str(background),
                'background_sha256':background_sha,'output_sha256':_sha(candidate),'dimensions':list(SIZE),
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
        'dimensions':list(SIZE),'cover_render_evidence':evidence,
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
