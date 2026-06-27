import requests
import json

url = "http://localhost:18000/api/chat/completions"
headers = {"Content-Type": "application/json"}
data = {
    "model": "lambda-triadic-agent",
    "messages": [
        {"role": "user", "content": "Liệt kê 3 bước phân tích dữ liệu cơ bản"}
    ],
    "session_id": "test_hitl_session"
}

print("== SENDING NEW TASK ==")
response = requests.post(url, headers=headers, json=data, stream=True)
for line in response.iter_lines():
    if line:
        print(line.decode("utf-8"))

print("\n\n== SENDING APPROVAL ==")
data["messages"].append({"role": "assistant", "content": "Plan shown here."})
data["messages"].append({"role": "user", "content": "Approve"})

response2 = requests.post(url, headers=headers, json=data, stream=True)
for line in response2.iter_lines():
    if line:
        print(line.decode("utf-8"))
