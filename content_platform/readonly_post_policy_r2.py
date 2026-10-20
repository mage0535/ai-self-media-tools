"""官方前端已证三条读取POST；不允许角色/资料/发表/交易修改。"""
import json
from urllib.parse import urlsplit

AUTH_FIELD = "kuaishou.web.cp.api_ph"
CURRENT = "/rest/v2/creator/pc/authority/account/current"
KSWITCH = "/rest/v2/creator/pc/frontend/kswitch/config"
HOTSPOT = "/rest/bamboo/pc/hotspot/show"
READONLY = {CURRENT, KSWITCH, HOTSPOT}


def readonly_post(url, content_type, body):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "cp.kuaishou.com" or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.path not in READONLY):
        return False, "post_endpoint_not_source_proven_readonly", []
    if len(body.encode()) > 16384 or not content_type.casefold().startswith("application/json"):
        return False, "post_content_type_or_size_not_proven", []
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return False, "post_body_not_json_object", []
    if not isinstance(data, dict):
        return False, "post_body_not_json_object", []
    fields = sorted(data)
    if AUTH_FIELD in data and (not isinstance(data[AUTH_FIELD], str) or len(data[AUTH_FIELD]) > 4096):
        return False, "post_common_auth_field_shape_mismatch", fields
    payload = {k: v for k, v in data.items() if k != AUTH_FIELD}
    expected = {"keys": []} if parsed.path == KSWITCH else {}
    if payload != expected:
        return False, "post_body_differs_from_actual_frontend_getter", fields
    return True, "source_proven_readonly_query", fields
