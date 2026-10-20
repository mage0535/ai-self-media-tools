"""Acquire new, task-bound photographs; this module never grants visual QA or publication."""
import hashlib
import html
import io
import json
import math
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DATA_ROOT = Path('/srv/ai-self-media-tools/data')
LICENSE_URL = 'https://www.pexels.com/license/'
SLOT_IDS = ('cover', 'section-01', 'section-02', 'section-03')
HELP_IDS = ('360042295174', '360042332714', '360042827393')
BINDING_FIELDS = ('job_id', 'current_task_id', 'platform', 'language', 'production_topic',
                  'draft_source_sha256', 'target_copy_ref', 'caption_sha256')


class CurrentVisualMaterialsBlocked(ValueError):
    """A typed capability/evidence failure, never an accepted content result."""


class _HTTPFailure(CurrentVisualMaterialsBlocked):
    def __init__(self, reason, raw, content_type, url, status, headers, complete=True):
        super().__init__(reason)
        self.raw, self.content_type, self.url, self.status = raw, content_type, url, status
        self.headers, self.complete = headers, complete


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {'path': str(path), 'sha256': _sha(raw)}


def _remaining(deadline):
    value = deadline - time.time()
    if not math.isfinite(value) or value <= 0:
        raise CurrentVisualMaterialsBlocked('current_material_original_deadline_exhausted')
    return value


def _official_url(url, host):
    parsed = urllib.parse.urlsplit(str(url))
    if (parsed.scheme != 'https' or parsed.hostname != host or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise CurrentVisualMaterialsBlocked('current_material_official_origin_required')
    return str(url)


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _official_url(newurl, urllib.parse.urlsplit(request.full_url).hostname)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _fetch(url, *, deadline, authorization=None, maximum):
    host = urllib.parse.urlsplit(url).hostname
    if host not in {'api.pexels.com', 'www.pexels.com', 'images.pexels.com', 'help.pexels.com'}:
        raise CurrentVisualMaterialsBlocked('current_material_official_origin_required')
    _official_url(url, host)
    headers = {'User-Agent': 'Mozilla/5.0 ai-self-media-tools/1.0.0', 'Accept-Encoding': 'identity'}
    if authorization is not None:
        if host != 'api.pexels.com':
            raise CurrentVisualMaterialsBlocked('current_material_credential_scope_invalid')
        headers['Authorization'] = authorization
    request = urllib.request.Request(url, headers=headers)
    # Default ProxyHandler deliberately uses the original process proxy environment.
    try:
        with urllib.request.build_opener(_OfficialRedirect()).open(request, timeout=min(12, _remaining(deadline))) as response:
            actual = _official_url(response.geturl(), host)
            raw = response.read(maximum + 1)
            kind = str(response.headers.get('Content-Type', '')).split(';', 1)[0].strip().lower()
            status = response.getcode()
            safe_headers = {k: response.headers[k] for k in ('Content-Type', 'Content-Length', 'Server', 'CF-Ray', 'Retry-After') if k in response.headers}
    except urllib.error.HTTPError as error:
        with error:
            raw = error.read(maximum + 1)
            actual = _official_url(error.geturl(), host)
            kind = str(error.headers.get('Content-Type', '')).split(';', 1)[0].strip().lower()
            safe_headers = {k: error.headers[k] for k in ('Content-Type', 'Content-Length', 'Server', 'CF-Ray', 'Retry-After') if k in error.headers}
            status = error.code
        raise _HTTPFailure('current_material_official_http_' + str(status), raw, kind, actual, status, safe_headers, len(raw) <= maximum) from None
    if status != 200:
        raise _HTTPFailure('current_material_http_not_200', raw, kind, actual, status, safe_headers, len(raw) <= maximum)
    if not raw or len(raw) > maximum:
        raise _HTTPFailure('current_material_http_size_invalid', raw, kind, actual, status, safe_headers, len(raw) <= maximum)
    return raw, kind, actual


def _binding(pipeline, current, target, plan):
    from .target_adaptation import _normal_guard, read_target_adaptation
    from .visual_policy_gate import digest
    if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH') != '0':
        raise CurrentVisualMaterialsBlocked('current_material_NoPub_required')
    if (Path(pipeline.data_dir).resolve() != DATA_ROOT.resolve()
            or Path(pipeline.store.path).resolve() != (DATA_ROOT / 'state.db').resolve()
            or any(p.is_symlink() for p in (DATA_ROOT, *DATA_ROOT.parents))):
        raise CurrentVisualMaterialsBlocked('current_material_canonical_store_required')
    home, task, route, owner = _normal_guard(pipeline, current['id'])
    actual = pipeline.store.get_job(current['id'])
    try:
        expiry = datetime.fromisoformat(str(actual.get('lease_expires_at', '')).replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            raise ValueError('naive lease')
        deadline = expiry.timestamp()
        original = os.environ.get('HERMES_CHANNEL_EXECUTION_DEADLINE_UNIX')
        if original is not None:
            bound = float(original)
            if not math.isfinite(bound):
                raise ValueError('nonfinite original deadline')
            deadline = min(deadline, bound)
    except (ValueError, TypeError, OverflowError):
        raise CurrentVisualMaterialsBlocked('current_material_original_deadline_invalid') from None
    _remaining(deadline)
    expected = {'version', 'job_id', 'current_task_id', 'platform', 'language', 'production_topic',
                'draft_source_sha256', 'target_copy_ref', 'caption_sha256', 'slots'}
    formal = read_target_adaptation(current, 'twitter')
    topic = ((current.get('brief') or {}).get('production_intent') or {}).get('topic') or current.get('topic')
    if (not isinstance(plan, dict) or set(plan) not in (expected, expected | {'role_requests'})
            or plan.get('version') != 'current_visual_scene_selection_v1'
            or not re.fullmatch('[a-f0-9]{16}', str(current.get('id', '')))
            or not re.fullmatch('[a-f0-9]{32}', str(task))
            or actual.get('id') != current['id'] or actual.get('platforms') != ['twitter']
            or actual.get('topic') != current.get('topic') or actual.get('state') != 'generating'
            or actual.get('lease_owner') != owner or current.get('lease_owner') != owner
            or (current.get('draft_meta') or {}).get('language', (current.get('brief') or {}).get('language')) != 'en'
            or any(not isinstance(current.get(k), str) or not current[k].strip() for k in ('title', 'body'))
            or plan.get('job_id') != current['id'] or plan.get('current_task_id') != task
            or plan.get('platform') != 'twitter' or plan.get('language') != 'en'
            or plan.get('production_topic') != topic
            or plan.get('draft_source_sha256') != digest({k: current.get(k) for k in ('title', 'body')})
            or plan.get('target_copy_ref') != formal.get('target_copy_ref')
            or plan.get('caption_sha256') != formal.get('caption_sha256')
            or any(target.get(k) != formal.get(k) for k in ('target_copy_ref', 'caption_sha256', 'caption'))):
        raise CurrentVisualMaterialsBlocked('current_material_current_binding_changed')
    slots = plan.get('slots')
    if not isinstance(slots, list) or len(slots) != 4:
        raise CurrentVisualMaterialsBlocked('current_material_four_slots_required')
    fields = {'id', 'role', 'source_text_sha256', 'background_query', 'background_match_reason'}
    for index, slot in enumerate(slots):
        if (not isinstance(slot, dict) or set(slot) != fields or slot.get('id') != SLOT_IDS[index]
                or slot.get('role') != ('cover' if index == 0 else 'section')
                or not re.fullmatch('[a-f0-9]{64}', str(slot.get('source_text_sha256')))
                or not isinstance(slot.get('background_query'), str) or not 3 <= len(slot['background_query'].strip()) <= 240
                or any(ord(char) < 32 for char in slot['background_query'])
                or not isinstance(slot.get('background_match_reason'), str)
                or not 1 <= len(slot['background_match_reason'].strip()) <= 1000):
            raise CurrentVisualMaterialsBlocked('current_material_slot_invalid')
    if 'role_requests' in plan:
        requests = plan['role_requests']
        if not isinstance(requests, list) or len(requests) != 2:
            raise CurrentVisualMaterialsBlocked('current_material_two_role_requests_required')
        by_slot = {slot['id']: slot for slot in slots[1:]}
        for request, role in zip(requests, ('curious_cat_explorer', 'watchful_dog_guard')):
            if (not isinstance(request, dict) or set(request) != {'role', 'query', 'match_reason', 'scene_bindings'}
                    or request.get('role') != role or not isinstance(request.get('query'), str)
                    or not 3 <= len(request['query'].strip()) <= 240 or any(ord(c) < 32 for c in request['query'])
                    or not isinstance(request.get('match_reason'), str) or not 1 <= len(request['match_reason'].strip()) <= 1000
                    or not isinstance(request.get('scene_bindings'), list) or len(request['scene_bindings']) != 3):
                raise CurrentVisualMaterialsBlocked('current_material_role_request_invalid')
            bindings = request['scene_bindings']
            if [row.get('slot_id') for row in bindings if isinstance(row, dict)] != list(SLOT_IDS[1:]):
                raise CurrentVisualMaterialsBlocked('current_material_role_scene_scope_invalid')
            for row in bindings:
                if (set(row) != {'slot_id', 'source_text_sha256', 'action'}
                        or row['source_text_sha256'] != by_slot[row['slot_id']]['source_text_sha256']
                        or not isinstance(row.get('action'), str) or not row['action'].strip()
                        or row['action'] not in current['body']):
                    raise CurrentVisualMaterialsBlocked('current_material_role_original_action_required')
    return {'home': str(home), 'task': task, 'route': route, 'owner': owner}, deadline


def _photo_id(url):
    parsed = urllib.parse.urlsplit(str(url))
    if parsed.hostname == 'images.pexels.com':
        found = re.match(r'/photos/([0-9]+)/', parsed.path)
    elif parsed.hostname == 'www.pexels.com':
        found = re.search(r'-([0-9]+)/?$', parsed.path)
    else:
        return None
    return found.group(1) if found else None


def _history(data_dir):
    """Only read existing records; never instantiate the writing AssetLedger constructor."""
    used_ids, used_sha, used_md5 = set(), set(), set()
    ledger = data_dir / 'asset_ledger.db'
    if ledger.exists():
        if ledger.is_symlink():
            raise CurrentVisualMaterialsBlocked('current_material_history_unsafe')
        with closing(sqlite3.connect('file:' + str(ledger) + '?mode=ro', uri=True, timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            for sha, url in db.execute('SELECT sha256,source_url FROM asset_uses'):
                used_sha.add(sha)
                identity = _photo_id(url)
                if identity:
                    used_ids.add(identity)
    def visit(value):
        if isinstance(value, list):
            for row in value:visit(row)
        elif isinstance(value, dict):
            sha = value.get('sha256')
            if isinstance(sha, str) and re.fullmatch('[a-f0-9]{64}', sha):
                used_sha.add(sha)
                path = value.get('path')
                if isinstance(path, str) and Path(path).suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}:
                    photo = Path(path)
                    if photo.is_file() and photo.resolve().is_relative_to(data_dir.resolve()):
                        if photo.is_symlink() or photo.stat().st_size > 16 * 1024 * 1024:
                            raise CurrentVisualMaterialsBlocked('current_material_history_unsafe')
                        raw = photo.read_bytes()
                        if _sha(raw) != sha:
                            raise CurrentVisualMaterialsBlocked('current_material_history_original_changed')
                        used_md5.add(hashlib.md5(raw).hexdigest())
            identity = str(value.get('photo_id') or '')
            if re.fullmatch('[0-9]+', identity):used_ids.add(identity)
            for key in ('source_url', 'photo_page_url', 'download_url'):
                identity = _photo_id(value.get(key))
                if identity:used_ids.add(identity)
            for row in value.values():
                if isinstance(row, (dict, list)):visit(row)
    matches = []
    for path in data_dir.rglob('*.json'):
        name = path.name.lower()
        if any(word in name for word in ('pool', 'source-receipt', 'download')) or name == 'asset_provenance.json':
            matches.append(path)
            if len(matches) > 10000:
                raise CurrentVisualMaterialsBlocked('current_material_history_inventory_limit')
    for path in matches:
        if any(p.is_symlink() for p in (path, *path.parents)) or not 0 < path.stat().st_size <= 4 * 1024 * 1024:
            raise CurrentVisualMaterialsBlocked('current_material_history_unsafe')
        visit(json.loads(path.read_bytes()))
    return used_ids, used_sha, used_md5


def _help_url(identity):
    return 'https://help.pexels.com/api/v2/help_center/en-us/articles/' + identity + '.json'


def _help_article(raw, identity, observed):
    try:
        article = json.loads(raw)['article']
        url = article['html_url'];_official_url(url, 'help.pexels.com')
        updated = datetime.fromisoformat(article['updated_at'].replace('Z', '+00:00'))
        stamp = datetime.fromisoformat(observed.replace('Z', '+00:00'))
        if (type(article.get('id')) is not int or article['id'] != int(identity)
                or not urllib.parse.urlsplit(url).path.startswith('/hc/en-us/articles/' + identity + '-')
                or article.get('draft') is not False or article.get('outdated') is not False
                or updated.tzinfo is None or stamp.tzinfo is None or updated > stamp
                or not isinstance(article.get('body'), str) or not article['body'].strip()):
            raise ValueError('article identity')
        text = html.unescape(re.sub('<[^>]+>', ' ', article['body'])).casefold()
        required = {'360042295174': ('pexels license', 'free', 'personal and commercial'),
                    '360042332714': ('endorsement', 'unaltered', 'redistribute', 'trade-mark'),
                    '360042827393': ('significant creative changes', 'background', 'own content')}[identity]
        if not all(word in text for word in required):raise ValueError('license contents')
        return article
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise CurrentVisualMaterialsBlocked('current_material_official_help_license_unproven') from None


def _photo_pair(search, details, identity):
    try:
        candidates = [row for row in search['photos'] if type(row.get('id')) is int and row['id'] == int(identity)]
        if len(candidates) != 1 or type(details.get('id')) is not int or details['id'] != int(identity):
            raise ValueError('native id')
        selected = candidates[0]
        if any(selected.get(k) != details.get(k) for k in ('id', 'url', 'photographer', 'src')):
            raise ValueError('search detail mismatch')
        _official_url(details['url'], 'www.pexels.com')
        if (_photo_id(details['url']) != identity or not urllib.parse.urlsplit(details['url']).path.startswith('/photo/')
                or not isinstance(details.get('photographer'), str) or not details['photographer'].strip()
                or not isinstance(details.get('src'), dict)):
            raise ValueError('native metadata')
        return details
    except (KeyError, TypeError, ValueError):
        raise CurrentVisualMaterialsBlocked('current_material_official_photo_api_pair_changed') from None


def validate_current_licensed_photo(background, expected_binding):
    """Read-only verification of v2 first-party API evidence; grants no semantic/QA pass."""
    try:
        if set(expected_binding) != set(BINDING_FIELDS):raise ValueError('binding fields')
        task = expected_binding['current_task_id'];job = expected_binding['job_id'];draft = expected_binding['draft_source_sha256']
        if (not re.fullmatch('[a-f0-9]{32}', str(task)) or not re.fullmatch('[a-f0-9]{16}', str(job))
                or not re.fullmatch('[a-f0-9]{64}', str(draft))):raise ValueError('binding identity')
        directory = DATA_ROOT / 'quality_runtime' / 'current-visual-materials' / task / (job + '-' + draft[:20])
        def pinned(ref, maximum=4 * 1024 * 1024):
            if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:raise ValueError('pin shape')
            path = Path(ref['path'])
            if (not path.is_absolute() or '..' in path.parts or path.resolve() != path
                    or path.parent != directory or any(p.is_symlink() for p in (path, *path.parents))):
                raise ValueError('private task path')
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_BINARY', 0))
            try:
                stat = os.fstat(fd)
                if hasattr(os, 'getuid') and (stat.st_uid != 0 or stat.st_mode & 0o077 or stat.st_nlink != 1):
                    raise ValueError('private file metadata')
                if not 0 < stat.st_size <= maximum:raise ValueError('pin size')
                raw = os.read(fd, stat.st_size + 1)
            finally:os.close(fd)
            if len(raw) != stat.st_size or _sha(raw) != ref['sha256']:raise ValueError('original bytes')
            return raw
        def capture(ref, url, content_type):
            record = json.loads(pinned(ref))
            host = urllib.parse.urlsplit(url).hostname
            if (record.get('source_url') != url or _official_url(record.get('actual_url'), host) != url
                    or record.get('http_status') != 200 or record.get('response_complete') is not True
                    or record.get('content_type') != content_type or record.get('current_binding') != expected_binding):
                raise ValueError('native response identity')
            stamp = datetime.fromisoformat(record['observed_utc'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:raise ValueError('response observation')
            raw = pinned(record['raw_ref'], 16 * 1024 * 1024)
            if record.get('bytes') != len(raw) or record.get('sha256') != _sha(raw):raise ValueError('response original')
            return raw, record
        receipt = json.loads(pinned(background['source_receipt_ref']))
        if (receipt.get('version') != 'licensed_real_scene_photo_receipt_v2'
                or receipt.get('evidence_kind') != 'pexels_first_party_api_and_help_v1'
                or receipt.get('current_binding') != expected_binding or receipt.get('current_job_id') != job
                or receipt.get('current_task_id') != task or receipt.get('source_kind') != 'licensed_real_scene_photo'
                or receipt.get('file') != {k: background[k] for k in ('path', 'sha256')}
                or receipt.get('photo_id') != background.get('photo_id')
                or background.get('source_kind') != 'licensed_real_scene_photo'
                or background.get('rights_cleared') is not True or background.get('real_scene') is not True):
            raise ValueError('receipt current identity')
        source = receipt['source'];rights = receipt['rights_provenance'];identity = receipt['photo_id']
        if (source.get('provider') != 'pexels' or source.get('license_url') != LICENSE_URL
                or rights.get('license_url') != LICENSE_URL
                or rights.get('source_evidence_ref') != source.get('photo_api_evidence_ref')
                or background.get('source_url') != source.get('photo_page_url')):
            raise ValueError('first party sources')
        refs = source['license_help_evidence_refs']
        if not isinstance(refs, list) or [r.get('article_id') for r in refs] != list(HELP_IDS):raise ValueError('license set')
        index = json.loads(pinned(source['license_evidence_ref']))
        if (index.get('version') != 'pexels_first_party_help_license_v1' or index.get('current_binding') != expected_binding
                or index.get('article_refs') != refs):raise ValueError('license index')
        for ref in refs:
            raw, record = capture(ref['pin'], _help_url(ref['article_id']), 'application/json')
            _help_article(raw, ref['article_id'], record['observed_utc'])
        search_record = json.loads(pinned(source['search_evidence_ref']));search_url = search_record['source_url']
        _official_url(search_url, 'api.pexels.com');parsed = urllib.parse.urlsplit(search_url)
        query = urllib.parse.parse_qs(parsed.query)
        if (parsed.path != '/v1/search' or query != {'query': [source['search_query']], 'per_page': ['5'], 'orientation': ['portrait']}):
            raise ValueError('search original query')
        search_raw, _ = capture(source['search_evidence_ref'], search_url, 'application/json')
        api_raw, _ = capture(source['photo_api_evidence_ref'], 'https://api.pexels.com/v1/photos/' + identity, 'application/json')
        photo = _photo_pair(json.loads(search_raw), json.loads(api_raw), identity)
        if photo['url'] != source['photo_page_url'] or photo['photographer'] != source['photographer']:
            raise ValueError('photo metadata')
        download = source['download_url'];_official_url(download, 'images.pexels.com')
        if (download not in photo['src'].values() or not re.fullmatch('/photos/' + identity + '/pexels-photo-' + identity + r'\.jpeg', urllib.parse.urlsplit(download).path)):
            raise ValueError('native download identity')
        downloads = json.loads(pinned(source['download_evidence_ref']))
        if downloads.get('current_binding') != expected_binding:raise ValueError('download scope')
        rows = [r for r in downloads['records'] if r.get('photo_id') == identity and r.get('source_url') == download]
        if len(rows) != 1:raise ValueError('download original row')
        row = rows[0];raw, _ = capture(row['download_evidence_ref'], download, 'image/jpeg')
        photo_raw = pinned(receipt['file'], 16 * 1024 * 1024)
        if (raw != photo_raw or row.get('bytes') != len(raw) or row.get('sha256') != _sha(raw)
                or row.get('http_status') != 200):raise ValueError('download original bytes')
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'JPEG' or min(image.size) < 500 or list(image.size) != background.get('dimensions'):
                raise ValueError('actual image')
        return receipt
    except (OSError, KeyError, TypeError, ValueError, UnicodeError):
        raise CurrentVisualMaterialsBlocked('current_material_v2_original_evidence_invalid') from None



def _role_photo_metadata_rejection(photo, role):
    """Photo-priority intake filter only; no animal action or illustration QA verdict."""
    species = {'curious_cat_explorer':'cat', 'watchful_dog_guard':'dog'}.get(role)
    if species is None:raise CurrentVisualMaterialsBlocked('current_material_unknown_role')
    description = photo.get('alt')
    if not isinstance(description, str) or not description.strip():return 'official_alt_unknown'
    if not re.search(r'\b' + species + r's?\b', description, re.I):return 'official_alt_has_no_' + species
    if re.search(r'\b(?:drawing|sketch|illustration|painting|cartoon|statue|sculpture|toy|stuffed|plush|figurine|logo|print|poster|t-shirt)\b', description, re.I):
        return 'not_a_living_animal_photo_candidate'
    return None


def acquire_current_visual_scene_pool(pipeline, current, target, scene_plan):
    try:
        identity, deadline = _binding(pipeline, current, target, scene_plan)
    except CurrentVisualMaterialsBlocked:
        raise
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        code = ('current_material_original_deadline_expired' if str(error) == 'normal_target_original_lease_expired'
                else 'current_material_current_authority_unavailable_' + type(error).__name__)
        raise CurrentVisualMaterialsBlocked(code) from None
    from .image_provider import load_secret
    key = load_secret('PEXELS_API_KEY')
    if not isinstance(key, str) or not key.strip():
        raise CurrentVisualMaterialsBlocked('current_material_official_search_credential_missing')
    root = DATA_ROOT / 'quality_runtime' / 'current-visual-materials' / identity['task']
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise CurrentVisualMaterialsBlocked('current_material_private_path_unsafe')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / (current['id'] + '-' + scene_plan['draft_source_sha256'][:20])
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        raise CurrentVisualMaterialsBlocked('current_material_existing_attempt_query_only_no_replay') from None
    binding = {k: scene_plan[k] for k in ('job_id', 'current_task_id', 'platform', 'language', 'production_topic',
                                        'draft_source_sha256', 'target_copy_ref', 'caption_sha256')}
    _write(directory / 'intent.private.json', _canonical(dict(binding, scene_plan_sha256=_sha(_canonical(scene_plan)),
           no_publish=True, automatic_replay=False)))
    def capture(label, url, maximum, authorization=None):
        _remaining(deadline)
        failure = None
        try:
            raw, kind, actual = _fetch(url, deadline=deadline, authorization=authorization, maximum=maximum)
        except _HTTPFailure as error:
            failure = error
            raw, kind, actual = error.raw, error.content_type, error.url
        _official_url(actual, urllib.parse.urlsplit(url).hostname)
        raw_ref = _write(directory / (label + '.raw'), raw)
        record = {'source_url': url, 'actual_url': actual, 'http_status': failure.status if failure else 200, 'content_type': kind,
                  'current_binding': binding,
                  'bytes': len(raw), 'sha256': _sha(raw), 'observed_utc': datetime.now(timezone.utc).isoformat(),
                  'response_headers': failure.headers if failure else {}, 'response_complete': failure.complete if failure else True,
                  'raw_ref': raw_ref, 'body_utf8_preview': raw.decode('utf-8', errors='replace') if kind != 'image/jpeg' else None}
        reference = _write(directory / (label + '.private.json'), _canonical(record))
        if failure:
            raise failure
        return raw, kind, actual, reference
    try:
        used_ids, used_sha, used_md5 = _history(DATA_ROOT)
        help_refs = []
        for article_id in HELP_IDS:
            raw, kind, actual, reference = capture('official-help-' + article_id, _help_url(article_id), 2 * 1024 * 1024)
            if kind != 'application/json':raise CurrentVisualMaterialsBlocked('current_material_official_help_license_unproven')
            _help_article(raw, article_id, json.loads(Path(reference['path']).read_bytes())['observed_utc'])
            help_refs.append({'article_id': article_id, 'pin': reference})
        license_ref = _write(directory / 'official-license-help-index.private.json', _canonical({
            'version': 'pexels_first_party_help_license_v1', 'canonical_license_url': LICENSE_URL,
            'article_refs': help_refs, 'current_binding': binding}))
        assets, role_assets, downloads, pending = [], [], [], []
        requests = list(scene_plan['slots'])
        for role in scene_plan.get('role_requests', []):
            requests.append({'id': role['role'], 'role': role['role'], 'background_query': role['query'],
                             'background_match_reason': role['match_reason'],
                             'source_text_sha256': _sha(_canonical(role['scene_bindings'])), '_role_request': role})
        for slot in requests:
            original_query = slot['background_query'].strip()
            role = (slot.get('_role_request') or {}).get('role')
            queries = [original_query]
            if role:
                species = {'curious_cat_explorer':'cat', 'watchful_dog_guard':'dog'}[role]
                queries = list(dict.fromkeys([original_query, species + ' desk', species]))
            for query_index, current_query in enumerate(queries):
                query = urllib.parse.urlencode({'query': current_query, 'per_page': '5', 'orientation': 'portrait'})
                label = 'search-' + slot['id'] + ('-fallback-' + str(query_index) if query_index else '')
                raw, kind, actual, search_ref = capture(label, 'https://api.pexels.com/v1/search?' + query,
                                                       2 * 1024 * 1024, key)
                if kind != 'application/json':
                    raise CurrentVisualMaterialsBlocked('current_material_search_protocol_invalid')
                search_result = json.loads(raw);rows = search_result.get('photos')
                if not isinstance(rows, list):
                    raise CurrentVisualMaterialsBlocked('current_material_search_protocol_invalid')
                if not role:break
                observations = [{'photo_id':str(photo.get('id') or ''), 'official_alt':photo.get('alt'),
                    'rejection':_role_photo_metadata_rejection(photo, role)} for photo in rows[:5]]
                _write(directory / (label + '.role-metadata.private.json'), _canonical({
                    'role':role, 'query':current_query, 'search_ref':search_ref, 'observations':observations,
                    'metadata_intake_only':True, 'semantic_action_verified':False}))
                rows = [photo for photo in rows[:5] if _role_photo_metadata_rejection(photo, role) is None]
                if rows:break
            if role and not rows:
                raise CurrentVisualMaterialsBlocked('current_material_role_photo_candidate_unavailable')
            chosen = None
            for photo in rows[:5]:
                photo_id = str(photo.get('id') or '')
                if not re.fullmatch('[0-9]+', photo_id) or photo_id in used_ids:continue
                page = photo.get('url');download = next((photo.get('src', {}).get(k) for k in ('large2x', 'large', 'original') if photo.get('src', {}).get(k)), None)
                try:
                    _official_url(page, 'www.pexels.com');_official_url(download, 'images.pexels.com')
                    if (not urllib.parse.urlsplit(page).path.startswith('/photo/') or _photo_id(page) != photo_id
                            or not re.fullmatch('/photos/' + photo_id + '/pexels-photo-' + photo_id + r'\.jpeg', urllib.parse.urlsplit(download).path)):
                        continue
                except (CurrentVisualMaterialsBlocked, ValueError):continue
                api_raw, api_kind, api_actual, page_ref = capture('photo-api-' + slot['id'] + '-' + photo_id,
                    'https://api.pexels.com/v1/photos/' + photo_id, 2 * 1024 * 1024, key)
                if api_kind != 'application/json':raise CurrentVisualMaterialsBlocked('current_material_official_photo_api_protocol_invalid')
                official_photo = _photo_pair(search_result, json.loads(api_raw), photo_id)
                if role and _role_photo_metadata_rejection(official_photo, role) is not None:
                    raise CurrentVisualMaterialsBlocked('current_material_role_photo_api_metadata_changed')
                pixels, image_kind, download_actual, download_ref = capture('download-' + slot['id'] + '-' + photo_id,
                                                                           download, 16 * 1024 * 1024)
                sha, md5 = _sha(pixels), hashlib.md5(pixels).hexdigest()
                if sha in used_sha or md5 in used_md5:continue
                from PIL import Image
                with Image.open(io.BytesIO(pixels)) as image:
                    image.verify()
                with Image.open(io.BytesIO(pixels)) as image:
                    if image_kind != 'image/jpeg' or image.format != 'JPEG' or min(image.size) < 500:
                        raise CurrentVisualMaterialsBlocked('current_material_actual_photo_dimensions_invalid')
                    dimensions = list(image.size)
                if not isinstance(photo.get('photographer'), str) or not photo['photographer'].strip():
                    raise CurrentVisualMaterialsBlocked('current_material_actual_photographer_missing')
                path = directory / (slot['id'] + '-' + photo_id + '.jpg');photo_ref = _write(path, pixels)
                downloads.append({'photo_id': photo_id, 'source_url': download, 'actual_url': download_actual,
                                  'http_status': 200, 'content_type': image_kind, 'bytes': len(pixels), 'sha256': sha,
                                  'download_evidence_ref': download_ref})
                chosen = (photo_id, photo, page, download, page_ref, search_ref, photo_ref, dimensions, md5, current_query)
                used_ids.add(photo_id);used_sha.add(sha);used_md5.add(md5)
                break
            if chosen is None:
                raise CurrentVisualMaterialsBlocked('current_material_distinct_official_photo_candidate_unavailable')
            pending.append((slot, chosen))
        download_ref = _write(directory / 'official-downloads.private.json', _canonical({'version': 'official_photo_http_download_receipt_v1',
                             'records': downloads, 'current_binding': binding}))
        for slot, (photo_id, photo, page, download, page_ref, search_ref, photo_ref, dimensions, md5, current_query) in pending:
            receipt = {'version': 'licensed_real_scene_photo_receipt_v2', 'photo_id': photo_id, 'file': photo_ref,
                       'evidence_kind': 'pexels_first_party_api_and_help_v1',
                       'source_kind': 'licensed_real_scene_photo', 'current_job_id': current['id'], 'current_task_id': identity['task'],
                       'current_binding': binding, 'source_text_sha256': slot['source_text_sha256'],
                       'source': {'provider': 'pexels', 'photographer': photo['photographer'], 'photo_page_url': page,
                                  'download_url': download, 'license_url': LICENSE_URL, 'license_evidence_ref': license_ref,
                                  'download_evidence_ref': download_ref, 'search_evidence_ref': search_ref,
                                  'search_query': current_query, 'photo_api_evidence_ref': page_ref,
                                  'license_help_evidence_refs': help_refs},
                       'rights_provenance': {'license_url': LICENSE_URL, 'source_evidence_ref': page_ref,
                                            'copyright_use_scope': 'method illustration for this current job; no endorsement, actual technical execution or business outcome claimed'},
                       'copyright_license_verified': True, 'real_photo_origin_verified': True,
                       'quality_review_passed': False, 'semantic_match_review_passed': False, 'business_evidence': False}
            if '_role_request' in slot:
                receipt['source_text_binding_kind'] = 'role_scene_bindings_sha256'
                receipt['role_request'] = slot['_role_request']
            receipt_ref = _write(directory / (slot['id'] + '.source-receipt.private.json'), _canonical(receipt))
            background = dict(photo_ref, photo_id=photo_id, asset_name=photo_id, source_kind='licensed_real_scene_photo',
                              source_url=page, license='Pexels License', source_receipt_ref=receipt_ref,
                              match_reason=slot['background_match_reason'], rights_cleared=True, real_scene=True,
                              native_VLM_review_passed=False, dimensions=dimensions, md5=md5)
            if '_role_request' in slot:
                role_assets.append(dict(slot['_role_request'], background=background))
            else:
                assets.append({'slot_id': slot['id'], 'role': slot['role'], 'source_text_sha256': slot['source_text_sha256'], 'background': background})
        for item in assets + role_assets:
            validate_current_licensed_photo(item['background'], binding)
        final_identity, final_deadline = _binding(pipeline, current, target, scene_plan)
        if final_identity != identity or final_deadline < deadline:
            raise CurrentVisualMaterialsBlocked('current_material_authority_changed_during_acquisition')
        _remaining(deadline)
        pool = dict(binding, version='current_task_real_scene_pool_v1', scene_plan_sha256=_sha(_canonical(scene_plan)),
                    assets=assets, role_assets=role_assets, background_history_checked=True, native_quality_passed=False,
                    delivery_acknowledged=False, business_completed=False)
        return _write(directory / 'scene-pool.private.json', _canonical(pool))
    except Exception as error:
        code = str(error) if isinstance(error, CurrentVisualMaterialsBlocked) else 'current_material_acquisition_' + type(error).__name__
        _write(directory / 'failure.private.json', _canonical(dict(binding, state='blocked_no_automatic_replay', reason=code)))
        raise CurrentVisualMaterialsBlocked(code) from None
