from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .routes import router

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="key-router git tool", docs_url=None, redoc_url=None)
    required_token = os.environ.get("KEY_ROUTER_TOOL_TOKEN", "")

    @app.middleware("http")
    async def tool_token(request: Request, call_next):
        if required_token and request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-tool-token") or request.query_params.get("token", "")
            if supplied != required_token:
                return JSONResponse(status_code=401, content={"detail": "Invalid tool token"})
        return await call_next(request)

    app.include_router(router)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
    else:
        @app.get("/")
        def root():
            return {"message": "Git tool UI is not built. Run npm install && npm run build in tools/git-tool/webui."}

    return app
