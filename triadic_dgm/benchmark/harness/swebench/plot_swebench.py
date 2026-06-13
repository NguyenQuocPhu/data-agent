import json
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import sys
import os

def plot_report(json_path, output_path):
    with open(json_path, 'r') as f:
        data = json.load(f)
        
    resolved = len(data.get('resolved_ids', []))
    unresolved = len(data.get('unresolved_ids', []))
    empty = len(data.get('empty_patch_ids', []))
    error = len(data.get('error_ids', []))
    
    total_submitted = resolved + unresolved + empty + error
    
    # 1. Pie Chart
    labels = ['Resolved', 'Unresolved', 'Empty Patch', 'Error']
    sizes = [resolved, unresolved, empty, error]
    colors = ['#4CAF50', '#FF9800', '#9E9E9E', '#F44336']
    
    # Filter out 0 size
    sizes_filtered = []
    labels_filtered = []
    colors_filtered = []
    for s, l, c in zip(sizes, labels, colors):
        if s > 0:
            sizes_filtered.append(s)
            labels_filtered.append(l)
            colors_filtered.append(c)
            
    fig, ax = plt.subplots(figsize=(8, 8))
    
    if sizes_filtered:
        ax.pie(sizes_filtered, labels=labels_filtered, colors=colors_filtered, autopct='%1.1f%%', startangle=90, textprops={'fontsize': 14})
        ax.axis('equal')
        plt.title('SWE-bench Evaluation Results', fontsize=18, pad=20)
    else:
        ax.text(0.5, 0.5, 'No instances submitted', horizontalalignment='center', verticalalignment='center', fontsize=16)
        
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Chart saved to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python plot_swebench.py <json_report_path> <output_image_path>")
        sys.exit(1)
        
    json_path = sys.argv[1]
    output_path = sys.argv[2]
    
    plot_report(json_path, output_path)
