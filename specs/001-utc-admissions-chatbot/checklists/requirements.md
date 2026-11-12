# Checklist yêu cầu và thiết kế

Ngày:2026-11-13. Phạm vi: rà soát tài liệu sau scope simplification.
[x] dưới đây chỉ nghĩa thiết kế đã có tiêu chí và task, không nghĩa source/tests đã chạy.

- [x] Hiến chương1.0.0 giữ nguyên16 nguyên tắc; demo local, tách FE/BE.
- [x] Quiz10 câu Likert1–5, scoring positive/negative/none công khai, có expected thuận/nghịch/none và lý do đúng chiều.
- [x] Top3–5 có score/reason/nguồn/disclaimer; tie/zero/ít hơn3/missing/stale có schema.
- [x] Request recommendation chỉ rubric_version/answers; Gemini không chấm/tạo ngành.
- [x] Catalogue UTC chính thức; chatbot vẫn trả điểm chuẩn từ native đúng context.
- [x] Scope/social/mixed/ngoài phạm vi/thiếu/mâu thuẫn có acceptance.
- [x] Gemini answer/evidence_ids thống nhất; validate schema/ID/nguồn, không parser claim.
- [x] Năm/mã ngành/tên chương trình có số hợp lệ không bị blanket guard; số trùng mã nhưng dùng làm định lượng vẫn bị chặn.
- [x] Số liệu quan trọng trích native nguyên văn/COUNT backend; OCR số không là căn cứ.
- [x] Không tuyên bố chứng minh tuyệt đối mọi narrative; golden review bổ sung grounding.
- [x] Hash/profile incremental, unchanged không encode, update lỗi giữ bản tốt.
- [x] Upload UUID riêng, URN không chứa fingerprint; URL partial unique chỉ web, nhiều provenance/context không unique sai.
- [x] Disable giữ flag qua crawl; enable thủ công; delete xóa thật và có thể crawl lại, không dấu chặn.
- [x] Native tự index; OCR lỗi/low-quality/bảng mơ hồ cách ly, không duyệt từng trang.
- [x] Jobs có origin đúng từng tin, nguồn JOIN, mapping nhóm nghề minh bạch.
- [x] CSV/JSON log mỗi record item_index, URL trùng/sai không làm mất log.
- [x] Quyền robots/terms/rate/reuse trước fetch/import, TopCV fallback hợp lệ.
- [x] JWT/revoke/RBAC/owner/Guest privacy và bí mật có kiểm thử trực tiếp.
- [x] Một outer timeout60s, CPU chỉ trả dữ liệu, handler duy nhất kiểm hạn rồi lưu; không hủy CPU/late-result registry.
- [x] Quota không retry, key/SDK-timeout/outer-timeout phân biệt, lỗi/kết quả muộn không lưu answered.
- [x] Một process/worker, một slot run; Crawl ngay202 nền, cron00:00 không reset, busy scheduled ghi skipped_busy và bỏ lượt, không tự chạy lại, stop/rerun an toàn.
- [x] Không đòi OS lock/test nhiều process cho demo; cấu hình unsupported ghi rõ.
- [x] uv/uv.lock và npm/package-lock nhất quán, PowerShell/Python3.13/Node24.22.1.
- [x] Unit/contract-stub/integration phân biệt; dependency/checkpoint/coverage trong tasks.
- [x] Không source code, không đổi nhánh hoặc commit/push/merge trong review.

## Cổng trước khi triển khai

- [x] Mọi FR-001..FR-036 và SC-001..SC-010 có task.
- [x] Không còn task/API/entity của phạm vi đã bỏ.
- [x] Các file thiết kế liên kết tương đối tới tài liệu tồn tại.
- [x] Không yêu cầu nghiệm thu integration trước dependency.

## Cổng trước demo (chưa thực hiện)

- [ ] Lock dependencies và smoke Python3.13/Node24.22.1/E5 CPU/Gemini retry control.
- [ ] Có tài liệu UTC hợp lệ cho RAG, >=3 ngành UTC usable và >=1 tin nghề nghiệp được phép; thiếu thì chưa đạt demo chính.
- [ ] Chạy unit/contract/core integration và security; ghi kết quả thật.
- [ ] Kiểm responsive/hành trình, latency/deadline và nguồn từng câu.
- [ ] Từ README demo upload→retrieval/RAG có nguồn, quiz ready/nghề có dữ liệu, auth/history/Admin; ghi actual/manifest; chỉ data_missing không đạt SC-010.

- [x] Job identity nguồn+external_id/URL, COUNTjob.id không document; CSV/JSON giữ publisher thực và kiểm quyền.
