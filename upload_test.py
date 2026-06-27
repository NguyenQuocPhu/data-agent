import requests
import json

url = "http://localhost:18000/workspace/upload-to?dir=&session_id=session_1782112580462_hjswfl0dj"
files = {'files': ('data_RM6T_T11_2025.csv', open('data_RM6T_T11_2025.csv', 'rb'), 'text/csv')}

response = requests.post(url, files=files)
print(response.status_code)
print(response.text)
