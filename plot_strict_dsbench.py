import json
import os
import matplotlib.pyplot as plt
import seaborn as sns

def analyze_strict_results(report_path="data/results_unified_strict/ds_report.json"):
    if not os.path.exists(report_path):
        print(f"File {report_path} chưa được tạo. Vui lòng chờ Benchmark chạy xong!")
        return

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    total = report.get("total", 0)
    passed = report.get("passed", 0)
    failed = total - passed
    pass_rate = report.get("pass_rate", 0) * 100

    print(f"{'='*50}")
    print(f"📊 KẾT QUẢ ĐÁNH GIÁ NGHIÊM NGẶT (STRICT LLM-AS-A-JUDGE)")
    print(f"{'='*50}")
    print(f"Tổng số bài: {total}")
    print(f"✅ Pass (Đúng đáp án): {passed}")
    print(f"❌ Fail (Sai đáp án / Lỗi code): {failed}")
    print(f"🎯 Pass Rate thực tế: {pass_rate:.1f}%")
    print(f"{'='*50}")

    # Vẽ biểu đồ so sánh với Baseline
    labels = ['Claude 4 Opus\n(Paper Baseline)', 'DGM + Qwen-35B\n(Our Strict SOTA)']
    rates = [49.8, pass_rate]
    colors = ['#ced4da', '#2b8a3e']

    plt.figure(figsize=(8, 6))
    bars = plt.bar(labels, rates, color=colors, width=0.5)
    
    # Add labels on top of bars
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{height:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=12)

    plt.ylim(0, 100)
    plt.ylabel('Strict Accuracy Pass Rate (%)', fontsize=12)
    plt.title('DS-Bench Unified Data Lake Evaluation\n(Evaluated using Strict LLM-as-a-judge)', fontsize=14, pad=15)
    
    # Threshold line
    plt.axhline(y=49.8, color='r', linestyle='--', alpha=0.5, label='Previous SOTA')
    plt.legend()

    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    output_img = "data/dsbench_strict_results.png"
    plt.savefig(output_img, dpi=300)
    print(f"\nĐã lưu biểu đồ vào: {output_img}")

if __name__ == "__main__":
    analyze_strict_results()
