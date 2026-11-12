# Hướng dẫn chạy local (để triển khai)

Hiện repository có tài liệu thiết kế; các lệnh ứng dụng dưới đây chỉ chạy được sau
khi hoàn thành task tương ứng. Không coi đây là bằng chứng đã có source hoặc đã test.
Dùng Windows PowerShell, Python3.13, uv, Node.js24.22.1/npm.
Không Docker/deploy; một backend process/worker và một frontend.

## 1. Môi trường và dependencies

Từ thư mục repository hiện tại, kiểm:
```powershell
Get-Location
git branch --show-current
py -3.13 --version
uv --version
node --version
npm --version
```

Nhánh thực tế ở lần review là master; không đổi nhánh hoặc suy nhánh mặc định.
Backend quản lý bằng pyproject.toml + uv.lock, FE package.json + package-lock.json.
Người triển khai tạo lockfile ở task setup; người chạy dùng lock, không cài tay thư viện.
Chọn torch/sentence-transformers CPU tương thích Python3.13; ghi phiên bản/revision thật.
Nếu bộ đã lock không cài được thì báo task blocked, không tự đổi stack.

Sau khi có manifest/lock/source, terminal backend từ repository root:
```powershell
Set-Location backend
uv sync --locked
Copy-Item -LiteralPath .env.example -Destination .env
```

Chỉ copy khi chưa có .env riêng để không ghi đè cấu hình đã nhập.
Bản mẫu không chứa key/password thật. Cấu hình dự kiến (Settings validate):
- DATABASE_URL=sqlite:///./data/utc.db; paths tương đối từ backend/.
- JWT_SECRET đủ ngẫu nhiên >=32 bytes, JWT_ALGORITHM=HS256, JWT_EXPIRE_MINUTES=30,
  JWT_ISSUER=utc-admissions-local, JWT_AUDIENCE=utc-admissions-web.
- GEMINI_API_KEY nhập riêng local; GEMINI_MODEL=gemini-3.5-flash-lite.
  Thiếu key vẫn khởi động cho dữ liệu/quiz; chat cần Gemini báo503 cấu hình.
- EMBEDDING_MODEL=intfloat/multilingual-e5-small; EMBEDDING_REVISION dùng revision đã
  chốt tại setup; EMBEDDING_DEVICE=cpu, MODEL_CACHE_DIR=./data/models.
- RETRIEVAL_MIN_SIMILARITY=0.75 (hiệu chỉnh/ghi lại), CORS_ORIGINS chỉ localhost:5173.
- TESSERACT_CMD đường dẫn executable nếu không trong PATH, TESSDATA_PREFIX nếu cần.
- CHAT_DEADLINE_SECONDS=60. Không biến VITE nào được chứa Gemini key/JWT secret.

Lần đầu model local có thể cần mạng để tải; các lần sau dùng cache.
Lưu index_profile cùng revision; đổi model/profile phải reindex, không trộn vectors.
Trên Windows cần IANA timezone data cho Asia/Ho_Chi_Minh; backend lock tzdata khi hệ máy
không có dữ liệu ZoneInfo. Đây là dữ liệu múi giờ hỗ trợ APScheduler, không service mới.

## 2. Khởi tạo và chạy backend

Sau khi hoàn thành CLI/auth/ingestion:
```powershell
uv run --locked python -m app.cli.init_db
uv run --locked python -m app.cli.create_admin
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

create_admin hỏi email và password không echo; không hardcode tài khoản.
init_db không xóa DB cũ. Không --reload khi chạy demo có scheduler.
Không mở backend thứ hai khác port cùng data/DB; không chạy CLI import đồng thời backend.
Khóa run chỉ trong RAM, không hỗ trợ nhiều instance. Khi chạy lại sau ngắt, run dở
thành interrupted, các document đã commit còn nguyên. Chạy mới quét lại, skip unchanged.

## 3. OCR khi cần

Cài Tesseract trên máy và ngôn ngữ vie+eng; kiểm:
```powershell
tesseract --version
tesseract --list-langs
```

PyMuPDF thử native trước. Không có OCR thì native vẫn dùng được, scan/ảnh báo thiếu OCR.
Gate: mean word confidence>=90 và >=30 ký tự/trang, tối đa200 trang,
60s/trang OCR và5 phút/item. Không đạt hoặc bảng mất header thì cách ly toàn document.
OCR đạt chỉ dùng mô tả; không dùng số liệu OCR làm căn cứ tuyển sinh.
Admin xem quality_reason/last_update_error và nhập bản native/TXT có nguồn rõ hơn,
không có nút duyệt số liệu/từng trang. Không sửa chữ số OCR bằng phỏng đoán.

## 4. Frontend (terminal riêng từ repository root)

```powershell
Set-Location frontend
npm ci
Copy-Item -LiteralPath .env.example -Destination .env
npm run dev -- --host localhost
```

Chỉ copy khi chưa có .env riêng. VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1,
không key hoặc password. Mở http://localhost:5173.
Token chỉ RAM, reload phải login lại; Guest chat không có lịch sử server.

## 5. Chuẩn bị dữ liệu hợp lệ

1. Admin tạo nguồn mặc định disabled/unknown, ghi robots/terms/quyền tái sử dụng,
   thời điểm kiểm tra và giới hạn; chỉ bật sau khi đủ căn cứ allowed.
2. UTC nguồn https://tuyensinh.utc.edu.vn/: chỉ lấy phạm vi được phép.
   Công khai không đồng nghĩa có quyền tái sử dụng. Chưa đủ quyền thì giữ disabled
   và hiện thiếu dữ liệu, không tạo thông tin tuyển sinh thay thế.
3. Upload PDF/TXT/PNG/JPG/JPEG<=20MiB: source_url hoặc provenance_note1..2000,
   Mỗi upload có origin UUID riêng/URN theo UUID, không lấy hash làm identity.
   Cùng text/context/profile không re-embed; khác context không gộp; cùng URL khác note
   giữ mọi xuất xứ. Đọc lại metadata và toàn bộ origins/note sau restart.
4. Native rõ tự embedding/ready; OCR lỗi/bảng mơ hồ quarantined.
   Ready không là chứng nhận mọi con số đúng: chat vẫn cần ngữ cảnh/nguồn rõ.
   Có thể dùng tài liệu điểm chuẩn native chính thức qua chatbot.
5. TopCV chỉ bật nếu có quyền rõ. Nếu bị chặn/unknown, không crawl vượt chặn;
   Admin nhập CSV/JSON hợp lệ theo REST, source URL của từng tin, collected_at và
   nguồn có reuse_basis. Xem run/items theo item_index để thấy dòng lỗi/trùng.
6. Khi backend dừng, dùng CLI catalogue:
```powershell
uv run --locked python -m app.cli.import_catalog --file ./data/import/catalog.json
```
   File do dự án chuẩn bị: majors từ documents nguồn chính thức, source_content_hash/page,
   description/career_groups, và10 câu Likert tự xây + scoring direction
   positive/negative/none có reason cho mỗi cặp câu/ngành. Thuận=(a-1)/4, nghịch=(5-a)/4,
   fit=100*trung bình các contribution khác none; mỗi ngành có ít nhất1 câu tính điểm.
   CLI validate toàn bộ, không tự tạo ngành/nguồn. Thiếu file thật thì chưa chạy,
   UI hiển thị data_missing. Quiz không cần dữ liệu điểm học tập.
7. Ghi docs/demo/manifest.json: loại dữ liệu, URL/tệp gốc, title/publisher, quyền/reuse_basis,
   checked_at/collected_at, năm/cơ sở/page nếu có và trạng thái thực.
   Quiz tự xây ghi “quy tắc tham khảo của dự án”; fixture giả lập ở tests/ không đưa vào kho thật.

## 6. Lịch, dừng và lỗi

Backend đang chạy: APScheduler00:00 Asia/Ho_Chi_Minh; không chạy bù khi máy tắt.
Chạy thủ công/lịch/upload/import dùng chung slot; yêu cầu thủ công busy409 RUN_IN_PROGRESS,
lượt lịch busy ghi skipped_busy và bỏ lượt; không chạy chồng hoặc tự chạy lại.
Admin Dừng kết thúc item hiện tại rồi cancelled; start mới quét từ đầu, skip unchanged.
Các item chưa xử lý không tính skipped; lỗi nguồn giữ bản cũ, last_success không tăng giả.
Không dùng nút dừng để dừng backend/chat.

Gemini gọi một lần/request, không retry429 hoặc fallback. Quota503, cấu hình key503,
SDK timeout504 và outer timeout504 có code riêng. Một timeout tổng60s cho chat;
CPU chạy qua to_thread chỉ trả dữ liệu, handler kiểm hạn trước lưu. Khi timeout, CPU có
thể kết thúc sau nhưng không lưu/gửi kết quả muộn; không hủy CPU hoặc thêm cơ chế riêng.
Transaction lưu ngắn có thể có overhead nhỏ, không cam kết ngắt commit đúng mili giây.
UI cho thử lại thủ công.
Không log raw SDK exception, key hoặc nội dung Guest. Lỗi không lưu cặp message answered.
Trả lời mô tả grounded có thể sai nghĩa dù citation đúng: xem nguồn; không có bảo đảm
ngữ nghĩa tuyệt đối. Năm/mã ngành/tên chương trình chứa số đúng nguồn và vai trò được phép;
không chặn chỉ do chữ số/keyword. Điểm chuẩn/học phí/chỉ tiêu/ngày/số tin vẫn chỉ qua
native nguyên văn/COUNT; không dùng ngoại lệ mã ngành để hợp thức hóa số định lượng.
Không đủ rõ thì báo thiếu.

## 7. Kiểm thử và demo

Từ backend:
```powershell
uv run --locked pytest
```

Từ frontend:
```powershell
npm run build
```

Suite mặc định offline, fixture ghi nhãn/cách ly; E5/OCR smoke riêng theo testing.md.
Kiểm tay 360/768/1366: Guest/auth/owner/history, chat có nguồn/ngoài phạm vi/missing/
quota, quiz10 câu/top3–5/zero/missing, jobs/source/expired, Admin disable/delete/
stop/rerun. Đo10 câu warm CPU và deadline60s. Ghi kết quả thật vào
docs/demo/acceptance-results.md, gồm các giới hạn quyền và dữ liệu hiện có.
README cuối phải giữ cùng lệnh/stack/giới hạn trên.

## Quản lý tài liệu và crawl hiện hành

Admin disable giữ tài liệu, crawl cập nhật vẫn disabled; enable thủ công mới dùng lại.
Xóa là xóa thật và các liên kết theo data-model; nếu website còn tài liệu, crawler có thể
nhập lại ở lần sau. UI xác nhận và README phải nói rõ điều này.
Nút “Crawl ngay” gọi POST /admin/runs, trả202 run_id ngay và poll run nền; busy409.
Không reset cron00:00. Cron đến khi bận bỏ lượt, ghi skipped_busy — “Bỏ qua do đang bận”,
khác “Thất bại”; counts0, không có tài liệu xử lý. Không chạy lượt đó sau khi rảnh/restart;
00:00 ngày sau vẫn chạy. Backend tắt không crawl/chạy bù. Một pipeline chung manual/scheduled.
CSV/JSON hỗ trợ nguồn xuất bản khác được phép: row source_id hoặc default request,
không coi tên file là nguồn web. Job count theo identity nguồn+ID/URL, không theo document.

## Cổng sẵn sàng demo

Cần tài liệu UTC có quyền sử dụng để RAG trả lời có nguồn, >=3 ngành UTC usable và
>=1 tin nghề nghiệp hợp lệ, có manifest nguồn/quyền/thời gian. Demo upload→index→retrieval,
quiz ready, nghề nghiệp có dữ liệu, login/logout/history và Admin thành công.
Ghi bằng chứng actual theo SC-010 vào acceptance-results. Thiếu vẫn hiển thị trung thực,
nhưng chỉ data_missing không đạt demo chính; đánh NOT READY demo cho đến khi đủ.
