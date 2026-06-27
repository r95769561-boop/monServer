"""
MON - Authentication Module
Handles: user creation, login, JWT tokens, device token issuance
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import secrets
import os

from models import User, Device, get_db

router  = APIRouter()
bearer  = HTTPBearer()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.getenv("MON_SECRET_KEY")
if not SECRET_KEY:
    if os.getenv("RENDER"):  # Render sets this env var automatically on every service
        raise RuntimeError(
            "MON_SECRET_KEY is not set. Add it in the Render dashboard "
            "(Environment tab) on every service that imports auth.py — "
            "a missing/mismatched secret across workers causes JWTs minted "
            "by one process to fail to decode on another."
        )
    SECRET_KEY = "mon-dev-secret-change-in-production"  # local dev only

ALGORITHM   = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 30   # 30 days


# ─────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    email: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str


class DeviceProvision(BaseModel):
    username:  str
    password:  str
    device_id: str
    device_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      str


class DeviceTokenResponse(BaseModel):
    device_token: str
    device_id:    str


# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_jwt(data: dict, expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire  = datetime.utcnow() + (expires_delta or timedelta(hours=TOKEN_EXPIRE_HOURS))
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


def generate_device_token() -> str:
    return secrets.token_urlsafe(32)


# ─────────────────────────────────────────
# Dependencies
# ─────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
) -> User:
    payload = decode_jwt(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def get_current_device(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
) -> Device:
    token  = credentials.credentials
    device = db.query(Device).filter(Device.device_token == token).first()
    if not device:
        raise HTTPException(status_code=401, detail="Invalid device token")
    return device


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────

@router.post("/register", status_code=201)
def register(body: UserCreate, db: Session = Depends(get_db)):
    """Create a new user account."""
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "username": user.username}


@router.post("/login", response_model=TokenResponse)
def login(body: UserLogin, db: Session = Depends(get_db)):
    """Authenticate user and return JWT."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_jwt({"sub": user.id, "username": user.username})
    return TokenResponse(access_token=token, user_id=user.id)


@router.post("/provision-device", response_model=DeviceTokenResponse)
def provision_device(body: DeviceProvision, db: Session = Depends(get_db)):
    """
    Called by ESP32 during first-boot provisioning.
    Validates user credentials, issues a device token.
    """
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid user credentials")

    # Check for existing device
    existing = db.query(Device).filter(Device.device_id == body.device_id).first()
    if existing:
        if existing.owner_id != user.id:
            raise HTTPException(status_code=409, detail="Device already claimed by another user")
        # Re-issue token
        existing.device_token = generate_device_token()
        db.commit()
        return DeviceTokenResponse(device_token=existing.device_token, device_id=body.device_id)

    device = Device(
        device_id=body.device_id,
        device_name=body.device_name,
        device_token=generate_device_token(),
        owner_id=user.id,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return DeviceTokenResponse(device_token=device.device_token, device_id=body.device_id)


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Return current user info."""
    return {"user_id": current_user.id, "username": current_user.username}
