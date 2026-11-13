# Fixtures Foundation

**GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC**.

`foundation.json` và các bảng `fixture_*` chỉ phục vụ kiểm thử T007.
SQLite đặt ở pytest `tmp_path`, không dùng `backend/data/` hoặc kho demo.
Mặc định chặn DNS/kết nối ngoài loopback. SDK timeout smoke T003 chỉ dùng loopback.
Smoke E5 tải thật phải chạy riêng bằng `tests/smoke/check_e5.py --download`.

Fixtures `fake_clock`, `fake_network`, `fake_encoder`, `fake_gemini`, `fake_ocr`
cung cấp đồng hồ/transport/đầu ra giả lập; encoder và Gemini chưa có service để
tích hợp tại T007. Chúng không thay nghiệm thu E5 thật, Gemini live hoặc pipeline.

## Fixtures T020–T024 (B2)

`utc/` chứa HTML trang danh sách, phân trang, bài viết, robots.txt, PDF native hai
trang, PDF bảng có/thiếu header, PDF scan và ảnh PNG. Toàn bộ là **GIẢ LẬP — KHÔNG
PHẢI THÔNG TIN UTC**, được tạo tại máy, không tải từ website. Tái tạo PDF/ảnh bằng
`python tests/fixtures/build_ingestion.py` từ backend với môi trường đã lock.

Test dùng BeautifulSoup/PyMuPDF thật, SQLite trong tmp_path, HTTP/DNS giả lập,
Tesseract subprocess giả lập TSV và indexer spy. Chúng kiểm cả 90/30, timeout,
missing language data, quarantine và numeric_eligible=false cho OCR, nhưng không
thay smoke Tesseract vie+eng thật hoặc embedding/retrieval T025 trở đi.

Smoke OCR thật chạy riêng từ `backend/` sau khi cài Tesseract và cấu hình `.env`:

```powershell
uv run --locked --offline python tests/smoke/check_ocr.py --output tests/smoke/ocr-local.json
```

Script tạo ảnh/PDF tiếng Việt GIẢ LẬP bằng font Arial local (đổi bằng `--font`),
gọi Tesseract thật qua Extractor và kiểm native, PNG, PDF scan, ảnh trống bị cách ly.
OCR đạt gate vẫn numeric_eligible=false. Script không nằm trong pytest mặc định;
`ocr-local.json` là bằng chứng chạy trên máy, không phải kết quả giả lập.

## Fixtures T025–T029 (C)

`tests/knowledge_support.py` cung cấp tokenizer/encoder giả lập xác định được;
`test_embedding.py`, `test_retrieval.py`, `integration/test_knowledge.py` dùng
chunking/indexing/publish/SQLite/retrieval/API thật. Suite mặc định không tải E5.
Hai fixture PDF bảng đã được tái tạo vì bytes cũ lỗi zlib; `.gitattributes` giữ
PDF/ảnh dạng binary để Git trên Windows không đổi newline trong PDF stream.

Smoke riêng chạy **E5 CPU thật**, tokenizer thật, SQLite tạm và tiếng Việt giả lập:

```powershell
uv run --locked --offline python tests/smoke/check_knowledge_e5.py --output tests/smoke/knowledge-e5-local.json
```

Chỉ đọc model cache `backend/data/models` với revision trong config; thiếu cache
thì thất bại, không tự tải/fallback. Dùng `check_e5.py --download` sẵn có nếu cần
chuẩn bị cache lần đầu. Không ghi DB/uploads demo, không gọi Gemini/website.
Artifact ghi model/revision/CPU/profile/latency cùng các kiểm tra lifecycle thực.
