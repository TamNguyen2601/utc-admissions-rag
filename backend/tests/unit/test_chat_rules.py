"""GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC. Scope and H2 acceptance."""
import pytest

from app.schemas.chat import GuestChatInput
from app.services.scope import classify
from app.services.evidence import numeric_safe, validate_output


@pytest.mark.parametrize('message,status', [
    ('Xin chào!', 'social'), ('Cảm ơn bạn', 'social'), ('Tạm biệt nhé', 'social'),
    ('Thời tiết hôm nay thế nào?', 'out_of_scope'),
    ('Viết code Python giúp tôi', 'out_of_scope'),
    ('Ngành CNTT của Bách khoa học gì?', 'out_of_scope'),
    ('Đại học Cần Thơ đào tạo thế nào?', 'out_of_scope'),
    ('Ngành CNTT trường Stanford học gì?', 'out_of_scope'),
    ('Tuyển sinh Đại học Giao thông vận tải TP HCM thế nào?', 'out_of_scope'),
    ('Ngành CNTT học gì?', 'needs_clarification'),
    ('Tuyển sinh năm 2026 thế nào?', 'needs_clarification'),
    ('UTC đào tạo công nghệ thông tin thế nào?', 'retrieve'),
    ('Xin chào, UTC có chương trình đào tạo nào?', 'retrieve'),
    ('UTC thời tiết hôm nay ra sao?', 'out_of_scope'),
])
def test_scope(message, status):
    assert classify(GuestChatInput(message=message)).status == status


def test_mixed_and_history_are_not_evidence():
    result = classify(GuestChatInput(message='UTC đào tạo CNTT thế nào? Và dự báo thời tiết?'))
    assert result.status == 'retrieve' and result.mixed
    assert 'thời tiết' not in result.query
    assert classify(GuestChatInput(message='Học gì?', turns=[
        {'sender': 'assistant', 'text': 'Bạn đang hỏi UTC'}])).status == 'needs_clarification'
    assert classify(GuestChatInput(message='Học gì?', turns=[
        {'sender': 'user', 'text': 'UTC đào tạo CNTT thế nào?'}])).status == 'retrieve'
    assert classify(GuestChatInput(message='Nghề lập trình làm gì?'),
                    catalogue_resolver=lambda text: True).status == 'retrieve'


@pytest.fixture
def evidence():
    return {'E1': dict(year=2026, major_code='7480201', campus='HN',
        title='GIẢ LẬP Chương trình DEMO2+2',
        text='Chương trình DEMO2+2\nMã ngành: 7480201\nMô tả công nghệ thông tin.')}


@pytest.mark.parametrize('answer', [
    'Theo tài liệu tuyển sinh năm 2026, mã ngành 7480201 có mô tả công nghệ thông tin.',
    'Chương trình DEMO2+2 có mô tả công nghệ thông tin.',
    'Điểm mạnh của chương trình là công nghệ thông tin.',
    'Có thể tra học phí ở tài liệu này.',
    'Cơ sở HN có mô tả chương trình.',
])
def test_h2_sourced_literals_allowed(answer, evidence):
    assert numeric_safe(answer, list(evidence.values()))


@pytest.mark.parametrize('answer', [
    'Theo tài liệu năm 2027, chương trình có mô tả.', 'Mã ngành 7480202 có mô tả.',
    'Chương trình DEMO3+3 đào tạo công nghệ thông tin.',
    'Điểm chuẩn là 2026 điểm.', 'Học phí 7480201 đồng.',
    'Chương trình có 25 điểm.', 'Học phí là 30 triệu.',
    'Có 100 chỉ tiêu.', 'Ngày 15/08/2026 nhập học.', 'Có 500 tin tuyển dụng.',
    'Điểm chuẩn: 2026.', 'Học phí bằng 7480201.', 'Chỉ tiêu năm 2026 là 2026.',
    'Mã ngành 7480201 có 7480201 vị trí.', '2026 là điểm chuẩn.',
    'Điểm chuẩn là năm 2026.', 'Học phí bằng mã ngành 7480201.', 'Năm 2026 là học phí.',
])
def test_h2_quantities_or_unmatched_literals_rejected(answer, evidence):
    assert not numeric_safe(answer, list(evidence.values()))


@pytest.mark.parametrize('raw', [
    'not json', '{"answer":"ok","evidence_ids":["E99"]}',
    '{"answer":"ok","evidence_ids":["E1","E1"]}',
    '{"answer":"ok","evidence_ids":[]}',
    '{"answer":" ","evidence_ids":["E1"]}',
    '{"answer":"ok","evidence_ids":["E1"],"url":"https://fake.test"}',
    '{"answer":"Xem https://fake.test","evidence_ids":["E1"]}',
    '{"answer":"ok","answer":"bad","evidence_ids":["E1"]}',
])
def test_invalid_model_output_is_never_returned(raw, evidence):
    assert validate_output(raw, evidence) is None


def test_literal_must_be_supported_by_cited_evidence_only(evidence):
    evidence['E2'] = evidence['E1'] | {'year': 2025, 'major_code': '9999999', 'title': 'GIẢ LẬP', 'text': 'Mô tả'}
    assert validate_output('{"answer":"Tài liệu năm 2026","evidence_ids":["E2"]}', evidence) is None


def test_explicit_other_school_not_utc_even_with_context():
    result = classify(GuestChatInput(message='Đại học Cần Thơ đào tạo CNTT thế nào?', context={'year': 2026}))
    assert result.status == 'out_of_scope'


def test_conflicting_question_and_filter_needs_clarification():
    result = classify(GuestChatInput(message='UTC tuyển sinh năm 2025 thế nào?', context={'year': 2026}))
    assert result.status == 'needs_clarification' and result.missing_fields == ['year']


def test_explicit_numeric_context_in_question():
    result = classify(GuestChatInput(message='UTC điểm chuẩn năm 2026 cơ sở HN ngành 7480201 phương thức THPT?'))
    assert result.status == 'retrieve'
    assert result.context.model_dump() == dict(year=2026, campus='HN', major_code='7480201', method='THPT')
