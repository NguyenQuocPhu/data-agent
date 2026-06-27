# Từ Điển Dữ Liệu (Metadata) cho file data_RM6T.csv

Tập dữ liệu này chứa thông tin về tập khách hàng FTEL. 
**Ghi chú quan trọng:** TẬP DỮ LIỆU NÀY LÀ TẬP 100% KHÁCH HÀNG ĐÃ RỜI MẠNG (CHURN = 1.0).

## 1. Thông tin Định Danh và Nhân Khẩu Học
*Lưu ý: Thường KHÔNG DÙNG để train model phân cụm hành vi (ví dụ: K-Means).*
- `OBJID_mask`: Mã định danh khách hàng (đã được mask) / mã hợp đồng.
- `LOCATIONID`, `LOCATIONNAME`: ID và tên khu vực địa lý của khách hàng.
- `BRANCHCODE`, `BRANCHNAME`, `BRANCHFULLNAMEVN`: Mã và tên chi nhánh viễn thông quản lý khách hàng.
- `SUBCOMPANYNAME`: Tên công ty con/đơn vị trực thuộc.
- `FILTER_MONTH`, `FILTER_YEAR`: Tháng và năm chốt dữ liệu (thường là thời điểm rời mạng).

## 2. Thông tin Tài Chính, Cước & Trạng Thái Thuê Bao
*Lưu ý: Dùng để tính ARPU/Revenue hoặc lọc dữ liệu. Có thể kết hợp phân tích nguyên nhân rời mạng ngoài kỹ thuật.*
- `HSSD`: Hủy sau sử dụng.
- `CTBDV`: Chủ thuê bao đi vắng.
- `SKD_BILL_LOCALTYPE`: Loại hình cước địa phương.
- `status_t30_tX` (với X ∈ {1, 2, 3, 4}): Trạng thái thuê bao 30 ngày trong các tháng T1, T2, T3, T4.
- `status_t90_tX` (với X ∈ {1, 2, 3, 4}): Trạng thái thuê bao 90 ngày trong các tháng T1, T2, T3, T4.

## 3. Phân Khúc Khách Hàng
- `Segment_branch_TX` (với X ∈ {1, 2, 3, 4, 10, 11, 12}): Phân khúc khách hàng theo chi nhánh tại tháng tương ứng.
- `Segment_sub_TX` (với X ∈ {1, 2, 3, 4, 10, 11, 12}): Phân khúc khách hàng theo đơn vị/công ty con tại tháng tương ứng.

## 4. Hành Vi Kỹ Thuật & Dịch Vụ (Quan trọng cho K-MEANS)
*Chú ý: Ký hiệu TX (như T1, T2, T3, T4, T10, T11, T12) đại diện cho các tháng lịch sử trước khi rời mạng.*

### 4.1 Sự cố mạng (Clearance/Faults)
- `CL1_TX` (X ∈ {1, 2, 3, 4, 11, 12}): Checklist hỗ trợ kỹ thuật lần 1.
- `CL2_TX` (X ∈ {1, 2, 3, 4, 11, 12}): Checklist lặp 2 hỗ trợ kỹ thuật.
- `CL3_TX` (X ∈ {1, 2, 3, 4, 11, 12}): Checklist lặp 3 hỗ trợ kỹ thuật.
- `TOTAL_CL_TX`: Tổng số lượng sự cố (CL1+CL2+CL3) trong tháng X.
- `HAS_CL_TX`: Biến cờ (0/1) đánh dấu khách hàng có gặp sự cố trong tháng X hay không.

### 4.2 Khiếu nại Dịch vụ (Complaints)
- `SR_COMPLAINT_TX` (X ∈ {1, 2, 3, 4, 10, 11, 12}): Số lượng phiếu khiếu nại (Service Request) gọi lên tổng đài CSKH.
- `TOTAL_COMPLAINT_TX`: Tổng số khiếu nại trong tháng X.
- `HAS_COMPLAINT_TX`: Biến cờ (0/1) đánh dấu khách hàng có khiếu nại trong tháng X hay không.

### 4.3 Tương tác Cuộc gọi (Calls)
- `total_call_TX` (X ∈ {1, 2, 3, 4}): Tổng số cuộc gọi của khách hàng trong tháng X.
- `total_missed_call_TX` (X ∈ {1, 2, 3, 4}): Tổng số cuộc gọi nhỡ trong tháng X.
- `HAS_CALL_TX`, `HAS_MISSED_CALL_TX`: Cờ đánh dấu có gọi điện hoặc có cuộc gọi nhỡ trong tháng X.
- `Total_TX` (X ∈ {1, 2, 3, 4, 10, 11, 12}): Tổng giao dịch / tổng tương tác của khách hàng trong tháng X.

### 4.4 Mức độ Hài lòng (CSAT - Customer Satisfaction)
- `num_csat12_r1`, `num_csat12_r2`: Số lần đánh giá không hài lòng qua các kênh (tổng đài, app).
- `total_csat`: Tổng số lần đánh giá trải nghiệm của khách hàng.

---

## 💡 HƯỚNG DẪN ỨNG DỤNG CHO AI (K-Means & Phân tích Persona):

1. **Lựa chọn đặc trưng (Feature Selection)**: 
   - Tập trung sử dụng các biến ở mục 4 (`CL`, `COMPLAINT`, `CSAT`, `Call`, `Total`) để phân cụm hành vi bằng học máy (VD: K-Means).

2. **Kỹ thuật gom nhóm (Feature Engineering)**: 
   - Có thể tính trung bình hoặc tổng các tháng để tạo thành một feature đại diện chung, giúp giảm bớt số chiều của dữ liệu và bắt được trend.
   - *Ví dụ mã Python*: `df['avg_complaint_3m'] = df[['TOTAL_COMPLAINT_T1', 'TOTAL_COMPLAINT_T2', 'TOTAL_COMPLAINT_T3']].mean(axis=1)`.

3. **Đặt tên Persona (Smart Naming)**: 
   - Nhãn của từng cụm (Cluster Label) nên được phân tích dựa trên sự phân phối của các feature nổi bật nhất của cụm đó.
   - *Ví dụ 1*: Nếu các cột `CL2` (suy hao) và `CL3` (thiết bị) cao nổi bật ➔ Đặt tên: **"Rời mạng do mạng chập chờn và lỗi Modem"**.
   - *Ví dụ 2*: Nếu cột `COMPLAINT` cao nổi bật ➔ Đặt tên: **"Rời mạng do trải nghiệm CSKH kém (Tần suất khiếu nại cao)"**.
   - *Ví dụ 3*: Nếu các chỉ số kỹ thuật bình thường nhưng `CTBDV` cao ➔ Đặt tên: **"Rời mạng do yếu tố cá nhân khách hàng (Đi vắng, chuyển nhà)"**.
