import json
import re

with open('data_processed_t4_metadata.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

def get_description(col):
    col_lower = col.lower()
    
    if col == 'OBJID_mask': return "Mã định danh khách hàng (đã che)"
    
    if 'cl_' in col_lower or col_lower.endswith('_cl'):
        prefix = "Sự cố kỹ thuật (CL)"
        if 'total' in col_lower: return f"Tổng số {prefix} trong 6 tháng"
        if 'avg' in col_lower: return f"Trung bình số {prefix} mỗi tháng"
        if 'active' in col_lower: return f"Số tháng có phát sinh {prefix}"
        if 'std' in col_lower: return f"Độ lệch chuẩn của {prefix} (sự biến động)"
        if 'old' in col_lower: return f"Số {prefix} ở giai đoạn cũ (tháng 4-6)"
        if 'recent' in col_lower and 'only' not in col_lower: return f"Số {prefix} ở giai đoạn gần đây (tháng 1-3)"
        if 'trend' in col_lower: return f"Xu hướng {prefix} (dương là tăng, âm là giảm)"
        if 'recent_only' in col_lower: return f"Chỉ phát sinh {prefix} gần đây (1=Có, 0=Không)"
        if 'no_cl_all_period' in col_lower: return "Không có sự cố nào trong toàn bộ 6 tháng (1=Đúng, 0=Sai)"
        if 'months_since_last' in col_lower: return f"Số tháng kể từ lần có {prefix} cuối cùng"
        if 'frequent' in col_lower: return f"Khách hàng thường xuyên gặp {prefix} (1=Có, 0=Không)"
        if 'escalating' in col_lower: return f"Tình trạng {prefix} đang leo thang (1=Có, 0=Không)"
        if 'declining' in col_lower: return f"Tình trạng {prefix} đang giảm (1=Có, 0=Không)"
        
    if 'complaint' in col_lower:
        prefix = "Khiếu nại (Complaint)"
        if 'total' in col_lower: return f"Tổng số {prefix} trong 6 tháng"
        if 'avg' in col_lower: return f"Trung bình số {prefix} mỗi tháng"
        if 'active' in col_lower: return f"Số tháng có phát sinh {prefix}"
        if 'std' in col_lower: return f"Độ lệch chuẩn của {prefix} (sự biến động)"
        if 'old' in col_lower: return f"Số {prefix} ở giai đoạn cũ (tháng 4-6)"
        if 'recent' in col_lower and 'only' not in col_lower: return f"Số {prefix} ở giai đoạn gần đây (tháng 1-3)"
        if 'trend' in col_lower: return f"Xu hướng {prefix} (dương là tăng, âm là giảm)"
        if 'recent_only' in col_lower: return f"Chỉ phát sinh {prefix} gần đây (1=Có, 0=Không)"
        if 'no_complaint_all_period' in col_lower: return "Không có khiếu nại nào trong toàn bộ 6 tháng (1=Đúng, 0=Sai)"
        if 'escalating' in col_lower: return f"Tình trạng {prefix} đang leo thang (1=Có, 0=Không)"
        if 'declining' in col_lower: return f"Tình trạng {prefix} đang giảm (1=Có, 0=Không)"
        
    if 'call' in col_lower or 'missed' in col_lower or 'contact' in col_lower:
        if 'call' in col_lower: prefix = "Cuộc gọi CSKH (Call)"
        elif 'missed' in col_lower: prefix = "Cuộc gọi nhỡ (Missed Call)"
        else: prefix = "Tương tác (Contact)"
        
        if 'total' in col_lower: return f"Tổng số {prefix} trong 6 tháng"
        if 'avg' in col_lower: return f"Trung bình số {prefix} mỗi tháng"
        if 'active' in col_lower: return f"Số tháng có phát sinh {prefix}"
        if 'ratio' in col_lower and 'high' not in col_lower: return "Tỷ lệ gọi nhỡ trên tổng số cuộc gọi"
        if 'high_missed_ratio' in col_lower: return "Tỷ lệ gọi nhỡ cao bất thường (1=Có, 0=Không)"
        if 'std' in col_lower: return f"Độ lệch chuẩn của {prefix}"
        if 'cv' in col_lower: return f"Hệ số biến thiên (CV) của {prefix}"
        if 'old' in col_lower: return f"Số {prefix} ở giai đoạn cũ"
        if 'recent' in col_lower and 'only' not in col_lower: return f"Số {prefix} ở giai đoạn gần đây"
        if 'trend' in col_lower: return f"Xu hướng {prefix}"
        if 'recent_only' in col_lower: return f"Chỉ phát sinh {prefix} gần đây"
        if 'no_' in col_lower and 'all_period' in col_lower: return f"Không có {prefix} trong toàn bộ kỳ (1=Có)"
        if 'months_since_last' in col_lower: return f"Số tháng kể từ lần {prefix} cuối cùng"
        if 'months_since_first' in col_lower: return f"Số tháng kể từ lần {prefix} đầu tiên"
        if 'frequent_caller' in col_lower: return "Khách hàng thường xuyên gọi (1=Có, 0=Không)"
        if 'escalating' in col_lower: return f"{prefix} đang leo thang (tăng dần)"
        if 'declining' in col_lower: return f"{prefix} đang giảm dần"

    if 'fee' in col_lower or 'spending' in col_lower:
        if 'total' in col_lower: return "Tổng cước phí/doanh thu trong 6 tháng"
        if 'avg' in col_lower: return "Trung bình cước phí mỗi tháng"
        if 'max' in col_lower: return "Cước phí cao nhất trong 1 tháng"
        if 'std' in col_lower: return "Độ biến động của cước phí"
        if 'active' in col_lower: return "Số tháng có phát sinh cước phí"
        if 'old' in col_lower: return "Cước phí trung bình giai đoạn cũ"
        if 'recent' in col_lower: return "Cước phí trung bình giai đoạn gần đây"
        if 'trend' in col_lower: return "Xu hướng cước phí (dương = tăng, âm = giảm)"
        if 'no_fee' in col_lower: return "Không có cước phí trong cả 6 tháng"
        if 'high_spender' in col_lower: return "Khách hàng chi tiêu cao (1=Có)"
        if 'spending_decline' in col_lower: return "Khách hàng có chi tiêu đang giảm dần (1=Có)"
        if 'spending_growth' in col_lower: return "Khách hàng có chi tiêu đang tăng (1=Có)"

    if 'segment' in col_lower:
        if 'branch' in col_lower:
            if 'avg' in col_lower: return "Phân khúc theo chi nhánh (Trung bình)"
            if 'std' in col_lower: return "Độ biến động phân khúc theo chi nhánh"
            if 'latest' in col_lower: return "Phân khúc chi nhánh hiện tại"
            if 'trend' in col_lower: return "Xu hướng hạng phân khúc chi nhánh"
            if 'upgrade' in col_lower: return "Số lần nâng hạng phân khúc chi nhánh"
            if 'downgrade' in col_lower: return "Số lần tụt hạng phân khúc chi nhánh"
            if 'drop_recent' in col_lower: return "Có tụt hạng phân khúc chi nhánh gần đây không (1=Có)"
        else:
            if 'avg' in col_lower: return "Phân khúc khách hàng (Trung bình 6 tháng)"
            if 'latest' in col_lower: return "Phân khúc khách hàng hiện tại"
            if 'oldest' in col_lower: return "Phân khúc khách hàng 6 tháng trước"
            if 'trend' in col_lower: return "Xu hướng hạng phân khúc (dương = nâng hạng, âm = tụt hạng)"
            if 'downgrade' in col_lower: return "Số lần tụt hạng phân khúc"
            if 'upgrade' in col_lower: return "Số lần nâng hạng phân khúc"
            if 'std' in col_lower: return "Độ biến động phân khúc"

    if 'cnt_' in col_lower or 'ever_' in col_lower or 'persistent_' in col_lower:
        if 'DEFAULT' in col_lower: return "Số tháng ở trạng thái DEFAULT (mặc định)"
        if 'Binh_thuong' in col_lower: return "Số tháng ở trạng thái Bình thường"
        if 'Dao_dong' in col_lower: return "Số tháng có cước Dao động"
        if 'Giam_nhe' in col_lower and 'cnt' in col_lower: return "Số tháng có cước Giảm nhẹ"
        if 'Giam_manh' in col_lower and 'cnt' in col_lower: return "Số tháng có cước Giảm mạnh"
        if 'ever_giam_nhe' in col_lower: return "Từng có tháng bị Giảm nhẹ (1=Có)"
        if 'ever_giam_manh' in col_lower: return "Từng có tháng bị Giảm mạnh (1=Có)"
        if 'persistent_giam_manh' in col_lower: return "Bị giảm mạnh liên tục nhiều tháng (1=Có)"

    if 'status' in col_lower:
        if 'change_count' in col_lower: return "Số lần thay đổi trạng thái thuê bao"
        if 'trend' in col_lower: return "Xu hướng thay đổi trạng thái"
        if 'worsening' in col_lower: return "Trạng thái thuê bao đang xấu đi (ví dụ: Chuyển sang tạm ngưng/rời mạng)"
        
    if col == 'CUSTOMER_TYPE': return "Loại khách hàng (ví dụ: Cá nhân, Doanh nghiệp)"
    if col == 'VIP_TYPE': return "Loại VIP của khách hàng"
    if col == 'LOYALTY_RANK': return "Hạng hạng thẻ khách hàng thân thiết"
    if col == 'LOYALTY_STATUS': return "Trạng thái chương trình khách hàng thân thiết"
    if col == 'LOYALTY_POINT': return "Điểm xét hạng khách hàng thân thiết"
    if col == 'LOYALTY_COIN': return "Điểm tiêu dùng (coin) khách hàng thân thiết"

    return f"Chỉ số {col}"

for item in data['columns']:
    item['description'] = get_description(item['column'])

with open('data_processed_t4_metadata.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=4, ensure_ascii=False)

print("Updated metadata definitions successfully.")
