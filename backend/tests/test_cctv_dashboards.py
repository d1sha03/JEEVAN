"""CCTV upload pipeline + emergency engine + dashboard API tests."""
import time

from conftest import auth


def _fake_mp4(tmp_path):
    p = tmp_path / "camera_01.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isomiso2" + b"\x01" * 4096)
    return p


def test_cctv_upload_validation_bad_type(client, police):
    r = client.post("/api/v1/cctv/upload", headers=auth(police),
                    files={"file": ("clip.txt", b"not-a-video", "text/plain")})
    assert r.status_code == 415
    assert r.json()["detail"]["code"] == "invalid_file"


def test_full_cctv_to_dispatch_flow(client, tmp_path, police, admin, driver,
                                    hospital, citizen):
    video = _fake_mp4(tmp_path)
    with open(video, "rb") as fh:
        r = client.post("/api/v1/cctv/upload", headers=auth(police),
                        files={"file": ("camera_01.mp4", fh, "video/mp4")},
                        data={"camera_id": "CAM-07", "latitude": "30.9089",
                              "longitude": "75.8538"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] in ("uploaded", "processing", "ai_analysis", "result")
    fid = body["id"]

    # poll until the pipeline settles (background task in TestClient)
    result = None
    for _ in range(40):
        g = client.get(f"/api/v1/cctv/{fid}", headers=auth(admin))
        assert g.status_code == 200
        result = g.json()
        if result["status"] in ("result", "failed"):
            break
        time.sleep(0.25)
    assert result["status"] == "result", result
    if result.get("analysis") and result["analysis"]["detected"]:
        assert 0.0 <= result["analysis"]["confidence"] <= 1.0
        assert result["analysis"]["model_name"]
        # detection -> verification gate -> emergency -> dispatch chain
        if result.get("emergency_id"):
            em = client.get("/api/v1/admin/overview", headers=auth(admin))
            ids = [e["id"] for e in em.json()["recent"]]
            assert result["emergency_id"] in ids


def test_footage_list_requires_role(client, citizen):
    r = client.get("/api/v1/cctv", headers=auth(citizen))
    assert r.status_code == 403


def test_sos_creates_and_dispatches(client, citizen):
    r = client.post("/api/v1/emergencies/sos", headers=auth(citizen),
                    json={"latitude": 30.9010, "longitude": 75.8573,
                          "note": "Crash on GT road"})
    assert r.status_code == 201
    em = r.json()
    assert em["source"] == "citizen_sos"
    assert em["status"] == "dispatched"


def test_driver_sees_queue_and_can_accept(client, driver):
    o = client.get("/api/v1/ambulance/overview", headers=auth(driver))
    assert o.status_code == 200
    data = o.json()
    assert data["ambulance"]["online"] is True
    if data["queue"]:
        d = data["queue"][0]
        acc = client.post(f"/api/v1/ambulance/missions/{d['id']}/accept",
                          headers=auth(driver))
        assert acc.status_code == 200
        assert acc.json()["state"] == "accepted"
        adv = client.post("/api/v1/ambulance/mission/advance", headers=auth(driver))
        assert adv.status_code == 200
        assert adv.json()["state"] == "en_route"


def test_hospital_sees_incoming(client, hospital):
    o = client.get("/api/v1/hospital/overview", headers=auth(hospital))
    assert o.status_code == 200
    assert "beds_available" in o.json()["hospital"]
    cap = client.post("/api/v1/hospital/capacity", headers=auth(hospital),
                      json={"beds_delta": -1, "icu_delta": 0})
    assert cap.status_code == 200


def test_police_feed_and_close(client, police):
    o = client.get("/api/v1/police/overview", headers=auth(police))
    assert o.status_code == 200
    cases = o.json()["cases"]
    if cases:
        c = client.post(f"/api/v1/police/cases/{cases[0]['id']}/close",
                        headers=auth(police))
        assert c.status_code == 200
        assert c.json()["police_state"] == "closed"


def test_admin_analytics_and_reports(client, admin):
    a = client.get("/api/v1/admin/analytics", headers=auth(admin))
    assert a.status_code == 200
    assert len(a.json()["trend"]) == 7
    r = client.get("/api/v1/admin/reports", headers=auth(admin))
    assert r.status_code == 200
    assert len(r.json()["reports"]) == 4


def test_admin_can_disable_and_enable_user(client, admin):
    users = client.get("/api/v1/admin/users", headers=auth(admin)).json()["items"]
    target = next(u for u in users if u["email"] == "citizen@test.io")
    off = client.post(f"/api/v1/admin/users/{target['id']}/active",
                      headers=auth(admin), json={"is_active": False})
    assert off.status_code == 200
    # disabled user cannot log in
    r = client.post("/api/v1/auth/login",
                    json={"identifier": "citizen@test.io",
                          "password": "Jeevan@123"})
    assert r.status_code == 403
    client.post(f"/api/v1/admin/users/{target['id']}/active",
                headers=auth(admin), json={"is_active": True})
