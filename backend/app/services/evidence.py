"""Request-local evidence gate and conservative numeric rules, not a claim parser."""
from dataclasses import dataclass, field
import json
import re

from pydantic import ValidationError

from app.schemas.chat import Citation, GeminiOutput
from app.services.scope import normalized


INJECTION = re.compile(
    r'ignore\s+(?:all\s+|previous\s+|the\s+)*(?:instructions|rules|prompt)|'
    r'system\s*prompt|(?:reveal|print|expose).{0,25}(?:secret|api.?key)|'
    r'bỏ qua.{0,25}(?:chỉ dẫn|quy tắc|hướng dẫn)|(?:tiết lộ|in ra).{0,25}(?:khóa|bí mật)|'
    r'<\s*/?\s*(?:system|assistant)|\[INST\]', re.I)
TOPICS = {
    'cutoff': r'điểm chuẩn', 'tuition': r'học phí', 'quota': r'chỉ tiêu',
    'date': r'ngày|hạn|lịch (?:tuyển sinh|xét tuyển|nhập học)',
    'count': r'số (?:tin|lượng|vị trí)|bao nhiêu (?:tin|việc|vị trí)',
}
NUMBER = r'\d+(?:[.,]\d+)*'
QUANTITATIVE = re.compile(
    rf'{NUMBER}\s*(?:điểm\b|triệu\b|nghìn\b|ngàn\b|tỷ\b|đồng\b|vnđ\b|vnd\b|%|chỉ tiêu\b|'
    r'tin\b|vị trí\b|sinh viên\b|thí sinh\b|người\b|tín chỉ\b|năm\b|tháng\b|ngày\b)|'
    rf'(?:điểm chuẩn|học phí|chỉ tiêu|số tin|số vị trí)\s*(?:(?:là|bằng|:|=|ở mức|khoảng|từ|đến)\s*)*{NUMBER}|'
    r'\d{1,4}\s*[/\-]\s*\d{1,2}(?:\s*[/\-]\s*\d{2,4})?|'
    r'(?:ngày|hạn)\s*:?\s*\d|'
    r'(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|trăm|nghìn|triệu)\s+(?:điểm|triệu|đồng|chỉ tiêu|vị trí|tin)\b', re.I)
QUANTITY_AS_IDENTIFIER = re.compile(
    rf'(?:điểm chuẩn|học phí|chỉ tiêu|số tin|số vị trí)\s*(?:là|bằng|:|=|ở mức)\s*'
    rf'(?:năm|mã ngành|cơ sở|chương trình)\s*:?\s*\S*\d|'
    rf'(?:năm|mã ngành)\s*:?\s*{NUMBER}\s*(?:là|bằng|:)\s*(?:điểm chuẩn|học phí|chỉ tiêu)', re.I)


def numeric_topic(query):
    """A request for quantities bypasses Gemini. Merely mentioning fees is not enough."""
    if re.search(r'cách (?:tra|tìm|xem)|tra cứu ở đâu|điểm mạnh', query, re.I):
        return None
    for topic, pattern in TOPICS.items():
        if re.search(pattern, query, re.I):
            return topic
    return None


def numeric_safe(answer, cited):
    text = normalized(answer)
    if QUANTITATIVE.search(text) or QUANTITY_AS_IDENTIFIER.search(text):
        return False
    # Allow complete role-bearing literals, never bare numbers found anywhere in text.
    spans = []
    for hit in cited:
        year, code = hit.get('year'), hit.get('major_code')
        patterns = []
        if year is not None:
            patterns.append(rf'\bnăm\s+{re.escape(str(year))}(?!\d)')
        if code:
            patterns.append(rf'\bmã ngành\s*:?\s*{re.escape(code)}(?!\w)')
        if hit.get('campus'):
            patterns.append(rf'\bcơ sở\s*:?\s*{re.escape(normalized(hit["campus"]))}(?!\w)')
        # Names are only collected from labelled name lines / title, not arbitrary prose.
        for source in (hit.get('title', ''), hit.get('section') or '', hit['text']):
            for line in source.splitlines():
                for name in re.finditer(
                    r'(?:chương trình|tên ngành|tên chương trình|cơ sở)\s*:?\s*([^|.;\n]+)', line, re.I):
                    literal = re.split(r'\s+(?:có|đào tạo|tập trung|là|học phí|điểm chuẩn)\s+',
                                       name.group(), maxsplit=1, flags=re.I)[0]
                    literal = normalized(literal)
                    if re.search(r'\d', literal):
                        patterns.append(rf'(?<!\w){re.escape(literal)}(?!\w|\+)')
        for pattern in patterns:
            spans.extend(m.span() for m in re.finditer(pattern, text, re.I))
    return all(any(start <= m.start() and m.end() <= end for start, end in spans)
               for m in re.finditer(r'\d+', text))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def validate_output(raw, evidence):
    try:
        output = GeminiOutput.model_validate(json.loads(raw, object_pairs_hook=_unique_object), strict=True)
        if any(identity not in evidence for identity in output.evidence_ids):
            return None
        cited = [evidence[identity] for identity in output.evidence_ids]
        if (re.search(r'https?://|www\.|urn:|\[[^\]]+\]|(?:nguồn|source)\s*:', output.answer, re.I)
                or INJECTION.search(output.answer) or not numeric_safe(output.answer, cited)):
            return None
        return output
    except (ValueError, TypeError, ValidationError):
        return None


def citations(hits):
    keys = Citation.model_fields
    return [Citation(**{key: hit[key] for key in keys}) for hit in hits]


STOP_WORDS = set('utc trường đại học giao thông vận tải tuyển sinh ngành chương trình đào tạo '
                 'cho tôi bạn về thế nào gì có là của và ở một các những được giúp hãy xin chào '
                 'năm mã cơ sở phương thức theo tài liệu biết muốn hỏi không'.split())


def relevant(query, hit, topic):
    if topic:
        return bool(re.search(TOPICS[topic], hit['text'], re.I))
    tokens = set(re.findall(r'[^\W_]+', query.casefold())) - STOP_WORDS
    tokens = {token for token in tokens if not token.isdigit()}
    text = normalized(' '.join((hit['title'], hit.get('section') or '', hit['text']))).casefold()
    if not tokens:
        return bool(re.search(r'tuyển sinh|chương trình|đào tạo|ngành', text))
    # A high cosine is not evidence. Require meaningful lexical subject overlap too.
    words = set(re.findall(r'[^\W_]+', text))
    return len(tokens & words) >= min(2, len(tokens))


@dataclass
class EvidenceDecision:
    status: str
    hits: list[dict] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    text: str = ''


def gate(query, context, hits, *, has_knowledge):
    topic = numeric_topic(query)
    if topic:
        required = ['year', 'campus']
        if topic == 'cutoff':
            required += ['major_code', 'method']
        elif topic in {'tuition', 'quota'} and re.search(r'ngành', query, re.I):
            required += ['major_code']
        missing = [key for key in required if getattr(context, key) is None]
        if missing:
            return EvidenceDecision('needs_clarification', missing_fields=missing)
    selected = []
    for hit in hits:
        source_text = '\n'.join((hit['title'], hit.get('section') or '', hit['text']))
        if (not hit.get('available') or INJECTION.search(source_text)
                or any(value is not None and hit.get(key) != value
                       for key, value in context.model_dump().items())
                or not relevant(query, hit, topic)):
            continue
        selected.append(hit)
    if not selected:
        return EvidenceDecision('insufficient_evidence' if has_knowledge else 'data_missing')
    # Do not silently pick one year/campus/major/method when the question leaves it open.
    varying = [key for key in type(context).model_fields if getattr(context, key) is None
               and len({hit.get(key) for hit in selected}) > 1]
    if varying:
        return EvidenceDecision('needs_clarification', missing_fields=varying)
    if not topic:
        return EvidenceDecision('generate', selected)
    if topic == 'count' or re.search(r'chênh lệch|xác suất|đảm bảo|bảo đảm|tính|so sánh|dự đoán', query, re.I):
        # Counts belong to the jobs service (later tasks); never synthesize them here.
        return EvidenceDecision('insufficient_evidence')
    native = [hit for hit in selected if hit.get('extraction_kind') == 'native'
              and hit.get('numeric_eligible') and all(
                  hit.get(key) is not None for key in ('year', 'campus'))]
    # Choose explicit labelled lines, retaining the whole chunk with headers/conditions.
    # Do not treat context identifiers elsewhere in the chunk as measured values.
    values, usable = [], []
    pattern = (rf'(?:{TOPICS[topic]})\s*(?::|là)?\s*({NUMBER}(?:\s*[/\-]\s*\d+)*)')
    for hit in native:
        matches = re.findall(pattern, hit['text'], re.I)
        # Reject a row with explicit context contradicting its chunk metadata, or
        # several measurements whose row cannot be uniquely identified. No guessed row.
        context_ok = True
        for key, label in [('year', 'năm'), ('major_code', 'mã ngành'),
                           ('campus', 'cơ sở'), ('method', 'phương thức')]:
            explicit = re.findall(rf'\b{label}\s*:\s*([^|\n;]+)', hit['text'], re.I)
            if any(normalized(value).casefold() != str(hit.get(key)).casefold() for value in explicit):
                context_ok = False
        units_ok = topic != 'tuition' or bool(re.search(r'đồng|\bvn[đd]\b|triệu|nghìn|ngàn', hit['text'], re.I))
        if matches and len(set(matches)) == 1 and context_ok and units_ok:
            values.append(tuple(normalized(value) for value in matches))
            usable.append(hit)
    if not usable:
        return EvidenceDecision('insufficient_evidence')
    if len(set(values)) > 1:
        return EvidenceDecision('conflicting_sources', usable)
    # No arithmetic, rewording or model generation on this path.
    hit = usable[0]
    labels = ', '.join(f'{key}: {value}' for key, value in context.model_dump().items() if value is not None)
    return EvidenceDecision('answered', [hit], text=f'Trích nguyên văn ({labels}):\n{hit["text"]}')
