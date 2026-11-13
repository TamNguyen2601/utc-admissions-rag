"""Bounded HTML, pagination and attachment discovery inside verified UTC scope."""
from collections import deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from fastapi import HTTPException

from app.services.crawl import CrawlError, USER_AGENT
from app.services.sources import validate_source_url
from app.services.documents import validate_file

ATTACHMENTS = {".pdf": "application/pdf", ".txt": "text/plain", ".png": "image/png",
               ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


@dataclass(frozen=True)
class DiscoveredDocument:
    url: str
    original_url: str
    title: str
    content: bytes
    media_type: str
    deadline: float


class UTCAdapter:
    def __init__(self, fetcher, *, max_urls=500):
        self.fetcher, self.max_urls = fetcher, max_urls

    def discover(self, source, *, should_stop=lambda: False):
        if should_stop():
            return
        robots = self.fetcher.fetch(source, source.robots_url, robots_resource=True)
        parser = RobotFileParser()
        parser.parse(robots.content.decode("utf-8-sig", errors="replace").splitlines())
        # Honor a stricter crawl-delay in addition to the registry's reviewed rate.
        delay = parser.crawl_delay(USER_AGENT)
        request_rate = parser.request_rate(USER_AGENT)
        if request_rate and request_rate.requests > 0:
            delay = max(delay or 0, request_rate.seconds / request_rate.requests)
        try:
            start = validate_source_url(source, source.base_url)
            seeds = [(start, source.base_url)]
        except (HTTPException, ValueError):
            seeds = [(urljoin(source.base_url, path), urljoin(source.base_url, path))
                     for path in source.allowed_paths_json]
        if not seeds:
            raise CrawlError("SOURCE_OR_URL_DENIED")
        queue, seen = deque(seeds), set()
        while queue:
            if should_stop():
                return
            url, original = queue.popleft()
            try:
                url = validate_source_url(source, url)
            except (HTTPException, ValueError):
                continue
            if url in seen:
                continue
            if len(seen) >= self.max_urls:
                raise CrawlError("DISCOVERY_LIMIT")
            seen.add(url)
            if not parser.can_fetch(USER_AGENT, url):
                raise CrawlError("ROBOTS_DENIED")
            deadline = self.fetcher.monotonic() + 300
            # Redirect targets must also pass robots, before their request is issued.
            result = self.fetcher.fetch(source, url, deadline=deadline, robots_policy=parser,
                                        minimum_interval=max(2, delay or 0))
            seen.add(result.url)
            suffix = PurePosixPath(urlsplit(result.url).path).suffix.lower()
            media = result.media_type or ATTACHMENTS.get(suffix, "text/html")
            if media == "application/octet-stream" and suffix in ATTACHMENTS:
                media = ATTACHMENTS[suffix]
                try:
                    validate_file(result.content, media, "attachment" + suffix)
                except HTTPException:
                    raise CrawlError("INVALID_ATTACHMENT") from None
            title = PurePosixPath(urlsplit(result.url).path).name or "UTC admissions document"
            if media in {"text/html", "application/xhtml+xml"}:
                media = "text/html"
                soup = BeautifulSoup(result.content, "html.parser")
                heading = soup.select_one("h1") or soup.title
                if heading:
                    title = heading.get_text(" ", strip=True)
                root = soup.select_one("main,article,[role=main],.view-content,#content") or soup.body or soup
                for link in root.select("a[href]"):
                    href = link.get("href", "")
                    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                        continue
                    destination = urljoin(result.url, href)
                    extension = PurePosixPath(urlsplit(destination).path).suffix.lower()
                    if extension and extension not in {*ATTACHMENTS, ".html", ".htm", ".php", ".aspx"}:
                        continue
                    try:
                        canonical = validate_source_url(source, destination)
                    except (HTTPException, ValueError):
                        continue
                    if canonical not in seen:
                        if len(queue) + len(seen) >= self.max_urls:
                            raise CrawlError("DISCOVERY_LIMIT")
                        queue.append((canonical, destination))
            if media not in {"text/html", "text/plain", "application/pdf", "image/png", "image/jpeg"}:
                raise CrawlError("UNSUPPORTED_MEDIA")
            yield DiscoveredDocument(result.url, original, title, result.content, media, deadline)
