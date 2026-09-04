"""Role-Based Access Control — permissions matrix and FastAPI dependencies."""
import fastapi
import jwt as pyjwt
from fastapi import Depends, Header, WebSocket
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_token

CITIZEN, DRIVER, HOSPITAL, POLICE, ADMIN = (
    "citizen", "ambulance_driver", "hospital_staff", "police_officer", "administrator")

ROLE_PERMISSIONS: dict[str, list[str]] = {
    CITIZEN: [
        "sos:create", "emergencies:read_own", "contacts:manage", "profile:read",
    ],
    DRIVER: [
        "missions:read", "missions:accept", "missions:update_state", "ambulance:status",
        "emergencies:read_assigned", "profile:read",
    ],
    HOSPITAL: [
        "patients:read_incoming", "capacity:manage", "emergencies:read_assigned", "profile:read",
    ],
    POLICE: [
        "incidents:read", "incidents:close", "cctv:upload", "cctv:read",
        "emergencies:read_all", "profile:read",
    ],
    ADMIN: ["*"],
}


def permissions_for(role: str) -> list[str]:
    return ROLE_PERMISSIONS.get(role, [])


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise fastapi.HTTPException(status_code=401, detail={
            "code": "not_authenticated", "message": "Missing bearer token."})
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token, "access")
    except pyjwt.ExpiredSignatureError:
        raise fastapi.HTTPException(status_code=401, detail={
            "code": "session_expired", "message": "Session expired. Sign in again."})
    except pyjwt.PyJWTError:
        raise fastapi.HTTPException(status_code=401, detail={
            "code": "invalid_token", "message": "Invalid token."})
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise fastapi.HTTPException(status_code=403, detail={
            "code": "account_disabled", "message": "Account is disabled."})
    return user


def has_permission(role: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, [])
    return "*" in perms or permission in perms


def require_role(*roles: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise fastapi.HTTPException(status_code=403, detail={
                "code": "forbidden", "message": "Your role is not authorized for this resource."})
        return user
    return dep


def require_permission(permission: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise fastapi.HTTPException(status_code=403, detail={
                "code": "forbidden", "message": f"Missing permission: {permission}"})
        return user
    return dep


async def ws_auth(ws: WebSocket, db: Session) -> User | None:
    """Authenticate a WebSocket connection via ?token= query param."""
    token = ws.query_params.get("token", "")
    if not token:
        return None
    try:
        payload = decode_token(token, "access")
    except pyjwt.PyJWTError:
        return None
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        return None
    return user
