import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JEEVAN_DB"] = "sqlite:///" + os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_jeevan.db").replace("\\", "/")
os.environ["JEEVAN_AI_DELAY"] = "0"
os.environ["JEEVAN_JWT_SECRET"] = "test-secret-key-not-for-production"

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app
from app.models import User
from app.security import hash_password
from app.seed import PASSWORD


@pytest.fixture(scope="session")
def client():
    # start each test session from a clean database (idempotent re-runs)
    import os
    dbfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_jeevan.db")
    if os.path.exists(dbfile):
        os.remove(dbfile)
    init_db()
    db = SessionLocal()
    roles = ["citizen", "ambulance_driver", "hospital_staff",
             "police_officer", "administrator"]
    for i, role in enumerate(roles):
        db.add(User(name=f"Test {role}", email=f"{role}@test.io",
                    phone=f"+91100000000{i}", role=role,
                    password_hash=hash_password(PASSWORD), is_active=True))
    db.add(User(name="Disabled User", email="disabled@test.io", phone="+91200000000",
                role="citizen", password_hash=hash_password(PASSWORD),
                is_active=False))
    db.commit()
    from app.models import Ambulance, Hospital, PoliceUnit
    driver_user = db.query(User).filter_by(role="ambulance_driver").first()
    db.add(Ambulance(code="TEST-AMB-1", driver_id=driver_user.id, online=True,
                     status="available", latitude=30.90, longitude=75.85))
    db.add(Hospital(name="Test Hospital", latitude=30.91, longitude=75.84,
                    icu_total=4, icu_available=2, beds_total=20, beds_available=8))
    db.add(PoliceUnit(code="PS-TEST", station="Test PS", latitude=30.90, longitude=75.85))
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


def login(client, ident, password=PASSWORD):
    r = client.post("/api/v1/auth/login",
                    json={"identifier": ident, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="session")
def citizen(client):
    return login(client, "citizen@test.io")


@pytest.fixture(scope="session")
def driver(client):
    return login(client, "ambulance_driver@test.io")


@pytest.fixture(scope="session")
def hospital(client):
    return login(client, "hospital_staff@test.io")


@pytest.fixture(scope="session")
def police(client):
    return login(client, "police_officer@test.io")


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "administrator@test.io")


def auth(tok):
    return {"Authorization": f"Bearer {tok['access_token']}"}
