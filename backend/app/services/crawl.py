"""Permission-gated UTC transport and offline-testable crawl orchestration.

Nothing starts crawling at import/startup. Scheduler/API wiring belongs to later tasks.
"""
from dataclasses import dataclass
from datetime import timedelta
from email.utils import parsedate_to_datetime
import ipaddress
import re
import socket
import time
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException
import requests
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict
from sqlalchemy import select

from app.db.base import utc_now
from app.models.crawl import CrawlRun
from app.models.knowledge import DataSource
from app.services.documents import MAX_UPLOAD
from app.services.sources import canonical_url, require_usable, validate_source_url

USER_AGENT = "UTCAdmissionsResearchBot/0.1"


class CrawlError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FetchResult:
    url: str
    content: bytes
    headers: dict
    status: int = 200

    def __post_init__(self):
        object.__setattr__(self, "headers", CaseInsensitiveDict(self.headers))

    @property
    def media_type(self):
        return self.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()


class PinnedHTTPSAdapter(HTTPAdapter):
    """Connect to a checked literal IP while verifying TLS/SNI for the original host."""
    def __init__(self, host, address):
        self.host, self.address = host, address
        super().__init__(max_retries=0)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        if proxies or verify is not True or urlsplit(request.url).hostname != self.host:
            raise CrawlError("UNSAFE_TRANSPORT")
        _, kwargs = self.build_connection_pool_key_attributes(request, verify, cert)
        kwargs.update(assert_hostname=self.host, server_hostname=self.host)
        return self.poolmanager.connection_from_host(self.address, 443, scheme="https", pool_kwargs=kwargs)


def requests_transport(url, *, addresses, timeout, allow_redirects, deadline, monotonic):
    # No environment proxies/netrc, automatic redirects, retries, or second hostname lookup.
    host = urlsplit(url).hostname
    with requests.Session() as session:
        session.trust_env = False
        session.mount("https://", PinnedHTTPSAdapter(host, addresses[0]))
        with session.get(url, headers={"User-Agent": USER_AGENT, "Host": host}, timeout=timeout,
                         allow_redirects=allow_redirects, stream=True, verify=True) as response:
            content = bytearray()
            # Status failures/redirects need no body (and must not wait for one).
            if response.status_code == 200:
                for chunk in response.iter_content(64 * 1024):
                    if monotonic() >= deadline:
                        raise CrawlError("ITEM_TIMEOUT")
                    content.extend(chunk)
                    if len(content) > MAX_UPLOAD:
                        raise CrawlError("RESPONSE_TOO_LARGE")
            return FetchResult(url, bytes(content), dict(response.headers), response.status_code)


class SafeFetcher:
    def __init__(self, *, transport=requests_transport, monotonic=time.monotonic, sleep=time.sleep,
                 now=utc_now, reload_source=None, on_retry=None):
        self.transport, self.monotonic, self.sleep, self.now = transport, monotonic, sleep, now
        self.reload_source, self.on_retry = reload_source, on_retry
        self.last_request = {}
        self.last_interval = {}

    def fetch(self, source, value, *, robots_resource=False, deadline=None, robots_policy=None, minimum_interval=2):
        deadline = deadline if deadline is not None else self.monotonic() + 300
        url = value
        for _ in range(6):
            if self.reload_source:
                source = self.reload_source(source.id)
            try:
                require_usable(source)
                if (source.kind != "utc" or not source.robots_url or not source.terms_url
                        or urlsplit(canonical_url(source.base_url)).hostname != "tuyensinh.utc.edu.vn"):
                    raise CrawlError("SOURCE_NOT_VERIFIED")
                if source.retry_not_before and source.retry_not_before > self.now():
                    raise CrawlError("RETRY_NOT_BEFORE")
                if robots_resource:
                    url = canonical_url(url)
                    if url != canonical_url(source.robots_url) or urlsplit(url).hostname != urlsplit(source.base_url).hostname:
                        raise CrawlError("ROBOTS_REDIRECT_DENIED")
                else:
                    url = validate_source_url(source, url)
                    if robots_policy is not None and not robots_policy.can_fetch(USER_AGENT, url):
                        raise CrawlError("ROBOTS_DENIED")
                host = urlsplit(url).hostname
                rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                addresses = list(dict.fromkeys(row[4][0] for row in rows))
                if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
                    raise CrawlError("PRIVATE_DESTINATION")
            except (HTTPException, ValueError, OSError, TypeError) as exc:
                if isinstance(exc, CrawlError):
                    raise
                raise CrawlError("SOURCE_OR_URL_DENIED") from None
            interval = max(2, minimum_interval, source.min_interval_seconds)
            delay = max(0, self.last_request.get(host, float("-inf"))
                        + max(interval, self.last_interval.get(host, 0)) - self.monotonic())
            if self.monotonic() + delay >= deadline:
                raise CrawlError("ITEM_TIMEOUT")
            if delay:
                self.sleep(delay)
            if self.reload_source:
                try:
                    latest = self.reload_source(source.id)
                    require_usable(latest)
                    if robots_resource:
                        if canonical_url(latest.robots_url) != url:
                            raise ValueError
                    else:
                        validate_source_url(latest, url)
                    if not latest.robots_url or not latest.terms_url:
                        raise ValueError
                    if latest.retry_not_before and latest.retry_not_before > self.now():
                        raise CrawlError("RETRY_NOT_BEFORE")
                except (HTTPException, ValueError, TypeError):
                    raise CrawlError("SOURCE_OR_URL_DENIED") from None
            self.last_request[host], self.last_interval[host] = self.monotonic(), interval
            try:
                result = self.transport(url, addresses=addresses, timeout=(5, 20), allow_redirects=False,
                                        deadline=deadline, monotonic=self.monotonic)
            except requests.RequestException:
                raise CrawlError("FETCH_FAILED") from None
            if self.monotonic() >= deadline:
                raise CrawlError("ITEM_TIMEOUT")
            if result.status == 429:
                wait = result.headers.get("Retry-After", "")
                try:
                    retry = self.now() + timedelta(seconds=max(0, int(wait))) if wait.strip().isdigit() else parsedate_to_datetime(wait)
                    if retry.tzinfo is None:
                        raise ValueError
                    retry = max(self.now(), retry)
                except (ValueError, TypeError, OverflowError):
                    retry = self.now() + timedelta(minutes=15)
                source.retry_not_before = retry
                if self.on_retry:
                    self.on_retry(source.id, retry)
                raise CrawlError("RATE_LIMITED")
            if result.status in {301, 302, 303, 307, 308}:
                if not result.headers.get("Location"):
                    raise CrawlError("INVALID_REDIRECT")
                url = urljoin(url, result.headers["Location"])
                continue
            if result.status != 200:
                raise CrawlError(f"HTTP_{result.status}")
            if len(result.content) > MAX_UPLOAD:
                raise CrawlError("RESPONSE_TOO_LARGE")
            if result.media_type in {"text/html", "application/xhtml+xml", ""}:
                if re.search(rb"\bcaptcha\b|g-recaptcha|h-captcha|hcaptcha|cf-chl-|cf-turnstile|challenge-platform|verify you are human", result.content, re.I):
                    raise CrawlError("CAPTCHA")
            return FetchResult(url, result.content, result.headers, result.status)
        raise CrawlError("REDIRECT_LIMIT")


class CrawlService:
    def __init__(self, database, documents, coordinator, *, fetcher=None):
        self.database, self.documents, self.coordinator = database, documents, coordinator
        self.fetcher = fetcher or SafeFetcher()
        self.fetcher.reload_source, self.fetcher.on_retry = self._load_source, self._retry

    def _load_source(self, identity):
        with self.database.session() as db:
            return db.get(DataSource, identity)

    def _retry(self, identity, retry):
        with self.database.session() as db:
            source = db.get(DataSource, identity)
            if source:
                source.retry_not_before = retry
                db.commit()

    def run(self, run_id, source_ids=None):
        from app.services.adapters.utc import UTCAdapter
        with self.database.session() as db:
            query = select(DataSource).where(DataSource.kind == "utc")
            if source_ids is not None:
                query = query.where(DataSource.id.in_(source_ids))
            sources = db.scalars(query.order_by(DataSource.id)).all()
        index = 0
        for source in sources:
            if self.coordinator.should_stop(run_id):
                break
            status, reason = "success", None
            try:
                adapter = UTCAdapter(self.fetcher)
                for item in adapter.discover(source, should_stop=lambda: self.coordinator.should_stop(run_id)):
                    started = utc_now()
                    payload = SimpleNamespace(title=item.title, original_url=item.original_url,
                        year=None, campus=None, major_code=None, method=None)
                    result = self.documents.process_web(source.id, item.url, item.content, item.media_type,
                                                        payload, deadline=item.deadline)
                    index += 1
                    self.documents.record_item(run_id, index, source.id, item.url, result, started)
                    if result.outcome == "error":
                        status, reason = "error", result.reason
                if self.coordinator.should_stop(run_id):
                    status, reason = "stopped", "STOP_REQUESTED"
            except Exception as exc:
                status = "error"
                reason = exc.reason if isinstance(exc, CrawlError) else "SOURCE_FAILED"
            with self.database.session() as db:
                run = db.get(CrawlRun, run_id)
                run.source_outcomes_json = [*run.source_outcomes_json,
                    {"source_id": source.id, "status": status, "message": reason}]
                current_source = db.get(DataSource, source.id)
                if status == "success" and current_source:
                    current_source.last_success_at = utc_now()
                db.commit()
