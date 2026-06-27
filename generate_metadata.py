import csv
import json

def is_float(value):
    try:
        float(value)
        return True
    except ValueError:
        return False

def is_int(value):
    try:
        int(value)
        return True
    except ValueError:
        return False

with open('data_processed_t4.csv', 'r') as f:
    reader = csv.reader(f)
    headers = next(reader)
    row = next(reader)
    
    metadata = []
    for i, col in enumerate(headers):
        val = row[i]
        
        dtype = "string"
        if is_int(val):
            dtype = "int"
        elif is_float(val):
            dtype = "float"
            
        metadata.append({
            "column": col,
            "type": dtype,
            "sample": val,
            "description": f"Dữ liệu của cột {col}"
        })

with open('data_processed_t4_metadata.json', 'w', encoding='utf-8') as f:
    json.dump({"dataset_name": "data_processed_t4", "description": "Metadata automatically generated", "columns": metadata}, f, indent=4, ensure_ascii=False)
