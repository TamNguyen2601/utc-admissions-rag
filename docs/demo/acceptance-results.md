# Kết quả nghiệm thu thực tế

**Hiện tại: T001–T024 PASS đến checkpoint B2 với fixtures offline/indexer fake,
đã bổ sung smoke OCR Tesseract thật vie+eng.
Dừng sau T024; T025+ chưa triển khai. Demo/RAG: NOT READY.**
Bản ghi T020–T024 ở cuối file là kết quả mới nhất. Các phần trước là lịch sử
nghiệm thu, giữ nguyên các giới hạn tại thời điểm chạy.

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

## Bản ghi T008–T012 — Authentication / Checkpoint A

Ngày: **2026-11-13**, múi giờ **Asia/Ho_Chi_Minh (UTC+07:00)**.
Chỉ triển khai T008–T012, không commit/push/merge, không tạo tài khoản demo thật.
Người dùng đã đồng ý tiếp tục dù 5 checklist trước demo chưa đánh dấu;
không sửa checklist. Không có `.specify/extensions.yml`, không có pre/post hook.

| Task | Kết quả thực tế |
| --- | --- |
| T008 | PASS: users email unique, role USER/ADMIN có DB constraint, auth_sessions FK/UTC/revoked_at; init/reopen không mất dữ liệu. Không lưu raw password/JWT. |
| T009 | PASS: Argon2id verify đúng/sai; JWT HS256 sub/sid/iat/exp/iss/aud, 1800 giây. Từ chối chữ ký/algorithm/claims sai, hết hạn, revoked và session DB không hợp lệ. |
| T010 | PASS: Guest401, USER403, ADMIN200 trên route probe quản trị; role/active đọc DB; invalid Authorization không downgrade Guest. Owner khác404 kể cả ADMIN. |
| T011 | PASS: register201 luôn USER, extra role422, duplicate409; login200, me200, logout204 revoke riêng sid. CLI prompt password không echo, từ chối terminal không bảo đảm ẩn password, không hardcode account hoặc nâng quyền tài khoản đã tồn tại. |
| T012 | PASS: auth contract + integration thật dùng SQLite file tạm/Argon2id/PyJWT; Guest/2USER/ADMIN, token giả/hết hạn/revoked/inactive, session qua reopen, không lộ password/token/key trong lỗi/log. |

Lệnh kiểm thử từ `backend/`:

```powershell
uv run --locked pytest -q
```

Kết quả cuối: **133 passed in 36.99s** (toàn bộ smoke/Foundation/auth, offline).
Contract được viết/chạy trước implementation: 20 test ban đầu fail404 đúng vì chưa có routes,
sau triển khai 20 pass. Lượt toàn suite đầu gặp trùng tên module test; đã thêm package
contract/integration. Lượt sau 128 pass/2 fail do assertion T007 giả định chưa có domain tables;
đã cập nhật assertion đúng schema identity, giữ kiểm tra fixture isolation và Foundation.
Kết quả cuối gồm thêm kiểm tra Bearer sai trên register/login và revoke qua reopen DB.

API hiện có thêm dưới `/api/v1`:

| Method/path | Thành công | Quyền |
| --- | --- | --- |
| POST /auth/register | 201 `{id,email,role}` | Public; role luôn USER |
| POST /auth/login | 200 `{access_token,token_type,expires_in,user}` | Public; JSON email/password |
| GET /auth/me | 200 `{id,email,role}` | Bearer hợp lệ |
| POST /auth/logout | 204, body rỗng | Bearer hợp lệ, revoke sid |

Login sai trả401 `INVALID_CREDENTIALS` chung, các401 có `WWW-Authenticate: Bearer`.
Email trim/lowercase; password8..128, không trim password. JWT30 phút, không refresh token.

Tạo Admin bằng terminal từ `backend/`, cấu hình `.env` riêng trước, backend dừng:

```powershell
uv run --locked python -m app.cli.init_db
uv run --locked python -m app.cli.create_admin
```

CLI hỏi email/password riêng, không cần truyền password trên command line.
Tests CLI dùng prompt giả lập và DB tạm, không tạo Admin trong DB demo.
Tests RBAC/owner dùng route `/test/*` chỉ gắn trên app kiểm thử, không thêm API quản trị
hoặc module hội thoại trước dependency. Nghiệm thu owner hội thoại thật vẫn ở T037.

Files chính: `app/models/identity.py`, `app/core/security.py`, `app/services/auth.py`,
`app/api/deps.py`, `app/schemas/auth.py`, `app/api/routes/auth.py`, `app/cli/create_admin.py`;
nối router/error envelope/model registration vào Foundation. Tests mới:
`tests/contract/test_auth.py`, `tests/integration/test_auth.py`; cập nhật hai assertion Foundation.
Dependencies/lockfiles giữ nguyên. Ignore hiện có bao phủ Python/Node/env/data/cache;
không có Docker/lint/publish/infra cần ignore riêng.

**Dừng sau T012. Checkpoint A: PASS. T013–T070 chưa triển khai. Demo: NOT READY.**

## Bản ghi T013–T019 — Documents / Checkpoint B1

Ngày: **2026-11-13**, múi giờ **Asia/Ho_Chi_Minh (UTC+07:00)**.
Phạm vi lần triển khai này chỉ T013–T019. Người dùng đã xác nhận tiếp tục dù checklist
trước demo còn 5 mục chưa đánh dấu; checklist giữ nguyên. Đã đọc Constitution, Spec,
Plan, Architecture, Data Model, REST, Tasks, Testing, Research và Quickstart.
Không có `.specify/extensions.yml` ở lần kiểm tra trước/sau, không có hook cần chạy.
Ignore hiện có đáp ứng Python/Node/env/data/cache; không thêm dependencies/lockfiles,
Docker, công cụ lint, npm publish hoặc hạ tầng mới.

| Task | Kết quả thực tế tại checkpoint B1 |
| --- | --- |
| T013 | PASS: data_sources/documents/document_origins, SHA256 raw/text, context ổn định có marker null; hash/context partial unique, URL unique riêng web, nhiều upload origins UUID độc lập và note riêng. FK source RESTRICT, document→origins CASCADE. Chỉ kiểm bảng đã có, không đòi đủ13bảng. |
| T014 | PASS: crawl_runs/crawl_run_items, enum/counts/item_index constraints, URL trùng/null vẫn có log riêng. skipped_busy chỉ scheduled, started_at null, ended_at=created_at, counts0/source_outcomes=[], DB trigger chặn items. Run delete cascade items; document delete SET NULL trên item. |
| T015 | PASS: một slot active_run_id với mutex ngắn; pipeline ngoài mutex. Event giữ pipeline, manual/upload busy409 không tạo run, scheduled busy ghi terminal ngay. Nhả slot khi hoàn tất/lỗi/stop; không chạy lại lượt đã bỏ, kể cả khi gọi execute với ID skipped_busy. Lỗi source dùng field status theo REST. Chưa tạo scheduler/run routes của T049–T051. |
| T016 | PASS: source registry unknown/allowed/denied, reuse_basis/checked_at, robots/terms cho web, interval>=2. HTTPS/host/path allowlist, bỏ fragment/tracking nhưng giữ query năm; kiểm private IP qua DNS giả lập và URL redirect đích. career/upload/catalog import-only. Chưa có HTTP fetch/adapter thật; transport, redirect loop và thực thi robots/rate thuộc T020+. |
| T017 | PASS với indexer stub: nhận upload, chuẩn hóa note NFC/trim, dedup text/context/profile, giữ origins/note đầu, thay đổi context tách doc, unchanged gọi index0. Disabled giữ flag qua reuse/update/split, collision với doc enabled bỏ qua DISABLED_DUPLICATE. Update lỗi giữ bản ready cũ; nguồn mất quyền lúc staging không publish; document bị xóa lúc staging không tái tạo. Enable chỉ ready và indexer xác nhận usable; delete xóa document/origins/file thật, không lưu dấu chặn. |
| T018 | PASS contract: Admin source create/list/patch và document upload/list/search/filter/detail/original/disable/enable/delete. Upload202 receipt có run_id/origin_id/document_id và Location; file lưu bằng UUID, tên client không quyết định đường dẫn. Guest401/USER403, original chỉ Admin. Public source hiện trả410 cho document tồn tại và404 nếu đã xóa; không công bố note/file path/stub text. Implementation excerpts đầy đủ vẫn ở T028. |
| T019 | PASS: contract-stub dùng SQLite file tạm, reopen engine giữ origins/notes; note1/2000 và quá2000/rỗng, cùng bytes/URL khác note/context, partial unique web; 20MiB được nhận, 20MiB+1 bị413, MIME/magic sai415; schema extra/duplicate multipart422; RBAC và privacy. Không có dữ liệu UTC thật trong fixture. |

Lệnh chạy từ `backend/` (Python3.13, uv/lockfile hiện có):

```powershell
uv run --locked pytest -q
```

**Kết quả cuối: 188 passed in 24.25s**, toàn suite backend mặc định offline
(smoke setup/Foundation/auth và unit/contract B1). `git diff --check` PASS.
Lượt đầu test database fail collection vì model chưa tồn tại; sau implementation pass.
Contract source list ban đầu lệch định dạng timestamp, đã dùng response DTO thống nhất.
Lượt toàn suite đầu có 2 failure do Foundation giả định chỉ có hai bảng auth; đã cập nhật
hai assertion để kiểm đúng **7 bảng hiện hành**, giữ kiểm tra fixture isolation và health
embedding_ready=false. Các lượt cuối không còn failure.

Indexer test nằm tại `tests/contract/knowledge_support.py`, ghi nhãn
**GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC**; không tải/gọi E5, OCR, Gemini hoặc website thật.
`DocumentService.indexer` là điểm tiêm stub; stub chỉ cho phép nghiệm thu contract và
quy tắc quản lý dữ liệu. Ứng dụng mặc định không gắn indexer: upload được lưu ở **pending**,
quality_reason/item reason **INDEXER_NOT_IMPLEMENTED**, item skipped, content_hash và
index_profile null. HTTP202 chỉ xác nhận tiếp nhận, không xác nhận đã index hoặc dùng RAG.
Receipt có thể chứa ID document pending đã được merge; kết quả liên kết đọc theo origin/run item.
API đọc runs/items/polling vẫn chưa triển khai (T049); không gọi chúng là API đã hoạt động.

Disable giữ dữ liệu và enabled=false. Delete xóa thật tài liệu và file/origins; nếu nguồn
website còn tài liệu, một lượt crawl mới sau khi crawler được triển khai **có thể nhập lại**.
Không có blacklist/blocklist hoặc record ngăn tái nhập. Chunks/jobs/majors chưa tồn tại;
cascade toàn hệ thống và source excerpts sẽ nghiệm thu ở các checkpoint sau dependency.
Không tuyên bố đã nghiệm thu ingestion→embedding→retrieval hoặc RAG thật.

**Dừng sau T019. Checkpoint B1: PASS (indexer stub). T020–T070 chưa triển khai.
Demo/RAG: NOT READY. Không commit/push/merge.**

## Bản ghi T020–T024 — checkpoint B2

Ngày **2026-11-13**, Asia/Ho_Chi_Minh. Phạm vi chỉ T020–T024; đã đọc source,
spec/plan/architecture/data-model/testing/contracts/research/quickstart và constitution.
Checklist requirements.md có 30/35 checked, 5 unchecked; người dùng đã xác nhận
tiếp tục. Không sửa checklist. Không có `.specify/extensions.yml` ở bước kiểm tra
trước/sau, không có hook để dispatch. Ignore hiện có đáp ứng stack; không thêm
dependency, không sửa lockfile/schema, không triển khai embedding T025 trở đi.

| Task | Kết quả thực tế |
| --- | --- |
| T020 | PASS offline: UTC discovery HTML/phân trang/attachment có scope HTTPS/canonical, giữ query năm và bỏ tracking. Kiểm quyền trước DNS/fetch và sau chờ rate; robots trước discovery và trước mọi redirect. Requests timeout connect/read `(5,20)`, không auto redirect/retry/proxy/netrc; pin IP public đã kiểm nhưng giữ TLS hostname/SNI. Rate theo host >=2s, tôn trọng registry/robots crawl-delay/request-rate. 403/CAPTCHA dừng, 429 lưu retry_not_before theo giây/HTTP-date hoặc 15 phút mặc định; nguồn độc lập vẫn tiếp tục. HTTP header không phân biệt hoa/thường; octet-stream attachment kiểm magic. |
| T021 | PASS: BeautifulSoup bỏ menu/script, HTML table giữ header trên từng dòng; TXT UTF-8/BOM/NFC; PyMuPDF native theo trang và bảng. Trả pages gồm text/page/section/extraction_kind/numeric_eligible cho index boundary. PDF hỏng/mật khẩu/quá200 trang, bảng số thiếu header và HTML error page có reason, không index nội dung lỗi. Không suy năm từ title/ngày đăng. |
| T022 | PASS bằng subprocess fake: Tesseract CLI vie+eng/TSV, confidence mean >=90, >=30 ký tự không trắng/trang, timeout <=60s/page và remaining budget <=300s/item. Scan/ảnh fallback; một trang lỗi làm cả tài liệu không được publish. Thiếu binary/tessdata, timeout, confidence thấp có reason/quarantine. Mọi OCR numeric_eligible=false, kể cả đạt gate; không sửa chữ số. |
| T023 | PASS với indexer spy: raw bytes/context/profile không đổi bỏ extraction và index; raw khác nhưng normalized text/context/profile giống thì index0. Profile đổi xử lý lại; khác context không gộp. Upload UUID/note độc lập, lookup web chỉ origin_kind=web. Origin thay nội dung tách khỏi origins còn dẫn bản cũ. Staging lỗi giữ text/hash/state ready và liên kết cũ, ghi last_update_error; cập nhật/split giữ enabled=false; DISABLED_DUPLICATE không chuyển origin sang document enabled. |
| T024 | PASS: unit/integration offline dùng SQLite tạm, HTTP/DNS/Tesseract giả lập, BS4/PyMuPDF thật và indexer fake. Kiểm H1 với extraction thật: cùng bytes/URL và nhiều note giữ origin riêng, cùng context dùng chung doc/index0, khác năm tách doc. Kiểm counters 1new/1updated/1skipped/1error, nguồn lỗi/backoff không mất bản tốt, OCR update lỗi, native table/header/page, source revoke lúc chờ rate và coordinator skipped_busy trong lúc extraction chờ Event. |

Fixtures tại `backend/tests/fixtures/utc/`: HTML danh sách/phân trang/thông báo,
robots.txt, PDF native hai trang, PDF bảng có/thiếu header, PDF scan và PNG. Tất cả
được tạo offline, ghi nhãn **GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC**; script tái tạo
`tests/fixtures/build_ingestion.py`. Không đưa fixture vào data demo.

Lệnh thực tế từ `backend/`:

```powershell
uv run --locked --offline pytest -p no:cacheprovider tests/unit/test_crawl.py tests/unit/test_extraction.py tests/unit/test_ingestion.py tests/unit/test_coordinator.py tests/integration/test_utc_ingestion.py -q --tb=short
uv run --locked --offline pytest -p no:cacheprovider -q --tb=short
```

Kết quả tập trung: **44 passed in 1.08s** (gồm 3 test coordinator cũ).
Kết quả hồi quy cuối: **229 passed in 25.16s**, tăng 41 test so với B1.
`git diff --check`: PASS. Lượt TDD đầu chưa có module nên fail collection như dự kiến.
Pytest trong sandbox bị chặn thư mục Temp; đã chạy lại ngoài sandbox sau khi được
cho phép. Ba test integration ban đầu dùng hai monotonic clock khác nhau nên lỗi
deadline; đã đồng bộ fake clock ở transport/extractor, các lượt cuối đều pass.

`Get-Command tesseract` không tìm thấy executable trong PATH. **Chưa chạy smoke
Tesseract vie+eng thật**; subprocess/TSV được fake để suite offline. Không tải
tessdata, model E5 hay gọi Gemini. Không crawl/DNS website thật và không thay đổi
quyền nguồn thật. Test transport kiểm pinning/TLS configuration, không phải live TLS smoke.

Ứng dụng có extractor thật được inject vào DocumentService nhưng vẫn **không có
indexer production**: upload mặc định pending/INDEXER_NOT_IMPLEMENTED, không tuyên bố
đã index/RAG. CrawlService là service gọi tường minh, chưa gắn scheduler hoặc API
Crawl ngay (tasks sau); không tự chạy ở startup. Pages hiện là đầu ra extraction
cho boundary indexing; document_chunks/storage/vector/retrieval thuộc T025–T029.

**Dừng sau T024. Checkpoint B2 PASS với fake indexing. T025–T070 còn chưa triển khai.
Demo/RAG NOT READY. Không commit/push/merge.**

## Bổ sung nghiệm thu T024 — Tesseract thật

Ngày **2026-11-13**, Asia/Ho_Chi_Minh. Bản ghi này cập nhật giới hạn “chưa chạy
smoke Tesseract thật” ở phần B2 phía trên; không thay kết quả lịch sử.

- Đã kiểm executable Tesseract **v5.5.3.20260724**, Leptonica1.87.0, đủ `eng`, `vie`
  (máy còn có `osd`). Đã cấu hình đường dẫn đầy đủ executable/tessdata trong
  `backend/.env` local, file vẫn được Git ignore. Không ghi JWT/key vào báo cáo.
- `get_settings()` + `probe_ocr()` với cấu hình local thực tế trả **ocr_available=true**.
- Smoke gọi subprocess Tesseract thật qua `Extractor`, giữ gate confidence>=90,
  >=30 ký tự không trắng, timeout60s/page và budget300s/item; không đổi ngưỡng.
- Không truy cập mạng/website thật, không tải dữ liệu hoặc model, không ghi kho demo.
  Fixtures tiếng Việt được tạo trong RAM bằng Arial trên Windows; Tesseract đọc ảnh
  tạm local. Indexing/RAG vẫn chưa có production implementation theo phạm vi B2.

Lệnh tái lập từ `backend/`:

```powershell
uv run --locked --offline python tests/smoke/check_ocr.py --output tests/smoke/ocr-local.json
```

| Fixture tự tạo | Kết quả | Thông tin thực tế |
| --- | --- | --- |
| PDF native tiếng Việt | PASS | native, numeric_eligible=true,108 ký tự không trắng; không gọi OCR |
| PNG tiếng Việt rõ nét | PASS | OCR thật, confidence mean95,6152;108 ký tự; numeric_eligible=false;0,348s |
| PDF scan tiếng Việt | PASS | OCR thật, confidence mean95,5295;108 ký tự; numeric_eligible=false;0,352s |
| PNG trống | PASS | OCR_LOW_QUALITY, quarantined=true, không dùng làm evidence |

**Smoke: 4/4 PASS.** Artifact: `backend/tests/smoke/ocr-local.json`.
Hồi quy sau khi cấu hình Tesseract thật:
`uv run --locked --offline pytest -p no:cacheprovider -q --tb=short`
→ **229 passed in 53.61s**. `git diff --check`: PASS.
Khẳng định đọc đúng chuỗi tiếng Việt trong PNG/PDF scan được kiểm bằng assertion.
PNG nhỏ `tests/fixtures/utc/image.png` ở bộ fixture cũ được kiểm thêm và bị
OCR_LOW_QUALITY; PDF scan cũ đọc được, numeric_eligible=false. Giữ kết quả cách ly
ảnh chất lượng thấp, không hạ gate để ép ảnh đó đạt.

Lượt smoke đầu trong sandbox bị chặn quyền thư mục Temp; đã được phép chạy lại
ngoài sandbox và tất cả ca smoke ở trên hoàn tất. Không có extension hook được
đăng ký (`.specify/extensions.yml` không tồn tại). Checklist giữ nguyên theo lần
chấp thuận trước; T025 trở đi chưa triển khai. Không commit/push/merge.

## Nghiệm thu T025–T029 — checkpoint C

Ngày **2026-11-13**, Asia/Ho_Chi_Minh. Phạm vi chỉ T025–T029. Phần này cập nhật
trạng thái B2 phía trên; các bản ghi cũ giữ nguyên như bằng chứng lịch sử.
Đã đọc skill speckit-implement, spec/plan/data-model/research/architecture/tasks/
testing/REST/constitution/quickstart và source. Checklist 30/35 đã checked, 5 mục
cổng demo còn trống; người dùng đã xác nhận tiếp tục. Không sửa checklist.
Không có `.specify/extensions.yml` trước/sau triển khai, không có hook để dispatch.
Ignore đã kiểm theo stack; thêm `.vscode/`. Không thêm dependency/đổi lockfile.

| Task | Kết quả thực tế |
| --- | --- |
| T025 | PASS: thêm `document_chunks`, FK cascade, unique doc/ordinal, dim384, BLOB thật1536bytes, page>=1, native/ocr và OCR numeric=false. Chia cửa sổ tối đa320 token bằng offset tokenizer, overlap48 cho phần thân, không trộn trang/section. Lặp lại cây header và điều kiện trước từng dòng bảng; header được tính trong320, kiểm lại passage+special<=512. Dòng bảng giữ nguyên; dòng/header quá dài bị từ chối an toàn. Snapshot có origin/URL/title/source/context/page/section, không note riêng. |
| T026 | PASS: singleton theo model/revision/cache, chỉ CPU, cache-only, không tải tự động; revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`. Cấu hình model/revision được chụp cố định trong encoder. Prefix `passage:`/`query:`, khóa chung cho tokenizer/encode, L2 và little-endian float32. Từ chối dim/NaN/Inf/zero norm sai. Không truncate query; quá512 gồm prefix/special trả422 `QUERY_TOO_LONG`. Health embedding_ready=true sau khi model đã load. |
| T027 | PASS: extraction/chunk/embed ngoài khóa và transaction publish; thay text/hash/profile/chunks trong transaction ngắn có rollback. Kiểm lại document/origin hiện hành, quyền/scope nguồn và enabled. Encode lỗi hoặc insert chunks lỗi giữ đúng BLOB/hash/text ready cũ. Disable giữa staging vẫn false; delete giữa staging trả DOCUMENT_REMOVED và không tái tạo trong item cũ. Dedup nguyên profile encode0; profile đổi reindex; split/merge và DISABLED_DUPLICATE giữ disable. Upload/crawl dùng DocumentService và coordinator hiện có. |
| T028 | PASS: NumPy cosine top5, threshold từ RETRIEVAL_MIN_SIMILARITY mặc định0,75; lọc profile chính xác, ready/enabled, 4 trường context, origin active và nguồn usable/scope hiện hành. Không cache vectors. Query encode ngoài khóa; kiểm DB sau encode nên disable trong query loại tài liệu ngay. Snapshot available kiểm doc/chunk/hash/nguồn hiện hành. GET /api/v1/documents/{id}/source có response schema đóng, origins/excerpts và filter page;410 unavailable,404 deleted; không private note/file path. |
| T029 | PASS: integration SQLite file tạm, service thật + encoder xác định được; API upload202→coordinator→chunks→retrieval/source, nhiều notes/context/dedup và reopen DB. Có1new/1updated/1skipped/1error qua crawler fixture với indexer thật; reindex/rollback/restart/disable/enable/delete/recrawl, nguồn mất quyền, native page/header và OCR numeric=false đều kiểm. E5 CPU thật chạy riêng như bên dưới. |

Các unit/integration dùng HTTP/OCR/encoder giả lập được ghi nhãn rõ, không phải
live UTC hoặc live OCR smoke. Hai fixture PDF bảng bị lỗi zlib đã tái tạo bằng
script sẵn có; thêm `.gitattributes` binary để tránh CRLF làm hỏng PDF stream.
Schema init vẫn chỉ tạo bảng thiếu; không reset DB hiện có hoặc sửa DB demo.

Lệnh thực tế từ `backend/`:

```powershell
uv run --locked --offline pytest -q --tb=short
uv run --locked --offline python tests/smoke/check_knowledge_e5.py --output tests/smoke/knowledge-e5-local.json
```

Hồi quy cuối: **254 passed in 26.02s** (229 test cũ +25 ca mới).
`git diff --check`: PASS.
E5 CPU smoke: **PASS**, exit0; artifact [knowledge-e5-local.json](../../backend/tests/smoke/knowledge-e5-local.json).
Lượt TDD đầu fail collection do chưa có chunking/retrieval, sau đó triển khai và
chạy lại. Lượt smoke đầu hoàn tất assertions nhưng print tiếng Việt lỗi cp1252;
đã sửa stdout dùng JSON ASCII, artifact vẫn UTF-8, các lượt sau exit0.
uv cache/Temp bị sandbox chặn; các lệnh test/smoke đã chạy lại với quyền được cấp.

| E5 CPU thật, cache local | Đo trên bản mã đã có khóa tokenizer/profile |
| --- | --- |
| Runtime | Python3.13.16; torch2.15.0+cpu; Intel64 Family6 Model154 Stepping3;20 logical CPU; torch14 threads |
| Load model từ cache | 5,5196s, gồm import sentence-transformers; không gồm import torch đầu process |
| Ingestion tài liệu đầu sau load | 37,1ms |
| Retrieval warm, cùng câu hỏi10 lần | p50 **12,431ms**; p95 **16,211ms**; max **17,224ms** |
| Kho đo latency | 3 đoạn tiếng Việt giả lập, 3 tài liệu; query encode + đọc/filter SQLite + NumPy cosine |
| Boundary bằng tokenizer E5 thật | 7 chunks; max nội dung320 tokens; max324 kể cả passage/special;384 chiều, L2, float32, BLOB1536bytes |
| Lifecycle bằng E5 thật | unchanged/dedup encode0, profile reindex, embedding update lỗi giữ bản cũ, disable→update→restart, enable, delete và recrawl; context/source filter và query quá dài422 |

Giới hạn: đây là benchmark kho nhỏ/cùng câu hỏi, không phải tải lớn hoặc latency
chat end-to-end. Threshold0,75 giữ nguyên cấu hình khởi đầu, **chưa hiệu chỉnh**:
đoạn đúng chủ đề cosine0,856562 nhưng hai đoạn ít liên quan vẫn đạt0,836389 và
0,834163, cùng vượt ngưỡng. Cosine không là xác suất hoặc đủ chứng minh evidence.
Chưa triển khai evidence gate/Gemini/chat của T030 trở đi; không tuyên bố RAG
trả lời hoàn chỉnh hoặc SC-010/demo đã đạt. Một backend process/worker; scan vectors
NumPy tuyến tính, staging trong RAM; không benchmark kho lớn/multi-process.
Mô hình thiếu cache sẽ thất bại an toàn, không tự dùng mạng/model khác. Bảng/header
vượt budget bị từ chối thay vì cắt mất điều kiện. Cần reindex dữ liệu có profile cũ
(extraction_version hiện là utc-c-2); retrieval loại profile cũ cho đến khi index lại.

**T025–T029 đã đánh [X]. Checkpoint C PASS. T030–T070 giữ nguyên chưa triển khai.
Không Gemini embedding, không dịch vụ vector ngoài, không commit/push/merge.**

## Checkpoint D1 — T030–T034: Gemini RAG chatbot

Ngày **2026-11-13**, Asia/Ho_Chi_Minh. Chỉ triển khai T030–T034; dừng trước
T035, không tạo bảng/API hay lưu lịch sử hội thoại. Bản ghi này cập nhật trạng
thái checkpoint C ở trên; giữ nguyên các kết quả trước đó làm bằng chứng lịch sử.
Checklist requirements 30/35 checked, 5 mục trước demo còn trống; người dùng đã
xác nhận tiếp tục. Không sửa checklist. Đã đọc Spec Kit/constitution/contracts,
skill speckit-implement và retrieval hiện hành. Không có `.specify/extensions.yml`
ở cả bước trước và sau triển khai, không có hook để dispatch. Ignore đã kiểm theo
stack Python/Node hiện tại; không cần thêm Docker/linter/publish ignore. Không
thêm dependency hoặc đổi lockfile, không seed hay sửa DB/data thật.

| Task | Kết quả thực tế |
| --- | --- |
| T030 | PASS: schema đóng cho message/context/turns; trim/NFC, message 1–4000, tối đa10 turns/4000 mỗi tin/16000 tổng; reject extra/conversation_id, bool/string year và token query quá budget. Scope rules UTC, xã giao, ngoài phạm vi, hỗn hợp và mơ hồ; phần ngoài bị loại khỏi query Gemini. Trường khác không được coi là UTC dù có context. Có catalogue resolver injectable; mặc định chưa có catalogue thì nghề/ngành mơ hồ hỏi lại. Chỉ user turn thiết lập chủ thể, không dùng assistant/history làm evidence. |
| T031 | PASS: phân biệt kho local trống với kho có nhưng không đủ chứng cứ, kiểm liên quan từ vựng bổ sung cosine, context chính xác và các context chưa rõ, loại đoạn chứa chỉ dẫn injection nhận diện được. Numeric bypass Gemini: trích nguyên văn native/numeric_eligible kèm context, header/đơn vị/điều kiện; không lấy năm/mã làm giá trị đo; nhiều giá trị không xác định dòng thì từ chối, số khác nhau cùng context trả conflicting_sources có citations. OCR không trả số. H2 cho phép năm/mã ngành/tên DEMO2+2 đúng vai trò/cited source; giá trị điểm/phí/chỉ tiêu/ngày/count vẫn bị chặn dù trùng định danh. |
| T032 | PASS: google-genai async, model gemini-3.5-flash-lite theo Settings; một client lazy ở backend, attempts=1 ở client và mỗi call; không retry429/5xx/timeout, không fallback. System grounding, chỉ gửi query đã scope và evidence hợp lệ với ID request-local; không gửi turns/private notes/URL nguồn cho model. Structured output đóng answer/evidence_ids; timeout SDK tính bằng ms làm tròn xuống từ ngân sách còn lại. Lifecycle đóng client. Lỗi đã sanitize, không raw exception/key. |
| T033 | PASS: POST /api/v1/chat/guest trả đúng Reply/Citation/context đủ4khóa/request_id. Một asyncio.timeout_at(expires_at), mặc định tổng60s; retrieval CPU qua to_thread chỉ trả dữ liệu. Handler kiểm hạn sau retrieval/model và sau khi lấy khóa finalize; kiểm lại source/hash/chunk/current permissions và session bằng Session mới. Khóa finalize dùng chung với disable/delete/publish, không giữ qua network/CPU/await. Model/CPU muộn không trả200 hoặc tự lưu; không registry/hủy CPU. Guest không INSERT/UPDATE/DELETE; Bearer sai/revoked401, không downgrade Guest. |
| T034 | PASS D1: thêm127 ca unit/contract/integration/SDK transport xác định được. Có prompt injection, URL/evidence ID giả, JSON/extra/duplicate key/ID sai, missing/out-of-scope, H2 literal sourced và số bịa, native năm/cơ sở/phương thức/dòng/đơn vị/OCR, conflict, disable/delete/update/revoke source trong lúc Gemini chờ, session revoke, quota/key/SDK timeout/outer timeout, CPU muộn và model cố trả sau cancellation, chờ khóa finalize và Guest không ghi DB. Không tuyên bố đã kiểm persistence của T035–T037. |

Các mã lỗi HTTP đã kiểm:

| HTTP | Code | Kiểm thực tế |
| --- | --- | --- |
| 503 | GEMINI_CONFIGURATION_ERROR | Thiếu key qua API; SDK MockTransport400/401/403/404, không lộ thông tin upstream |
| 503 | GEMINI_QUOTA_EXCEEDED | SDK429 đúng1 request; contract error envelope |
| 503 | GEMINI_SERVICE_UNAVAILABLE | SDK500/503 và network error đúng1 request; contract error envelope |
| 504 | GEMINI_TIMEOUT | SDK httpx.ReadTimeout/504 đúng1 request, timeout riêng trước outer |
| 504 | REQUEST_DEADLINE_EXCEEDED | Budget hết khi CPU/model/finalize chờ; explicit final check chặn model trả sau cancellation |
| 422 | QUERY_TOO_LONG | Query E5 vượt512 token gồm prefix/special, không truncate |

Lệnh và kết quả cuối, trên dependencies đã lock:

```powershell
# backend/
uv run --locked --offline pytest -q --tb=short
# frontend/
npm run build
# repository root
git diff --check
```

- Backend: **381 passed in 30.25s** =254 ca cũ +127 ca mới. Bao gồm toàn bộ
  tests/unit, contract, integration và smoke/test_setup.py có SDK transport test;
  offline mặc định, SQLite/temp storage và encoder giả lập cách ly hoàn toàn data thật.
- Frontend: **PASS**, TypeScript + Vite7.3.8; 40 modules, build743ms sau tsc.
  Frontend hiện không có script test riêng; không triển khai UI chat của T055.
- `git diff --check`: PASS.
- TDD đầu fail collection vì chưa có app.schemas.chat, đúng trạng thái trước triển khai.
  Lượt đầu127ca thiết kế dần có2 lỗi: scope thiếu từ khóa công nghệ thông tin và
  fixture nhiều năm dùng cùng URL làm origin chuyển bản. Đã sửa rules/fixture,
  bổ sung guard/dòng native, các lượt cuối đều PASS. uv cache bị sandbox từ chối;
  Vite/esbuild spawn EPERM trong sandbox; đã chạy lại test/build bằng quyền được cấp.

Nguồn kỹ thuật SDK đã đối chiếu với bản lock và
[tài liệu chính thức google-genai](https://googleapis.github.io/python-genai/)
về structured output, HttpOptions và retry. Unit dùng **SDK thật + HTTP giả lập**;
integration dùng **ingestion/chunking/SQLite/retrieval/chat thật + encoder/Gemini giả lập**.
Không gọi Gemini live hoặc nạp key thật; chưa nghiệm thu quyền truy cập model bằng
key người dùng, narrative live, bộ30câu/golden review T064 hoặc latency10câu chat T065.
Không chạy lại smoke E5/OCR riêng; bằng chứng checkpoint C/B2 vẫn ở các mục trước.

Giới hạn: scope/overlap/injection/numeric rules bảo thủ, không là semantic claim parser
hay bảo đảm mọi diễn giải đều đúng; vẫn cần đọc nguồn/golden review. Tên/identifier
chỉ chấp nhận khi khớp cited evidence. Đường native từ chối khi không nhận diện được
giá trị/đơn vị/context/dòng, không tự đoán. COUNT việc làm chưa có service T038+ nên
không sinh số tin từ Gemini. Catalogue chưa có nên không tự tạo ngành/nghề liên quan.
Timeout có thể có overhead nhỏ của điều phối/DB kiểm cuối đồng bộ, không SLA thời gian
thực; kiểm hạn cuối không cho phép kết quả hết hạn thành200. Lịch sử/account persistence,
owner/conversation busy và atomic message pair dành cho T035–T037, chưa triển khai.

**T030–T034 đã đánh [X], checkpoint D1 PASS offline. T035–T070 giữ nguyên chưa làm.
Không tạo dữ liệu tuyển sinh cho database thật; không commit/push/merge. Demo SC-010
chưa đạt và Gemini live chưa nghiệm thu.**
