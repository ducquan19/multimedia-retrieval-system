# AIC 2026 Retrieval Inspector

Ứng dụng web chạy local để tra cứu video, xem và sắp xếp lại kết quả truy vấn, sau đó nộp bài cho HCMC AI Challenge 2026.

## Các loại truy vấn

- **KIS — Textual Known Item Search:** nộp `<video_id>,<frame_id>`.
- **VQA — Visual Question Answering:** nộp `<video_id>,<frame_id>,<answer>`.
- **TRAKE — Temporal Retrieval and Alignment of Key Events:** nộp `<video_id>,<frame_id_1>,...,<frame_id_n>`.
- **TRAFFIC:** tìm trong video camera giao thông (nhóm N), lọc theo camera, thời gian và thời tiết.

Thứ tự các dòng nộp bài có ý nghĩa. Backend luôn giữ nguyên thứ tự nhận từ client, không sắp xếp lại theo thứ hạng tìm kiếm cũ.

## Công nghệ

### Backend

- Python 3.12+
- FastAPI và Uvicorn
- Pydantic v2 và pydantic-settings
- FAISS (index SigLIP và BEiT-3)
- Elasticsearch (tìm BM25 trên transcript)
- Google Gemini 3.5 Flash Lite (Enhance query, KIS Query Understanding & Planning)
- Kiến trúc stateless, metadata lưu trong SQLite

### Frontend

- React và TypeScript (strict mode)
- Vite
- TanStack Query
- dnd-kit (kéo thả để sắp xếp lại kết quả)
- Vitest, React Testing Library và Playwright

## Yêu cầu

- Python 3.12 trở lên
- Node.js 22 trở lên, npm 10 trở lên
- Docker (để chạy Elasticsearch)
- Google Gemini API key (Developer API hoặc Enterprise) cho Enhance query

## Cài đặt nhanh

### 1. Tạo môi trường Python

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Cài thư viện

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r .\backend\requirements.lock
python -m pip install --no-deps -e .\backend
npm --prefix frontend ci
```

### 3. Cấu hình môi trường

```powershell
Copy-Item .env.example .env
```

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `AIC_DATA_ROOT` | `./data` | Thư mục gốc chứa dữ liệu (xem [Chuẩn bị dữ liệu](#chuẩn-bị-dữ-liệu)) |
| `AIC_FRONTEND_ORIGIN` | `http://localhost:5173` | Origin của frontend khi dev |
| `AIC_GEMINI_API_KEY` | trống | **Bắt buộc** cho Enhance query |
| `AIC_ENABLE_RERANKING` | `false` | Bật rerank BLIP-2 chạy local |
| `AIC_HF_TOKEN` | trống | Token đọc (read-only) Hugging Face để phát video trong repo riêng tư |
| `AIC_DRES_USERNAME`, `AIC_DRES_PASSWORD` | trống | Tài khoản nộp bài DRES |
| `AIC_DRES_BASE_URL` | `https://eventretrieval.one` | Địa chỉ server DRES |

Top-K mặc định là `100`, tối đa `500`.

### 4. Chuẩn bị dữ liệu

Làm theo mục [Chuẩn bị dữ liệu](#chuẩn-bị-dữ-liệu) bên dưới.

### 5. Chạy ứng dụng

```powershell
docker compose up -d      # Elasticsearch
python scripts/dev.py     # backend + frontend
```

- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>

## Chuẩn bị dữ liệu

Toàn bộ dữ liệu nằm dưới một thư mục gốc (`AIC_DATA_ROOT`, mặc định `./data`). Thư mục `data/` quá lớn nên không được đưa lên Git.

### Các tập dữ liệu

| Batch | Nhóm | Nội dung | Mã video | Keyframe |
| --- | --- | --- | --- | --- |
| Batch 1 | **L** | L21–L30 | `L21_V001` | Tự trích theo shot: `keyframes/<video_id>/S<shot>/F<frame>.jpg` |
| Batch 2 | **M** | Tin tức 60 Giây – HTV (M01–M10) | `M01_V001` | BTC cung cấp, không chia shot: `keyframes/<video_id>/<n>.jpg` |
| Batch 2 | **N** | Camera giao thông (N001–N100) | `N001-V001` | BTC cung cấp, không chia shot: `keyframes/<video_id>/<n>.jpg` |
| Batch 2 | **S** | Thể thao – HTV Thể Thao (S01) | `S01-V001` | BTC cung cấp, không chia shot: `keyframes/<video_id>/<n>.jpg` |

Lưu ý:

- Nhóm M dùng dấu gạch dưới (`M01_V001`), còn nhóm N và S dùng dấu gạch ngang (`N001-V001`). Giữ nguyên tên thư mục như BTC cung cấp, vì các file `objects/`, `map-keyframes/` và `keyframes/` được ghép với nhau theo đúng tên này.
- Keyframe batch 2 được đặt tên theo số thứ tự `n` (`001.jpg`, `002.jpg`, ...). Số frame thật được tra trong `map-keyframes/<video_id>.csv` (cột `n` → `frame_idx`).

### Link tải

**Batch 1 (L)** — Kaggle:

- [Keyframes batch 1](https://kaggle.com/datasets/d7aa43eea17237235450ede4a409cb562ff02d218a1340f4d6bdcdfe19a9d50c) → `data/keyframes/`
- [Embeddings SigLIP / BEiT-3](https://kaggle.com/datasets/c7b426cfb41d654ce995b9e35eb3a108167d65a6640caf0cd6af82e18d58b89a) → `data/embeddings/`
- [ASR (Whisper, theo shot)](https://kaggle.com/datasets/e2642647173eb4867e6f7ca12b592843b60e5ddb16dc76f08288fd816c6d0fd5) → `data/asr/`
- Video gốc: [dwctien/aic-2026-videos](https://www.kaggle.com/datasets/dwctien/aic-2026-videos)

**Batch 2 (M, N, S):**

- Keyframes, `map-keyframes`, `objects` và `media-info` do BTC cung cấp. Mỗi gói keyframe có dạng `Keyframes_<nhóm>/keyframes/<video_id>/*.jpg`. _(bổ sung link BTC)_
- Video gốc: [dwctien/aic26-videos-batch2](https://www.kaggle.com/datasets/dwctien/aic26-videos-batch2)

**Dùng chung:**

- [BEiT-3 checkpoint](https://kaggle.com/datasets/d41406373d9f714c275a2fd01c5222f46437b426c357abf603195a41eafa3228) → `data/checkpoint/`
- Trọng số TransNetV2 (chia shot): [trncqun/transnetv2-weights](https://www.kaggle.com/datasets/trncqun/transnetv2-weights)

### Cấu trúc thư mục `data/`

```text
data/
├── keyframes/
│   ├── L21_V001/                    # Batch 1: chia theo shot
│   │   ├── S00000/
│   │   │   ├── F000008.jpg          # F<frame_idx>
│   │   │   └── ...
│   │   └── ...
│   ├── M01_V001/                    # Batch 2: không chia shot
│   │   ├── 001.jpg                  # <n>, tra frame trong map-keyframes
│   │   └── ...
│   ├── N001-V001/
│   └── S01-V001/
├── map-keyframes/                   # <video_id>.csv: n,pts_time,fps,frame_idx
├── objects/                         # <video_id>/<n>.json: kết quả nhận diện vật thể của từng keyframe
├── scenes/                          # <video_id>.scenes.csv: ranh giới shot (L, M)
├── asr/                             # <video_id>/S<shot>.json: transcript theo shot
├── embeddings/
│   ├── siglip/<video_id>.npy
│   └── beit3/<video_id>.npy
├── checkpoint/                      # beit3.spm, beit3_base_patch16_384_coco_retrieval.pth
│
│   # Các file dưới đây do script sinh ra
├── keyframes.json                   # generate_manifest.py
├── indexing/
│   ├── siglip.index                 # build_faiss_index.py
│   └── beit3.index
├── objects_index.json               # build_object_index.py
├── video_sources.json               # generate_video_sources.py
├── metadata.db
└── dres_submissions.jsonl           # lịch sử nộp DRES, backend tự ghi
```

### Sắp xếp keyframe batch 2 vào `data/keyframes/`

Chép (hoặc di chuyển) từng thư mục video trong các gói của BTC vào `data/keyframes/`, giữ nguyên tên thư mục video:

```powershell
Get-ChildItem data\Keyframes_*\keyframes -Directory | ForEach-Object {
    Get-ChildItem $_.FullName -Directory | Move-Item -Destination data\keyframes\
}
```

Sau đó có thể xoá các thư mục `Keyframes_*` và file `.zip` đã giải nén.

### Các bước build dữ liệu

Chạy theo đúng thứ tự dưới đây. Mỗi khi thêm hoặc bớt keyframe, cần chạy lại từ bước 1.

1. **Tạo `keyframes.json`**. Script quét `data/keyframes/`:
   - Thư mục chia shot `S*/F<frame>.jpg` (batch 1): `frame_id` lấy từ tên file.
   - Thư mục phẳng `<n>.jpg` (batch 2): `frame_id` tra trong `map-keyframes`. Với video có `scenes/` (nhóm M), keyframe được gán `segment_id` theo shot để ghép với transcript.

   ```powershell
   python scripts/generate_manifest.py
   ```

2. **Build FAISS index** từ các file `.npy`. Thứ tự vector trong mỗi file `.npy` phải khớp với thứ tự keyframe khi trích embedding: batch 1 theo thư mục shot rồi tên file, batch 2 theo số `n` tăng dần.

   ```powershell
   python scripts/build_faiss_index.py
   ```

3. **Build Elasticsearch index (BM25)** cho transcript. Cần chạy Elasticsearch (`docker compose up -d`) trước.

   ```powershell
   python scripts/build_es_index.py
   ```

4. **Build object index** cho nguồn tìm kiếm **Object**. Script đọc `objects/`, `map-keyframes/` và `scenes/`, rồi ghi ra `data/objects_index.json`:
   - Keyframe batch 2 (M, N, S) được ghép với đúng keyframe của BTC có cùng `frame_idx`.
   - Keyframe tự trích của batch 1 (L) nhận objects gộp của mọi keyframe BTC nằm trong cùng shot.

   ```powershell
   python scripts/build_object_index.py
   ```

   Các kết quả nhận diện có điểm dưới `--min-score` (mặc định `0.3`) bị loại. `--shot-level-prefixes` (mặc định `L`) chọn các nhóm luôn gộp objects theo shot.

5. **Khởi động lại backend** để nạp dữ liệu mới.

### Transcript (ASR)

Transcript được lưu theo shot, mỗi shot một file `data/asr/<video_id>/S<scene_id>.json`:

```json
{
    "video_id": "M01_V001",
    "scene_id": 5,
    "start_time_s": 21.44,
    "end_time_s": 23.0,
    "text": "Bình dân học vụ số sức lan tỏa từ cơ sở.",
    "segments": [{"start": 18.96, "end": 26.32, "text": "...", "overlap": 1.56}]
}
```

- **Batch 1 (L):** trích bằng Whisper large-v3 trên Kaggle (`scripts/extract_asr_kaggle.py`), rồi tải về `data/asr/`.
- **Batch 2 (M, S):** lấy phụ đề YouTube từ trường `watch_url` trong `media-info`. Cần có file `scenes/<video_id>.scenes.csv` trước; video chưa có scenes sẽ bị bỏ qua.

  ```powershell
  python -m pip install "youtube-transcript-api>=1.0" yt-dlp tqdm
  python scripts/extract_youtube_transcript.py --prefix M --cookies-from-browser firefox
  ```

  - Script ghi lại tiến độ vào `data/asr/_youtube_transcript_state.json`. Video đã xong hoặc không có phụ đề sẽ được bỏ qua ở lần chạy sau. Dùng `--overwrite` hoặc `--retry-missing` để chạy lại.
  - YouTube hay chặn IP (`IpBlocked`, `HTTP 429`) khi gửi nhiều request. Script sẽ tự nghỉ (`--cooldown`, mặc định 15 phút) rồi thử lại; bị chặn liên tiếp quá `--max-blocks` lần thì dừng. Khi đó hãy đổi mạng hoặc dùng `--proxy`, rồi chạy lại.
  - Cookie trình duyệt giúp ít bị chặn hơn. Trên Windows nên dùng `--cookies-from-browser firefox`, hoặc xuất cookie ra `cookies.txt` rồi dùng `--source ytdlp --cookies cookies.txt`. **Không commit file cookie** (đã có trong `.gitignore`), và nên dùng tài khoản YouTube phụ.

### Chia shot (scenes)

`scripts/extract_scenes.py` chia shot bằng TransNetV2 trên Kaggle và xuất `<video_id>.scenes.csv`:

```text
video_id,scene_id,start_frame,end_frame,start_time_s,end_time_s,duration_s,fps
```

Hiện đã có scenes cho nhóm L và M. Nhóm N và S chưa có. Keyframe của N và S vẫn được index bình thường, chỉ không có `segment_id` theo shot.

### Phát video

- **Video local:** đặt file vào `data/videos/<video_id>.mp4` rồi dùng nút "Open Local Video" trên giao diện.
- **Video từ xa:** `data/video_sources.json` lưu `remote_url` và `fps` của từng video, được tạo từ `data/metadata.json`:

  ```powershell
  python scripts/generate_video_sources.py
  ```

  Video nằm trong repo Hugging Face riêng tư (`dwctien/aic26-videos-private`) dùng `private_path` thay cho `remote_url`, và cần đặt `AIC_HF_TOKEN` trong `.env`. Backend đổi token thành URL ký sẵn có thời hạn, nên token không bị gửi xuống trình duyệt.

## Tìm kiếm kết hợp và Enhance query

Tìm kiếm kết hợp ba nguồn: **Image** (SigLIP / BEiT-3), **ASR** (BM25 trên transcript) và **Object** (vật thể nhận diện được). Các nguồn được đánh dấu là những nguồn mà một lần tìm được phép dùng.

Khi bật **Enhance query**, Gemini sẽ:

- viết lại câu truy vấn sang tiếng Anh;
- trích từ khoá tiếng Việt có khả năng được nói ra, dùng cho ASR;
- chọn các lớp vật thể (chỉ trong các nhãn có ở `objects_index.json`) kèm số lượng tối thiểu;
- dự đoán trọng số cho từng nguồn.

Vật thể nhập tay luôn được giữ, vật thể Gemini chọn được thêm vào. Trọng số được chuẩn hoá lại trên những nguồn thực sự trả về kết quả. Một kết quả ASR khớp sẽ cộng điểm cho mọi keyframe trong cùng shot.

### KIS Query Understanding & Planning

Vùng tìm KIS có quy trình **Query Understanding & Planning** (tuỳ chọn bật). Khi bật, nút **Understand query** gửi mô tả tiếng Việt tới `POST /api/search/kis/plan`. Gemini trả về một kế hoạch có thể chỉnh sửa, gồm:

- truy vấn hình ảnh bằng tiếng Anh;
- truy vấn ASR bằng tiếng Việt;
- mức độ quan trọng của từng sự kiện;
- chiến lược theo thời gian.

Xem lại kế hoạch rồi bấm Search.

## Nộp bài DRES

Đặt `AIC_DRES_USERNAME` và `AIC_DRES_PASSWORD` trong `.env`; có thể đặt thêm `AIC_DRES_BASE_URL`. Backend tự đăng nhập, giữ phiên DRES và gia hạn khi hết hạn. Trình duyệt không bao giờ thấy tài khoản.

Mở chi tiết một kết quả, bấm **Submit DRES**, chọn evaluation, kiểm tra các trường và phần xem trước request, rồi bấm **Xác nhận nộp**:

- **KIS**: `mediaItemName` + `start`/`end` tính bằng ms (mặc định `frame_id / fps × 1000`).
- **VQA** (dùng được cả trên kết quả KIS): `QA-<ANSWER>-<VIDEO_ID>-<TIME(ms)>`.
- **TRAKE**: `TR-<VIDEO_ID>-<FRAME_ID1>,<FRAME_ID2>,...` lấy từ cả hàng ứng viên.

Khi đang mở trình phát video, nút **Dùng frame đang xem** lấy thời điểm đang xem (với TRAKE là frame của sự kiện đó). Mọi câu trả lời đã được DRES chấm được ghi thêm vào `data/dres_submissions.jsonl`. Nộp lại đúng câu trả lời cũ cho cùng evaluation sẽ bị chặn, trừ khi xác nhận **Vẫn nộp lại**.

## Kiểm tra chất lượng

```powershell
make lint
make typecheck
make test
make build
```

## Cấu trúc dự án

```text
.
├── backend/              # Ứng dụng FastAPI, domain model, adapter và test
├── data/                 # Dữ liệu, index và media (không đưa lên Git)
├── frontend/             # Ứng dụng React/Vite và test frontend
├── scripts/              # Trích xuất dữ liệu (Kaggle), build index, chạy dev
├── .env.example
├── Makefile
└── README.md
```
