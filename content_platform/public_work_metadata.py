"""Credential-free public metadata snapshots for explicitly supplied work URLs."""
from __future__ import annotations

import hashlib
import json
import subprocess
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request,urlopen


Runner = Callable[..., Any]
_FIXTURE_PARENT=Path('/srv/hermes-worker-media/fixtures')
_NATIVE_DATA=Path('/srv/ai-self-media-tools/data')
_ALLOWED_HOSTS = {
    "youtube": ("youtube.com", "youtu.be"),
    "tiktok": ("tiktok.com",),
    "kuaishou": ("kuaishou.com",),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _public_url(platform: str, value: Any) -> str:
    value = str(value or "").strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    allowed = _ALLOWED_HOSTS.get(platform, ())
    if parsed.scheme not in {"http", "https"} or not any(host == item or host.endswith("." + item) for item in allowed):
        return ""
    if platform=='kuaishou' and (parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.path.startswith(('/short-video/','/photo/'))):return ''
    return value


def _date(value: Any) -> str:
    text = str(value or "")
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _isolated_technical_context():
    try:
        spec=Path(os.environ.get('HERMES_TECHNICAL_API_FIXTURE') or '')
        if not spec.is_absolute() or spec.is_symlink() or any(parent.is_symlink() for parent in spec.parents):return False
        sandbox=spec.parent.parent
        if sandbox.parent!=_FIXTURE_PARENT or not re.fullmatch(r'full-run-[0-9a-f]{32}',sandbox.name) or spec!=sandbox/'api-fixture/spec.json':return False
        guard=sandbox/'guard-policy.json'
        if guard.is_symlink():return False
        if os.name=='posix' and any(path.stat().st_uid!=os.geteuid() or path.stat().st_mode&0o022 for path in (spec,guard,sandbox)):return False
        policy=json.loads(guard.read_text(encoding='utf-8'))
        packet=json.loads(spec.read_text(encoding='utf-8'))
        private=sandbox/'data'
        return (packet.get('version')==1 and packet.get('technical_only') is True
            and policy.get('shadow_bindings',{}).get(str(_NATIVE_DATA))==str(private)
            and _NATIVE_DATA.is_dir() and private.is_dir() and _NATIVE_DATA.samefile(private))
    except (OSError,ValueError,TypeError):return False


class PublicWorkMetadataAdapter:
    """Read public work metadata without auth, downloads, or browser state."""

    def __init__(self, *, runner: Runner | None = None):
        self.runner = runner or subprocess.run

    def collect(self, *, platform: str, urls: list[str] | tuple[str, ...], raw_responses=None,
                source_trust=None, max_age_seconds=86400, authorization_reference=None,license_scope=None) -> dict[str, Any]:
        platform = str(platform or "").casefold().strip()
        observed_at = _now()
        items: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for source_url in urls:
            collector='authorized_raw_work_metadata' if platform=='kuaishou' else 'yt_dlp_public_metadata'
            public_url = _public_url(platform, source_url)
            if not public_url:
                sources.append({"platform": platform, "source": collector, "status": "rejected", "reason": "non_platform_public_url"})
                continue
            command = ["yt-dlp", "--skip-download", "--no-playlist", "--no-warnings", "--dump-single-json", public_url]
            try:
                raw_hash=None;sample_observed=observed_at
                if platform=='kuaishou':
                    if source_trust!='authorized_export':raise ValueError('kuaishou_authorized_raw_export_required')
                    if not isinstance(authorization_reference,str) or not authorization_reference.strip() or license_scope not in {'commercial_generation','technical_fixture'}:
                        raise ValueError('kuaishou_explicit_authorization_and_license_required')
                    if license_scope=='technical_fixture' and not _isolated_technical_context():
                        raise ValueError('technical_fixture_license_outside_isolated_run')
                    binding=(raw_responses or {}).get(public_url) or {}
                    endpoint=urlparse(str(binding.get('url') or ''))
                    if endpoint.scheme!='https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.fragment:
                        raise ValueError('explicit_https_raw_export_required')
                    with urlopen(Request(endpoint.geturl(),headers={'Accept':'application/json'}),timeout=15) as response:
                        raw=response.read(4*1024*1024+1)
                    raw_hash=hashlib.sha256(raw).hexdigest()
                    if len(raw)>4*1024*1024 or raw_hash!=binding.get('sha256'):raise ValueError('raw_export_hash_or_size_invalid')
                    payload=json.loads(raw)
                    if not isinstance(payload,dict):raise ValueError('raw_work_object_required')
                    provenance=' '.join(str(payload.get(key) or '') for key in ('source','collector','license','license_status','license_scope','evidence_level','source_kind')).casefold()
                    if payload.get('research_only') or any(marker in provenance for marker in ('mediacrawler','non-commercial','noncommercial','research_only','research_import')):
                        raise ValueError('research_or_noncommercial_source_not_admitted')
                    content_id=str(payload.get('content_id') or payload.get('photo_id') or payload.get('id') or '').strip()
                    canonical=_public_url(platform,payload.get('canonical_url') or payload.get('content_url') or payload.get('url'))
                    if canonical!=public_url or content_id!=urlparse(public_url).path.rstrip('/').rsplit('/',1)[-1]:
                        raise ValueError('raw_work_identity_mismatch')
                    observed=datetime.fromisoformat(str(payload.get('collected_at') or payload.get('observed_at') or '').replace('Z','+00:00'))
                    now=datetime.now(timezone.utc)
                    if observed.tzinfo is None or type(max_age_seconds) not in (int,float) or not 0<max_age_seconds<=86400 or not 0<=(now-observed).total_seconds()<=max_age_seconds:
                        raise ValueError('raw_work_observation_stale_or_invalid')
                    sample_observed=observed.astimezone(timezone.utc).isoformat(timespec='seconds')
                    published=datetime.fromisoformat(str(payload.get('published_at') or payload.get('publish_time') or '').replace('Z','+00:00'))
                    if published.tzinfo is None or published>observed:raise ValueError('raw_work_publish_date_invalid')
                    original=payload
                    payload={'id':content_id,'webpage_url':canonical,'upload_date':published.strftime('%Y%m%d'),
                        'title':original.get('title') or original.get('desc'),'channel':original.get('author') or original.get('nickname'),
                        'duration':original.get('duration_seconds')}
                    for target,aliases in {'view_count':['view_count','play_count','video_play_count'],
                        'like_count':['like_count','liked_count','realLikeCount'],
                        'comment_count':['comment_count'],'repost_count':['share_count','video_share_count']}.items():
                        for alias in aliases:
                            if alias in original:
                                value=original[alias]
                                if isinstance(value,bool) or not str(value).isdigit():raise ValueError('raw_work_metric_invalid')
                                payload[target]=int(value);break
                    if not payload['title'] or not payload['channel']:raise ValueError('raw_work_title_or_author_missing')
                else:
                    result = self.runner(command, capture_output=True, text=True, timeout=45, check=False)
                    if int(result.returncode) != 0:
                        raise RuntimeError(f"yt_dlp_exit_{result.returncode}")
                    payload = json.loads(result.stdout)
                content_id = str(payload.get("id") or "").strip()
                published_at = _date(payload.get("upload_date"))
                metric_values = {
                    "views": _positive_int(payload.get("view_count")),
                    "likes": _positive_int(payload.get("like_count")),
                    "comments": _positive_int(payload.get("comment_count")),
                    "reposts": _positive_int(payload.get("repost_count")),
                }
                metrics = {key: value for key, value in metric_values.items() if value is not None}
                if not content_id or not published_at or not metrics:
                    raise ValueError("metadata_missing_content_id_publish_date_or_metrics")
                canonical_url = _public_url(platform, payload.get("webpage_url")) or public_url
                items.append({
                    "platform": platform,
                    "source": "authorized_raw_work_metadata" if platform=='kuaishou' else "yt_dlp_public_metadata",
                    "collector": "authorized_raw_work_metadata" if platform=='kuaishou' else "yt_dlp_public_metadata",
                    "signal_type": "public_work_metadata_snapshot",
                    "evidence_level": "authorized_raw_work_snapshot" if platform=='kuaishou' else "public_platform_work_snapshot",
                    "source_trust":source_trust if platform=='kuaishou' else 'public_metadata_read',
                    "authorization_reference":authorization_reference if platform=='kuaishou' else '',
                    "license_scope":license_scope if platform=='kuaishou' else 'public_metadata_read',
                    "license_status": "Operator-authorized metadata export; "+str(license_scope) if platform=='kuaishou' else "Publicly accessible work metadata; credential-free snapshot",
                    "observed_at": sample_observed,
                    "raw_response_hash": raw_hash or _hash(payload),
                    "content_id": content_id,
                    "canonical_url": canonical_url,
                    "title": str(payload.get("title") or ""),
                    "author": str(payload.get("channel") or payload.get("uploader") or ""),
                    "published_at": published.isoformat(timespec='seconds') if platform=='kuaishou' else published_at,
                    "duration_seconds": _positive_int(payload.get("duration")),
                    "metrics": metrics,
                    "native_verified": platform!='kuaishou',
                    "generation_only": True,
                    "auto_selection_eligible": False,
                    "viral_claim_eligible": False,
                })
                if platform=='kuaishou' and isinstance(original.get('observed_content'),dict):
                    items[-1]['observed_content']=json.loads(json.dumps(original['observed_content'],ensure_ascii=False))
                elif platform=='kuaishou' and isinstance(original.get('content_evidence'),dict):
                    items[-1]['content_evidence']=json.loads(json.dumps(original['content_evidence'],ensure_ascii=False))
                sources.append({"platform": platform, "source": collector, "status": "ok", "count": 1, "content_id": content_id})
            except Exception as exc:
                sources.append({"platform": platform, "source": collector, "status": "failed", "count": 0, "reason": str(exc)[:160]})
        return {"version": "public_work_metadata_v1", "observed_at": observed_at, "items": items, "sources": sources}
