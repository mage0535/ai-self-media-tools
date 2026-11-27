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


XHS_TITLE_LIMIT, XHS_TEXT_LIMIT = 20, 950
XHS_AI_DISCLOSURE = "本笔记由AI辅助创作，配图含AI生成内容。"
_CLAUSE_END = "：:，,；;。！!？?、|｜"


_HOOK_CUES = ("?", "？", "!", "！", "怎么", "如何", "清单", "避坑", "复核", "核对", "步骤", "实测", "防错", "别", "先", "坑", "步", "招")


def _note_title(title):
    """Xiaohongshu allows 20 characters: keep whole clauses, preserve hook/promise over bare topic labels, never cut inside a word."""
    title = _plain(title)
    if len(title) <= XHS_TITLE_LIMIT:
        return title
    for mark in "：:｜|":
        if mark not in title:
            continue
        head, tail = [part.strip() for part in title.split(mark, 1)]
        head_is_bare_label = len(head) <= 11 and not any(cue in head for cue in _HOOK_CUES)
        if head_is_bare_label and tail and any(cue in tail for cue in _HOOK_CUES):
            if 6 <= len(tail) <= XHS_TITLE_LIMIT:
                return tail
            tail_cut = max(tail.rfind(m, 0, XHS_TITLE_LIMIT + 1) for m in _CLAUSE_END)
            if tail_cut >= 6:
                return tail[:tail_cut].strip()
        if 6 <= len(head) <= XHS_TITLE_LIMIT:
            return head
    cut = max(title.rfind(mark, 0, XHS_TITLE_LIMIT + 1) for mark in _CLAUSE_END)
    if cut >= 6:
        return title[:cut].strip()
    head = title[:XHS_TITLE_LIMIT]
    return re.sub(r"[A-Za-z0-9+._-]+$", "", head).strip() or head


_STANDALONE_DIVIDER_RE = re.compile(r"^[\s\-—–─_=*•·~]+$")


def _trim_at_sentence(text, limit):
    text = str(text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text[:max(0, limit)].strip()
    # d91/d91c: If text introduces a compact table/checklist ("以下是待填模板：\n· ..."), preserve the
    # structured `· ` rows FIRST and compact the prose intro around them so saveable XHS checklists/tables
    # are never chopped off while leaving a dangling "下面是验证表模板" lead-in behind.
    if "\n· " in text or text.startswith("· "):
        all_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        first_item = next((i for i, ln in enumerate(all_lines) if ln.startswith("· ")), -1)
        if first_item >= 0:
            prose_part = "\n".join(all_lines[:first_item]).strip()
            item_lines = all_lines[first_item:]
            kept_items = []
            items_budget = limit if not prose_part else max(min(limit, len("\n".join(item_lines))), int(limit * 0.72))
            used_items = 0
            for ln in item_lines:
                add = len(ln) + (1 if kept_items else 0)
                if used_items + add <= items_budget:
                    kept_items.append(ln)
                    used_items += add
                elif not kept_items:
                    kept_items.append(ln[:items_budget].strip())
                    used_items = len(kept_items[0])
                    break
                else:
                    break
            if kept_items:
                items_str = "\n".join(kept_items)
                if not prose_part:
                    return items_str
                prose_budget = limit - len(items_str) - 1
                if prose_budget >= 18:
                    # Keep the trailing lead-in sentence or compact intro within prose_budget.
                    if len(prose_part) <= prose_budget:
                        return prose_part + "\n" + items_str
                    # Prefer the last sentence (closest lead-in to the table) if it fits cleanly.
                    sents = [s.strip() for s in re.split(r"(?<=[。！？!?])", prose_part) if s.strip()]
                    if sents and 8 <= len(sents[-1]) <= prose_budget:
                        return sents[-1] + "\n" + items_str
                    cut_p = max(prose_part.rfind(m, 0, prose_budget + 1) for m in "。！？!?；;：:")
                    lead = prose_part[:cut_p + 1].strip() if cut_p >= 12 else prose_part[:prose_budget].strip()
                    if lead:
                        return lead + "\n" + items_str
                return items_str
    cut = max(text.rfind(mark, 0, limit + 1) for mark in "。！？!?；;")
    if cut >= max(24, limit // 2) and not text[:cut + 1].rstrip().endswith(("：", ":")):
        return text[:cut + 1].strip()
    cut = max(text.rfind(mark, 0, limit + 1) for mark in "，,、 ")
    if cut >= max(24, limit // 2):
        return text[:cut].strip()
    return text[:limit].strip()


def _note_blocks_tagged(body):
    """Paragraph blocks of plain text paired with a flag indicating Markdown headings."""
    blocks = []
    for block in re.split(r"\n\s*\n", str(body)):
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        is_heading = len(lines) == 1 and bool(re.match(r"^#{1,6}\s+", lines[0]))
        if all(line.startswith("|") for line in lines):
            rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
            rows = [row for row in rows if not all(re.fullmatch(r":?-{2,}:?", cell) for cell in row if cell)]
            lines = ["· " + "｜".join(_plain(cell) for cell in row if cell) for row in rows]
        lines = [line for line in lines if not _STANDALONE_DIVIDER_RE.fullmatch(line)]
        if not lines:
            continue
        text = "\n".join(_plain(line) for line in lines).strip()
        if text and not _STANDALONE_DIVIDER_RE.fullmatch(text):
            blocks.append((text, is_heading))
    return blocks


def _note_blocks(body):
    """Paragraph blocks of plain text; a Markdown table (not rendered by Xiaohongshu) becomes one line per row."""
    return [text for text, _ in _note_blocks_tagged(body)]


def _note_text(hook, body):
    """Preserve all sections (headings + actionable checklist/handoff) cleanly within XHS_TEXT_LIMIT.

    d87/d90: Never emit orphaned headings or standalone divider lines ('—'). When a note has multiple
    sections, reserve every section heading verbatim (so section_image_map anchors stay 100% valid in
    publication_copy) and allocate the remaining budget proportionally across the intro and ALL sections
    so closing checklists and human-handoff steps are never truncated away.
    """
    tagged = _note_blocks_tagged(body)
    plain_hook = _plain(hook)
    if plain_hook and not _STANDALONE_DIVIDER_RE.fullmatch(plain_hook) and (
        not tagged
        or (plain_hook not in tagged[0][0] and tagged[0][0] not in plain_hook and plain_hook[:16] not in tagged[0][0])
    ):
        tagged.insert(0, (plain_hook, False))
    closing = ""
    if len(tagged) > 2 and not tagged[-1][1] and not tagged[-2][1]:
        closing = tagged.pop()[0]
    elif len(tagged) > 1 and not tagged[-1][1] and not any(is_h for _, is_h in tagged):
        closing = tagged.pop()[0]
    tail = [part for part in (closing, XHS_AI_DISCLOSURE) if part]
    budget = XHS_TEXT_LIMIT - sum(len(part) + 2 for part in tail)

    intro_blocks = []
    sections = []
    cur_heading = None
    cur_bodies = []
    for text, is_heading in tagged:
        if is_heading:
            if cur_heading is not None and cur_bodies:
                sections.append((cur_heading, cur_bodies))
            cur_heading = text
            cur_bodies = []
        elif cur_heading is None:
            intro_blocks.append(text)
        else:
            cur_bodies.append(text)
    if cur_heading is not None and cur_bodies:
        sections.append((cur_heading, cur_bodies))

    kept = []
    if not sections:
        rem = budget
        for text in intro_blocks:
            if len(text) + 2 <= rem:
                kept.append(text)
                rem -= len(text) + 2
    else:
        full_intro = "\n".join(intro_blocks).strip()
        full_sections = [(h, "\n".join(bs).strip()) for h, bs in sections]
        total_full = (len(full_intro) + 2 if full_intro else 0) + sum(len(h) + 2 + len(b) + 2 for h, b in full_sections)
        if total_full <= budget:
            if full_intro:
                kept.append(full_intro)
            for h, b in full_sections:
                kept.append(h)
                kept.append(b)
        else:
            # Reserve all section headings first; drop tail sections only in extreme cases where headings alone overflow.
            usable_sections = []
            heading_cost = 0
            for h, b in full_sections:
                if heading_cost + len(h) + 2 + 42 <= budget:
                    usable_sections.append((h, b))
                    heading_cost += len(h) + 2
            body_budget = max(0, budget - heading_cost - 2 * len(usable_sections))
            intro_share = 0
            if full_intro and body_budget > 80:
                intro_share = min(len(full_intro), max(60, int(body_budget * 0.22)))
                if body_budget - intro_share - 2 < 45 * len(usable_sections):
                    intro_share = max(0, body_budget - 45 * len(usable_sections) - 2)
                if intro_share >= 30:
                    trimmed_intro = _trim_at_sentence(full_intro, intro_share)
                    if trimmed_intro:
                        kept.append(trimmed_intro)
                        body_budget -= len(trimmed_intro) + 2
            n_sec = len(usable_sections)
            if n_sec:
                # Two-pass fair allocation: short sections keep full length; checklist/table sections
                # ("· " rows) receive 1.5x share priority so saveable XHS templates survive intact.
                raw_lens = [len(b) for _, b in usable_sections]
                weights = [1.5 if ("\n· " in b or b.startswith("· ")) else 1.0 for _, b in usable_sections]
                shares = [0] * n_sec
                rem_b = body_budget
                open_idx = list(range(n_sec))
                while open_idx and rem_b > 0:
                    w_sum = sum(weights[i] for i in open_idx)
                    next_open = []
                    consumed = 0
                    for i in open_idx:
                        alloc = max(1, int(rem_b * (weights[i] / w_sum)))
                        if raw_lens[i] - shares[i] <= alloc:
                            add = raw_lens[i] - shares[i]
                            shares[i] += add
                            consumed += add
                        else:
                            shares[i] += alloc
                            consumed += alloc
                            next_open.append(i)
                    rem_b -= consumed
                    if consumed == 0 or len(next_open) == len(open_idx):
                        break
                    open_idx = next_open
                for (h, b), limit in zip(usable_sections, shares):
                    trimmed = _trim_at_sentence(b, max(30, limit))
                    if trimmed:
                        kept.append(h)
                        kept.append(trimmed)
    text = "\n\n".join(kept + tail)
    return text if len(text) <= XHS_TEXT_LIMIT else text[:XHS_TEXT_LIMIT - len(XHS_AI_DISCLOSURE) - 2].rsplit("\n", 1)[0] + "\n\n" + XHS_AI_DISCLOSURE


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
        return {**base, "kind": "note", "title": _note_title(title), "text": _note_text(draft_meta.get("hook", ""), body),
                "hashtags": _hashtags(job), "ai_assisted_disclosure": XHS_AI_DISCLOSURE}
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
