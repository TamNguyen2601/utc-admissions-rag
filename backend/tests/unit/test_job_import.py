"""Parser boundaries, including CSV logical records; no database or network."""
import json

import pytest
from fastapi import HTTPException

from app.services.adapters.job_import import parse_import


def test_exact_twenty_mib_accepted_and_over_rejected():
    maximum = 20 * 1024 * 1024
    data = b'[]' + b' ' * (maximum - 2)
    assert parse_import(data, 'fixture.json', 'application/json') == []
    with pytest.raises(HTTPException) as exc:
        parse_import(data + b' ', 'fixture.json', 'application/json')
    assert exc.value.status_code == 413


def test_five_thousand_records_boundary():
    assert len(parse_import(json.dumps([{}] * 5000).encode(), 'x.json', 'application/json')) == 5000
    with pytest.raises(HTTPException) as exc:
        parse_import(json.dumps([{}] * 5001).encode(), 'x.json', 'application/json')
    assert exc.value.status_code == 422
    header = b'title,employer,description,source_url,collected_at\n'
    assert len(parse_import(header + b'a,b,c,d,e\n' * 5000, 'x.csv', 'text/csv')) == 5000
    with pytest.raises(HTTPException): parse_import(header + b'a,b,c,d,e\n' * 5001, 'x.csv', 'text/csv')


@pytest.mark.parametrize('data,filename,media', [
    (b'\xff', 'x.json', 'application/json'), (b'[1]', 'x.json', 'application/json'),
    (b'[{"title":"a","title":"b"}]', 'x.json', 'application/json'),
    (b'[{"x":NaN}]', 'x.json', 'application/json'),
    (b'title\nx', 'x.csv', 'text/csv'),
    (b'title,employer,description,source_url,collected_at\na,b,c,d,e,extra', 'x.csv', 'text/csv'),
    (b'title,employer,description,source_url,collected_at\na,b,c,d', 'x.csv', 'text/csv'),
    (b'title,employer,description,source_url,collected_at\n"unterminated', 'x.csv', 'text/csv'),
])
def test_structural_errors_reject_entire_file(data, filename, media):
    with pytest.raises(HTTPException) as exc: parse_import(data, filename, media)
    assert exc.value.status_code == 422


def test_csv_quoted_newline_is_one_logical_record():
    rows = parse_import(b'title,employer,description,source_url,collected_at\na,b,"one\ntwo",d,e\n',
                        'fixture.csv', 'text/csv')
    assert len(rows) == 1 and rows[0]['description'] == 'one\ntwo'
