"""/api/v1/cctv — secure footage upload + analysis tracking (RBAC protected)."""
import asyncio
import os

from fastapi import (APIRouter, BackgroundTasks, Depends, Form, HTTPException,
                     UploadFile)
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import AIDetection, AuditLog, CCTVFootage, User
from ..rbac import require_permission, require_role
from ..services import emergency_engine
from ..services.ai_inference import analyze_footage
from ..services.ws_manager import manager

router = APIRouter(prefix="/api/v1/cctv", tags=["cctv"])

STAGES = ["uploaded", "processing", "ai_analysis", "result"]


def footage_dict(f: CCTVFootage, db: Session | None = None) -> dict:
    out = {
        "id": f.id, "filename": f.filename, "file_size": f.file_size,
        "mime_type": f.mime_type, "camera_id": f.camera_id,
        "location": ({"latitude": f.latitude, "longitude": f.longitude}
                     if f.latitude is not None else None),
        "uploaded_at": f.uploaded_at.isoformat() + "Z",
        "status": f.processing_status,
        "analysis_id": f.analysis_id,
        "emergency_id": f.emergency_id,
        "error": f.error or None,
    }
    if db is not None and f.analysis_id:
        det = db.get(AIDetection, f.analysis_id)
        if det:
            out["analysis"] = {
                "detected": det.detected, "confidence": det.confidence,
                "severity": det.severity, "detection_type": det.detection_type,
                "timestamp": det.timestamp.isoformat() + "Z",
                "location": ({"latitude": det.latitude, "longitude": det.longitude}
                             if det.latitude is not None else None),
                "model_name": det.model_name, "model_version": det.model_version,
            }
    return out


async def process_footage(footage_id: str) -> None:
    """Background pipeline: PROCESSING -> AI ANALYSIS -> RESULT (-> engine)."""
    db = SessionLocal()
    try:
        f = db.get(CCTVFootage, footage_id)
        if not f:
            return
        meta = {"camera_id": f.camera_id, "latitude": f.latitude, "longitude": f.longitude}
        for stage in STAGES[1:3]:
            f.processing_status = stage
            db.commit()
            manager.broadcast_threadsafe({"type": "cctv_status", "id": f.id, "status": stage},
                                         roles=["administrator", "police_officer"])
            await asyncio.sleep(settings.AI_STAGE_DELAY)
        try:
            result = await asyncio.to_thread(analyze_footage, f.storage_path, meta)
        except Exception as exc:  # inference service failure
            f.processing_status = "failed"
            f.error = f"AI service error: {exc}"
            db.commit()
            manager.broadcast_threadsafe({"type": "cctv_status", "id": f.id,
                                          "status": "failed", "error": f.error},
                                         roles=["administrator", "police_officer"])
            return

        ingest = emergency_engine.ingest_detection(db, f, result)
        f.analysis_id = ingest["analysis_id"]
        f.processing_status = "result"
        db.commit()
        manager.broadcast_threadsafe({
            "type": "cctv_result", "id": f.id, "status": "result",
            "detected": ingest["detected"], "confidence": ingest["confidence"],
            "severity": ingest["severity"], "duplicate": ingest["duplicate"],
            "emergency_id": ingest["emergency_id"],
            "verification": ingest["verification"],
        }, roles=["administrator", "police_officer"])
    finally:
        db.close()


@router.post("/upload", status_code=201)
async def upload(
    background: BackgroundTasks,
    file: UploadFile,
    camera_id: str = Form(default=""),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    user: User = Depends(require_permission("cctv:upload")),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in settings.ALLOWED_VIDEO:
        raise HTTPException(status_code=415, detail={
            "code": "invalid_file",
            "message": f"Unsupported format '{ext or '?'}'. Allowed: MP4, AVI, MOV."})
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    dest = os.path.join(settings.CCTV_DIR, f"{next(_uuid_gen())}{ext}")
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail={
                        "code": "file_too_large",
                        "message": f"File exceeds the {settings.MAX_UPLOAD_MB} MB limit."})
                out.write(chunk)
    except HTTPException:
        os.unlink(dest)
        raise
    if size == 0:
        os.unlink(dest)
        raise HTTPException(status_code=415, detail={
            "code": "invalid_file", "message": "Empty file."})

    footage = CCTVFootage(
        uploaded_by=user.id, filename=os.path.basename(file.filename),
        storage_path=dest, file_size=size,
        mime_type=settings.ALLOWED_VIDEO[ext], camera_id=camera_id,
        latitude=latitude, longitude=longitude, processing_status="uploaded")
    db.add(footage)
    db.commit()
    db.add(AuditLog(action="CCTV_UPLOADED", actor_id=user.id,
                    target=footage.id, meta=f"{footage.filename} ({size} bytes)"))
    db.commit()
    background.add_task(process_footage, footage.id)
    return {
        "id": footage.id, "filename": footage.filename, "status": footage.processing_status,
        "uploaded_at": footage.uploaded_at.isoformat() + "Z", "analysis_id": None,
    }


def _uuid_gen():
    import uuid
    while True:
        yield str(uuid.uuid4())


@router.get("")
def list_footages(user: User = Depends(require_role("administrator", "police_officer")),
                  db: Session = Depends(get_db)):
    rows = (db.query(CCTVFootage).order_by(CCTVFootage.created_at.desc()).limit(50).all())
    return {"items": [footage_dict(f, db) for f in rows]}


@router.get("/{footage_id}")
def get_footage(footage_id: str,
                user: User = Depends(require_role("administrator", "police_officer")),
                db: Session = Depends(get_db)):
    f = db.get(CCTVFootage, footage_id)
    if not f:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": "Footage not found."})
    return footage_dict(f, db)
