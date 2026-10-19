# 0002. `faiss_id` là vị trí trong `keyframes.json`; nhóm N nối vào cuối

Trạng thái: Đang áp dụng

## Bối cảnh

Nhiều artifact cần trỏ tới cùng một keyframe: hai index FAISS, document Elasticsearch, mask lọc traffic và intro. Embedding `.npy` được trích trên Kaggle theo thứ tự ảnh trong từng video.

## Quyết định

Vị trí của keyframe trong `keyframes.json` chính là id của nó trong FAISS và trong Elasticsearch (`faiss_id`). Nhóm N (camera giao thông) được `append_traffic_index.py` nối vào cuối manifest, FAISS và object index, nên vị trí của L, M, S không đổi.

Hợp đồng này được kiểm tra:

- `build_faiss_index.py` ghi `<model>.index.meta.json` với order hash; backend từ chối index lệch.
- `build_es_index.py` ghi `keyframe_order` và `keyframe_count` vào `_meta` của mapping; backend so hash của đúng số keyframe đó, và bỏ nguồn ASR nếu lệch. Nhờ so theo tiền tố, index ES build trước khi nối N vẫn hợp lệ.
- Hàm hash ở `scripts/_common.py` và ở backend được giữ giống nhau bằng một test.
- `objects_index.json` khoá theo `keyframe_id`, không theo vị trí, nên không cần hash.

Các script ghi kết quả qua file tạm rồi `os.replace`, để một lần chạy bị dừng giữa chừng không làm hỏng manifest.

## Hệ quả

- Lọc là phép toán trên mảng boolean, gửi sang ES dưới dạng khoảng `faiss_id`.
- Thêm hoặc bớt keyframe L, M, S buộc build lại từ bước 1 đến bước 5.
- Mọi artifact sinh ra phải thuộc cùng một lần build; gói dữ liệu không mang số phiên bản riêng, chỉ có các hash ở trên.

## Khi nào xem lại

Khi cần thêm nhóm dữ liệu mới mà không muốn build lại toàn bộ: cân nhắc id ổn định (ví dụ `keyframe_id` → id số trong một bảng ánh xạ) thay cho vị trí.
