"""B2 SQLite + real BS4/PyMuPDF + fake HTTP/OCR/indexer. No embedding/retrieval."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import select

from app.db.base import utc_now
from app.models.crawl import CrawlRun, CrawlRunItem
from app.models.knowledge import DataSource, Document, DocumentOrigin
from app.services.crawl import CrawlService, FetchResult, SafeFetcher
from tests.ingestion_support import ingestion, ingest
from tests.unit.test_extraction import tsv

FIXTURES = Path(__file__).parents[1] / "fixtures/utc"
BASE = "https://tuyensinh.utc.edu.vn"


def transport_fixture(ingestion, monkeypatch):
    _, service, coordinator = ingestion
    monkeypatch.setattr("app.services.crawl.socket.getaddrinfo", lambda *_a, **_kw: [(2,1,6,"",("93.184.216.34",443))])
    clock = SimpleNamespace(value=0.)
    def sleep(seconds): clock.value += seconds
    assets = {"/robots.txt": ("robots.txt", "text/plain"), "/": ("index.html", "text/html"),
        "/?page=2": ("page2.html", "text/html"), "/notice?year=2026": ("notice.html", "text/html"),
        "/native.pdf": ("native.pdf", "application/pdf"), "/image.png": ("image.png", "image/png")}
    def response(url, **_kwargs):
        name, media = assets[url.removeprefix(BASE)]
        return FetchResult(url, (FIXTURES / name).read_bytes(), {"Content-Type": media})
    fetcher = SafeFetcher(transport=Mock(side_effect=response), sleep=sleep, monotonic=lambda: clock.value)
    service.extractor.monotonic = fetcher.monotonic
    crawler = CrawlService(service.database, service, coordinator, fetcher=fetcher)
    return crawler, coordinator, assets


def test_fixture_discovery_native_ocr_and_repeated_ingestion(ingestion, monkeypatch):
    source, service, _ = ingestion
    service.extractor.runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=tsv(), stderr=""))
    crawler, coordinator, _ = transport_fixture(ingestion, monkeypatch)
    run = coordinator.claim("manual")
    coordinator.execute(run.id, crawler.run)
    with service.database.session() as db:
        saved = db.get(CrawlRun, run.id)
        assert saved.state == "succeeded" and saved.new_count == 5 and saved.error_count == 0
        assert db.get(DataSource, source.id).last_success_at is not None
        assert [x.item_index for x in db.scalars(select(CrawlRunItem).order_by(CrawlRunItem.item_index))] == list(range(1, 6))
        assert all(origin.origin_kind == "web" for origin in db.scalars(select(DocumentOrigin)))
    staged = [call.args[1] for call in service.indexer.index.call_args_list]
    assert all(item["year"] is None for item in staged)
    pdf = next(item for item in staged if len(item["pages"]) == 2)
    assert [page["page"] for page in pdf["pages"]] == [1, 2]
    ocr = next(page for item in staged for page in item["pages"] if page["extraction_kind"] == "ocr")
    assert ocr["numeric_eligible"] is False
    assert all("REMOVE_SCRIPT" not in call.args[0] for call in service.indexer.index.call_args_list)
    extraction_calls = service.extractor.extract.call_count
    next_run = coordinator.claim("manual")
    coordinator.execute(next_run.id, crawler.run)
    assert service.indexer.index.call_count == 5 and service.extractor.extract.call_count == extraction_calls
    with service.database.session() as db:
        saved = db.get(CrawlRun, next_run.id)
        assert saved.skipped_count == 5 and saved.state == "succeeded"


def test_ocr_quarantine_initial_and_update_preserves_good_data(ingestion):
    source, service, _ = ingestion
    good = ingest(ingestion)
    service.set_enabled(good.document_id, False)
    service.extractor.runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=tsv(40), stderr=""))
    payload = SimpleNamespace(title="SYNTHETIC", year=None, campus=None, major_code=None, method=None)
    bad_bytes = (FIXTURES / "scan.pdf").read_bytes()
    result = service.process_web(source.id, BASE + "/a", bad_bytes, "application/pdf", payload)
    assert result.outcome == "error" and result.reason == "OCR_LOW_QUALITY"
    initial = service.process_web(source.id, BASE + "/bad.pdf", bad_bytes, "application/pdf", payload)
    with service.database.session() as db:
        old = db.get(Document, good.document_id)
        assert old.state == "ready" and not old.enabled and old.last_update_error == "OCR_LOW_QUALITY"
        assert "offline ingestion" in old.content_text
        quarantined = db.get(Document, initial.document_id)
        assert quarantined.state == "quarantined" and quarantined.content_hash is None
    assert service.indexer.index.call_count == 1


def test_source_failure_continues_and_retry_is_persisted(ingestion, monkeypatch):
    source, service, coordinator = ingestion
    old = ingest(ingestion)
    with service.database.session() as db:
        other = DataSource(name="SYNTHETIC second independent source", kind="utc", base_url=BASE + "/",
            allowed_paths_json=["/"], enabled=True, permission_status="allowed", reuse_basis="TEST ONLY",
            checked_at=utc_now(), robots_url=BASE + "/robots.txt", terms_url=BASE + "/terms")
        db.add(other); db.commit()
    monkeypatch.setattr("app.services.crawl.socket.getaddrinfo", lambda *_a, **_kw: [(2,1,6,"",("93.184.216.34",443))])
    transport = Mock(side_effect=[FetchResult(BASE, b"", {"Retry-After": "120"}, 429),
        FetchResult(BASE, b"User-agent: *\nAllow: /", {}),
        FetchResult(BASE, b"<main>SYNTHETIC independent description</main>", {"Content-Type": "text/html"})])
    # No waiting: each source has only one data request, clock advances on every call.
    ticks = iter(range(0, 10000, 3))
    crawler = CrawlService(service.database, service, coordinator,
        fetcher=SafeFetcher(transport=transport, monotonic=lambda: next(ticks), sleep=lambda _: None))
    service.extractor.monotonic = crawler.fetcher.monotonic
    run = coordinator.claim("manual")
    coordinator.execute(run.id, lambda rid: crawler.run(rid, [source.id, other.id]))
    with service.database.session() as db:
        saved = db.get(CrawlRun, run.id)
        outcomes = saved.source_outcomes_json
        assert sorted(item["status"] for item in outcomes) == ["error", "success"]
        assert saved.state == "partial" and saved.new_count == 1
        failed_id = next(item["source_id"] for item in outcomes if item["status"] == "error")
        assert db.get(DataSource, failed_id).retry_not_before > utc_now()
        assert db.get(DataSource, failed_id).last_success_at is None
        assert db.get(Document, old.document_id).state == "ready"


def test_counts_new_updated_skipped_error(ingestion, monkeypatch):
    source, service, coordinator = ingestion
    crawler, _, assets = transport_fixture(ingestion, monkeypatch)
    # Seed three pages. The fourth fixture is new; one existing page will change,
    # one remains unchanged, and one now has a numeric table without headers.
    payload = SimpleNamespace(title="SYNTHETIC", year=None, campus=None, major_code=None, method=None)
    for path in ["/", "/notice?year=2026", "/?page=2"]:
        file, media = assets[path]
        data = (FIXTURES / file).read_bytes() if path != "/" else b"<main>SYNTHETIC old listing</main>"
        service.process_web(source.id, BASE + path, data, media, payload)
    index_html = b'<main>SYNTHETIC changed listing<a href="/notice?year=2026">same</a><a href="/native.pdf">new</a><a href="/?page=2">bad</a></main>'
    responses = [FetchResult(BASE, (FIXTURES / "robots.txt").read_bytes(), {}),
        FetchResult(BASE + "/", index_html, {"Content-Type": "text/html"}),
        FetchResult(BASE, (FIXTURES / "notice.html").read_bytes(), {"Content-Type": "text/html"}),
        FetchResult(BASE, (FIXTURES / "native.pdf").read_bytes(), {"Content-Type": "application/pdf"}),
        FetchResult(BASE, b"<main><table><tr><td>DEMO</td><td>25</td></tr></table></main>", {"Content-Type": "text/html"})]
    crawler.fetcher.transport.side_effect = responses
    run = coordinator.claim("manual")
    coordinator.execute(run.id, crawler.run)
    with service.database.session() as db:
        saved = db.get(CrawlRun, run.id)
        assert (saved.new_count, saved.updated_count, saved.skipped_count, saved.error_count) == (1, 1, 1, 1)
        assert saved.state == "partial"


def test_h1_real_extraction_uploads_and_web_keep_all_provenance(ingestion):
    source, service, coordinator = ingestion
    data = "GIẢ LẬP nội dung UTF-8, không phải dữ liệu UTC".encode()
    origins = []
    for note, year in [("GIẢ LẬP thứ nhất", None), ("GIẢ LẬP thứ hai", None), ("GIẢ LẬP thứ hai", None), ("GIẢ LẬP khác năm", 2026)]:
        payload = SimpleNamespace(source_id=source.id, source_url=BASE + "/a", title="GIẢ LẬP",
            provenance_note=note, publisher=None, published_at=None, year=year, campus=None, major_code=None, method=None)
        origin_id, doc_id = service.accept_upload(payload, data, "text/plain")
        run = coordinator.claim("upload")
        coordinator.execute(run.id, lambda rid: service.process_upload(rid, origin_id, doc_id, "text/plain"))
        origins.append(origin_id)
    web = ingest(ingestion, data)
    assert service.extractor.extract.call_count == 2 and service.indexer.index.call_count == 2
    with service.database.session() as db:
        rows = [db.get(DocumentOrigin, identity) for identity in origins]
        assert len({row.id for row in rows}) == 4
        assert all(row.origin_kind == "upload" for row in rows)
        assert [row.provenance_note for row in rows] == ["GIẢ LẬP thứ nhất", "GIẢ LẬP thứ hai", "GIẢ LẬP thứ hai", "GIẢ LẬP khác năm"]
        assert rows[0].document_id == rows[1].document_id == rows[2].document_id == web.document_id
        assert rows[3].document_id != web.document_id
        assert len(db.scalars(select(DocumentOrigin)).all()) == 5
