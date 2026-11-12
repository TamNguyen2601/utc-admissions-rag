# Quyết định thiết kế sau đơn giản hóa

Ngày: 2026-11-13. Căn cứ: yêu cầu scope simplification, constitution 1.0.0 và
[spec](spec.md). Đây là quyết định thiết kế; việc cài dependency, đo chất lượng và
kiểm quyền nguồn phải được ghi kết quả thật ở các task triển khai, không coi đã hoàn tất.

| Chủ đề | Quyết định | Lý do và cách kiểm tra |
| --- | --- | --- |
| Phạm vi tư vấn | Quiz hướng nghiệp, không đầu vào điểm học tập | Giảm dữ liệu/luật xét tuyển; kiểm request strict và UI; RAG vẫn giữ kiến thức điểm chuẩn |
| Rubric | 10 câu Likert1–5, direction positive/negative/none theo ngành | Hỗ trợ câu thuận/nghịch; none không vào mẫu số; ít nhất6 bộ expected và biên1/3/5 |
| Catalogue | Người làm dự án nhập ngành UTC từ nguồn chính thức còn hợp lệ | Không để Gemini bịa ngành/mapping; kiểm source hash và quyền trước trả kết quả |
| Narrative | Gemini answer + evidence_ids | Giữ mô tả có năm/mã ngành/tên chương trình đúng nguồn; guard theo vai trò số, golden review thay parser từng claim |
| Số liệu | Template trích nguyên văn native có ngữ cảnh | Tránh model sửa số/đơn vị; không tính chênh lệch hay dự đoán; OCR/bảng mơ hồ không làm evidence số |
| Indexing | Một bản hiện hành, content_hash + index_profile | Đáp ứng incremental và hiến chương; staging ngoài DB, short transaction giữ bản tốt |
| Origin | Upload UUID riêng, URL partial unique web; giữ provenance | Không gộp sai context; disable giữ flag, delete xóa vật lý và được crawl lại |
| Career mapping | majors.career_groups + job.career_group | Lọc minh bạch; không cần liên kết từng job/ngành, không suy đủ toàn thị trường |
| Import log | UNIQUE(run_id,item_index) | Log mỗi dòng kể cả URL sai/trùng; khác khóa chống trùng nội dung/job |
| Scheduler | APScheduler3 + coordinator lock trong một process | Phù hợp local; không cần OS lock hoặc test nhiều instance/crash process |
| OCR | PyMuPDF trước; Tesseract CLI vie+eng khi thiếu native | Không thêm wrapper; gate chất lượng và cách ly toàn tài liệu thay duyệt từng trang |
| Auth | JWT + Argon2id + session thu hồi | Logout có hiệu lực backend; ownership/RBAC kiểm trực tiếp |
| Dependencies | uv backend, npm frontend, lockfiles | Chạy lại được trên Python3.13/Node24.22.1/PowerShell; setup phải resolve và smoke thực |
| Timeout | Một asyncio.timeout_at(expires_at), tổng60s, to_thread chỉ tính, handler duy nhất lưu | Không kill CPU/task registry; kiểm hạn trước commit, bỏ kết quả đến muộn; test timeout account không answered |
| Testing | Core unit/contract/integration và kiểm tay có nguồn | Không hạ kiểm tra bảo mật, không thêm hạ tầng production |

## Tham số triển khai cần giữ thống nhất

- E5 CPU `intfloat/multilingual-e5-small`: prefix query:/passage:, 384 chiều L2;
  NumPy cosine; BLOB little-endian float32 = 1.536 bytes. Revision cụ thể được ghi
  trong cấu hình/manifest ở task setup sau khi tải thành công, không ghi một revision giả.
- Chunk 320 token/overlap48, tổng <=512 có prefix/special; query vượt budget trả 422.
  Threshold ban đầu 0,75; tune trên tiếng Việt và ghi lại giá trị, không coi là confidence.
- index_profile gồm model/revision/dim/normalization/chunking/extraction_version;
  không trộn vector khác profile; thay đổi profile reindex các document bị ảnh hưởng.
- Gemini default gemini-3.5-flash-lite qua google-genai, SDK retry tổng attempts=1.
  Setup/adapter task kiểm SDK đã lock hỗ trợ timeout/retry control; không tự đổi model.
  Quota503 không retry; key503; SDK timeout504 khác outer timeout504.
  Một outer asyncio.timeout_at(expires_at) tổng60s, SDK timeout<=remaining tại lúc gọi; thread CPU không persist.
  Handler kiểm expires_at sau retrieval và ngay trước transaction; không hủy CPU đang chạy.
- Quiz: c(positive)=(a-1)/4, c(negative)=(5-a)/4; none loại tổng/mẫu số/lý do.
  fit=100*sum(c)/N, N là số mapping khác none, N>=1 cho mỗi ngành;
  mỗi câu có ít nhất1 ngành khác none. Sort chưa round rồi code/campus; top5 dương nếu>=3.
  Catalogue/rubric thực do dự án biên soạn từ nguồn hợp lệ, không giả là thang tâm lý chuẩn.
- OCR mean confidence >=90, >=30 ký tự không trắng/trang, nếu không đạt cách ly toàn doc;
  mọi OCR numeric_eligible=false. Native bảng thiếu header/context cách ly, không tự sửa.
  Các ngưỡng chỉ là quality gate demo, không chứng nhận OCR đúng tuyệt đối.
- Nguồn bật chỉ khi có kiểm tra quyền đủ; robots cho phép không đồng nghĩa được tái sử dụng.
  TopCV chưa đủ quyền mặc định disabled/unknown, dùng file có quyền.
- Không có chạy bù lịch khi máy tắt, multi-instance, deployment hoặc SLA.
  Tác vụ CPU và nguồn mạng có thể chậm; ghi thông số máy/latency trong nghiệm thu.

## Giới hạn được chấp nhận

Grounding và citation validation không chứng minh mọi diễn giải đều đúng.
Đường số bảo thủ có thể từ chối dù người đọc hiểu được bảng; cần bản native rõ hơn
thay vì tự đoán. Nguồn thiếu/quyền chưa xác định làm giảm phạm vi demo; phải hiển thị
trung thực. Nếu backend thứ hai cùng DB được chạy sai hướng dẫn, khóa RAM không bảo vệ
được; đó là cấu hình không được hỗ trợ, không bổ sung kiến trúc nhiều instance.

## Quyết định quản lý tài liệu/lịch/jobs hiện hành

Disable không tự enable khi crawl; delete xóa vật lý doc/chunks/origins/jobs/majors phụ thuộc,
snapshot chat độc lập và run FK nullable. Không giữ record để ngăn crawler nhập lại.
Cron00:00 cố định không reset bởi manual. Busy bỏ lượt, ghi terminal skipped_busy trong
crawl_runs (khác failed), không tự chạy khi rảnh/restart; ngày sau vẫn00:00. Backend tắt
không crawl hoặc chạy bù; manual rảnh chạy ngay, busy409, một pipeline.
Job source+external_id tin cậy hoặc source+canonical_url là identity, COUNT job.id,
không gộp hai job chỉ vì text/document giống nhau. CSV/JSON nguồn xuất bản theo dòng,
default nguồn request tùy chọn; registry quyền vẫn bắt buộc, không coi import là miễn quyền.
