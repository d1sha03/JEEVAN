"""Pydantic request schemas."""
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    identifier: str = Field(min_length=3, description="email or phone")
    password: str = Field(min_length=1)
    remember: bool = False


class RefreshIn(BaseModel):
    refresh_token: str


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    phone: str = ""
    password: str = Field(min_length=8)


class ForgotIn(BaseModel):
    identifier: str


class ResetIn(BaseModel):
    identifier: str
    code: str
    new_password: str = Field(min_length=8)


class SosIn(BaseModel):
    latitude: float
    longitude: float
    note: str = ""


class ContactIn(BaseModel):
    name: str
    phone: str
    relation: str = ""


class OnlineIn(BaseModel):
    online: bool


class CapacityIn(BaseModel):
    beds_delta: int = 0
    icu_delta: int = 0


class ActiveIn(BaseModel):
    is_active: bool


class VerifyIn(BaseModel):
    approve: bool = True
