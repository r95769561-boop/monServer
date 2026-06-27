"""
Microcontroller Overlay Network (MON) - Control Server
Revision 1 - FastAPI Backend
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
import uvicorn

from auth import router as auth_router
from devices import router as device_router
from websocket_manager import router as ws_router, manager
from signaling import router as signaling_router
from relay import router as relay_router

app = FastAPI(
    title="MON Control Server",
    description="Microcontroller Overlay Network - Revision 2 (P2P + E2E Encryption)",
    version="2.0.0"
)

# CORS_ORIGINS: comma-separated list, e.g. "https://your-dashboard.onrender.com,http://localhost:5173"
# NOTE: allow_origins=["*"] together with allow_credentials=True is invalid
# per the CORS spec — browsers will reject the response outright, which
# shows up as a network/CORS error on the frontend (and can look like a
# 500 if your client swallows it). Set CORS_ORIGINS in Render's env vars.
_origins_env = os.getenv("CORS_ORIGINS", "")
allow_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or ["*"]
allow_credentials = allow_origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,      prefix="/auth",      tags=["Authentication"])
app.include_router(device_router,    prefix="/devices",   tags=["Devices"])
app.include_router(ws_router,        prefix="/ws",         tags=["WebSocket"])
app.include_router(signaling_router, prefix="/signaling",  tags=["Signaling (Rev2)"])
app.include_router(relay_router,     prefix="",            tags=["Relay Fallback (Rev2)"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "MON Control Server", "revision": 2}


# Resolve mobile_app directory safely for local dev & Render deployment
_base_dir = os.path.dirname(__file__)
_local_app_dir = os.path.join(_base_dir, "mobile_app")
_parent_app_dir = os.path.abspath(os.path.join(_base_dir, "..", "mobile_app"))

if os.path.exists(_local_app_dir):
    app_dir = _local_app_dir
elif os.path.exists(_parent_app_dir):
    app_dir = _parent_app_dir
else:
    # Safe fallback: create a dummy directory to prevent starlette crash
    app_dir = _local_app_dir
    os.makedirs(app_dir, exist_ok=True)

app.mount("/app", StaticFiles(directory=app_dir, html=True), name="app")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
