import uvicorn

from .config import settings


if __name__ == "__main__":
    uvicorn.run(
        "soccer_rig.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
