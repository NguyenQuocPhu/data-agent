import sys
import os

# 1. Chèn thư mục harness vào ĐẦU sys.path để ưu tiên dùng swebench local thay vì pip
harness_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "harness"))
sys.path.insert(0, harness_dir)

# 2. Xóa các module swebench đã cache (nếu có)
for key in list(sys.modules.keys()):
    if key.startswith("swebench"):
        del sys.modules[key]

# 3. Import run_evaluation từ polyglot
from polyglot.run_evaluation import main

if __name__ == "__main__":
    # Các tham số bắt buộc cho Smoke Test Phase 2
    # --dataset_name: polyglot ko có file metadata cục bộ, mà load_swebench_dataset() 
    # trong polyglot sẽ tự phân giải sang 'xlangai/polyglot' hoặc file json
    # Ta truyền đường dẫn file polyglot_60.json làm dataset_name.
    dataset_name = os.path.join(harness_dir, "polyglot", "subsets", "polyglot_60.json")
    
    predictions_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "predictions.jsonl"))
    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
    
    # polyglot_60.json có instance_ids. Tạm truyền rỗng để lấy toàn bộ 6 bài trong predictions.jsonl
    # run_evaluation sẽ tự filter
    
    print(f"🚀 Khởi chạy Polyglot Docker Harness với {predictions_path}")
    
    try:
        main(
            dataset_name=dataset_name,
            split="test",
            instance_ids=None,
            predictions_path=predictions_path,
            max_workers=4,
            force_rebuild=False,
            cache_level="env",
            clean=False,
            open_file_limit=4096,
            run_id="smoke_test",
            timeout=1800
        )
    except Exception as e:
        print(f"❌ Lỗi: {e}")
