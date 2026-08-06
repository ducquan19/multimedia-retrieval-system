# AIC 2026 Retrieval Inspector - Product Specification

## 1. Mục đích và phạm vi

AIC 2026 Retrieval Inspector là công cụ web chạy local để đội thi:

1. gửi truy vấn KIS, VQA hoặc TRAKE tới một retrieval adapter;
2. kiểm tra keyframe, similarity score và ngữ cảnh ASR;
3. sửa câu trả lời VQA và sắp xếp lại candidate thủ công;
4. xem trước và tải submission đúng với trạng thái UI hiện tại.

Phạm vi MVP được khóa là **retrieval result inspector + manual reranking + submission builder**. MVP dùng dữ liệu fixture/precomputed có tính xác định. Gemini enhancement, hybrid search và retrieval chỉ là contract/mock; không gọi model, tạo embedding, index, vector database, OCR/ASR inference, VQA auto-answer hay temporal alignment thật.

## 2. Phân loại yêu cầu và nguồn

Các nhãn dùng trong bộ tài liệu:

- **SOURCE-PDF**: quy định trực tiếp trong `Thong tin vong So tuyen AIC2026.pdf`.
- **SOURCE-CSV**: nhu cầu sản phẩm trong `App features - Trang tính1.csv`.
- **DECISION**: quyết định kỹ thuật đã khóa trong prompt pack.
- **ASSUMPTION**: phần nguồn chưa quy định, được cô lập để có thể thay đổi.

Khi có xung đột, quy định cuộc thi trong PDF có ưu tiên cao hơn CSV và quyết định triển khai.

## 3. Nghiệp vụ cuộc thi

### 3.1. Loại truy vấn

| Loại | Yêu cầu | Submission row | Nguồn |
| --- | --- | --- | --- |
| KIS | Tìm đúng video và một frame thuộc đoạn sự kiện được mô tả | `<video_id>,<frame_id>` | SOURCE-PDF |
| VQA/Q&A | Tìm đúng video/frame và trả lời câu hỏi; answer có thể bằng tiếng Việt hoặc tiếng Anh | `<video_id>,<frame_id>,<answer>` | SOURCE-PDF |
| TRAKE | Tìm một video chứa chuỗi sự kiện và một semantic keyframe cho mỗi event | `<video_id>,<frame_id_1>,...,<frame_id_n>` | SOURCE-PDF |

Semantic keyframe của TRAKE là khái niệm nội dung, không phải I-frame nén video. Mọi event trong một TRAKE candidate thuộc cùng một video và giữ đúng thứ tự truy vấn. **SOURCE-PDF + DECISION**

### 3.2. Xếp hạng

- Mỗi truy vấn được nộp tối đa 100 câu trả lời. **SOURCE-PDF**
- Điểm cuối dùng R@k tại `k = 1, 5, 20, 50, 100`; vì vậy thứ tự candidate là dữ liệu nghiệp vụ. **SOURCE-PDF**
- UI cho phép chọn top-k `1, 5, 20, 50, 100`, tương ứng các mốc đánh giá R@k. **SOURCE-PDF + DECISION**
- Kéo thả hoặc Move up/Move down phải cập nhật thứ tự hiện tại; preview/download phải dùng chính thứ tự đó, không dùng `rank` cũ từ API. **SOURCE-CSV + DECISION**
- MVP không tính R-Score vì không có ground truth. **ASSUMPTION**

### 3.3. Dữ liệu nguồn

PDF công bố Videos, Keyframes, Objects, CLIP features và Metadata. Video là dữ liệu chính thức; các thành phần còn lại chỉ hỗ trợ. Keyframe filename tăng theo thứ tự, còn frame index thật nằm trong metadata. Một số video có thể thiếu metadata. **SOURCE-PDF**

CSV yêu cầu ảnh, video, metadata, ASR, OCR và objects nằm dưới một data root chung. MVP chuẩn hóa chúng dưới `./data` thông qua manifest nội bộ. **SOURCE-CSV + DECISION**

## 4. User journeys và yêu cầu chức năng

### 4.1. Chung

- Header hiển thị tên app và badge `Mock retrieval`.
- Tabs/segmented control cho KIS, VQA, TRAKE.
- Controls: top-k; Gemini enhance; nguồn Image, ASR, Object, OCR; nút Search.
- Ít nhất một search source phải được chọn.
- Có loading, error, empty state và hủy request cũ khi tìm lại.
- Khi Gemini toggle bật, mock adapter trả enhanced query và UI hiển thị original/enhanced cùng badge `Mock`.
- Candidate hiển thị rank hiện tại, thumbnail, video ID, frame ID và similarity score.
- Click thumbnail mở modal ảnh lớn và ASR của segment; OCR/object chỉ hiện khi có.
- Action bar cho row count, reset order, filename, preview và download.

Nguồn: **SOURCE-CSV + DECISION**.

### 4.2. KIS

- Một textarea mô tả sự kiện.
- Kết quả là sortable card grid/list; mỗi card đại diện một keyframe.
- Submission dùng `video_id` và frame index thật.

### 4.3. VQA

- Một textarea chứa mô tả/câu hỏi; MVP không tự sinh answer.
- Kết quả giống KIS và có answer input/textarea trên từng card.
- Answer được keyed theo `result_id`, giữ nguyên sau reorder và được export đúng Unicode/CSV escaping.

### 4.4. TRAKE

- Form gồm main query, số event và N event query inputs.
- Mỗi candidate là một sortable row với đúng N event cells theo thứ tự Event 1..N.
- Chỉ reorder cả row, không reorder event cells.
- Trên màn hình hẹp, event area cuộn ngang và thumbnail không bị co mất khả năng kiểm tra.

### 4.5. Modal và accessibility

- Ảnh dùng `object-fit: contain`; hiển thị IDs, segment, score và ASR.
- Đóng bằng button, Escape hoặc backdrop; có focus trap và trả focus về trigger.
- Drag handle riêng, keyboard sensor và Move up/Move down fallback.
- Thumbnail lazy-load, có kích thước ổn định và placeholder khi lỗi.

## 5. Submission

- UTF-8, không header, một candidate mỗi dòng, mặc định `.csv`. **ASSUMPTION**
- Dùng formatter backend duy nhất và CSV writer để escape comma, quote, newline, Unicode. **DECISION**
- Preview và download nhận ordered state từ UI và phải có cùng content. **DECISION**
- Filename do người dùng sửa được, phải loại path separator/null byte/traversal. **SOURCE-CSV + DECISION**
- VQA cho phép answer rỗng nhưng preview trả warning. **ASSUMPTION**

## 6. Phi chức năng

- Frontend: React, TypeScript strict, Vite, TanStack Query, dnd-kit, plain CSS/CSS Modules, Vitest/RTL, Playwright. **DECISION**
- Backend: Python 3.12+, FastAPI, Pydantic v2, pydantic-settings, pytest, Ruff; stateless và không database. **DECISION**
- Manifest được cache read-only trong process; ảnh trả bằng URL, không base64; không preload video. **DECISION**
- Media resolver và filename sanitizer chống path traversal; request có giới hạn độ dài; CORS chỉ cho local frontend khi phát triển. **DECISION**
- Thiếu ASR/OCR/object/video/metadata tùy chọn không được làm crash app. **SOURCE-PDF + DECISION**

## 7. Ngoài phạm vi

Gemini thật, CLIP query encoding, embedding generation, vector search/fusion thật, FAISS/Qdrant/Elasticsearch, OCR/ASR inference, VQA auto-answer, TRAKE alignment AI, video transcoding, ground-truth scoring, authentication, realtime collaboration và production cloud deployment.

## 8. Acceptance criteria MVP

- KIS: fixture bị cắt đúng top-k; card có score/IDs; mở modal thấy ASR; đưa candidate #2 lên #1 làm dòng đầu preview/download đổi theo.
- VQA: sửa answer `màu xanh, đậm`; CSV quote đúng; reorder không mất hoặc gắn nhầm answer.
- TRAKE: event count N tạo N inputs và N cells; mỗi row cùng video; event order cố định; reorder row đổi submission.
- Mock controls: Gemini toggle và bốn hybrid flags có trong payload; UI hiển thị mock enhanced query; không có lời gọi AI thật.
- Submission: filename traversal được sanitize; đúng số field; không header; preview khớp download và current UI state.
- Quality: backend lint/tests, frontend lint/typecheck/tests/build và smoke E2E chạy pass trước khi kết thúc Prompt 8.
