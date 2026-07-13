from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from triadic_dgm.services.convergence_feed import build_feed_items, render_markdown

from ..services.convergence_loop import convergence_loop

router = APIRouter()


@router.get("/convergence/personas")
async def list_latest_personas(limit: int = Query(20, ge=1, le=100)):
    return {"personas": build_feed_items(convergence_loop.db_path, limit=limit)}


@router.get("/convergence/status")
async def loop_status():
    return convergence_loop.status()


@router.get("/convergence/markdown")
async def get_markdown_feed(limit: int = Query(20, ge=1, le=100)):
    """The persisted markdown file summarizing the latest persona feed — same content the
    background loop writes to workspace/convergence/generated/ after every run, regenerated
    on-demand here so it's never stale even between runs."""
    md = render_markdown(build_feed_items(convergence_loop.db_path, limit=limit))
    return PlainTextResponse(md, media_type="text/markdown")
