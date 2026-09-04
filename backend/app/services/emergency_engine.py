"""Emergency engine — the ONLY component allowed to create/dispatch emergencies.

Pipeline (spec Feature 11):
  AI detection -> deduplication -> verification gate -> emergency creation
  -> resource dispatch (ambulance + hospital + police) -> notifications/WS.

The AI service never calls this directly with dispatch powers; the backend
ingestion path (CCTV upload task / citizen SOS) drives the engine.
"""
import datetime as dt
import math

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (Ambulance, AIDetection, AuditLog, Dispatch, Emergency,
                      Hospital, Notification, PoliceUnit)
from .ws_manager import manager


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _eta_minutes(lat1, lon1, lat2, lon2) -> int:
    return max(2, round(haversine_km(lat1, lon1, lat2, lon2) / 40.0 * 60))


def _notify(db: Session, title: str, body: str, role: str | None = None,
            user_id: str | None = None) -> None:
    db.add(Notification(title=title, body=body, role=role, user_id=user_id))


def _dispatch_resources(db: Session, em: Emergency) -> list[Dispatch]:
    made: list[Dispatch] = []
    amb = (db.query(Ambulance)
             .filter(Ambulance.status == "available", Ambulance.online == True)  # noqa: E712
             .all())
    if amb:
        unit = min(amb, key=lambda a: haversine_km(a.latitude, a.longitude,
                                                   em.latitude, em.longitude))
        eta = _eta_minutes(unit.latitude, unit.longitude, em.latitude, em.longitude)
        d = Dispatch(emergency_id=em.id, role="ambulance", ref_id=unit.id,
                     state="pending", eta_min=eta)
        db.add(d)
        unit.status = "busy"
        made.append(d)
    else:
        made.append(Dispatch(emergency_id=em.id, role="ambulance", ref_id="",
                             state="queued", eta_min=0))

    hosp = db.query(Hospital).filter(Hospital.beds_available > 0).all()
    if hosp:
        h = min(hosp, key=lambda x: haversine_km(x.latitude, x.longitude,
                                                 em.latitude, em.longitude))
        d = Dispatch(emergency_id=em.id, role="hospital", ref_id=h.id,
                     state="pending",
                     eta_min=_eta_minutes(h.latitude, h.longitude, em.latitude, em.longitude))
        db.add(d)
        made.append(d)

    pol = db.query(PoliceUnit).all()
    if pol:
        p = min(pol, key=lambda x: haversine_km(x.latitude, x.longitude,
                                                em.latitude, em.longitude))
        d = Dispatch(emergency_id=em.id, role="police", ref_id=p.id,
                     state="assigned", eta_min=0)
        db.add(d)
        made.append(d)

    db.flush()
    return made


def finalize_emergency(db: Session, em: Emergency, dispatches: list[Dispatch]) -> None:
    em.status = "dispatched"
    db.add(AuditLog(action="EMERGENCY_DISPATCHED", target=em.id,
                    meta=f"source={em.source} severity={em.severity}"))
    db.commit()
    manager.broadcast_threadsafe({
        "type": "emergency_created",
        "emergency": {"id": em.id, "source": em.source, "severity": em.severity,
                      "status": em.status, "latitude": em.latitude,
                      "longitude": em.longitude},
    })


def create_emergency(db: Session, *, source: str, latitude: float, longitude: float,
                     severity: str, note: str = "", user_id: str | None = None,
                     cctv_id: str | None = None,
                     auto_verified: bool = True) -> Emergency:
    em = Emergency(source=source, latitude=latitude, longitude=longitude,
                   severity=severity, note=note, user_id=user_id, cctv_id=cctv_id,
                   status="active" if auto_verified else "pending_verification")
    db.add(em)
    db.flush()
    _notify(db, "Emergency reported",
            f"{source} incident near ({latitude:.4f}, {longitude:.4f})",
            role="administrator")
    if auto_verified:
        dispatches = _dispatch_resources(db, em)
        _notify(db, "Ambulance request", f"New {severity} emergency assigned",
                role="ambulance_driver")
        _notify(db, "Incoming patient", f"Emergency en route ({severity})",
                role="hospital_staff")
        _notify(db, "Incident opened", f"Severity {severity} incident logged",
                role="police_officer")
        if user_id:
            _notify(db, "SOS activated",
                    "Location captured. Response teams notified.", user_id=user_id)
        db.commit()
        finalize_emergency(db, em, dispatches)
    else:
        _notify(db, "Verification needed",
                "AI detection below auto-verify threshold. Review required.",
                role="administrator")
        db.commit()
    return em


def ingest_detection(db: Session, footage, detection: dict) -> dict:
    """Post-analysis ingestion: dedup -> verification gate -> dispatch."""
    det = AIDetection(
        footage_id=footage.id,
        detection_type="road_accident",
        detected=detection["detected"],
        confidence=detection["confidence"],
        severity=detection["severity"],
        latitude=(detection.get("location") or {}).get("latitude"),
        longitude=(detection.get("location") or {}).get("longitude"),
        model_name=detection.get("model_name", settings.AI_MODEL_NAME),
        model_version=detection.get("model_version", settings.AI_MODEL_VERSION),
    )
    db.add(det)
    db.flush()

    result = {
        "analysis_id": det.id,
        "detected": det.detected,
        "confidence": det.confidence,
        "severity": det.severity,
        "duplicate": False,
        "emergency_id": None,
        "verification": "not_applicable",
    }
    if not det.detected:
        db.commit()
        return result

    lat = det.latitude if det.latitude is not None else footage.latitude
    lon = det.longitude if det.longitude is not None else footage.longitude

    # --- deduplication: same ~500m cell within the last 10 minutes ---
    if lat is not None:
        window = dt.datetime.utcnow() - dt.timedelta(minutes=10)
        recent = (db.query(Emergency)
                    .filter(Emergency.created_at >= window,
                            Emergency.status.in_(["active", "dispatched",
                                                  "pending_verification"]))
                    .all())
        for em in recent:
            if abs(em.latitude - lat) < 0.005 and abs(em.longitude - (lon or 0)) < 0.005:
                result["duplicate"] = True
                result["emergency_id"] = em.id
                footage.emergency_id = em.id
                db.commit()
                return result

    # --- verification gate ---
    auto = det.confidence >= settings.AI_AUTO_VERIFY_CONFIDENCE
    result["verification"] = "auto_verified" if auto else "pending_manual"
    em = create_emergency(
        db,
        source="cctv_ai",
        latitude=lat if lat is not None else 30.9010,
        longitude=lon if lon is not None else 75.8573,
        severity=det.severity if det.severity != "none" else "medium",
        note=f"CCTV detection {det.confidence:.0%} via camera {footage.camera_id or footage.id[:8]}",
        cctv_id=footage.id,
        auto_verified=auto,
    )
    footage.emergency_id = em.id
    result["emergency_id"] = em.id
    db.commit()
    return result
