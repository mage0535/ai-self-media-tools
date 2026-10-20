"""Bind real licensed-music attribution into the reviewed publication copy."""

import hashlib
import json

if __package__:
    from .audio_plan_resolver import _json, _path, _sha
else:
    from audio_plan_resolver import _json, _path, _sha

from content_platform.run_contract import validate_audio_plan

CHANGES = {
    'mixed_with_narration': '与旁白混音',
    'trimmed_or_looped': '按视频长度剪辑或循环',
    'volume_adjusted': '调整音量',
    'unmodified': '原音乐未改动',
}


def prepare_audio_attribution(formatted,resolved_plan,*,platform,copy_limit):
    """Freeze intended public copy before execution; this is not a render receipt.

    The selected native mixer is required to prove these operations after it runs.
    No review or publisher may consume this pending object as actual evidence.
    """
    copy=bind_audio_attribution(formatted,resolved_plan,platform=platform,
        render_changes=['mixed_with_narration','trimmed_or_looped','volume_adjusted'],copy_limit=copy_limit)
    copy['music_attribution_status']='pending_native_render'
    return copy


def _text(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 2048
            or any(ord(char) < 32 for char in value)):
        raise ValueError('invalid_music_credit_field')
    return value


def bind_audio_attribution(formatted, resolved_plan, *, platform, render_changes,
                           copy_limit, field='caption') -> dict:
    """Inputs must come from the trusted resolver and actual renderer operations.

    Never pass model-authored copyright/changes. Use this SAME result in the
    review bundle and publisher/packet; do not append credits after approval.
    """
    if not isinstance(formatted, dict) or not isinstance(resolved_plan, dict):
        raise ValueError('formatted_and_audio_plan_objects_required')
    if (resolved_plan.get('status') != 'resolved'
            or resolved_plan.get('route') != 'embedded_licensed_bgm'
            or not validate_audio_plan(resolved_plan, require_bgm=True)['passed']):
        raise ValueError('resolved_licensed_audio_required')
    scope = resolved_plan.get('rights_scope')
    if (not isinstance(scope, dict) or not isinstance(scope.get('platforms'), list)
            or platform not in scope['platforms']):
        raise ValueError('music_platform_scope_mismatch')
    if field not in {'caption', 'description', 'text'} or not isinstance(formatted.get(field), str):
        raise ValueError('platform_copy_field_required')
    if type(copy_limit) is not int or copy_limit < 1:
        raise ValueError('explicit_platform_copy_limit_required')
    if (not isinstance(render_changes, (list, tuple)) or not render_changes
            or any(not isinstance(change, str) or change not in CHANGES for change in render_changes)
            or ('unmodified' in render_changes and len(render_changes) != 1)):
        raise ValueError('trusted_native_render_changes_required')
    record_path = _path(resolved_plan['source_record_path'])
    if _sha(record_path) != resolved_plan.get('source_record_sha256'):
        raise ValueError('music_record_binding_changed')
    record = _json(record_path)
    fingerprint = resolved_plan.get('fingerprint')
    if _sha(_path(resolved_plan['audio_path'])) != fingerprint or record.get('sha256') != fingerprint:
        raise ValueError('music_audio_binding_changed')
    credit = {name: _text(record.get(name)) for name in ['artist', 'title', 'source_url', 'license']}
    if (credit != resolved_plan.get('attribution') or credit['license'] != resolved_plan.get('license')
            or credit['source_url'] != resolved_plan.get('source_url')):
        raise ValueError('music_credit_binding_changed')
    changes = [key for key in CHANGES if key in render_changes]
    line = (f"音乐：{credit['title']} / {credit['artist']}\n"
            f"来源：{credit['source_url']}\n许可：{credit['license']}\n"
            f"改动：{'、'.join(CHANGES[key] for key in changes)}。")
    if len(line) > copy_limit:
        raise ValueError('music_attribution_exceeds_platform_copy_limit')
    binding = {'audio_sha256': fingerprint,
               'source_record_sha256': resolved_plan['source_record_sha256'],
               'credit': credit, 'render_changes': changes, 'text': line}
    binding['sha256'] = hashlib.sha256(json.dumps(binding, ensure_ascii=False,
                           sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    previous = formatted.get('music_attribution')
    if previous is not None:
        if previous != binding or not formatted[field].endswith(line) or len(formatted[field]) > copy_limit:
            raise ValueError('reviewed_music_copy_binding_changed')
        return dict(formatted)
    body = formatted[field].rstrip()
    remaining = copy_limit - len(line) - 2
    body = body[:max(0, remaining)].rstrip()
    return dict(formatted, **{field: body+'\n\n'+line if body else line},
                music_attribution=binding)


def assert_music_copy_matches_review(reviewed, publication_copy, *, field='caption'):
    """Call immediately before building uploader args / the native publish packet."""
    if (not isinstance(reviewed, dict) or not isinstance(publication_copy, str)
            or not isinstance(reviewed.get('music_attribution'), dict)
            or reviewed.get(field) != publication_copy
            or not publication_copy.endswith(reviewed['music_attribution'].get('text', '\0'))):
        raise ValueError('music_publication_copy_differs_from_review')
