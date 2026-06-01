import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

def plot_final_results():
    plt.figure(figsize=(10, 6))
    sns.set_theme(style="whitegrid")
    
    methods = ['DS-Bench (LLM-Judge)', 'DA-Code (Execution-based)']
    pass_rates = [10.0, 34.0]
    
    colors = ['#ff9999', '#66b3ff']
    bars = plt.bar(methods, pass_rates, color=colors, width=0.5)
    
    plt.title('Qwen-35B Pass Rate Comparison (MDL-Pruner)', fontsize=16, pad=20)
    plt.ylabel('Pass Rate (%)', fontsize=12)
    plt.ylim(0, 100)
    
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height + 2,
                f'{height:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=12)
                
    # Add improvement arrow/text
    plt.annotate('3.4x Improvement!', 
                xy=(1, 34), xycoords='data',
                xytext=(0.5, 60), textcoords='data',
                arrowprops=dict(facecolor='green', shrink=0.05, width=2, headwidth=8),
                fontsize=12, fontweight='bold', color='green',
                horizontalalignment='center')
                
    plt.tight_layout()
    plt.savefig('C:/Users/Lenovo/.gemini/antigravity-ide/brain/be374064-f24b-4f79-b671-ddc96afd98dd/dacode_final_results.png', dpi=300)
    print("Plot saved to artifacts.")

if __name__ == "__main__":
    plot_final_results()
