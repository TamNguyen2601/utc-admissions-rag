# Đặc tả chức năng: UTC Admissions RAG Chatbot

**Ngày rà soát phạm vi**: 2026-11-13  
**Trạng thái**: Thiết kế hoàn thành, sẵn sàng triển khai, chưa thực hiện source code  
**Phạm vi**: Bài tập lớn tiếng Việt, một frontend và một backend chạy local.  
**Căn cứ**: [Hiến chương 1.0.0](../../.specify/memory/constitution.md).
Yêu cầu đơn giản hóa hiện tại thay thế quyết định cũ về đối chiếu điểm và cấu trúc trắc nghiệm.
Không đổi nhánh Git; nhánh thực tế khi rà soát là `master`, không suy ra nhánh mặc định.

## Phạm vi và vai trò

- Guest: chat không lưu server, đọc ngành/nghề, làm quiz và nhận gợi ý.
- USER: thêm lịch sử hội thoại riêng.
- ADMIN: quyền cá nhân như USER; quản lý tài liệu, quyền nguồn và lần cập nhật.
  Không được xem hội thoại người khác.
- Tư vấn ngành chỉ dùng trắc nghiệm tính cách, sở thích và phong cách làm việc;
  không thu điểm học tập hay ngữ cảnh để đối chiếu điểm. Không dự báo trúng tuyển.
- Chatbot vẫn trả lời điểm chuẩn, học phí, chỉ tiêu, lịch tuyển sinh từ tài liệu
  chính thức đúng ngữ cảnh. Không loại kiến thức điểm chuẩn khỏi RAG.
- Không yêu cầu Docker, Redis, Celery, Kubernetes, microservices, cloud database,
  hệ thống production hoặc framework RAG bổ sung.

## User stories và acceptance scenarios

P1 là nền tảng; P2 hoàn thiện các hành trình demo. Cả hai thuộc phạm vi triển khai.
Fixture được phép giả lập nhưng phải ghi nhãn và cách ly kho demo chính thức.

### US1 — Hỏi đáp có căn cứ (P1)

Guest/USER/ADMIN hỏi tiếng Việt về tuyển sinh UTC, chương trình đào tạo và nghề liên quan.

1. Có tài liệu hợp lệ: trả lời có tên nguồn, URL hoặc định danh cục bộ tra cứu được,
   trang/mục nếu có. Mô tả có thể diễn giải tự nhiên từ retrieved context; năm làm ngữ cảnh,
   mã ngành và tên chương trình có số được phép khi khớp đúng vai trò trong nguồn đã trích.
   Không từ chối chỉ vì có chữ số hoặc từ khóa như “học phí”; dữ kiện định lượng vẫn theo mục2.
2. Hỏi điểm chuẩn/học phí/chỉ tiêu/ngày: chỉ trích số từ đoạn/bảng đọc rõ, giữ đơn vị,
   năm, cơ sở, ngành, phương thức và điều kiện liên quan; thiếu ngữ cảnh thì hỏi lại.
   Không tính chênh lệch, xác suất hay đảm bảo trúng tuyển.
3. Kho rỗng/không đủ bằng chứng/nguồn mâu thuẫn: trả trạng thái rõ, không bịa dữ kiện
   hoặc nguồn. Không lấy dữ liệu năm/cơ sở khác thay cho dữ liệu được hỏi.
4. Chào/cảm ơn/tạm biệt: phản hồi xã giao không cần nguồn. Ngoài phạm vi: từ chối ngắn;
   câu hỗn hợp chỉ tư vấn phần trong phạm vi, phần này vẫn cần nguồn.
5. Citation ID không thuộc retrieval hoặc tài liệu vừa vô hiệu hóa/xóa: không trả nội dung đó;
   chỉ dẫn trong tài liệu không được thay prompt, quyền hoặc lộ bí mật.
6. Gemini hết quota/timeout/sai key: lỗi HTTP đúng contract, kết thúc loading,
   không tạo câu trả lời giả hoặc lưu message answered. Một timeout tổng60s cho luồng chat;
   phần tính CPU có thể kết thúc sau nhưng không được tự lưu hoặc gửi kết quả.

**Kiểm thử độc lập**: Kho fixture hai năm/hai cơ sở, nguồn xung đột và Gemini stub.

### US2 — Quản lý tri thức có nguồn (P1)

Admin chuẩn bị HTML/PDF/TXT/ảnh được phép dùng, quản lý trạng thái và nguồn.

1. Upload/crawl hợp lệ lưu metadata/xuất xứ, trích nội dung và tự index khi đạt chất lượng.
   URL hoặc ghi chú xuất xứ upload phải tồn tại; URN tệp không thay xuất xứ.
2. HTML/PDF native rõ được dùng tự động; PyMuPDF trước, Tesseract khi cần.
   OCR lỗi/chất lượng thấp hoặc bảng số mất cột/ngữ cảnh bị cách ly.
   Nội dung OCR không làm căn cứ số liệu tuyển sinh; không có luồng duyệt từng trang.
3. Web dùng URL chuẩn hóa để nhận diện nguồn; mỗi upload hợp lệ có origin UUID riêng,
   không dùng raw/content hash làm identity. Cùng nội dung/ngữ cảnh/cấu hình tái sử dụng
   document/chunks, không re-embed dù đổi tên hay có nhiều lần cung cấp xuất xứ.
   Cùng bytes nhưng khác năm/cơ sở không gộp document; URL upload giống nhau hoặc note
   khác hợp lệ không gây lỗi UNIQUE hay ghi đè xuất xứ trước. URN dùng origin UUID, không hash.
4. Nội dung đổi: chuẩn bị bản mới trước, thay text/chunks/vectors cùng transaction ngắn;
   lỗi giữ bản đang dùng và ghi lỗi cập nhật riêng.
5. Vô hiệu hóa giữ document/metadata, không retrieval; crawl cập nhật vẫn giữ enabled=false.
   Admin kích hoạt lại thủ công. Xóa thật document/chunks/vectors/origins và liên kết;
   không lưu dấu chặn, website còn tài liệu thì được crawl lại. UI/README phải nói rõ.
6. Nguồn cấm/chưa rõ quyền/403/CAPTCHA: dừng, không vượt chặn; 404 không tự xóa bản tốt.

**Kiểm thử độc lập**: Tệp có quyền, ảnh rõ/mờ, PDF scan/hỏng, URL biến thể, hash trùng.

### US3 — Tài khoản và phân quyền (P1)

1. Đăng ký hợp lệ tạo USER; email trùng/đầu vào sai bị chặn. Không nhận role do client chọn.
2. Đăng nhập đúng nhận phiên 30 phút; đăng xuất thu hồi phiên trên backend.
3. Guest gọi quản trị bị 401, USER bị 403; gọi trực tiếp vẫn kiểm tra quyền.
4. Guest chat không có DB/log nội dung, không nhập lịch sử Guest vào tài khoản khi login.
5. Token sai/hết hạn được báo 401, không tự đổi thành Guest.

**Kiểm thử độc lập**: Hai USER, một ADMIN và Guest; không cần Gemini thật.

### US4 — Hội thoại riêng (P2)

1. Chủ sở hữu tạo/liệt kê/mở/tiếp tục/đặt tên/xóa hội thoại; tin đúng thứ tự, có nguồn.
2. USER khác hoặc ADMIN truy cập ID của người khác nhận 404, không lộ hoặc đổi dữ liệu.
3. Lỗi dịch vụ không lưu cặp tin thành công; trả lời nghiệp vụ thiếu nguồn được lưu
   với đúng trạng thái, không phải answered.
4. Lịch sử giữ snapshot nguồn; nguồn bị đổi/vô hiệu hóa/xóa hiện không còn khả dụng,
   không dùng snapshot hay lời assistant cũ làm evidence cho lượt mới.

**Kiểm thử độc lập**: Hai chủ sở hữu, nguồn bị xóa và Gemini stub lỗi.

### US5 — Quiz hướng nghiệp và gợi ý ngành (P2)

1. Một bộ 10 câu bắt buộc về tính cách/sở thích/phong cách làm việc, mỗi câu 5 đáp án
   Likert 1–5 có nhãn rõ; mỗi cặp câu/ngành có direction positive (thuận), negative (nghịch)
   hoặc none (không tính). Chuẩn hóa contribution thuận=(value-1)/4, nghịch=(5-value)/4;
   fit=100*trung bình contribution của các câu khác none. Rubric/công thức công khai,
   không coi là chẩn đoán; không đồng ý câu nghịch có thể tăng mức phù hợp.
2. Trả đủ 10 câu và rubric còn hiệu lực: chấm rule-based, xếp 3–5 ngành UTC có
   dữ liệu nguồn còn hợp lệ; mỗi ngành có tên/cơ sở, điểm phù hợp, lý do và nguồn.
   Cùng dữ liệu/đáp án cho cùng thứ tự; đồng điểm sắp theo mã ngành rồi cơ sở.
3. Thiếu câu/trùng câu/đáp án ngoài 1–5 bị 422; rubric đã đổi bị 409, không tự điền.
4. Thiếu quiz/catalogue đủ điều kiện: data_missing, không tạo bộ câu/ngành giả.
   Tất cả điểm 0: no_match. Có ít hơn ba ngành có điểm dương: insufficient_matches,
   không điền ngành không phù hợp để đủ số.
5. GET /quiz luôn phân biệt ready hoặc data_missing bằng status và đủ các khóa theo
   contract; UI không đoán bằng trường tùy chọn.
6. Không có form điểm xét tuyển hoặc đối chiếu điểm trong request/result.
   Gemini không chấm điểm hoặc tạo catalogue; luôn có lưu ý chỉ tham khảo.

**Kiểm thử độc lập**: Rubric tự xây ghi nhãn, ba đến sáu ngành fixture có nguồn,
đáp án chuẩn/tie/zero/thiếu. Không cần dữ liệu điểm chuẩn hay Gemini.

### US6 — Thông tin nghề nghiệp (P2)

1. Tin có xuất xứ từng tin: source_url, source_name, collected_at và origin_id;
   nguồn import container không thay nguồn gốc tin.
2. Ngành liên hệ nhóm nghề bằng mapping rõ từ mô tả ngành có nguồn; tin chưa phân nhóm
   không được tự gán ngành. Lọc ngành dùng mapping này.
3. TopCV chỉ chạy khi được phép; nếu chặn/không rõ quyền thì dừng và dùng CSV/JSON hợp lệ.
4. Import lỗi cấu trúc từ chối tệp; lỗi dòng cách ly, log item_index kể cả URL sai/trùng,
   dòng hợp lệ vẫn nhập. Job mới →new; cùng identity không đổi nghiệp vụ →skipped;
   nghiệp vụ/trạng thái nguồn đổi so DB →updated. Trong file giữ dòng hợp lệ đầu tiên:
   cùng identity/payload →skipped, payload mâu thuẫn →error/conflict cho dòng sau.
   Cùng source/URL có hai external_id khác nhau →error/identity_conflict, không ghi đè
   job/origin khác. Thay đổi thời gian quan sát đơn thuần không là updated.
5. Phân biệt open/expired/unverified, kiểm tra lại hạn khi đọc.
   Số tin quan sát có phạm vi/thời gian/nguồn; không suy toàn thị trường hay số vị trí.

**Kiểm thử độc lập**: CSV/JSON đủ quyền, trùng URL, ngày sai, ba trạng thái; không cần TopCV thật.

### US7 — Cập nhật theo lịch và thủ công (P2)

1. Khi backend đang chạy, APScheduler kích hoạt 00:00 Asia/Ho_Chi_Minh;
   chỉ nguồn bật/đủ quyền. Không chạy bù lúc máy tắt.
2. Nút “Crawl ngay” gọi Admin API kiểm ADMIN, khởi chạy nền và trả202 run_id/state ngay.
   Chung pipeline với cron00:00, manual không reset/đổi lịch. Một process/worker,
   chung slot upload/import/crawl; mutex chỉ giữ lúc chuyển trạng thái, không qua xử lý dài;
   active_run_id bảo đảm một pipeline; manual busy409 RUN_IN_PROGRESS. Đến00:00 khi bận,
   bỏ lượt scheduled và ghi skipped_busy, không chạy lại khi slot rảnh. Ngày sau vẫn đúng00:00.
3. Admin Dừng: hoàn tất tài liệu hiện tại rồi dừng, không bắt đầu tài liệu kế.
   Chạy lại tạo run mới, quét từ đầu và skip phần không đổi.
4. Run lưu người kích hoạt/dừng, thời gian, trạng thái, số mới/đổi/skip/lỗi,
   kết quả từng nguồn/dòng; lỗi một nguồn không phá dữ liệu cũ hoặc nguồn khác.
5. Khởi động lại trong cấu hình một process: run chưa kết thúc được đánh interrupted,
   giữ dữ liệu đã commit. Không hỗ trợ nhiều instance cùng thư mục dữ liệu.
6. Guest/USER không được start/stop/xem quản trị; chatbot vẫn dùng được khi dừng crawl.

**Kiểm thử độc lập**: Đồng hồ giả, ba tài liệu tuần tự, restart app test với SQLite tạm.

### US8 — Dashboard và chạy demo (P2)

1. Header/sidebar/menu responsive tại 360/768/1366 px, không cuộn ngang toàn trang;
   trang chat, quiz, nghề nghiệp, lịch sử, login/register và quản trị đúng quyền.
2. Mỗi trang có loading/empty/error/data_missing rõ bằng tiếng Việt, không lấp bằng dữ liệu giả.
3. Admin xem lỗi xử lý/cách ly, nguồn và run; không có thao tác duyệt số liệu/từng trang.
4. README đủ chạy local Windows PowerShell, backend uv/Python 3.13, frontend npm/Node.js
   24.22.1, một worker; dữ liệu demo thật có manifest quyền/xuất xứ.
5. Trước demo chạy core tests và ghi kết quả thật, không đánh dấu đã chạy khi mới thiết kế.
   Demo chính phải có tài liệu UTC hợp lệ để hỏi đáp RAG có nguồn, ít nhất3 ngành UTC
   có nguồn cho quiz, ít nhất1 tin nghề nghiệp được phép dùng; trình diễn ingestion thủ công
   →retrieval, authentication, history và Admin thành công. Thiếu vẫn báo trung thực nhưng
   data_missing đơn thuần không đạt nghiệm thu demo chính.

## Yêu cầu có thể kiểm tra

| Chức năng gốc | Yêu cầu hiện hành |
| --- | --- |
| F01 Chatbot | FR-001–FR-006 |
| F02 Cơ sở tri thức UTC | FR-007–FR-014 |
| F03 Nghề nghiệp | FR-015–FR-018 |
| F04 Cập nhật tự động/thủ công | FR-019–FR-021 |
| F05 Gợi ý ngành bằng quiz | FR-022–FR-025 |
| F06 Tài khoản | FR-026–FR-029 |
| F07 Lịch sử | FR-030–FR-031 |
| F08 Quản lý tài liệu | FR-007, FR-010, FR-032 |
| F09 Dashboard | FR-033 |
| F10 Chất lượng/chạy local | FR-034–FR-036 |

| ID | Yêu cầu bắt buộc |
| --- | --- |
| FR-001 | Mọi vai trò chat tiếng Việt; message trim 1–4.000 ký tự, quá giới hạn không cắt âm thầm. |
| FR-002 | Scope gate trước Gemini: UTC/nghề liên quan, xã giao, ngoài phạm vi, hỗn hợp, mơ hồ theo US1. |
| FR-003 | Thiếu/mâu thuẫn bằng chứng trả trạng thái riêng, không bịa dữ kiện hoặc nguồn. |
| FR-004 | Trả lời dựa tài liệu có citation hợp lệ, nguồn còn được dùng; diễn giải có grounding, cho năm/mã ngành/tên chương trình có số đúng vai trò và khớp nguồn, không chặn chỉ vì chữ số/từ khóa hoặc thêm semantic parser. |
| FR-005 | Số liệu quan trọng chỉ trích nguyên văn từ native context đọc rõ đúng năm/cơ sở/ngành/phương thức/điều kiện khi liên quan; không tự tính hoặc dự báo. |
| FR-006 | Gemini key chỉ backend, một lần gọi/request, không retry quota/model fallback; một timeout tổng60s cho luồng chat, không lưu kết quả đến muộn; lỗi key/quota/timeout phân biệt, không cơ chế hủy CPU phức tạp. |
| FR-007 | UTC crawl HTML/PDF/ảnh đúng phạm vi URL và quyền; upload PDF/TXT UTF-8/PNG/JPG/JPEG tối đa 20 MiB. |
| FR-008 | PyMuPDF trước OCR; chất lượng thấp/bảng số không rõ cách ly; OCR không dùng trả số liệu; native hợp lệ tự index. |
| FR-009 | Metadata title, URL/origin, publisher nếu biết, published_at, year/campus/method nếu rõ, collected/updated, content/status/error; không đoán năm từ ngày đăng. |
| FR-010 | Upload có source_url hoặc provenance_note trim NFC 1–2.000 ký tự; URN chỉ định danh, note đọc lại đúng sau restart, note riêng không lộ public. |
| FR-011 | Identity origin độc lập hash: UUID riêng mỗi upload, URL chuẩn hóa cho web; content_hash+ngữ cảnh chống trùng document, giữ nhiều provenance cùng URL/bytes mà không lỗi UNIQUE hoặc gộp khác năm/cơ sở. |
| FR-012 | Lưu cấu hình chỉ mục; cùng nội dung/cấu hình không re-embed; bản đổi chỉ thay khi thành công, lỗi giữ bản tốt. Index thành công truy xuất ngay không cần train lại model. |
| FR-013 | Chỉ document còn tồn tại, state=ready và enabled=true, có nguồn allowed mới được retrieval; kiểm lại trước trả lời. |
| FR-014 | Ghi kiểm tra robots/terms/reuse/rate/time; unknown/denied/403/CAPTCHA chặn, 429 tôn trọng Retry-After, không bypass/SSRF. |
| FR-015 | Job có nội dung, đơn vị, nguồn từng tin và thời điểm; TopCV chỉ khi allowed, CSV/JSON có quyền là fallback. |
| FR-016 | Import log từng dòng và counts new/updated/skipped/error theo job identity; giữ dòng hợp lệ đầu tiên trong file, dòng sau giống nghiệp vụ skipped, khác nghiệp vụ error/conflict. Thời gian quan sát đổi đơn thuần không updated; dòng lỗi không loại dòng đúng. |
| FR-017 | Job open/expired/unverified; lọc ngành theo nhóm nghề minh bạch có nguồn; không đếm hết hạn/chưa xác minh là đang tuyển. |
| FR-018 | Job identity ưu tiên source_id+external_id tin cậy, thiếu dùng source_id+canonical_url; cùng source/URL có hai external_id khác nhau error/identity_conflict trước ghi. Khác URL cùng text không tự gộp. COUNT job hợp lệ, không document/toàn thị trường; thiếu khác0. |
| FR-019 | APScheduler00:00 Asia/Ho_Chi_Minh khi backend chạy; manual không đổi cron. Busy tại giờ lịch bỏ lượt, log skipped_busy khác failed; không lưu chờ/chạy lại hoặc chạy bù lúc khởi động. Ngày sau vẫn chạy00:00. |
| FR-020 | Admin “Crawl ngay” trả202 run_id/state qua worker nền, busy409; chung pipeline lịch. Stop sau item hiện tại, rerun ID mới/skip unchanged; không dừng chat hoặc đổi cron. |
| FR-021 | Run/items/source outcomes/counters và last_success đúng; lỗi giữ cũ; restart đánh run dở interrupted theo cấu hình một process. |
| FR-022 | Quiz 10 câu bắt buộc, đáp án1–5; mapping direction positive/negative/none và công thức công khai; GET /quiz có ready/data_missing tường minh. |
| FR-023 | Rule scoring thuận/nghịch theo US5, none không vào tổng/mẫu số/lý do; top3–5 điểm dương, lý do đúng chiều trả lời và đặc điểm ngành có nguồn; không dùng Gemini hoặc điểm học tập. |
| FR-024 | Quiz/catalogue thiếu, rubric cũ, no_match/insufficient_matches xử lý rõ; kết quả chỉ tham khảo, không đảm bảo trúng tuyển. |
| FR-025 | Catalogue chỉ ngành UTC từ nguồn chính thức còn dùng được; câu hỏi điểm chuẩn vẫn phục vụ qua RAG tài liệu. |
| FR-026 | Register/login/logout; email trim case-normalized duy nhất, password 8–128 ký tự, Argon2, JWT 30 phút có session thu hồi. |
| FR-027 | Role USER/ADMIN từ DB; đăng ký luôn USER, tạo Admin bằng CLI local; không nâng quyền client. |
| FR-028 | Backend xác thực/role/owner trên mọi protected API; invalid Bearer không downgrade Guest, Admin không đọc hội thoại khác. |
| FR-029 | Guest không lưu DB/log nội dung hoặc chuyển chat sang tài khoản; chat công khai khác dữ liệu cá nhân. |
| FR-030 | Owner CRUD/tiếp tục hội thoại, title trim 1–100 mặc định Hội thoại mới, tin có thứ tự; xóa cascade messages. |
| FR-031 | Lưu cặp user/assistant nguyên tử khi có kết quả; service failure không answered/không tin mồ côi; nguồn snapshot unavailable khi thay/vô hiệu hóa. |
| FR-032 | Admin upload tự extraction/index, xem/tìm/lọc/detail/disable/enable/delete; disabled không tự bật kể cả nội dung đổi. Xóa thật liên kết, không lưu dấu chặn; được crawl lại. UI xác nhận/nói rõ hành vi xóa. |
| FR-033 | UI đầy đủ US8, route guard cho tiện dụng và backend quyền thực; loading/empty/error/missing responsive. |
| FR-034 | API validation/lỗi thống nhất, không lộ key/password/path/stack; log request metadata, không nội dung Guest, không auto retry POST. |
| FR-035 | Tách frontend/backend; stack theo plan, uv + uv.lock backend và npm + package-lock frontend, hướng dẫn local tái lập. |
| FR-036 | Tests chức năng chính, bảo mật, nguồn, incremental, quiz, run; dữ liệu demo có manifest hợp lệ, fixture cách ly và ghi nhãn. |

## Edge cases

- “Năm nay” dùng giờ VN; ngữ cảnh thiếu ảnh hưởng số thì hỏi lại. Năm cũ chỉ trình bày
  khi người hỏi chấp nhận và ghi năm; nguồn mâu thuẫn không tự chọn số đúng.
- URL lỗi, PDF mật khẩu/hỏng/quá 200 trang, thiếu tessdata, HTML trang lỗi, OCR timeout:
  ghi lý do, không publish bản lỗi. Một item tối đa 5 phút; một trang OCR tối đa 60s.
- Raw bytes đổi nhưng normalized text và ngữ cảnh không đổi: không re-embed.
  Cùng URL đổi tài liệu khi nội dung cũ có origin khác: giữ tài liệu cũ cho origin kia.
- Không suy ngày đăng/năm/cơ sở; NULL là chưa biết, không thành 0. Deadline chỉ ngày
  kết thúc cuối ngày Việt Nam; thiếu hạn/căn cứ mở là unverified.
- CSV lỗi cấu trúc/JSON không phải array: 422 toàn tệp. URL sai/trùng vẫn có log theo dòng.
- Tài liệu chứa prompt injection: là dữ liệu; không cho truy cập file nội bộ, role hoặc key.
- Hết phiên trong khi chat: không lưu vào tài khoản khác hay Guest; lỗi 401.
  Hai request cùng hội thoại trả 409 CONVERSATION_BUSY.
- Không thể tự động chứng minh mọi câu diễn giải đều đúng; grounding/citations và
  đánh giá mẫu có người kiểm tra là mức đảm bảo của demo. Số liệu dùng đường trích dẫn bảo thủ.

## Success criteria và cổng nghiệm thu

| ID | Điều kiện đạt |
| --- | --- |
| SC-001 | Bộ30 câu fixture có expected status/source gồm đúng phạm vi, ngoài phạm vi, xã giao, mơ hồ, thiếu, xung đột, injection và mô tả chứa năm/mã ngành/tên chương trình có số; citation giả không lọt. |
| SC-002 | Bộ native số liệu và OCR mờ/thiếu cột: không đưa số sai/khác ngữ cảnh vào response; điểm chuẩn vẫn trả được từ native phù hợp. |
| SC-003 | 1mới/1đổi/1unchanged/1lỗi counters đúng, unchanged encode0; update lỗi giữ cũ. Disabled qua crawl/restart không bật; xóa thật rồi crawl nguồn còn có thể tạo lại. Nhiều provenance/context không unique sai. |
| SC-004 | Guest/USER/ADMIN và hai chủ sở hữu vượt qua ma trận 401/403/404, revoke phiên, Guest không DB/log; key không trong response/log/bundle. |
| SC-005 | GET /quiz đủ hai schema; ít nhất6 bộ đáp án có expected score/order/reason cho positive/negative/none; biên1/3/5, tie/zero/thiếu/rubric cũ đúng, không có input điểm xét tuyển. |
| SC-006 | Import đủ new/updated/skipped/error, first-valid-wins và conflict trong file; identity_conflict không đổi job/origin cũ. Cùng identity đổi nghiệp vụ so DB updated, chỉ observation đổi skipped; hai URL cùngtext thiếuID vẫn2jobs/count2; nguồn/status/time/filter đúng. |
| SC-007 | Manual10:00 không đổi00:00 ngày sau; cron busy ghi skipped_busy, không ingestion/items/error và không chạy khi slot rảnh hoặc restart; manual409, max pipeline1; stop/rerun an toàn, update lỗi giữ cũ. |
| SC-008 | UI đủ trang/role ở 360/768/1366 px; state tải/rỗng/lỗi/missing và thao tác stop/source/history dùng được. |
| SC-009 | Fixture tests offline mặc định; ghi latency10 câu warm CPU (mục tiêu9/10<=30s); timeout tổng chat60s và kiểm trước lưu, không lưu kết quả muộn. Đo riêng sai lệch điều phối/transaction ngắn, không hứa SLA hay hủy CPU tức thì. |
| SC-010 | Theo README chạy local: tài liệu UTC hợp lệ cho RAG trả lời có nguồn, >=3 ngành UTC cho quiz, >=1 tin nghề nghiệp hợp lệ; demo ingestion thủ công→retrieval, authentication/history/Admin thành công, manifest/bằng chứng thật. data_missing đúng là nhánh lỗi đạt, không thay thành công demo chính. |

## Liên kết thiết kế

[Plan](plan.md), [Architecture](architecture.md), [Research](research.md),
[Data model](data-model.md), [REST](contracts/rest-api.md),
[Testing](testing.md), [Quickstart](quickstart.md), [Tasks/coverage](tasks.md),
[Checklist](checklists/requirements.md).
