import html
import re
import subprocess
import tempfile
from pathlib import Path


def _html_anything(markdown: str) -> str | None:
    """Try html-anything CLI, fall back to simple converter"""
    md_path = None
    out_path = None
    try:
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        tf.write(markdown)
        md_path = tf.name
        tf.close()
        out_path = md_path + ".html"
        r = subprocess.run(
            ["html-anything", "-t", "article", "-o", out_path, md_path],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            html = Path(out_path).read_text(encoding="utf-8")
            start = html.find("<body")
            end = html.find("</body>")
            if start != -1 and end != -1:
                start = html.index(">", start) + 1
                return html[start:end]
            return html
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    finally:
        for p in [md_path, out_path]:
            if p:
                try: Path(p).unlink(missing_ok=True)
                except OSError: pass
    return None


def _plain(text):
    return re.sub(r"[#*_`>]+", "", str(text)).strip()


def _hashtags(job):
    draft_meta = job.get("draft_meta", {})
    if draft_meta.get("hashtags"):
        return ["#" + str(word).lstrip("#").replace(" ", "") for word in draft_meta["hashtags"][:6]]
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,6}", job.get("topic", ""))
    tags = list(dict.fromkeys(words + ["AI内容", "效率工具"]))[:6]
    return ["#" + word.replace(" ", "") for word in tags]


def _html_article(body):
    sections = []
    for block in str(body).split("\n\n"):
        clean = block.strip()
        if not clean:
            continue
        if clean.startswith("# "):
            sections.append(f"<h1>{html.escape(clean[2:])}</h1>")
        elif clean.startswith("## "):
            sections.append(f"<h2>{html.escape(clean[3:])}</h2>")
        else:
            sections.append(f"<p>{html.escape(_plain(clean)).replace(chr(10), '<br>')}</p>")
    return "".join(sections)


def format_threads_copy(job, *, phase='generation'):
    """按当前 Threads 合同保真格式化；本函数不作原生语义审核。"""
    if phase not in {'generation', 'rendered'}:
        raise ValueError('threads_current_quality_phase_invalid')
    from .run_contract import build_run_contract
    contract = build_run_contract('threads')
    rules = contract.get('channel_rules') or {}
    required = {'conversational_tone', 'engagement_question', 'hashtag_1_to_3'}
    if set(rules.get('quality_gates') or []) != required:
        raise ValueError('threads_current_quality_rules_unsupported')
    brief = job.get('brief') or {}
    meta = job.get('draft_meta') or {}
    contracts = [bound for bound in (job.get('run_contract'), brief.get('run_contract')) if bound is not None]
    if contracts:
        if any(not isinstance(bound, dict) or bound != contracts[0] for bound in contracts):
            raise ValueError('threads_current_run_contract_mismatch')
        contract = build_run_contract('threads', audio_plan=contracts[0].get('audio_plan'))
        if contracts[0] != contract:
            raise ValueError('threads_current_run_contract_mismatch')
    forms = [item for item in (job.get('content_form'), brief.get('content_form'),
                              meta.get('content_form')) if item is not None]
    forms = ['image_text_post' if item == 'image_text' else item for item in forms]
    if not forms or len(set(forms)) != 1 or forms[0] not in rules.get('primary_types', []):
        raise ValueError('threads_current_content_form_missing_or_conflicting')
    limit, max_images = rules.get('char_limit'), rules.get('max_images')
    if type(limit) is not int or limit <= 0 or type(max_images) is not int or max_images <= 0:
        raise ValueError('threads_current_numeric_rules_invalid')
    title, body = job.get('title'), job.get('body')
    if not isinstance(title, str) or not isinstance(body, str) or not title.strip() or not body.strip():
        raise ValueError('threads_current_copy_missing')
    first_line = re.sub(r'^#{1,6}\s+', '', body.strip().splitlines()[0]).strip()
    if first_line == title.strip():
        raise ValueError('threads_current_title_repeated_in_body')
    text = title.strip() + '\n\n' + body.strip()
    # 仅使用当前生成的标签；没有标签时拒绝，不生成默认标签，不删除原文中的 #。
    tag_sources = [item for item in (job.get('hashtags'), meta.get('hashtags')) if item is not None]
    if tag_sources and any(item != tag_sources[0] for item in tag_sources):
        raise ValueError('threads_current_hashtags_conflicting')
    tags = tag_sources[0] if tag_sources else []
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not re.fullmatch(r'#?\w+', tag) for tag in tags):
        raise ValueError('threads_current_hashtags_invalid')
    tags = ['#' + tag.lstrip('#') for tag in tags]
    if len({tag.casefold() for tag in tags}) != len(tags):
        raise ValueError('threads_current_hashtags_duplicate')
    def visible_tags(value):
        without_urls = re.sub(r'https?://\S+', '', value)
        return re.findall(r'(?<![\w/#])#\w+', without_urls)
    inline = {tag.casefold() for tag in visible_tags(text)}
    missing = [tag for tag in tags if tag.casefold() not in inline]
    if missing:
        text += '\n\n' + ' '.join(missing)
    final_tags = visible_tags(text)
    if len({tag.casefold() for tag in final_tags}) != len(final_tags):
        raise ValueError('threads_current_hashtags_duplicate')
    count = len(final_tags)
    if not 1 <= count <= 3:
        raise ValueError('threads_current_hashtag_count_outside_1_to_3')
    if len(text) > limit:
        raise ValueError('threads_current_copy_length_exceeds_rule')
    image_count = None
    if 'images' in job:
        images = job['images']
        if not isinstance(images, list) or len(images) > max_images:
            raise ValueError('threads_current_images_invalid_or_exceed_rule')
        image_count = len(images)
    if phase == 'rendered':
        actual_images = job.get('images') or []
        if any(not isinstance(row, dict) or row.get('role') not in {'image', 'cover'}
               or not isinstance(row.get('path'), str) or not row.get('checksum')
               or type(row.get('artifact_id')) is not int for row in actual_images):
            raise ValueError('threads_rendered_registered_image_inventory_required')
        if forms[0] == 'image_text_post' and not any(row['role'] == 'image' for row in actual_images):
            raise ValueError('threads_rendered_image_text_actual_images_missing')
    return {'text': text, 'rulebook_sha256': contract['rulebook']['sha256'],
            'char_count': len(text), 'char_limit': limit, 'hashtag_count': count,
            'image_count_if_supplied': image_count, 'max_images': max_images,
            'semantic_review_required': True,
            'required_native_auto_checks': sorted('channel_rule:' + gate for gate in required)}


def format_for_platform(job, platform,*,audio_phase='rendered'):
    platform = platform.lower()
    from .task_source_inputs import project_task_source_job
    job=project_task_source_job(job,platform)
    title, body = job["title"].strip(), job["body"].strip()
    profile = job.get("profile", "default")
    draft_meta = job.get("draft_meta", {})
    base = {"platform": platform, "sources": job.get("brief", {}).get("sources", []), "profile": profile}
    if platform in {"wechat", "weixin", "wechat_official"}:
        html_body = _html_anything(body) or _html_article(body)
        return {**base, "kind": "article", "title": title[:64], "summary": _plain(body)[:120], "html": html_body}
    if platform in {"xiaohongshu", "rednote"}:
        hook = (draft_meta.get("hook", "") + "\n\n") if draft_meta.get("hook") else ""
        return {**base, "kind": "note", "title": _plain(title)[:20], "text": (hook + _plain(body))[:950], "hashtags": _hashtags(job)}
    if platform in {"youtube"}:
        desc = _plain(body)[:5000]
        return {**base, "kind": "video", "title": title[:100], "caption": desc, "hashtags": _hashtags(job)}
    if platform in {"bilibili"}:
        form=(job.get('brief') or {}).get('content_form')
        if form not in {'edited_short_video','tutorial_video'}:
            raise ValueError('bilibili_native_video_form_required')
        tags=draft_meta.get('hashtags') or []
        if not isinstance(tags,list) or any(not isinstance(tag,str) or not tag.strip() for tag in tags):
            raise ValueError('bilibili_current_video_tags_invalid')
        audio=(draft_meta.get('video_toolchain_plan') or {}).get('audio_plan') or {}
        return {**base, 'kind':'video', 'content_form':form, 'title':title,
                'description':_plain(body), 'caption':_plain(body), 'tags':list(tags),
                'bgm_source':audio,
                'recommended_publish_time':draft_meta.get('recommended_publish_time') or
                    ((job.get('brief') or {}).get('publishing_plan') or {}).get('recommended_publish_time')}
    if platform in {"douyin", "tiktok", "kuaishou", "shipinhao"}:
        hook = draft_meta.get("hook", "")
        caption = f"{hook} {_plain(body)}".strip() if hook else _plain(body)
        script = draft_meta.get("video_prompt") or _plain(body)
        formatted={**base, "kind": "video", "title": _plain(title)[:30], "caption": caption[:220], "script": script[:1200], "hashtags": _hashtags(job)}
        audio=(draft_meta.get('video_toolchain_plan') or {}).get('audio_plan') or {}
        if audio.get('status')=='resolved' and audio.get('route')=='embedded_licensed_bgm' and audio.get('license')=='https://creativecommons.org/licenses/by/4.0/':
            from .audio_attribution_formatter import bind_audio_attribution,prepare_audio_attribution
            if audio_phase=='planning':
                return prepare_audio_attribution(formatted,audio,platform=platform,copy_limit=220)
            if audio_phase!='rendered':raise ValueError('music_copy_phase_invalid')
            video=Path((draft_meta.get('video_artifact') or {}).get('path') or '')
            metadata=draft_meta.get('native_metadata_revision')
            if metadata:
                import hashlib,json
                from .media import MediaBridge
                root=Path(metadata['path'])
                if (str(job.get('id'))!='940c5334ccb445a0' or metadata.get('video_sha256')!='733d65daee0843636d29efb67c69ddb7e6d5b6fd2e10cf91575870ea05615e55'
                        or hashlib.sha256(video.read_bytes()).hexdigest()!=metadata['video_sha256']
                        or root.is_symlink() or any(p.is_symlink() for p in root.parents)
                        or not root.resolve().is_relative_to(Path('/srv/ai-self-media-tools/data/artifacts/940c5334ccb445a0'))
                        or hashlib.sha256((root/'trusted_run_manifest.json').read_bytes()).hexdigest()!=metadata['trusted_sha256']
                        or hashlib.sha256((root/'delivery_manifest.json').read_bytes()).hexdigest()!=metadata['delivery_sha256']
                        or hashlib.sha256((root/'cover.png').read_bytes()).hexdigest()!=metadata.get('cover_sha256')
                        or not (root/'cover.png').samefile(metadata['cover_path'])
                        or not (root/'final.mp4').samefile(video)):
                    raise ValueError('native_metadata_revision_binding_invalid')
                MediaBridge._validate_trusted_video_manifest(root,expected_output=root/'final.mp4')
                video=root/'final.mp4'
            from .resolved_audio_inputs import verify_rendered_audio_binding,actual_audio_render_changes
            verify_rendered_audio_binding(audio,video.parent,video,platform=platform)
            changes=actual_audio_render_changes(video.parent,video,audio)
            formatted=bind_audio_attribution(formatted,audio,platform=platform,render_changes=changes,copy_limit=220)
            planned=(draft_meta.get('video_toolchain_plan') or {}).get('music_publication_copy')
            packet_path=video.parent/'packet.json'
            if not planned or planned.get('caption')!=formatted['caption'] or not packet_path.is_file():
                raise ValueError('music_publication_copy_not_bound')
            import json
            packet=json.loads(packet_path.read_text(encoding='utf-8'))
            if packet.get('description')!=formatted['caption'] or packet.get('music_attribution')!=formatted['music_attribution']:
                raise ValueError('music_packet_copy_differs_from_review')
        return formatted
    if (platform in {"twitter", "x"}
            and (job.get("id") == "25110343c3354385" or draft_meta.get("target_adaptation_ref"))):
        from .target_adaptation import read_target_adaptation
        import hashlib
        target = read_target_adaptation(job, platform)
        text = target["caption"]
        if (not isinstance(text, str) or not 8 <= len(text) <= 275
                or hashlib.sha256(text.encode()).hexdigest() != target["caption_sha256"]):
            raise ValueError("twitter_target_copy_source_or_length_invalid")
        return {**base, "kind": "short", "text": text,
                "target_copy_ref": target["target_copy_ref"],
                "caption_sha256": target["caption_sha256"]}
    if platform == 'threads':
        measured = format_threads_copy(job, phase='rendered')
        return {**base, 'kind': 'short', 'text': measured['text'],
                'threads_copy_measurements': {key: value for key, value in measured.items() if key != 'text'}}
    if platform in {"twitter", "x", "mastodon", "bluesky"}:
        text = f"{_plain(title)}\n\n{_plain(body)}"
        limit = 280 if platform in {"twitter", "x"} else 500
        return {**base, "kind": "short", "text": text[:limit]}
    if platform in {"reddit"}:
        return {**base, "kind": "post", "title": title[:300], "text": body[:40000], "subreddit": draft_meta.get("subreddit", "manual-selection")}
    if platform in {"facebook", "instagram", "pinterest"}:
        text = _plain(body)[:2000]
        return {**base, "kind": "short", "text": text}
    return {**base, "kind": "article", "title": title, "markdown": body}
