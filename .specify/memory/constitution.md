# Hiến chương UTC Admissions RAG Chatbot

## Nguyên tắc cốt lõi

### I. Đơn giản, dễ hiểu, dễ bảo trì

PHẢI chọn giải pháp đơn giản nhất đáp ứng yêu cầu bài tập lớn. Mỗi thành phần PHẢI có
trách nhiệm rõ ràng; hướng dẫn chạy demo PHẢI đủ để khởi động trên máy cá nhân.

### II. Giới hạn hạ tầng

KHÔNG sử dụng Docker, Kubernetes, Redis, microservices hoặc cơ sở dữ liệu đám mây.
Dữ liệu và chỉ mục PHẢI lưu cục bộ; không yêu cầu hạ tầng production để chạy demo.

### III. Tách frontend và backend

Frontend và backend PHẢI có mã nguồn, cấu hình và lệnh chạy riêng, giao tiếp qua API
có đầu vào và đầu ra xác định. Backend PHẢI chịu trách nhiệm xử lý dữ liệu và RAG.

### IV. Gemini sinh câu trả lời, embedding cục bộ

Chỉ được dùng Gemini API để sinh câu trả lời. Mọi embedding tài liệu và câu hỏi
PHẢI do model chạy trên máy cá nhân tạo ra; KHÔNG gọi API embedding bên ngoài.

### V. Giới hạn phạm vi tư vấn

Chatbot chỉ được trả lời về tuyển sinh UTC và định hướng nghề nghiệp liên quan đến
ngành đào tạo của UTC, ngoài ngoại lệ xã giao ở mục VIII. Câu hỏi ngoài phạm vi
PHẢI được từ chối ngắn gọn và hướng người dùng về chủ đề được hỗ trợ.

### VI. Không suy đoán số liệu

KHÔNG tự tạo, suy diễn hoặc ngoại suy dữ liệu tuyển sinh, điểm chuẩn, chỉ tiêu,
học phí hay số lượng việc làm. Số liệu PHẢI khớp nguồn và nêu năm, ngành, cơ sở
hoặc điều kiện áp dụng khi có; thiếu căn cứ thì PHẢI thông báo chưa đủ dữ liệu.

### VII. Câu trả lời có nguồn kiểm chứng

Mọi câu trả lời dựa trên tài liệu PHẢI dẫn nguồn hỗ trợ trực tiếp cho thông tin
được nêu, gồm tên tài liệu và URL hoặc định danh tài liệu cục bộ có thể tra cứu.
KHÔNG tạo nguồn giả hoặc gắn nguồn không chứa thông tin được trả lời.

### VIII. Chấp nhận xã giao

Chatbot PHẢI phản hồi được lời chào, cảm ơn và tạm biệt thông thường. Phản hồi
thuần xã giao không cần nguồn; phần tư vấn kèm theo vẫn PHẢI tuân thủ các mục V–VII.

### IX. Dữ liệu có xuất xứ

Mỗi tài liệu đưa vào kho PHẢI lưu tên, đơn vị phát hành nếu xác định được, URL gốc
hoặc nguồn cung cấp tệp, thời điểm thu thập và kỳ/năm áp dụng nếu có. Tài liệu
không xác định được nguồn gốc KHÔNG được dùng làm căn cứ trả lời.

### X. Không embedding lại tài liệu không đổi

PHẢI lưu dấu vân tay nội dung và cấu hình embedding/chia đoạn đã dùng. Khi cả nội dung
và cấu hình xử lý không đổi, PHẢI tái sử dụng embedding; chỉ xử lý lại phần bị ảnh hưởng
khi tài liệu hoặc cấu hình thay đổi. Chạy nhập lại cùng dữ liệu PHẢI bỏ qua embedding.

### XI. Backend kiểm tra xác thực và vai trò

Backend PHẢI xác thực người gọi và kiểm tra vai trò trên mọi API yêu cầu đăng nhập
hoặc phân quyền; KHÔNG chỉ dựa vào việc ẩn chức năng ở frontend. API quản trị PHẢI
từ chối người chưa đăng nhập hoặc sai vai trò. API công khai PHẢI được khai báo rõ.

### XII. Không lưu bí mật trong mã nguồn

API key, mật khẩu và thông tin xác thực PHẢI được cấp qua biến môi trường hoặc
cấu hình cục bộ được loại khỏi Git. KHÔNG ghi bí mật vào mã nguồn, tệp mẫu, log
hoặc bundle frontend; Gemini API key chỉ được sử dụng ở backend.

### XIII. Chỉ thêm độ phức tạp khi có nhu cầu

Mọi công nghệ hoặc lớp kiến trúc mới PHẢI gắn với yêu cầu cụ thể, ghi rõ lý do và
vì sao giải pháp hiện có không đáp ứng. KHÔNG thêm để dự phòng nhu cầu chưa có;
việc bổ sung vẫn PHẢI tuân thủ các giới hạn của hiến chương.

### XIV. Chức năng mới có tiêu chí kiểm thử

Trước khi triển khai, mỗi chức năng mới PHẢI có đầu vào, kết quả mong đợi và tiêu chí
đạt/trượt; PHẢI có tình huống thành công và lỗi liên quan. Trước khi đánh dấu hoàn tất,
PHẢI ghi kết quả kiểm thử thủ công hoặc tự động tương xứng với phạm vi chức năng.

### XV. Hiển thị trung thực trạng thái thiếu dữ liệu

Khi chưa có dữ liệu thật hoặc không tìm thấy căn cứ phù hợp, API và giao diện PHẢI
thể hiện rõ trạng thái thiếu dữ liệu. KHÔNG tạo dữ liệu giả rồi trình bày là thông tin
chính thức; dữ liệu kiểm thử, nếu dùng, PHẢI tách riêng và ghi rõ là dữ liệu giả lập.

### XVI. Thu thập và tái sử dụng dữ liệu đúng quyền

Trước khi thu thập, PHẢI kiểm tra và ghi nhận robots.txt khi áp dụng, điều khoản sử dụng,
giới hạn truy cập và quyền tái sử dụng. KHÔNG vượt cơ chế hạn chế hoặc coi việc truy cập
công khai là quyền tái sử dụng. Nếu bị cấm hoặc chưa rõ quyền, PHẢI dừng thu thập hay sử dụng
nguồn đó cho đến khi được làm rõ; PHẢI tuân thủ tốc độ và yêu cầu dừng của nguồn.

## Phạm vi và ràng buộc

Đây là bài tập lớn đại học, chạy và demo trên máy cá nhân; không đặt yêu cầu vận hành
production. Gemini API là dịch vụ bên ngoài được phép cho sinh câu trả lời; embedding,
lưu trữ và truy xuất dữ liệu chạy cục bộ. Không bắt buộc bổ sung công nghệ cụ thể khi
chưa có yêu cầu. Tài liệu tuyển sinh PHẢI được đối chiếu đúng kỳ/năm và phạm vi áp dụng;
khi nguồn mâu thuẫn mà chưa xác minh được, PHẢI báo rõ thay vì tự chọn một số liệu.

## Quy trình và tiêu chí kiểm tra

- Đặc tả và kế hoạch PHẢI đối chiếu 16 nguyên tắc trước khi triển khai.
- Khi thay đổi xử lý câu hỏi, PHẢI kiểm tra: đúng phạm vi, ngoài phạm vi, xã giao,
  câu trả lời có nguồn và trường hợp thiếu dữ liệu hoặc thiếu căn cứ cho số liệu.
- Khi thay đổi nhập liệu, PHẢI kiểm tra xuất xứ, quyền thu thập/tái sử dụng và việc
  nhập lại tài liệu không đổi không phát sinh embedding mới.
- Khi thay đổi API hoặc bảo mật, PHẢI kiểm tra người chưa đăng nhập, đúng vai trò,
  sai vai trò và việc bí mật không xuất hiện trong mã nguồn hay phản hồi frontend.
- Mỗi thay đổi PHẢI có bằng chứng kiểm tra phù hợp; không bắt buộc hạ tầng kiểm thử
  production hoặc tự động hóa toàn bộ cho bản demo.

## Quản trị

Hiến chương là căn cứ ưu tiên khi lập đặc tả, kế hoạch, nhiệm vụ và rà soát thay đổi.
Mâu thuẫn PHẢI được giải quyết trước khi triển khai; không được tự miễn trừ nguyên tắc.

Mọi sửa đổi PHẢI ghi lý do, tác động, phiên bản, ngày sửa và được người phụ trách dự án
thông qua. Quy tắc phiên bản: tăng MAJOR khi loại bỏ hoặc định nghĩa lại nguyên tắc
không tương thích; tăng MINOR khi thêm hoặc mở rộng đáng kể nguyên tắc/mục; tăng PATCH
khi chỉ làm rõ câu chữ mà không đổi nghĩa. Ngày thông qua ban đầu PHẢI được giữ nguyên.

Mỗi lần rà soát thay đổi và trước demo PHẢI kiểm tra tuân thủ; vi phạm chưa giải quyết
PHẢI được ghi nhận và khắc phục trước khi đánh dấu phần việc liên quan hoàn tất.

**Phiên bản**: 1.0.0 | **Ngày thông qua**: 2026-11-13 | **Sửa đổi gần nhất**: 2026-11-13
