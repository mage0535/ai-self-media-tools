"""仅同F8 Root history-reobserve签证上下文的浏览器只读路由；正常调用无变化。"""
import contextlib
import contextvars
import os
from urllib.parse import urlsplit
import re

from .readonly_post_policy_r2 import readonly_post

_CURRENT=contextvars.ContextVar('fixed_f8_history_reobserve_store',default=None)
ACTION='source_history_reobserve'
ALIAS='collect_native_source_inputs__root_history_reobserve'


@contextlib.contextmanager
def scoped_history_collector(store):
    from .source_repair_runtime import active_grant,JOB
    grant=active_grant(store)
    if grant.get('action')!=ACTION or grant.get('alias')!=ALIAS or grant.get('allow_readonly_reobservation') is not True:
        raise PermissionError('actual_signed_readonly_history_reobservation_scope_required')
    payload=grant['policy'].verify(grant['token'],ACTION)
    if payload.get('job_id')!=JOB or payload.get('allow_readonly_reobservation') is not True:
        raise PermissionError('source_history_readonly_reobservation_signature_required')
    marker=_CURRENT.set(store)
    try:yield
    finally:_CURRENT.reset(marker)


def attach_if_scoped(context):
    store=_CURRENT.get()
    if store is None:return False
    from .source_repair_runtime import active_grant
    grant=active_grant(store)
    if grant.get('action')!=ACTION or grant.get('alias')!=ALIAS or grant.get('allow_readonly_reobservation') is not True:
        raise PermissionError('actual_same_store_thread_source_readonly_guard_expired')
    def route_handler(route,request):
        try:
            live=active_grant(store)
            if live is not grant:raise PermissionError('source_readonly_route_scope_changed')
            parsed=urlsplit(request.url)
            method=request.method.upper()
            allowed=False
            if method=='POST':
                allowed=readonly_post(request.url,request.headers.get('content-type',''),request.post_data or '')[0]
            elif method in {'GET','HEAD'}:
                forbidden=re.search(r'/(?:login|logout|signin|signout|sso|oauth|passport|captcha|challenge|publish|upload|delete|submit|update|save|edit|payment|trade)(?:/|$)',parsed.path,re.I)
                forbidden_host=re.search(r'(?:^|\.)(?:passport|sso|login)(?:\.|$)',parsed.hostname or '',re.I)
                allowed=parsed.scheme=='https' and not parsed.username and not parsed.password and not forbidden and not forbidden_host
            if allowed:route.continue_()
            else:route.abort('blockedbyclient')
        except Exception:
            route.abort('blockedbyclient')
    context.route('**/*',route_handler)
    return True
