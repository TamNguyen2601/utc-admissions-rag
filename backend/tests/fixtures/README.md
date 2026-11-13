# Fixtures Foundation

**GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC**.

`foundation.json` và các bảng `fixture_*` chỉ phục vụ kiểm thử T007.
SQLite đặt ở pytest `tmp_path`, không dùng `backend/data/` hoặc kho demo.
Mặc định chặn DNS/kết nối ngoài loopback. SDK timeout smoke T003 chỉ dùng loopback.
Smoke E5 tải thật phải chạy riêng bằng `tests/smoke/check_e5.py --download`.

Fixtures `fake_clock`, `fake_network`, `fake_encoder`, `fake_gemini`, `fake_ocr`
cung cấp đồng hồ/transport/đầu ra giả lập; encoder và Gemini chưa có service để
tích hợp tại T007. Chúng không thay nghiệm thu E5 thật, Gemini live hoặc pipeline.
