"""python -m stmtai.api [--host 127.0.0.1] [--port 8000]"""

import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Bank Statement Intelligence API.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args()
    uvicorn.run("stmtai.api.app:create_app", factory=True, host=a.host, port=a.port, reload=a.reload)


if __name__ == "__main__":
    main()
