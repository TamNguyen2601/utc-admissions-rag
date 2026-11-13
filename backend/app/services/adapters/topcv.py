"""Explicitly invoked, permission-gated TopCV HTML adapter; no browser or bypass.

Only publisher JobPosting JSON-LD is supported. JS-only/unsupported pages fail closed
and require an authorized CSV/JSON import. Nothing starts this adapter at startup.
"""
from collections import deque
from datetime import date, datetime, time
import json
import re
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from fastapi import HTTPException

from app.models.crawl import CrawlRun
from app.models.knowledge import DataSource
from app.services.adapters.job_import import JobImportAdapter
from app.services.crawl import CrawlError, SafeFetcher, USER_AGENT
from app.services.sources import canonical_url, require_usable, validate_source_url


class TopCVAdapter:
    def __init__(self, jobs, *, fetcher=None, max_urls=500):
        self.jobs, self.max_urls = jobs, max_urls
        self.fetcher = fetcher or SafeFetcher()
        self.fetcher.reload_source, self.fetcher.on_retry = self._load_source, self._retry

    def _load_source(self, identity):
        with self.jobs.database.session() as db:
            return db.get(DataSource, identity)

    def _retry(self, identity, retry):
        with self.jobs.database.session() as db:
            source = db.get(DataSource, identity)
            if source:
                source.retry_not_before = retry
                db.commit()

    @staticmethod
    def check_source(source):
        try:
            require_usable(source)
            if (source.kind != 'topcv' or not source.robots_url or not source.terms_url
                    or urlsplit(canonical_url(source.base_url)).hostname not in {'topcv.vn', 'www.topcv.vn'}):
                raise ValueError
        except (HTTPException, ValueError, TypeError):
            raise CrawlError('SOURCE_NOT_VERIFIED') from None

    @staticmethod
    def postings(value):
        if isinstance(value, list):
            for item in value:
                yield from TopCVAdapter.postings(item)
        elif isinstance(value, dict):
            kinds = value.get('@type', [])
            if kinds == 'JobPosting' or isinstance(kinds, list) and 'JobPosting' in kinds:
                yield value
            if '@graph' in value:
                yield from TopCVAdapter.postings(value['@graph'])

    def discover(self, source, *, should_stop=lambda: False):
        self.check_source(source)  # Gate even when a fake/custom fetcher is supplied.
        if should_stop():
            return
        robots = self.fetcher.fetch(source, source.robots_url, robots_resource=True)
        policy = RobotFileParser()
        policy.parse(robots.content.decode('utf-8-sig', errors='replace').splitlines())
        delay = policy.crawl_delay(USER_AGENT) or 2
        rate = policy.request_rate(USER_AGENT)
        if rate and rate.requests > 0:
            delay = max(delay, rate.seconds / rate.requests)
        try:
            seeds = [validate_source_url(source, source.base_url)]
        except HTTPException:
            seeds = [urljoin(source.base_url, path) for path in source.allowed_paths_json]
        queue, visited = deque(seeds), set()
        while queue and not should_stop():
            source = self._load_source(source.id)
            self.check_source(source)
            url = validate_source_url(source, queue.popleft())
            if url in visited:
                continue
            if len(visited) >= self.max_urls:
                raise CrawlError('DISCOVERY_LIMIT')
            visited.add(url)
            if not policy.can_fetch(USER_AGENT, url):
                raise CrawlError('ROBOTS_DENIED')
            result = self.fetcher.fetch(source, url, robots_policy=policy, minimum_interval=delay)
            visited.add(result.url)
            if result.media_type not in {'text/html', 'application/xhtml+xml'}:
                raise CrawlError('UNSUPPORTED_HTML')
            soup = BeautifulSoup(result.content, 'html.parser')
            emitted = False
            for script in soup.select('script[type="application/ld+json"]'):
                try:
                    data = json.loads(script.get_text())
                except (ValueError, RecursionError):
                    continue
                for posting in self.postings(data):
                    emitted = True
                    publisher_url = posting.get('url') or result.url
                    publisher_url = validate_source_url(source, urljoin(result.url, publisher_url))
                    organization = posting.get('hiringOrganization')
                    identifier = posting.get('identifier')
                    # Publisher JSON-LD identifier is an explicit stable ID; never derive it from text.
                    if isinstance(identifier, dict):
                        identifier = identifier.get('value')
                    if not isinstance(identifier, (str, int)) or isinstance(identifier, bool):
                        identifier = None
                    posted = posting.get('datePosted')
                    if isinstance(posted, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', posted):
                        try:
                            posted = datetime.combine(date.fromisoformat(posted), time.min,
                                                      ZoneInfo('Asia/Ho_Chi_Minh')).isoformat()
                        except ValueError:
                            pass  # Row validation logs the malformed timestamp.
                    row = dict(title=posting.get('title'), employer=organization.get('name')
                        if isinstance(organization, dict) else None,
                        description=BeautifulSoup(posting.get('description') or '', 'html.parser').get_text(' ', strip=True),
                        source_id=source.id, source_url=publisher_url,
                        collected_at=self.jobs.now().isoformat(), posted_at=posted,
                        deadline_at=posting.get('validThrough'), observed_status='open'
                        if posting.get('validThrough') else 'unknown')
                    if identifier is not None:
                        row['external_id'] = str(identifier)
                    yield row
            links = []
            root = soup.select_one('main,article,[role=main]') or soup
            for anchor in root.select('a[href]'):
                href = urljoin(result.url, anchor['href'])
                try:
                    candidate = validate_source_url(source, href)
                except (HTTPException, ValueError):
                    continue
                if candidate not in visited and candidate not in queue:
                    links.append(candidate)
            if not emitted and not links:
                raise CrawlError('UNSUPPORTED_HTML')
            for link in links:
                if len(queue) + len(visited) >= self.max_urls:
                    raise CrawlError('DISCOVERY_LIMIT')
                queue.append(link)

    def run(self, run_id, source_id):
        status, reason = 'success', None
        with self.jobs.database.session() as db:
            errors_before = db.get(CrawlRun, run_id).error_count
        try:
            source = self._load_source(source_id)
            JobImportAdapter(self.jobs).run(run_id,
                self.discover(source, should_stop=lambda: self.jobs.coordinator.should_stop(run_id)),
                source_id, record_sources=False)
            with self.jobs.database.session() as db:
                if db.get(CrawlRun, run_id).error_count > errors_before:
                    status, reason = 'error', 'ROW_ERRORS'
            if self.jobs.coordinator.should_stop(run_id):
                status, reason = 'stopped', 'STOP_REQUESTED'
        except Exception as exc:
            status, reason = 'error', exc.reason if isinstance(exc, CrawlError) else 'SOURCE_FAILED'
        self.jobs.coordinator.record_source(run_id, source_id, status, reason)
