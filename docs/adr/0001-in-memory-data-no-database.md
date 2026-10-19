# 0001. Nạp toàn bộ metadata và index vào RAM, không dùng cơ sở dữ liệu

Trạng thái: Đang áp dụng

## Bối cảnh

Dữ liệu tìm kiếm chỉ đọc trong lúc thi: khoảng 444k keyframe (`keyframes.json`), hai index FAISS phẳng (SigLIP 1152 chiều, BEiT-3 768 chiều), object index và metadata camera giao thông. Dữ liệu chỉ đổi khi một người build lại và gửi gói mới.

## Quyết định

Backend đọc mọi thứ vào RAM khi khởi động (`core/lifespan.py`, `core/container.py`): manifest thành `KeyframeCollection` bất biến, FAISS bằng `faiss.read_index`, object index thành posting list. Thứ duy nhất ghi ra đĩa lúc chạy là `dres_submissions.jsonl`. Transcript tìm bằng BM25 trong Elasticsearch chạy local.

## Hệ quả

- Tìm kiếm không có độ trễ truy vấn DB; lọc theo traffic hay intro là mask nhị phân trên `faiss_id`.
- Khởi động mất khoảng 20–30 giây trên CPU; RAM cần khoảng 6–7 GB với cả hai model. Một backend bị bỏ lại (xem 0003) giữ nguyên lượng bộ nhớ đó.
- Đổi dữ liệu phải khởi động lại backend.

## Khi nào xem lại

Khi số keyframe tăng tới mức một máy thành viên không còn đủ RAM, hoặc khi đội cần dùng chung một server: cân nhắc index FAISS nén (IVF/PQ) hoặc memory-map, và tách metadata ra khỏi tiến trình.
