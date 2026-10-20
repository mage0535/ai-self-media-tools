"""Use the current Hermes process network policy without leaking proxy values."""
from __future__ import annotations
import sys
from pathlib import Path
from urllib.parse import urlsplit

def current_edge_transport(*, isolated_packages: str | None = None) -> dict:
    # Official runtime resolver implements normalization and NO_PROXY matching.
    from agent.process_bootstrap import _get_proxy_for_base_url
    proxy = _get_proxy_for_base_url('https://speech.platform.bing.com')
    if not proxy:
        return {'proxy': None, 'connector_factory': None, 'route_kind': 'current_policy_direct'}
    scheme = urlsplit(proxy).scheme.lower()
    if scheme in {'http', 'https'}:
        return {'proxy': proxy, 'connector_factory': None, 'route_kind': 'current_policy_http_proxy'}
    if scheme not in {'socks5', 'socks5h', 'socks4', 'socks4a'}:
        raise RuntimeError('current_edge_proxy_protocol_unsupported')
    if isolated_packages:
        directory = Path(isolated_packages)
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
            raise RuntimeError('isolated_edge_proxy_dependency_path_invalid')
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    from aiohttp_socks import ProxyConnector, ProxyType
    parts = urlsplit(proxy)
    if not parts.hostname or not parts.port or parts.path not in ('', '/'):
        raise RuntimeError('current_edge_proxy_url_invalid')
    # Explicit rdns preserves SOCKS5h remote DNS; URL/auth remain in memory.
    from urllib.parse import unquote
    def connector_factory():
        return ProxyConnector(proxy_type=ProxyType.SOCKS5 if scheme.startswith('socks5') else ProxyType.SOCKS4,
            host=parts.hostname, port=parts.port,
            username=unquote(parts.username) if parts.username else None,
            password=unquote(parts.password) if parts.password else None,
            rdns=scheme in {'socks5h', 'socks4a'})
    return {'proxy': None, 'connector_factory': connector_factory, 'route_kind': 'current_policy_socks_proxy'}


def normal_proxy_options()->dict:
    """Production caller uses the isolated installed SOCKS dependency target."""
    result=current_edge_transport(isolated_packages='/srv/hermes-worker/staging/edge-current-proxy-runtime-20261014-r1/packages')
    return {k:result[k] for k in ('proxy','connector_factory')}
