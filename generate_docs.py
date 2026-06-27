import json
from api_server import app
import os

openapi_schema = app.openapi()
with open("openapi.json", "w", encoding="utf-8") as f:
    json.dump(openapi_schema, f, ensure_ascii=False, indent=2)

print("OpenAPI JSON exported.")
