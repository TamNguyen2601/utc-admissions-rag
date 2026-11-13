# Kết quả nghiệm thu thực tế

**Hiện tại: T001–T007 PASS; dừng sau T007. T008+ chưa triển khai.**
Kết quả T004–T007 và cách chạy Foundation ở cuối file. Phần T001–T003 bên dưới
là bản ghi lịch sử của lượt trước; các giới hạn tại thời điểm đó được giữ nguyên.

## Bản ghi T001–T003

Ngày: **2026-11-13**, múi giờ **Asia/Ho_Chi_Minh (UTC+07:00)**.
Phạm vi: setup dependencies và smoke; chưa nghiệm thu ứng dụng hoặc SC-010 toàn bộ.
**T001–T003: PASS. Demo: NOT READY.** T004 trở đi chưa triển khai.
Không commit/push/merge, không đổi nhánh hoặc quyết định kiến trúc.

## Môi trường

- Windows x86_64, PowerShell; Python **3.13.16**, uv **0.13.7**.
- Node.js **24.22.1**, npm **11.19.1**.
- CPU **12th Gen Intel Core i7-12700H**, 14 cores / 20 logical processors.
- RAM **16.869.548.032 bytes**, khoảng 15,71 GiB.
- Backend `requires-python >=3.13,<3.14`, `.python-version=3.13`.
- Frontend `engines.node=24.22.1`, `.node-version=24.22.1`.
- Các phiên bản chính xác khóa trong `backend/uv.lock`, `frontend/package-lock.json`.
  Lock uv có 87 package entries (gồm biến thể theo nền tảng), Windows cài 84 packages.
- PyTorch trên Windows/Linux dùng index CPU riêng, không cài CUDA runtime.
  Manifest dùng stack theo plan; không thêm RAG framework, OCR wrapper, Recharts/shadcn.

## Kết quả theo task

| Task | Kết quả | Bằng chứng |
| --- | --- | --- |
| T001 | PASS | `uv lock` resolve thành công; Python3.13, CPU dependencies, APScheduler3.x, tzdata; actual versions bên dưới |
| T002 | PASS | React/TypeScript/Vite/Tailwind/Router/Axios; dev/build scripts; `npm ci` tái lập từ lock, 0 vulnerabilities |
| T003 | PASS | `uv sync --locked`; 28 dependency smoke pass; E5 tải đúng revision/CPU và chạy cache-only; `npm ci/build` pass; timezone và SDK timeout/retry kiểm thực tế |

## Actual versions

Tất cả dependencies Python dưới đây đã import thành công trong Python3.13.16:

| Dependency | Actual |
| --- | --- |
| FastAPI / Uvicorn | 0.162.5 / 0.54.0 |
| SQLAlchemy / Pydantic Settings | 2.1.8 / 2.16.2 |
| PyJWT | 2.15.1 |
| pwdlib / argon2-cffi | 0.3.1 / 25.1.0 |
| python-multipart | 0.0.33 |
| sentence-transformers / torch | 5.7.0 / 2.15.0+cpu |
| NumPy | 2.5.4 |
| google-genai | 1.75.0 |
| requests / beautifulsoup4 | 2.34.2 / 4.15.0 |
| PyMuPDF | 1.28.2 |
| APScheduler / tzdata | 3.11.3 / 2026.6 |
| Pytest / httpx | 9.2.0 / 0.28.1 |

Frontend `npm ls --depth=0` không thiếu/invalid dependency:

| Dependency | Actual |
| --- | --- |
| react / react-dom | 19.3.1 / 19.3.1 |
| react-router-dom / axios | 7.18.5 / 1.21.1 |
| vite / typescript | 7.3.8 / 5.9.3 |
| tailwindcss / @tailwindcss/vite | 4.3.5 / 4.3.5 |
| @vitejs/plugin-react | 5.2.0 |
| @types/node | 24.19.2 |
| @types/react / @types/react-dom | 19.3.0 / 19.3.0 |

## Lệnh đã thực hiện

Từ repository root, lần lượt đổi thư mục. Lệnh tải/cài cần mạng và quyền ghi cache;
smoke SDK không cần Gemini key. E5 bình thường cache-only, tải mạng phải bật `--download`.

```powershell
Set-Location backend
uv lock
uv sync --locked
uv run --locked pytest tests/smoke/test_setup.py -v -s
uv run --locked python tests/smoke/check_e5.py --resolve-revision
uv run --locked python tests/smoke/check_e5.py --download
uv run --locked python tests/smoke/check_e5.py
Set-Location ../frontend
npm install --package-lock-only --ignore-scripts
npm ci
npm ls --depth=0
npm run build
```

| Kiểm tra | Expected | Actual | Kết quả |
| --- | --- | --- | --- |
| `uv lock` | Resolve Python3.13/CPU, lưu phiên bản | Resolve 87 entries | PASS |
| `uv sync --locked` | Cài từ lock, không đổi phiên bản | Cài 84 packages | PASS |
| `pytest tests/smoke/test_setup.py -v -s` | Imports/CPU/timezone/SDK hoạt động | **28 passed in 19.04s** | PASS |
| E5 resolve revision | Commit thực từ Hugging Face | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | PASS |
| E5 `--download` | Tải đúng revision, CPU384/L2/float32 | 10 files, shape2x384, norms1/1; load+download+encodes67,153s | PASS |
| E5 cache-only | Load cùng revision, encode tiếng Việt, không tải lại | shape2x384, norms1/1, float32, BLOB1536; load+encodes2,043s | PASS |
| `npm ci` | Cài tái lập từ package-lock | Added114, audited121, 0 vulnerabilities | PASS |
| `npm ls --depth=0` | Dependency tree đầy đủ | Actual versions như bảng trên | PASS |
| `npm run build` | TypeScript + Vite production build | 40 modules; build769ms; có HTML/JS/CSS | PASS |

## Chi tiết dependency smoke

Đây là **dependency smoke**, không phải contract/integration ứng dụng. Gemini dùng
fixture **GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC**. E5 dùng chuỗi kiểm thử có nhãn,
không nhập dữ liệu demo hay gọi API embedding bên ngoài.

- 19 import checks, gồm Argon2 backend của pwdlib; Python đúng major/minor3.13.
- `torch.version.cuda is None`, CUDA unavailable; tensor CPU tính toán thành công.
- `ZoneInfo("Asia/Ho_Chi_Minh")` có offset+07:00 trên Windows với tzdata đã khóa.
  APScheduler `CronTrigger` trả `2026-11-14T00:00:00+07:00` rồi
  `2026-11-15T00:00:00+07:00`. Chưa triển khai scheduler/coordinator.
- Gọi **async generate_content** của google-genai thật qua `httpx.MockTransport`;
  `HttpRetryOptions(attempts=1)`, giữ model **gemini-3.5-flash-lite**.
  Thành công/401/403/429/503/ReadTimeout đều **đúng một request**.
- Per-call `HttpOptions(timeout=250)` xuất hiện tại transport dưới dạng **0,25s**,
  thay default client1s: SDK đã khóa hỗ trợ timeout theo ngân sách còn lại.
- HTTP server loopback thực giữ response: timeout per-call100ms ngắt SDK sau
  **0,113s**, một request, `httpx.TimeoutException`. Không gọi Google hay dùng key thật.

## E5 CPU và revision

- Model **intfloat/multilingual-e5-small**, revision
  **614241f622f53c4eeff9890bdc4f31cfecc418b3** lấy từ metadata thực tế.
- Pin tại `backend/tests/smoke/e5-model.json`; chưa tạo settings thuộc T004.
- Cache `backend/data/models/` được `.gitignore` loại trừ. Tải safetensors và các
  cấu hình/tokenizer/pooling cần thiết, không tải ONNX/OpenVINO hoặc weights.bin trùng.
- Model và parameter thực trên **cpu**; tiền tố **query:** / **passage:**.
- Hai vectors **384 chiều, float32, finite, L2=1**. Little-endian float32 BLOB
  **1.536 bytes**, roundtrip bằng vector gốc; repeat encode tương đương atol1e-6.
- Lượt cache-only dùng câu tiếng Việt có dấu; `local_files_only=True` cho cả
  snapshot và SentenceTransformer. Không gọi API tạo embedding bên ngoài.
- Đã thay alias `get_sentence_embedding_dimension` bị deprecation bằng
  `get_embedding_dimension`; chạy lại cache-only thành công.
- Các thời gian trên gồm load/encode; **không** phải phép đo10 câu warm RAG,
  chưa kiểm query budget/chunking/retrieval thuộc task sau.

## Lỗi đã gặp và xử lý

- Sandbox chặn uv cache (`Access is denied`) và npm registry/cache (`ENOTCACHED`):
  chạy lại với quyền được cấp; lock/sync/ci PASS, không đổi stack.
- Build đầu `spawn EPERM` khi esbuild tạo process: chạy lại với quyền được cấp,
  build PASS, không thay Vite để né lỗi.
- Lệnh Python inline lấy metadata lỗi quote PowerShell: chuyển sang script
  `check_e5.py --resolve-revision`, đọc revision thành công.
- npm cảnh báo esbuild postinstall chưa có allowScripts; build thực đã chạy
  esbuild thành công, không đổi policy cài scripts toàn máy.
- Hugging Face cảnh báo Windows thiếu symlink cache và tải không xác thực;
  tải và cache-only đều PASS. Có thể tốn thêm dung lượng/rate limit khi tải lại;
  không thay cấu hình OS hoặc yêu cầu token cho smoke này.

## Các mục checklist được kiểm chứng

Giữ nguyên **mọi marker** trong `specs/001-utc-admissions-chatbot/checklists/requirements.md`.
Người dùng đã cho phép bắt đầu T001–T003 dù 5 mục trước demo còn `[ ]`.

| Mục cổng trước demo | Bằng chứng hiện tại | Marker |
| --- | --- | --- |
| Lock + Python3.13/Node24.22.1/E5 CPU/Gemini retry control | Toàn bộ dependency smoke của mục này PASS như trên; Gemini live chưa gọi | Giữ `[ ]` theo phạm vi được yêu cầu |
| Dữ liệu UTC hợp lệ, >=3 ngành, >=1 tin nghề nghiệp | Chưa chuẩn bị dữ liệu/quyền demo | Giữ `[ ]` |
| Unit/contract/core integration/security | Mới dependency smoke, chưa có chức năng tương ứng | Giữ `[ ]` |
| Responsive/hành trình/latency/deadline/nguồn | Chưa có chức năng tương ứng | Giữ `[ ]` |
| README demo toàn hành trình/actual/manifest | Chưa có chức năng tương ứng | Giữ `[ ]` |

Coverage: **FR-035** trong phạm vi setup; phần môi trường/dependencies của
**FR-033/FR-036/SC-010**. Không tuyên bố hoàn tất các FR/SC này toàn bộ.

## Giới hạn và phần chưa kiểm chứng

- Không có lỗi chặn còn tồn tại cho **T001–T003**.
- Chưa gọi Gemini live: key/quota/quyền dùng model demo chưa kiểm chứng;
  không tự fallback model. T003 chỉ xác minh khả năng async/timeout/retry của SDK.
- Adapter lỗi HTTP503/504, outer deadline60s, persistence/late results và auth
  chưa được triển khai, chờ T032–T037/T065 và các dependency tương ứng.
- Frontend chỉ scaffold báo chức năng chưa sẵn sàng; chưa dashboard/API/responsive.
- T004–T070 chưa làm; dữ liệu demo, OCR binary, integration/security/performance và
  hành trình SC-010 chưa kiểm chứng. **Dừng sau T003**.

## File tạo/sửa

- Backend: `.python-version`, `pyproject.toml`, `uv.lock`;
  `tests/smoke/{test_setup.py,check_e5.py,e5-model.json}`.
- Frontend: `.node-version`, `package.json`, `package-lock.json`, `index.html`,
  `tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json`, `vite.config.ts`,
  `src/main.tsx`, `src/styles.css`.
- Báo cáo này và `specs/001-utc-admissions-chatbot/tasks.md`.
- `.gitignore` đã kiểm tra: env/venv/node_modules/dist/data/model cache được loại trừ,
  lockfiles được giữ; không cần sửa. Không Docker hoặc npm publishing nên không
  tạo `.dockerignore`/`.npmignore`.
- `.specify/extensions.yml` không tồn tại ở cả kiểm tra trước/sau; không có hook để chạy.

Tham khảo nguồn SDK chính thức khi chọn phép kiểm: [python-genai](https://github.com/googleapis/python-genai)
và [PyTorch CPU installation](https://pytorch.org/get-started/locally/).
Kết quả PASS dựa trên chạy bản đã khóa ở máy trên, không suy từ tài liệu.

## Nghiệm thu T004–T007 — 2026-11-13

Môi trường giữ nguyên Python3.13.16/uv0.13.7/Node24.22.1/npm11.19.1/Windows.
Không thêm dependency, đổi stack, model, nhánh hoặc commit/push/merge.
Checklist trước demo vẫn **30/35**, giữ nguyên cả5 mục `[ ]` theo xác nhận đã có.

### Kiểm tra trạng thái trước khi triển khai

- Source T001–T003 có manifest/lockfiles, scaffold và smoke tests đúng bản ghi trên.
- `uv run --locked pytest tests/smoke/test_setup.py -q`: **28 passed in 6.75s**.
- `npm run build`: **PASS**,40modules,716ms.
- Không chạy lại download E5: model/dependency/pin không đổi; bằng chứng CPU ở lượt trước.
- Không có `.specify/extensions.yml`; kiểm trước/sau không có hook cần chạy.

### Tasks và bằng chứng

| Task | Kết quả | Bằng chứng thực tế |
| --- | --- | --- |
| T004 | PASS | Settings đọc env/.env, secret bắt buộc >=32bytes, chặn cấu hình sai; Gemini key tùy chọn; paths tương đối backend; E5 CPU/pin; deadline/OCR/CORS; hai .env.example không có credentials |
| T005 | PASS | SQLite file với WAL/FK/busy_timeout5000 trên từng connection; init hai lần giữ dữ liệu, chỉ thêm bảng thiếu; session riêng/request và worker, rollback/close; UUID/timeUTC roundtrip |
| T006 | PASS | FastAPI lifespan/health/request ID, error envelope kể cả CORS lỗi và500; log JSON metadata không URL/body/header/raw exception; không scheduler/model load/chat |
| T007 | PASS | **50 Foundation tests** dùng SQLite tmp_path, fixture có nhãn, network ngoài loopback bị chặn, success/invalid config/FK/rollback/CORS/error/log pass |

`Base.metadata` tại T007 chưa có domain tables. Test FK/cascade/init dùng
`fixture_parents`/`fixture_children`/`fixture_added_later` trong metadata riêng và
SQLite tạm, không tạo bảng Authentication hoặc đủ13 bảng của checkpoint T062.
Startup và CLI chỉ tạo các bảng đã đăng ký còn thiếu, không drop/reset/seed dữ liệu.

### Kiểm thử cuối

| Lệnh / phép kiểm | Actual | Kết quả |
| --- | --- | --- |
| `uv sync --locked` | Resolve87 entries, check84 packages, không đổi dependencies/lock | PASS |
| `uv run --locked pytest -q` | **78 passed in 6.96s**:28 dependency smoke +50 Foundation | PASS |
| `npm run build` | TypeScript/Vite PASS,40modules,711ms | PASS |
| `uv run --locked python -m app.cli.init_db` hai lần | Hai lần in `Database initialized; existing data preserved.` | PASS |
| Uvicorn một worker, JWT sinh ngẫu nhiên tạm, Gemini key rỗng | Startup complete tại127.0.0.1:8000 | PASS |
| HTTP thật `GET /api/v1/health`, Origin localhost:5173 | HTTP200, response bên dưới, X-Request-ID hợp lệ và Allow-Origin đúng | PASS |
| Dừng Uvicorn bằng Ctrl+C | Application shutdown complete; không để backend thử nghiệm chạy | PASS |
| `git diff --check` và ignore runtime | Không lỗi whitespace; env/DB/WAL/SHM/cache/dist bị ignore, .env.example được giữ | PASS |

Response health thực:

```json
{"status":"ok","embedding_ready":false,"ocr_available":false,"gemini_configured":false}
```

Request ID thực: `d0419455-0c65-4b70-a1e9-e055d0a70046`.
`Access-Control-Allow-Origin: http://localhost:5173`.
Thiếu Gemini key không chặn startup. `embedding_ready=false` vì service embedding
chưa được triển khai, dù có cache model từ T003. `ocr_available=false` là trạng thái
probe máy thật; không giả là OCR đã cài hoặc đạt chất lượng trích xuất.

Test OCR availability dùng subprocess giả cho missing executable, thiếu vie/eng,
timeout và đủ ngôn ngữ. Không xây pipeline OCR. Fixture encoder/Gemini không thay
nghiệm thu service; không có gọi UTC/TopCV/Gemini thật trong pytest.

### Các nhánh Foundation đã kiểm

- Config: thiếu/blank/weak JWT bị chặn, secret không có trong repr/error text;
  env ưu tiên hơn .env; paths được neo backend; mẫu .env blank JWT phải được bổ sung
  secret sinh local; missing Gemini được chấp nhận. Sai database/CORS/model/device/
  revision/JWT algorithm/expiry/deadline/OCR giới hạn bị chặn.
- Database: PRAGMA trên hai physical connections và reopen; init lặp giữ row và thêm
  bảng mới; UUID riêng; datetime có timezone lưu UTC RFC3339 `Z`, từ chối naive;
  FK orphan insert bị chặn, cascade fixture đúng; rollback sau flush/lỗi và đóng
  session không commit; hai worker có Session riêng, không rò connection.
- FastAPI: health thiếu/có Gemini key, không lộ giá trị key/path; session dependency
  riêng mỗi request, lỗi500 rollback; middleware request ID tự sinh, không phản chiếu
  ID tùy ý từ client; không khởi scheduler/Gemini/E5.
- CORS: chỉ origin cấu hình được nhận Allow-Origin; origin khác/null không được cấp;
  preflight rejection có JSON envelope/content-length đúng; không wildcard credentials;
  lỗi500 vẫn có CORS cho origin được phép.
- Errors: malformed JSON, sai kiểu/extra fields422;404/405/401/403/500 synthetic
  có `{error:{code,message,details:null},request_id}`. HTTPException.detail/Pydantic
  input/raw exception không phản chiếu ra response;401 có WWW-Authenticate:Bearer.
  Đây là kiểm handler lỗi, **chưa** phải Authentication/RBAC.
- Log: chỉ event/request_id/method/status/duration_ms; bỏ message/traceback/path,
  Guest body/query, Authorization và client request ID. Tắt uvicorn.access vì log
  mặc định chứa URL/query. Đã kiểm trường hợp500 thực qua TestClient.
- Pytest mặc định chặn DNS/kết nối ngoài loopback; fixture ghi nhãn ở tests/fixtures,
  SQLite tmp_path ngoài kho runtime/demo. SDK smoke loopback T003 vẫn pass.

### Lỗi tìm thấy và đã sửa

Lượt Foundation đầu **49pass/1fail**: `Literal[30]` không parse chuỗi `"30"` từ
JWT_EXPIRE_MINUTES trong .env với bản Pydantic đã khóa. Đổi thành `int` có
`ge=30,le=30`: vẫn bắt buộc30phút và đọc env đúng. Sau sửa toàn bộ78tests PASS.
Không đổi dependency hoặc hạ Python. Không còn lỗi chặn T004–T007.

### File thêm/sửa trong lượt T004–T007

- `backend/.env.example`, `frontend/.env.example`.
- `backend/app/core/{config,errors,logging}.py`.
- `backend/app/db/{base,session}.py`, `backend/app/cli/init_db.py`.
- `backend/app/main.py`, `backend/app/api/router.py`, `backend/app/api/routes/health.py`.
- Các `__init__.py` cho package app/core/db/cli/api/routes và tests.
- `backend/tests/conftest.py`, `backend/tests/unit/test_foundation.py`,
  `backend/tests/fixtures/{foundation.json,README.md}`.
- `backend/pyproject.toml`: chỉ thêm cấu hình pytest pythonpath/testpaths;
  không thay danh sách dependencies hoặc uv.lock.
- `specs/001-utc-admissions-chatbot/tasks.md` và báo cáo này.
- `.gitignore` hiện có đã đủ secrets/runtime/DB/cache; đã kiểm, không cần sửa.
  Không sửa frontend source, package-lock hoặc bất kỳ checklist marker nào.

### Cách chạy phần đã có

Terminal backend, từ repository root (JWT sinh mới cho phiên shell này; không in
hoặc ghi secret vào source; để sử dụng lâu dài tự lưu riêng trong backend/.env):

```powershell
Set-Location backend
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
$env:JWT_SECRET = (uv run --locked python -c "import secrets; print(secrets.token_hex(32))")
uv run --locked python -m app.cli.init_db
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Không cần Gemini key để kiểm Foundation. Biến môi trường ưu tiên hơn .env.
Health: `http://127.0.0.1:8000/api/v1/health`. Không chạy backend thứ hai cùng DB.

Terminal frontend riêng, từ repository root:

```powershell
Set-Location frontend
npm ci
if (-not (Test-Path .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
npm run dev -- --host localhost
```

Mở `http://localhost:5173`; hiện vẫn là scaffold. Chưa có UI gọi API.
Mẫu frontend chỉ có VITE_API_BASE_URL, không có key/password/JWT secret.

### Phần còn lại

**Dừng sau T007.** T008+ chưa triển khai/đánh dấu, Checkpoint A chưa hoàn tất vì
Authentication chưa có. Chưa RAG/chat/crawler/scheduler/nguồn dữ liệu demo; chưa có
nghiệm thu đầy đủ security/integration/SC-010. Cả5 mục checklist trước demo giữ `[ ]`.
**Demo: NOT READY.**

Tham khảo thiết lập transaction/PRAGMA: [SQLAlchemy SQLite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).
Kết luận PASS dựa trên pytest và HTTP thực đã chạy ở trên.
