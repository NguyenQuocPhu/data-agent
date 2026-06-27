import pandas as pd
df = pd.read_csv('/home/anlnm/anlnm/data-agent/data-agent/workspace/session_1782112580462_hjswfl0dj/Files/801d34cb_data_RM6T_T11_2025.csv')
print(f"Total rows: {len(df)}")
cols = df.columns
print("Columns:", cols)
print("\nUnique values in TOTAL_COMPLAINT_T4:", df['TOTAL_COMPLAINT_T4'].value_counts().head(5).to_dict() if 'TOTAL_COMPLAINT_T4' in cols else "None")
print("\nUnique values in TOTAL_CL_T4:", df['TOTAL_CL_T4'].value_counts().head(5).to_dict() if 'TOTAL_CL_T4' in cols else "None")
print("\nBasic Stats of cuoc_hang_thang:", df['cuoc_hang_thang'].describe().to_dict() if 'cuoc_hang_thang' in cols else "None")
