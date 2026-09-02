"""Startskript fuer die Entwicklung.

Produktion:  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
(Ein Worker! Der Live-Zustand liegt im Prozessspeicher.)
"""
from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("TW_HOST", "0.0.0.0"),
        port=int(os.environ.get("TW_PORT", 8000)),
        reload=os.environ.get("TW_RELOAD", "1") == "1",
        ws_ping_interval=20,
        ws_ping_timeout=20,
        log_level="info",
    )
