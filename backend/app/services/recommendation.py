"""Deterministic scoring and atomic, offline catalogue replacement. No model calls."""
from fractions import Fraction
import hashlib
import json
import re
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.models.knowledge import Document
from app.models.quiz import Major, QuizQuestion
from app.schemas.quiz import CatalogInput, DISCLAIMER, MajorInput
from app.services.retrieval import usable_origins
from app.services.scope import normalized

OPTIONS = [dict(value=i, label=label) for i, label in enumerate(
    ['Rất không đồng ý', 'Không đồng ý', 'Trung lập', 'Đồng ý', 'Rất đồng ý'], 1)]
SCORING_DESCRIPTION = (
    'Quy tắc tham khảo của dự án, không phải chẩn đoán tâm lý. '
    'positive=(answer-1)/4; negative=(5-answer)/4; none không tham gia tổng, mẫu số hoặc lý do. '
    'fit=100*sum(contribution)/N, N là số câu khác none (N>=1). '
    'Sắp điểm chưa làm tròn giảm dần, rồi mã ngành/cơ sở tăng dần; tối đa 5 ngành điểm dương, ít nhất 3. '
    'Hiển thị 2 chữ số thập phân; tối đa 2 lý do contribution>=0,75, ưu tiên contribution rồi vị trí câu.')
MISSING_MESSAGE = 'Chưa có catalogue nguồn UTC và bộ 10 câu với mapping đầy đủ, còn hiệu lực.'


class QuizError(HTTPException):
    def __init__(self, status_code, code):
        super().__init__(status_code)
        self.code = code


def contribution(direction, answer):
    if type(answer) is not int or not 1 <= answer <= 5:
        raise ValueError('INVALID_ANSWER')
    if direction == 'positive': return Fraction(answer - 1, 4)
    if direction == 'negative': return Fraction(5 - answer, 4)
    if direction == 'none': return None
    raise ValueError('INVALID_DIRECTION')


def score_major(major_id, questions, answers):
    values, reasons = [], []
    for question in questions:
        rule = question['scoring'].get(major_id)
        if not isinstance(rule, dict) or not isinstance(rule.get('reason'), str) or not rule['reason'].strip():
            raise ValueError('INVALID_MAPPING')
        value = contribution(rule.get('direction'), answers[question['id']])
        if value is None:
            continue
        values.append(value)
        if value >= Fraction(3, 4):
            stance = 'đồng ý với câu thuận' if rule['direction'] == 'positive' else 'không đồng ý với câu nghịch'
            reason = f'Bạn {stance} “{question["text"]}”: {rule["reason"]}'
            reasons.append((value, question['position'], reason))
    if not values:
        raise ValueError('ZERO_DENOMINATOR')
    reasons.sort(key=lambda item: (-item[0], item[1]))
    return 100 * sum(values) / len(values), [r[2] for r in reasons[:2]] or ['Chưa có xu hướng nổi trội.']


def major_input(major):
    return dict(id=major.id, code=major.code, name=major.name, campus=major.campus,
        description=major.description, source_document_id=major.source_document_id,
        source_content_hash=major.source_content_hash, source_page=major.source_page,
        career_groups=major.career_groups_json)


def major_sources(db, major):
    document = db.get(Document, str(major.source_document_id))
    if (document is None or document.state != 'ready' or not document.enabled or not document.content_text
            or not document.content_hash or document.content_hash != major.source_content_hash):
        return []
    sources = []
    for origin, source in usable_origins(db, document.id):
        if source.kind not in {'utc', 'catalog', 'upload'}:
            continue
        host = urlsplit(origin.canonical_url).hostname or ''
        official_url = host == 'utc.edu.vn' or host.endswith('.utc.edu.vn')
        # Offline originals require an identified UTC publisher and retained provenance.
        official_upload = (origin.origin_kind == 'upload' and origin.canonical_url.startswith('urn:upload:')
            and normalized(origin.publisher or '').casefold() in {
                'utc', 'trường đại học giao thông vận tải', 'đại học giao thông vận tải'}
            and bool(origin.provenance_note))
        if not (official_url or official_upload):
            continue
        sources.append(dict(document_id=document.id, title=document.title, url=origin.canonical_url,
                            source_name=source.name, page=major.source_page))
    return sources


def public_major(major, sources):
    return dict(id=str(major.id), code=major.code, name=major.name, campus=major.campus,
                description=major.description,
                career_groups=[g.model_dump() for g in major.career_groups], sources=sources)


class RecommendationService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def _version(data):
        content = data.model_dump(mode='json')
        content['majors'].sort(key=lambda m: (m['code'], m['campus'], m['id']))
        content['questions'].sort(key=lambda q: q['position'])
        return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                          separators=(',', ':')).encode('utf-8')).hexdigest()

    def import_catalog(self, payload):
        data = CatalogInput.model_validate(payload)
        with self.database.session() as db:
            # PEP 249 autocommit=False starts one transaction for reads and writes.
            # This offline CLI is run with the backend stopped.
            for major in data.majors:
                if not major_sources(db, major):
                    raise ValueError('CATALOG_SOURCE_UNAVAILABLE')
                document = db.get(Document, str(major.source_document_id))
                # Human-curated descriptions/mappings remain the author's responsibility.
                # Identity must at least be supported by the current source text.
                content = normalized(document.content_text).casefold()
                if normalized(major.name).casefold() not in content or not re.search(
                        r'(?<!\w)' + re.escape(major.code.casefold()) + r'(?!\w)', content):
                    raise ValueError('MAJOR_IDENTITY_NOT_IN_SOURCE')
            db.execute(delete(QuizQuestion))
            db.execute(delete(Major))
            for major in data.majors:
                row = major.model_dump(mode='json')
                row['career_groups_json'] = row.pop('career_groups')
                db.add(Major(**row))
            for question in data.questions:
                row = question.model_dump(mode='json')
                row['scoring_json'] = row.pop('scoring')
                db.add(QuizQuestion(**row))
            db.flush()
            db.commit()
        return self._version(data)

    def _load(self, db):
        majors = db.scalars(select(Major).where(Major.active.is_(True)).order_by(Major.code, Major.campus)).all()
        questions = db.scalars(select(QuizQuestion).where(QuizQuestion.active.is_(True))
                               .order_by(QuizQuestion.position)).all()
        try:
            data = CatalogInput.model_validate(dict(majors=[major_input(m) for m in majors], questions=[
                dict(id=q.id, position=q.position, text=q.text, scoring=q.scoring_json) for q in questions]))
            sources = {str(m.id): major_sources(db, m) for m in data.majors}
            if any(not source for source in sources.values()):
                return None
        except (ValidationError, ValueError, TypeError):
            return None
        return data, sources, self._version(data)

    def quiz(self):
        with self.database.session() as db:
            loaded = self._load(db)
            if loaded is None:
                return dict(status='data_missing', rubric_version=None, questions=[], scoring_description=None,
                            missing_fields=['catalogue_or_rubric'], message=MISSING_MESSAGE)
            data, sources, version = loaded
            questions = [dict(id=str(q.id), position=q.position, text=q.text, options=OPTIONS, scoring=[
                dict(major_id=str(m.id), **q.scoring[m.id].model_dump()) for m in data.majors]) for q in data.questions]
            return dict(status='ready', rubric_version=version, questions=questions,
                        scoring_description=SCORING_DESCRIPTION, missing_fields=[], message=None)

    def recommend(self, payload):
        with self.database.session() as db:
            loaded = self._load(db)
            base = dict(items=[], missing_fields=[], message=None, disclaimer=DISCLAIMER)
            if loaded is None:
                return base | dict(status='data_missing', rubric_version=None,
                                   missing_fields=['catalogue_or_rubric'], message=MISSING_MESSAGE)
            data, sources, version = loaded
            if payload.rubric_version != version:
                raise QuizError(409, 'RUBRIC_CHANGED')
            answers = {str(answer.question_id): answer.value for answer in payload.answers}
            if set(answers) != {str(q.id) for q in data.questions}:
                raise QuizError(422, 'INVALID_QUIZ_ANSWERS')
            questions = data.model_dump(mode='json')['questions']
            scored = []
            for major in data.majors:
                score, reasons = score_major(str(major.id), questions, answers)
                if score > 0:
                    source = sources[str(major.id)][0]
                    citation = f' Nguồn: {source["title"]} ({source["url"]}'
                    citation += f', trang {source["page"]}).' if source['page'] is not None else ').'
                    scored.append((score, major, [r + citation for r in reasons]))
            if len(scored) < 3:
                return base | dict(status='insufficient_matches' if scored else 'no_match', rubric_version=version,
                    message='Chưa đủ 3 ngành phù hợp có điểm dương.' if scored else 'Chưa có ngành phù hợp với bộ đáp án này.')
            scored.sort(key=lambda row: (-row[0], row[1].code, row[1].campus))
            return base | dict(status='ready', rubric_version=version, items=[dict(
                major=public_major(m, sources[str(m.id)]), fit_score=round(float(score), 2), reasons=reasons)
                for score, m, reasons in scored[:5]])

    def list_majors(self, *, campus=None, page=1, page_size=20):
        with self.database.session() as db:
            rows = db.scalars(select(Major).where(Major.active.is_(True)).order_by(Major.code, Major.campus)).all()
            items = []
            for row in rows:
                if campus is not None and row.campus != campus:
                    continue
                try:
                    major = MajorInput.model_validate(major_input(row))
                    sources = major_sources(db, major)
                    if sources: items.append(public_major(major, sources))
                except (ValidationError, ValueError, TypeError):
                    continue
            return dict(items=items[(page - 1)*page_size:page*page_size], total=len(items), page=page, page_size=page_size)

    def career_groups(self):
        return {g['code'] for major in self.list_majors(page_size=2**31)['items'] for g in major['career_groups']}

    def major_groups(self, major_id):
        with self.database.session() as db:
            row = db.get(Major, major_id)
            if row is None:
                raise HTTPException(404)
            try:
                major = MajorInput.model_validate(major_input(row))
                if not row.active or not major_sources(db, major):
                    return None
                return {g.code for g in major.career_groups}
            except (ValidationError, ValueError, TypeError):
                return None

    def resolves_scope(self, text):
        text = normalized(text).casefold()
        for major in self.list_majors(page_size=2**31)['items']:
            # Full names/labels only. A generic career question still needs clarification.
            terms = [major['name'], *(g['label'] for g in major['career_groups'])]
            if any(re.search(r'(?<!\w)' + re.escape(normalized(term).casefold()) + r'(?!\w)', text) for term in terms):
                return True
        return False
