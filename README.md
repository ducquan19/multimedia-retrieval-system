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
- Metadata keyframe đọc từ `keyframes.json` vào RAM khi khởi động; không cần cơ sở dữ liệu

### Frontend

- React và TypeScript (strict mode)
- Vite
- TanStack Query
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
python -m pip install -e ".\backend[dev]" -c .\backend\requirements.lock
npm --prefix frontend ci
```

Mọi dependency Python khai báo ở một chỗ: `backend/pyproject.toml`. `backend/requirements.lock` pin chính xác phiên bản web stack và công cụ dev, được dùng làm constraints (`-c`). Cần chạy các script tiền xử lý trong `scripts/` thì cài thêm nhóm `scripts`: `".\backend[dev,scripts]"`.

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
| `AIC_DEVICE` | tự chọn | `cuda` hoặc `cpu` cho các model |
| `AIC_LOG_LEVEL` | `INFO` | Mức log của backend (ghi ra console và `logs/backend.log`) |

Danh sách đầy đủ (model, index, Elasticsearch, tham số TRAKE, ...) nằm trong `backend/src/core/config.py`; mọi trường đều đặt được bằng biến `AIC_<TÊN_TRƯỜNG>`.

Top-K mặc định là `100`, tối đa `500`.

### 4. Chuẩn bị dữ liệu

- Nếu đã nhận gói dữ liệu build sẵn: làm theo [Dùng gói dữ liệu đã build](#dùng-gói-dữ-liệu-đã-build-thành-viên-không-build).
- Nếu tự build: làm theo mục [Chuẩn bị dữ liệu](#chuẩn-bị-dữ-liệu) bên dưới.

### 5. Chạy ứng dụng

```powershell
docker compose up -d      # Elasticsearch
python scripts/dev.py     # backend + frontend
```

- Frontend: <http://localhost:5173>
- Backend API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- Trạng thái các thành phần (model, index, Elasticsearch, Gemini): <http://localhost:8000/api/health/ready>

Backend chỉ phục vụ các thư mục media `keyframes/`, `traffic_keyframes/` và `videos/` của `data/` qua `/media` (đổi bằng `AIC_MEDIA_DIRS`). Index, metadata và log nộp DRES không tải được qua HTTP.

## Chuẩn bị dữ liệu

Toàn bộ dữ liệu nằm dưới một thư mục gốc (`AIC_DATA_ROOT`, mặc định `./data`). Thư mục `data/` quá lớn nên không được đưa lên Git.

### Các tập dữ liệu

| Batch | Nhóm | Nội dung | Mã video | Keyframe |
| --- | --- | --- | --- | --- |
| Batch 1 | **L** | L21–L30 | `L21_V001` | Tự trích theo shot: `keyframes/<video_id>/S<shot>/F<frame>.jpg` |
| Batch 2 | **M** | Tin tức 60 Giây – HTV (M01–M10) | `M01_V001` | BTC cung cấp, không chia shot: `keyframes/<video_id>/<n>.jpg` |
| Batch 2 | **N** | Camera giao thông (N001–N100) | `N001-V001` | BTC cung cấp, xử lý riêng (xem [Video giao thông N](#video-giao-thông-n)): `traffic_keyframes/<video_id>/<n>.jpg` |
| Batch 2 | **S** | Thể thao – HTV Thể Thao (S01) | `S01-V001` | BTC cung cấp, không chia shot: `keyframes/<video_id>/<n>.jpg` |

Lưu ý:

- Nhóm M dùng dấu gạch dưới (`M01_V001`), còn nhóm N và S dùng dấu gạch ngang (`N001-V001`). Giữ nguyên tên thư mục như BTC cung cấp, vì các file `objects/`, `map-keyframes/` và `keyframes/` được ghép với nhau theo đúng tên này.
- Keyframe batch 2 được đặt tên theo số thứ tự `n` (M: `001.jpg`, S: `0001.jpg`, ...). Số frame thật được tra trong `map-keyframes/<video_id>.csv` (cột `n` → `frame_idx`).
- Nhóm N **không** đặt trong `keyframes/`: video giao thông có tốc độ khung hình thay đổi (VFR), nên `frame_idx` của BTC chỉ là giá trị xấp xỉ và không dùng được để tính thời điểm nộp bài.

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
│   └── S01-V001/                    # (N không nằm ở đây)
├── traffic_keyframes/               # N: <video_id>/<n>.jpg, keyframe BTC (không đặt trong keyframes/)
├── traffic_probe/merged/frames/     # N: <video_id>.npz, bảng pts của mọi frame (tính frame_id, time_ms)
├── traffic_camera/                  # N: video_metadata.csv, cameras.json, video_weather.csv (tab TRAFFIC)
├── map-keyframes/                   # <video_id>.csv: n,pts_time,fps,frame_idx của keyframe BTC (L, M, N, S)
├── objects/                         # <video_id>/<n>.json: vật thể nhận diện của từng keyframe (L, M, N, S)
├── scenes/                          # <video_id>.scenes.csv: ranh giới shot (L, M)
├── asr/                             # <video_id>/S<shot>.json: transcript theo shot
├── embeddings/                      # <video_id>.npy của L, M, N, S; dòng i = keyframe thứ i
│   ├── siglip/<video_id>.npy
│   └── beit3/<video_id>.npy
├── checkpoint/                      # beit3.spm, beit3_base_patch16_384_coco_retrieval.pth
│
│   # Các file dưới đây do script sinh ra
├── keyframes.json                   # generate_manifest.py + append_traffic_index.py
├── indexing/
│   ├── siglip.index                 # build_faiss_index.py + append_traffic_index.py
│   ├── siglip.index.meta.json       # hash thứ tự keyframe, backend kiểm tra khi khởi động
│   ├── beit3.index
│   └── beit3.index.meta.json
├── objects_index.json               # build_object_index.py + append_traffic_index.py
├── video_sources.json               # nguồn phát và fps của từng video (có trong gói dữ liệu)
└── dres_submissions.jsonl           # lịch sử nộp DRES, backend tự ghi
```

### Sắp xếp keyframe batch 2 vào `data/keyframes/`

Chép (hoặc di chuyển) từng thư mục video trong các gói **M và S** của BTC vào `data/keyframes/`, giữ nguyên tên thư mục video. Gói N (`Keyframes_N*`) chuyển vào `data/traffic_keyframes/` thay vì `data/keyframes/`:

```powershell
Get-ChildItem data\Keyframes_M*\keyframes, data\Keyframes_S*\keyframes -Directory | ForEach-Object {
    Get-ChildItem $_.FullName -Directory | Move-Item -Destination data\keyframes\
}
New-Item -ItemType Directory -Force data\traffic_keyframes | Out-Null
Get-ChildItem data\Keyframes_N*\keyframes -Directory | ForEach-Object {
    Get-ChildItem $_.FullName -Directory | Move-Item -Destination data\traffic_keyframes\
}
```

Tương tự, chuyển các thư mục video trong `Objects_*` (cả N) vào `data/objects/`, và file `*.csv` của map-keyframes vào `data/map-keyframes/`. Sau đó có thể xoá các thư mục `Keyframes_*`, `Objects_*` và file `.zip` đã giải nén.

### Các bước build dữ liệu

Chạy theo đúng thứ tự dưới đây. Mỗi khi thêm hoặc bớt keyframe, cần chạy lại từ bước 1 (kể cả bước 5). Tham số và cách chạy trên Kaggle của từng script: [scripts/README.md](scripts/README.md).

Embedding `.npy` được trích trên GPU bằng notebook `notebooks/embed_siglip2.ipynb` / `embed_beit3.ipynb` (Kaggle), hoặc `scripts/embed_keyframes.py` (Colab, Lightning, máy local). Dòng i của `<video_id>.npy` là ảnh thứ i theo số `n` tăng dần.

1. **Tạo `keyframes.json`**. Script quét `data/keyframes/`:
   - Thư mục chia shot `S*/F<frame>.jpg` (batch 1): `frame_id` lấy từ tên file.
   - Thư mục phẳng `<n>.jpg` (batch 2): `frame_id` tra trong `map-keyframes`. Với video có `scenes/` (nhóm M), keyframe được gán `segment_id` theo shot để ghép với transcript.

   ```powershell
   python scripts/generate_manifest.py
   ```

2. **Build FAISS index** từ các file `.npy`. Thứ tự vector trong mỗi file `.npy` phải khớp với thứ tự keyframe khi trích embedding: batch 1 theo thư mục shot rồi tên file, batch 2 theo số `n` tăng dần. Script dừng nếu một video thiếu `.npy` hoặc có số dòng khác số keyframe (thêm `--allow-missing` nếu chấp nhận vector 0 cho video thiếu), và ghi `<model>.index.meta.json` để backend kiểm tra index có khớp `keyframes.json` không.

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

5. **Nối nhóm N** vào cuối `keyframes.json`, hai file FAISS và `objects_index.json`. Với mỗi keyframe N, script tính `frame_id` và `time_ms` (thời điểm gốc của frame, dùng khi nộp KIS/QA) từ `traffic_probe/merged/frames/`, gắn `group_id` là camera, và ghép vật thể theo số `n`. Vì N nằm ở cuối, vị trí của L, M, S trong index không đổi. Script từ chối chạy nếu manifest đã có N, nên muốn chạy lại thì phải chạy lại từ bước 1.

   ```powershell
   python scripts/append_traffic_index.py
   ```

   Khi chỉ có dữ liệu object mới (keyframe không đổi), không cần chạy lại từ bước 1: chạy lại bước 4 rồi thêm lại object của N. Lệnh này bỏ phần N mà bước 4 ghép theo `frame_idx` và ghép lại theo số `n`, không động tới `keyframes.json` và FAISS:

   ```powershell
   python scripts/build_object_index.py
   python scripts/append_traffic_index.py --objects-only
   ```

6. **Khởi động lại backend** để nạp dữ liệu mới.

### Dùng gói dữ liệu đã build (thành viên không build)

Chỉ một người build dữ liệu theo [Các bước build dữ liệu](#các-bước-build-dữ-liệu) rồi gửi gói `aic26_index_*.zip` cho các thành viên còn lại. Transcript (`asr/`) được gửi và hướng dẫn riêng. Nếu bạn nhận gói, làm các bước sau:

1. **Cập nhật code** lên bản mới nhất (`git pull`) để backend đọc được dữ liệu trong gói.

2. **Giải nén gói index vào `data/`**, cho phép ghi đè file cũ. Gói gồm `keyframes.json`, `indexing/siglip.index`, `indexing/beit3.index`, `objects_index.json`, `video_sources.json` và `traffic_camera/`. Bỏ các gói nhận trước đó: ba file `keyframes.json`, `siglip.index`, `beit3.index` phải cùng một lần build, không dùng lẫn.

3. **Đặt ảnh keyframe đúng chỗ** (tải từ BTC hoặc Kaggle, xem [Link tải](#link-tải)):
   - L, M, S: `data/keyframes/<video_id>/` (lệnh ở mục [Sắp xếp keyframe batch 2](#sắp-xếp-keyframe-batch-2-vào-datakeyframes))
   - N: `data/traffic_keyframes/<video_id>/`, **không** đặt trong `keyframes/`

   Thiếu ảnh thì tìm kiếm vẫn chạy nhưng kết quả không hiện hình.

4. **Index transcript vào Elasticsearch** (index nằm trong Docker của từng máy nên phải tự chạy). Sau khi đã có transcript trong `data/asr/`:

   ```powershell
   docker compose up -d
   python scripts/build_es_index.py
   ```

5. **Kiểm tra `.env`** có `AIC_HF_TOKEN` đọc được repo `dwctien/aic26-videos-private` (để phát video N011–N100), rồi **khởi động lại backend**.

**Không chạy** `generate_manifest.py`, `build_faiss_index.py`, `build_object_index.py` hay `append_traffic_index.py`: các file chúng sinh ra đã có trong gói, chạy lại sẽ ghi đè bằng bản không khớp. Cũng không cần tải `embeddings/`, `objects/`, `map-keyframes/`, `scenes/` hay dữ liệu `traffic_probe/`, vì chúng chỉ dùng khi build.

Khi nhận gói mới (ví dụ khi có thêm ASR hoặc object), lặp lại bước 2 và bước 4.

### Video giao thông N

- Ảnh keyframe BTC của N nằm trong `traffic_keyframes/<video_id>/` (tách khỏi `keyframes/` để `generate_manifest.py` bỏ qua N). Nếu dời ảnh sang chỗ khác sau khi build, chạy `python scripts/append_traffic_index.py --relink-images` để cập nhật `image_path` mà không phải build lại index.
- `traffic_probe/merged/frames/<video_id>.npz` (bảng pts của mọi frame) và `traffic_camera/` (tên camera, ngày giờ trên OSD, buổi, thời tiết) được sinh bởi các notebook Kaggle trong `scripts/traffic/`.
- Thời điểm nộp KIS/QA cho N là `time_ms`, tức pts gốc của frame, không phải `frame_idx / fps`. Bản `.mp4` trên Hugging Face bắt đầu ở 0 thay vì 0,2 s, nên `video_sources.json` lưu thêm `time_offset_ms` để giao diện quy đổi thời điểm đang phát về thời gian gốc.

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

- **Batch 1 (L):** trích bằng Whisper large-v3 trên Kaggle (`notebooks/extract_asr.ipynb`), rồi tải về `data/asr/`.
- **Batch 2 (M, S):** lấy phụ đề YouTube từ trường `watch_url` trong `media-info`. Cần có file `scenes/<video_id>.scenes.csv` trước; video chưa có scenes sẽ bị bỏ qua.

  ```powershell
  python -m pip install "youtube-transcript-api>=1.0" yt-dlp tqdm
  $env:PYTHONUTF8 = "1"
  python scripts/extract_youtube_transcript.py --prefix M --cookies-from-browser firefox
  ```

  - Script ghi lại tiến độ vào `data/asr/_youtube_transcript_state.json`. Video đã xong hoặc không có phụ đề sẽ được bỏ qua ở lần chạy sau. Dùng `--overwrite` hoặc `--retry-missing` để chạy lại.
  - YouTube hay chặn IP (`IpBlocked`, `HTTP 429`) khi gửi nhiều request. Script sẽ tự nghỉ (`--cooldown`, mặc định 15 phút) rồi thử lại; bị chặn liên tiếp quá `--max-blocks` lần thì dừng. Khi đó hãy đổi mạng hoặc dùng `--proxy`, rồi chạy lại.
  - Cookie trình duyệt giúp ít bị chặn hơn. Trên Windows nên dùng `--cookies-from-browser firefox`, hoặc xuất cookie ra `cookies.txt` rồi dùng `--source ytdlp --cookies cookies.txt`. **Không commit file cookie** (đã có trong `.gitignore`), và nên dùng tài khoản YouTube phụ.

### Chia shot (scenes)

`notebooks/extract_scenes.ipynb` chia shot trên Kaggle bằng TransNetV2 (kèm SliTraNet để loại ranh giới sai) và xuất `<video_id>.scenes.csv`:

```text
video_id,scene_id,start_frame,end_frame,start_time_s,end_time_s,duration_s,fps
```

Hiện đã có scenes cho nhóm L và M. Scenes của L được chuyển từ `transnetv2_results_batch1/<video_id>.json` sang cùng định dạng CSV. Nhóm N và S chưa có. Keyframe của N và S vẫn được index bình thường, chỉ không có `segment_id` theo shot.

### Phát video

- **Video local:** đặt file vào `data/videos/<video_id>.mp4` rồi dùng nút "Open Local Video" trên giao diện.
- **Video từ xa:** `data/video_sources.json` (có trong gói dữ liệu) lưu `remote_url`, `fps` và với nhóm N cả `time_offset_ms` của từng video. Video nằm trong repo Hugging Face riêng tư (`dwctien/aic26-videos-private`) dùng `private_path` thay cho `remote_url`, và cần đặt `AIC_HF_TOKEN` trong `.env`. Backend đổi token thành URL ký sẵn có thời hạn, nên token không bị gửi xuống trình duyệt.

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

Khi đang mở trình phát video, nút **Dùng frame đang xem** lấy thời điểm đang xem (với TRAKE là frame của sự kiện đó). Mọi câu trả lời đã được DRES chấm được ghi thêm vào `data/dres_submissions.jsonl`. Nộp lại đúng câu trả lời cũ cho cùng evaluation luôn bị chặn (`409`), kể cả sau khi khởi động lại backend; thời điểm `"12000"` và `12000` được coi là cùng một câu trả lời.

## Kiểm tra chất lượng

```powershell
make lint
make typecheck
make test
make build
```

`make test` không cần GPU, model hay `data/`: test backend dựng app với FAISS trong bộ nhớ, encoder và Elasticsearch giả (`backend/tests/fakes.py`). GitHub Actions (`.github/workflows/ci.yml`) chạy các lệnh trên cho mỗi push và pull request.

### Đánh giá chất lượng tìm kiếm

Trước khi giữ một thay đổi về trọng số fusion, tham số TRAKE, model hay index, chạy lại bộ truy vấn có nhãn và so sánh Recall@K và MRR:

```powershell
python scripts/evaluate_retrieval.py data/eval/queries.jsonl --top-k 100 --output eval_before.json
```

Định dạng file truy vấn được mô tả ở đầu `scripts/evaluate_retrieval.py`.

## Cấu trúc dự án

```text
.
├── backend/              # Ứng dụng FastAPI, domain model, repository và test
├── data/                 # Dữ liệu, index và media (không đưa lên Git)
├── frontend/             # Ứng dụng React/Vite và test frontend
├── notebooks/            # Notebook Kaggle: chia shot, ASR, embedding, OCR, object (GPU)
├── scripts/              # Build index, dev.py, evaluate_retrieval.py: xem README trong thư mục
├── .env.example
├── Makefile
└── README.md
```
