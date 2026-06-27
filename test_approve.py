import requests
import json
import uuid

session_id = "test_session_" + str(uuid.uuid4())
url = "http://localhost:18000/chat/completions" # use direct backend port
headers = {"Content-Type": "application/json"}
data = {
    "model": "lambda-triadic-agent",
    "messages": [
        {"role": "user", "content": "hello world plan"}
    ],
    "session_id": session_id
}

print(f"== SENDING NEW TASK to {session_id} ==")
response = requests.post(url, headers=headers, json=data, stream=True)
for line in response.iter_lines():
    pass

print("\n\n== SENDING APPROVAL ==")
data["messages"].append({"role": "assistant", "content": "plan"})
data["messages"].append({"role": "user", "content": "Approve"})

response2 = requests.post(url, headers=headers, json=data, stream=True)
for line in response2.iter_lines():
    if line:
        print(line.decode("utf-8"))
