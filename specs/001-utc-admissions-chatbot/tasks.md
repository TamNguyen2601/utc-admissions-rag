# Công việc triển khai — phạm vi local đơn giản

**Trạng thái**: T001–T034 đã triển khai đến checkpoint D1; chat Guest/scope/evidence/Gemini adapter/API được kiểm bằng SQLite tạm, encoder xác định được và Gemini stub/SDK MockTransport. E5 CPU smoke riêng đã PASS ở checkpoint C. Dừng sau T034; T035+ và lịch sử chat chưa triển khai, chưa nghiệm thu Gemini live hoặc demo.
**Bằng chứng**: [Kết quả thực tế T001–T034](../../docs/demo/acceptance-results.md).
**Số task**: 70. Không yêu cầu giữ số lượng của bản thiết kế trước.
Căn cứ: [spec](spec.md), [plan](plan.md), [architecture](architecture.md),
[data model](data-model.md), [REST](contracts/rest-api.md), [testing](testing.md).

Mỗi task có phạm vi, file, phụ thuộc và điều kiện đạt. File source dưới đây là file dự kiến,
không được tạo trong bước review tài liệu. Chỉ đánh [x] khi đã có bằng chứng nghiệm thu.
Không commit/push/merge tự động. Thứ tự IDs là thứ tự thực hiện mặc định; dependency là bắt buộc.
Contract dùng stub không được ghi là integration pass. Tests đi sau chức năng ở mỗi chặng.

## 1. Project setup

- [x] T001 [Setup/backend] [—] Khai báo stack backend theo plan, Python3.13 và uv; tạo lockfile, CPU dependencies; tzdata cho ZoneInfo Windows nếu cần.
  - File: `backend/pyproject.toml`, `backend/uv.lock`, `backend/.python-version`.
  - Phụ thuộc: không; coverage: FR-035.
  - Nghiệm thu: uv lock thành công, manifest không chứa framework ngoài plan; phiên bản lock được ghi, chưa đánh dấu smoke pass.

- [x] T002 [Setup/frontend] [US8] Khởi tạo React TypeScript Vite/Tailwind/Router/Axios, scripts dev/build; Node24.22.1/npm.
  - File: `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/main.tsx`.
  - Phụ thuộc: không; coverage: FR-033 FR-035.
  - Nghiệm thu: npm ci tái lập; chưa thêm Recharts/shadcn component không có nhu cầu.

- [x] T003 [Test/setup] [—] uv sync --locked, uv run import smoke các dependency Python3.13/CPU; npm ci/build; kiểm timezone/async SDK và timeout-retry API.
  - File: `backend/uv.lock`, `frontend/package-lock.json`, `docs/demo/acceptance-results.md`.
  - Phụ thuộc: T001, T002; coverage: FR-035 FR-036 SC-010.
  - Nghiệm thu: Ghi actual phiên bản, model revision tải được/CPU và tương thích; lỗi chặn được ghi, không tự đổi Python/stack/model.

- [x] T004 [Setup/config] [—] Settings DB/JWT/Gemini/E5/paths/CORS/deadline/OCR; mẫu không secret; ignore env/data/model cache.
  - File: `backend/app/core/config.py`, `backend/.env.example`, `frontend/.env.example`, `.gitignore`.
  - Phụ thuộc: T003; coverage: FR-006 FR-034 FR-035.
  - Nghiệm thu: Thiếu key không chặn startup, JWT secret sai bị chặn; VITE chỉ API URL; không có key thật trong file/bundle.

- [x] T005 [Database] [—] Engine WAL/FK/busy_timeout5000, UUID/timeUTC, Session mỗi request/thread; init chỉ tạo thiếu.
  - File: `backend/app/db/base.py`, `backend/app/db/session.py`, `backend/app/cli/init_db.py`.
  - Phụ thuộc: T004; coverage: FR-035.
  - Nghiệm thu: Init hai lần không mất dữ liệu; transaction rollback/FK được test ở T007.

- [x] T006 [Backend/API] [—] App/lifespan skeleton, request_id/error envelope, CORS allowlist, health flags, log metadata sanitize.
  - File: `backend/app/main.py`, `backend/app/api/router.py`, `backend/app/core/errors.py`, `backend/app/core/logging.py`, `backend/app/api/routes/health.py`.
  - Phụ thuộc: T004, T005; coverage: FR-034.
  - Nghiệm thu: Health không secret; lỗi không stack/path/key hoặc nội dung Guest; chưa start lịch khi scheduler chưa có.

- [x] T007 [Test/foundation] [—] SQLite file tạm, fake clock/network/encoder/Gemini/OCR; kiểm config/FK/init/rollback/error/CORS.
  - File: `backend/tests/conftest.py`, `backend/tests/unit/test_foundation.py`, `backend/tests/fixtures/`.
  - Phụ thuộc: T005, T006; coverage: FR-034 FR-035 FR-036.
  - Nghiệm thu: Offline mặc định; fixture ghi nhãn/cách ly; unit pass cả success và invalid config, không mạng thật.

## 2. Database và authentication — checkpoint A

- [x] T008 [Database/auth] [US3] users/auth_sessions theo data model, email unique/role enum/session revoke.
  - File: `backend/app/models/identity.py`.
  - Phụ thuộc: T005, T007; coverage: FR-026 FR-027.
  - Nghiệm thu: DB tests unique email/role/session FK pass; không raw password/JWT.

- [x] T009 [Auth] [US3] Argon2id, JWT HS256 sub/sid/iat/exp/iss/aud30phút; login/logout revoke sid.
  - File: `backend/app/core/security.py`, `backend/app/services/auth.py`.
  - Phụ thuộc: T008; coverage: FR-026.
  - Nghiệm thu: Unit hash verify đúng/sai, token expiry/signature/audience/revoked đúng; không lưu secret log.

- [x] T010 [Auth/RBAC] [US3] optional/required auth, DB role/active/session, require_admin và owner helper deny mặc định.
  - File: `backend/app/api/deps.py`.
  - Phụ thuộc: T009; coverage: FR-027 FR-028.
  - Nghiệm thu: Invalid Bearer401 không Guest; Guest401/USER403 trên Admin; ADMIN không vượt owner.

- [x] T011 [Auth/API/CLI] [US3] Register/login/me/logout JSON strict, email/password validation; CLI email/password prompt không echo.
  - File: `backend/app/api/routes/auth.py`, `backend/app/schemas/auth.py`, `backend/app/cli/create_admin.py`.
  - Phụ thuộc: T010; coverage: FR-026 FR-027.
  - Nghiệm thu: Register luôn USER, extra role422, duplicate409, logout204 sau revoke; CLI không hardcode account.

- [x] T012 [Test/auth] [US3] Nghiệm thu auth/RBAC bằng Guest/2USER/ADMIN và token giả/hết hạn/revoked/inactive.
  - File: `backend/tests/contract/test_auth.py`, `backend/tests/integration/test_auth.py`.
  - Phụ thuộc: T011; coverage: FR-026 FR-027 FR-028 SC-004.
  - Nghiệm thu: Q02 pass, 401 header/403 đúng; password rõ/key không lộ. Checkpoint A hoàn tất sau T007 và T012.

## 3. Quản lý tài liệu — checkpoint B1

- [x] T013 [Database/knowledge] [US2] documents/origins, hash/context unique và web URL partial unique; upload UUID riêng; enabled độc lập state.
  - File: `backend/app/models/knowledge.py`.
  - Phụ thuộc: T005, T007; coverage: FR-009 FR-010 FR-011 FR-013 FR-032.
  - Nghiệm thu: Chỉ data_sources/documents/document_origins và FK đã có ở T013: hash/context unique, web URL partial unique, document→origins cascade, provenance/UUID. Không đòi chunks(T025), jobs(T038), majors(T043) hoặc đủ13bảng; schema/cascade đầy đủ nghiệm thu T062.

- [x] T014 [Database/run] [US7] runs/items có created_at và terminal skipped_busy; started_at nullable chỉ khi lượt lịch bị bỏ.
  - File: `backend/app/models/crawl.py`.
  - Phụ thuộc: T013; coverage: FR-016 FR-021.
  - Nghiệm thu: URL trùng/sai vẫn log theo item_index; skipped_busy trigger scheduled, startnull/end=created/counts0/items0, ràng buộc item_index đúng.

- [x] T015 [Crawler/coordinator] [US7] Coordinator active_run_id + Lock chỉ chuyển trạng thái ngắn; claim/nhả trước pipeline; cron busy ghi skipped_busy rồi trả.
  - File: `backend/app/services/coordinator.py`.
  - Phụ thuộc: T014; coverage: FR-019 FR-020 FR-021.
  - Nghiệm thu: Không giữ mutex qua network/OCR/embedding/join/publish; một pipeline, manual busy409; xong/lỗi/stop clear slot, không tự start lượt khác hoặc acquire lặp/deadlock.

- [x] T016 [Admin/source] [US2] Registry nguồn allowed/unknown/denied, kind career import-only bên cạnh utc/topcv; robots/terms/reuse/rate, URL canonical/allowlist/redirect/private-IP gate.
  - File: `backend/app/services/sources.py`.
  - Phụ thuộc: T013, T010; coverage: FR-014.
  - Nghiệm thu: Unknown không enable/fetch/import, HTTPS/host/path đúng, tracking bỏ nhưng query năm giữ; requests chỉ dùng URL đã kiểm.

- [x] T017 [Admin/document] [US2] Upload20MiB tự xử lý/index, origin UUID/provenance; CRUD/search/disable/enable/delete vật lý.
  - File: `backend/app/services/documents.py`, `backend/app/schemas/document.py`.
  - Phụ thuộc: T013, T016; coverage: FR-007 FR-010 FR-032.
  - Nghiệm thu: Disabled giữ flag qua update/merge; enable chỉready usable; delete cascade, website còn có thể nhập lại; không unique sai note.

- [x] T018 [Admin/API] [US2] Routes documents/sources theo REST, upload202 có origin_id UUID qua coordinator; metadata origin_kind/notes, original chỉ Admin.
  - File: `backend/app/api/routes/admin.py`, `backend/app/api/routes/documents.py`.
  - Phụ thuộc: T010, T015, T016, T017; coverage: FR-007 FR-009 FR-010 FR-032.
  - Nghiệm thu: Contract có thể inject indexer stub, không gọi success ingest thực trước T027; public source implementation đầy đủ tại T028.

- [x] T019 [Test/admin contract] [US2] Test schema/role/limits/note/public privacy với indexer stub; upload nhiều provenance/cùngURL kháccontext, partial unique web và reopen DB.
  - File: `backend/tests/contract/test_documents.py`, `backend/tests/contract/test_sources.py`.
  - Phụ thuộc: T018; coverage: FR-007 FR-010 FR-011 FR-014 FR-028 FR-032 SC-003 SC-004.
  - Nghiệm thu: Role/limits/provenance qua restart đúng; disable giữ enabled=false, enable/delete API đúng; indexer stub, chưa nghiệm thu embedding. Checkpoint B1.

## 4. UTC crawler và xử lý PDF/OCR — checkpoint B2

- [x] T020 [Crawler/UTC] [US2] Discovery HTML/attachments/phân trang UTC đúng quyền; requests5/20s, mininterval, redirect,403/CAPTCHA/429.
  - File: `backend/app/services/crawl.py`, `backend/app/services/adapters/utc.py`.
  - Phụ thuộc: T015, T016; coverage: FR-007 FR-014.
  - Nghiệm thu: Unit mock nguồn: không bypass/private fetch, Retry-After đặt retry_not_before; lỗi nguồn không tự xóa dữ liệu.

- [x] T021 [Extraction] [US2] BeautifulSoup HTML, PyMuPDF native theo trang/bảng, TXT UTF-8, metadata/page và numeric_eligible.
  - File: `backend/app/services/extraction.py`.
  - Phụ thuộc: T020; coverage: FR-008 FR-009.
  - Nghiệm thu: Native đọc rõ tự sẵn sàng cho index; bảng mất header/quá200 trang/hỏng có lý do cách ly/lỗi; không suy năm từ ngày đăng.

- [x] T022 [OCR] [US2] Tesseract CLI vie+eng fallback, TSV confidence>=90/30ký tự,60s/page/5phút item; OCR numeric false.
  - File: `backend/app/services/extraction.py`.
  - Phụ thuộc: T021; coverage: FR-008.
  - Nghiệm thu: Scan tốt mô tả được; ảnh mờ/thiếu tessdata/timeout không dùng evidence; không workflow duyệt trang hoặc tự sửa số.

- [x] T023 [Ingestion/hash/origin] [US2] Hash/context/profile skip độc lập originUUID; staging giữ cũ khi lỗi, cập nhật giữ enabled=false.
  - File: `backend/app/services/crawl.py`, `backend/app/services/documents.py`.
  - Phụ thuộc: T013, T015, T017, T021, T022; coverage: FR-011 FR-012 FR-013.
  - Nghiệm thu: Cùngtext/context/profile encode0; kháccontext tách; giữ disable khi tách/merge origin, không tự bật.

- [x] T024 [Test/crawler] [US2] Test quyền/HTML/PDF/OCR/URL/hash/multi-origin/counters/source failure với indexer fake, H1 cùngbytes/cùngURL/note/context.
  - File: `backend/tests/unit/test_ingestion.py`, `backend/tests/unit/test_extraction.py`, `backend/tests/unit/test_coordinator.py`.
  - Phụ thuộc: T019, T020, T021, T022, T023; coverage: FR-007 FR-008 FR-009 FR-011 FR-014 FR-016 SC-003.
  - Nghiệm thu: Q03–Q07: origin không nhân document/encode, kháccontext không gộp, disabled giữ flag; extraction/OCR đúng, fakeencoder. Checkpoint B2.
  - Bằng chứng bổ sung: smoke Tesseract thật vie+eng tại `backend/tests/smoke/check_ocr.py`, kết quả `backend/tests/smoke/ocr-local.json`; native/PNG tiếng Việt/PDF scan/quarantine đều PASS. Báo cáo nghiệm thu ghi chi tiết; embedding vẫn fake theo phạm vi B2.

## 5. Local embedding và retrieval — checkpoint C

- [X] T025 [Database/chunking] [US2] chunks384/BLOB constraints, snapshot/page/context; chunk320 token overlap48, giữ headers, <=512 incl prefix/special.
  - File: `backend/app/models/knowledge.py`, `backend/app/services/chunking.py`.
  - Phụ thuộc: T023, T024; coverage: FR-009 FR-012.
  - Nghiệm thu: Unit boundary/metadata và DB BLOB length1536 pass; không trộn trang/điều kiện làm mất context.

- [X] T026 [RAG/embedding] [US2] Singleton E5 CPU cùng revision, query:/passage:,L2,<f4; encode lock, profile, không truncate query.
  - File: `backend/app/services/embedding.py`.
  - Phụ thuộc: T003, T025; coverage: FR-012 FR-035.
  - Nghiệm thu: Smoke thật trên CPU + unit spy/prefix/dim/norm/finite/BLOB roundtrip; query vượt budget422.

- [X] T027 [RAG/publish] [US2] Publish staging transaction ngắn dưới khóa, kiểm doc hiện hành/quyền/enabled; nối cùng pipeline coordinator.
  - File: `backend/app/services/documents.py`, `backend/app/services/crawl.py`.
  - Phụ thuộc: T015, T023, T025, T026; coverage: FR-011 FR-012 FR-013 FR-032.
  - Nghiệm thu: Unchanged encode0; update lỗi giữ cũ; disabled cập nhật vẫn false; target bị xóa trong staging error DOCUMENT_REMOVED, lượt mới được nhập lại.

- [X] T028 [RAG/retrieval/source] [US2] NumPy cosine top5/threshold config, filter profile/context/usable; public excerpts/source410 không private note.
  - File: `backend/app/services/retrieval.py`, `backend/app/api/routes/documents.py`.
  - Phụ thuộc: T027; coverage: FR-004 FR-005 FR-013.
  - Nghiệm thu: Fixture topk đúng, disabled/quarantined/sai context không retrieval; available kiểm hiện hành, không cache stale vector.

- [X] T029 [Test/RAG data] [US2] Integration ingestion→retrieval/source API, dedup/disable/enable/delete/restart; E5 smoke riêng.
  - File: `backend/tests/integration/test_knowledge.py`, `backend/tests/unit/test_retrieval.py`.
  - Phụ thuộc: T028; coverage: FR-008 FR-009 FR-010 FR-011 FR-012 FR-013 FR-032 SC-002 SC-003.
  - Nghiệm thu: 1new/1update/1skip/1error; note/context/encode đúng, disabled qua restart không bật; delete thật rồi recrawl tạo mới, DISABLED_DUPLICATE giữ flag và không lỗiunique, OCR số không eligible. Checkpoint C.

## 6. Gemini RAG chatbot — checkpoint D1

- [X] T030 [RAG/scope] [US1] Rules UTC/social/ngoài/hỗn hợp/mơ hồ, message/turn/context validation; inject catalogue resolver, chưa có catalogue thì hỏi lại câu nghề mơ hồ.
  - File: `backend/app/services/scope.py`.
  - Phụ thuộc: T028; coverage: FR-001 FR-002 FR-003.
  - Nghiệm thu: Unit status expected, không Gemini cho nhánh không cần; không tự coi ngành trường khác là UTC.

- [X] T031 [RAG/evidence] [US1] Evidence gate context/thiếu/conflict, native quote template, ID/source validation; numeric guard tách literal năm/mã/tên chương trình khỏi giá trị định lượng.
  - File: `backend/app/services/evidence.py`.
  - Phụ thuộc: T028, T030; coverage: FR-003 FR-004 FR-005.
  - Nghiệm thu: H2: literal đúng vai trò/citedsource được giữ, không blanket chữ số/keyword; giá trị điểm/phí/chỉtiêu/ngày/count trùng mã vẫn bị loại; native đúng context, không parser claim.

- [X] T032 [RAG/Gemini] [US1] google-genai async SDK/default model, strict answer/evidence_ids, grounding cho phép context literals, attempts1; timeout<=remaining lúc gọi và sanitize error.
  - File: `backend/app/services/gemini.py`.
  - Phụ thuộc: T004, T031; coverage: FR-006 FR-034.
  - Nghiệm thu: Stub429 chỉ1call→503quota; key503/SDKtimeout504/service503 đúng; không fallback/key leak, không reset outer timeout hoặc tự lưu message.

- [X] T033 [RAG/chat API] [US1] Một async handler với asyncio.timeout_at(expires_at) tổng60s, retrieval CPU to_thread chỉ trả dữ liệu, numeric bypass Gemini; handler kiểm nguồn/session/hạn trước trả Reply và lưu.
  - File: `backend/app/services/chat.py`, `backend/app/schemas/chat.py`, `backend/app/api/routes/chat.py`.
  - Phụ thuộc: T006, T030, T031, T032; coverage: FR-001 FR-002 FR-003 FR-004 FR-005 FR-006 FR-029.
  - Nghiệm thu: Reply200/schema đúng, output sai→insufficient; outertimeout504, kết quả CPU/Gemini muộn không finalize/persist; không CPU kill/task registry; Guest không DB/log.

- [X] T034 [Test/chat] [US1] Test scope/nguồn/JSON/ID/injection, H2 năm/mã/tên cósố hợp lệ và số bịa, quota/key/outertimeout, disable khi Gemini stub chờ.
  - File: `backend/tests/contract/test_chat.py`, `backend/tests/integration/test_chat.py`.
  - Phụ thuộc: T033; coverage: FR-001 FR-002 FR-003 FR-004 FR-005 FR-006 FR-029 FR-034 SC-001 SC-002.
  - Nghiệm thu: Q09–Q14/H2 pass: literal sourced không bị chặn, số định lượng trùng ID vẫn bị loại; outer504 khác SDK504, attempts1; sốnative có nguồn, không bảo đảm tuyệt đối narrative.

## 7. Lịch sử hội thoại — checkpoint D

- [ ] T035 [Database/history] [US4] Owner CRUD, messages seq/turn pair, title, source snapshot, một request/hội thoại.
  - File: `backend/app/models/conversation.py`, `backend/app/services/conversations.py`.
  - Phụ thuộc: T012, T033; coverage: FR-030 FR-031.
  - Nghiệm thu: Unit owner/seq/rename/delete cascade, chỉ handler gọi lưu cặp tin; recheck session/deadline trước transaction, HTTP lỗi không cặp tin mồ côi.

- [ ] T036 [History/API] [US4] Gắn account chat vào async orchestrator, owner trước đọc; chỉ handler chưa timeout commit cặp200 đúng status, source available khi xem.
  - File: `backend/app/api/routes/conversations.py`, `backend/app/schemas/conversation.py`.
  - Phụ thuộc: T035; coverage: FR-028 FR-030 FR-031.
  - Nghiệm thu: 404 mọi thao tác trên hội thoại người khác kể cả ADMIN;409busy; expired session không ghi; old snapshots không làm evidence.

- [ ] T037 [Test/history] [US4] Hai USER/ADMIN, quota/SDKtimeout/outertimeout account, cho CPU stub trả muộn, title boundaries, source đổi/xóa/logout.
  - File: `backend/tests/contract/test_history.py`, `backend/tests/integration/test_history.py`.
  - Phụ thuộc: T034, T036; coverage: FR-028 FR-029 FR-030 FR-031 SC-004.
  - Nghiệm thu: Sau timeout và sau stub trả muộn đều không thêm messages/answered; quota/key không leak; thiếunguồn đúngstatus, Guest/privacy/ownership/source pass. Checkpoint D.

## 8. Thông tin nghề nghiệp — checkpoint E1

- [ ] T038 [Database/career] [US6] Job model source_id/identity_key/origin_id, unique source+key; cascade khi doc/origin xóa.
  - File: `backend/app/models/career.py`.
  - Phụ thuộc: T013, T014; coverage: FR-015 FR-017 FR-018.
  - Nghiệm thu: UNIQUE(source_id,identity_key), fallbackURL/nângID đúng; cùng source/URL khác external_id báo identity_conflict trước ghi, không đổi job/origin khác; shared doc không gộpjob.

- [ ] T039 [Crawler/TopCV] [US6] Adapter khi allowed, mỗi tin đúng origin; HTML không hỗ trợ/403/CAPTCHA/unknown dừng,429backoff.
  - File: `backend/app/services/adapters/topcv.py`.
  - Phụ thuộc: T020, T027, T038; coverage: FR-014 FR-015.
  - Nghiệm thu: Mock cấm không fetch, source lỗi giữ cũ; không phụ thuộc TopCV live cho nghiệm thu.

- [ ] T040 [Crawler/job import] [US6] CSV/JSON20MiB/5000records, publisher row/default, normalize payload; first-valid-wins, so DB cho new/updated/skipped, row conflict/error.
  - File: `backend/app/services/adapters/job_import.py`.
  - Phụ thuộc: T015, T027, T038; coverage: FR-015 FR-016.
  - Nghiệm thu: U1/U2 theo data-model: cùngidentity/payload skipped, đổi nghiệp vụ soDB updated, file mâu thuẫn conflict; sameURL khácID identity_conflict trướcghi; observation-only không updated, không thêm last_seen_at, log/counters đủ.

- [ ] T041 [Career/API] [US6] GETjobs/import202, origin JOIN, status/time, COUNT job.id theo identity, major filter interface.
  - File: `backend/app/services/jobs.py`, `backend/app/schemas/career.py`, `backend/app/api/routes/jobs.py`, `backend/app/api/routes/admin.py`.
  - Phụ thuộc: T038, T039, T040; coverage: FR-015 FR-017 FR-018.
  - Nghiệm thu: HaiURL cùngtext khôngID→2jobs/count2; sameexternalID đổiURL→1; không gộp theo document; filter major có thể contractstub.

- [ ] T042 [Test/career] [US6] Nghiệm thu import/status/origin/count; contract major_id với stub resolver.
  - File: `backend/tests/contract/test_jobs.py`, `backend/tests/integration/test_job_import.py`.
  - Phụ thuộc: T041; coverage: FR-014 FR-015 FR-016 FR-017 FR-018 SC-006.
  - Nghiệm thu: Q16/Q17/U1-U2 pass: new/update/skip, first-valid-wins/invalidfirst, conflict vs identity_conflict không đổi origin khác, observation-only skipped, status-only updated/encode0; mixed6rows counts1new/1updated/2skipped/2error; majorfilter stub. Checkpoint E1.

## 9. Quiz và gợi ý ngành — checkpoint E2

- [ ] T043 [Database/quiz/catalogue] [US5] majors có sourcehash/description/career_groups; quiz10 positions/scoring_json direction positive/negative/none + reason.
  - File: `backend/app/models/quiz.py`.
  - Phụ thuộc: T013, T029; coverage: FR-022 FR-025.
  - Nghiệm thu: Uniquecode/campus/position; direction enum, đủ mapping, mỗi ngành N>=1/mỗi câu>=1 ngành khácnone; không profile thí sinh.

- [ ] T044 [Recommendation/catalogue CLI] [US5] CLI nhập catalogue+10câu+mapping từ file có nguồn, backend dừng; atomic validate, rubric_version hash.
  - File: `backend/app/cli/import_catalog.py`, `backend/app/services/recommendation.py`.
  - Phụ thuộc: T043, T016; coverage: FR-022 FR-023 FR-024 FR-025.
  - Nghiệm thu: Source ready/current/allowed,>=3ngành, N>=1 và mapping đủ/đúngchiều, direction/reason vào rubric hash; invalid rollback, không tạo thông tin giả.

- [ ] T045 [Recommendation/scoring] [US5] Contribution thuận=(a-1)/4, nghịch=(5-a)/4, none loại; fit=100*sum(c)/N, sort chưa round/code/campus, top3–5.
  - File: `backend/app/services/recommendation.py`.
  - Phụ thuộc: T044; coverage: FR-022 FR-023 FR-024.
  - Nghiệm thu: M1 cases S1–S6/biên1-3-5 đúng, none không mẫu số/lý do; reason tối đa2 với c>=0,75 đúng chiều; tie/zero/missing, không Gemini/điểm học tập.

- [ ] T046 [Quiz/API] [US5] GET catalogue/quiz hai schema với scoring direction/reason; POST chỉ rubric_version/answers và mọi result state.
  - File: `backend/app/api/routes/quiz.py`, `backend/app/schemas/quiz.py`.
  - Phụ thuộc: T045; coverage: FR-022 FR-023 FR-024 FR-025.
  - Nghiệm thu: Ready/missing đủ6khóa GET, direction enum; đổichiều rubric409,422invalid, disclaimer/source/reason đúngthuận-nghịch; không input học tập.

- [ ] T047 [Test/quiz] [US5] M1 S1–S6 theo testing.md, contribution biên1/3/5, none/N=0/mapping thiếu, source/version, zero/insufficient_matches.
  - File: `backend/tests/unit/test_recommendation.py`, `backend/tests/contract/test_quiz.py`, `backend/tests/integration/test_quiz.py`.
  - Phụ thuộc: T046; coverage: FR-022 FR-023 FR-024 FR-025 SC-005.
  - Nghiệm thu: Q18/Q19/M1 pass: S1=(100,0,50), S2=(0,100,50), S3=(50,50,50), S4=(75,25,50), S5=(75,25,55), S6=(50,50,100); none không đổi A/B, reason nghịch đúng; missing/stale/status đúng.

- [ ] T048 [Career-major integration] [US5/US6] Nối major career_groups thật vào jobs filter và scope resolver, nguồn/mapping stale check; chạy hành trình quiz→ngành→nghề.
  - File: `backend/app/services/jobs.py`, `backend/tests/integration/test_major_jobs.py`.
  - Phụ thuộc: T034, T041, T042, T044, T046, T047; coverage: FR-017 FR-023 FR-025 SC-006.
  - Nghiệm thu: Q20 pass, null/khác nhóm không lọt; scope nhận nghề liên quan catalogue, mơ hồ vẫn hỏi lại; checkpoint E2 sau toàn dependency.

## 10. Scheduler — checkpoint F

- [ ] T049 [Scheduler] [US7] APScheduler00:00VN cố định, manual không reset; busy ghi skipped_busy, rảnh dùng chung pipeline.
  - File: `backend/app/services/scheduler.py`, `backend/app/main.py`, `backend/app/services/coordinator.py`.
  - Phụ thuộc: T015, T027, T039, T040, T048; coverage: FR-019 FR-020 FR-021.
  - Nghiệm thu: Manual10:00 không đổi00:00ngày sau; cron busy bỏ lượt không tự retry khi rảnh/restart; log khác failed, last_success không tăng; backend tắt không chạy bù.

- [ ] T050 [Admin/run API] [US7] Admin Crawl ngay nền202/run_id, busy409; list/detail/items/stop có terminal skipped_busy.
  - File: `backend/app/api/routes/admin.py`, `backend/app/schemas/crawl.py`.
  - Phụ thuộc: T010, T049; coverage: FR-019 FR-020 FR-021.
  - Nghiệm thu: ADMIN thực/Guest401/USER403, HTTP không đợi crawl; skipped_busy counts0/startnull/items0; stop terminal idempotent, không dừng run khác.

- [ ] T051 [Test/scheduler] [US7] Fakeclock cron/manual/upload/import cùngslot, skipped_busy, stop/rerun/restart giữ dữ liệu cũ.
  - File: `backend/tests/contract/test_runs.py`, `backend/tests/integration/test_scheduler.py`.
  - Phụ thuộc: T050, T029, T042; coverage: FR-019 FR-020 FR-021 SC-007.
  - Nghiệm thu: Event giữ manual tại network/OCR/embedding: cron ghi skipped_busy trước nhả Event; max pipeline1, manual409; nhả slot/restart không chạy lượt bỏ, ngày sau00:00 rảnh chạy; skipbusy counters0/items0 không failed, stop sauitem/rerun ID mới, lỗi giữ cũ.

## 11. Frontend dashboard — checkpoint G

- [ ] T052 [Frontend/API] [US8] DTOs theo REST gồm origin_kind/UUID và quiz scoring.direction, Axios/token RAM/401/logout, no auto POST retry; status unions.
  - File: `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/app/AuthContext.tsx`.
  - Phụ thuộc: T012, T034, T037, T042, T047, T050; coverage: FR-028 FR-034.
  - Nghiệm thu: Typecheck không dùng optional-field guessing; không key/token persistent, expiry không gửi như Guest âm thầm.

- [ ] T053 [Frontend/layout] [US8] Router/header/sidebar/mobilemenu, route guard theo role, loading/empty/error/missing dùng chung.
  - File: `frontend/src/app/router.tsx`, `frontend/src/components/DashboardLayout.tsx`, `frontend/src/components/AsyncState.tsx`.
  - Phụ thuộc: T002, T052; coverage: FR-033.
  - Nghiệm thu: Đến được các trang đúng quyền; guard không thay backend auth; plain text source/model.

- [ ] T054 [Frontend/auth] [US8] Login/register/logout form, validation, token RAM, không rolepicker.
  - File: `frontend/src/pages/Login.tsx`, `frontend/src/pages/Register.tsx`.
  - Phụ thuộc: T053; coverage: FR-026 FR-027 FR-033.
  - Nghiệm thu: Login đúng/sai/duplicate/logout/reload cần login; không password console.

- [ ] T055 [Frontend/chat] [US8] Guest/account chat, contextclarification/sourcecards, trạng thái/lỗi quota-timeout-key, disable duplicate send.
  - File: `frontend/src/pages/Chat.tsx`, `frontend/src/components/SourceCard.tsx`.
  - Phụ thuộc: T053, T054; coverage: FR-001 FR-002 FR-003 FR-004 FR-005 FR-006 FR-029 FR-033.
  - Nghiệm thu: Guest không lưu, error kết thúc loading, thử lại có kiểm history khi không rõ commit; source unavailable rõ.

- [ ] T056 [Frontend/history] [US8] List/open/continue/rename/delete confirm, messages seq/citation unavailable.
  - File: `frontend/src/pages/History.tsx`.
  - Phụ thuộc: T055; coverage: FR-030 FR-031 FR-033.
  - Nghiệm thu: CRUD giữ sau reload/login lại; lỗi/401/404 rõ; không truy cập conversation khác.

- [ ] T057 [Frontend/quiz] [US8] 10câu Likert, công bố quy tắc thuận/nghịch/none, score/reasons/nguồn/disclaimer; switch status quiz/result.
  - File: `frontend/src/pages/Recommendation.tsx`.
  - Phụ thuộc: T053, T047; coverage: FR-022 FR-023 FR-024 FR-025 FR-033.
  - Nghiệm thu: GET missing không form giả; đổi direction cần rubric mới, lý do câu nghịch không đảo nghĩa, ready3–5/zero/ítmatch rõ; không form điểm học tập.

- [ ] T058 [Frontend/jobs] [US8] Ngành/nhóm nghề/status filter, nguồn/collected_at/date/nhãn và số quan sát.
  - File: `frontend/src/pages/Jobs.tsx`.
  - Phụ thuộc: T053, T048; coverage: FR-015 FR-017 FR-018 FR-033.
  - Nghiệm thu: Không gọi sốtin là sốvịtrí/thịtrường; missing khác0, nullgroup/expired đúng.

- [ ] T059 [Frontend/admin docs] [US8] Admin upload/note/list/detail/original/disable/enable/delete, lỗi/quarantine.
  - File: `frontend/src/pages/admin/Documents.tsx`.
  - Phụ thuộc: T053, T029; coverage: FR-007 FR-009 FR-010 FR-032 FR-033.
  - Nghiệm thu: Delete confirm nói có thể crawl lại; disabled bền qua update, enable thủ công, không trang quản lý dấu chặn.

- [ ] T060 [Frontend/admin sources/runs] [US8] Admin nguồn/quyền, Crawl ngay, polling run running/terminal/counts, skipped_busy, stop/rerun.
  - File: `frontend/src/pages/admin/Sources.tsx`, `frontend/src/pages/admin/Runs.tsx`.
  - Phụ thuộc: T053, T051; coverage: FR-014 FR-019 FR-020 FR-021 FR-033.
  - Nghiệm thu: 202 nền/409 busy, cron không đổi; skipped_busy hiện Bỏ qua do đang bận, khác Thất bại và Đã dừng; quyền nguồn giữ nguyên.

- [ ] T061 [Test/frontend] [US8] npm run build, kiểm tay đủrole/page/viewport360/768/1366 và loading/empty/error/missing.
  - File: `frontend/package.json`, `docs/demo/acceptance-results.md`.
  - Phụ thuộc: T054, T055, T056, T057, T058, T059, T060; coverage: FR-033 FR-034 SC-008.
  - Nghiệm thu: Không cuộn ngang toàn trang, plain text/no secret, quiz hai schema/status, source/history/startstop dùng được. Checkpoint G.

## 12. Integration, security và grounding

- [ ] T062 [Test/integration] [—] Integration schema/cascade đầy đủ13bảng rồi ingestion→chat/history/docs/jobs/quiz và restart/rerun.
  - File: `backend/tests/integration/test_demo_flow.py`.
  - Phụ thuộc: T029, T034, T037, T048, T051; coverage: FR-011 FR-012 FR-013 FR-016 FR-021 FR-031 FR-032 SC-003 SC-006 SC-007.
  - Nghiệm thu: Sau T025/T038/T043 và dependency hiện tại: kiểm schema/FK/unique đủ13bảng, delete doc cascade chunks/origins/jobs/majors, run FK SET NULL, snapshot history giữ unavailable, quiz refs mất trả missing; disabled/recrawl/counters/owner đúng. Đây là checkpoint toàn hệ thống, không đòi ở T013.

- [ ] T063 [Test/security] [—] Rà revoke/owner/RBAC/key/log/bundle/Guest/injection/SSRF/pathtraversal, kiểm nguồn disable khi đang chờ.
  - File: `backend/tests/integration/test_security.py`, `docs/demo/acceptance-results.md`.
  - Phụ thuộc: T012, T019, T034, T037, T048, T051, T061; coverage: FR-006 FR-014 FR-026 FR-027 FR-028 FR-029 FR-034 SC-004.
  - Nghiệm thu: Mọi bypass bị từ chối; raw SDK error/key không leak; quota không answered; không bỏ critical security tests.

- [ ] T064 [Test/grounding] [US1] Bộ30câu expected status/source gồm H2 literal năm/mã/têncósố và số giả trùng ID, review mô tả; cutoffnative/OCR/conflict.
  - File: `backend/tests/fixtures/chat_cases.json`, `docs/demo/acceptance-results.md`.
  - Phụ thuộc: T034, T037, T048; coverage: FR-002 FR-003 FR-004 FR-005 FR-025 FR-036 SC-001 SC-002.
  - Nghiệm thu: Citation/số bịa bị loại, literal sourced đúng vai trò không false reject; người kiểm ghi thêm/đổi nghĩa/đảo phủ định; lỗi mẫu sửa trước đạt, không hứa tuyệt đối.

- [ ] T065 [Test/performance] [US1] Kiểm một timeout tổng/SDKtimeout và handler không lưu kết quả muộn, không hủy CPU; đo10câu warmCPU/hiệu chỉnhthreshold.
  - File: `backend/tests/integration/test_deadline.py`, `docs/demo/acceptance-results.md`.
  - Phụ thuộc: T062, T064; coverage: FR-006 FR-031 SC-009.
  - Nghiệm thu: M2: timeout rút ngắn trả504 đúng, CPU stub kết thúc sau không thêm messages/callback; check trướccommit, dung sai điều phối/transaction được ghi; mục tiêu9/10<=30s và timeout tổng60s.

## 13. Hoàn thiện demo — checkpoint H

- [ ] T066 [Demo/manifest] [—] Chuẩn bị dữ liệu thật có quyền: UTC/native điểmchuẩn nếu có, jobsfilefallback, metadata/page/quyền/thời gian.
  - File: `docs/demo/manifest.json`.
  - Phụ thuộc: T062, T063; coverage: FR-009 FR-014 FR-015 FR-036 SC-010.
  - Nghiệm thu: Manifest có tài liệu UTC được phép dùng cho RAG và >=1 tin nghề nghiệp hợp lệ (nguồn/time/status rõ); không đủ thì task chưa đạt demo, ghi thiếu, không bịa và không secret.

- [ ] T067 [Demo/catalogue/quiz] [US5] Biên soạn10câu thuận/nghịch/none và catalogue >=3 ngành UTC có nguồn hợp lệ cho demo.
  - File: `backend/data/import/catalog.json`, `docs/demo/manifest.json`.
  - Phụ thuộc: T047, T066; coverage: FR-022 FR-023 FR-024 FR-025 FR-036.
  - Nghiệm thu: >=3 ngành usable, sourcehash/page đúng, rule/reason minh bạch và sample answers cho kết quả ready; không đủ thì ghi data_missing nhưng task demo chưa đạt.

- [ ] T068 [Demo/load] [—] Nạp dữ liệu hợp lệ qua pipeline chung và CLIcatalogue lúc backenddừng; kiểm dedup/disable/delete/note persist.
  - File: `docs/demo/acceptance-results.md`, `docs/demo/manifest.json`.
  - Phụ thuộc: T051, T066, T067; coverage: FR-010 FR-011 FR-012 FR-013 FR-015 FR-016 FR-036.
  - Nghiệm thu: Nạp nguồn thật và demo upload hợp lệ→index→retrieval có nguồn; >=3 ngành/quiz ready, >=1 tin nghề nghiệp hiển thị đúng nguồn/status; verify disable/delete/note, không trộn fixture; chỉ data_missing chưa đạt.

- [ ] T069 [Docs/local] [—] README setup uv/npm/locks/Admin/OCR/model/import/tests/1worker và giới hạn; khớp quickstart.
  - File: `README.md`, `specs/001-utc-admissions-chatbot/quickstart.md`, `docs/demo/acceptance-results.md`.
  - Phụ thuộc: T061, T065, T068; coverage: FR-035 FR-036 SC-010.
  - Nghiệm thu: Lệnh PowerShell rõ, không dùng secret mẫu thật, không đổi nhánh, không cài hệ production; kết quả test thực được ghi.

- [ ] T070 [Demo/final] [—] Chạy từ checkout sạch theo README và trình diễn Guest/auth/history/quiz/jobs/docs/startstop/rerun/missingerror.
  - File: `docs/demo/acceptance-results.md`, `docs/demo/manifest.json`.
  - Phụ thuộc: T062, T063, T064, T065, T068, T069; coverage: FR-036 SC-008 SC-009 SC-010.
  - Nghiệm thu: SC-010 thành công thực: RAG trả lời có nguồn UTC, quiz >=3 ngành hợp lệ, nghề nghiệp có dữ liệu được phép; upload→retrieval, login/logout/history/Admin có bằng chứng actual. Nhánh missing/error vẫn test nhưng không thay demo chính; chưa đủ dữ liệu/hành trình thì NOT READY cho demo.

## Checkpoint và phạm vi tests

| Checkpoint | Tasks kết thúc | Dependency đầy đủ | Kiểm tra được phép trước đó |
| --- | --- | --- | --- |
| A | T007,T012 | Setup/DB/auth | Unit và auth contract/integration |
| B1 | T019 | Documents/sources, indexer stub | T013 chỉ schema/FK đã có; chưa đòi jobs/majors/chunks hoặc đầy đủ cascade |
| B2 | T024 | UTC/extraction/OCR/hash | Unit dùng fake encoder; chưa tuyên bố publish/retrieval hoàn tất |
| C | T029 | Chunk/E5/publish/retrieval | Integration knowledge, kể cả public source |
| D | T034,T037 | Chat/Gemini/history | Quota/deadline account cần T036/T037, guest test có thể chạy tại T034 |
| E1 | T042 | Jobs/import/status | Major filter contract stub, không nghiệm thu filter thật |
| E2 | T047,T048 | Catalogue/quiz + jobs | Integration major filter sau T044/T046, không đòi trước T042 |
| F | T051 | Coordinator/ingestion/scheduler/run API | Fake clock và single-process restart, không multi-process crash test |
| G | T061 | Frontend + API | Build và kiểm tay responsive/state |
| Full DB | T062 | Chunks T025, jobs T038, majors T043 qua dependency hiện tại | Schema/FK/cascade đủ13bảng; không đổi thứ tự task |
| H | T070 | T062–T069 và core checkpoints | Demo/coverage theo actual; chưa chạy không được ghi pass |

## Requirement coverage

Bảng dưới là coverage thiết kế, không phải kết quả tests. Không có task không gắn FR/SC.

| FR | Tasks |
| --- | --- |
| FR-001 | T030, T033, T034, T055 |
| FR-002 | T030, T033, T034, T055, T064 |
| FR-003 | T030, T031, T033, T034, T055, T064 |
| FR-004 | T028, T031, T033, T034, T055, T064 |
| FR-005 | T028, T031, T033, T034, T055, T064 |
| FR-006 | T004, T032, T033, T034, T055, T063, T065 |
| FR-007 | T017, T018, T019, T020, T024, T059 |
| FR-008 | T021, T022, T024, T029 |
| FR-009 | T013, T018, T021, T024, T025, T029, T059, T066 |
| FR-010 | T013, T017, T018, T019, T029, T059, T068 |
| FR-011 | T013, T019, T023, T024, T027, T029, T062, T068 |
| FR-012 | T023, T025, T026, T027, T029, T062, T068 |
| FR-013 | T013, T023, T027, T028, T029, T062, T068 |
| FR-014 | T016, T019, T020, T024, T039, T042, T060, T063, T066 |
| FR-015 | T038, T039, T040, T041, T042, T058, T066, T068 |
| FR-016 | T014, T024, T040, T042, T062, T068 |
| FR-017 | T038, T041, T042, T048, T058 |
| FR-018 | T038, T041, T042, T058 |
| FR-019 | T015, T049, T050, T051, T060 |
| FR-020 | T015, T049, T050, T051, T060 |
| FR-021 | T014, T015, T049, T050, T051, T060, T062 |
| FR-022 | T043, T044, T045, T046, T047, T057, T067 |
| FR-023 | T044, T045, T046, T047, T048, T057, T067 |
| FR-024 | T044, T045, T046, T047, T057, T067 |
| FR-025 | T043, T044, T046, T047, T048, T057, T064, T067 |
| FR-026 | T008, T009, T011, T012, T054, T063 |
| FR-027 | T008, T010, T011, T012, T054, T063 |
| FR-028 | T010, T012, T019, T036, T037, T052, T063 |
| FR-029 | T033, T034, T037, T055, T063 |
| FR-030 | T035, T036, T037, T056 |
| FR-031 | T035, T036, T037, T056, T062, T065 |
| FR-032 | T013, T017, T018, T019, T027, T029, T059, T062 |
| FR-033 | T002, T053, T054, T055, T056, T057, T058, T059, T060, T061 |
| FR-034 | T004, T006, T007, T032, T034, T052, T061, T063 |
| FR-035 | T001, T002, T003, T004, T005, T007, T026, T069 |
| FR-036 | T003, T007, T064, T066, T067, T068, T069, T070 |

| SC | Tasks |
| --- | --- |
| SC-001 | T034, T064 |
| SC-002 | T029, T034, T064 |
| SC-003 | T019, T024, T029, T062 |
| SC-004 | T012, T019, T037, T063 |
| SC-005 | T047 |
| SC-006 | T042, T048, T062 |
| SC-007 | T051, T062 |
| SC-008 | T061, T070 |
| SC-009 | T065, T070 |
| SC-010 | T003, T066, T069, T070 |

## Quy tắc hoàn tất

- Mỗi task test chỉ nghiệm thu phần có dependency đủ; mock/stub được ghi rõ.
- Không giữ task của phạm vi đã loại. Catalogue/rubric/jobs thiếu dữ liệu hợp lệ phải
  hiển thị thiếu và ghi rõ hạn chế, không thay bằng nội dung giả.
- T066–T068/T070 chỉ hoàn tất khi đủ dữ liệu thật hợp lệ và hành trình thành công theo SC-010.
  Thiếu dữ liệu/quyền phải báo trung thực và để các task demo chưa đạt; test data_missing
  không thay nghiệm thu chức năng chính. Có thể READY triển khai nhưng NOT READY demo.
- Dependency lock/model/quyền nguồn/latency là kết quả phải xác minh khi triển khai,
  không suy là đã đạt từ tài liệu.
