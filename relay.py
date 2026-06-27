"""
MON Revision 2 — Relay Fallback Module
======================================

Provides a WebSocket-based relay route for end-to-end encrypted message forwarding
when P2P direct connection fails. Relays opaque encrypted payloads between the browser
and the ESP32 device.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session
from models import get_db, Device, SignalingSession, SessionLocal
from auth import decode_jwt
from typing import Dict
import json
import asyncio

router = APIRouter()

class RelayManager:
    def __init__(self):
        # Maps session_id -> { "browser": WebSocket, "device": WebSocket }
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, session_id: str, client_type: str, websocket: WebSocket):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = {}
        self.active_connections[session_id][client_type] = websocket

    def disconnect(self, session_id: str, client_type: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].pop(client_type, None)
            if not self.active_connections[session_id]:
                self.active_connections.pop(session_id, None)

    async def send_to_peer(self, session_id: str, sender_type: str, message: str, db: Session) -> bool:
        peer_type = "device" if sender_type == "browser" else "browser"
        
        # 1. Try to send to the peer on the dedicated relay WebSocket first
        if session_id in self.active_connections:
            peer_ws = self.active_connections[session_id].get(peer_type)
            if peer_ws:
                try:
                    await peer_ws.send_text(message)
                    return True
                except Exception:
                    pass

        # 2. Bridge to the primary control WebSockets if not connected to the relay socket
        if peer_type == "device":
            session = db.query(SignalingSession).filter(SignalingSession.id == session_id).first()
            if session:
                device = db.query(Device).filter(Device.id == session.device_id).first()
                if device:
                    from websocket_manager import manager as ws_manager
                    # Wrap message in the standard websocket frame format
                    payload = {
                        "event": "relay_message",
                        "session_id": session_id,
                        "payload": message  # Opaque base64-encoded E2E encrypted string
                    }
                    delivered = await ws_manager.send_to_device(device.device_id, payload)
                    return delivered

        elif peer_type == "browser":
            session = db.query(SignalingSession).filter(SignalingSession.id == session_id).first()
            if session:
                from websocket_manager import manager as ws_manager
                payload = {
                    "event": "relay_message",
                    "session_id": session_id,
                    "payload": message
                }
                await ws_manager.send_to_browser(session.requested_by, payload)
                return True

        return False


relay_manager = RelayManager()


@router.websocket("/relay/{session_id}")
async def websocket_relay(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...)
):
    db = SessionLocal()
    session = db.query(SignalingSession).filter(SignalingSession.id == session_id).first()
    
    if not session:
        await websocket.close(code=4004)
        db.close()
        return

    # Authenticate the connection
    role = None

    # Check if the token is a user JWT (for the browser client)
    try:
        payload = decode_jwt(token)
        user_id = payload.get("sub")
        if user_id and session.requested_by == user_id:
            role = "browser"
    except Exception:
        pass

    # Check if the token is a device token (for the ESP32 client)
    if not role:
        device = db.query(Device).filter(Device.id == session.device_id).first()
        if device and device.device_token == token:
            role = "device"

    if not role:
        await websocket.close(code=4001)
        db.close()
        return

    await relay_manager.connect(session_id, role, websocket)
    
    try:
        while True:
            # Receive incoming E2E encrypted message
            data = await websocket.receive_text()
            # Forward it to the peer
            await relay_manager.send_to_peer(session_id, role, data, db)
    except WebSocketDisconnect:
        relay_manager.disconnect(session_id, role)
    finally:
        db.close()
