# 0004. Fusion bằng RRF có trọng số điểm, chuẩn hoá lại theo nguồn có kết quả

Trạng thái: Đang áp dụng

## Bối cảnh

Một lần tìm gộp ba nguồn có thang điểm khác nhau: cosine của SigLIP/BEiT-3 (có thể nhiều biến thể truy vấn và nhiều model), BM25 của Elasticsearch, và điểm object trong [0, 1]. Nguồn ASR có thể không chạy (ES tắt, index lệch).

## Quyết định

`services/retrieval/fusion.py`:

- Mỗi danh sách visual được chuẩn hoá min-max rồi cộng dồn theo `score / (60 + rank)`; tổng visual được min-max lần nữa.
- BM25 chia cho hit tốt nhất; điểm ASR của một shot được chia cho mọi keyframe cùng shot.
- Điểm object được tính cho mọi ứng viên đã gộp, không chỉ top-k của nguồn object.
- Trọng số từng nguồn (mặc định, hoặc do Gemini đề xuất khi bật Enhance query) được chuẩn hoá lại trên các nguồn thực sự trả về ứng viên.

Mỗi nguồn là một `Modality`; thêm một nguồn mới (ví dụ OCR) là thêm một lớp, không sửa công thức gộp.

## Hệ quả

- Một nguồn hỏng không kéo điểm của các nguồn còn lại xuống; giao diện nhận cảnh báo thay vì lỗi.
- Hằng số 60 và các bước chuẩn hoá chưa được tinh chỉnh bằng bộ truy vấn có nhãn: repo có `scripts/evaluate_retrieval.py` nhưng chưa có tập truy vấn đi kèm.

## Khi nào xem lại

Khi đã có tập truy vấn có nhãn: so Recall@K và MRR của các biến thể (hằng số RRF, chuẩn hoá z-score, trọng số học từ dữ liệu) trước khi đổi.
