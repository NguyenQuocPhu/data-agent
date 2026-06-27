import pandas as pd
import numpy as np

print("Reading original dataset data_processed_t4.csv...")
df = pd.read_csv('data_processed_t4.csv')

print("Sampling 10,000 rows...")
df = df.sample(n=10000, random_state=42).reset_index(drop=True)

n = len(df)
idx_issue = df.index[:int(n*0.3)]       # 30% Sự cố kỹ thuật
idx_complain = df.index[int(n*0.3):int(n*0.5)] # 20% Bất mãn
idx_silent = df.index[int(n*0.5):int(n*0.8)]   # 30% Im lặng
idx_normal = df.index[int(n*0.8):]             # 20% Bình thường

# Zero out ALL numerical noise to force perfect clustering on 6 target columns
target_cols = [
    'cl_total_6m', 'complaint_total_6m', 'call_total_6m', 
    'escalating_cl', 'no_call_all_period', 'no_complaint_all_period'
]

for col in df.columns:
    if col not in target_cols and pd.api.types.is_numeric_dtype(df[col]):
        df[col] = 0

# Baseline for target columns
if 'cl_total_6m' in df.columns: df['cl_total_6m'] = 0
if 'complaint_total_6m' in df.columns: df['complaint_total_6m'] = 0
if 'call_total_6m' in df.columns: df['call_total_6m'] = 0
if 'escalating_cl' in df.columns: df['escalating_cl'] = 0.0
if 'no_call_all_period' in df.columns: df['no_call_all_period'] = 0.0
if 'no_complaint_all_period' in df.columns: df['no_complaint_all_period'] = 0.0

# 1. Sự cố kỹ thuật (Technical Issues)
if 'cl_total_6m' in df.columns: df.loc[idx_issue, 'cl_total_6m'] = 10
if 'escalating_cl' in df.columns: df.loc[idx_issue, 'escalating_cl'] = 1.0

# 2. Bất mãn (Complaints)
if 'complaint_total_6m' in df.columns: df.loc[idx_complain, 'complaint_total_6m'] = 8
if 'call_total_6m' in df.columns: df.loc[idx_complain, 'call_total_6m'] = 15

# 3. Im lặng (Silent)
if 'no_call_all_period' in df.columns: df.loc[idx_silent, 'no_call_all_period'] = 1.0
if 'no_complaint_all_period' in df.columns: df.loc[idx_silent, 'no_complaint_all_period'] = 1.0

output_path = 'data_demo_golden.csv'
print(f"Saving to {output_path}...")
df.to_csv(output_path, index=False)
print("Done! Golden Demo Dataset without noise has been created.")
