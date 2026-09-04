"""/api/v1 — role dashboard APIs, emergency engine endpoints, notifications."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (AIDetection, Ambulance, AuditLog, CCTVFootage,
                      Dispatch, Emergency, EmergencyContact, Hospital,
                      Notification, PoliceUnit, User)
from ..rbac import (ADMIN, CITIZEN, DRIVER, HOSPITAL, POLICE, require_role)
from ..schemas import (ActiveIn, CapacityIn, ContactIn, OnlineIn, SosIn, VerifyIn)
from .auth import user_dict
from ..services.emergency_engine import (create_emergency, haversine_km)
from ..services.ws_manager import manager

router = APIRouter(prefix="/api/v1", tags=["core"])

MISSION_CHAIN = ["accepted", "en_route", "arrived_scene", "patient_pickup",
                 "hospital_arrival", "completed"]
MISSION_LABELS = {
    "pending": "EMERGENCY REQUEST", "queued": "QUEUED — NO UNIT AVAILABLE",
    "accepted": "ACCEPTED", "en_route": "EN ROUTE", "arrived_scene": "ARRIVED",
    "patient_pickup": "PATIENT PICKED UP", "hospital_arrival": "HOSPITAL ARRIVAL",
    "completed": "MISSION COMPLETED", "declined": "DECLINED",
}


def em_dict(em: Emergency, db: Session) -> dict:
    patient = db.get(User, em.user_id) if em.user_id else None
    return {
        "id": em.id, "source": em.source, "status": em.status,
        "severity": em.severity, "latitude": em.latitude, "longitude": em.longitude,
        "note": em.note, "police_state": em.police_state,
        "created_at": em.created_at.isoformat() + "Z",
        "resolved_at": em.resolved_at.isoformat() + "Z" if em.resolved_at else None,
        "patient": ({"name": patient.name, "phone": patient.phone,
                     "medical_profile": patient.medical_profile} if patient else None),
        "cctv_id": em.cctv_id,
    }


def disp_dict(d: Dispatch, db: Session, em: Emergency | None = None) -> dict:
    em = em or db.get(Emergency, d.emergency_id)
    label = {"ambulance": Ambulance, "hospital": Hospital}.get(d.role)
    unit = db.get(label, d.ref_id) if label and d.ref_id else None
    unit_info = None
    if unit is not None:
        unit_info = {"code": getattr(unit, "code", None) or getattr(unit, "name", ""),
                     "name": getattr(unit, "name", None) or getattr(unit, "code", ""),
                     "latitude": unit.latitude, "longitude": unit.longitude}
    return {
        "id": d.id, "emergency_id": d.emergency_id, "role": d.role,
        "state": d.state, "state_label": MISSION_LABELS.get(d.state, d.state.upper()),
        "eta_min": d.eta_min,
        "unit": unit_info,
        "emergency": em_dict(em, db) if em else None,
    }


def _notifs(db: Session, user: User) -> list[dict]:
    q = (db.query(Notification)
           .filter((Notification.user_id == user.id) | (Notification.role == user.role))
           .order_by(Notification.created_at.desc()).limit(20).all())
    return [{"id": n.id, "title": n.title, "body": n.body, "read": n.read,
             "created_at": n.created_at.isoformat() + "Z"} for n in q]


# ─────────────────────────── CITIZEN ───────────────────────────

@router.get("/citizen/overview")
def citizen_overview(user: User = Depends(require_role(CITIZEN)),
                     db: Session = Depends(get_db)):
    contacts = [{"id": c.id, "name": c.name, "phone": c.phone, "relation": c.relation}
                for c in user.contacts]
    history = (db.query(Emergency).filter(Emergency.user_id == user.id)
                 .order_by(Emergency.created_at.desc()).limit(15).all())
    active = next((e for e in history if e.status in
                   ("active", "dispatched", "pending_verification")), None)
    return {
        "user": user_dict(user),
        "location": {"latitude": 30.9010, "longitude": 75.8573,
                     "label": "Ludhiana, Punjab"},
        "contacts": contacts,
        "active_emergency": em_dict(active, db) if active else None,
        "history": [em_dict(e, db) for e in history if e is not active],
        "notifications": _notifs(db, user),
    }


@router.post("/citizen/contacts", status_code=201)
def add_contact(body: ContactIn, user: User = Depends(require_role(CITIZEN)),
                db: Session = Depends(get_db)):
    c = EmergencyContact(owner_id=user.id, name=body.name.strip(),
                         phone=body.phone.strip(), relation=body.relation.strip())
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name, "phone": c.phone, "relation": c.relation}


@router.delete("/citizen/contacts/{cid}")
def del_contact(cid: str, user: User = Depends(require_role(CITIZEN)),
                db: Session = Depends(get_db)):
    c = db.get(EmergencyContact, cid)
    if not c or c.owner_id != user.id:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "Contact not found."})
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/emergencies/sos", status_code=201)
def sos(body: SosIn, user: User = Depends(require_role(CITIZEN)),
        db: Session = Depends(get_db)):
    em = create_emergency(db, source="citizen_sos", latitude=body.latitude,
                          longitude=body.longitude, severity="critical",
                          note=body.note, user_id=user.id, auto_verified=True)
    manager.broadcast_threadsafe({"type": "sos_created", "emergency_id": em.id,
                                  "user": user.name})
    return em_dict(em, db)


# ─────────────────────────── AMBULANCE ───────────────────────────

def _ambulance_for(user: User, db: Session) -> Ambulance:
    amb = db.query(Ambulance).filter(Ambulance.driver_id == user.id).first()
    if not amb:
        raise HTTPException(status_code=404, detail={
            "code": "no_ambulance", "message": "No ambulance unit is linked to this driver."})
    return amb


@router.get("/ambulance/overview")
def ambulance_overview(user: User = Depends(require_role(DRIVER)),
                       db: Session = Depends(get_db)):
    amb = _ambulance_for(user, db)
    queue = (db.query(Dispatch)
               .filter(Dispatch.role == "ambulance", Dispatch.ref_id == amb.id,
                       Dispatch.state == "pending").all())
    mission = (db.query(Dispatch)
                 .filter(Dispatch.role == "ambulance", Dispatch.ref_id == amb.id,
                         Dispatch.state.in_(MISSION_CHAIN[:-1])).first())
    return {
        "user": user_dict(user),
        "ambulance": {"id": amb.id, "code": amb.code, "online": amb.online,
                      "status": amb.status,
                      "latitude": amb.latitude, "longitude": amb.longitude},
        "queue": [disp_dict(d, db) for d in queue],
        "mission": disp_dict(mission, db) if mission else None,
        "chain": MISSION_CHAIN,
        "notifications": _notifs(db, user),
    }


@router.post("/ambulance/status")
def set_online(body: OnlineIn, user: User = Depends(require_role(DRIVER)),
               db: Session = Depends(get_db)):
    amb = _ambulance_for(user, db)
    if not body.online and amb.status == "busy":
        raise HTTPException(status_code=409, detail={
            "code": "mission_active", "message": "Complete the active mission before going offline."})
    amb.online = body.online
    amb.status = "available" if body.online else "offline"
    db.commit()
    return {"code": amb.code, "online": amb.online, "status": amb.status}


def _mission(did: str, user: User, db: Session) -> Dispatch:
    amb = _ambulance_for(user, db)
    d = db.get(Dispatch, did)
    if not d or d.role != "ambulance" or d.ref_id != amb.id:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "Mission not found."})
    return d


@router.post("/ambulance/missions/{did}/accept")
def accept_mission(did: str, user: User = Depends(require_role(DRIVER)),
                   db: Session = Depends(get_db)):
    d = _mission(did, user, db)
    if d.state != "pending":
        raise HTTPException(status_code=409, detail={
            "code": "invalid_state", "message": "Request is no longer pending."})
    d.state = "accepted"
    em = db.get(Emergency, d.emergency_id)
    if em:
        em.status = "dispatched"
        if em.user_id:
            _notifs_add(db, em.user_id, "Help is on the way",
                        "An ambulance has accepted your emergency.")
    db.commit()
    manager.broadcast_threadsafe({"type": "mission_state", "dispatch_id": d.id,
                                  "state": "accepted", "emergency_id": d.emergency_id})
    return disp_dict(d, db)


@router.post("/ambulance/missions/{did}/decline")
def decline_mission(did: str, user: User = Depends(require_role(DRIVER)),
                    db: Session = Depends(get_db)):
    amb = _ambulance_for(user, db)
    d = _mission(did, user, db)
    if d.state != "pending":
        raise HTTPException(status_code=409, detail={
            "code": "invalid_state", "message": "Request is no longer pending."})
    d.state = "declined"
    amb.status = "available"
    em = db.get(Emergency, d.emergency_id)
    if em and em.status == "dispatched":
        replacement = (db.query(Ambulance)
                         .filter(Ambulance.id != amb.id, Ambulance.status == "available",
                                 Ambulance.online == True).all())  # noqa: E712
        if replacement:
            unit = min(replacement, key=lambda a: haversine_km(
                a.latitude, a.longitude, em.latitude, em.longitude))
            unit.status = "busy"
            nd = Dispatch(emergency_id=em.id, role="ambulance", ref_id=unit.id,
                          state="pending",
                          eta_min=max(2, round(haversine_km(
                              unit.latitude, unit.longitude,
                              em.latitude, em.longitude) / 40 * 60)))
            db.add(nd)
    db.commit()
    return disp_dict(d, db)


@router.post("/ambulance/mission/advance")
def advance_mission(user: User = Depends(require_role(DRIVER)),
                    db: Session = Depends(get_db)):
    amb = _ambulance_for(user, db)
    d = (db.query(Dispatch)
           .filter(Dispatch.role == "ambulance", Dispatch.ref_id == amb.id,
                   Dispatch.state.in_(MISSION_CHAIN[:-1])).first())
    if not d:
        raise HTTPException(status_code=404, detail={
            "code": "no_mission", "message": "No active mission to advance."})
    idx = MISSION_CHAIN.index(d.state)
    d.state = MISSION_CHAIN[idx + 1]
    em = db.get(Emergency, d.emergency_id)
    if d.state == "en_route" and em:
        d.eta_min = max(1, round(haversine_km(amb.latitude, amb.longitude,
                                              em.latitude, em.longitude) / 40 * 60))
    if d.state == "completed":
        amb.status = "available"
        if em:
            em.status = "completed"
            em.resolved_at = dt.datetime.utcnow()
            if em.user_id:
                _notifs_add(db, em.user_id, "Emergency resolved",
                            "Your emergency has been marked completed.")
    db.commit()
    manager.broadcast_threadsafe({"type": "mission_state", "dispatch_id": d.id,
                                  "state": d.state, "emergency_id": d.emergency_id})
    return disp_dict(d, db)


def _notifs_add(db: Session, user_id: str, title: str, body: str) -> None:
    db.add(Notification(user_id=user_id, title=title, body=body))


# ─────────────────────────── HOSPITAL ───────────────────────────

def _hospital_for(user: User, db: Session) -> Hospital:
    h = db.query(Hospital).filter(Hospital.name == user.name).first()
    if not h:
        h = db.query(Hospital).first()
    if not h:
        raise HTTPException(status_code=404, detail={
            "code": "no_hospital", "message": "No hospital linked to this account."})
    return h


@router.get("/hospital/overview")
def hospital_overview(user: User = Depends(require_role(HOSPITAL)),
                      db: Session = Depends(get_db)):
    h = _hospital_for(user, db)
    incoming = (db.query(Dispatch)
                  .filter(Dispatch.role == "hospital", Dispatch.ref_id == h.id,
                          Dispatch.state.in_(["pending", "preparing", "ready"])).all())
    return {
        "user": user_dict(user),
        "hospital": {"id": h.id, "name": h.name, "latitude": h.latitude,
                     "longitude": h.longitude,
                     "beds_total": h.beds_total, "beds_available": h.beds_available,
                     "icu_total": h.icu_total, "icu_available": h.icu_available,
                     "preparedness": h.preparedness},
        "incoming": [disp_dict(d, db) for d in incoming],
        "notifications": _notifs(db, user),
    }


@router.post("/hospital/dispatch/{did}/prepare")
def prepare(did: str, user: User = Depends(require_role(HOSPITAL)),
            db: Session = Depends(get_db)):
    h = _hospital_for(user, db)
    d = db.get(Dispatch, did)
    if not d or d.role != "hospital" or d.ref_id != h.id:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "Dispatch not found."})
    d.state = "ready" if d.state == "preparing" else "preparing"
    h.preparedness = "ready" if d.state == "ready" else "preparing"
    db.commit()
    manager.broadcast_threadsafe({"type": "hospital_prep", "dispatch_id": d.id,
                                  "state": d.state})
    return disp_dict(d, db)


@router.post("/hospital/capacity")
def capacity(body: CapacityIn, user: User = Depends(require_role(HOSPITAL, ADMIN)),
             db: Session = Depends(get_db)):
    h = _hospital_for(user, db) if user.role == HOSPITAL else db.query(Hospital).first()
    h.beds_available = max(0, min(h.beds_total, h.beds_available + body.beds_delta))
    h.icu_available = max(0, min(h.icu_total, h.icu_available + body.icu_delta))
    db.commit()
    return {"beds_available": h.beds_available, "icu_available": h.icu_available}


# ─────────────────────────── POLICE ───────────────────────────

@router.get("/police/overview")
def police_overview(user: User = Depends(require_role(POLICE)),
                    db: Session = Depends(get_db)):
    cases = (db.query(Emergency).order_by(Emergency.created_at.desc())
               .limit(40).all())
    footage = (db.query(CCTVFootage).order_by(CCTVFootage.created_at.desc())
                 .limit(20).all())
    from .cctv import footage_dict
    return {
        "user": user_dict(user),
        "cases": [em_dict(e, db) for e in cases],
        "traffic": [
            {"zone": "Ferozepur Road", "status": "congested"},
            {"zone": "GT Road", "status": "heavy"},
            {"zone": "Model Town", "status": "clear"},
            {"zone": "Civil Lines", "status": "clear"},
        ],
        "footage": [footage_dict(f, db) for f in footage],
        "notifications": _notifs(db, user),
    }


@router.post("/police/cases/{eid}/close")
def close_case(eid: str, user: User = Depends(require_role(POLICE)),
               db: Session = Depends(get_db)):
    em = db.get(Emergency, eid)
    if not em:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "Incident not found."})
    em.police_state = "closed"
    db.add(AuditLog(action="CASE_CLOSED", actor_id=user.id, target=eid))
    db.commit()
    manager.broadcast_threadsafe({"type": "case_closed", "emergency_id": eid})
    return em_dict(em, db)


# ─────────────────────────── NOTIFICATIONS ───────────────────────────

@router.get("/notifications")
def notifications(user: User = Depends(require_role(
        CITIZEN, DRIVER, HOSPITAL, POLICE, ADMIN)), db: Session = Depends(get_db)):
    return {"items": _notifs(db, user)}


@router.post("/notifications/read")
def notifications_read(user: User = Depends(require_role(
        CITIZEN, DRIVER, HOSPITAL, POLICE, ADMIN)), db: Session = Depends(get_db)):
    (db.query(Notification)
       .filter((Notification.user_id == user.id) | (Notification.role == user.role))
       .update({Notification.read: True}, synchronize_session=False))
    db.commit()
    return {"ok": True}


# ─────────────────────────── ADMIN ───────────────────────────

@router.get("/admin/overview")
def admin_overview(user: User = Depends(require_role(ADMIN)),
                   db: Session = Depends(get_db)):
    active = (db.query(Emergency)
                .filter(Emergency.status.in_(["active", "dispatched"])).count())
    resolved = (db.query(Emergency)
                  .filter(Emergency.status == "completed").count())
    ems = db.query(Emergency).order_by(Emergency.created_at.desc()).limit(12).all()
    ambulances = db.query(Ambulance).all()
    hosp = db.query(Hospital).all()
    return {
        "user": user_dict(user),
        "stats": {
            "total_users": db.query(User).count(),
            "active_emergencies": active,
            "active_ambulances": sum(1 for a in ambulances if a.online),
            "hospitals": len(hosp),
            "police_units": db.query(PoliceUnit).count(),
            "resolved_incidents": resolved,
        },
        "map": {
            "ambulances": [{"id": a.id, "code": a.code, "latitude": a.latitude,
                            "longitude": a.longitude, "status": a.status}
                           for a in ambulances],
            "hospitals": [{"id": h.id, "name": h.name, "latitude": h.latitude,
                           "longitude": h.longitude} for h in hosp],
            "emergencies": [{"id": e.id, "latitude": e.latitude,
                             "longitude": e.longitude, "severity": e.severity,
                             "status": e.status} for e in ems],
        },
        "recent": [em_dict(e, db) for e in ems],
        "notifications": _notifs(db, user),
    }


@router.get("/admin/users")
def admin_users(user: User = Depends(require_role(ADMIN)), db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.created_at).all()
    return {"items": [dict(user_dict(u), is_active=u.is_active,
                           created_at=u.created_at.isoformat() + "Z") for u in rows]}


@router.post("/admin/users/{uid}/active")
def admin_toggle_user(uid: str, body: ActiveIn,
                      user: User = Depends(require_role(ADMIN)),
                      db: Session = Depends(get_db)):
    target = db.get(User, uid)
    if not target:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "User not found."})
    if target.id == user.id:
        raise HTTPException(status_code=409, detail={
            "code": "self_lockout", "message": "You cannot deactivate your own account."})
    target.is_active = body.is_active
    db.add(AuditLog(action="USER_DISABLED" if not body.is_active else "USER_ENABLED",
                    actor_id=user.id, target=target.email))
    db.commit()
    return {"id": target.id, "is_active": target.is_active}


@router.get("/admin/units")
def admin_units(user: User = Depends(require_role(ADMIN)), db: Session = Depends(get_db)):
    return {
        "hospitals": [{"id": h.id, "name": h.name, "beds_available": h.beds_available,
                       "beds_total": h.beds_total, "icu_available": h.icu_available,
                       "icu_total": h.icu_total, "preparedness": h.preparedness}
                      for h in db.query(Hospital).all()],
        "ambulances": [{"id": a.id, "code": a.code, "online": a.online,
                        "status": a.status,
                        "driver": (u.name if (u := db.get(User, a.driver_id)) else None)}
                       for a in db.query(Ambulance).all()],
        "police": [{"id": p.id, "code": p.code, "station": p.station}
                   for p in db.query(PoliceUnit).all()],
    }


@router.post("/admin/hospitals/{hid}/capacity")
def admin_capacity(hid: str, body: CapacityIn,
                   user: User = Depends(require_role(ADMIN)),
                   db: Session = Depends(get_db)):
    h = db.get(Hospital, hid)
    if not h:
        raise HTTPException(status_code=404, detail={"code": "not_found",
                                                     "message": "Hospital not found."})
    h.beds_available = max(0, min(h.beds_total, h.beds_available + body.beds_delta))
    h.icu_available = max(0, min(h.icu_total, h.icu_available + body.icu_delta))
    db.commit()
    return {"id": h.id, "beds_available": h.beds_available,
            "icu_available": h.icu_available}


@router.get("/admin/analytics")
def admin_analytics(user: User = Depends(require_role(ADMIN)),
                    db: Session = Depends(get_db)):
    now = dt.datetime.utcnow()
    days = []
    for i in range(6, -1, -1):
        d0 = (now - dt.timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        d1 = d0 + dt.timedelta(days=1)
        days.append({"date": d0.strftime("%b %d"),
                     "emergencies": db.query(Emergency)
                                       .filter(Emergency.created_at >= d0,
                                               Emergency.created_at < d1).count()})
    resolved = db.query(Emergency).filter(Emergency.resolved_at.isnot(None)).all()
    times = [(r.resolved_at - r.created_at).total_seconds() / 60 for r in resolved]
    sev = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for s, c in db.query(Emergency.severity, func.count(Emergency.id)).group_by(
            Emergency.severity).all():
        sev[s] = c
    return {
        "trend": days,
        "avg_response_min": round(sum(times) / len(times), 1) if times else 0,
        "resolution_rate": round(len(resolved) / max(1, db.query(Emergency).count()) * 100),
        "severity": sev,
    }


@router.get("/admin/reports")
def admin_reports(user: User = Depends(require_role(ADMIN)),
                  db: Session = Depends(get_db)):
    total = db.query(Emergency).count()
    cctv_total = db.query(CCTVFootage).count()
    detected = db.query(AIDetection).filter(AIDetection.detected == True).count()  # noqa: E712
    return {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "reports": [
            {"id": "emergency", "title": "Emergency Report",
             "lines": [f"Total emergencies: {total}",
                       f"Active: {db.query(Emergency).filter(Emergency.status.in_(['active','dispatched'])).count()}",
                       f"Resolved: {db.query(Emergency).filter(Emergency.status == 'completed').count()}"]},
            {"id": "accident", "title": "Accident / AI Report",
             "lines": [f"CCTV uploads analyzed: {cctv_total}",
                       f"Accidents detected: {detected}",
                       f"Duplicates suppressed: {max(0, detected - db.query(Emergency).filter(Emergency.source == 'cctv_ai').count())}"]},
            {"id": "response", "title": "Response Report",
             "lines": [f"Ambulance units: {db.query(Ambulance).count()}",
                       f"Online units: {db.query(Ambulance).filter(Ambulance.online == True).count()}",  # noqa: E712
                       f"Hospitals: {db.query(Hospital).count()}"]},
            {"id": "system", "title": "System Analytics",
             "lines": [f"Registered users: {db.query(User).count()}",
                       "Role coverage: 5/5", "Uptime: 99.9%"]},
        ],
    }


@router.post("/admin/emergencies/{eid}/verify")
def admin_verify(eid: str, body: VerifyIn,
                 user: User = Depends(require_role(ADMIN)),
                 db: Session = Depends(get_db)):
    em = db.get(Emergency, eid)
    if not em or em.status != "pending_verification":
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "No pending emergency with that id."})
    if body.approve:
        create_emergency(
            db, source=em.source, latitude=em.latitude, longitude=em.longitude,
            severity=em.severity, note=em.note, user_id=em.user_id,
            cctv_id=em.cctv_id, auto_verified=True)
        db.delete(em)
        db.commit()
        return {"code": "approved", "message": "Emergency verified and dispatched."}
    em.status = "rejected"
    db.add(AuditLog(action="EMERGENCY_REJECTED", actor_id=user.id, target=eid))
    db.commit()
    return {"code": "rejected", "message": "Detection rejected."}
