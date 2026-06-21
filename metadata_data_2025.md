# Từ Điển Dữ Liệu (Metadata) cho file data_2025.csv
Tập dữ liệu này chứa thông tin về tập khách hàng FTEL. Ghi chú quan trọng: TẬP DỮ LIỆU NÀY LÀ TẬP 100% KHÁCH HÀNG ĐÃ RỜI MẠNG (CHURN = 1.0).

## 1. Thông tin Định Danh và Nhân Khẩu Học (KHÔNG DÙNG ĐỂ TRAIN KMEANS)
- `OBJID`, `objid`, `CONTRACT`, `SKD_BILL_OBJECT`: Mã định danh khách hàng / mã hợp đồng.
- `LOCATIONID`, `LOCATIONNAME`: ID và tên khu vực địa lý của khách hàng.
- `BRANCHCODE`, `BRANCHNAME`, `BRANCHFULLNAMEVN`: Mã và tên chi nhánh viễn thông quản lý khách hàng.
- `SUBCOMPANYNAME`: Tên công ty con/đơn vị trực thuộc.
- `FILTER_MONTH`, `FILTER_YEAR`: Tháng và năm chốt dữ liệu (thường là thời điểm rời mạng).

## 2. Thông tin Doanh Thu & Cước (KHÔNG TRAIN KMEANS, CHỈ DÙNG ĐỂ TÍNH ARPU/REVENUE)
- `HSSD`: Số lượng hồ sơ sử dụng.
- `CTBDV`: Cước thuê bao dịch vụ (ARPU). Đây là biến quan trọng để tính Revenue At Risk.
- `SKD_BILL_LOCALTYPE`: Loại hình cước địa phương.

## 3. Các Biến Hành Vi Kỹ Thuật & Dịch Vụ (DÙNG ĐỂ TRAIN KMEANS)
*Chú ý: T10, T11, T12 đại diện cho 3 tháng lịch sử gần nhất trước khi rời mạng (Tháng 10, 11, 12).*

**Biến Sự cố mạng (Clearance/Faults):**
- `CL1_T11`, `CL1_T12`: Sự cố đứt cáp, mất kết nối hoàn toàn.
- `CL2_T11`, `CL2_T12`: Sự cố suy hao quang, mạng chập chờn, chậm.
- `CL3_T11`, `CL3_T12`: Sự cố liên quan đến thiết bị đầu cuối (Modem, Router bị lỗi/treo).
- `TOTAL_CL_T11`, `TOTAL_CL_T12`: Tổng số lượng sự cố (CL1+CL2+CL3) trong tháng.
- `HAS_CL_T11`, `HAS_CL_T12`: Biến cờ (0/1) đánh dấu khách hàng có gặp sự cố trong tháng hay không.

**Biến Khiếu nại Dịch vụ (Complaints):**
- `SR_COMPLAINT_T10`, `SR_COMPLAINT_T11`, `SR_COMPLAINT_T12`: Số lượng phiếu khiếu nại (Service Request) mà khách hàng gọi lên tổng đài CSKH phản ánh về chất lượng dịch vụ hoặc cước phí.
- `TOTAL_COMPLAINT_T10`, `TOTAL_COMPLAINT_T11`, `TOTAL_COMPLAINT_T12`: Tổng số khiếu nại.
- `HAS_COMPLAINT_T10`, `HAS_COMPLAINT_T11`, `HAS_COMPLAINT_T12`: Biến cờ (0/1) đánh dấu khách hàng có khiếu nại.

**Biến Mức độ Hài lòng (CSAT - Customer Satisfaction):**
- `num_csat12_r1`, `num_csat12_r2`: Điểm số hoặc số lần đánh giá không hài lòng qua các kênh (tổng đài, app).
- `total_csat`: Tổng điểm đánh giá chất lượng trải nghiệm của khách hàng (Càng thấp hoặc âm có thể là trải nghiệm tồi tệ).

## 4. Các biến Tổng Hợp Khác (DÙNG ĐỂ TRAIN KMEANS)
- `Total_T10`, `Total_T11`, `Total_T12`: Tổng giao dịch / tổng tương tác của khách hàng.
- `Segment_branch_T...`, `Segment_sub_T...`: Phân khúc khách hàng theo chi nhánh / đơn vị tại các tháng tương ứng.

---
**💡 HƯỚNG DẪN DÀNH CHO AI:**
- Khi phân cụm Persona, hãy DÙNG CÁC CỘT Ở PHẦN 3 VÀ 4 (Các biến có tiền tố CL, COMPLAINT, CSAT, Total).
- Bạn có thể gom nhóm các tháng lại với nhau để tạo thành feature đại diện. Ví dụ: `df['avg_complaint_3m'] = df[['TOTAL_COMPLAINT_T10', 'TOTAL_COMPLAINT_T11', 'TOTAL_COMPLAINT_T12']].mean(axis=1)`.
- Khi đặt tên Persona (Smart Name), hãy bám sát vào ý nghĩa các biến này. Ví dụ, nếu cụm có `CL2` (suy hao) và `CL3` (thiết bị) cao, hãy đặt tên là: "Rời mạng do mạng chập chờn và lỗi Modem". Nếu cụm có `COMPLAINT` cao, hãy đặt tên: "Rời mạng do trải nghiệm CSKH kém (Hay khiếu nại)".
