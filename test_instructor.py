import os
import json
import instructor
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List, Literal

# Đọc .env thủ công (không cần cài thư viện dotenv)
api_key = ""
try:
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("QWEN_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
except FileNotFoundError:
    pass

# --- 1. Định nghĩa SCHEMA BẮT BUỘC (LLM không thể cãi) ---
class PersonaInsight(BaseModel):
    persona_name: str = Field(description="Tên của nhóm khách hàng")
    severity: Literal["LOW", "MEDIUM", "HIGH", "EXTREME"] = Field(description="Mức độ nghiêm trọng")
    behavior_insight: str = Field(description="Insight giải thích TẠI SAO nhóm này lại có hành vi như vậy (tối đa 2 câu)")

class ActionPriority(BaseModel):
    persona_name: str
    recommended_action: str = Field(description="Hành động CSKH đề xuất. PHẢI LẤY TỪ raw_json, KHÔNG ĐƯỢC BỊA")
    reason: str = Field(description="Lý do tại sao chọn hành động này")

class FinalReport(BaseModel):
    executive_summary: str = Field(description="Tóm tắt ngắn gọn báo cáo (2-3 câu)")
    personas: List[PersonaInsight]
    actions: List[ActionPriority]
    the_one_action: str = Field(description="Chiến dịch quan trọng nhất cần làm ngay. PHẢI LẤY TỪ actions phía trên.")

# --- 2. Khởi tạo Client với Instructor ---
if not api_key:
    print("WARNING: QWEN_API_KEY not found in environment. Please check .env file.")

client = instructor.from_openai(
    OpenAI(
        api_key=api_key,
        base_url="https://proxy.onebot.meobeo.ai/v1"
    ),
    mode=instructor.Mode.JSON
)

# --- 3. Test với Dữ liệu mẫu ---
raw_python_output = """
[JSON_START_PERSONA]
[
  {
    "persona_name": "Sự cố kỹ thuật mức cao",
    "cl_total_6m": 10.5,
    "recommended_actions": ["Kiểm tra chất lượng mạng", "Cử kỹ thuật viên xuống nhà"]
  },
  {
    "persona_name": "Khách hàng im lặng",
    "cl_total_6m": 0,
    "recommended_actions": ["Thu thập thêm App usage logs", "Gửi SMS khảo sát"]
  }
]
[JSON_END_PERSONA]
"""

prompt = f"""
Hãy phân tích dữ liệu JSON sau và đưa ra báo cáo. 
TUYỆT ĐỐI TUÂN THỦ SCHEMA ĐƯỢC YÊU CẦU. Không tự chế Action.
Dữ liệu:
{raw_python_output}
"""

print("Đang gọi LLM với Structured Output (Ép kiểu Pydantic)...")
try:
    report: FinalReport = client.chat.completions.create(
        model="hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8",
        response_model=FinalReport,
        messages=[{"role": "user", "content": prompt}],
        max_retries=2
    )

    # --- 4. Tận hưởng kết quả chuẩn xác 100% ---
    print("\n✅ KẾT QUẢ ĐÃ ĐƯỢC ÉP KIỂU THÀNH CÔNG (PYTHON OBJECT):")
    print("=" * 60)
    print(f"📌 EXECUTIVE SUMMARY: {report.executive_summary}\n")
    print(f"🏆 THE ONE ACTION: {report.the_one_action}\n")
    
    print("👥 THÔNG TIN PERSONAS:")
    for p in report.personas:
        print(f"  + [{p.severity}] {p.persona_name}: {p.behavior_insight}")
        
    print("\n🎯 ĐỀ XUẤT HÀNH ĐỘNG:")
    for a in report.actions:
        print(f"  + {a.persona_name} -> {a.recommended_action} (Lý do: {a.reason})")
    print("=" * 60)
except Exception as e:
    print(f"Lỗi khi gọi API: {e}")
