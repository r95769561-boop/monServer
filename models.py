"""
MON - Database Models (SQLAlchemy)
"""

from sqlalchemy import create_engine, Column, String, Boolean, Float, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import uuid

# ─────────────────────────────────────────
# Database URL
# ─────────────────────────────────────────
# On Render, set DATABASE_URL to the Internal Database URL of a Postgres
# instance (Render dashboard -> your Postgres -> "Internal Database URL").
# SQLite is kept ONLY as a local-dev fallback — Render's filesystem is
# ephemeral and wipes the .db file on every deploy/restart, and if you ever
# run >1 worker each process gets its own separate SQLite file, which is
# why auth was 500ing (user created on one worker, login hits another).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mon.db")

# Render (like Heroku) sometimes hands out URLs starting with "postgres://"
# which SQLAlchemy's psycopg dialect rejects — it wants "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency: yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_id():
    return str(uuid.uuid4())


# ─────────────────────────────────────────
# Models
# ─────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id            = Column(String, primary_key=True, default=generate_id)
    username      = Column(String, unique=True, nullable=False, index=True)
    email         = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    is_active     = Column(Boolean, default=True)

    devices = relationship("Device", back_populates="owner")


class Device(Base):
    __tablename__ = "devices"

    id           = Column(String, primary_key=True, default=generate_id)
    device_id    = Column(String, unique=True, nullable=False, index=True)   # esp32_abc123
    device_name  = Column(String, nullable=False)
    device_token = Column(String, unique=True, nullable=False, index=True)
    owner_id     = Column(String, ForeignKey("users.id"), nullable=False)
    is_online    = Column(Boolean, default=False)
    last_seen    = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)

    # ── Revision 2: P2P identity ──────────────────────────────────
    # Long-term X25519 public key, base64-encoded (32 raw bytes -> 44 b64 chars).
    # The server NEVER sees the matching private key — it is generated and
    # stored only in ESP32 NVS. This field lets the server hand the key to a
    # browser during signaling so the browser can box/seal messages to the
    # device's box-keypair identity if desired (defense in depth on top of
    # the ephemeral session key derived in the SPAKE2/X25519 handshake).
    public_key   = Column(String, nullable=True)

    owner     = relationship("User", back_populates="devices")
    resources = relationship("Resource", back_populates="device", cascade="all, delete")
    sessions  = relationship("SignalingSession", back_populates="device", cascade="all, delete")


class Resource(Base):
    __tablename__ = "resources"

    id          = Column(String, primary_key=True, default=generate_id)
    resource_id = Column(String, nullable=False)        # e.g. "speed"
    device_id   = Column(String, ForeignKey("devices.id"), nullable=False)
    type        = Column(String, nullable=False)         # switch | value | control
    unit        = Column(String, nullable=True)
    min_val     = Column(Float, nullable=True)
    max_val     = Column(Float, nullable=True)
    last_value  = Column(JSON, nullable=True)
    updated_at  = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="resources")


class SignalingSession(Base):
    """
    Revision 2 — tracks one P2P connection attempt between a browser and a
    device. The server only ever sees: public keys, candidate IPs/ports, and
    connection state. It never sees session keys or decrypted payloads.
    """
    __tablename__ = "signaling_sessions"

    id               = Column(String, primary_key=True, default=generate_id)
    device_id        = Column(String, ForeignKey("devices.id"), nullable=False)
    requested_by      = Column(String, ForeignKey("users.id"), nullable=False)

    # Ephemeral X25519 public keys for THIS session (base64), one per side
    browser_pubkey   = Column(String, nullable=True)
    device_pubkey    = Column(String, nullable=True)

    # NAT/STUN-observed candidates: "ip:port"
    browser_candidate = Column(String, nullable=True)
    device_candidate  = Column(String, nullable=True)

    # State machine: pending -> exchanging -> punching -> connected
    #                                                   -> relay_fallback -> closed
    state            = Column(String, default="pending")
    transport        = Column(String, nullable=True)   # "p2p" | "relay" | None
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="sessions")


# Create all tables
Base.metadata.create_all(bind=engine)
