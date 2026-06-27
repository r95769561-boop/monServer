"""
MON - WebSocket Broker
Server brokers commands between browser dashboard and ESP32 devices.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict
import json
import asyncio
from datetime import datetime

from models import Device, SessionLocal
from auth import decode_jwt

router = APIRouter()


class ConnectionManager:
    """
    Tracks two types of connections:
      - device connections  : keyed by device_id
      - browser connections : keyed by user_id (multiple tabs allowed)
    """

    def __init__(self):
        self.devices:  Dict[str, WebSocket] = {}         # device_id -> ws
        self.browsers: Dict[str, list[WebSocket]] = {}   # user_id   -> [ws, ...]

    # ── Connect / Disconnect ──────────────────────────

    async def connect_device(self, device_id: str, ws: WebSocket):
        await ws.accept()
        self.devices[device_id] = ws
        self._mark_online(device_id, True)
        await self.broadcast_to_user_by_device(device_id, {
            "event": "device_online",
            "device_id": device_id,
            "timestamp": datetime.utcnow().isoformat()
        })

    def disconnect_device(self, device_id: str):
        self.devices.pop(device_id, None)
        self._mark_online(device_id, False)

    async def connect_browser(self, user_id: str, ws: WebSocket):
        await ws.accept()
        if user_id not in self.browsers:
            self.browsers[user_id] = []
        self.browsers[user_id].append(ws)

    def disconnect_browser(self, user_id: str, ws: WebSocket):
        if user_id in self.browsers:
            self.browsers[user_id] = [w for w in self.browsers[user_id] if w != ws]

    # ── Sending ───────────────────────────────────────

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        ws = self.devices.get(device_id)
        if ws:
            await ws.send_text(json.dumps(message))
            return True
        return False

    async def send_to_browser(self, user_id: str, message: dict):
        for ws in self.browsers.get(user_id, []):
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                pass

    async def broadcast_to_user_by_device(self, device_id: str, message: dict):
        db     = SessionLocal()
        device = db.query(Device).filter(Device.device_id == device_id).first()
        if device:
            await self.send_to_browser(device.owner_id, message)
        db.close()

    # ── Helpers ───────────────────────────────────────

    def _mark_online(self, device_id: str, online: bool):
        db     = SessionLocal()
        device = db.query(Device).filter(Device.device_id == device_id).first()
        if device:
            device.is_online = online
            device.last_seen = datetime.utcnow()
            db.commit()
        db.close()

    def get_online_devices(self) -> list:
        return list(self.devices.keys())


manager = ConnectionManager()


# ─────────────────────────────────────────
# WebSocket Endpoints
# ─────────────────────────────────────────

@router.websocket("/device/{device_id}")
async def device_ws(websocket: WebSocket, device_id: str, token: str = Query(...)):
    """
    ESP32 connects here with its device_token.
    Receives commands, sends telemetry/events.
    """
    db     = SessionLocal()
    device = db.query(Device).filter(Device.device_token == token).first()
    db.close()

    if not device or device.device_id != device_id:
        await websocket.close(code=4001)
        return

    await manager.connect_device(device_id, websocket)
    try:
        while True:
            raw     = await websocket.receive_text()
            message = json.loads(raw)
            message["_from"]     = device_id
            message["timestamp"] = datetime.utcnow().isoformat()

            # Intercept E2E encrypted relay messages and route them appropriately
            if message.get("event") == "relay_message":
                session_id = message.get("session_id")
                payload_data = message.get("payload")
                if session_id and payload_data:
                    from relay import relay_manager
                    db = SessionLocal()
                    delivered = await relay_manager.send_to_peer(session_id, "device", payload_data, db)
                    db.close()
                    if delivered:
                        continue

            # Forward telemetry/events to the owning browser
            await manager.broadcast_to_user_by_device(device_id, message)

            # Update resource value in DB if it's a value report
            if message.get("event") == "value_report":
                _update_resource_value(device_id, message.get("target"), message.get("value"))

    except WebSocketDisconnect:
        manager.disconnect_device(device_id)


@router.websocket("/browser")
async def browser_ws(websocket: WebSocket, token: str = Query(...)):
    """
    Dashboard browser connects here with user JWT.
    Sends commands to devices, receives events.
    """
    try:
        payload = decode_jwt(token)
        user_id = payload["sub"]
    except Exception:
        await websocket.close(code=4001)
        return

    await manager.connect_browser(user_id, websocket)
    try:
        while True:
            raw     = await websocket.receive_text()
            message = json.loads(raw)

            target_device = message.get("device_id")
            if not target_device:
                continue

            # Verify ownership
            db     = SessionLocal()
            device = db.query(Device).filter(
                Device.device_id == target_device,
                Device.owner_id  == user_id
            ).first()
            db.close()

            if not device:
                await websocket.send_text(json.dumps({
                    "error": "device_not_found_or_not_owned"
                }))
                continue

            delivered = await manager.send_to_device(target_device, message)
            if not delivered:
                await websocket.send_text(json.dumps({
                    "error": "device_offline",
                    "device_id": target_device
                }))

    except WebSocketDisconnect:
        manager.disconnect_browser(user_id, websocket)


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _update_resource_value(device_id: str, resource_id: str, value):
    if not resource_id:
        return
    from models import Resource
    db     = SessionLocal()
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device:
        resource = db.query(Resource).filter(
            Resource.device_id   == device.id,
            Resource.resource_id == resource_id
        ).first()
        if resource:
            resource.last_value = value
            resource.updated_at = datetime.utcnow()
            db.commit()
    db.close()
