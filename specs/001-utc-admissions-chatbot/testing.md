# Chiến lược kiểm thử

Theo [spec](spec.md), [REST](contracts/rest-api.md) và checkpoint [tasks](tasks.md).
Tài liệu này quy định cách nghiệm thu, chưa ghi nhận test ứng dụng đã chạy.

## Ba mức kiểm thử

- Unit: một thuật toán/service đã xây; fake requests/OCR/Gemini/clock/encoder.
- Contract: schema/status/nullable/auth dependency, được dùng stub service khi dependency
  chưa có. Ghi rõ stub; pass contract không nghĩa ingestion/RAG/quiz đã tích hợp xong.
- Integration: SQLite file tạm và service thật liên quan; chỉ chạy khi tất cả dependency
  task đã hoàn thành. Gemini/network/OCR binary có thể stub để offline xác định được;
  E5 CPU smoke và Tesseract thật là smoke riêng khi đã cài, không giả là đã chạy.

Không thêm framework E2E; UI kiểm tay có checklist, backend Pytest/httpx.
Không mặc định truy cập UTC/TopCV/Gemini thật khi chạy suite.
Tests/fixture và DB test nằm ngoài data demo, có nhãn “GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC”.

## Bộ kiểm tra và pass/fail

| Bộ | Đầu vào/điều kiện | Kết quả bắt buộc |
| --- | --- | --- |
| Q01 Setup/database | env sai/đúng, init hai lần, FK/rollback | Lỗi cấu hình không lộ secret; DB không mất dữ liệu; lockfiles resolve và build thành công |
| Q02 Auth/RBAC | Guest/2USER/ADMIN; role giả, token sai/expiry/revoked/inactive | 401/403/404 đúng; owner không bị vượt kể cả ADMIN; password Argon2, logout hiệu lực |
| Q03 Metadata/quyền | URL/note, NFC/trim, note null/rỗng/2000/2001, cùng bytes/URL khác note/context, source unknown | Upload UUID riêng, không UNIQUE sai; cùng context dùng chung doc/encode0, khác context tách doc; mọi note đọc lại sau restart; public không note riêng |
| Q04 Tài liệu | 20MiB boundary/type/path traversal, disable/delete/allow | Tệp an toàn; disabled qua crawl không bật, enable thủ công; delete xóa thật và crawl lại được; không lộ path |
| Q05 Crawl/extraction | HTML lỗi/PDF native/scan/hỏng/200+ trang, ảnh mờ, thiếu OCR | Native tự index, OCR fallback đúng; gate90/30, timeout60s/trang/5phút item; cách ly chất lượng thấp |
| Q06 Quyền web | robots/terms/reuse unknown,403/CAPTCHA/429/redirect private | Không bypass, Retry-After/backoff đúng, nguồn khác vẫn chạy, bản tốt không bị mất |
| Q07 Incremental | mới/đổi/unchanged/lỗi; raw khác text giống; profile khác; nhiều origins | Counts đúng; spy encode unchanged=0; staging rollback giữ text/hash/vector cũ; origin đổi không sửa nguồn khác |
| Q08 Embedding/retrieval | prefixes/querybudget/BLOB malformed,2năm/2cơsở, source disabled | CPU384/L2/<f4/1536, chunk320/48/<=512, cosine top5 đúng; không trả nguồn sai context/profile |
| Q09 Scope | social/ngoài phạm vi/UTC/nghề liên quan/hỗn hợp/mơ hồ | Status đúng; không gọi Gemini khi xã giao/từ chối/thiếu/mơ hồ/conflict; không coi mọi câu nghề là UTC |
| Q10 Citations/grounding | JSON sai/ID giả/trùng/ngoài retrieval, source vô hiệu hóa khi chờ | Không trả raw model output; insufficient_evidence, không answered; citations dựng từ DB, không từ URL model |
| Q11 Native số | Điểm chuẩn/học phí/chỉ tiêu/ngày đúng-sai năm/cơ sở/phương thức; OCR số; thiếu header | Chỉ trích native chính xác có context/citation; OCR/mơ hồ thiếu căn cứ; không tính thêm hoặc cam kết trúng tuyển |
| Q12 Hallucination/guard | Năm/mã ngành/tên chương trình có số đúng nguồn; code/năm dùng giả làm mức điểm/học phí; số/đơn vị bịa | Mô tả định danh đúng vai trò được giữ; định lượng không qua Gemini dù giá trị trùng ID; từ khóa không có số không tự chặn; golden review kiểm nghĩa |
| Q13 Gemini quota/key | Stub429/key401/403/service5xx | SDK tổng attempt1, quota503/key503/service503 đúng; không fallback/retry, không key trong response/log |
| Q14 Timeout/message | Một outer timeout, SDK timeout trước outer, CPU stub trả muộn, account service failure | SDK504 khác outer504; không reset; handler không nhận/lưu kết quả muộn, CPU không callback ghi; không answered/cặp mồ côi; session hết hạn không commit |
| Q15 History | create/list/send/rename0/1/100/101/delete, owner khác, source thay | Đúng thứ tự; 409 cùng hội thoại; cascade; snapshot unavailable; Guest không DB/log |
| Q16 Job import | JSON/CSV sai, identity mới/cũ, payload đổi/không đổi, file trùng/mâu thuẫn, observation-only | Sai cấu trúc422; log từng dòng; new/updated/skipped/error đúng; first-valid-wins; conflict/identity_conflict không ghi đè nguồn/job khác |
| Q17 Job nguồn/count | Hai nguồn cùng nội dung, origin khác ngày, open/expired/unverified | source_url/name/collected_at chính xác; count theo job identity, haiURL cùngtext thiếuID vẫn2tin; date-only cuối ngày VN; thiếu khác0 |
| Q18 Quiz contract | Ready10 câu; thiếu scoring/direction không hợp lệ/N=0/source; direction đổi version; rubric stale | Đủ6 khóa và scoring positive/negative/none; missing questions=[]/version=null/description=null; stale409; answer sai422 |
| Q19 Scoring | Sáu bộ đáp án tính trước; thuận/nghịch/none, biên1/3/5, tie/zero/1–2 ngành dương | Formula/denominator đúng, lý do đúng chiều, none không điểm/lý do; top3–5/status đúng; không Gemini/điểm học tập, extra fields422 |
| Q20 Career filter | Mapping có source, group null, catalogue source đổi/vô hiệu hóa | Chỉ nhóm nghề liên quan; không tự gán, không dùng mapping cũ; integration sau cả jobs/catalogue/scoring API sẵn sàng |
| Q21 Scheduler | Fake clock00:00 VN,manual+lịch cùng slot,stop giữa item, restart app | Một run/process; manual409 overlap, scheduled busy skipped_busy, không tự chạy lại; current item xong rồi stop; item chưa xét không đếm; rerun mới skip unchanged; dở interrupted |
| Q22 UI/demo | Tất cả trang/role,360/768/1366,empty/loading/error/missing | Điều hướng/state rõ, không overflow ngang; plain text; source/history/stop dùng được; no token/key frontend |

## Acceptance bổ sung H1 — upload identity

- Upload cùng bytes/context/profile lần1 → một doc ready; lần2 đổi tên/note hợp lệ →
  cùng document/chunks, encode spy lần2=0, hai origin UUID và hai note độc lập.
  Lặp cùng note cũng là lần cung cấp nguồn mới, không tạo document trùng.
- Cùng bytes nhưng year/campus khác → hai documents/context, origins riêng; không lỗi
  UNIQUE hoặc gộp ngữ cảnh. Không bắt buộc encode0 cho context mới.
- Hai upload có cùng source_id và source_url, note khác → hai upload origins, không409;
  thêm origin_kind=web cùng URL vẫn hợp lệ. Web URL trùng vẫn upsert/skip, partial unique
  ngăn nhân bản web. Cùng raw_hash không bao giờ là lý do lỗi unique origin.
- Không source_url: URN chứa origin UUID, không raw_hash; metadata sau restart giữ mọi
  note/UUID và liên kết doc. Disabled không tự bật khi upload/crawl reuse; xóa thật rồi
  upload/crawl lại được tạo doc mới, snapshot cũ unavailable.

## Acceptance bổ sung H2 — numeric guard

Fixture chỉ để test, không phải thông tin UTC chính thức. Retrieved metadata có năm 2026,
mã ngành 7480201 và dòng tên “Chương trình DEMO2+2”; evidence ID/citation hợp lệ:
- “Theo tài liệu tuyển sinh năm 2026, mã ngành 7480201 có mô tả…” và tên chương trình trên
  được giữ nếu mô tả grounded; cùng câu đổi2027/mã không có nguồn bị từ chối.
- “Điểm mạnh của chương trình…” hoặc “Có thể tra học phí ở tài liệu này” không bị chặn
  chỉ vì keyword, vẫn phải grounding/citation như mọi mô tả.
- “Điểm chuẩn là2026 điểm” hoặc “học phí7480201 đồng” bị loại dù số bằng năm/mã đã có.
  Thêm25điểm/30triệu/100chỉtiêu/ngày15/08/2026/500tin vào prose Gemini cũng bị loại.
- Hỏi số liệu thực sự: đi template native đúng nguồn/context hoặc COUNT jobs; không gọi
  Gemini tự sinh số. Citation hợp lệ không thay kiểm chứng giá trị/ngữ cảnh.

## Expected cases M1 — scoring thuận/nghịch

Catalogue GIẢ LẬP gồm A/B/C, code sắp A<B<C, nguồn test hợp lệ; đủ10 câu bắt buộc.
Q1: A positive, B negative, C positive. Q2: A negative, B positive, C positive.
Q3–Q10: A/B none, C positive. Mỗi mapping có reason đúng chiều; N(A)=2,N(B)=2,N(C)=10.
Đây là expected số học để test, không mapping hay thông tin ngành UTC thật.

| Case | Answers | A | B | C | Kết quả API |
| --- | --- | --- | --- | --- | --- |
| S1 | Q1=5,Q2=1,còn lại3 | 100 | 0 | 50 | insufficient_matches, items=[] (chỉ2 ngành dương) |
| S2 | Q1=1,Q2=5,còn lại3 | 0 | 100 | 50 | insufficient_matches, items=[] |
| S3 | Tất cả3 | 50 | 50 | 50 | ready, thứ tự A/B/C |
| S4 | Q1=4,Q2=2,còn lại3 | 75 | 25 | 50 | ready, A/C/B |
| S5 | Như S4 nhưng Q3=5 | 75 | 25 | 55 | ready, A/C/B; none không đổi A/B |
| S6 | Tất cả5 | 50 | 50 | 100 | ready, C/A/B; không coi câu nghịch là thuận |

Test contribution riêng: positive tại1/3/5 =0/0,5/1; negative =1/0,5/0.
Lý do S1(A) phải nói không đồng ý Q2 nghịch, không khẳng định đồng ý Q2.
Lý do không dùng Q3–10 cho A/B. Tạo fixture zero riêng: mọi ngành Q1 positive,Q2 negative,
Q3–10 positive; answers Q1=1,Q2=5,còn lại1 → mọi score0/no_match.
N=0/thiếu mapping/direction lạ → data_missing, không chia0 hoặc mặc định none.
Đổi direction giữ câu/answers cũ → rubric_version đổi, POST version cũ409.
Giữ test missing/duplicate answers, value ngoài1–5, source unavailable và strict request.

## Grounding: kiểm tự động và kiểm người

Backend tự động kiểm schema/ID/source eligibility/context, không semantic parser từng claim.
Bộ30 câu có expected status và source, tối thiểu5 câu số liệu và5 câu thiếu/ngoài phạm vi.
Chạy unit với stub để bảo đảm số bịa/citation không hợp lệ bị loại, và kiểm tay output
mô tả dựa trên chính đoạn đã retrieve. Người kiểm đánh dấu từng dữ kiện thêm/đổi nghĩa/
đảo phủ định/thiếu nguồn. Nếu output mẫu không đạt thì sửa prompt/gate hoặc trả thiếu
căn cứ ở trường hợp đó; không tuyên bố có bảo đảm tuyệt đối cho mọi diễn giải.
Không viết một assertion chỉ kiểm evidence_id rồi coi là đã chống hallucination.

## Checkpoint không đòi dependency tương lai

- A: Setup/auth unit + API + security.
- B: Documents API dùng indexer stub; crawl/OCR unit riêng; chưa đòi retrieval hay UI.
- C: Chunks/E5/publish/retrieval sẵn sàng mới chạy ingestion → source API integration.
- D: RAG/history sẵn sàng mới kiểm message persistence, owner và quota/deadline đầy đủ.
- E1: Jobs schema/status/import source không cần quiz; filter major được stub ở contract.
- E2: Catalogue/quiz/mapping xong mới chạy jobs?major_id integration và quiz hành trình.
- F: Coordinator+ingestion+scheduler xong mới kiểm stop/rerun/00:00.
- G/H: API hoàn chỉnh rồi build và nghiệm thu UI/toàn bộ demo.

Giữ kiểm tra revoke/ownership/key/prompt injection/SSRF/path traversal và nguồn bị disable.
Một integration test đơn giản cho disable trong lúc Gemini stub chờ là đủ; không yêu cầu
ma trận race nhiều process, OS lock/crash subprocess hoặc kiểm thử phân tán.

## Hiệu năng và ghi bằng chứng

Một asyncio.timeout_at(expires_at) tổng60s cho luồng chat, mốc expires_at không reset.
Kiểm remaining khi gọi SDK và ngay trước transaction lưu, không timer/cancel protocol mỗi bước.
Giả lập SDK timeout trước outer → GEMINI_TIMEOUT504; outer hết khi chờ CPU/Gemini →
REQUEST_DEADLINE_EXCEEDED504. Stub CPU chỉ trả dữ liệu, không có quyền/callback ghi DB:
sau response timeout cho stub kết thúc rồi kiểm DB không thêm tin, không answered muộn.
Guest cũng phải nhận504, không nhận Reply200 từ kết quả trả sau hạn; kiểm final expiry
áp dụng trước trả response và sau lấy khóa finalize, không chỉ trước lưu account.
Gemini lỗi quota/key giữ503 tương ứng, một attempt, không cặp tin mồ côi/lộ secret.
Dùng timeout rút ngắn trong integration test, cho dung sai điều phối hợp lý; không yêu cầu
hủy CPU, kill process hoặc test framework concurrency mới. Check deadline trước commit;
không khẳng định commit đồng bộ ngắn có thể bị ngắt đúng60s. Ghi overhead thực khi đo.
E5 warm CPU đo10 câu, mục tiêu9/10<=30s trên máy demo; ghi CPU/RAM/model revision/
profile/threshold/timing thật. Không biến mục tiêu thành SLA production.

`docs/demo/acceptance-results.md` ghi lệnh/ngày/máy/fixture/expected/actual/pass-fail,
checkpoint, unit/contract-stub/integration/smoke-live; các FR/SC liên quan.
Chưa chạy ghi “chưa chạy”, nguồn thiếu ghi “thiếu dữ liệu/quyền”, không tự điền thành công.

## Nghiệm thu tài liệu, cron chờ và business identity

- Disable D rồi crawl unchanged/changed: enabled=false, retrieval loại D, không tự bật.
  Admin enable D ready → retrieval dùng được. Upload hợp lệ tự index, lỗi không được dùng.
- Delete D: không còn doc/chunks/origins/jobs/majors liên quan; run FK null, chat snapshot
  available=false; GET deleted404. Crawl lại URL còn tồn tại tạo doc mới; UI xác nhận rõ hành vi.
- Manual13/11 10:00 →202 ngay/worker nền, ADMIN đúng quyền; cron14/11 00:00 vẫn kích hoạt.
  Busy manual409 RUN_IN_PROGRESS không thêm run. Cron busy ghi terminal skipped_busy,
  startnull/end=created/counts0/items0/source_outcomes=[], không tăng last_success_at.
  Nhả slot không tạo ingestion; cron ngày sau00:00 nếu rảnh chạy bình thường.
- Stop current sau item, giữ commit; không start lượt mới tự động. Restart run dở interrupted,
  không phục hồi lượt đã bỏ hoặc tạo bù ngày backend tắt; manual chạy lại ID mới. Test fake clock/worker; không cần queue service.
- Hai URL khác cùng source/text, external_id thiếu: hai job.id, có thể một document,
  observed_open_count=2 nếu đều open hợp lệ. Cùng source/external_id tin cậy đổiURL:
  một job/count1. CùngURL thiếuID nhưng đã cójob ID không nhân bản. Conflict nângID error dòng.
- File trộn nguồn TopCV được phép và nguồn khác được phép: row source_id chọn đúng publisher,
  URL/name/collected_at JOIN đúng, không source tên file. Unknown/denied hoặc file từ thu thập
  trái phép: error row, không dùng trong jobs/RAG; log từng dòng vẫn đầy đủ.

Disabled đổi hash trùng doc enabled: skip DISABLED_DUPLICATE, giữ bản disabled cũ/flagfalse,
không unique error hoặc tự chuyển origin sang doc enabled.

## Nghiệm thu bổ sung coordinator và demo

- Dùng fake item/Event giữ manual trong network/OCR/embedding ngoài mutex; callback cron
  vẫn ghi skipped_busy trước nhả Event. Assert active pipeline tối đa1, manual busy409,
  log terminal khác failed (không error/item, không cập nhật last_success). Sau nhả Event
  và sau restart không gọi ingestion cho lượt đã bỏ; ngày sau00:00 chạy khi rảnh.
  Lỗi/stop clear slot, giữ dữ liệu cũ; không acquire lặp Lock. Chỉ test một process,
  không thêm framework, sleep dài hoặc concurrency infrastructure.
- Cổng demo SC-010 yêu cầu tài liệu UTC có nguồn/quyền hợp lệ, >=3 ngành UTC usable,
  >=1 tin nghề nghiệp được phép với nguồn/thời điểm/trạng thái rõ, tách fixture giả lập.
  Trình diễn upload tài liệu hợp lệ→index→retrieval và RAG trả lời có citation từ tài liệu UTC;
  quiz trả ready, nghề nghiệp hiển thị dữ liệu thật. Ghi input/output/citation/run_id thực.
- Trình diễn đăng nhập/đăng xuất, gửi và mở lại history của chủ sở hữu, Admin upload/
  quản lý tài liệu hoặc Crawl ngay. Ghi actual trong acceptance-results, không stub/mocked
  output để thay bằng chứng thành công demo. Unit/contract vẫn được dùng fixture/stub.
- Nếu thiếu bất kỳ dữ liệu/hành trình chính: báo thiếu trung thực, demo NOT READY,
  T066–T068/T070 tương ứng chưa đạt; data_missing pass chỉ chứng minh nhánh thiếu hoạt động.

## Acceptance U1/U2 — job import theo identity

Dùng SQLite fixture có nhãn, không dữ liệu UTC chính thức:
- Identity mới: outcome=new (inserted); import file mới với cùng identity/payload: skipped,
  số job không đổi. Cùng identity đổi title/description/deadline/observed_status so DB:
  updated, đúng một job; đổi status không đổi text thì encode spy0.
- Chỉ collected_at/retrieved_at/last_seen_at (nếu có) khác: skipped, updated_at nghiệp vụ
  không đổi, không encode. Không cần tạo cột last_seen_at; expired do đồng hồ không là
  payload đổi. Normalize whitespace/NFC/URL/UTC trước so; optional thiếu theo snapshot contract.
- Trong file: cùng identity/payload giữ dòng hợp lệ đầu, dòng sau skipped; payload mâu thuẫn
  giữ dòng đầu, dòng sau error/reason=conflict. Dòng sau không ghi cả observation/provenance.
  Dòng đầu sai validation không chiếm identity; dòng hợp lệ sau đó được xử lý bình thường.
- Cùng source/canonical_url có hai external_id khác nhau (DB hoặc các dòng đã nhận trong file):
  dòng sau error/reason=identity_conflict, không đổi job/origin/collected_at/nội dung của job khác.
  Kiểm identity_conflict trước conflict payload/upsert origin. Cùng ID tin cậy đổi URL hợp lệ:
  một job updated; URL đích thuộc identity khác thì error, không đè xuất xứ.
- Thiếu ID nhưng URL đã có job ext-key: dùng job hiện hữu, giữ ID/key; bổ sung ID cho url-key
  hợp lệ: nâng key, không nhân bản, map file vẫn nhận ra dòng sau là cùng job.
- Mixed fixture: DB có J và K; row1=N mới, row2=N cùngpayload, row3=N payload khác,
  row4=J đổi trạng thái, row5=J giống row4, row6=cùngURL K nhưng khác external_id.
  Expected theo thứ tự: new,skipped,error(conflict),updated,skipped,error(identity_conflict);
  counts={new:1,updated:1,skipped:2,error:2},6 item_index, chỉ thêm1 job, K không thay đổi.
  HTTP vẫn202, lỗi dòng không rollback dòng hợp lệ. Count theo job identity, không document.

## Acceptance I1 — checkpoint database

- T013 chỉ kiểm data_sources/documents/document_origins, uniqueness và FK/cascade đã có
  tại checkpoint đó. Không yêu cầu chunks trước T025, jobs trước T038, majors trước T043.
- T062 mới kiểm đủ13bảng/schema/FK/unique; xóa document cascade chunks/origins/jobs/majors,
  run item document_id SET NULL, messages/citation snapshot không mất; quiz tham chiếu major
  bị xóa trả data_missing thay vì lỗi server. Chỉ chạy integration khi đủ dependency thật.
