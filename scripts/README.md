# Scripts

- `dev.py`: chạy backend và frontend cùng lúc (`python scripts/dev.py`).
- `evaluate_retrieval.py`: đo Recall@K và MRR của backend trên bộ truy vấn có nhãn (xem phần [Đánh giá](#đánh-giá)).
- Các script còn lại là bước tiền xử lý, mô tả bên dưới.

## Tiền xử lý dữ liệu

Các script chạy trên máy build để tạo dữ liệu mà backend đọc trong `data/` (`AIC_DATA_ROOT`). Phần trích xuất cần GPU (shot, ASR, embedding, OCR, object) nằm ở dạng notebook trong [`notebooks/`](../notebooks/README.md) để chạy trên Kaggle. Mỗi script là một chương trình dòng lệnh: xem tham số bằng `--help`, và script trả mã thoát khác 0 khi có lỗi, nên có thể nối chúng trong shell hoặc CI.

```powershell
python -m pip install -e "./backend[dev,scripts]" -c backend/requirements.lock
python scripts/<script>.py --help
```

Trên Windows, đặt `$env:PYTHONUTF8 = "1"` trước khi chạy `extract_youtube_transcript.py` (thông báo tiếng Việt) để console không báo `UnicodeEncodeError`.

## Thứ tự chạy

| Bước | Script / notebook | Đầu vào | Đầu ra |
| --- | --- | --- | --- |
| 0a | `notebooks/extract_scenes.ipynb` (Kaggle) | `videos/*.mp4` | `scenes/<video_id>.scenes.csv` |
| 0b | `notebooks/embed_siglip2.ipynb`, `embed_beit3.ipynb` (Kaggle) hoặc `embed_keyframes.py` | `keyframes/<video_id>/…` | `embeddings/{siglip,beit3}/<video_id>.npy` |
| 0c | `notebooks/extract_asr.ipynb` (Kaggle) hoặc `extract_youtube_transcript.py` | video + `scenes/` | `asr/<video_id>/S<shot>.json` |
| 1 | `generate_manifest.py` | `keyframes/`, `map-keyframes/`, `scenes/` | `keyframes.json` |
| 2 | `build_faiss_index.py` | `keyframes.json`, `embeddings/` | `indexing/{siglip,beit3}.index` + `.meta.json` |
| 3 | `build_es_index.py` | `keyframes.json`, `asr/` | index Elasticsearch `keyframes_metadata`, `asr_texts.json` |
| 4 | `build_object_index.py` | `objects/`, `map-keyframes/`, `scenes/` | `objects_index.json` |
| 5 | `append_traffic_index.py` | N: `traffic_keyframes/`, `traffic_probe/`, `embeddings/` | nối N vào `keyframes.json`, FAISS, `objects_index.json` |

Bước 0 chạy trên máy có GPU (notebook Kaggle, hoặc `embed_keyframes.py` trên Colab/Lightning/máy local). Bước 1–5 chạy trên máy build. Khi thêm hoặc bớt keyframe, phải chạy lại từ bước 1 đến bước 5, vì vị trí của keyframe trong `keyframes.json` chính là id của nó trong FAISS và Elasticsearch.

### Bất biến quan trọng: dòng i = keyframe thứ i

- Dòng `i` của `embeddings/<model>/<video_id>.npy` là ảnh thứ `i` của video, sắp theo số trong tên file (= dòng `n` của `map-keyframes/<video_id>.csv`).
- `build_faiss_index.py` đặt vector đó vào vị trí của keyframe tương ứng trong `keyframes.json`. Nếu số dòng `.npy` khác số keyframe của video, script **dừng** chứ không copy lệch. Video thiếu `.npy` cũng làm script dừng; chỉ khi chấp nhận vector 0 cho các video đó mới thêm `--allow-missing`.
- Script ghi `indexing/<model>.index.meta.json` chứa hash thứ tự `keyframe_id`. Khi khởi động, backend từ chối index nếu số vector, số chiều hoặc hash không khớp `keyframes.json`, thay vì trả kết quả sai mà không báo lỗi.
- Index Elasticsearch ghi `keyframe_order` và `keyframe_count` vào `_meta` của mapping. Backend so chúng với `keyframes.json`: lệch thì nguồn ASR bị bỏ qua kèm cảnh báo. Vì nhóm N được nối vào cuối, index build trước bước 5 vẫn hợp lệ.
- Mọi script ghi kết quả (manifest, FAISS, `.meta.json`, object index, `asr_texts.json`) qua file tạm rồi thay thế, nên script bị dừng giữa chừng không để lại file hỏng.
- `embed_keyframes.py`, notebook `embed_siglip2.ipynb` và backend dùng chung một commit SigLIP trên Hugging Face (`SIGLIP2_REVISION`, `MODEL_REVISION`, `AIC_SIGLIP_MODEL_REVISION`); một test kiểm tra ba giá trị này luôn trùng nhau. Khi đổi commit phải trích lại embedding.
- `embed_keyframes.py` và hai notebook embedding dừng ở ảnh lỗi thay vì bỏ qua ảnh đó, vì bỏ một ảnh sẽ làm lệch mọi dòng phía sau.

## Mô tả từng script

### Embedding ngoài Kaggle
- **`embed_keyframes.py`**: embedding ảnh SigLIP-2 (`--model siglip2`, 1152 chiều, pad ảnh thành hình vuông) hoặc BEiT-3 (`--model beit3`, 768 chiều, resize 384). Mã BEiT-3 dùng chung bản vendored trong `backend/src/infrastructure/beit3`, trọng số mặc định là `data/checkpoint/beit3_base_patch16_384_coco_retrieval.pth`. Thư mục ra là `siglip/` hoặc `beit3/`, đúng tên mà `build_faiss_index.py` đọc. `--map-dir` kiểm tra số lượng và thứ tự ảnh với `map-keyframes`; `--shard K/N` chia việc cho nhiều máy, `--archive` nén kết quả. Tiền xử lý giống hệt hai notebook `embed_siglip2.ipynb` và `embed_beit3.ipynb`.

### Transcript YouTube (M, S)

- **`extract_youtube_transcript.py`**: lấy phụ đề YouTube theo `watch_url` trong `media-info`, tự chuyển sang yt-dlp (có cookie) khi bị chặn IP, lưu tiến độ để chạy tiếp.

### Build index (máy build)

- **`generate_manifest.py`**: quét `data/keyframes/` và tạo `keyframes.json`.
- **`build_faiss_index.py`**: `--models siglip beit3`, `--allow-missing`.
- **`build_es_index.py`**: build tăng dần (chỉ đọc lại các thư mục ASR đã đổi). `--full` để build lại từ đầu; `--index-name` phải trùng `AIC_ES_INDEX_NAME`. Script không sửa `keyframes.json`; transcript để hiện trên giao diện được ghi vào `asr_texts.json`.
- **`build_object_index.py`**: `--min-score` (mặc định 0,3), `--shot-level-prefixes` (mặc định `L`).
- **`append_traffic_index.py`**: nối nhóm N vào cuối và ghi lại `.meta.json`. `--objects-only` và `--relink-images` xem trong `--help`.

## Đánh giá

Sau khi build lại index hoặc đổi tham số tìm kiếm, đo lại chất lượng bằng `scripts/evaluate_retrieval.py` (Recall@K, MRR trên một tập truy vấn có nhãn). Xem phần đầu file script để biết định dạng.
