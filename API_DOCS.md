# API Reference Documentation
**System:** DeepAnalyze (LAMBDA) Core Engine
**Version:** 1.0.0
**Protocol:** HTTP/1.1
**Base URL:** 
- Local Development: `http://localhost:8000`
- Docker Deployment: `http://localhost:18000`

---

## 1. Overview
Tài liệu này cung cấp đặc tả kỹ thuật cho các API endpoints thuộc hệ thống DeepAnalyze Backend (FastAPI). Các dịch vụ được chia thành 3 nhóm chính:
- **Core Execution API:** Giao tiếp với Agent lõi để xử lý các luồng hội thoại và thực thi mã nguồn.
- **Workspace API:** Quản lý không gian làm việc tĩnh, danh sách tệp tin và truy xuất tài nguyên sinh ra bởi mô hình.
- **Compatibility API:** Các endpoint hỗ trợ khả năng tương thích ngược với chuẩn giao tiếp của OpenAI.

> **Lưu ý định tuyến (Routing):** Khi tích hợp thông qua NextJS Frontend, tất cả các request có tiền tố `/api/*` sẽ được tự động Proxy sang Base URL của backend.

---

## 2. Core Execution API

### 2.1. Create Chat Completion
Xử lý truy vấn ngôn ngữ tự nhiên từ người dùng và phản hồi qua luồng Server-Sent Events (SSE). Hỗ trợ khả năng chèn ngữ cảnh (Context Injection) tự động.

- **URL:** `/chat/completions`
- **Method:** `POST`
- **Content-Type:** `application/json`

**Request Body (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| `model` | string | Optional | Định danh của mô hình (Mặc định: `lambda-triadic-agent`) |
| `session_id` | string | Optional | Định danh phiên làm việc (Mặc định: `default`) |
| `messages` | array | Yes | Mảng chứa lịch sử hội thoại. Mỗi đối tượng bắt buộc gồm `role` (user/assistant) và `content` |

**Example Request:**
```json
{
  "model": "lambda-triadic-agent",
  "session_id": "usr_789_xyz",
  "messages": [
    {
      "role": "user",
      "content": "Phân tích biến động doanh thu trong file data.csv"
    }
  ]
}
```

**Response:** `200 OK (text/event-stream)`
Trả về luồng dữ liệu liên tục theo định dạng chunk của OpenAI:
```text
data: {"id": "chatcmpl-...", "object": "chat.completion.chunk", "choices": [{"delta": {"content": "Hệ thống đang xử lý..."}}]}
...
data: [DONE]
```

### 2.2. Execute Python Code
Cho phép thực thi mã nguồn Python trực tiếp trên phân vùng Kernel an toàn (Jupyter Sandbox) của Backend và trả về kết quả hoặc lỗi.

- **URL:** `/execute`
- **Method:** `POST`
- **Content-Type:** `application/json`

**Request Body (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | Optional | Định danh phiên làm việc |
| `code` | string | Yes | Mã nguồn Python cần thực thi |

**Response:** `200 OK (application/json)`
```json
{
  "success": true,
  "result": "Output của quá trình thực thi",
  "message": "Code executed successfully",
  "generated_files": []
}
```

### 2.3. Retrieve Agent Memory (RIMRULE)
Trích xuất danh sách các quy tắc (heuristics) và bài học kinh nghiệm mà AI đã tự động học được từ các lỗi runtime trong quá khứ.

- **URL:** `/memory`
- **Method:** `GET`

**Response:** `200 OK (application/json)`
```json
{
  "success": true,
  "rules": [
    {
      "rule_id": "r_101",
      "content": "Luôn kiểm tra Null trước khi tính Mean..."
    }
  ]
}
```

---

## 3. Workspace API

Nhóm API quản lý tệp tin và không gian làm việc cục bộ của mô hình.

### 3.1. Fetch Workspace Tree
Lấy cấu trúc thư mục dạng cây của toàn bộ không gian làm việc thuộc phiên hiện tại.

- **URL:** `/workspace/tree`
- **Method:** `GET`
- **Query Parameters:**
  - `session_id` (string, Default: `default`)

### 3.2. List Generated Files
Liệt kê danh sách các tệp tin (biểu đồ, báo cáo, dữ liệu phái sinh) do AI sinh ra trong phiên làm việc.

- **URL:** `/workspace/generated-files`
- **Method:** `GET`
- **Query Parameters:**
  - `session_id` (string, Default: `default`)

### 3.3. File Rendering & Download
Truy xuất nội dung tệp tin tĩnh.

- **URL:** `/file`
- **Method:** `GET`
- **Query Parameters:**
  - `path` (string, Required): Đường dẫn tương đối của tệp tin. (e.g., `workspace/generated/reports/chart.png`)

**Lưu ý:** Để thiết lập hành vi Download thay vì Inline Preview, có thể sử dụng endpoint `/workspace/download` với tham số `download=true`.

### 3.4. Preview Dataset (Pagination)
Truy xuất một phần dữ liệu của tệp tin dạng bảng (CSV/Excel) để hiển thị lên Data Grid của Frontend mà không gây tràn bộ nhớ.

- **URL:** `/workspace/preview`
- **Method:** `GET`
- **Query Parameters:**
  - `path` (string, Required): Đường dẫn tệp tin
  - `page` (int, Default: 1): Số trang hiện tại
  - `page_size` (int, Default: 50): Số lượng dòng dữ liệu trên mỗi trang

---

## 4. Compatibility API

### 4.1. List Models
Cung cấp định dạng tương thích với chuẩn OpenAI để tích hợp liền mạch với các giao diện bên thứ 3 (VD: Open WebUI, LibreChat).

- **URL:** `/v1/models`
- **Method:** `GET`

**Response:** `200 OK (application/json)`
```json
{
  "object": "list",
  "data": [
    {
      "id": "lambda-triadic-agent",
      "object": "model",
      "owned_by": "deepanalyze-engine"
    }
  ]
}
```

---
*Tài liệu được cập nhật nội bộ cho đội ngũ Kỹ sư Phần mềm.*
