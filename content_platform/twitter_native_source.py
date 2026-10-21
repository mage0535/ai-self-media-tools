"""Read public X posts through the operator's existing browser state.

Only official responses produced by ordinary page navigation are consumed.
Missing metrics stay missing; this module never certifies editorial quality.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from urllib.parse import urlsplit,parse_qs,quote


OPERATIONS = {"TweetDetail", "TweetResultByRestId", "UserTweets"}
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
MAX_RESPONSE_BYTES = 2_097_152


def _timestamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observation_timestamp_invalid") from exc
    if stamp.utcoffset() is None:
        raise ValueError("observation_timestamp_requires_offset")
    return stamp.isoformat()


def _error_text(error):
    # Browser diagnostics can echo a proxy URL; never emit its user information.
    return re.sub(r"(https?|socks5h?)://[^/\s@]+@", r"\1://[REDACTED]@",
                  f"{type(error).__name__}: {str(error)}")[:240]


def _profile_handle(url):
    parsed = urlsplit(str(url))
    handle = parsed.path.strip("/")
    if (parsed.scheme != "https" or parsed.hostname not in {"x.com", "twitter.com"}
            or parsed.query or parsed.fragment or not HANDLE.fullmatch(handle)):
        raise ValueError("configured_native_profile_url_required")
    return handle


def _official_operation(url, operations=OPERATIONS):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"x.com", "twitter.com"}
            or parsed.username or parsed.password or parsed.port
            or not parsed.path.startswith("/i/api/graphql/")
            or parsed.path.rsplit("/", 1)[-1] not in operations):
        raise ValueError("official_tweet_response_required")
    return parsed.path


def _count(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    raise ValueError("metric_invalid")


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _author(tweet):
    user = ((tweet.get("core") or {}).get("user_results") or {}).get("result") or {}
    return (user.get("core") or {}).get("screen_name") or (user.get("legacy") or {}).get("screen_name")


def _search_timeline_entries(payload):
    """Actual response entry order; neither an inferred popularity rank nor a metric."""
    entries=[];seen=set()
    for row in _walk(payload):
        identity=str(row.get('entryId')or'')
        if not re.fullmatch(r'tweet-[0-9]+',identity)or identity in seen:continue
        seen.add(identity);entries.append({'entry_id':identity,'content_id':identity[6:],
            'response_order':len(entries),'sort_index':row.get('sortIndex')})
    return entries


def normalize_tweet_response(raw, *, requested_handle, response_url,
                             http_status, observed_at, raw_path=None, query_binding=None):
    """Normalize preserved official JSON; no inferred identities or numbers."""
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("whole_tweet_response_size_invalid")
    if http_status != 200:
        raise ValueError("http_status_not_success")
    api_path = _official_operation(response_url, {"SearchTimeline"} if query_binding is not None else OPERATIONS)
    if query_binding is not None:
        variables=json.loads(parse_qs(urlsplit(response_url).query).get("variables",["{}"]) [0])
        if variables.get("rawQuery")!=query_binding:raise ValueError("official_search_query_binding_changed")
    if not HANDLE.fullmatch(str(requested_handle)):
        raise ValueError("requested_handle_invalid")
    _timestamp(observed_at)
    payload = json.loads(raw)
    rows, rejected, seen = [], [], set()
    digest = hashlib.sha256(raw).hexdigest()
    for tweet in _walk(payload):
        if tweet.get("__typename") != "Tweet":
            continue
        author = _author(tweet)
        if not author:
            rejected.append("author_missing")
            continue
        if author.casefold() != requested_handle.casefold():
            rejected.append("author_mismatch")
            continue
        legacy = tweet.get("legacy") or {}
        identifier = tweet.get("rest_id")
        if not isinstance(identifier, str) or not identifier.isdigit() or legacy.get("id_str") != identifier:
            rejected.append("post_identity_missing_or_mismatch")
            continue
        if identifier in seen:
            continue
        note = (((tweet.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {})
        text = note.get("text") or legacy.get("full_text")
        if not isinstance(text, str) or not text.strip():
            rejected.append("whole_post_text_missing")
            continue
        metrics = {}
        try:
            views = tweet.get("views") or {}
            if "count" in views:
                metrics["views"] = _count(views["count"])
            for output, source in (("likes", "favorite_count"), ("comments", "reply_count"),
                                   ("shares", "retweet_count"), ("favorites", "bookmark_count")):
                if source in legacy:
                    metrics[output] = _count(legacy[source])
        except ValueError:
            rejected.append("metric_invalid")
            continue
        if not metrics:
            rejected.append("metrics_missing")
            continue
        quote = (tweet.get("quoted_status_result") or {}).get("result") or {}
        if quote.get("__typename") == "TweetWithVisibilityResults":
            quote = quote.get("tweet") or {}
        quote_text = (quote.get("legacy") or {}).get("full_text") or ""
        try:
            published = datetime.strptime(legacy["created_at"], "%a %b %d %H:%M:%S %z %Y").isoformat()
        except (KeyError, ValueError, TypeError):
            rejected.append("published_timestamp_missing")
            continue
        row = {
            "platform": "twitter", "source": "native.twitter_browser",
            "author": author, "account": author, "content_id": identifier,
            "canonical_url": f"https://x.com/{author}/status/{identifier}",
            "url": f"https://x.com/{author}/status/{identifier}",
            "title": text, "summary": text if query_binding is not None else text + ("\nQuoted public source:\n" + quote_text if quote_text else ""),
            "published_at": published, "observed_at": observed_at,
            "raw_response_hash": digest, "raw_response_kind": "official_browser_api_json",
            "official_api_path": api_path, "source_record_id": identifier,
            "query": f"https://x.com/{requested_handle}", "metrics": dict(metrics),
            **metrics,
        }
        if query_binding is not None and quote_text:
            row["quoted_source_text"]=quote_text
            row["quoted_source_text_sha256"]=hashlib.sha256(quote_text.encode()).hexdigest()
            row["quoted_source_contributes_to_primary_qualification"]=False
        if raw_path is not None:
            row["raw_response_path"] = str(raw_path)
        rows.append(row)
        seen.add(identifier)
    return {"items": rows, "rejected": rejected, "status": "ok" if rows else "unavailable"}


def normalize_account_response(raw, *, requested_handle, response_url, http_status, observed_at):
    """Extract account numbers from the actual official user response."""
    _official_operation(response_url, {"UserByScreenName", "TweetDetail", "TweetResultByRestId"})
    _timestamp(observed_at)
    if http_status != 200 or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("actual_account_response_unavailable")
    for user in _walk(json.loads(raw)):
        if user.get("__typename") != "User":
            continue
        author = (user.get("core") or {}).get("screen_name") or (user.get("legacy") or {}).get("screen_name")
        if not author or author.casefold() != requested_handle.casefold():
            continue
        metrics = {}
        relationships = user.get("relationship_counts") or {}
        tweets = user.get("tweet_counts") or {}
        for output, values, key in (("followers", relationships, "followers"),
                                   ("following", relationships, "following"),
                                   ("posts", tweets, "tweets")):
            if key in values:
                metrics[output] = _count(values[key])
        if metrics:
            return {"account": author, "account_metrics": metrics, "collected_at": observed_at,
                    "source_url": f"https://x.com/{author}", "raw_response_hash": hashlib.sha256(raw).hexdigest()}
    raise ValueError("actual_account_metrics_missing")


def _cookie_state(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data.get("cookies", []) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise ValueError("existing_x_cookie_state_invalid")
    cookies = []
    for item in raw:
        if not isinstance(item, dict) or str(item.get("domain", "")).lstrip(".") not in {"x.com", "twitter.com"}:
            continue
        cookie = {name: item[name] for name in ("name", "value", "domain") if name in item}
        if len(cookie) != 3:
            continue
        cookie.update(path=item.get("path") or "/", secure=bool(item.get("secure")),
                      httpOnly=bool(item.get("httpOnly")),
                      expires=float(item.get("expires", item.get("expirationDate", -1)) or -1))
        same_site = str(item.get("sameSite") or "Lax").capitalize()
        cookie["sameSite"] = same_site if same_site in {"Strict", "Lax", "None"} else "Lax"
        cookies.append(cookie)
    if not cookies:
        raise ValueError("existing_x_cookie_state_missing")
    return {"cookies": cookies, "origins": []}


def _write_raw(folder, raw):
    digest = hashlib.sha256(raw).hexdigest()
    target = folder / (digest + ".json")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != raw:
            raise ValueError("raw_capture_identity_changed")
        return target
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return target


def _private_file(path):
    path = Path(path)
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("native_account_snapshot_private_file_required")
    return path.read_bytes()


def read_native_account_snapshot(reference, *, expected_profile_url, now=None):
    """Re-read exact captured API bytes; expose only actually observed fields."""
    options = reference if isinstance(reference, dict) else {"path": reference}
    path = Path(options["path"])
    header_raw = _private_file(path)
    if len(header_raw) > 16384:
        raise ValueError("native_account_snapshot_header_size_invalid")
    snapshot = json.loads(header_raw)
    if snapshot.get("version") != "native_x_account_snapshot_v1":
        raise ValueError("native_account_snapshot_version_invalid")
    expected = _profile_handle(expected_profile_url)
    if str(snapshot.get("account") or "").casefold() != expected.casefold():
        raise ValueError("native_account_snapshot_profile_mismatch")
    stamp = datetime.fromisoformat(_timestamp(snapshot["collected_at"])).astimezone(timezone.utc)
    current = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    maximum = options.get("max_age_seconds", 900)
    if type(maximum) is not int or not 1 <= maximum <= 3600:
        raise ValueError("native_account_snapshot_age_contract_invalid")
    age = (current - stamp).total_seconds()
    if age < 0:
        raise ValueError("native_account_snapshot_observation_in_future")
    if age > maximum:
        raise ValueError("native_account_snapshot_observation_expired")
    producer = snapshot["capture_program"]
    current_program_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if (producer.get("sha256") != current_program_sha
            or hashlib.sha256(Path(producer["path"]).read_bytes()).hexdigest() != current_program_sha):
        raise ValueError("native_account_snapshot_capture_program_changed")
    raw = _private_file(snapshot["raw_response_path"])
    if hashlib.sha256(raw).hexdigest() != snapshot.get("raw_response_hash"):
        raise ValueError("native_account_snapshot_raw_response_changed")
    actual = normalize_account_response(
        raw, requested_handle=expected, response_url=snapshot["api_response_url"],
        http_status=snapshot["http_status"], observed_at=snapshot["collected_at"],
    )
    if actual["account_metrics"] != snapshot.get("account_metrics"):
        raise ValueError("native_account_snapshot_declared_metrics_changed")
    observed = actual["account_metrics"]
    return {"status": "ok", "account": actual["account"], "source_url": actual["source_url"],
            "collected_at": actual["collected_at"], "account_metrics": observed,
            "metric_scope": "account_snapshot", "native_snapshot_path": str(path),
            "native_snapshot_sha256": hashlib.sha256(header_raw).hexdigest(),
            "raw_response_hash": actual["raw_response_hash"],
            "raw_response_path": snapshot["raw_response_path"],
            "missing_metrics": [name for name in ("views", "likes", "comments", "shares", "saves")
                                if name not in observed]}


def _save_account_snapshot(path, metrics):
    """Retain the immutable capture header and atomically update its live pointer."""
    destination = Path(path)
    if destination.is_symlink():
        raise ValueError("native_account_snapshot_output_symlink")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    program = Path(__file__).resolve()
    snapshot = {"version": "native_x_account_snapshot_v1", **metrics,
                "capture_program": {"path": str(program), "sha256": hashlib.sha256(program.read_bytes()).hexdigest()}}
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
    immutable = _write_raw(Path(metrics["raw_response_path"]).parent, raw)
    fd, temporary = tempfile.mkstemp(prefix=".native-account-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"path": str(destination), "sha256": hashlib.sha256(raw).hexdigest(),
            "immutable_capture_header": str(immutable)}


class TwitterNativeBrowserAdapter:
    """One bounded browser read; never retries verification or creates accounts."""

    def collect(self, config):
        started = time.monotonic()
        self._account_collection_exception=None
        self._query_sources=[];self._query_capture_dir=None
        try:
            result = asyncio.run(self._collect(dict(config or {})))
        except Exception as error:
            if (config or {}).get('account_only') is True:
                self._account_collection_exception=error
            result = {"items": [], "sources": [], "status": "unavailable",
                      "reason": _error_text(error)}
            if (config or {}).get("query") is not None:
                result["sources"]=self._query_sources
                if self._query_capture_dir is not None:
                    diagnostic={"status":"failed","error_type":type(error).__name__,"exception":str(error)[:65536],
                        "elapsed_seconds":round(time.monotonic()-started,3),"sources":self._query_sources,"partial_items_qualified":False}
                    ref=_write_raw(self._query_capture_dir,json.dumps(diagnostic,ensure_ascii=False).encode())
                    result["failure_diagnostic_ref"]={"path":str(ref),"sha256":hashlib.sha256(ref.read_bytes()).hexdigest()}
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["source"] = "native.twitter_browser"
        return result

    def collect_account_metrics(self, account_config):
        """Run before the hot-source phase, so an expired cache cannot deadlock it."""
        reference = account_config["native_account_snapshot"]
        options = reference if isinstance(reference, dict) else {"path": reference}
        config = {
            "account_only": True, "accounts": [], "account_config": dict(account_config),
            "collect_own_account_metrics": True,
            "own_account_snapshot_output": options["path"],
            "raw_response_dir": str(Path(options["path"]).parent / "account-captures"),
            # A cold browser through the slow egress timed out at 18 s twice (10-20 00:05Z, 04:26Z); the owned-account
            # caller already requires >= 75 s left before this capture.
            "max_total_seconds": 60, "account_timeout_seconds": 45,
        }
        report = self.collect(config)
        if not report.get("own_account_snapshot"):
            failure=ValueError("native_account_capture_unavailable: " + str(report.get("reason") or report.get("sources"))[:200])
            original=self._account_collection_exception
            if original is not None:
                # performance_collectors既有异常分支只把这些属性存Root600原件；
                # 完整Chrome日志不放report.reason/exception.args/公开traceback。
                failure.stdout=f'{type(original).__name__}: {str(original)}'
                failure.stderr=getattr(original,'stderr',None)
                failure.native_error_type=type(original).__name__
            raise failure from None
        return read_native_account_snapshot(
            reference, expected_profile_url=account_config["public_profile_url"]
        )

    def collect_query(self,account_config,query,raw_response_dir):
        """一次普通官方搜索；不登录、不改cookie、不把自号作为竞榜。"""
        if not isinstance(query,str) or not 1<=len(query)<=400 or any(ord(c)<32 for c in query):
            raise ValueError('bounded_native_search_query_required')
        return self.collect({'query':query,'accounts':[],'account_config':dict(account_config),
            'raw_response_dir':str(raw_response_dir),'max_total_seconds':45,'account_timeout_seconds':20})

    async def _collect(self, config):
        from playwright.async_api import async_playwright
        handles = config.get("accounts") or []
        query=config.get('query')
        minimum = 0 if config.get("account_only") is True or query is not None else 3
        if (not isinstance(handles, list) or not minimum <= len(handles) <= 8
                or any(not HANDLE.fullmatch(str(handle)) for handle in handles)
                or len({handle.casefold() for handle in handles}) != len(handles)):
            raise ValueError("distinct_configured_x_accounts_required")
        total = float(config.get("max_total_seconds", 45))
        timeout = float(config.get("account_timeout_seconds", 18))
        if not 10 <= total <= 60 or not 5 <= timeout <= 45:
            raise ValueError("bounded_x_source_budget_required")
        if config.get("account_only") is True or query is not None:
            account_config = config["account_config"]
        else:
            performance = json.loads(Path(config["performance_collector_config"]).read_text(encoding="utf-8"))
            account_config = performance.get("x") or performance.get("twitter") or {}
        state = _cookie_state(account_config.get("state_file") or account_config.get("cookie_file") or "")
        own_handle = _profile_handle(account_config["public_profile_url"]) if config.get("collect_own_account_metrics") or query is not None else None
        raw_root = Path(config["raw_response_dir"])
        if raw_root.is_symlink():
            raise ValueError("raw_capture_directory_symlink")
        raw_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        capture_dir = Path(tempfile.mkdtemp(prefix="capture-", dir=raw_root))
        if query is not None:self._query_capture_dir=capture_dir
        proxy = next((os.environ.get(key) for key in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy")
                      if os.environ.get(key)), "")
        launch = {"headless": True, "env": {
            **os.environ,
            "HOME": str(capture_dir),
            "XDG_CONFIG_HOME": str(capture_dir / "browser-config"),
            "XDG_CACHE_HOME": str(capture_dir / "browser-cache"),
        }}
        if config.get("executable_path"):
            launch["executable_path"] = config["executable_path"]
        elif os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            # The runtime supplies a readonly installed Chromium, which can differ
            # from the Python package's optional headless-shell revision.
            installed = list(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]).glob("chromium-*/chrome-linux64/chrome"))
            if len(installed) != 1:
                raise ValueError("unique_existing_runtime_chromium_required")
            launch["executable_path"] = str(installed[0])
        if proxy:
            parsed = urlsplit(proxy.replace("socks5h://", "socks5://"))
            launch["proxy"] = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
            if parsed.username:
                launch["proxy"]["username"] = parsed.username
            if parsed.password:
                launch["proxy"]["password"] = parsed.password
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch)
            context = await browser.new_context(storage_state=state)
            try:
                operation=(self._read_query(context,query,timeout,capture_dir,own_handle) if query is not None
                           else self._read_accounts(context,handles,timeout,capture_dir,own_handle))
                result = await asyncio.wait_for(operation,timeout=total)
                if result.get("own_account_metrics") and config.get("own_account_snapshot_output"):
                    result["own_account_snapshot"] = _save_account_snapshot(
                        config["own_account_snapshot_output"], result["own_account_metrics"]
                    )
                return result
            finally:
                await context.close()
                await browser.close()

    async def _read_query(self,context,query,timeout,capture_dir,own_handle):
        page=await context.new_page();rows=[];sources=[];pending=[]
        self._query_sources=sources
        async def capture(response):
            path=urlsplit(response.url).path
            if not path.endswith('/SearchTimeline') or '/i/api/graphql/' not in path:return
            stamp=datetime.now(timezone.utc).isoformat()
            report={'source':'native.twitter_browser','api_path':path,'http_status':response.status,'observed_at':stamp,
                'query_sha256':hashlib.sha256(query.encode()).hexdigest(),'request_sha256':hashlib.sha256(response.url.encode()).hexdigest()};sources.append(report)
            try:
                _official_operation(response.url,{'SearchTimeline'})
                variables=json.loads(parse_qs(urlsplit(response.url).query).get('variables',['{}'])[0])
                if variables.get('rawQuery')!=query:raise ValueError('official_search_query_binding_changed')
                raw=await response.body()
                if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('whole_search_response_size_invalid')
                raw_path=_write_raw(capture_dir,raw)
                report.update(raw_response_hash=hashlib.sha256(raw).hexdigest(),raw_response_path=str(raw_path),bytes=len(raw))
                payload=json.loads(raw);selected={}
                receipt={'version':'native_twitter_search_capture_v1','request_url':response.url,
                    'request_sha256':hashlib.sha256(response.url.encode()).hexdigest(),'api_path':path,
                    'request_variables':variables,'query_binding':query,'query_sha256':hashlib.sha256(query.encode()).hexdigest(),
                    'http_status':response.status,'observed_at':stamp,
                    'capture_program':{'path':str(Path(__file__).resolve()),'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                    'response_ref':{'path':str(raw_path),'sha256':hashlib.sha256(raw).hexdigest()},
                    'timeline_entries':_search_timeline_entries(payload),
                    'use':'actual_native_selection_parameters_not_a_viral_result_certificate'}
                receipt_raw=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
                receipt_path=_write_raw(capture_dir,receipt_raw)
                receipt_ref={'path':str(receipt_path),'sha256':hashlib.sha256(receipt_raw).hexdigest()}
                report['native_search_capture_ref']=receipt_ref
                for entry in _walk(payload):
                    identifier=str(entry.get('entryId') or '')
                    if not re.fullmatch(r'tweet-[0-9]+',identifier):continue
                    item=(entry.get('content')or{}).get('itemContent')or{}
                    tweet=(item.get('tweet_results')or{}).get('result')or{}
                    if tweet.get('__typename')=='TweetWithVisibilityResults':tweet=tweet.get('tweet')or{}
                    author=_author(tweet);tid=str(tweet.get('rest_id')or'')
                    if not HANDLE.fullmatch(str(author or '')) or tid!=identifier[6:] or author.casefold()==own_handle.casefold():continue
                    selected[tid]=author
                observed_rows=[]
                for tid,author in selected.items():
                    normalized=normalize_tweet_response(raw,requested_handle=author,response_url=response.url,
                        http_status=response.status,observed_at=stamp,raw_path=raw_path,query_binding=query)
                    exact=[row for row in normalized['items'] if row['content_id']==tid]
                    if len(exact)!=1:continue
                    row=exact[0];row.update(query=query,query_sha256=hashlib.sha256(query.encode()).hexdigest(),
                        source_operation='SearchTimeline',own_account_excluded=True,native_search_capture_ref=receipt_ref)
                    observed_rows.append(row)
                rows.extend(observed_rows)
                report.update(status='ok'if observed_rows else'empty',count=len(observed_rows),raw_response_hash=hashlib.sha256(raw).hexdigest(),
                    raw_response_path=str(raw_path),bytes=len(raw))
            except Exception as error:report.update(status='failed',count=0,reason=_error_text(error))
        page.on('response',lambda response:pending.append(asyncio.create_task(capture(response))))
        try:
            await page.goto('https://x.com/search?q='+quote(query,safe='')+'&src=typed_query&f=top',wait_until='domcontentloaded',timeout=int(timeout*1000))
            await page.wait_for_selector('[data-testid="tweet"]',timeout=int(timeout*1000))
            if pending:await asyncio.gather(*pending,return_exceptions=True)
        finally:await page.close()
        unique={row['canonical_url']:row for row in rows}
        return {'items':list(unique.values()),'sources':sources,'status':'ok'if unique else'unavailable',
            'query':query,'query_sha256':hashlib.sha256(query.encode()).hexdigest(),'editorial_quality_certified':False,
            'own_account_used_as_benchmark':False}

    async def _read_accounts(self, context, handles, timeout, capture_dir, own_handle=None):
        semaphore = asyncio.Semaphore(3)

        async def read(handle):
            async with semaphore:
                page = await context.new_page()
                rows, sources, pending, own_metrics = [], [], [], []
                metrics_ready = asyncio.Event()

                async def capture(response):
                    path = urlsplit(response.url).path
                    operation = path.rsplit("/", 1)[-1]
                    if operation not in OPERATIONS | {"UserByScreenName"} or "/i/api/graphql/" not in path:
                        return
                    stamp = datetime.now(timezone.utc).isoformat()
                    source = {"source": "native.twitter_browser", "account": handle,
                              "api_path": path, "http_status": response.status, "observed_at": stamp}
                    sources.append(source)
                    try:
                        raw = await response.body()
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise ValueError("whole_tweet_response_size_invalid")
                        raw_path = _write_raw(capture_dir, raw)
                        if operation == "UserByScreenName":
                            if own_handle and handle.casefold() == own_handle.casefold():
                                metrics = normalize_account_response(
                                    raw, requested_handle=handle, response_url=response.url,
                                    http_status=response.status, observed_at=stamp,
                                )
                                own_metrics.append({**metrics, "raw_response_path": str(raw_path)})
                                own_metrics[-1].update(api_response_url=response.url, http_status=response.status)
                                metrics_ready.set()
                            source.update(status="ok", count=0, kind="account_metadata",
                                          raw_response_hash=hashlib.sha256(raw).hexdigest(),
                                          raw_response_path=str(raw_path))
                            return
                        report = normalize_tweet_response(
                            raw, requested_handle=handle, response_url=response.url,
                            http_status=response.status, observed_at=stamp, raw_path=raw_path,
                        )
                        rows.extend(report["items"])
                        source.update(status=report["status"], count=len(report["items"]),
                                      rejected=report["rejected"], raw_response_hash=hashlib.sha256(raw).hexdigest(),
                                      raw_response_path=str(raw_path))
                    except Exception as error:
                        source.update(status="failed", reason=_error_text(error))

                page.on("response", lambda response: pending.append(asyncio.create_task(capture(response))))
                account_started = time.monotonic()
                try:
                    await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=int(timeout * 1000))
                    if not handles and own_handle:
                        await asyncio.wait_for(metrics_ready.wait(), timeout=timeout)
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        return handle, rows, sources, own_metrics
                    async def read_discovered_posts():
                        await page.wait_for_selector('[data-testid="tweet"]', timeout=int(timeout * 1000))
                        hrefs = await page.locator('[data-testid="tweet"] a[href*="/status/"]').evaluate_all(
                            "(xs)=>xs.map(e=>e.getAttribute('href'))"
                        )
                        exact = re.compile(r"/" + re.escape(handle) + r"/status/[0-9]+", re.I)
                        paths, discovered_ids = [], set()
                        for href in hrefs:
                            if exact.fullmatch(href or ""):
                                identifier = href.rsplit("/", 1)[-1]
                                if identifier not in discovered_ids:
                                    paths.append(href)
                                    discovered_ids.add(identifier)
                        sources.append({"source": "native.twitter_browser", "account": handle,
                                        "kind": "discovered_native_post_paths", "status": "observed",
                                        "paths": paths, "paths_sha256": hashlib.sha256(json.dumps(paths, separators=(",", ":")).encode()).hexdigest(),
                                        "observed_at": datetime.now(timezone.utc).isoformat(),
                                        "account_budget_seconds": timeout})
                        if not paths:
                            raise ValueError("requested_account_public_post_missing")
                        for path in paths:
                            url = "https://x.com" + path
                            already_observed = any(row.get("canonical_url", "").casefold() == url.casefold() for row in rows)
                            navigation = {"source": "native.twitter_browser", "account": handle,
                                          "kind": "native_post_navigation", "canonical_url": url,
                                          "status": "already_observed_no_navigation" if already_observed else "started",
                                          "started_at": datetime.now(timezone.utc).isoformat(),
                                          "observed_post_ids_before": sorted({row["content_id"] for row in rows})}
                            sources.append(navigation)
                            if already_observed:
                                continue
                            try:
                                await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
                                await page.wait_for_selector('[data-testid="tweet"]', timeout=int(timeout * 1000))
                                if pending:
                                    await asyncio.gather(*pending, return_exceptions=True)
                                navigation.update(status="completed", finished_at=datetime.now(timezone.utc).isoformat(),
                                                  observed_post_ids_after=sorted({row["content_id"] for row in rows}))
                            except BaseException as error:
                                navigation.update(status="failed", error_type=type(error).__name__,
                                                  reason=_error_text(error), automatic_replay=False)
                                raise
                    # The existing per-account budget covers discovery and all distinct post reads together.
                    # Account-only observation above retains its original path and bounds.
                    remaining = timeout - (time.monotonic() - account_started)
                    if remaining <= 0:
                        raise TimeoutError("original_account_source_budget_exhausted")
                    await asyncio.wait_for(read_discovered_posts(), timeout=remaining)
                except Exception as error:
                    sources.append({"source": "native.twitter_browser", "account": handle,
                                    "status": "failed", "reason": _error_text(error)})
                finally:
                    await page.close()
                return handle, rows, sources, own_metrics

        requested = list(handles)
        if own_handle and own_handle.casefold() not in {handle.casefold() for handle in handles}:
            requested.append(own_handle)
        collected = await asyncio.gather(*(read(handle) for handle in requested))
        unique, sources, own_metrics = {}, [], []
        for handle, rows, reports, metrics in collected:
            sources.extend(reports)
            own_metrics.extend(metrics)
            if handle.casefold() not in {value.casefold() for value in handles}:
                continue
            for row in rows:
                unique.setdefault(row["canonical_url"], row)
        items = list(unique.values())
        accounts = {row["author"].casefold() for row in items}
        result = {"items": items, "sources": sources, "status": "ok" if len(accounts) >= 3 else "incomplete",
                  "observed_account_count": len(accounts), "editorial_quality_certified": False}
        if own_metrics:
            result["own_account_metrics"] = own_metrics[-1]
        return result
