import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers.workspace import router as workspace_router
from api.routers.chat import router as chat_router
from api.routers.export import router as export_router
from api.routers.convergence import router as convergence_router
from api.services.convergence_loop import convergence_loop
from triadic_dgm.services.report_generator import set_profile_resolver


# The convergence loop runs the persona pipeline continuously in the background against a
# fixed dataset, for cross-run convergence monitoring. It is a research instrument, not
# part of the user-facing chat product: it holds its own kernel and calls the LLM without
# pause. Off by default so a normal deployment only serves chat; set
# CONVERGENCE_LOOP_ENABLED=1 to run it. The /convergence/* endpoints keep working either
# way — they read the stored run history, which simply stops growing while it is off.
CONVERGENCE_LOOP_ENABLED = os.getenv("CONVERGENCE_LOOP_ENABLED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)


# Where chat's DatasetProfile cache lives. Deliberately NOT the convergence loop's
# directory: that loop emits its frozen derived-feature definitions into its task prompt so
# the sandbox materialises those columns, and the chat path has no equivalent — the user
# writes their own query. Sharing one cache would hand chat a feature list naming columns
# that never get created.
CHAT_PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "chat", "profiles")


def _resolve_chat_profile():
    """Build/load the DatasetProfile for the chat workspace's active dataset.

    Registered on ReportGenerator so a persona report rendered from a chat session gets
    the same treatment the convergence loop gets: readable persona names from inferred
    column labels, and telco fields neutralised when the data has no churn columns.

    Derived-feature selection is off here — see CHAT_PROFILES_DIR.
    """
    from api.services import profile_provider, workspace as workspace_service
    from api.services.convergence_loop import _load_base_config

    return profile_provider.load_profile(
        str(workspace_service.resolve_workspace_root("default")),
        _load_base_config(),
        CHAT_PROFILES_DIR,
        with_derived=False,
    )


# Registered at import, not in lifespan: lifespan only runs under uvicorn, so any other
# entry point (a worker importing the app, a script, a test) would silently render reports
# with no profile — the exact "generic path never ran" failure this wiring exists to fix.
set_profile_resolver(_resolve_chat_profile)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if CONVERGENCE_LOOP_ENABLED:
        convergence_loop.start()
    else:
        print("[convergence] background loop disabled (CONVERGENCE_LOOP_ENABLED=1 to enable)")
    yield
    if CONVERGENCE_LOOP_ENABLED:
        convergence_loop.stop()


app = FastAPI(title="LAMBDA Unified Backend (DeepAnalyze Compatible)", lifespan=lifespan)

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
app.include_router(convergence_router)

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
