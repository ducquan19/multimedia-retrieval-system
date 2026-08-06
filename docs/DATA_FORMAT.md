# Data Format

## 1. Nguồn và nguyên tắc

Tất cả runtime data nằm dưới một `DATA_ROOT`, mặc định `./data`. **SOURCE-CSV + DECISION**

PDF mô tả Videos, Keyframes, Objects, CLIP features và Metadata, nhưng không quy định một schema tích hợp chung; CSV còn nêu ASR và OCR. Vì vậy normalized manifest dưới đây là **DECISION**, không phải định dạng chính thức của BTC.

Quy tắc bắt buộc từ PDF: keyframe filename chỉ thể hiện thứ tự tăng dần; frame index thật được ghi trong metadata. Ứng dụng không được suy diễn `frame_id` từ `0000.jpg`.

## 2. Layout đề xuất

```text
data/
  manifest.json
  fixtures/search_results.json
  videos/L01_V001.mp4
  keyframes/L01_V001/0000.jpg
  metadata/L01_V001.json
  asr/
  ocr/
  objects/L01_V001/0000.json
  features/                         # chưa dùng trong mock MVP
```

Mọi path trong manifest là POSIX-style relative path dưới `DATA_ROOT`; không chấp nhận absolute path, drive prefix, `..` segment hoặc path resolve ra ngoài root.

## 3. `manifest.json`

```json
{
  "version": 1,
  "keyframes": [
    {
      "keyframe_id": "L01_V001/0000",
      "video_id": "L01_V001",
      "frame_id": 505,
      "image_path": "keyframes/L01_V001/0000.jpg",
      "video_path": "videos/L01_V001.mp4",
      "segment_id": "L01_V001_segment_000",
      "asr_text": "",
      "ocr_text": "",
      "objects": []
    }
  ]
}
```

### Fields

| Field | Type | Required | Quy tắc |
| --- | --- | --- | --- |
| `version` | integer | yes | Hiện hỗ trợ `1` |
| `keyframe_id` | string | yes | Unique stable ID; không dùng làm frame index |
| `video_id` | string | yes | ID logic, không yêu cầu extension |
| `frame_id` | non-negative integer | yes | Frame index thật từ metadata |
| `image_path` | relative path | yes | Nằm trong DATA_ROOT |
| `video_path` | relative path/null | no | File có thể thiếu |
| `segment_id` | string/null | no | Chuẩn hóa thành chuỗi rỗng trong response nếu thiếu |
| `asr_text` | string/null | no | Chuẩn hóa thành chuỗi rỗng |
| `ocr_text` | string/null | no | Chuẩn hóa thành chuỗi rỗng |
| `objects` | array/null | no | Chuẩn hóa thành array rỗng; item schema ban đầu cho phép JSON object có kiểm soát |

Loader từ chối duplicate `keyframe_id`, invalid path và field bắt buộc sai kiểu. File media thiếu có thể được ghi nhận và UI dùng placeholder; malformed manifest không được bỏ qua im lặng.

## 4. Fixture search results

`data/fixtures/search_results.json` chứa deterministic candidate cho KIS, VQA và TRAKE. Candidate tham chiếu `keyframe_id`; backend hydrate URL/metadata từ manifest để tránh lặp frame mapping.

Schema logic đề xuất:

```json
{
  "version": 1,
  "KIS": [
    {
      "result_id": "kis-001",
      "keyframe_id": "L01_V001/0000",
      "similarity_score": 0.9321
    }
  ],
  "VQA": [
    {
      "result_id": "vqa-001",
      "keyframe_id": "L05_V005/0000",
      "similarity_score": 0.91,
      "answer": ""
    }
  ],
  "TRAKE": [
    {
      "result_id": "trake-001",
      "video_id": "L10_V010",
      "similarity_score": 0.91,
      "events": [
        {
          "event_index": 1,
          "keyframe_id": "L10_V010/0001",
          "similarity_score": 0.92
        }
      ]
    }
  ]
}
```

TRAKE invariants: events không rỗng; `event_index` liên tục từ 1; số event bằng request; mỗi hydrated keyframe có cùng `video_id` với row; thứ tự event cố định.

## 5. Cache và missing data

Manifest được parse/validate một lần cho mỗi process và lưu ở immutable repository state. Test sẽ chứng minh không đọc lại file trên mỗi search. Thay đổi data trong lúc server chạy cần restart trong MVP. **ASSUMPTION**

ASR, OCR, objects, video path và metadata ngoài frame mapping có thể thiếu theo nguồn. Response dùng giá trị rỗng/null đã mô tả; UI không crash và ảnh lỗi có placeholder.

## 6. Dữ liệu chưa dùng trong MVP

CLIP `.npy` và raw object/ASR/OCR indexes có thể được giữ dưới DATA_ROOT nhưng FixtureRetrievalEngine không đọc để tính similarity. Không có inference/indexing pipeline trong MVP.
