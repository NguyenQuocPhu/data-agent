#!/bin/bash
echo "🐳 Khởi động Polyglot Docker Sandbox (Phase 2)..."

# Kích hoạt môi trường và set đường dẫn
source .venv/bin/activate
export PYTHONPATH="dgm_agent_v2/harness"

# Chạy harness trên thư mục data_60 mới
python -m dgm_agent_v2.harness.polyglot.run_evaluation \
    --predictions_path dgm_agent_v2/experiments/polyglot/data_60/predictions.jsonl \
    --run_id triadic_dgm_v2_full_60

echo "✅ Đánh giá hoàn tất. File kết quả JSON đã được lưu tại thư mục hiện tại!"
