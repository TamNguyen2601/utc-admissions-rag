"""Small deterministic scope rules; catalogue lookup is injectable, never invented."""
from dataclasses import dataclass, field
import re
import unicodedata

from app.schemas.chat import Context, GuestChatInput


def normalized(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


UTC = re.compile(r'\butc\b|(?:đại học|trường) giao thông vận tải', re.I)
OTHER_SCHOOL = re.compile(
    r'bách khoa|\b(?:hust|neu|uth|uit|hcmut|ftu|rmit|fpt)\b|kinh tế quốc dân|'
    r'đại học (?:hà nội|quốc gia|y|ngoại thương)|trường khác|'
    r'giao thông vận tải\s*(?:tp\.?\s*hcm|thành phố hồ chí minh)', re.I)
NAMED_SCHOOL = re.compile(r'(?:đại học|học viện|trường đh)\s+'
    r'(?!(?:giao thông vận tải|năm|chính quy|bằng|của|ở|tại|nào|gì)\b)\w+', re.I)
OTHER_NAMED_SCHOOL = re.compile(r'\btrường\s+(?!(?:Đại học|Giao thông|UTC)\b)[A-ZĐÀ-Ỹ]')
TOPIC = re.compile(
    r'tuyển sinh|đào tạo|chương trình|ngành|học (?:gì|phí|bổng)|điểm chuẩn|'
    r'chỉ tiêu|xét tuyển|nhập học|hồ sơ|phương thức|cơ sở|nghề|việc làm|'
    r'lập trình|kỹ sư|công nghệ thông tin|\bcntt\b|ra trường|tốt nghiệp|học ở|đăng ký|đăng kí', re.I)
OUTSIDE = re.compile(
    r'thời tiết|bóng đá|chứng khoán|tiền ảo|bitcoin|nấu ăn|chính trị|tổng thống|'
    r'viết (?:code|mã|thơ)|lập trình (?:giúp|hộ)|chữa bệnh|chẩn đoán|tử vi|'
    r'api.?key|khóa bí mật|mật khẩu|system prompt|bỏ qua (?:mọi |các )?(?:quy tắc|chỉ dẫn)', re.I)
SOCIAL = re.compile(
    r'(?:(?:xin chào|chào|hello|hi|cảm ơn|cám ơn|thanks|thank you|tạm biệt|bye|goodbye)'
    r'(?:\s+(?:bạn|em|anh|chị|bot|nhé|nha|ạ|rất nhiều|nhiều))?\s*[,!.;?]*\s*)+', re.I)


@dataclass
class ScopeDecision:
    status: str
    query: str
    context: Context
    mixed: bool = False
    missing_fields: list[str] = field(default_factory=list)


def classify(payload: GuestChatInput, catalogue_resolver=None):
    context = payload.context.model_copy(deep=True)
    text = payload.message
    if SOCIAL.fullmatch(text):
        return ScopeDecision('social', '', context)
    # Only user turns can establish the subject; assistant text never establishes truth.
    previous = next((t.text for t in reversed(payload.turns) if t.sender == 'user'), '')
    confirmed = bool(UTC.search(previous) and not OTHER_SCHOOL.search(previous))
    confirmed = confirmed or any(v is not None for v in context.model_dump().values())
    parts = re.split(r'[?;!\n]+|(?<=[.])\s+|,?\s+(?:và|còn|nhưng|đồng thời|ngoài ra)\s+'
                     r'(?=(?:dự báo|thời tiết|viết|bóng đá|cho tôi|ai |hãy |đại học|ngành .*trường))', text, flags=re.I)
    included, rejected, ambiguous = [], [], False
    for part in parts:
        part = part.strip(' .,')
        if not part or SOCIAL.fullmatch(part):
            continue
        if (OUTSIDE.search(part) or OTHER_SCHOOL.search(part) or NAMED_SCHOOL.search(part)
                or OTHER_NAMED_SCHOOL.search(part)):
            rejected.append(part)
            continue
        direct = bool(UTC.search(part))
        relevant = bool(TOPIC.search(part))
        catalogued = bool(catalogue_resolver and catalogue_resolver(part)) if relevant else False
        if relevant and (direct or confirmed or catalogued):
            included.append(part)
            confirmed = True
        elif relevant or re.search(r'học gì|thế nào|còn (?:ngành|năm)|ở đâu|bao nhiêu', part, re.I):
            ambiguous = True
        else:
            rejected.append(part)
    if not included:
        return ScopeDecision('needs_clarification' if ambiguous else 'out_of_scope', '', context,
                             missing_fields=['subject'] if ambiguous else [])
    query = '. '.join(included)
    # Explicit context in the current question must not be silently overridden by a filter.
    inferred = {}
    for key, pattern in (
        ('year', r'\bnăm\s*(\d{4})\b'),
        ('major_code', r'\b(?:mã\s+)?ngành\s*:?\s*(\d{7})\b'),
        ('campus', r'\bcơ sở\s*:?\s*(Hà Nội|TP\.?\s*HCM|Hồ Chí Minh|HN|HCM)\b'),
        ('method', r'\bphương thức\s*:?\s*(THPT|ĐGNL|DGNL|học bạ|xét tuyển thẳng)\b'),
    ):
        values = re.findall(pattern, query, re.I)
        if len(set(v.casefold() for v in values)) > 1:
            return ScopeDecision('needs_clarification', query, context, missing_fields=[key])
        if values:
            inferred[key] = int(values[0]) if key == 'year' else values[0]
    for key, value in inferred.items():
        existing = getattr(context, key)
        if existing is not None and str(existing).casefold() != str(value).casefold():
            return ScopeDecision('needs_clarification', query, context, missing_fields=[key])
        setattr(context, key, value)
    return ScopeDecision('retrieve', query, context, bool(rejected or ambiguous))
