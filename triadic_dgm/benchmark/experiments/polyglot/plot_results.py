import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Patch

def plot_polyglot_results(report_path="triadic_dgm_v2.smoke_test_phase_2.json", output_dir="triadic_dgm.benchmark/experiments/polyglot/data/analysis_output"):
    print(f"📊 [PHASE 3] Đang đọc file báo cáo: {report_path}...")
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Đọc dữ liệu JSON
    if not os.path.exists(report_path):
        print(f"❌ Không tìm thấy file {report_path}. Bác nhớ đổi tên file mock cho khớp nhé!")
        return
        
    with open(report_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    # 2. Bóc tách dữ liệu (Hỗ trợ cả format SWE-bench chuẩn và format Custom DGM)
    tasks = []
    if 'resolved_instances' in data: # Format SWE-bench chuẩn
        for t in data.get('resolved_instances', []): tasks.append({"task_id": t, "status": "PASS"})
        for t in data.get('unresolved_instances', []): tasks.append({"task_id": t, "status": "FAIL"})
        for t in data.get('error_instances', []): tasks.append({"task_id": t, "status": "ERROR"})
    elif 'task_results' in data: # Format DGM Outer Loop
        tasks = data['task_results']
    else:
        print("❌ Format JSON không khớp chuẩn SWE-bench hoặc DGM.")
        return

    # 3. Chuẩn bị DataFrame
    records = []
    lang_map = {'python': 'Python', 'cpp': 'C++', 'java': 'Java', 'go': 'Go', 'rust': 'Rust', 'javascript': 'JavaScript'}
    
    for t in tasks:
        t_id = t['task_id']
        # Tách ngôn ngữ từ task_id (VD: "cpp__diamond" -> "cpp")
        lang_prefix = t_id.split('__')[0]
        lang_name = lang_map.get(lang_prefix, lang_prefix.capitalize())
        task_name = t_id.split('__')[-1]
        
        status = t.get('status', 'FAIL')
        if isinstance(t, str): # Fallback nếu là string array
            status = 'PASS'
            
        records.append({
            "Task_ID": task_name,
            "Language": lang_name,
            "Passed": 1 if status == "PASS" else 0,
            "Status": status
        })
        
    df = pd.DataFrame(records)
    
    # ==========================================
    # VẼ BIỂU ĐỒ 1: PASS RATE THEO NGÔN NGỮ (BAR CHART)
    # ==========================================
    plt.figure(figsize=(10, 6))
    pass_rates = df.groupby('Language')['Passed'].mean() * 100
    
    # Sắp xếp theo điểm giảm dần cho đẹp
    pass_rates = pass_rates.sort_values(ascending=False)
    
    sns.barplot(x=pass_rates.index, y=pass_rates.values, palette='mako')
    plt.title('Triadic DGM V2 - Pass Rate by Language (Polyglot Benchmark)', fontsize=14, pad=15)
    plt.ylabel('Pass Rate (%)', fontsize=12)
    plt.xlabel('Programming Language', fontsize=12)
    plt.ylim(0, 100)
    
    # In điểm số lên đỉnh cột
    for i, v in enumerate(pass_rates.values):
        plt.text(i, v + 2, f"{v:.1f}%", ha='center', fontweight='bold', fontsize=11)
        
    plt.tight_layout()
    bar_chart_path = os.path.join(output_dir, 'pass_rate_bar.png')
    plt.savefig(bar_chart_path, dpi=300)
    plt.close()
    print(f"✅ Đã lưu Biểu đồ Pass Rate: {bar_chart_path}")

    # ==========================================
    # VẼ BIỂU ĐỒ 2: MA TRẬN TASK STATUS (HEATMAP)
    # ==========================================
    plt.figure(figsize=(12, 8))
    
    # Chuyển đổi dữ liệu thành dạng Ma trận 2D
    matrix_df = df.pivot(index="Task_ID", columns="Language", values="Passed")
    
    # Bảng màu: Đỏ (Fail/Error/Skipped) - Xanh (Pass)
    cmap = sns.color_palette(["#ff6b6b", "#4ece8b"]) 
    
    ax = sns.heatmap(matrix_df, cmap=cmap, cbar=False, linewidths=2, linecolor='white')
    
    # Tạo Legend tùy chỉnh
    legend_elements = [
        Patch(facecolor='#4ece8b', edgecolor='w', label='PASS (Solved)'),
        Patch(facecolor='#ff6b6b', edgecolor='w', label='FAIL / SKIPPED')
    ]
    ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1.25, 1.05), title='Execution Status')
    
    plt.title('Triadic DGM V2 - Multi-Language Task Status Matrix', fontsize=14, pad=15)
    plt.ylabel('Exercise Name', fontsize=12)
    plt.xlabel('Programming Language', fontsize=12)
    
    plt.tight_layout()
    heatmap_path = os.path.join(output_dir, 'task_status_matrix.png')
    plt.savefig(heatmap_path, dpi=300)
    plt.close()
    print(f"✅ Đã lưu Ma trận Trạng thái: {heatmap_path}")
    print("🚀 [PHASE 3 HOÀN TẤT] Bác hãy mở thư mục analysis_output để xem ảnh nhé!")

if __name__ == "__main__":
    # Sử dụng mock_report.json để test
    report_path = os.path.join(os.path.dirname(__file__), "data", "mock_report.json")
    plot_polyglot_results(report_path=report_path)
