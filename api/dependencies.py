from LAMBDA import LAMBDA
import os
from .services import workspace as workspace_service

# Khởi tạo singleton instance
print("Initializing LAMBDA Backend...")
lambda_instance = LAMBDA(config_path='config.yaml')
print(f"LAMBDA session cache path: {lambda_instance.session_cache_path}")

# Tự động đồng bộ các file đã upload trong workspace của UI vào não của LAMBDA khi khởi động lại server
workspace_dir = workspace_service.resolve_workspace_root("default")
safe_workspace_dir = str(workspace_dir).replace('\\', '/')

print("Injecting load_dataset into Sandbox Kernel...")
tool_layer_code = f"""
import json
import pandas as pd
import os

_DATASET_CACHE = dict()

def load_dataset(file_id):
    if file_id in _DATASET_CACHE:
        return _DATASET_CACHE[file_id]
        
    workspace_root = r'{safe_workspace_dir}'
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        raise ValueError("No index.json found in workspace")
        
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
        
    if file_id not in index_data:
        raise ValueError("File ID '" + str(file_id) + "' not found")
        
    file_path = os.path.join(workspace_root, index_data[file_id]['path'])
    if not os.path.exists(file_path):
        raise FileNotFoundError("File not found: " + str(file_path))
        
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.csv', '.tsv']:
        df = pd.read_csv(file_path, sep='\\t' if ext == '.tsv' else ',')
    elif ext in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    else:
        raise ValueError("Unsupported extension " + ext)
        
    if len(df) < 1000:
        raise ValueError("Hệ thống chặn: LLM bị phát hiện dùng dữ liệu giả. Số lượng dòng < 1000.")
        
    _DATASET_CACHE[file_id] = df
    return df
"""
lambda_instance.conv.run_code(tool_layer_code)

def get_lambda_agent():
    return lambda_instance
