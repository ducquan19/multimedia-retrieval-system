# Architecture Decision Records

Mỗi file ghi một quyết định kiến trúc: bối cảnh, quyết định, hệ quả và khi nào nên xem lại. Lý do được lấy từ code, comment và README tại thời điểm viết; chỗ nào chưa rõ lý do ban đầu thì ghi là chưa rõ.

| # | Quyết định | Trạng thái |
| --- | --- | --- |
| [0001](0001-in-memory-data-no-database.md) | Nạp toàn bộ metadata và index vào RAM, không dùng cơ sở dữ liệu | Đang áp dụng |
| [0002](0002-faiss-id-is-manifest-position.md) | `faiss_id` là vị trí trong `keyframes.json`; nhóm N nối vào cuối | Đang áp dụng |
| [0003](0003-one-backend-per-member.md) | Mỗi thành viên chạy một backend riêng, chỉ nghe localhost | Đang áp dụng |
| [0004](0004-score-weighted-rrf-fusion.md) | Fusion bằng RRF có trọng số điểm, trọng số chuẩn hoá lại theo nguồn có kết quả | Đang áp dụng |
| [0005](0005-layered-backend.md) | Backend chia tầng, luật phụ thuộc được test tự động | Đang áp dụng |

Thêm ADR mới khi một quyết định khó đảo ngược, ảnh hưởng nhiều module, hoặc từng gây tranh luận. Không sửa ADR cũ để đổi quyết định: viết ADR mới và đánh dấu ADR cũ là "Thay bởi #xxxx".
