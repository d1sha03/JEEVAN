"""Auth + RBAC tests."""
from conftest import PASSWORD, auth, login


def test_login_success_returns_role_and_permissions(client, citizen):
    assert citizen["token_type"] == "bearer"
    assert citizen["user"]["role"] == "citizen"
    assert "sos:create" in citizen["permissions"]
    assert citizen["user"]["dashboard"] == "/citizen"


def test_login_with_phone(client):
    tok = login(client, "+911000000000")
    assert tok["user"]["role"] == "citizen"


def test_login_invalid_credentials(client):
    r = client.post("/api/v1/auth/login",
                    json={"identifier": "citizen@test.io", "password": "wrong-pass"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_credentials"


def test_login_disabled_account(client):
    r = client.post("/api/v1/auth/login",
                    json={"identifier": "disabled@test.io", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "account_disabled"


def test_me_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_returns_user(client, admin):
    r = client.get("/api/v1/auth/me", headers=auth(admin))
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "administrator"
    assert "*" in r.json()["permissions"]


def test_refresh_flow(client, citizen):
    r = client.post("/api/v1/auth/refresh",
                    json={"refresh_token": citizen["refresh_token"]})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_register_creates_citizen(client):
    r = client.post("/api/v1/auth/register", json={
        "name": "New Person", "email": "new@test.io",
        "phone": "+919999999999", "password": "Str0ngPass!"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "citizen"


def test_rbac_citizen_blocked_from_admin(client, citizen):
    r = client.get("/api/v1/admin/overview", headers=auth(citizen))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"


def test_rbac_citizen_blocked_from_cctv_upload(client, citizen):
    r = client.post("/api/v1/cctv/upload", headers=auth(citizen),
                    files={"file": ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")})
    assert r.status_code == 403


def test_rbac_citizen_blocked_from_police_apis(client, citizen):
    r = client.get("/api/v1/police/overview", headers=auth(citizen))
    assert r.status_code == 403


def test_rbac_driver_blocked_from_hospital_management(client, driver):
    r = client.get("/api/v1/hospital/overview", headers=auth(driver))
    assert r.status_code == 403


def test_rbac_hospital_blocked_from_admin_users(client, hospital):
    r = client.get("/api/v1/admin/users", headers=auth(hospital))
    assert r.status_code == 403
