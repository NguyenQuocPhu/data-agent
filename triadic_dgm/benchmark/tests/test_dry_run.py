import os
import json
from triadic_dgm.benchmark.DGM_orchestrator import run_ds_pipeline

def main():
    # 1. Tạo thư mục workspace giả lập và bài test
    workspace_dir = "./triadic_dgm.benchmark/test_workspace"
    os.makedirs(workspace_dir, exist_ok=True)
    
    # Tạo một file CSV giả
    csv_path = os.path.join(workspace_dir, "sales_data.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("id,date,sales,region\n1,2023-01-01,100,North\n2,2023-01-02,150,South\n3,2023-01-03,,East\n")
        
    # Tạo file manifest (đề bài JSON)
    manifest_path = "./triadic_dgm.benchmark/test_manifest.json"
    task = {
        "task_id": "test_task_001",
        "description": "Read the sales_data.csv file. Fill missing sales values with the mean, then calculate the total sales by region.",
        "workspace": workspace_dir
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump([task], f, indent=4)
        
    output_dir = "./triadic_dgm.benchmark/test_output"
    os.makedirs(output_dir, exist_ok=True)

    print("🚀 BẮT ĐẦU DRY-RUN HỆ THỐNG TRIADIC DGM V2...")
    # 2. Khởi chạy Pipeline
    run_ds_pipeline(manifest_path, output_dir)
    
    # 3. Kiểm tra kết quả Archive sinh ra cho Outer Loop
    archive_path = os.path.join(output_dir, "evolution_archive.json")
    if os.path.exists(archive_path):
        print(f"\n✅ Dry-run thành công! Đã sinh ra file: {archive_path}")
        with open(archive_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(json.dumps(data, indent=2))
    else:
        print("\n❌ Lỗi: Không tìm thấy file evolution_archive.json!")

if __name__ == "__main__":
    main()
