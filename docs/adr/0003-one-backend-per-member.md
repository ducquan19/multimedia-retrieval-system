# 0003. Mỗi thành viên chạy một backend riêng, chỉ nghe localhost

Trạng thái: Đang áp dụng

## Bối cảnh

Ứng dụng là công cụ cho một đội thi. Mỗi thành viên có dữ liệu trên máy mình (gói index nhận từ người build) và Elasticsearch trong Docker của máy đó. API không có xác thực, và endpoint nộp bài dùng tài khoản DRES của đội.

## Quyết định

Mỗi thành viên chạy backend và frontend của mình (`scripts/dev.py`). Mặc định backend chỉ trả lời request từ chính máy đó (`factories/middleware.py`, `AIC_ALLOW_REMOTE_CLIENTS=false`); Vite proxy nối tới nó qua localhost.

## Hệ quả

- Không cần đăng nhập hay quản lý phiên; bí mật (Gemini, DRES, Hugging Face) chỉ nằm trong `.env` của từng máy.
- Chặn nộp trùng và lịch sử nộp (`dres_submissions.jsonl`) chỉ có tác dụng trong một backend: hai người nộp cùng một đáp án từ hai máy thì không bị chặn.
- Mọi máy phải đủ RAM cho toàn bộ dữ liệu (xem 0001). `dev.py` gắn các server con vào một Job Object trên Windows để chúng không bị bỏ lại khi `dev.py` bị dừng đột ngột.

## Khi nào xem lại

Khi đội cần chặn trùng giữa các máy, hoặc khi máy thành viên không đủ RAM: chạy một backend dùng chung (có GPU), thêm xác thực, rồi mới bật `AIC_ALLOW_REMOTE_CLIENTS`.
