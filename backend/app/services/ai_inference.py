"""AI inference service — accident detection for CCTV footage.

Architecture (per spec): the AI service ONLY detects. It never dispatches.
The emergency engine consumes the standardized payload returned here.

Two modes:
  1. JEEVAN_AI_URL set  -> footage is POSTed to the external inference service
                           (e.g. a GPU model server) and its JSON is normalized.
  2. No URL (default)   -> deterministic local stub analyzer. Same output
                           contract, clearly labeled, so the real model can be
                           dropped in without touching the backend flow.

Standardized output:
  {"detected": bool, "confidence": float, "severity": str,
   "timestamp": iso, "location": {...}|None, "source": {"type": "cctv"}}
"""
import datetime as dt
import hashlib
import os


def _severity_from_confidence(conf: float) -> str:
    if conf >= 0.92:
        return "critical"
    if conf >= 0.85:
        return "high"
    if conf >= 0.72:
        return "medium"
    return "low"


def _local_analyze(path: str, meta: dict) -> dict:
    """Deterministic stub: derives a stable pseudo-analysis from the file hash.

    Replace with the real model server by setting JEEVAN_AI_URL.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    seed = int(digest.hexdigest()[:12], 16)
    detected = (seed % 100) < 78  # ~78% of clips flag an accident
    confidence = round(0.55 + (seed % 4400) / 10000.0, 4)  # 0.55 - 0.99
    if not detected:
        confidence = round(min(confidence, 0.4), 4)
    loc = None
    if meta.get("latitude") is not None and meta.get("longitude") is not None:
        loc = {"latitude": meta["latitude"], "longitude": meta["longitude"]}
    return {
        "detected": bool(detected),
        "confidence": confidence,
        "severity": _severity_from_confidence(confidence) if detected else "none",
        "timestamp": dt.datetime.utcnow().isoformat() + "Z",
        "location": loc,
        "source": {"type": "cctv", "camera_id": meta.get("camera_id", "")},
        "model_name": os.environ.get("JEEVAN_AI_MODEL_NAME", "jeevan-vision-stub"),
        "model_version": os.environ.get("JEEVAN_AI_MODEL_VERSION", "0.3.0"),
    }


def _normalize_remote(data: dict, meta: dict) -> dict:
    return {
        "detected": bool(data.get("detected", False)),
        "confidence": float(data.get("confidence", 0.0)),
        "severity": str(data.get("severity") or
                        (_severity_from_confidence(float(data.get("confidence", 0)))
                         if data.get("detected") else "none")),
        "timestamp": data.get("timestamp") or dt.datetime.utcnow().isoformat() + "Z",
        "location": data.get("location") or (
            {"latitude": meta["latitude"], "longitude": meta["longitude"]}
            if meta.get("latitude") is not None else None),
        "source": {"type": "cctv", "camera_id": meta.get("camera_id", "")},
        "model_name": str(data.get("model_name", "remote-service")),
        "model_version": str(data.get("model_version", "unknown")),
    }


def analyze_footage(path: str, meta: dict) -> dict:
    """Synchronous analysis entry point (run via threadpool by the caller)."""
    from ..config import settings
    if settings.AI_SERVICE_URL:
        import httpx
        with open(path, "rb") as fh:
            resp = httpx.post(
                settings.AI_SERVICE_URL,
                files={"file": (os.path.basename(path), fh)},
                data={k: str(v) for k, v in meta.items() if v},
                timeout=120,
            )
            resp.raise_for_status()
        return _normalize_remote(resp.json(), meta)
    return _local_analyze(path, meta)
