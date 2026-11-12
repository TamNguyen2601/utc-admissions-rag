# Kế hoạch triển khai kỹ thuật

**Phạm vi**: Theo [spec](spec.md); thiết kế sẵn sàng, chưa viết source code.
Một frontend + backend modular monolith local; giữ hiến chương 1.0.0.
Các quyết định chi tiết ở [architecture](architecture.md); không có lớp triển khai production.

## Stack đã chốt

| Phần | Công nghệ |
| --- | --- |
| Frontend | React, TypeScript, Vite, Tailwind CSS, React Router, Axios; shadcn/ui cho component cần; Recharts chỉ nếu thật sự cần biểu đồ run |
| Backend | Python 3.13, FastAPI, Uvicorn một worker, SQLAlchemy, SQLite, Pydantic Settings |
| Auth/test | PyJWT, pwdlib[argon2], Pytest, httpx cho test; python-multipart cho upload |
| RAG | sentence-transformers, intfloat/multilingual-e5-small CPU, NumPy cosine, SQLite float32 BLOB |
| Sinh mô tả | google-genai, model mặc định gemini-3.5-flash-lite; key chỉ backend |
| Ingestion | requests, BeautifulSoup (beautifulsoup4), PyMuPDF, Tesseract CLI vie+eng khi cần |
| Lịch | APScheduler 3.x trong process backend |
| Dependencies | Backend uv, pyproject.toml, uv.lock, .python-version; FE npm, package.json, package-lock.json; Node.js 24.22.1 |

Không Docker/Redis/Celery/LangChain/Kubernetes/microservices/cloud database.
Không thêm thư viện OCR wrapper: subprocess/csv chuẩn Python đủ gọi Tesseract.
Trên Windows lock thêm dữ liệu múi giờ tzdata nếu ZoneInfo không có IANA data cho Asia/Ho_Chi_Minh.
Chưa khẳng định dependency đã cài/resolve: task setup phải lock và smoke trên Python 3.13.
Nếu không tương thích, ghi lỗi chặn trước khi đổi stack; không tự hạ Python.
Kiểm model được phép dùng với key demo, không tự fallback.

## Cấu trúc dự kiến (chưa tạo source)

```text
backend/
  pyproject.toml, uv.lock, .python-version, .env.example
  app/
    main.py
    core/{config,security,errors,logging}.py
    db/{base,session}.py
    models/{identity,conversation,knowledge,career,quiz,crawl}.py
    schemas/{auth,chat,conversation,document,career,quiz,crawl}.py
    api/{deps,router}.py
    api/routes/{health,auth,chat,conversations,documents,jobs,quiz,admin}.py
    services/
      auth.py, conversations.py, documents.py, sources.py
      crawl.py, extraction.py, chunking.py, embedding.py, retrieval.py
      gemini.py, scope.py, evidence.py, chat.py
      jobs.py, recommendation.py, coordinator.py, scheduler.py
      adapters/{utc,topcv,job_import}.py
    cli/{init_db,create_admin,import_catalog}.py
  tests/
    conftest.py
    unit/, contract/, integration/, fixtures/
  data/                         # ignored: SQLite, uploads, model cache
frontend/
  package.json, package-lock.json, .env.example
  src/
    main.tsx
    app/{router,AuthContext}.tsx
    api/{client,types}.ts
    components/{DashboardLayout,AsyncState,SourceCard}.tsx
    pages/{Chat,Login,Register,History,Recommendation,Jobs}.tsx
    pages/admin/{Documents,Sources,Runs}.tsx
docs/demo/{manifest.json,acceptance-results.md}
README.md
```

Tên file trong tasks là đường dẫn triển khai dự kiến; chúng chưa tồn tại và không phải
yêu cầu tạo code ở bước tài liệu này.

## Quyết định quan trọng

- SQLite WAL, foreign_keys=ON, busy_timeout=5000; transaction ngắn, Session mỗi request/thread.
  Không cần Alembic cho demo ban đầu; init_db chỉ tạo thiếu, không xóa DB khi khởi động.
- E5 cùng revision/profile cho query/document, 384 chiều, L2, prefix query:/passage:,
  float32 little-endian BLOB 1.536 bytes. Chunk 320 token, overlap48, tối đa512 token
  kể cả prefix/special. Không âm thầm truncate query; vượt token budget trả 422.
- Chỉ một bộ text/chunks hiện hành; hash/profile + staging + transaction ngắn đủ giữ
  bản cũ khi lỗi. Upload origin UUID độc lập hash, URN theo origin_id, URL unique chỉ cho
  origin_kind=web; nhiều xuất xứ cùng content/context dùng chung document. Giữ origins,
  snapshot citation vì cần nguồn và lịch sử. Disable giữ enabled=false qua crawl;
  delete xóa thật/cascade và có thể crawl lại, không giữ dấu chặn.
- Gemini diễn giải mô tả qua answer/evidence_ids. Backend validate ID/nguồn, prompt grounding,
  kiểm mẫu hallucination; số quan trọng đi template trích native context, không model tự tạo.
  Guard cho năm/mã ngành/tên chương trình chứa số khớp vai trò/nguồn được trích;
  không chặn mọi chữ số/từ khóa hoặc cho số định lượng lọt nhờ trùng mã ngành.
  Không cố chứng minh ngữ nghĩa từng câu bằng parser.
- Quiz chỉ10 câu tính cách/sở thích/phong cách; direction positive/negative/none,
  trung bình contribution thuận=(a-1)/4, nghịch=(5-a)/4; none không vào mẫu số.
  Catalogue/mapping do dự án biên soạn từ nguồn chính thức, công bố là quy tắc tham khảo.
- Career mapping ngành → nhóm nghề trên catalogue, job → một nhóm hoặc null;
  nguồn đọc từ origin. Không liên kết evidence từng cặp ngành/job.
- Chat có một asyncio.timeout_at(expires_at) tổng60s; CPU qua to_thread chỉ trả dữ liệu, handler duy nhất
  lưu message sau kiểm deadline/session/nguồn. Không hủy CPU hoặc lưu kết quả muộn.
- Một process/worker và run lock trong RAM đủ cho local; không hỗ trợ nhiều backend cùng DB.
  Scheduler không chạy bù ngày máy tắt; busy00:00 ghi skipped_busy và bỏ lượt,
  không tự chạy sau khi rảnh hoặc restart. Manual “Crawl ngay” chung pipeline, không reset cron; stop sau item/rerun mới.

## Giai đoạn và checkpoint

| Chặng | Kết quả | Chỉ nghiệm thu khi |
| --- | --- | --- |
| A — Setup/database/auth | Manifest lock, config, DB, auth/RBAC | Unit + API auth và bảo mật cơ bản pass |
| B — Tài liệu/crawler | Metadata, origins, upload, UTC/PDF/OCR, run log | Test extraction/permission/dedup pass; API có thể dùng indexer stub |
| C — Embedding/retrieval | Chunks BLOB CPU, incremental publish, source API | E5 smoke + unit vector + integration ingestion/retrieval pass |
| D — Chat/history | Scope/evidence/Gemini, errors, owner history | Fake Gemini contract/core integration và nguồn/owner/security pass |
| E — Career/quiz | Import/jobs, catalogue/10 câu/scoring/filter | Unit từng service trước; integration jobs major filter sau catalogue sẵn sàng |
| F — Scheduler | Midnight/stop/rerun/restart | Coordinator + ingestion thật (fixture), fake clock integration pass |
| G — Frontend | Dashboard và hành trình đúng quyền | API theo contract; build + kiểm tay responsive/state pass |
| H — Demo | Core integration, manifest, README | Đạt SC-010: nguồn UTC, >=3 ngành, nghề nghiệp và các hành trình thành công; thiếu vẫn ghi thật nhưng không đạt demo chính |

Contract tests được viết với mock/stub trước dependency. Không gọi chúng là nghiệm thu
integration. Không đòi chức năng chưa xây ở checkpoint trước.
[Tasks](tasks.md) định nghĩa thứ tự ID và dependency cụ thể; [testing](testing.md) là pass/fail.
Mỗi FR/SC có coverage trong tasks, không cố giữ số lượng task cũ.

## Kiểm tra hiến chương

16/16 nguyên tắc được giữ: đơn giản/local/tách FE-BE; Gemini sinh và embedding local;
phạm vi/xã giao/không đoán số/có nguồn; xuất xứ/incremental; auth/secret; không mở rộng
công nghệ; acceptance tests/missing data; quyền thu thập. Không sửa constitution.
Dữ liệu thật chưa có phải hiện thiếu; fixture không được trình bày như thông tin UTC chính thức.

Crawl job thủ công/lịch dùng cùng coordinator. Scheduled busy ghi terminal skipped_busy trong crawl_runs,
không khởi ingestion; ngày sau cron00:00 vẫn chạy. Job count theo source+business identity,
không theo nội dung/document; CSV/JSON mỗi dòng chỉ rõ nguồn xuất bản hợp lệ.
