# 🚀 Hướng Dẫn Cài Đặt & Khởi Chạy DeepAnalyze (LAMBDA)

Dự án này bao gồm 2 thành phần chính: **Backend (Python FastAPI)** đảm nhiệm xử lý Data Agent/AI và **Frontend (Next.js)** hiển thị giao diện phân tích.

Bạn có thể chạy dự án theo 2 cách: **Chạy qua Docker (Khuyên dùng)** hoặc **Chạy thủ công bằng Code**.

---

## 🔑 Bước 1: Cấu hình API Key (Bắt buộc)
Hệ thống AI cần API Key để hoạt động. Bạn hãy tạo một file tên là `.env` ở thư mục gốc của dự án (ngang hàng với file `docker-compose.yml`) và điền các Key bạn có vào:

```env
GROQ_API_KEY=gsk_xxx_your_groq_key_here
OPENAI_API_KEY=sk-xxx_your_openai_key_here
QWEN_API_KEY=your_qwen_key_here
```
*(Chỉ cần cung cấp API Key của mô hình mà bạn định dùng làm Core Engine, mặc định hệ thống đang dùng `qwen-2.5-coder-32b` qua Groq hoặc vLLM).*

---

## 🐳 Cách 1: Chạy bằng Docker Compose (Khuyên Dùng)
Cách này đơn giản nhất, không cần cài đặt Node.js hay Python rườm rà. Chỉ cần máy bạn có cài đặt [Docker Desktop](https://www.docker.com/products/docker-desktop/).

1. Mở Terminal / Command Prompt tại thư mục dự án.
2. Chạy lệnh sau để build và khởi động tất cả dịch vụ:
   ```bash
   docker compose up -d --build
   ```
3. Đợi vài phút để Docker cài đặt thư viện. Sau khi xong, bạn có thể truy cập:
   - 🌐 **DeepAnalyze Dashboard (Giao diện chính):** [http://localhost:13000](http://localhost:13000)
   - ⚙️ **Backend API (Swagger UI):** [http://localhost:18000/docs](http://localhost:18000/docs)
   - 💬 **Open WebUI (Giao diện Chat tùy chọn):** [http://localhost:18080](http://localhost:18080)

*(Để tắt hệ thống, chạy lệnh: `docker compose down`)*

---

## 💻 Cách 2: Chạy thủ công (Dành cho Developer/Debug)
Nếu bạn muốn sửa code và thấy thay đổi ngay lập tức (Hot-Reload) mà không cần build lại Docker. Yêu cầu máy phải có **Python 3.10+** và **Node.js 18+**.

**Bước 1: Cài đặt thư viện Backend (Python)**
```bash
# Tạo môi trường ảo (tùy chọn)
python -m venv .venv
source .venv/bin/activate  # Trên Windows: .venv\Scripts\activate

# Cài đặt thư viện
pip install -r requirements.txt
```

**Bước 2: Cài đặt thư viện Frontend (Node.js)**
```bash
cd ui/deepanalyze_frontend
npm install   # hoặc pnpm install
cd ../..
```

**Bước 3: Khởi động hệ thống (1 Click)**
Dự án đã có sẵn script khởi động tự động cả 2 server cùng lúc. Bạn chỉ cần chạy script tương ứng với hệ điều hành:

- **Trên Windows (PowerShell):**
  ```powershell
  .\start_saas.ps1
  ```
- **Trên Linux / macOS:**
  ```bash
  bash start_saas.sh
  ```

Sau khi Terminal báo thành công, bạn truy cập vào:
- 🌐 **Giao diện chính:** [http://localhost:3000](http://localhost:3000)
- ⚙️ **Backend API:** [http://localhost:8000](http://localhost:8000)

---

## 🛠 Fix Lỗi Thường Gặp
- **Lỗi thiếu thư viện Python:** Đảm bảo bạn đã kích hoạt môi trường ảo (venv) trước khi chạy `pip install`.
- **Lỗi Next.js (Cannot resolve...):** Đảm bảo bạn đã chạy `npm install` ở thư mục `ui/deepanalyze_frontend`.
- **Lỗi cổng (Port already in use):** Tắt các ứng dụng đang chiếm cổng `3000`, `8000`, `13000` hoặc `18000`.
