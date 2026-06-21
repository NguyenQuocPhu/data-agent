# Metadata: FTEL Comprehensive Customer Behavior Dataset (113 Columns)

## 1. TỔNG QUAN (OVERVIEW)
Bộ dữ liệu gồm 602,416 dòng và 113 cột, ghi nhận toàn diện lịch sử hành vi của khách hàng viễn thông theo chuỗi thời gian (Time-series) trong các tháng (T1, T2, T3, T4, T10, T11, T12). 

Quy ước thời gian: `T1` có thể là tháng hiện tại/gần nhất, `T2`, `T3`, `T4` là các tháng trước đó.

## 2. PHÂN LOẠI BIẾN (FEATURE CATEGORIES)

### 2.1 Định Danh & Địa Lý (ID & Geography)
*KHÔNG ĐƯỢC dùng các biến này trong quá trình phân cụm (Clustering).*
- **`OBJID_mask`, `objid`, `CONTRACT`**: Mã khách hàng / Hợp đồng đã được ẩn danh.
- **`LOCATIONID`, `LOCATIONNAME`**: Tỉnh / Thành phố.
- **`BRANCHCODE`, `BRANCHNAME`, `BRANCHFULLNAMEVN`, `SUBCOMPANYNAME`**: Mã và Tên chi nhánh / Vùng kinh doanh.

### 2.2 Hành Vi Kỹ Thuật & Cước Theo Tháng (Behavior & Usage - Mức độ gắn kết)
- **`status_t30_T...`, `status_t90_T...`**: Trạng thái khách hàng theo tháng (ví dụ: mất kết nối/không sử dụng 30 ngày hoặc 90 ngày). Đây là chỉ báo quan trọng của rủi ro Rời Mạng (Churn).
- **`Total_T...`, `Segment_branch_T...`, `Segment_sub_T...`**: Tổng dung lượng sử dụng, cước phí hoặc lưu lượng theo chi nhánh/công ty con trong từng tháng.

### 2.3 Sự Cố Mạng & Khiếu Nại (Technical Issues & Complaints)
*Đây là các biến BẮT BUỘC dùng làm trọng tâm cho phân tích chân dung nguy cơ rời mạng.*
- **`CL1_T...`, `CL2_T...`, `CL3_T...`**: Phân loại lỗi kỹ thuật/sự cố theo 3 mức độ ở từng tháng.
- **`TOTAL_CL_T...`, `HAS_CL_T...`**: Tổng số lượng và cờ (1/0) xác nhận có sự cố kỹ thuật.
- **`SR_COMPLAINT_T...`**: Tổng số lần khiếu nại dịch vụ (Service Request/Complaint).
- **`TOTAL_COMPLAINT_T...`, `HAS_COMPLAINT_T...`**: Tổng khiếu nại và cờ (1/0) có khiếu nại.

### 2.4 Tương Tác CSKH & Đánh Giá (Customer Service & Satisfaction)
- **`total_call_T...`, `total_missed_call_T...`**: Tổng số cuộc gọi đến tổng đài và số cuộc gọi bị nhỡ.
- **`HAS_CALL_T...`, `HAS_MISSED_CALL_T...`**: Cờ (1/0) biểu thị có gọi CSKH hay gọi nhỡ.
- **`num_csat12_r1`, `num_csat12_r2`, `total_csat`**: Điểm số đo lường sự hài lòng của khách hàng (CSAT).

### 2.5 Dịch Vụ & Cước Phí Khác
- **`HSSD`**: Hệ số sử dụng.
- **`CTBDV`**: Cước trung bình dịch vụ.
- **`SKD_BILL_LOCALTYPE`**: Loại hình thanh toán/dịch vụ nội bộ.
- **`FILTER_MONTH`, `FILTER_YEAR`**: Cột lọc thời gian truy xuất dữ liệu.

## 3. LƯU Ý CHO TRÍ TUỆ NHÂN TẠO (AI INSTRUCTIONS)

1. **TARGET LEAKAGE (CẢNH BÁO MỤC TIÊU):** 
   Bộ dữ liệu này KHÔNG có cột `RMDT` rõ ràng. Biến mục tiêu rời mạng (Churn) có thể đang nằm ẩn dưới dạng trạng thái tháng gần nhất (VD: `status_t30_T1` hoặc `status_t90_T1`). 
   👉 **Hành động:** Khi làm Clustering, bạn PHẢI loại bỏ TẤT CẢ các biến trạng thái của tháng T1 (hiện tại) để tránh Target Leakage.

2. **FEATURE SELECTION CHO K-MEANS:** 
   Chỉ sử dụng các biến **Hành vi, Sự Cố, Khiếu Nại, và Tương Tác CSKH** (Mục 2.3, 2.4). 
   Loại bỏ hoàn toàn ID, Vị trí địa lý (Mục 2.1) và Biến Cước/Doanh Thu (Mục 2.5) trước khi đưa vào KMeans. Các biến này chỉ dùng để Profiling sau khi đã chia cụm.

3. **TIME-SERIES AGGREGATION:**
   Do dữ liệu trải dài trên nhiều tháng (T1 -> T12), AI cần cẩn thận khi Gom cụm. Có thể phải tính tổng (SUM) hoặc trung bình (MEAN) của các sự cố trong 3 tháng gần nhất (T2, T3, T4) thành một cột mới như `avg_complaint_3M` để KMeans dễ phân tích hơn, thay vì đưa cả 113 cột vào model.

4. **ANTI-HALLUCINATION:** 
   Không được tự phát minh ra nguyên nhân rời mạng do "Đối thủ cạnh tranh" hoặc "Khuyến mãi" vì data không có. Hãy diễn giải cụm dựa trên độ sụt giảm dịch vụ (status), sự cố (CL1, CL2), và tương tác gọi CSKH (call/complaint). Tên Persona không được chứa số đếm vô nghĩa (Cluster 1, Cụm 0).
