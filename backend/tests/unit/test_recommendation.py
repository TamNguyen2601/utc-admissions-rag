"""Exact M1 arithmetic before rounding; synthetic rubric only."""
import pytest

from app.services.recommendation import contribution, score_major
from tests.quiz_support import catalogue, CASES


@pytest.mark.parametrize('direction,expected', [('positive', [0, .5, 1]), ('negative', [1, .5, 0]),
                                              ('none', [None, None, None])])
def test_contribution_boundaries(direction, expected):
    assert [contribution(direction, value) for value in [1, 3, 5]] == expected


@pytest.mark.parametrize('case,values,expected,status,order', CASES)
def test_m1_scores(case, values, expected, status, order):
    data = catalogue('unused', '0'*64)
    answers = {q['id']: a for q, a in zip(data['questions'], values)}
    assert [score_major(m['id'], data['questions'], answers)[0] for m in data['majors']] == expected


def test_negative_reason_is_disagreement_none_never_explains():
    data = catalogue('unused', '0'*64)
    answers = {q['id']: a for q, a in zip(data['questions'], [5, 1] + [5]*8)}
    score, reasons = score_major(data['majors'][0]['id'], data['questions'], answers)
    assert score == 100 and len(reasons) == 2
    assert 'đồng ý' in reasons[0] and 'không đồng ý' in reasons[1] and 'nghịch' in reasons[1]
    assert 'câu 2:' in reasons[1] and all('câu 3:' not in reason for reason in reasons)


@pytest.mark.parametrize('bad', ['zero', 'missing', 'direction'])
def test_corrupt_mapping_never_divides_by_zero_or_defaults_none(bad):
    data = catalogue('unused', '0'*64)
    major = data['majors'][0]['id']
    for q in data['questions']:
        if bad == 'zero': q['scoring'][major]['direction'] = 'none'
        elif bad == 'missing': q['scoring'].pop(major)
        else: q['scoring'][major]['direction'] = 'bogus'
    with pytest.raises(ValueError):
        score_major(major, data['questions'], {q['id']: 3 for q in data['questions']})


@pytest.mark.parametrize('direction,value', [('bogus', 3), ('positive', True), ('negative', 0),
                                           ('positive', 6), ('positive', 3.0)])
def test_invalid_contribution(direction, value):
    with pytest.raises(ValueError): contribution(direction, value)
