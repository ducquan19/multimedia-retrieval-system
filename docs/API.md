# HTTP API Contract

## 1. Quy ước

- Base path: `/api`; JSON UTF-8 trừ endpoint download.
- Validation errors dùng HTTP 422; media không tồn tại dùng 404; path không an toàn không được tiết lộ path tuyệt đối.
- `query_type` là discriminator: `KIS`, `VQA`, `TRAKE`.
- Query/answer length limits và CORS origins lấy từ settings.
- API hiện là contract của mock MVP; `retrieval_mode` phải ghi rõ `mock`.

## 2. Health và public config

### `GET /api/health`

```json
{"status":"ok"}
```

### `GET /api/config`

```json
{
  "min_top_k": 1,
  "max_top_k": 100,
  "default_top_k": 20,
  "max_trake_events": 10,
  "max_query_length": 4000,
  "max_answer_length": 4000,
  "retrieval_mode": "mock"
}
```

Ba giới hạn `max_trake_events=10`, `max_query_length=4000` và
`max_answer_length=4000` là default triển khai, không phải giới hạn từ BTC. Có thể cấu hình
chúng lần lượt qua `AIC_MAX_TRAKE_EVENTS`, `AIC_MAX_QUERY_LENGTH` và
`AIC_MAX_ANSWER_LENGTH`; mọi giá trị phải là số nguyên dương.

## 3. Search

### `POST /api/search`

Common search sources:

```json
{"image":true,"asr":false,"object":false,"ocr":false}
```

Ít nhất một field phải là `true`; top-k chỉ nhận một trong `1,5,20,50,100`.
Mỗi `query`, `main_query` và query của từng TRAKE event không được vượt quá
`max_query_length` mà `/api/config` công bố.

KIS request:

```json
{
  "query_type": "KIS",
  "query": "mô tả sự kiện",
  "top_k": 20,
  "enhance_query": false,
  "search_sources": {"image":true,"asr":false,"object":false,"ocr":false}
}
```

VQA request có cùng shape với `query_type: "VQA"`; `query` chứa mô tả/câu hỏi.

TRAKE request:

```json
{
  "query_type": "TRAKE",
  "main_query": "mô tả chuỗi sự kiện",
  "events": [
    {"event_index":1,"query":"event 1"},
    {"event_index":2,"query":"event 2"}
  ],
  "top_k": 20,
  "enhance_query": false,
  "search_sources": {"image":true,"asr":false,"object":false,"ocr":false}
}
```

KIS/VQA response:

```json
{
  "query_type": "KIS",
  "original_query": "...",
  "enhanced_query": null,
  "retrieval_mode": "mock",
  "results": [
    {
      "result_id": "result-001",
      "rank": 1,
      "video_id": "L01_V001",
      "frame_id": 505,
      "keyframe_url": "/media/keyframes/L01_V001/0000.jpg",
      "segment_id": "L01_V001_segment_000",
      "asr_text": "...",
      "ocr_text": "",
      "objects": [],
      "similarity_score": 0.9321,
      "answer": ""
    }
  ]
}
```

TRAKE response:

```json
{
  "query_type": "TRAKE",
  "original_query": "...",
  "enhanced_query": null,
  "retrieval_mode": "mock",
  "results": [
    {
      "result_id": "trake-result-001",
      "rank": 1,
      "video_id": "L10_V010",
      "similarity_score": 0.91,
      "events": [
        {
          "event_index": 1,
          "frame_id": 101,
          "keyframe_url": "/media/keyframes/L10_V010/0001.jpg",
          "segment_id": "segment-1",
          "asr_text": "...",
          "ocr_text": "",
          "objects": [],
          "similarity_score": 0.92
        }
      ]
    }
  ]
}
```

Khi enhance bật, `enhanced_query` chứa kết quả deterministic dễ nhận biết là mock. Hybrid flags được truyền tới service/adapter nhưng không kích hoạt vector search.

## 4. Submission render/download

Hai endpoint nhận discriminated union có ordered `rows`. Row schema không nhận `rank`; array order là thứ tự output duy nhất.

KIS example:

```json
{
  "query_type": "KIS",
  "filename": "kis.csv",
  "rows": [
    {"video_id":"L01_V001","frame_id":505}
  ]
}
```

VQA request:

```json
{
  "query_type": "VQA",
  "filename": "vqa.csv",
  "rows": [
    {"video_id":"L05_V005","frame_id":888,"answer":"màu xanh, đậm"}
  ]
}
```

TRAKE request:

```json
{
  "query_type": "TRAKE",
  "filename": "trake.csv",
  "event_count": 4,
  "rows": [
    {"video_id":"L10_V010","frame_ids":[101,151,203,251]}
  ]
}
```

### `POST /api/submissions/render`

```json
{
  "content": "L01_V001,505\r\n",
  "filename": "kis.csv",
  "row_count": 1,
  "warnings": []
}
```

VQA answer rỗng tạo warning metadata nhưng vẫn render. Formatter dùng dialect CSV chuẩn với CRLF (`\r\n`); comma, quote và newline trong answer được quote/escape bởi Python `csv.writer`.

### `POST /api/submissions/download`

Trả cùng UTF-8 bytes với `content` từ render, media type `text/csv; charset=utf-8`, và `Content-Disposition: attachment` với filename đã sanitize. Filename Unicode dùng thêm tham số RFC 5987 `filename*`.

Sanitization lấy basename sau cả `/` và `\\`, loại control/null byte cùng ký tự filename nguy hiểm, xử lý tên Windows reserved, giới hạn 255 ký tự và ép extension `.csv`. Ví dụ `../../evil.csv` trở thành `evil.csv`. Backend không ghi submission vào filesystem.

Validation:

- KIS/VQA: `video_id` không rỗng, `frame_id` là non-negative integer.
- VQA: `answer` là string tối đa `max_answer_length` ký tự theo `/api/config`; cho phép
  rỗng kèm warning.
- TRAKE: `event_count >= 1`, mọi `frame_ids` có đúng `event_count` phần tử.
- Rows tối đa 100.

## 5. Media

### `GET /media/{relative_path:path}`

Chỉ phục vụ file resolve bên trong `DATA_ROOT`. Absolute path, drive path, `..`, encoded traversal và symlink escape bị từ chối. Response search chỉ chứa URL tương đối, không chứa binary hoặc absolute filesystem path.
