"""One process, one port: the API under /api and the built review UI at /.

Used by the Docker image (``STMTAI_WEB_DIR=/app/web``). In development the UI runs on Vite's dev server and
proxies /api to the API, so nothing here is needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .app import Settings, create_app


def create_site(settings: Optional[Settings] = None, web_dir: Optional[Path] = None) -> FastAPI:
    web = Path(web_dir or os.environ.get("STMTAI_WEB_DIR", ""))
    if not (web / "index.html").is_file():
        raise RuntimeError(f"STMTAI_WEB_DIR must be a built UI folder containing index.html (got {str(web)!r}). "
                           "Build it with: cd web && npm ci && npm run build")
    site = FastAPI(title="Bank Statement Intelligence", docs_url=None, redoc_url=None, openapi_url=None)
    api = create_app(settings)
    site.mount("/api", api)
    site.mount("/", StaticFiles(directory=web, html=True), name="ui")
    site.state.api = api
    return site
