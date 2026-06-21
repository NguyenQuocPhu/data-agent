import pandas as pd
import os

file_path = r'd:\kh4ng\Data_agent\data_2025.csv'
backup_path = r'd:\kh4ng\Data_agent\data_2025_backup.csv'

print(f"Loading {file_path}...")
df = pd.read_csv(file_path)

# Tạo backup cho chắc chắn
df.to_csv(backup_path, index=False)
print(f"Created backup at {backup_path}")

original_cols = len(df.columns)
# Lọc các cột có hậu tố T1, T2, T3, T4 (cả chữ hoa và chữ thường)
suffixes = ('T1', 'T2', 'T3', 'T4', 't1', 't2', 't3', 't4')
cols_to_drop = [col for col in df.columns if str(col).endswith(suffixes)]

print(f"Found {len(cols_to_drop)} columns ending with T1, T2, T3, T4.")
print(f"Columns to drop: {cols_to_drop[:10]} ...")

df = df.drop(columns=cols_to_drop)

# Ghi đè lại file
df.to_csv(file_path, index=False)
print(f"Saved {file_path}. Original columns: {original_cols}, New columns: {len(df.columns)}")
