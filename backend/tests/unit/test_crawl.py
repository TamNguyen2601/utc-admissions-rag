"""Synthetic UTC HTML/robots responses. No live DNS or HTTP."""
from datetime import timedelta
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.db.base import utc_now
from app.services.crawl import CrawlError, SafeFetcher, FetchResult, PinnedHTTPSAdapter
from app.services.adapters.utc import UTCAdapter

BASE = "https://tuyensinh.utc.edu.vn"


@pytest.fixture
def source():
    return SimpleNamespace(id="synthetic", kind="utc", enabled=True, permission_status="allowed",
        reuse_basis="TEST ONLY", checked_at=utc_now(), base_url=BASE + "/", allowed_paths_json=["/"],
        robots_url=BASE + "/robots.txt", terms_url=BASE + "/terms", min_interval_seconds=2,
        retry_not_before=None)


def setup_fetcher(source, monkeypatch, responses):
    monkeypatch.setattr("app.services.crawl.socket.getaddrinfo", lambda *_args, **_kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    clock = SimpleNamespace(value=0.)
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds); clock.value += seconds
    transport = Mock(side_effect=responses)
    fetcher = SafeFetcher(transport=transport, monotonic=lambda: clock.value, sleep=sleep)
    return fetcher, transport, sleeps


def response(body=b"SYNTHETIC", status=200, headers=None):
    return FetchResult(BASE + "/", body, headers or {"Content-Type": "text/html"}, status)


def test_discovery_pagination_attachments_and_rate(source, monkeypatch):
    html = b'<main><article><a href="/notice?year=2026&utm_source=test">Notice</a></article><a href="/file.pdf">PDF</a><a rel="next" href="/?page=2">Next</a><a href="https://other.example/a">Outside</a></main>'
    fetcher, transport, sleeps = setup_fetcher(source, monkeypatch, [response(b"User-agent: *\nAllow: /"), response(html), response(), response(b"%PDF-synthetic", headers={"Content-Type": "application/pdf"}), response()])
    items = list(UTCAdapter(fetcher).discover(source))
    assert {item.url for item in items} == {BASE + "/", BASE + "/notice?year=2026", BASE + "/file.pdf", BASE + "/?page=2"}
    assert all(call.kwargs["timeout"] == (5, 20) for call in transport.call_args_list)
    assert all(call.kwargs["allow_redirects"] is False for call in transport.call_args_list)
    assert len(sleeps) == 4 and all(s >= 2 for s in sleeps)


@pytest.mark.parametrize("status,body,reason", [(403,b"blocked","HTTP_403"),(200,b'<div class="g-recaptcha"></div>',"CAPTCHA"),(429,b"busy","RATE_LIMITED")])
def test_no_bypass_and_retry_after(source, monkeypatch, status, body, reason):
    fetcher, transport, _ = setup_fetcher(source, monkeypatch, [response(body, status, {"Retry-After": "120"})])
    with pytest.raises(CrawlError, match=reason): fetcher.fetch(source, BASE + "/")
    assert transport.call_count == 1
    if status == 429:
        assert source.retry_not_before >= utc_now() + timedelta(seconds=119)
        with pytest.raises(CrawlError, match="RETRY_NOT_BEFORE"): fetcher.fetch(source, BASE + "/")
        assert transport.call_count == 1


def test_unknown_robots_and_redirects_do_not_fetch(source, monkeypatch):
    fetcher, transport, _ = setup_fetcher(source, monkeypatch, [])
    source.permission_status = "unknown"
    with pytest.raises(CrawlError): list(UTCAdapter(fetcher).discover(source))
    transport.assert_not_called()

    source.permission_status = "allowed"
    transport.side_effect = [response(b"User-agent: *\nDisallow: /")]
    with pytest.raises(CrawlError, match="ROBOTS_DENIED"): list(UTCAdapter(fetcher).discover(source))
    assert transport.call_count == 1
    transport.reset_mock(side_effect=True)
    transport.side_effect = [response(status=302, headers={"Location": "https://127.0.0.1/private"})]
    with pytest.raises(CrawlError): fetcher.fetch(source, BASE + "/")
    assert transport.call_count == 1
    transport.reset_mock(side_effect=True)
    monkeypatch.setattr("app.services.crawl.socket.getaddrinfo", lambda *_args, **_kw: [(2,1,6,"",("10.0.0.1",443))])
    with pytest.raises(CrawlError, match="PRIVATE_DESTINATION"): fetcher.fetch(source, BASE + "/")
    transport.assert_not_called()


@pytest.mark.parametrize("changes", [{"permission_status": "denied"}, {"permission_status": "unknown"},
    {"enabled": False}, {"reuse_basis": None}, {"checked_at": None}, {"robots_url": None}, {"terms_url": None}])
def test_unverified_sources_never_resolve_or_fetch(source, monkeypatch, changes):
    for field, value in changes.items(): setattr(source, field, value)
    resolver, transport = Mock(), Mock()
    monkeypatch.setattr("app.services.crawl.socket.getaddrinfo", resolver)
    with pytest.raises(CrawlError): SafeFetcher(transport=transport).fetch(source, BASE + "/")
    resolver.assert_not_called()
    transport.assert_not_called()


@pytest.mark.parametrize("value,seconds", [(None,900),("invalid",900),("0",0),("120",120),("date",240)])
def test_retry_after_fallback_and_http_date(source, monkeypatch, value, seconds):
    now = utc_now()
    if value == "date": value = format_datetime(now.replace(microsecond=0) + timedelta(seconds=240))
    headers = {} if value is None else {"Retry-After": value}
    fetcher, transport, _ = setup_fetcher(source, monkeypatch, [response(status=429, headers=headers)])
    fetcher.now = lambda: now
    with pytest.raises(CrawlError, match="RATE_LIMITED"): fetcher.fetch(source, BASE + "/")
    assert abs((source.retry_not_before - now).total_seconds() - seconds) < 1
    assert transport.call_count == 1


def test_allowed_redirect_and_robots_redirect_target(source, monkeypatch):
    fetcher, transport, _ = setup_fetcher(source, monkeypatch, [
        response(status=302, headers={"Location": "/notice?utm_source=test&year=2026#top"}), response()])
    result = fetcher.fetch(source, BASE + "/")
    assert result.url == BASE + "/notice?year=2026"
    assert transport.call_count == 2
    from urllib.robotparser import RobotFileParser
    robots = RobotFileParser()
    robots.parse(["User-agent: *", "Disallow: /private/"])
    transport.reset_mock(side_effect=True)
    transport.side_effect = [response(status=302, headers={"Location": "/private/blocked"})]
    with pytest.raises(CrawlError, match="ROBOTS_DENIED"):
        fetcher.fetch(source, BASE + "/", robots_policy=robots)
    assert transport.call_count == 1


def test_pinned_connection_keeps_tls_hostname_and_disallows_proxies():
    import requests
    adapter = PinnedHTTPSAdapter("tuyensinh.utc.edu.vn", "93.184.216.34")
    try:
        request = requests.Request("GET", BASE + "/").prepare()
        pool = adapter.get_connection_with_tls_context(request, True)
        assert pool.host == "93.184.216.34"
        assert pool.assert_hostname == "tuyensinh.utc.edu.vn"
        assert pool.conn_kw["server_hostname"] == "tuyensinh.utc.edu.vn"
        assert adapter.max_retries.total == 0
        with pytest.raises(CrawlError, match="UNSAFE_TRANSPORT"):
            adapter.get_connection_with_tls_context(request, True, proxies={"https": "http://proxy.example"})
    finally:
        adapter.close()


def test_permission_revoked_during_rate_wait(source, monkeypatch):
    fetcher, transport, _ = setup_fetcher(source, monkeypatch, [response()])
    fetcher.fetch(source, BASE + "/")
    fetcher.reload_source = lambda _id: source
    source.min_interval_seconds = 10
    old_sleep = fetcher.sleep
    def revoke(seconds):
        old_sleep(seconds)
        source.enabled = False
    fetcher.sleep = revoke
    with pytest.raises(CrawlError, match="SOURCE_OR_URL_DENIED"):
        fetcher.fetch(source, BASE + "/")
    assert transport.call_count == 1


def test_lowercase_http_headers_are_supported(source, monkeypatch):
    fetcher, transport, _ = setup_fetcher(source, monkeypatch, [
        response(status=302, headers={"location": "/next"}),
        response(status=429, headers={"retry-after": "120", "content-type": "text/plain"})])
    with pytest.raises(CrawlError, match="RATE_LIMITED"):
        fetcher.fetch(source, BASE + "/")
    assert source.retry_not_before >= utc_now() + timedelta(seconds=119)
    assert transport.call_count == 2
    assert response(headers={"content-type": "application/pdf"}).media_type == "application/pdf"


def test_allowed_paths_seed_when_base_is_outside_scope(source, monkeypatch):
    source.allowed_paths_json = ["/docs"]
    fetcher, transport, _ = setup_fetcher(source, monkeypatch, [response(b"User-agent: *\nAllow: /"), response()])
    items = list(UTCAdapter(fetcher).discover(source))
    assert [item.url for item in items] == [BASE + "/docs"]
    assert transport.call_args.args[0] == BASE + "/docs"


def test_rate_cannot_be_bypassed_with_another_source_id(source, monkeypatch):
    fetcher, _, sleeps = setup_fetcher(source, monkeypatch, [response(), response()])
    source.min_interval_seconds = 10
    fetcher.fetch(source, BASE + "/")
    source.id = "another-source-on-same-host"
    source.min_interval_seconds = 2
    fetcher.fetch(source, BASE + "/")
    assert sleeps == [10]


def test_octet_stream_attachment_uses_magic_checked_media(source, monkeypatch):
    from pathlib import Path
    data = (Path(__file__).parents[1] / "fixtures/utc/native.pdf").read_bytes()
    source.base_url = BASE + "/native.pdf"
    fetcher, _, _ = setup_fetcher(source, monkeypatch, [response(b"User-agent: *\nAllow: /"),
        response(data, headers={"Content-Type": "application/octet-stream"})])
    items = list(UTCAdapter(fetcher).discover(source))
    assert len(items) == 1 and items[0].media_type == "application/pdf"
