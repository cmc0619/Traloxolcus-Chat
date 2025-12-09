"""Entry point for running the processing-station FastAPI app."""

from __future__ import annotations

import uvicorn

from .app import app


def run() -> None:
    uvicorn.run(app, host="0.0.0.0", port=4220)


if __name__ == "__main__":
    run()
