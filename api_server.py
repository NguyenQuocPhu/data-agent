import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers.workspace import router as workspace_router
from api.routers.chat import router as chat_router
from api.routers.export import router as export_router

app = FastAPI(title="LAMBDA Unified Backend (DeepAnalyze Compatible)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include SOLID Routers
app.include_router(workspace_router)
app.include_router(chat_router)
app.include_router(export_router)

from fastapi.responses import FileResponse
from fastapi import Query
import os

@app.get("/file")
async def get_file(path: str = Query(...)):
    # Handle WSL paths for Windows server only if running on Windows
    if os.name == 'nt':
        if path.startswith("/mnt/d/"):
            path = "D:/" + path[7:]
        elif path.startswith("/mnt/c/"):
            path = "C:/" + path[7:]
            
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": f"File not found: {path}"}

@app.get("/v1/models")
async def get_models():
    import time
    return {
        "object": "list",
        "data": [
            {
                "id": "lambda-triadic-agent",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "organization-owner"
            }
        ]
    }

if __name__ == "__main__":
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
