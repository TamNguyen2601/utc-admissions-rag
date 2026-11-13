# Nhập catalogue và rubric quiz

Chỉ dùng catalogue do dự án biên soạn từ tài liệu UTC chính thức đã nhập hợp lệ
vào `documents`. Không có dữ liệu ngành mặc định hoặc dữ liệu demo tự sinh.
Các fixture trong `backend/tests/` là giả lập, không đưa vào kho thật.

Dừng backend trước khi chạy từ `backend/`:

```powershell
uv run --locked python -m app.cli.import_catalog --file ./data/import/catalog.json
```

File UTF-8 JSON, tối đa 20 MiB, object có đúng hai khóa `majors` và `questions`.
CLI thay toàn bộ catalogue và rubric trong một transaction. Lỗi validation, nguồn,
hoặc SQL rollback toàn bộ, giữ bản trước. Khi biên soạn lại, giữ UUID ngành/câu
không đổi để các liên kết và mã định danh của client ổn định. Không chạy đồng thời
với backend hoặc một tiến trình import khác; không có khóa liên tiến trình.

`majors` có ít nhất ba object, mỗi object đủ các trường sau:

| Trường | Kiểu và ý nghĩa |
| --- | --- |
| `id` | UUID ngành do người biên soạn cấp, duy nhất |
| `code`, `name`, `campus` | Chuỗi không rỗng; cặp code/campus duy nhất |
| `description` | Mô tả ngành đã đối chiếu tài liệu nguồn |
| `source_document_id` | UUID document hiện có, ready và enabled |
| `source_content_hash` | SHA256 nội dung hiện hành, 64 ký tự hex thường |
| `source_page` | Số nguyên >=1 hoặc null; ghi đúng trang hỗ trợ thông tin |
| `career_groups` | Array object `{code,label,reason}`; code không lặp trong ngành; reason giải thích liên hệ theo nguồn |

Nguồn phải active, enabled, allowed, có checked_at/reuse_basis hợp lệ và URL trong
scope. Chỉ chấp nhận registry kind utc/catalog/upload. URL nguồn thuộc `utc.edu.vn`
hoặc tên miền con; bản upload chỉ có URN cần provenance_note và publisher xác định
là “UTC”, “Trường Đại học Giao thông vận tải” hoặc “Đại học Giao thông vận tải”.
Tên và mã ngành phải xuất hiện trong nội dung nguồn hiện hành. Đây là kiểm identity
và xuất xứ; tác giả vẫn phải kiểm tra mô tả, cơ sở, trang và lý do mapping có căn cứ.
Không nhập điểm xét tuyển hoặc coi việc đọc được URL là quyền tái sử dụng.

`questions` có đúng 10 object:

| Trường | Kiểu và ý nghĩa |
| --- | --- |
| `id` | UUID câu hỏi, duy nhất |
| `position` | Số nguyên 1..10, không lặp |
| `text` | Câu hỏi tính cách/sở thích/phong cách làm việc do dự án biên soạn |
| `scoring` | Object keyed UUID ngành; mỗi giá trị là `{direction,reason}` |

Mỗi câu phải mapping đủ và đúng một lần mọi ngành trong file. `direction` chỉ có
`positive`, `negative`, `none`; `reason` luôn là chuỗi không rỗng. Mỗi câu cần ít nhất
một ngành khác none; mỗi ngành cần ít nhất một câu khác none. Không có weight.
JSON trùng khóa, khóa UUID trùng sau chuẩn hóa, extra fields đều bị từ chối.

Năm lựa chọn cố định từ 1 “Rất không đồng ý” đến 5 “Rất đồng ý”. Contribution thuận
là `(a-1)/4`, nghịch `(5-a)/4`; none không tham gia tổng hoặc mẫu số.
Điểm `100*sum(contribution)/N`; N=0 là rubric lỗi. Sắp điểm chưa làm tròn giảm dần,
rồi code/campus tăng dần, trả tối đa 5 ngành có điểm dương khi đủ ít nhất 3 ngành.
Điểm trả về làm tròn hai chữ số thập phân. Lý do chọn tối đa hai contribution >=0,75,
ưu tiên contribution cao rồi position; câu nghịch nêu rõ không đồng ý.

CLI in `rubric_version` là SHA256 ổn định của câu hỏi, ID, directions, reasons,
catalogue và source hashes. Nhập lại cùng dữ liệu dù đổi thứ tự array giữ version.
Đổi nội dung nguồn cần đối chiếu và nhập lại catalogue với hash mới.

API công khai:

- `GET /api/v1/catalog/majors`: catalogue usable, hỗ trợ campus/page/page_size.
- `GET /api/v1/quiz`: schema ready hoặc data_missing, công bố mapping và công thức.
- `POST /api/v1/recommendations`: chỉ `{rubric_version,answers:[{question_id,value}]}`.
- `GET /api/v1/jobs?major_id=<UUID>`: dùng career_groups còn nguồn hợp lệ; không gán
  ngành cho job chưa phân nhóm. Scope chat dùng tên ngành/nhãn nhóm từ catalogue.

Đáp án phải đủ 10 UUID duy nhất và value nguyên 1..5, không boolean/float/string.
Schema sai trả 422 INVALID_QUIZ_ANSWERS. Rubric đổi trả 409 RUBRIC_CHANGED.
Dữ liệu thiếu trả 200 data_missing trước kiểm version; không dùng rubric một phần.
Không có điểm dương trả no_match; chỉ một hoặc hai ngành dương trả insufficient_matches.
Quiz không lưu attempt/answers/profile, không gọi Gemini. Kết quả luôn có lưu ý:
“Kết quả chỉ mang tính tham khảo, không bảo đảm trúng tuyển.”
