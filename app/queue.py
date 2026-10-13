"""Hospital queue logic: daily token limits per department, 'how many ahead', 'your turn is near' calls.

Works for ANY hospital: tokens and limits are keyed by (hospital, department).
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, voice
from .models import Department, QueueToken


def day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def issued_today(db: Session, hospital: str, dept: str, now: datetime) -> int:
    return db.scalar(select(func.count()).select_from(QueueToken).where(
        QueueToken.hospital == hospital, QueueToken.department == dept,
        QueueToken.created_at >= day_start(now))) or 0


def limit_for(db: Session, hospital: str, dept: str) -> int | None:
    d = db.scalar(select(Department).where(Department.hospital == hospital, Department.name == dept))
    return d.daily_limit if d else None


def availability(db: Session, now: datetime, hospital: str | None = None, lang: str = "hi") -> list[dict]:
    q = select(Department).order_by(Department.hospital, Department.name)
    if hospital:
        q = q.where(Department.hospital == hospital)
    out = []
    for d in db.scalars(q).all():
        issued = issued_today(db, d.hospital, d.name, now)
        left = max(d.daily_limit - issued, 0)
        out.append({"hospital": d.hospital, "department": d.name, "daily_limit": d.daily_limit, "issued_today": issued,
                    "left": left, "full": left == 0, "say": voice.availability_script(d.hospital, d.name, left, lang)})
    return out


def ahead_count(db: Session, t: QueueToken, now: datetime) -> int:
    return db.scalar(select(func.count()).select_from(QueueToken).where(
        QueueToken.hospital == t.hospital, QueueToken.department == t.department,
        QueueToken.status == "waiting", QueueToken.token_no < t.token_no,
        QueueToken.created_at >= day_start(now))) or 0


def notify_near(db: Session, now: datetime, send) -> int:
    """Call every waiting patient (once) when few people remain ahead of them."""
    sent = 0
    waiting = db.scalars(select(QueueToken).where(
        QueueToken.status == "waiting", QueueToken.phone.is_not(None), QueueToken.notified.is_(False),
        QueueToken.created_at >= day_start(now))).all()
    for t in waiting:
        ahead = ahead_count(db, t, now)
        if ahead <= config.NOTIFY_AHEAD:
            send(db, None, "queue_near", "call", t.phone, voice.near_script(t.name, t.department, ahead, t.language), t.language, now)
            t.notified = True
            sent += 1
    return sent
