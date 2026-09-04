"""/api/v1/auth — login, refresh, register, forgot/reset, me, logout."""
import datetime as dt
import secrets

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User
from ..rbac import ROLE_PERMISSIONS, get_current_user
from ..schemas import (ForgotIn, LoginIn, RefreshIn, RegisterIn, ResetIn)
from ..security import (create_access_token, create_refresh_token, decode_token,
                        hash_password, verify_password)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

ROLE_DASHBOARDS = {
    "citizen": "/citizen",
    "ambulance_driver": "/ambulance",
    "hospital_staff": "/hospital",
    "police_officer": "/police",
    "administrator": "/admin",
}


def user_dict(user: User) -> dict:
    return {
        "id": user.id, "name": user.name, "email": user.email,
        "phone": user.phone, "role": user.role,
        "dashboard": ROLE_DASHBOARDS.get(user.role, "/"),
        "is_active": user.is_active,
        "medical_profile": user.medical_profile,
    }


def _audit(db: Session, action: str, actor: str | None = "", target: str = "",
           meta: str = "") -> None:
    db.add(AuditLog(action=action, actor_id=actor or None, target=target, meta=meta))
    db.commit()


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    ident = body.identifier.strip().lower()
    user = db.query(User).filter((User.email == ident) |
                                 (User.phone == body.identifier.strip())).first()
    if not user or not verify_password(body.password, user.password_hash):
        _audit(db, "LOGIN_FAILED", target=ident)
        raise HTTPException(status_code=401, detail={
            "code": "invalid_credentials", "message": "Invalid email/phone or password."})
    if not user.is_active:
        _audit(db, "LOGIN_BLOCKED_DISABLED", actor=user.id, target=user.email)
        raise HTTPException(status_code=403, detail={
            "code": "account_disabled",
            "message": "This account has been deactivated. Contact your administrator."})
    _audit(db, "LOGIN_SUCCESS", actor=user.id, target=user.email)
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
        "expires_in": 60 * 30,
        "user": user_dict(user),
        "permissions": ROLE_PERMISSIONS.get(user.role, []),
    }


@router.post("/refresh")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail={
            "code": "session_expired", "message": "Refresh token invalid or expired."})
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail={
            "code": "account_disabled", "message": "Account is disabled."})
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
        "user": user_dict(user),
        "permissions": ROLE_PERMISSIONS.get(user.role, []),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.refresh(user)
    return {"user": user_dict(user), "permissions": ROLE_PERMISSIONS.get(user.role, [])}


@router.post("/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail={
            "code": "email_taken", "message": "An account with this email already exists."})
    user = User(name=body.name.strip(), email=email, phone=body.phone.strip(),
                password_hash=hash_password(body.password), role="citizen")
    db.add(user)
    db.commit()
    _audit(db, "USER_REGISTERED", actor=user.id, target=email)
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
        "user": user_dict(user),
        "permissions": ROLE_PERMISSIONS.get(user.role, []),
    }


@router.post("/forgot-password")
def forgot(body: ForgotIn, db: Session = Depends(get_db)):
    ident = body.identifier.strip().lower()
    user = db.query(User).filter((User.email == ident) | (User.phone == ident)).first()
    # always generic to avoid account enumeration
    msg = {"code": "reset_sent", "message": "If the account exists, a 6-digit recovery code has been sent."}
    if user:
        code = f"{secrets.randbelow(1000000):06d}"
        user.reset_code = hash_password(code)
        user.reset_expires = dt.datetime.utcnow() + dt.timedelta(minutes=10)
        db.commit()
        if dt is None:  # pragma: no cover
            pass
        # No SMS/email provider in this environment: surface the code in debug mode only.
        from ..config import settings
        if settings.DEBUG:
            msg["debug_code"] = code
    return msg


@router.post("/reset-password")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    ident = body.identifier.strip().lower()
    user = db.query(User).filter((User.email == ident) | (User.phone == ident)).first()
    if not user or not user.reset_code or not user.reset_expires \
            or dt.datetime.utcnow() > user.reset_expires \
            or not verify_password(body.code, user.reset_code):
        raise HTTPException(status_code=400, detail={
            "code": "invalid_code", "message": "Invalid or expired recovery code."})
    user.password_hash = hash_password(body.new_password)
    user.reset_code = ""
    user.reset_expires = None
    db.commit()
    _audit(db, "PASSWORD_RESET", actor=user.id, target=user.email)
    return {"code": "password_reset", "message": "Password updated. You can sign in now."}


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _audit(db, "LOGOUT", actor=user.id, target=user.email)
    return {"code": "logged_out", "message": "Signed out."}
