"""GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC; temporary SQLite, synthetic encoder."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.base import utc_now
from app.models.career import JobPosting
from app.models.crawl import CrawlRun, CrawlRunItem
from app.models.knowledge import DataSource
from app.services.embedding import EmbeddingService, Indexer
from app.services.extraction import Extractor
from app.services.jobs import JobService
from tests.contract.knowledge_support import admin_client, create_source  # noqa: F401
from tests.knowledge_support import Model

BASE = '/api/v1'


@pytest.fixture
def job_client(admin_client, settings):
    state = admin_client.app.state
    model = Model()
    state.documents.indexer = Indexer(state.database, EmbeddingService(settings, model=model))
    state.documents.extractor = Extractor(settings)
    state.jobs = JobService(state.database, state.documents, state.coordinator)
    source = create_source(admin_client, name='SYNTHETIC publisher', kind='career',
        base_url='https://publisher.example.test/', allowed_paths=['/jobs'],
        robots_url='https://publisher.example.test/robots.txt',
        terms_url='https://publisher.example.test/terms')
    admin_client.job_source = source['id']
    admin_client.job_model = model
    return admin_client


def row(client, **changes):
    return dict(title='SYNTHETIC engineering', employer='SYNTHETIC employer',
        description='SYNTHETIC engineering role. Not an official job.',
        source_id=client.job_source, source_url='https://publisher.example.test/jobs/one',
        collected_at=(utc_now() - timedelta(days=1)).isoformat(),
        deadline_at=(utc_now() + timedelta(days=30)).isoformat(), observed_status='open') | changes


def import_rows(client, rows, **data):
    return client.post(BASE + '/admin/jobs/import', data=data,
        files={'file': ('synthetic.json', json.dumps(rows, ensure_ascii=False).encode(), 'application/json')})


def results(client, response):
    assert response.status_code == 202, response.text
    with client.app.state.database.session() as db:
        run = db.get(CrawlRun, response.json()['run_id'])
        items = db.scalars(select(CrawlRunItem).where(CrawlRunItem.run_id == run.id)
                           .order_by(CrawlRunItem.item_index)).all()
    return run, items


def stored_jobs(client):
    with client.app.state.database.session() as db:
        return db.scalars(select(JobPosting).order_by(JobPosting.id)).all()
