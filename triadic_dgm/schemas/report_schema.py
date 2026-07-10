from pydantic import BaseModel, Field
from typing import List

class ExecutiveSummaryNarrative(BaseModel):
    executive_overview: str = Field(description="Một đoạn văn liền mạch (3-4 câu) tổng quan tình hình kinh doanh. KHÔNG CÓ SỐ LIỆU. KHÔNG BULLETS.")

class PersonaNarrative(BaseModel):
    cluster_id: int = Field(description="ID của cụm")
    business_interpretation: str = Field(description="Giải thích ý nghĩa nghiệp vụ. TỐI ĐA 2 CÂU. KHÔNG LẶP SỐ LIỆU.")
    operational_impact: str = Field(description="Tác động lên doanh nghiệp (ví dụ: Retention, Operational Cost). TỐI ĐA 2 CÂU.")

# ActionNarrative/recommendations_analysis/risk_tier_commentary đã bị xoá — chưa từng được đọc ở bất
# kỳ đâu trong report_generator.py (chỉ tồn tại trong schema + _fallback_narrative), nghĩa là mọi lần
# gọi LLM đều tốn thời gian sinh ra các trường này một cách vô ích, góp phần làm request lâu hơn và dễ
# chạm timeout gateway (504) hơn mức cần thiết.
class ReportNarrative(BaseModel):
    executive_summary: ExecutiveSummaryNarrative
    personas_analysis: List[PersonaNarrative]
    conclusion: str = Field(description="Đoạn văn kết luận toàn bộ báo cáo. TỐI ĐA 3 CÂU.")
