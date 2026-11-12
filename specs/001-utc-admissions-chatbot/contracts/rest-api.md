# REST API contract v1

Base `/api/v1`, JSON UTF-8, không streaming. Thiết kế chưa phải API đang chạy.
Mọi schema đóng (extra fields bị422); UUID string; timestamp UTC RFC3339; nullable dùng null,
không bỏ khóa trong response được mô tả. List: page>=1, page_size1..100 default20,
`{items,total,page,page_size}`. Thời gian hiển thị UI theo Việt Nam.

Public không bắt buộc Bearer; Bearer đã gửi mà sai/hết hạn thì401, không downgrade Guest.
User = USER/ADMIN hợp lệ; Owner = user_id của resource, áp dụng cả ADMIN;
Admin = role ADMIN từ DB. 401 có WWW-Authenticate: Bearer, sai role403, sai owner404.

## Lỗi và DTO chung

Lỗi: `{error:{code:string,message:string,details:object|null},request_id:string}`.
Không raw exception/key/path máy/stack trace. 409 conflict, 410 nguồn không khả dụng,
413 quá kích thước, 415 loại tệp sai, 422 validation. Các lỗi dịch vụ chat:
- 503 GEMINI_QUOTA_EXCEEDED: 429 từ SDK; không tự retry.
- 503 GEMINI_CONFIGURATION_ERROR: thiếu/sai key hoặc model không được cấu hình/sử dụng.
- 503 GEMINI_SERVICE_UNAVAILABLE: dịch vụ/mạng khác.
- 504 GEMINI_TIMEOUT: lời gọi Gemini hết timeout trong ngân sách còn lại.
- 504 REQUEST_DEADLINE_EXCEEDED: tổng ngân sách chat60s hết ở các bước khác/trước gọi.
Không model fallback, không auto retry POST FE/SDK; không lưu cặp message trên các lỗi này.
Một outer timeout60s cho luồng chat, SDK timeout<=remaining lúc gọi; chỉ request handler
còn hiệu lực được lưu. CPU qua to_thread chỉ trả dữ liệu, không callback/persist, không cố
hủy CPU. Kiểm expires_at trước trả Reply (kể cả Guest) và trước transaction account;
hết timeout/kết quả Gemini sau hạn không gửi200 hoặc lưu; không cơ chế late-result riêng.

Context = {year:int|null,campus:string|null,major_code:string|null,method:string|null}.
Context chỉ để hỏi đáp tuyển sinh, không là đầu vào quiz. Request có thể bỏ context
hoặc bỏ trường chưa biết; backend chuẩn hóa đủ4 khóa trong Reply.

Citation = {document_id:UUID,chunk_id:UUID,content_hash:string,title:string,url:string,
source_name:string,year:int|null,campus:string|null,page:int|null,section:string|null,
available:bool}. url HTTPS nguồn hoặc `urn:upload:<origin_id>` có public source endpoint tra cứu.

Reply = {status,text:string,citations:Citation[],context:Context,missing_fields:string[],
request_id:string}. status thuộc answered/social/out_of_scope/needs_clarification/
insufficient_evidence/data_missing/conflicting_sources. Đây là 200 nghiệp vụ.
answered luôn có citations không rỗng. social/out_of_scope/needs_clarification/
data_missing/insufficient_evidence có citations=[]; conflicting_sources có citations
các nguồn mâu thuẫn, text báo mâu thuẫn không khẳng định một số là đúng.
text plain text; số quan trọng chỉ template trích nguyên văn native đúng context;
mô tả có thể diễn giải grounded theo internal schema bên dưới. Năm/mã ngành/tên chương trình
có số đúng vai trò và nguồn đã trích vẫn hợp lệ; không chặn chỉ do chữ số hoặc từ khóa.

## Auth và health

| Method/path | Quyền | Request | Response |
| --- | --- | --- | --- |
| GET /health | Public | Không | 200 {status,embedding_ready:bool,ocr_available:bool,gemini_configured:bool}; không giá trị secret |
| POST /auth/register | Public | {email,password} | 201 {id,email,role:USER}; duplicate409 |
| POST /auth/login | Public | {email,password} | 200 {access_token,token_type:bearer,expires_in:1800,user:{id,email,role}} |
| GET /auth/me | User | Bearer | 200 {id,email,role} |
| POST /auth/logout | User | Bearer | 204 sau revoke sid |

Email trim/lowercase hợp lệ/duy nhất, password8..128; sai login INVALID_CREDENTIALS chung.
Không chọn role công khai; tạo ADMIN qua CLI, không refresh token.

## Chat, history và nguồn công khai

| Method/path | Quyền | Request | Response |
| --- | --- | --- | --- |
| POST /chat/guest | Public | {message,context?,turns?:[{sender:user/assistant,text}]} | 200 Reply, không DB/log nội dung |
| POST /conversations | User | {title?:string} | 201 {id,title,created_at,updated_at} |
| GET /conversations | User | pagination | List chỉ của người gọi |
| GET /conversations/{id} | Owner | Không | 200 conversation |
| GET /conversations/{id}/messages | Owner | pagination | List {id,seq,sender,content,reply_status,citations,created_at}, seq tăng |
| POST /conversations/{id}/messages | Owner | {message,context?} | 200 {user_message_id,assistant_message_id,reply:Reply} |
| PATCH /conversations/{id} | Owner | {title} | 200 conversation |
| DELETE /conversations/{id} | Owner | Không | 204, cascade messages |
| GET /documents/{id}/source | Public | page?:int>=1 | 200 {id,title,origins:[{url,source_name}],excerpts:[{chunk_id,page,section,text}],available:true}; 410 nếu còn document nhưng disabled/không usable;404 nếu xóa/không tồn tại |

message trim1..4000; E5 query vượt512 token có prefix/special trả422 QUERY_TOO_LONG.
Guest turns tối đa10 tin, mỗi tin<=4000, tổng<=16000; chỉ ngữ cảnh không là evidence,
không nhận conversation_id. History server cũng giới hạn10 tin/16000 ký tự cho context.
Title mặc định “Hội thoại mới”, trim1..100. Song song cùng hội thoại409 CONVERSATION_BUSY.
Kiểm owner trước đọc dữ liệu; kiểm session/nguồn trước commit cuối.
Chỉ commit user+assistant cùng transaction khi có Reply200; HTTP lỗi không tin mồ côi.
Nếu client mất response không rõ đã commit, tải messages trước gửi lại.
Snapshot citation cũ có available=false nếu hash/chunk không còn hiện hành hoặc nguồn không còn được phép dùng.
Public source chỉ excerpts được phép dùng, không file path, không provenance_note riêng.

## Quiz và catalogue ngành

| Method/path | Quyền | Request | Response |
| --- | --- | --- | --- |
| GET /catalog/majors | Public | campus?:string,pagination | List Major |
| GET /quiz | Public | Không | QuizResponse theo hai schema đóng dưới đây |
| POST /recommendations | Public | {rubric_version:string,answers:[{question_id:UUID,value:int}]} | 200 RecommendationResponse |

Major = {id,code,name,campus,description,career_groups:[{code,label,reason}],
sources:[{document_id,title,url,source_name,page:int|null}]}.
Chỉ trả ngành source current hash/ready/allowed, không trả catalogue cũ khi nguồn đã đổi.

QuizResponse luôn có đúng6 khóa cấp ngoài:
- ready: {status:"ready",rubric_version:string,questions:Question[10],
  scoring_description:string,missing_fields:[],message:null}.
- data_missing: {status:"data_missing",rubric_version:null,questions:[],
  scoring_description:null,missing_fields:string[] (ít nhất1),message:string (không rỗng)}.

Question = {id,position:int1..10,text:string,options:[{value:int,label:string}][5],
scoring:[{major_id:UUID,direction:positive|negative|none,reason:string}]}.
Options cố định 1=Rất không đồng ý,2=Không đồng ý,3=Trung lập,4=Đồng ý,5=Rất đồng ý.
Ready cần đúng10 câu, >=3 ngành usable; scoring có đúng một entry cho mỗi ngành/câu,
không trùng major_id; mỗi ngành có N>=1 direction khác none, mỗi câu ít nhất một ngành
khác none. Direction không thuộc enum/thiếu mapping là lỗi rubric, toàn bộ data_missing,
không tự mặc định none hoặc trả bộ một phần. scoring/scoring_description công khai quy tắc.

answers cần đúng10 question_id duy nhất của rubric, value integer1..5 (không boolean).
Thiếu/trùng/sai422 INVALID_QUIZ_ANSWERS; rubric_version khác hiện hành409 RUBRIC_CHANGED.
Request chỉ nhận rubric_version/answers, extra field bất kỳ422.
Không persist answers/profile. Không gọi Gemini.

RecommendationResponse luôn có:
{status:ready|data_missing|no_match|insufficient_matches,rubric_version:string|null,
items:Recommendation[],missing_fields:string[],message:string|null,disclaimer:string}.
Recommendation = {major:Major,fit_score:number0..100,reasons:string[]}.
- ready: items3..5, rubric_version hiện hành, missing_fields=[],message=null.
- data_missing: items=[], rubric_version=null, missing_fields không rỗng,message không rỗng.
- no_match: mọi score0, items=[], rubric_version hiện hành, missing_fields=[],message không rỗng.
- insufficient_matches: chỉ1..2 ngành score>0, items=[], rubric_version hiện hành,
  missing_fields=[],message nói chưa đủ3 ngành phù hợp, không tự điền.
disclaimer bắt buộc “Kết quả chỉ mang tính tham khảo, không bảo đảm trúng tuyển.”

Nếu dữ liệu thiếu tại lúc POST: trả200 data_missing trước kiểm rubric stale; nếu dữ liệu
sẵn sàng nhưng version sai thì409. Input cấu trúc sai luôn422.
Contribution: positive=(value-1)/4, negative=(5-value)/4; none loại tổng và mẫu số.
fit=100*sum(contribution)/N, N là số câu khác none; sort score chưa round giảm dần rồi code/campus.
Hiển thị2 số thập phân; reasons tối đa2 câu contribution>=0,75 (tie position), kèm nguồn:
positive nêu đồng ý câu thuận (value>=4), negative nêu không đồng ý câu nghịch (value<=2).
Không dùng none tạo lý do, không đổi nghĩa câu nghịch; không đủ ngưỡng thì nói chưa có xu hướng nổi trội.
Rubric_version bao gồm directions/reasons; đổi chiều mapping làm version cũ nhận409.
Chỉ lấy tối đa5 score>0, không lọc theo học lực.

## Jobs và import

| Method/path | Quyền | Request | Response |
| --- | --- | --- | --- |
| GET /jobs | Public | major_id?,career_group?,status?:open/expired/unverified,pagination | 200 JobsResponse |
| POST /admin/jobs/import | Admin | multipart file,source_id? (nguồn xuất bản mặc định) | 202 RunAccepted; 422 cấu trúc sai,409 run busy |

Job = {id,source_id,identity_key,document_id,origin_id,title,employer,description,source_url,source_name,
collected_at,updated_at,posted_at:timestamp|null,deadline_at:timestamp|null,
status:open|expired|unverified,career_group:string|null,classification_reason:string|null}.
source_url/name/collected_at JOIN đúng origin của từng tin, không lấy từ file container.
Mỗi job có source_id/identity_key: ext:<external_id> tin cậy, thiếu thì url:<canonical_url>.
UNIQUE(source_id,identity_key), không dedup/count bằng document_id. Hai URL khác, cùng text
và thiếu external_id là hai job. Đổi URL cùng external_id tin cậy upsert một job.
Nếu row thiếu ID nhưng URL khớp job có ID thì giữ ID/ext-key hiện hữu; nâng url-key sang
ext-key khi hợp lệ, không tạo bản sao. Cùng source_id+canonical_url có hai external_id
không rỗng khác nhau →outcome error/reason identity_conflict, trước ghi job/origin;
kiểm DB và dòng đã nhận trong file. Không đổi xuất xứ, collected_at hoặc dữ liệu job khác.

JobsResponse = {status:ready|data_missing,items:Job[],total,page,page_size,
observed_open_count:int|null,as_of:timestamp,sources:[{id,name}],scope_note:string}.
ready khi có kho hợp lệ, total/count0 là hợp lệ nếu filter không khớp;
data_missing khi chưa có nguồn/tin usable: items=[],total=0,observed_open_count=null.
Count dùng cùng filter ngành/nhóm nghề, không phụ thuộc page; COUNT job.id hợp lệ/open theo identity,
không đếm expired/unverified. Nếu filter status khác open, count vẫn là số open của
cùng ngành/nhóm nghề; scope_note nói rõ điều này. Không là số vị trí/toàn thị trường.
major_id không tồn tại404; ngành mất source usable200 data_missing; career_group lạ422.
Bộ mã nhóm nghề công bố qua catalogue; null không khớp major filter.

Import UTF-8 CSV header hoặc JSON array, tối đa20 MiB/5000 records, lỗi định dạng422 toàn tệp.
Mỗi dòng: title/employer/description/source_url/collected_at bắt buộc; optional external_id,source_id,
posted_at/deadline_at/observed_status(open/closed/unknown),career_group,classification_reason.
Mỗi row có source_id nguồn website xuất bản thực hoặc dùng default source_id từ multipart.
Nguồn khác TopCV được phép nếu registry đã allowed/checked_at/reuse_basis rõ; không
coi file CSV là website xuất bản. Thiếu cả row/default source_id → error dòng.
Mọi source_url phải
trong allowlist source. Timestamp tương lai collected_at/posted_at bị422 ở cấp dòng.
Không URL/nguồn/quyền hợp lệ thì error dòng, không dùng URN thay nguồn tin.
Không tự điền observed_status=open; thiếu là unknown. Chỉ ngày deadline → cuối ngày VN.
File sai cấu trúc toàn tệp không tạo run; lỗi dữ liệu dòng ghi vào run, dòng đúng vẫn nhập.
Response202 không có nghĩa mọi dòng thành công; đọc run/items để nghiệm thu.
Quy tắc per-row: identity mới →new (inserted), cùng identity/payload nghiệp vụ không đổi
so DB →skipped, nghiệp vụ/observed_status đổi →updated. Payload/normalize theo data-model;
collected_at/retrieved_at/last_seen_at đơn thuần không làm updated, không thêm cột last_seen_at.
Trong file chỉ dòng hợp lệ đầu tiên được áp dụng; dòng sau cùng identity/payload skipped,
payload khác error/reason conflict, không sửa dòng đầu. Dòng không hợp lệ không giữ chỗ identity.
identity_conflict ưu tiên trước conflict payload. Đây là lỗi dòng, không đổi HTTP202 thành409
hoặc hủy toàn file. RunItem.reason dùng literal conflict/identity_conflict (không thêm field).
counts new/updated/skipped/error theo job rows, không document; log mọi record kể cả trùng.
Record là snapshot: optional thiếu null/observed_status unknown; giữ external_id hiện hữu
nếu row thiếu ID đã resolve cùng job. Không re-embed khi chỉ đổi status/observation.


## Admin documents, sources và runs

DocumentMetadata = {id,title,provenance_note:string|null,year:int|null,campus:string|null,
major_code:string|null,method:string|null,state,enabled:bool,content_hash:string|null,
index_profile:object|null,quality_reason:string|null,last_update_error:string|null,
created_at,updated_at,last_checked_at:timestamp|null,origins:Origin[]}.
Origin = {id:UUID,source_id,origin_kind:web|upload,canonical_url,original_url,provenance_note:string|null,
publisher:string|null,published_at:timestamp|null,retrieved_at,active:bool}.
Detail thêm content_text:string|null. List không trả content_text.
State: pending/ready/quarantined/error. Update lỗi giữ ready bản tốt,
last_update_error giải thích bản thử; log item có lý do cách ly/lỗi, không mất bản tốt.

| Method/path | Quyền | Request | Response |
| --- | --- | --- | --- |
| POST /admin/documents/upload | Admin | multipart file,title,source_id,source_url?,provenance_note?,year?,campus?,major_code?,method?,publisher?,published_at? | 202 {run_id,origin_id:UUID,document_id:UUID\|null}; 409 busy |
| GET /admin/documents | Admin | q?:title/URL,state?,enabled?:bool,pagination | List DocumentMetadata |
| GET /admin/documents/{id} | Admin | Không | 200 DocumentMetadata + content_text |
| GET /admin/documents/{id}/original | Admin | Không | 200 file an toàn;404 nếu không còn |
| POST /admin/documents/{id}/disable | Admin | {reason} | 200 metadata enabled=false; giữ state xử lý |
| DELETE /admin/documents/{id} | Admin | Không | 204 xóa vật lý doc/chunks/origins/liên kết; UI confirm có thể crawl lại |
| POST /admin/documents/{id}/enable | Admin | {reason} | 200 metadata enabled=true; chỉ ready có chunks hợp lệ được RAG |
| GET /admin/sources | Admin | pagination | List Source |
| POST /admin/sources | Admin | SourceInput | 201 Source |
| PATCH /admin/sources/{id} | Admin | các trường SourceInput đổi | 200 Source;422 nếu bật thiếu quyền |
| POST /admin/runs | Admin | {source_id?:UUID} | 202 RunAccepted;409 RUN_IN_PROGRESS |
| GET /admin/runs | Admin | pagination | List Run |
| GET /admin/runs/{id} | Admin | Không | 200 Run |
| GET /admin/runs/{id}/items | Admin | pagination | List RunItem |
| POST /admin/runs/{id}/stop | Admin | Không | 200 Run; idempotent nếu đã kết thúc |

SourceInput = {name,kind:utc|topcv|career|upload|catalog,base_url:string|null,
allowed_paths:string[],enabled:bool,permission_status:unknown|allowed|denied,
robots_url:string|null,terms_url:string|null,reuse_basis:string|null,
checked_at:timestamp|null,min_interval_seconds:number>=2}.
Source thêm id/retry_not_before/last_success_at nullable.
Allowed yêu cầu reuse_basis và checked_at; nguồn web cần robots/terms và domain/path hợp lệ;
unknown/denied không được enabled hoặc fetch/import. Tài liệu cũ từ nguồn mất quyền
cũng bị loại khỏi retrieval/jobs/catalogue. URL Admin không cho truy cập mạng nội bộ.

Upload PDF/TXT UTF-8/PNG/JPG/JPEG <=20 MiB; validate MIME/magic. source_url HTTPS hợp lệ
hoặc provenance_note bắt buộc. Nếu note có mặt, NFC/trim1..2000; chuỗi trắng422 kể cả có URL.
Mỗi upload được tiếp nhận có origin UUID mới/origin_kind=upload; client không gửi origin_id.
Không source_url: original/canonical_url là urn:upload:<origin_id>, note vẫn phải lưu.
Có source_url: lưu URL nguồn, cùng URL vẫn cho nhiều origins upload/note hợp lệ,
không409 do khác provenance. UUID/URN không lấy từ raw_hash/content_hash.
Web/career import origin_kind=web có UNIQUE(source_id,canonical_url) riêng; upload không nằm
trong unique URL. Cùng content/context/profile dùng chung document/chunks, không re-embed;
khác context giữ document riêng. Mỗi lần cung cấp nguồn là một origin, không nhân bản document.
Receipt document_id có thể null khi chưa xử lý; lấy document_id kết quả từ run/items.
origin_id giữ nguyên khi dedup sang document có sẵn; metadata trả mọi origin và note
đã lưu sau restart, document.provenance_note không ghi đè note đầu tiên.
409 RUN_IN_PROGRESS khi slot bận. Không conflict từ cùng URL/bytes.
Reason Admin trim1..500. Disable giữ record và chunks, enabled=false bền qua crawl:
nội dung đổi vẫn có thể update nhưng không tự bật. Enable không tự tạo chunks còn thiếu.
Delete xóa vật lý theo data-model; không endpoint enable cho ID đã xóa (404).
Nguồn còn tài liệu thì lượt crawl sau được nhập lại. UI/README phải thông báo rõ.

RunAccepted = {run_id,state:"running"}, Location /api/v1/admin/runs/{run_id}.
Run = {id,source_id:UUID|null,trigger,state,created_at,triggered_by:UUID|null,started_at:timestamp|null,ended_at:timestamp|null,
stop_requested_at:timestamp|null,stop_requested_by:UUID|null,
counts:{new,updated,skipped,error},source_outcomes:[{source_id,status,message:string|null}]}.
trigger scheduled/manual/upload/job_import; state running/stop_requested/cancelled/
succeeded/partial/failed/interrupted/skipped_busy. Counters theo data-model; không tạo item giả cho lỗi nguồn.
RunItem = {item_index:int>=1,source_id:UUID|null,canonical_url:string|null,
document_id:UUID|null,outcome:new|updated|skipped|error,reason:string|null,started_at,ended_at}.
Mỗi record import có item_index dù URL sai/trùng, UNIQUE(run_id,item_index), không khóa log bằng URL.
Dừng chỉ active; terminal (kể cả skipped_busy) trả trạng thái cũ idempotent, không dừng run mới.
Rerun qua POST /admin/runs tạo ID mới, không endpoint resume. Một process/worker,
scheduler/manual/upload/import dùng cùng slot; không multi-instance support.

## Internal Gemini schema và acceptance

Schema đóng: {answer:string không rỗng,evidence_ids:string[] không rỗng/unique}.
evidence_id do backend gán theo chunk được chọn, chỉ tồn tại trong request; model không
được tạo URL/metadata. Backend validate schema, ID thuộc context, nguồn/hash/chunk còn
usable trước finalize. Output lỗi/citation không hợp lệ → Reply insufficient_evidence,
không gửi raw output. Không có parser semantic claims hoặc nhiều tầng duyệt nội dung.
Prompt chỉ cho diễn giải mô tả theo context, không thêm số liệu/suy đoán/cam kết.
Guard ưu tiên nhận định định lượng (giá trị/đơn vị gắn điểm chuẩn, học phí, chỉ tiêu,
ngày/hạn hoặc số tin/vị trí): không lấy từ Gemini, chỉ template native/COUNT backend.
Còn năm, mã ngành, cơ sở và tên chương trình có số được phép khi đúng vai trò và khớp
literal metadata/dòng tên trong cited chunks. Không whitelist một số vô điều kiện chỉ vì
nó có trong context: mã7480201 không cho phép “7480201 điểm”. Từ khóa không có số liệu
như “điểm mạnh” hoặc “cách tra học phí” không tự gây từ chối. Số/định danh không khớp
nguồn hoặc vai trò trả insufficient_evidence. Chi tiết rule/allowlist ở architecture,
không thêm field model output hoặc semantic claim parser.

Contract tests phải kiểm đủ khóa/nullable hai QuizResponse; mọi RecommendationResponse;
input ngoài schema bị422; upload cùng bytes/URL khác provenance/context không unique sai,
origin_kind/UUID và note persist/restart; scoring thuận/nghịch/none đúng schema;
mô tả có năm/mã ngành/tên chương trình hợp lệ không bị chặn; job origin JOIN; mỗi item import;
quota503/timeout504/key503 không retry/lộ key hoặc lưu answered; source unavailable410.
Integration chỉ chạy khi dependency thật sẵn sàng theo tasks/testing.

## Crawl ngay và lịch00:00 độc lập

POST /admin/runs chính là nút “Crawl ngay”: ADMIN,202 RunAccepted/Location, chạy nền,
không chờ hoàn tất; Guest401/USER403, busy409 không tạo run. Manual không đổi cron.
Cron00:00 Asia/Ho_Chi_Minh khi bận bỏ lượt và ghi terminal skipped_busy.
GET /admin/runs và detail trả trigger=scheduled/state=skipped_busy, started_at=null,
created_at=ended_at lúc bỏ lượt, counts tất cả0/source_outcomes=[], items=[]/total0.
UI “Bỏ qua do đang bận”; không coi là failed hoặc item unchanged/skipped. Không tăng
last_success_at, không chạy lại khi slot rảnh/restart. Manual busy409 RUN_IN_PROGRESS
không tạo log run. Ngày sau vẫn00:00; backend tắt không chạy bù.
Pipeline extraction/hash/chunk/localembedding/retrieval dùng chung manual/scheduled.

Disabled cập nhật mà hash mới trùng doc enabled cùng context: giữ bản disabled cũ,
run item skipped/reason DISABLED_DUPLICATE, không auto enable hoặc nhân document sai unique.

Nguồn kind=career dùng cho publisher nghề nghiệp khác nhập CSV/JSON; import-only.
Scheduler/manual không tự fetch career/upload/catalog; ghi source outcome skipped/import-only.
