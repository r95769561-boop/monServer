"""
MON - Device & Resource Management Routes
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Any

from models import Device, Resource, get_db
from auth import get_current_user, get_current_device

router = APIRouter()


# ─────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────

class ResourceSchema(BaseModel):
    id:   str
    type: str                  # switch | value | control
    unit: str | None = None
    min:  float | None = None
    max:  float | None = None


class DescribePayload(BaseModel):
    device:    str
    resources: list[ResourceSchema]


class ResourceValueUpdate(BaseModel):
    resource_id: str
    value:       Any


# ─────────────────────────────────────────
# Device Routes (authenticated as USER)
# ─────────────────────────────────────────

@router.get("/")
def list_devices(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Return all devices owned by the current user."""
    devices = db.query(Device).filter(Device.owner_id == user.id).all()
    result = []
    for d in devices:
        result.append({
            "device_id":   d.device_id,
            "device_name": d.device_name,
            "is_online":   d.is_online,
            "last_seen":   d.last_seen,
            "resources":   [_resource_to_dict(r) for r in d.resources],
        })
    return result


@router.get("/{device_id}")
def get_device(device_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Return a single device with its resources."""
    device = _get_owned_device(device_id, user.id, db)
    return {
        "device_id":   device.device_id,
        "device_name": device.device_name,
        "is_online":   device.is_online,
        "last_seen":   device.last_seen,
        "resources":   [_resource_to_dict(r) for r in device.resources],
    }


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove a device from the user's account."""
    device = _get_owned_device(device_id, user.id, db)
    db.delete(device)
    db.commit()


# ─────────────────────────────────────────
# Device Routes (authenticated as DEVICE)
# ─────────────────────────────────────────

@router.post("/auth/ping")
def device_ping(device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """
    ESP32 calls this after boot to confirm token validity.
    Marks the device online.
    """
    device.is_online  = True
    device.last_seen  = datetime.utcnow()
    db.commit()
    return {"success": True, "device_id": device.device_id, "device_name": device.device_name}


@router.post("/describe")
def describe(
    payload: DescribePayload,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db)
):
    """
    ESP32 registers its resource model.
    Overwrites previous resource list.
    """
    # Clear old resources
    db.query(Resource).filter(Resource.device_id == device.id).delete()

    for r in payload.resources:
        resource = Resource(
            resource_id=r.id,
            device_id=device.id,
            type=r.type,
            unit=r.unit,
            min_val=r.min,
            max_val=r.max,
        )
        db.add(resource)

    device.device_name = payload.device or device.device_name
    device.last_seen   = datetime.utcnow()
    db.commit()
    return {"registered": len(payload.resources)}


@router.post("/heartbeat")
def heartbeat(device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """ESP32 calls this every 30 seconds to stay marked online."""
    device.is_online = True
    device.last_seen = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/resource-update")
def resource_update(
    update: ResourceValueUpdate,
    device: Device = Depends(get_current_device),
    db: Session = Depends(get_db)
):
    """ESP32 pushes a new resource value to the server."""
    resource = db.query(Resource).filter(
        Resource.device_id  == device.id,
        Resource.resource_id == update.resource_id
    ).first()

    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    resource.last_value = update.value
    resource.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def _get_owned_device(device_id: str, user_id: str, db: Session) -> Device:
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not your device")
    return device


def _resource_to_dict(r: Resource) -> dict:
    return {
        "id":         r.resource_id,
        "type":       r.type,
        "unit":       r.unit,
        "min":        r.min_val,
        "max":        r.max_val,
        "last_value": r.last_value,
        "updated_at": r.updated_at,
    }
