"""Dummy demo data. All names and numbers are fictional."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import CheckSchedule, Department, Medicine, Patient, QueueToken, Stock


def load_demo(db: Session) -> dict:
    if db.scalar(select(Patient.id)):
        return {"seeded": False, "reason": "data already present"}
    today = config.now().date()

    dadi = Patient(name="Gurmeet Kaur", phone="+910000000001", language="pa", age=68,
                   family_name="Harpreet", family_phone="+910000000002")
    ram = Patient(name="Ramesh Sharma", phone="+910000000003", language="hi", age=55,
                  family_name="Sunita", family_phone="+910000000004")
    db.add_all([dadi, ram])
    db.flush()

    # Times are set around "now" so the demo shows a due reminder straight away.
    t1 = config.now().strftime("%H:%M")
    meds = [
        Medicine(patient_id=dadi.id, name="Amlodipine", dose="5 mg", times=f"08:00,{t1}", food="after", confirmed_by="Dr. Demo"),
        Medicine(patient_id=dadi.id, name="Metformin", dose="500 mg", times="08:30,20:30", food="after", confirmed_by="Dr. Demo"),
        Medicine(patient_id=ram.id, name="Telmisartan", dose="40 mg", times=f"09:00,{t1}", food=None, confirmed_by="Dr. Demo"),
        Medicine(patient_id=ram.id, name="Atorvastatin", dose="10 mg", times="21:00", food="after", confirmed_by=None),  # awaiting confirmation
    ]
    db.add_all(meds)

    db.add_all([
        Stock(name="Paracetamol 500", batch="PC2201", expiry=today + timedelta(days=25), qty=120),
        Stock(name="Metformin 500", batch="MF1109", expiry=today + timedelta(days=210), qty=300),
        Stock(name="Cetirizine 10", batch="CT0987", expiry=today - timedelta(days=5), qty=40),
        Stock(name="ORS sachet", batch="OR5521", expiry=today + timedelta(days=55), qty=80),
    ])
    # Two demo hospitals. Civil Hospital: Medicine OPD has 6 tokens left. District Hospital: Medicine OPD is FULL.
    civil, district = "Civil Hospital Demo", "District Hospital Demo"
    db.add_all([
        Department(hospital=civil, name="Medicine OPD", daily_limit=20),
        Department(hospital=civil, name="Skin OPD", daily_limit=30),
        Department(hospital=district, name="Medicine OPD", daily_limit=15),
    ])
    names = ["Baljeet Singh", "Kamla Devi", "Rohan Verma", "Sunita Rani", "Manjit Kaur", "Amit Kumar", "Seema Devi",
             "Harjeet Singh", "Pooja Sharma", "Gurdeep Singh", "Anita Rani", "Vikas Yadav", "Rajni Bala", "Sohan Lal"]
    for i, n in enumerate(names, start=1):          # 14 waiting at Civil Hospital Medicine OPD
        db.add(QueueToken(token_no=i, name=n, hospital=civil, department="Medicine OPD"))
    for i in range(1, 16):                          # 15 issued at District Hospital: full
        db.add(QueueToken(token_no=i, name=f"Demo Patient {i}", hospital=district, department="Medicine OPD"))
    db.add_all([
        CheckSchedule(patient_id=dadi.id, kind="sugar", times=f"07:30,{t1}", set_by="Dr. Demo"),
        CheckSchedule(patient_id=ram.id, kind="bp", times=f"07:30,{t1}", set_by="Dr. Demo"),
    ])
    db.commit()
    return {"seeded": True, "patients": 2, "medicines": 4}
