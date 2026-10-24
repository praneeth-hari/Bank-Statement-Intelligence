"""python -m stmtai.api [--host 127.0.0.1] [--port 8000]

With STMTAI_WEB_DIR pointing at the built UI (web/dist), the UI is served from the same port, API under /api.
"""

import argparse
import os

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Bank Statement Intelligence API.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args()
    target = "stmtai.api.site:create_site" if os.environ.get("STMTAI_WEB_DIR") else "stmtai.api.app:create_app"
    uvicorn.run(target, factory=True, host=a.host, port=a.port, reload=a.reload)


if __name__ == "__main__":
    main()
