from LAMBDA import LAMBDA
import os
from .services import workspace as workspace_service

# Khởi tạo singleton instance
print("Initializing LAMBDA Backend...")
lambda_instance = LAMBDA(config_path='config.yaml')
print(f"LAMBDA session cache path: {lambda_instance.session_cache_path}")

# Tự động đồng bộ các file đã upload trong workspace của UI vào não của LAMBDA khi khởi động lại server
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAFE_REPO_ROOT = str(REPO_ROOT).replace('\\', '/')
workspace_dir = workspace_service.resolve_workspace_root("default")
safe_workspace_dir = str(workspace_dir).replace('\\', '/')

print("Injecting load_dataset into Sandbox Kernel...")
tool_layer_code = f"""
import sys
# Put the repo on the sandbox kernel's path: it runs with cwd set to the session cache
# directory, so `import triadic_dgm` fails without this. The generated code needs it to call
# run_persona_pipeline() instead of retyping the clustering/rule-engine script every run.
if r'{_SAFE_REPO_ROOT}' not in sys.path:
    sys.path.insert(0, r'{_SAFE_REPO_ROOT}')

import json
import pandas as pd
import os

_DATASET_CACHE = dict()

def load_dataset(file_id=None):
    \"\"\"Load a dataset by file_id or filename. If no argument, load the first available dataset.\"\"\"
    workspace_root = r'{safe_workspace_dir}'
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        raise ValueError("No index.json found in workspace. Please upload a file first.")
        
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
    
    if not index_data:
        raise ValueError("No datasets available. Please upload a file first.")
    
    # If no file_id provided, load latest dataset
    if file_id is None:
        # Prioritize tabular files (CSV/Excel) over other types like JSON
        tabular_exts = {{'.csv', '.tsv', '.xlsx', '.xls', '.parquet'}}
        
        # Filter to tabular files only first
        tabular_entries = [
            (fid, info) for fid, info in index_data.items()
            if os.path.splitext(info.get('filename', info.get('path', '')))[1].lower() in tabular_exts
        ]
        
        if tabular_entries:
            # Sort by created_at descending → pick latest tabular file
            tabular_entries.sort(key=lambda x: x[1].get('created_at', ''), reverse=True)
            file_id = tabular_entries[0][0]
        else:
            # Fallback: pick latest file of any type
            dated = [(fid, info.get('created_at','')) for fid, info in index_data.items() if info.get('created_at')]
            if dated:
                dated.sort(key=lambda x: x[1], reverse=True)
                file_id = dated[0][0]
            else:
                file_id = list(index_data.keys())[-1]
        print(f"Auto-selecting dataset: {{index_data[file_id].get('filename', file_id)}} (ID: {{file_id}})")
    
    # Try exact match first
    if file_id in index_data:
        matched_id = file_id
    else:
        # Fallback: search by filename (exact or partial match)
        matched_id = None
        search = str(file_id).lower().strip()
        for fid, info in index_data.items():
            fname = info.get('filename', os.path.basename(info.get('path',''))).lower()
            if search == fname or search == os.path.splitext(fname)[0] or search in fname:
                matched_id = fid
                break
        if matched_id is None:
            available = ', '.join(f"'{{fid}}' ({{info.get('filename','?')}})" for fid, info in index_data.items())
            raise ValueError(f"File '{{file_id}}' not found. Available datasets: {{available}}")
    
    if matched_id in _DATASET_CACHE:
        return _DATASET_CACHE[matched_id]
    
    file_path = os.path.join(workspace_root, index_data[matched_id]['path'])
    if not os.path.exists(file_path):
        raise FileNotFoundError("File not found: " + str(file_path))
        
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.csv', '.tsv']:
        df = pd.read_csv(file_path, sep='\\t' if ext == '.tsv' else ',')
    elif ext in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    else:
        raise ValueError("Unsupported extension " + ext)
        
    _DATASET_CACHE[matched_id] = df
    print(f"Loaded '{{index_data[matched_id].get('filename', matched_id)}}': {{len(df)}} rows x {{len(df.columns)}} columns")
    return df

def list_datasets():
    \"\"\"List all available datasets in the workspace.\"\"\"
    workspace_root = r'{safe_workspace_dir}'
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        print("No datasets available.")
        return
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
    if not index_data:
        print("No datasets available.")
        return
    print(f"Available datasets ({{len(index_data)}}):")
    for fid, info in index_data.items():
        print(f"  - load_dataset('{{fid}}')  # {{info.get('filename', fid)}}")
"""
lambda_instance.conv.run_code(tool_layer_code)

def get_lambda_agent():
    return lambda_instance
