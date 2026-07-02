import json
import os
from triadic_dgm.services.report_generator import ReportGenerator

# mock output
mock_python_output = """
[JSON_START_PERSONA]
[
  {
    "cluster_id": 0,
    "persona_name": "Sự cố kỹ thuật mức trung bình",
    "support": 19134,
    "support_pct": 0.3526,
    "segmentation_quality": "NORMAL",
    "feature_means": {
      "cl_total_6m": 2.35,
      "months_since_last_call": 999
    },
    "recommended_actions": [
      "Outbound CSKH chủ động để xoa dịu khách hàng"
    ],
    "priority_score": 10
  }
]
[JSON_END_PERSONA]
"""

rg = ReportGenerator(
    api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
    base_url="https://api.openai.com/v1",
    model_name="gpt-4o-mini"
)

try:
    print("Testing generate_markdown_report...")
    # NOTE: since dummy key, API call will fail, but we can catch it
    res = rg.generate_markdown_report(mock_python_output)
    print("Success")
except Exception as e:
    print(f"Error: {e}")
