"""TopCV adapter with real safe transport policy and synthetic HTTP only."""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.db.base import utc_now
from app.models.crawl import CrawlRun
from app.models.knowledge import DataSource
from app.services.adapters.topcv import TopCVAdapter
from app.services.crawl import CrawlError, FetchResult, SafeFetcher
from tests.contract.knowledge_support import create_source
from tests.jobs_support import job_client, admin_client, stored_jobs, BASE  # noqa: F401

HOST = 'https://www.topcv.vn'


@pytest.fixture
def topcv(job_client, monkeypatch):
    client = job_client
    source = create_source(client, name='SYNTHETIC TopCV', kind='topcv', base_url=HOST + '/',
        allowed_paths=['/viec-lam'], robots_url=HOST + '/robots.txt', terms_url=HOST + '/terms')
    monkeypatch.setattr('app.services.crawl.socket.getaddrinfo',
        lambda *_args, **_kw: [(2, 1, 6, '', ('93.184.216.34', 443))])
    timer = SimpleNamespace(value=0.)
    def sleep(seconds): timer.value += seconds
    transport = Mock()
    fetcher = SafeFetcher(transport=transport, monotonic=lambda: timer.value, sleep=sleep)
    adapter = TopCVAdapter(client.app.state.jobs, fetcher=fetcher)
    return client, source['id'], adapter, transport


def response(content=b'', status=200, **headers):
    return FetchResult(HOST + '/viec-lam', content, {'Content-Type': 'text/html'} | headers, status)


def html(**changes):
    posting = dict(**{'@type': 'JobPosting'}, title='SYNTHETIC job',
        description='<p>SYNTHETIC engineering description</p>', hiringOrganization={'name': 'SYNTHETIC'},
        identifier={'@type': 'PropertyValue', 'value': 'stable-topcv-id'}, datePosted='2020-01-01',
        validThrough=(utc_now() + timedelta(days=10)).isoformat()) | changes
    return ('<main><script type="application/ld+json">' + json.dumps(posting) + '</script></main>').encode()


def run(topcv):
    client, source_id, adapter, _ = topcv
    coordinator = client.app.state.coordinator
    run = coordinator.claim('manual', source_id)
    coordinator.execute(run.id, lambda identity: adapter.run(identity, source_id))
    with client.app.state.database.session() as db:
        return db.get(CrawlRun, run.id)


def test_permitted_html_to_job_origin_and_skip(topcv):
    client, source_id, adapter, transport = topcv
    transport.side_effect = [response(b'User-agent: *\nAllow: /\nCrawl-delay: 3'), response(html())]
    result = run(topcv)
    assert result.new_count == 1 and result.state == 'succeeded'
    assert len(stored_jobs(client)) == 1
    item = client.get(BASE + '/jobs').json()['items'][0]
    assert item['source_id'] == source_id and item['source_url'] == HOST + '/viec-lam'
    assert item['identity_key'] == 'ext:stable-topcv-id'
    assert all(call.kwargs['allow_redirects'] is False for call in transport.call_args_list)
    assert all(call.kwargs['timeout'] == (5, 20) for call in transport.call_args_list)
    client.job_model.encode.reset_mock()
    # Status and description stay identical even though observation time changes.
    content = html(validThrough=item['deadline_at'])
    transport.side_effect = [response(b'User-agent: *\nAllow: /'), response(content)]
    assert run(topcv).skipped_count == 1
    client.job_model.encode.assert_not_called()


@pytest.mark.parametrize('changes', [dict(permission_status='unknown'), dict(permission_status='denied'),
    dict(enabled=False), dict(robots_url=None), dict(terms_url=None)])
def test_no_permission_no_fetch(topcv, changes):
    client, source_id, adapter, transport = topcv
    with client.app.state.database.session() as db:
        source = db.get(DataSource, source_id)
        source.enabled = False
        for key, value in changes.items(): setattr(source, key, value)
        db.commit()
    result = run(topcv)
    transport.assert_not_called()
    assert result.state == 'failed' and result.source_outcomes_json[0]['message'] == 'SOURCE_NOT_VERIFIED'


@pytest.mark.parametrize('status,content,reason', [
    (403, b'denied', 'HTTP_403'), (200, b'<div class="g-recaptcha"></div>', 'CAPTCHA'),
    (429, b'wait', 'RATE_LIMITED'), (200, b'<main id="app">JavaScript only</main>', 'UNSUPPORTED_HTML'),
])
def test_blocked_or_unsupported_does_not_retry_or_damage_existing_job(topcv, status, content, reason):
    client, source_id, adapter, transport = topcv
    transport.side_effect = [response(b'User-agent: *\nAllow: /'), response(html())]
    run(topcv)
    before = client.get(BASE + '/jobs').json()['items']
    transport.reset_mock()
    transport.side_effect = [response(b'User-agent: *\nAllow: /'), response(content, status, **{'Retry-After': '120'})]
    result = run(topcv)
    assert result.state == 'failed' and result.source_outcomes_json[0]['message'] == reason
    assert transport.call_count == 2
    assert client.get(BASE + '/jobs').json()['items'] == before
    if status == 429:
        with client.app.state.database.session() as db:
            source = db.get(DataSource, source_id)
            assert source.retry_not_before > utc_now()
        transport.reset_mock()
        assert run(topcv).source_outcomes_json[0]['message'] == 'RETRY_NOT_BEFORE'
        transport.assert_not_called()


def test_robots_denied_and_private_redirect_stop(topcv):
    client, source_id, adapter, transport = topcv
    transport.side_effect = [response(b'User-agent: *\nDisallow: /')]
    assert run(topcv).source_outcomes_json[0]['message'] == 'ROBOTS_DENIED'
    assert transport.call_count == 1
    transport.reset_mock()
    transport.side_effect = [response(b'User-agent: *\nAllow: /'),
        response(status=302, **{'Location': 'https://127.0.0.1/private'})]
    assert run(topcv).state == 'failed'
    assert transport.call_count == 2


def test_permission_revoked_between_robots_and_html_never_fetches_html(topcv):
    client, source_id, adapter, transport = topcv
    def robots(*args, **kwargs):
        with client.app.state.database.session() as db:
            db.get(DataSource, source_id).enabled = False
            db.commit()
        return response(b'User-agent: *\nAllow: /')
    transport.side_effect = robots
    assert run(topcv).state == 'failed'
    assert transport.call_count == 1
