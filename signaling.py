"""
MON Revision 2 — Signaling Module
==================================

Responsibilities (per the Phase 13-17 design):
  - Browser asks "I want to talk to device X" -> server returns device's
    long-term public key + tells device to prepare a session.
  - Both sides report their STUN-observed (public_ip, public_port) candidate.
  - Once both candidates are known, server tells both peers "send packets
    now" to begin UDP hole punching.
  - Server tracks session state but NEVER sees the derived session key or
    any decrypted payload — it only relays opaque key material and IP/port
    candidates, exactly like a SIP/WebRTC signaling server.

This module does NOT do the actual UDP hole punching or encryption — that
happens directly between browser and ESP32 (see dashboard/index.html and
esp32/P2PClient.h). This module only brokers the handshake metadata over
the existing WebSocket connections from websocket_manager.py.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
import asyncio

from models import Device, SignalingSession, get_db
from auth import get_current_user, get_current_device

router = APIRouter()


# ─────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────

class RequestSession(BaseModel):
    target_device_id: str
    initiator_pubkey: str    # base64 X25519 ephemeral public key


class SessionResponse(BaseModel):
    session_id:    str
    device_pubkey: str | None = None
    state:         str


class CandidateReport(BaseModel):
    session_id: str
    ip:         str
    port:       int


class DevicePubkeyRegister(BaseModel):
    public_key: str   # base64 X25519 long-term public key


# ─────────────────────────────────────────
# Browser-side: request a P2P session
# ─────────────────────────────────────────

@router.post("/d2d/request", response_model=SessionResponse)
async def request_session(
    body: RequestSession,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Phase 13 — Browser asks server to begin a P2P session with `device_id`.
    Server validates ownership, creates a SignalingSession row, and (in a
    full implementation) pushes a "session_offer" event down the device's
    WebSocket so the ESP32 can generate its ephemeral keypair and candidate.
    """
    device = db.query(Device).filter(Device.device_id == body.target_device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not your device")
    if not device.is_online:
        raise HTTPException(status_code=409, detail="Device is offline")

    session = SignalingSession(
        device_id=device.id,
        requested_by=user.id,
        browser_pubkey=body.initiator_pubkey,
        state="pending",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    # Notify the device over its existing WebSocket connection (best-effort;
    # actual delivery handled by websocket_manager's connection registry).
    from websocket_manager import manager
    asyncio.create_task(manager.send_to_device(device.device_id, {
        "event":      "session_offer",
        "session_id": session.id,
        "browser_pubkey": body.initiator_pubkey,
    }))

    return SessionResponse(session_id=session.id, state=session.state)


@router.get("/d2d/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Poll for session state — used by the browser while waiting for the
    device to respond with its ephemeral public key and ICE-style candidate."""
    session = db.query(SignalingSession).filter(SignalingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.requested_by != user.id:
        raise HTTPException(status_code=403, detail="Not your session")

    return SessionResponse(
        session_id=session.id,
        device_pubkey=session.device_pubkey,
        state=session.state,
    )


# ─────────────────────────────────────────
# Device-side: respond to a session offer
# ─────────────────────────────────────────

@router.post("/{session_id}/respond")
def respond_session(
    session_id: str,
    body: dict,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db)
):
    """
    ESP32 calls this after generating its ephemeral X25519 keypair in
    response to a session_offer event received over WebSocket.
    body: { "device_pubkey": "<base64>" }
    """
    session = db.query(SignalingSession).filter(SignalingSession.id == session_id).first()
    if not session or session.device_id != device.id:
        raise HTTPException(status_code=404, detail="Session not found for this device")

    session.device_pubkey = body.get("device_pubkey")
    session.state         = "exchanging"
    session.updated_at    = datetime.utcnow()
    db.commit()
    return {"ok": True, "state": session.state}


# ─────────────────────────────────────────
# Both sides: report STUN candidate
# ─────────────────────────────────────────

@router.post("/candidate/browser")
async def report_browser_candidate(
    body: CandidateReport,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Phase 15 — Browser reports its STUN-observed public IP:port."""
    session = _get_session_for_user(body.session_id, user.id, db)
    session.browser_candidate = f"{body.ip}:{body.port}"
    session.updated_at = datetime.utcnow()
    db.commit()
    _maybe_start_punching(session, db)
    return {"ok": True}


@router.post("/candidate/device")
async def report_device_candidate(
    body: CandidateReport,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db)
):
    """Phase 15 — ESP32 reports its STUN-observed public IP:port."""
    session = db.query(SignalingSession).filter(
        SignalingSession.id == body.session_id,
        SignalingSession.device_id == device.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.device_candidate = f"{body.ip}:{body.port}"
    session.updated_at = datetime.utcnow()
    db.commit()
    _maybe_start_punching(session, db)
    return {"ok": True}


# ─────────────────────────────────────────
# Relay fallback negotiation
# ─────────────────────────────────────────

@router.post("/{session_id}/fallback-relay")
def fallback_to_relay(
    session_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Phase 19 — Called by the browser when hole punching fails (no direct
    packets received within a timeout). Switches the session to relay mode;
    actual byte relaying happens over the relay WebSocket endpoint in
    relay.py, which only ever forwards opaque encrypted blobs.
    """
    session = _get_session_for_user(session_id, user.id, db)
    session.state     = "relay_fallback"
    session.transport  = "relay"
    session.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "relay_path": f"/relay/{session_id}"}


# ─────────────────────────────────────────
# Device long-term public key registration
# ─────────────────────────────────────────

@router.post("/register-pubkey")
def register_pubkey(
    body: DevicePubkeyRegister,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db)
):
    """
    ESP32 calls this once (typically right after provisioning) to publish
    its long-term X25519 public key. The private key never leaves the device.
    """
    device.public_key = body.public_key
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _get_session_for_user(session_id: str, user_id: str, db: Session) -> SignalingSession:
    session = db.query(SignalingSession).filter(SignalingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.requested_by != user_id:
        raise HTTPException(status_code=403, detail="Not your session")
    return session


def _maybe_start_punching(session: SignalingSession, db: Session):
    """Once both candidates are known, flip state to 'punching' and notify
    both sides to start sending UDP packets (Phase 16)."""
    if session.browser_candidate and session.device_candidate and session.state == "exchanging":
        session.state = "punching"
        db.commit()

        from websocket_manager import manager
        device = db.query(Device).filter(Device.id == session.device_id).first()
        if device:
            asyncio.create_task(manager.send_to_device(device.device_id, {
                "event":            "start_punching",
                "session_id":       session.id,
                "peer_candidate":   session.browser_candidate,
            }))
            asyncio.create_task(manager.send_to_browser(session.requested_by, {
                "event":            "start_punching",
                "session_id":       session.id,
                "peer_candidate":   session.device_candidate,
            }))
