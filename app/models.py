import json
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import config
from .db import Base


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(5), default="hi")  # hi | pa | en
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    family_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=config.now)
    medicines: Mapped[list["Medicine"]] = relationship(back_populates="patient")


class Medicine(Base):
    __tablename__ = "medicines"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    name: Mapped[str] = mapped_column(String(120))
    dose: Mapped[str | None] = mapped_column(String(60), nullable=True)
    times: Mapped[str] = mapped_column(String(60))  # "08:00,21:00"
    food: Mapped[str | None] = mapped_column(String(20), nullable=True)  # before | after | None
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Safety: reminders only start once a doctor/pharmacist confirms the schedule.
    confirmed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    patient: Mapped[Patient] = relationship(back_populates="medicines")

    def time_list(self) -> list[str]:
        return [t.strip() for t in self.times.split(",") if t.strip()]


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    medicine_id: Mapped[int | None] = mapped_column(ForeignKey("medicines.id"), nullable=True)
    check_id: Mapped[int | None] = mapped_column(ForeignKey("check_schedules.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default="dose")  # dose | check (sugar/BP reading)
    label: Mapped[str] = mapped_column(String(160), default="")
    due_at: Mapped[datetime] = mapped_column(DateTime)
    # called -> taken | missed | escalated
    status: Mapped[str] = mapped_column(String(20), default="called")
    script: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_call_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    patient: Mapped[Patient] = relationship()
    medicine: Mapped["Medicine | None"] = relationship()
    check: Mapped["CheckSchedule | None"] = relationship()


class CheckSchedule(Base):
    """'Please measure your sugar / BP now and tell me the number' reminders."""

    __tablename__ = "check_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    kind: Mapped[str] = mapped_column(String(10))  # sugar | bp
    times: Mapped[str] = mapped_column(String(60))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    set_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    def time_list(self) -> list[str]:
        return [t.strip() for t in self.times.split(",") if t.strip()]


class Reading(Base):
    __tablename__ = "readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    kind: Mapped[str] = mapped_column(String(10))  # sugar | bp
    value1: Mapped[int] = mapped_column(Integer)  # sugar mg/dL, or systolic
    value2: Mapped[int | None] = mapped_column(Integer, nullable=True)  # diastolic
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=config.now)
    flag: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Summary(Base):
    """What the patient said at home, packaged for the doctor."""

    __tablename__ = "summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    code: Mapped[str] = mapped_column(String(10), unique=True)
    raw_text: Mapped[str] = mapped_column(Text)
    detected: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of strings
    created_at: Mapped[datetime] = mapped_column(DateTime, default=config.now)

    def detected_list(self) -> list[str]:
        return json.loads(self.detected or "[]")


class Department(Base):
    """A department of a hospital with a daily token limit (any hospital, not just one)."""

    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    hospital: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(60))
    daily_limit: Mapped[int] = mapped_column(Integer)


class QueueToken(Base):
    __tablename__ = "queue_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    hospital: Mapped[str] = mapped_column(String(120), default=config.DEFAULT_HOSPITAL)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="hi")
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    department: Mapped[str] = mapped_column(String(60), default="General OPD")
    status: Mapped[str] = mapped_column(String(10), default="waiting")  # waiting | called | done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=config.now)


class Stock(Base):
    __tablename__ = "stock"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    batch: Mapped[str | None] = mapped_column(String(60), nullable=True)
    expiry: Mapped[date] = mapped_column(Date)
    qty: Mapped[int] = mapped_column(Integer, default=0)


class CallLog(Base):
    """Every outgoing call/SMS (mock or real). The dashboard shows this as the 'phone'."""

    __tablename__ = "call_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # reminder | followup | family_alert
    channel: Mapped[str] = mapped_column(String(10), default="call")  # call | sms
    to_phone: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(5), default="hi")
    text: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(20), default="mock")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=config.now)
