"""Seed demo data: 5 role accounts, hospitals, ambulances, police, sample history.

Run:  python -m app.seed
Demo credentials (all): password `Jeevan@123`
  citizen@jeevan.app / driver@jeevan.app / hospital@jeevan.app
  police@jeevan.app  / admin@jeevan.app
"""
import datetime as dt

from .database import SessionLocal, init_db
from .models import (Ambulance, Emergency, EmergencyContact, Hospital,
                     Notification, PoliceUnit, User)
from .security import hash_password

PASSWORD = "Jeevan@123"


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == "admin@jeevan.app").first():
            print("Seed already present — skipping.")
            return

        users = {
            "citizen": User(name="Arjun Mehta", email="citizen@jeevan.app",
                            phone="+919000000001", role="citizen",
                            password_hash=hash_password(PASSWORD),
                            medical_profile="Blood type O+. Penicillin allergy."),
            "driver": User(name="Harpreet Singh", email="driver@jeevan.app",
                           phone="+919000000002", role="ambulance_driver",
                           password_hash=hash_password(PASSWORD)),
            "hospital": User(name="Civil Hospital Ludhiana", email="hospital@jeevan.app",
                             phone="+919000000003", role="hospital_staff",
                             password_hash=hash_password(PASSWORD)),
            "police": User(name="Insp. R. Kaur", email="police@jeevan.app",
                           phone="+919000000004", role="police_officer",
                           password_hash=hash_password(PASSWORD)),
            "admin": User(name="Platform Admin", email="admin@jeevan.app",
                          phone="+919000000005", role="administrator",
                          password_hash=hash_password(PASSWORD)),
        }
        db.add_all(users.values())
        db.commit()

        db.add_all([
            EmergencyContact(owner_id=users["citizen"].id, name="Simran Mehta",
                             phone="+919800000011", relation="Spouse"),
            EmergencyContact(owner_id=users["citizen"].id, name="Vikram Mehta",
                             phone="+919800000012", relation="Brother"),
        ])

        hosp = Hospital(name="Civil Hospital Ludhiana", latitude=30.9114,
                        longitude=75.8473, icu_total=12, icu_available=5,
                        beds_total=60, beds_available=18)
        hosp2 = Hospital(name="DMCH Hospital", latitude=30.9245, longitude=75.8349,
                         icu_total=16, icu_available=9, beds_total=80,
                         beds_available=31)
        db.add_all([hosp, hosp2])

        amb1 = Ambulance(code="PB-01-AMB-112", driver_id=users["driver"].id,
                         online=True, status="available",
                         latitude=30.9089, longitude=75.8538)
        amb2 = Ambulance(code="PB-01-AMB-208", online=True, status="available",
                         latitude=30.9320, longitude=75.8210)
        amb3 = Ambulance(code="PB-01-AMB-305", online=False, status="offline",
                         latitude=30.8852, longitude=75.8901)
        db.add_all([amb1, amb2, amb3])
        db.add(PoliceUnit(code="PS-MODEL-TOWN", station="Model Town PS",
                          latitude=30.9165, longitude=75.8560))
        db.add(PoliceUnit(code="PS-SARABHA", station="Sarabha Nagar PS",
                          latitude=30.9065, longitude=75.8210))

        now = dt.datetime.utcnow()
        for i, (days, sev) in enumerate([(6, "high"), (4, "medium"),
                                         (2, "critical"), (1, "low")]):
            created = now - dt.timedelta(days=days, hours=i)
            db.add(Emergency(source="citizen_sos", status="completed",
                             severity=sev, latitude=30.90 + i * 0.004,
                             longitude=75.85 + i * 0.003, user_id=users["citizen"].id,
                             created_at=created, resolved_at=created + dt.timedelta(minutes=18 + i * 7),
                             police_state="closed"))
        db.add(Emergency(source="cctv_ai", status="completed", severity="high",
                         latitude=30.9205, longitude=75.8400, cctv_id=None,
                         created_at=now - dt.timedelta(days=3),
                         resolved_at=now - dt.timedelta(days=3, minutes=-25),
                         police_state="closed", note="Seeded CCTV detection"))

        db.add(Notification(role="citizen", title="Welcome to JEEVAN",
                            body="Your emergency profile is active. Add contacts in Profile."))
        db.add(Notification(role="administrator", title="System seeded",
                            body="Demo hospitals, ambulances and users created."))
        db.commit()
        print("Seed complete: 5 users, 2 hospitals, 3 ambulances, 2 police units, 5 sample emergencies")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
