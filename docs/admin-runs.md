# Crawl ngay và lịch tự động — T049–T051

Chạy backend bằng một process, một Uvicorn worker:

```powershell
cd backend
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Không chạy đồng thời backend thứ hai dùng cùng SQLite. Slot coordinator nằm trong RAM;
phạm vi local không hỗ trợ nhiều process/worker. Không có Redis, Celery hay hàng đợi.

APScheduler 3 dùng MemoryJobStore và CronTrigger cố định **00:00 Asia/Ho_Chi_Minh**.
Job `daily-crawl`: `max_instances=1`, `coalesce=True`, `misfire_grace_time=60`.
Callback chỉ claim slot và dispatch pipeline nền; manual không sửa lịch.
Khởi động lại tạo mốc cron tương lai, không chạy bù các mốc backend tắt.

Các đường dẫn dưới đây có tiền tố `/api/v1` và yêu cầu Bearer token ADMIN:

| API | Hành vi |
| --- | --- |
| `POST /admin/runs` với `{}` hoặc `{"source_id":"<UUID>"}` | `202 {run_id,state:"running"}` và Location tới detail; HTTP trả trước khi crawl xong |
| `GET /admin/runs?page=1&page_size=20` | Danh sách mới nhất trước |
| `GET /admin/runs/{id}` | Trigger, actor, trạng thái, timestamps, counts, source_outcomes |
| `GET /admin/runs/{id}/items?page=1&page_size=20` | Item theo item_index tăng dần; page_size tối đa 100 |
| `POST /admin/runs/{id}/stop` | Đặt stop_requested cho run active; terminal trả nguyên trạng thái |

Manual, scheduled, upload và job import cùng dùng một coordinator/slot. Khi busy,
manual/upload/import trả `409 RUN_IN_PROGRESS`, không tạo lượt mới. Cron ghi terminal
`skipped_busy`: started_at null, ended_at bằng created_at, counts 0, không item,
source_outcomes rỗng. Bỏ lượt hoàn toàn; nhả slot không tự khởi chạy lại.

Manual/scheduled cùng gọi CrawlService, tuần tự dùng adapter UTC/TopCV và các service
document/job hiện có. Chỉ chọn nguồn enabled/allowed; nguồn chỉ định phải usable.
Nguồn career/upload/catalog ghi `skipped / import-only`, không fetch hoặc tăng last_success.
Item_index liên tục qua mọi nguồn của một run.

Stop giữ item đang xử lý hoàn tất và commit trước khi cancelled; không xử lý item tiếp.
Các item đã thành công được giữ lại, kể cả khi lượt sau lỗi. Gửi POST mới khi rảnh để
rerun từ đầu với ID mới; không resume offset. Stop ID terminal không tác động run mới.
Shutdown ngừng lịch, từ chối claim mới, yêu cầu stop và chờ item hiện tại hoàn tất trước
khi đóng DB. Startup đổi running/stop_requested còn dở thành interrupted, giữ dữ liệu,
không tự chạy lại. Log chỉ chứa metadata run/state/counts và các lý do lỗi đã chuẩn hóa.

Kiểm tra offline, không dùng dữ liệu demo thật:

```powershell
cd backend
uv run --locked --offline pytest tests/contract/test_runs.py tests/integration/test_scheduler.py -q
uv run --locked --offline pytest -q
```

Fake clock đi qua BaseScheduler, CronTrigger và MemoryJobStore thật; chỉ timer/executor
test được điều khiển trực tiếp. HTTP/OCR/encoder được giả lập; SQLite, extraction,
chunking/index/publish và coordinator thực thi thật. Đây không phải nghiệm thu nguồn
UTC/TopCV live hoặc E5 CPU mới; các phần đó có checkpoint riêng.
