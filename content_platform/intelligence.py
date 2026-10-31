import json
import re
import urllib.request
from html import unescape
from pathlib import Path

from .niche_analysis import analyze_niche
from .paths import trend_cache_dir
from .prompt_compiler import compile_prompt_bundle, validate_prompt_bundle
from .prompt_registry import PromptRegistry
from .real_world_ai_policy import is_real_world_ai_context, load_real_world_ai_positioning
from .sources import normalize_source_items, summarize_source_items
from .strategy_router import choose_content_strategy
from .viral_score import score_topic_candidate
from .viral_monitor import build_viral_report

GLOBAL_EN_PLATFORMS = {"devto", "buttondown", "writeas", "telegraph", "mastodon", "bluesky", "threads", "twitter", "x", "tiktok", "youtube", "nostr", "instagram"}
CN_PLATFORMS = {"wechat", "weixin", "wechat_official", "douyin", "xiaohongshu", "rednote", "bilibili", "kuaishou", "shipinhao", "juejin", "zhihu", "csdn"}


def infer_content_language(brief):
    brief = brief or {}
    explicit = str(brief.get("language") or brief.get("locale") or "").strip().lower()
    if explicit:
        if explicit.startswith(("en", "english")):
            return "en"
        if explicit.startswith(("zh", "cn", "chinese")) or "中文" in explicit:
            return "zh"
        return explicit[:16]
    platforms = [str(p).casefold() for p in brief.get("platforms", []) if str(p).strip()]
    if platforms and all(p in GLOBAL_EN_PLATFORMS for p in platforms):
        return "en"
    if any(p in CN_PLATFORMS for p in platforms):
        return "zh"
    return "zh"


def _clean_external_text(text, *, max_control_ratio=0.02):
    """Reject binary/embedded-NUL payloads before they enter model context.

    Short-link pages and failed decompression responses can be decoded into a
    string containing NUL bytes. Passing that string as a subprocess argument
    later raises ``ValueError: embedded null byte`` and obscures the source
    failure. Treat suspicious payloads as unavailable evidence instead.
    """
    value = str(text or "")
    if "\x00" in value:
        return ""
    if not value:
        return ""
    controls = sum(1 for char in value if ord(char) < 32 and char not in "\n\r\t")
    if controls / max(1, len(value)) > max_control_ratio:
        return ""
    return value


def _plain(text):
    text = _clean_external_text(text)
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_url(url, timeout=15):
    request = urllib.request.Request(url, headers={"User-Agent": "HermesContentPlatform/3.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        content_type = str(response.headers.get("Content-Type") or "").casefold()
        if "text/" not in content_type and "html" not in content_type and "json" not in content_type:
            return ""
        text = payload.decode("utf-8", errors="replace")
        return _clean_external_text(text)


def collect_reference_posts(brief, limit=3):
    brief = brief or {}
    if brief.get('content_mode') == 'original_method':
        # Only the normal Source producer's immutable observation grants this
        # factual domain. Re-read its original HTTP/native receipts; a caller's
        # typed string or copied research summary is not a factual credential.
        from .original_knowledge import _bytes
        from .task_source_inputs import verify_original_method_facts
        ref = brief.get('original_method_observed_ref') or {}
        proof = json.loads(_bytes(ref['path'], ref['sha256'], private=True))
        topic = (brief.get('production_intent') or {}).get('topic')
        if proof.get('schema') != 'observed_original_method_facts_v1' or proof.get('topic') != topic:
            raise ValueError('original_method_observation_scope_mismatch')
        verified = verify_original_method_facts({'id': proof['job_id'], 'topic': topic, 'brief': brief})
        if proof != verified:
            raise ValueError('original_method_observation_originals_changed')
        factual = [{
            'title': row['url'].rstrip('/').split('/')[-1],
            'body': row['text'], 'url': row['url'],
            'source': 'official_primary_documentation',
            'source_kind': row['source_kind'], 'source_use': row['source_use'],
            'raw_ref': row['raw_ref'], 'capture_ref': row['capture_ref'],
            'evidence_status': 'verified_original_reference_not_measured_outcome',
        } for row in verified['official_documents']]
        if verified['native_first_party_receipts']:
            factual.append({
                'title': 'Native delivery receipt identity example',
                'body': ('A completed report has independently accepted summary, text and file delivery receipts. '
                         'Compare task identity, exact file version/checksum and intended recipient evidence separately. '
                         'This supports an identity-checking method, not a tested n8n workflow, performance gain or '
                         'proof that a new report has been delivered. Missing evidence remains unconfirmed.'),
                'url': 'hermes-receipt://verified-report-delivery/method-example',
                'source': 'anonymized_native_delivery_receipts',
                'source_kind': 'native_first_party_receipt', 'source_use': 'method_facts_only',
                'original_method_observed_ref': ref,
                'evidence_status': 'verified_receipt_identity_example_not_implementation_result',
            })
        # All four official sources (including Graph's 202 distinction) and one
        # anonymized receipt fit the bounded five-reference generation contract.
        if not factual or len(factual) > 5:
            raise ValueError('original_method_factual_reference_count_invalid')
        supplied = brief.get('factual_reference_posts')
        if supplied is not None and supplied != factual:
            raise ValueError('original_method_factual_reference_projection_changed')
        return factual
    posts = []
    # Evidence is produced in several structured forms by the collectors.  The
    # old path only accepted the legacy reference_posts field, so a perfectly
    # valid platform_source_matrix silently became sample_count=0.
    structured_rows = list(brief.get("reference_posts") or [])
    for evidence_key in ("trend_evidence", "platform_source_matrix"):
        value = brief.get(evidence_key) or {}
        if evidence_key == "platform_source_matrix" and isinstance(value, dict):
            value = value.get("trend_evidence") or value
        if isinstance(value, dict):
            structured_rows.extend(value.get("samples") or [])
            structured_rows.extend(value.get("reference_posts") or [])
    seen = set()
    for row in structured_rows:
        if not isinstance(row, dict):
            continue
        title = _clean_external_text(row.get("title", ""))
        body = _clean_external_text(row.get("body", row.get("summary", row.get("description", ""))))
        url = str(row.get("url") or row.get("source_url") or "")
        identity = (title, body, url)
        if not (title or body) or identity in seen:
            continue
        seen.add(identity)
        posts.append(
            {
                "title": title,
                "body": body,
                "source": row.get("source", row.get("source_name", "reference")),
                "account_handle": str(row.get("account_handle", "")),
                "platform": str(row.get("platform", "")),
                "url": url,
                "views": row.get("views", row.get("plays", row.get("impressions", 0))),
                "likes": row.get("likes", 0),
                "comments": row.get("comments", 0),
                "shares": row.get("shares", row.get("reposts", 0)),
                "saves": row.get("saves", row.get("favorites", 0)),
                "followers": row.get("followers", row.get("account_followers", 0)),
                "evidence_status": row.get("status", "available"),
            }
        )
    if posts:
        return posts[:limit]
    keywords = [str(word).casefold() for word in brief.get("keywords", []) if str(word).strip()]
    trend_dir = Path(brief.get("trend_cache_dir", str(trend_cache_dir())))
    if trend_dir.exists():
        files = sorted(trend_dir.glob("trending_*.json"), reverse=True)
        if files:
            try:
                payload = json.loads(files[0].read_text(encoding="utf-8"))
                rows = payload if isinstance(payload, list) else payload.get("trends", payload.get("items", []))
                for row in rows:
                    title = str(row.get("title", ""))
                    url = str(row.get("url", ""))
                    if not url:
                        continue
                    if keywords and not any(word in title.casefold() for word in keywords):
                        continue
                    try:
                        html = _fetch_url(url)
                    except Exception:
                        continue
                    body = _plain(html)[:4000]
                    if title or body:
                        posts.append(
                            {
                                "title": title[:160],
                                "body": body,
                                "source": row.get("source", url),
                                "account_handle": str(row.get("account_handle", "")),
                                "platform": str(row.get("platform", "")),
                                "url": url,
                            }
                        )
                    if len(posts) >= limit:
                        return posts[:limit]
            except Exception:
                pass
    for url in brief.get("sources", [])[:limit]:
        try:
            html = _fetch_url(url)
        except Exception:
            continue
        title = ""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if title_match:
            title = _plain(title_match.group(1))
        body = _plain(html)[:4000]
        if title or body:
            posts.append({"title": title[:160], "body": body, "source": url, "account_handle": "", "platform": "", "url": url})
    return posts[:limit]


def analyze_reference_posts(posts):
    posts = [row for row in (posts or []) if row.get("title") or row.get("body")]
    formats = set()
    cta = ""
    emoji_hits = 0
    opening_patterns = []
    paragraph_lengths = []
    for row in posts:
        body = str(row.get("body", ""))
        title = str(row.get("title", ""))
        if re.search(r"(^|\n)\s*\d+[.)]", body):
            formats.add("listicle")
        if "## " in body or re.search(r"(^|\n)\s*##\s+", body):
            formats.add("sectioned")
        if "?" in title or "？" in title:
            formats.add("question_hook")
        for token in ("Save this", "Follow", "Comment", "收藏", "关注", "评论"):
            if token.casefold() in body.casefold():
                cta = token
                break
        emoji_hits += len(re.findall(r"[\U0001F300-\U0001FAFF]", body))
        first_sentence = re.split(r"[。！？.!?]", body.strip(), maxsplit=1)[0].strip()
        if first_sentence:
            opening_patterns.append(first_sentence[:50])
        paragraph_lengths.extend(len(part.strip()) for part in re.split(r"\n\s*\n", body) if part.strip())
    return {
        "sample_count": len(posts),
        "formats": sorted(formats),
        "cta": cta or "Save this",
        "emoji_density": round(emoji_hits / max(1, len(posts)), 2),
        "opening_patterns": opening_patterns[:3],
        "paragraph_length_hint": int(sum(paragraph_lengths) / max(1, len(paragraph_lengths))) if paragraph_lengths else 80,
    }


def cluster_reference_topics(items):
    buckets = {}
    for item in items or []:
        signals = list(item.get("topic_signals", []))
        forms = list(item.get("content_forms", []))
        host = item.get("source_host", "")
        platform = item.get("platform", "")
        key_parts = signals[:2] or forms[:1] or [platform or host or "general"]
        cluster_key = "-".join(str(part).casefold() for part in key_parts if str(part).strip())[:80] or "general"
        bucket = buckets.setdefault(
            cluster_key,
            {
                "cluster_key": cluster_key,
                "label": key_parts[0] if key_parts else "general",
                "sample_count": 0,
                "platforms": set(),
                "source_hosts": set(),
                "topic_signals": set(),
                "content_forms": set(),
            },
        )
        bucket["sample_count"] += 1
        if platform:
            bucket["platforms"].add(platform)
        if host:
            bucket["source_hosts"].add(host)
        bucket["topic_signals"].update(signals)
        bucket["content_forms"].update(forms)
    clusters = []
    for bucket in buckets.values():
        clusters.append(
            {
                "cluster_key": bucket["cluster_key"],
                "label": bucket["label"],
                "score": round(min(1.0, 0.35 + bucket["sample_count"] * 0.12 + len(bucket["platforms"]) * 0.08), 3),
                "sample_count": bucket["sample_count"],
                "platforms": sorted(bucket["platforms"]),
                "source_hosts": sorted(bucket["source_hosts"]),
                "topic_signals": sorted(bucket["topic_signals"])[:8],
                "content_forms": sorted(bucket["content_forms"]),
            }
        )
    return sorted(clusters, key=lambda row: (-row["score"], row["cluster_key"]))


def prepare_generation_strategy_inputs(topic, brief, *, content_form=None):
    """在严格策略选择前真实编译关键词/提示词，保留采源与拆解强门。"""
    from .strategy_compiler import build_strategy_evidence_contract,validate_strategy_evidence_contract
    from .viral_breakdown import cache_is_fresh,validate_breakdown_report
    scoped=dict(brief or {})
    requested=[str(item).casefold() for item in scoped.get('platforms') or []]
    platform=str(scoped.get('platform') or (requested[0] if len(requested)==1 else '')).casefold()
    if not platform or requested not in ([],[platform]):
        raise ValueError('strategy_evidence_single_platform_required')
    profile=PromptRegistry.from_default().platform(platform)
    form=str(content_form or scoped.get('content_form') or scoped.get('preferred_content_form') or profile.get('content_type') or '')
    lane=str(scoped.get('lane') or scoped.get('niche') or '').strip()
    references=list((scoped.get('viral_breakdown') or {}).get('samples') or [])
    evidence=[str(row.get('canonical_url') or row.get('url') or '') for row in references if row.get('url') or row.get('canonical_url')]
    evidence=list(dict.fromkeys(evidence+[str(row) for row in scoped.get('evidence') or [] if str(row).strip()]))
    spec={'platform':platform,'content_type':form,'topic':topic,'audience':str(scoped.get('audience') or '内容用户'),
        'goal':str(scoped.get('goal') or '提高完播、收藏和评论质量'),'evidence':evidence,
        'visual_style':str(scoped.get('visual_style') or '真实工作场景与可核验画面'),'duration':str(scoped.get('duration') or '20-60秒'),
        'constraints':['不得把AI画面伪装成真实事件','画面必须与主题匹配','数字与事实必须绑定真实来源']}
    if is_real_world_ai_context(scoped):
        policy=load_real_world_ai_positioning()
        package=scoped.get('real_world_ai_package') or {}
        spec.update(policy_profile=policy['policy_profile'],policy_revision=policy['policy_revision'],
            prompt_profile=profile['prompt_profile'],scenario=scoped.get('scenario') or package.get('scenario'))
    bundle=compile_prompt_bundle(spec)
    bundle_gate=validate_prompt_bundle(bundle)
    keywords={'tool':'content_platform.prompt_compiler','platform':platform,'lane':lane,
        'queries':list((bundle.get('keywords') or {}).get('topic') or []),'fingerprint':bundle.get('fingerprint')}
    breakdown=scoped.get('viral_breakdown') or {}
    strict=bool(scoped.get('require_live_strategy_evidence') or (scoped.get('run_contract') or {}).get('enforce_strategy_evidence'))
    # Lanes without their own public collector observe a declared sibling platform (overnight_benchmarks).
    source_platform=str(scoped.get('cross_platform_source') or platform).casefold()
    if strict and (breakdown.get('platform')!=source_platform or not validate_breakdown_report(breakdown)['passed'] or not cache_is_fresh(breakdown)):
        raise ValueError('strategy_evidence_breakdown_platform_or_freshness_invalid')
    if strict:
        from datetime import datetime,timezone
        current=datetime.now(timezone.utc)
        try:
            timestamps=[datetime.fromisoformat(str(row.get('captured_at') or '').replace('Z','+00:00')) for row in breakdown.get('samples') or []]
        except ValueError as error:raise ValueError('strategy_evidence_sample_timestamp_invalid') from error
        maximum=(scoped.get('viral_collection') or {}).get('max_age_seconds')
        expected=900 if all(row.get('source')=='native.twitter_browser' for row in breakdown.get('samples') or []) else 86400
        if maximum!=expected or not timestamps or any(value.tzinfo is None or not 0<=(current-value).total_seconds()<=maximum for value in timestamps):
            raise ValueError('strategy_evidence_sample_observation_expired')
        from .task_source_inputs import _observed_strategy_inputs
        actual=_observed_strategy_inputs(source_platform,{'items':breakdown['samples']},now=current)['viral_breakdown']
        if actual['samples']!=breakdown['samples']:
            raise ValueError('strategy_evidence_observed_breakdown_changed')
    contract=build_strategy_evidence_contract(platform=platform,lane=lane,
        viral_collection=scoped.get('viral_collection'),viral_breakdown=breakdown,keyword_tool=keywords,
        prompt_bundle={'validation':bundle_gate,'fingerprint':bundle.get('fingerprint'),'evidence':evidence},
        reference_platform=source_platform)
    gate=validate_strategy_evidence_contract(contract)
    if strict and not gate['passed']:
        raise ValueError('strategy evidence contract invalid: '+', '.join(gate['failures']))
    scoped.update(prompt_bundle=bundle,prompt_bundle_gate=bundle_gate,keyword_plan=keywords,
        strategy_evidence=contract,strategy_evidence_gate=gate)
    return scoped


def build_generation_context(topic, brief):
    brief = dict(brief or {})
    strict=bool(brief.get('require_live_strategy_evidence') or (brief.get('run_contract') or {}).get('enforce_strategy_evidence'))
    if strict:
        brief=prepare_generation_strategy_inputs(topic,brief)
    language = infer_content_language(brief)
    references = collect_reference_posts(brief)
    source_catalog = normalize_source_items(topic, brief, references)
    source_summary = summarize_source_items(source_catalog)
    topic_clusters = cluster_reference_topics(source_catalog)
    research_references = references
    research_catalog = source_catalog
    if brief.get('content_mode') == 'original_method':
        research_references = brief.get('style_research_reference_posts') or []
        if not research_references or research_references != brief.get('reference_posts'):
            raise ValueError('original_method_current_style_research_missing')
        research_references = collect_reference_posts({'reference_posts': research_references}, limit=5)
        research_catalog = normalize_source_items(topic, dict(brief, sources=[]), research_references)
    style = analyze_reference_posts(research_references)
    niche_report = analyze_niche(topic, source_catalog or references)
    viral_score = score_topic_candidate(topic, brief, research_references, niche_report)
    viral_growth_report = build_viral_report(research_catalog or research_references, brief.get("recent_by_account", {}))
    strategy = choose_content_strategy(topic, brief, viral_score, niche_report, viral_growth_report)
    if str(brief.get("content_form") or "").strip():
        strategy = dict(strategy)
        strategy["content_form"] = str(brief["content_form"]).strip()
    if strict and (brief['prompt_bundle'].get('input') or {}).get('content_type')!=strategy['content_form']:
        brief=prepare_generation_strategy_inputs(topic,brief,content_form=strategy['content_form'])
        strategy=choose_content_strategy(topic,brief,viral_score,niche_report,viral_growth_report)
    trend_stage = brief.get("trend_stage", viral_score["trend_stage"])
    trend_angle = brief.get("trend_angle", "")
    reference_titles = [row.get("title", "") for row in references if row.get("title")]
    audience = str(brief.get("audience", "")).strip()
    niche = str(brief.get("niche", "")).strip()
    from .growth_policy import verify_owned_feedback
    feedback_platforms = brief.get("platforms") or ([brief["platform"]] if brief.get("platform") else [])
    if isinstance(feedback_platforms, str):
        feedback_platforms = [feedback_platforms]
    feedback_scope = {"platform": feedback_platforms[0] if len(feedback_platforms) == 1 else "",
        "account_id": str(brief.get("account_id") or "").strip(),
        "internal_account_alias": str(brief.get("internal_account_alias") or brief.get("account") or "").strip(),
        "window_hours": brief.get("review_window_hours")}
    historical_feedback = verify_owned_feedback(brief.get("historical_feedback", {}), target_scope=feedback_scope)
    cluster_memory = []
    content_hygiene = brief.get("content_hygiene", {})
    # A ready viral report is an executable input, not merely a readiness flag.
    # Keep the policy bounded so providers receive decisions rather than raw
    # sample dumps. Missing reports remain compatible for non-strict callers.
    viral_execution_policy = {}
    try:
        from .viral_execution import build_viral_execution_policy, find_viral_report

        platform_hint = str(brief.get("platform") or "").strip()
        report = find_viral_report(brief, platform_hint)
        if report is not None:
            viral_execution_policy = build_viral_execution_policy(report)
    except ValueError:
        # Strict workflow validation owns the blocking decision. Do not turn a
        # malformed report into a plausible default policy here.
        viral_execution_policy = {"status": "blocked", "reason": "viral_breakdown_not_executable"}
    cornerstone_mode = bool(content_hygiene and content_hygiene.get("recommended_action") in {"merge_into_cornerstone", "refresh_existing_cornerstone"})

    # 可选：Open Notebook 深度研究
    on_research = {}
    if brief.get("deep_research"):
        try:
            from scripts.open_notebook_integrator import research_topic
            urls = brief.get("deep_research_urls", [])
            texts = brief.get("deep_research_texts", [])
            if urls or texts:
                on_research = research_topic(topic, urls=urls, texts=texts)
        except Exception:
            on_research = {"error": "open_notebook unavailable"}

    content_form = strategy["content_form"]
    prompt_bundle = brief.get('prompt_bundle') if strict else {}
    prompt_bundle_gate = brief.get('prompt_bundle_gate') if strict else {"passed": False, "errors": ["prompt_bundle_not_compiled"], "warnings": []}
    prompt_platform = str((strategy.get("primary_platforms") or [brief.get("platform") or ""])[0]).casefold()
    policy = load_real_world_ai_positioning()
    ai_lane = is_real_world_ai_context(brief)
    package = brief.get("real_world_ai_package") if isinstance(brief.get("real_world_ai_package"), dict) else {}
    scenario = brief.get("scenario") if isinstance(brief.get("scenario"), dict) else package.get("scenario")
    prompt_spec = {
        "platform": prompt_platform,
        "content_type": content_form,
        "topic": topic,
        "audience": audience or "宠物内容用户",
        "goal": str(brief.get("goal") or "提高完播、收藏和评论质量"),
        "evidence": [str(item) for item in reference_titles[:5] if str(item).strip()] or [str(item) for item in (brief.get("evidence") or []) if str(item).strip()],
        "visual_style": str(brief.get("visual_style") or "真实宠物视频优先，移动端安全区"),
        "duration": str(brief.get("duration") or "20-60秒"),
        "constraints": [
            "优先使用真实宠物视频",
            "不得把AI画面伪装成真实事件",
            "画面必须与主题匹配",
        ],
    }
    if ai_lane:
        profile = PromptRegistry.from_default().platform(prompt_platform)
        prompt_spec.update({
            "policy_profile": policy["policy_profile"],
            "policy_revision": policy["policy_revision"],
            "prompt_profile": profile["prompt_profile"],
            "scenario": scenario,
        })
    try:
        if not strict:
            prompt_bundle = compile_prompt_bundle(prompt_spec)
            prompt_bundle_gate = validate_prompt_bundle(prompt_bundle)
    except (KeyError, TypeError, ValueError) as exc:
        prompt_bundle = {"status": "blocked", "error": str(exc), "input": prompt_spec}
        prompt_bundle_gate = {"passed": False, "errors": ["prompt_bundle_compile_failed", str(exc)], "warnings": []}
    if ai_lane and not prompt_bundle_gate.get("passed"):
        reasons = ",".join(str(item) for item in prompt_bundle_gate.get("errors") or [])
        raise ValueError(f"ai_lane_prompt_gate_failed:{reasons}")
    image_prompt = f"{topic} | niche={niche} | audience={audience} | form={content_form} | create a strong cover with high information density"
    video_prompt = f"{topic} | form={content_form} | start with a hook, explain three points, end with a CTA"
    if viral_execution_policy and viral_execution_policy.get("status") != "blocked":
        video_prompt += " | execute the selected viral reference policy; do not reuse the default card sequence"
    # 配音脚本生成指南（传给生成器）
    if language == "en":
        narration_guide = (
            f"Generate an English narration script. Adapt tone to niche={niche} and content_form={content_form}. "
            "Single-speaker mode: output narration text directly. Multi-speaker mode: use [Speaker A] lines."
        )
    else:
        narration_guide = (
            f"生成中文配音脚本。跟踪赛道(niche={niche})和内容形式({content_form})自动适配风格。"
            "单人播报模式：直接输出配音文本。"
            "多人对话模式：使用[角色A]台词\n[角色B]台词格式标记不同说话人。"
        )
    return {
        "language": language,
        "trend_stage": trend_stage,
        "trend_angle": trend_angle,
        "reference_titles": reference_titles[:5],
        "style": style,
        "image_prompt": image_prompt,
        "video_prompt": video_prompt,
        "prompt_bundle": prompt_bundle,
        "prompt_bundle_gate": prompt_bundle_gate,
        "keyword_plan": {
            "tool": "content_platform.prompt_compiler",
            "platform": prompt_platform,
            "lane": niche or str(brief.get("lane") or ""),
            "queries": list((prompt_bundle.get("keywords") or {}).get("topic") or []) if isinstance(prompt_bundle, dict) else [],
            "fingerprint": str(prompt_bundle.get("fingerprint") or "") if isinstance(prompt_bundle, dict) else "",
        },
        "narration_guide": narration_guide,
        "hashtags": brief.get("keywords", [])[:6],
        "source_catalog": source_catalog,
        "source_summary": source_summary,
        "evidence": references[:5],
        **({'style_research': research_references} if brief.get('content_mode') == 'original_method' else {}),
        "topic_clusters": topic_clusters,
        "niche_report": niche_report,
        "viral_score": viral_score,
        "viral_growth_report": viral_growth_report,
        "strategy": strategy,
        "historical_feedback": historical_feedback,
        "cluster_memory": cluster_memory,
        "open_notebook_research": on_research,
        "content_hygiene": content_hygiene,
        "cornerstone_mode": cornerstone_mode,
        "viral_execution_policy": viral_execution_policy,
        # 2026-08-16：注入平台运营规则（收藏率权重/AI声明/新规等），生成器自动适配
        "platform_rules": _load_platform_rules(strategy),
        # 2026-08-16：注入平台可用钩子模板库，生成标题/脚本时参考爆款结构
        "hook_samples": _load_hook_samples(strategy.get("primary_platforms") or ""),
    }


def _load_platform_rules(strategy: dict) -> str:
    """按策略主平台加载 2026 规则浓缩文本；失败时静默返回空串（不阻断生成）。"""
    try:
        from .platform_rules import platform_rules_brief

        platforms = {str(p).casefold() for p in strategy.get("primary_platforms") or []}
        # douyin_ai/douyin_pet 映射到 douyin 规则；wechat_official 映射 gzh
        # Reuse registered platform contracts; never borrow another platform's rules.
        if platforms & {"twitter", "x", "mastodon"}:
            platform = next(iter(platforms))
            if len(platforms) != 1:
                raise ValueError("2026 single-platform rule scope required")
            requested = platform
            canonical = "twitter" if requested == "x" else requested
            from .run_contract import build_run_contract, validate_run_contract
            contract = build_run_contract(canonical)
            if (not validate_run_contract(contract).get("passed")
                    or contract.get("platform") != canonical
                    or (contract.get("channel_rules") or {}).get("status") == "unsupported_pre_onboarding"):
                raise ValueError("registered platform rule contract unavailable: " + canonical)
            specific = ""
            if canonical == "twitter":
                from .platform_rules import load_rules, rules_for_platform, _SECTION_MAP
                targets = _SECTION_MAP.get(requested)
                sections = load_rules()
                if (not targets or not any(any(token in title for token in targets)
                        and isinstance(body, str) and body.strip() for title, body in sections.items())):
                    raise ValueError("2026 own platform rule section missing: " + canonical)
                specific = rules_for_platform(requested)
                if not isinstance(specific, str) or not specific.strip():
                    raise ValueError("2026 own platform rule text missing: " + canonical)
            return json.dumps({"platform": canonical, "run_contract": contract,
                "platform_specific_rules": specific}, ensure_ascii=False, sort_keys=True)
        alias = {
            "douyin_ai": "douyin", "douyin_pet": "douyin",
            "wechat_official": "gzh", "weixin": "gzh", "rednote": "xhs",
        }
        platform = next(
            (alias.get(p, p) for p in platforms
             if p in {"douyin", "douyin_ai", "douyin_pet", "kuaishou", "shipinhao", "tiktok",
                      "youtube", "bilibili", "xiaohongshu", "xhs", "wechat", "gzh", "wechat_official",
                      "weixin", "rednote", "zhihu", "juejin"}),
            "",
        )
        brief = platform_rules_brief(platform, 900) if platform else ""
        if platform and not brief:
            raise RuntimeError(f"2026 platform rules unavailable for {platform}; refusing generation without rule context")
        return brief
    except Exception:
        if platform:
            raise
        return ""


def _load_hook_samples(platform: str, max_hooks: int = 5) -> str:
    """加载平台可用钩子模板库作为标题/脚本生成参考（2026-08-16 新增接入）。
    返回浓缩文本注入生成 prompt；失败静默返回空串。
    """
    try:
        from .hooks_loader import pick_hooks

        hooks = pick_hooks(platform, max_hooks)
        if not hooks:
            return ""
        lines = []
        for h in hooks[:max_hooks]:
            template = str(h.get("template") or "")
            example = str(h.get("example") or "")
            lines.append(f"模板: {template}")
            if example:
                lines.append(f"示例: {example}")
        return "\n".join(lines)
    except Exception:
        return ""


def prompt_brief(topic, brief):
    context = build_generation_context(topic, brief)
    return json.dumps(
        {
            "topic": topic,
            "brief": brief,
            "language": context.get("language", "zh"),
            "trend_stage": context["trend_stage"],
            "trend_angle": context["trend_angle"],
            "reference_titles": context["reference_titles"],
            "style": context["style"],
            "source_summary": context["source_summary"],
            "evidence": context.get("evidence", []),
            "topic_clusters": context["topic_clusters"],
            "niche_report": context["niche_report"],
            "viral_score": context["viral_score"],
            "strategy": context["strategy"],
            "historical_feedback": context.get("historical_feedback", {}),
            "cluster_memory": context.get("cluster_memory", []),
            "content_hygiene": context.get("content_hygiene", {}),
            "cornerstone_mode": context.get("cornerstone_mode", False),
            "viral_execution_policy": context.get("viral_execution_policy", {}),
            "prompt_bundle": context.get("prompt_bundle", {}),
            "prompt_bundle_gate": context.get("prompt_bundle_gate", {}),
            "keyword_plan": context.get("keyword_plan", {}),
            "image_prompt": context["image_prompt"],
            "video_prompt": context["video_prompt"],
            "narration_guide": context.get("narration_guide", ""),
            "platform_rules": context.get("platform_rules", ""),
            "open_notebook_research": context.get("open_notebook_research", {}),
        },
        ensure_ascii=False,
    )
