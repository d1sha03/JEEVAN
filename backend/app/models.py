"""SQLAlchemy models — JEEVAN emergency response platform."""
import datetime as dt
import uuid

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(24), default="", index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), index=True)  # citizen | ambulance_driver | hospital_staff | police_officer | administrator
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    medical_profile: Mapped[str] = mapped_column(Text, default="")  # citizen blood type / conditions
    reset_code: Mapped[str] = mapped_column(String(12), default="")
    reset_expires: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class EmergencyContact(Base):
    __tablename__ = "emergency_contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(24))
    relation: Mapped[str] = mapped_column(String(40), default="")


class Hospital(Base):
    __tablename__ = "hospitals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(160))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    icu_total: Mapped[int] = mapped_column(Integer, default=10)
    icu_available: Mapped[int] = mapped_column(Integer, default=10)
    beds_total: Mapped[int] = mapped_column(Integer, default=50)
    beds_available: Mapped[int] = mapped_column(Integer, default=50)
    preparedness: Mapped[str] = mapped_column(String(24), default="ready")  # ready | preparing | strained


class Ambulance(Base):
    __tablename__ = "ambulances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    driver_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="offline")  # available | busy | offline
    latitude: Mapped[float] = mapped_column(Float, default=30.9010)
    longitude: Mapped[float] = mapped_column(Float, default=75.8573)


class PoliceUnit(Base):
    __tablename__ = "police_units"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    station: Mapped[str] = mapped_column(String(160), default="")
    latitude: Mapped[float] = mapped_column(Float, default=30.9010)
    longitude: Mapped[float] = mapped_column(Float, default=75.8573)


class Emergency(Base):
    __tablename__ = "emergencies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(24), default="citizen_sos")  # citizen_sos | cctv_ai
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)  # pending_verification | active | dispatched | completed | rejected
    severity: Mapped[str] = mapped_column(String(16), default="high")  # low | medium | high | critical
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cctv_id: Mapped[str | None] = mapped_column(ForeignKey("cctv_footages.id"), nullable=True)
    police_state: Mapped[str] = mapped_column(String(24), default="open")  # open | closed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Dispatch(Base):
    __tablename__ = "dispatches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    emergency_id: Mapped[str] = mapped_column(ForeignKey("emergencies.id"), index=True)
    role: Mapped[str] = mapped_column(String(24))  # ambulance | hospital | police
    ref_id: Mapped[str] = mapped_column(String(64))  # ambulance/hospital/police unit id
    state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    eta_min: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class CCTVFootage(Base):
    __tablename__ = "cctv_footages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(80))
    camera_id: Mapped[str] = mapped_column(String(80), default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    processing_status: Mapped[str] = mapped_column(String(24), default="uploaded", index=True)
    # uploaded | processing | ai_analysis | result | failed
    analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    emergency_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AIDetection(Base):
    __tablename__ = "ai_detections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    footage_id: Mapped[str] = mapped_column(ForeignKey("cctv_footages.id"), index=True)
    detection_type: Mapped[str] = mapped_column(String(48), default="road_accident")
    detected: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), default="none")  # none | low | medium | high | critical
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_name: Mapped[str] = mapped_column(String(80), default="")
    model_version: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # broadcast to role
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(160), default="")
    meta: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# relationships used by serializers
User.contacts = relationship("EmergencyContact", cascade="all,delete-orphan",
                             primaryjoin="User.id==EmergencyContact.owner_id")
