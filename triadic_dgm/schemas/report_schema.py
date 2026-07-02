from pydantic import BaseModel, Field
from typing import List, Optional

class ExecutiveSummaryNarrative(BaseModel):
    executive_overview: str = Field(description="Một đoạn văn liền mạch (3-4 câu) tổng quan tình hình kinh doanh. KHÔNG CÓ SỐ LIỆU. KHÔNG BULLETS.")

class PersonaNarrative(BaseModel):
    cluster_id: int = Field(description="ID của cụm")
    business_interpretation: str = Field(description="Giải thích ý nghĩa nghiệp vụ. TỐI ĐA 2 CÂU. KHÔNG LẶP SỐ LIỆU.")
    operational_impact: str = Field(description="Tác động lên doanh nghiệp (ví dụ: Retention, Operational Cost). TỐI ĐA 2 CÂU.")
    risk_tier_commentary: Optional[str] = Field(default=None, description="1 câu diễn giải mức độ ưu tiên hành động cho nhóm này. KHÔNG LẶP SỐ LIỆU.")

class ActionNarrative(BaseModel):
    cluster_id: int = Field(description="ID của cụm")
    expected_outcome: str = Field(description="Tác động kỳ vọng khi thực hiện hành động này. TỐI ĐA 2 CÂU.")

class ReportNarrative(BaseModel):
    executive_summary: ExecutiveSummaryNarrative
    personas_analysis: List[PersonaNarrative]
    recommendations_analysis: List[ActionNarrative]
    conclusion: str = Field(description="Đoạn văn kết luận toàn bộ báo cáo. TỐI ĐA 3 CÂU.")
