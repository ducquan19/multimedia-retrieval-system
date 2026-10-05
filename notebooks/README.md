# Notebook Kaggle

Các bước trích xuất cần GPU, chạy trên Kaggle. Kết quả tải về rồi đặt vào `data/` trên máy build; sau đó chạy các script trong [`scripts/`](../scripts/README.md) để build index.

| Notebook | Làm gì | Đặt kết quả vào |
| --- | --- | --- |
| `extract_scenes.ipynb` | Chia shot bằng TransNetV2, SliTraNet loại điểm cắt sai | `data/scenes/` |
| `extract_asr.ipynb` | Whisper large-v3, chia lời thoại theo shot (cần `scenes/` trước) | `data/asr/` |
| `embed_siglip2.ipynb` | Vector ảnh SigLIP-2, 1152 chiều | `data/embeddings/siglip/` |
| `embed_beit3.ipynb` | Vector ảnh BEiT-3, 768 chiều | `data/embeddings/beit3/` |
| `extract_clip.ipynb` | Vector ảnh CLIP (thử nghiệm, backend chưa dùng) | `data/embeddings/clip/` |
| `extract_ocr.ipynb` | PaddleOCR tiếng Việt (thử nghiệm, backend chưa dùng) | `data/ocr/` |
| `extract_objects.ipynb` | YOLOv8x-oiv7 + SAM (khác định dạng object của BTC) | `data/od/` |

## Cách chạy

1. Tạo notebook trên Kaggle bằng **File → Import Notebook**, chọn file `.ipynb` trong thư mục này.
2. Thêm dataset đầu vào (keyframe, video, trọng số) và bật GPU (T4 x2 hoặc P100) trong Settings.
3. Sửa cell **Cấu hình**: đường dẫn dataset và `SHARD_INDEX` / `NUM_SHARDS`.
4. **Run All**. Cell cuối nén kết quả; tải file ở tab **Output**.

## Chia việc cho nhiều máy

Mỗi người chạy cùng notebook với `NUM_SHARDS` giống nhau và `SHARD_INDEX` khác nhau (1, 2, …). Danh sách được sắp xếp trước khi chia nên các phần không chồng nhau. `extract_asr.ipynb` chia theo dung lượng video để các máy xong gần cùng lúc.

Chạy lại notebook sẽ bỏ qua phần đã xong, nên có thể tiếp tục khi Kaggle ngắt phiên.

## Các bất biến không được phá

- Dòng *i* của `<video_id>.npy` là ảnh thứ *i* của video, sắp theo **số** trong tên file. Đây là thứ tự mà `build_faiss_index.py` dùng để ghép vector với `keyframes.json`.
- Ảnh lỗi làm **dừng** video đó thay vì bị bỏ qua, vì bỏ một ảnh sẽ làm mọi vector phía sau gắn nhầm keyframe. Sửa ảnh rồi chạy lại.
- Giữ nguyên tiền xử lý: SigLIP-2 pad ảnh thành hình vuông, BEiT-3 resize thẳng 384×384. Đổi cách này thì vector mới không còn cùng không gian với index đang dùng.
- File shot phải tên `<video_id>.scenes.csv`.

Notebook embedding có bản dòng lệnh tương đương để chạy ngoài Kaggle: `scripts/embed_keyframes.py`.
