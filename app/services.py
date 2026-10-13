"""Core business logic: placing calls, reminder lifecycle, escalation, adherence."""
from datetime import datetime, timedelta

from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, nlp, queue, voice
from .models import CallLog, CheckSchedule, Medicine, Patient, Reading, Reminder

CALLS = Counter("sehat_calls_total", "Outgoing calls/SMS", ["kind", "channel"])
REMINDERS = Counter("sehat_reminders_total", "Reminder outcomes", ["status"])


def _send(db: Session, patient: Patient | None, kind: str, channel: str, phone: str, text: str, lang: str, now: datetime):
    provider = voice.get_provider()
    try:
        ok = provider.call(phone, text, lang) if channel == "call" else provider.sms(phone, text)
    except Exception:  # network/API failure must never crash the scheduler
        ok = False
    db.add(CallLog(patient_id=patient.id if patient else None, kind=kind, channel=channel,
                   to_phone=phone, language=lang, text=text, provider=provider.name, ok=ok, created_at=now))
    CALLS.labels(kind=kind, channel=channel).inc()
    return ok


def start_reminder(db: Session, med: Medicine, due: datetime, now: datetime) -> Reminder:
    pat = med.patient
    script = voice.build_reminder_script(pat, med)
    label = med.name + (f" {med.dose}" if med.dose else "")
    r = Reminder(patient_id=pat.id, medicine_id=med.id, kind="dose", label=label, due_at=due, status="called",
                 script=script, attempts=1, last_call_at=now)
    db.add(r)
    _send(db, pat, "reminder", "call", pat.phone, script, pat.language, now)
    REMINDERS.labels(status="called").inc()
    return r


def start_check(db: Session, chk: CheckSchedule, due: datetime, now: datetime) -> Reminder:
    pat = db.get(Patient, chk.patient_id)
    script = voice.build_check_script(pat, chk.kind)
    r = Reminder(patient_id=pat.id, check_id=chk.id, kind="check", label=f"{chk.kind.upper()} check", due_at=due,
                 status="called", script=script, attempts=1, last_call_at=now)
    db.add(r)
    _send(db, pat, "reminder", "call", pat.phone, script, pat.language, now)
    REMINDERS.labels(status="called").inc()
    return r


def escalate(db: Session, r: Reminder, now: datetime):
    r.status = "escalated"
    pat = r.patient
    if pat.family_phone:
        text = (voice.build_family_check_alert(pat, r.check.kind, r.due_at) if r.kind == "check" and r.check
                else voice.build_family_alert(pat, r.medicine, r.due_at))
        _send(db, pat, "family_alert", "sms", pat.family_phone, text, "en", now)
    REMINDERS.labels(status="escalated").inc()


def tick(db: Session, now: datetime | None = None) -> dict:
    """Run once a minute: start due reminders, retry unanswered ones, escalate to family."""
    now = now or config.now()
    stats = {"created": 0, "retried": 0, "escalated": 0}

    meds = db.scalars(select(Medicine).where(Medicine.active.is_(True), Medicine.confirmed_by.is_not(None))).all()
    for med in meds:
        for t in med.time_list():
            hh, mm = (int(x) for x in t.split(":"))
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due <= now < due + timedelta(minutes=config.REMINDER_WINDOW_MIN):
                exists = db.scalar(select(Reminder.id).where(Reminder.medicine_id == med.id, Reminder.due_at == due))
                if not exists:
                    start_reminder(db, med, due, now)
                    stats["created"] += 1

    checks = db.scalars(select(CheckSchedule).where(CheckSchedule.active.is_(True))).all()
    for chk in checks:
        for t in chk.time_list():
            hh, mm = (int(x) for x in t.split(":"))
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due <= now < due + timedelta(minutes=config.REMINDER_WINDOW_MIN):
                exists = db.scalar(select(Reminder.id).where(Reminder.check_id == chk.id, Reminder.due_at == due))
                if not exists:
                    start_check(db, chk, due, now)
                    stats["created"] += 1

    waiting = db.scalars(select(Reminder).where(Reminder.status == "called")).all()
    for r in waiting:
        if r.last_call_at and now - r.last_call_at >= timedelta(minutes=config.RETRY_MINUTES):
            if r.attempts < config.MAX_ATTEMPTS:
                r.attempts += 1
                r.last_call_at = now
                _send(db, r.patient, "reminder", "call", r.patient.phone, r.script, r.patient.language, now)
                stats["retried"] += 1
            else:
                escalate(db, r, now)
                stats["escalated"] += 1
    stats["queue_notified"] = queue.notify_near(db, now, _send)
    db.commit()
    return stats


def save_readings(db: Session, patient_id: int, items: list[dict], now: datetime | None = None) -> list[Reading]:
    now = now or config.now()
    saved = []
    for it in items:
        flag, reason = nlp.check_reading(it["kind"], it["value1"], it.get("value2"))
        rd = Reading(patient_id=patient_id, kind=it["kind"], value1=it["value1"], value2=it.get("value2"),
                     taken_at=now, flag=flag, flag_reason=reason)
        db.add(rd)
        saved.append(rd)
    return saved


def handle_response(db: Session, r: Reminder, text: str, now: datetime | None = None) -> dict:
    """Patient's spoken reply (already transcribed) to a reminder call."""
    now = now or config.now()
    r.response_text = text
    r.responded_at = now
    if r.kind == "check":
        items = nlp.parse_readings(text) or nlp.parse_bare_reading(r.check.kind if r.check else "", text)
        readings = save_readings(db, r.patient_id, items, now)
        if readings:
            r.status, answer = "taken", True  # reading received = done
        elif nlp.parse_yes_no(text) is False:
            r.status, answer = "missed", False
        else:
            answer = None  # could not hear a number: scheduler will ask again
        REMINDERS.labels(status=r.status).inc()
        db.commit()
        return {"understood": answer is not None, "status": r.status,
                "readings": [{"kind": x.kind, "value1": x.value1, "value2": x.value2, "flag": x.flag, "reason": x.flag_reason} for x in readings]}
    readings = save_readings(db, r.patient_id, nlp.parse_readings(text), now)
    answer = nlp.parse_yes_no(text)
    if answer is True:
        r.status = "taken"
    elif answer is False:
        r.status = "missed"
        _send(db, r.patient, "followup", "call", r.patient.phone,
              voice.build_followup_script(r.patient), r.patient.language, now)
    # answer is None -> keep status "called"; scheduler will retry
    REMINDERS.labels(status=r.status).inc()
    db.commit()
    return {
        "understood": answer is not None,
        "status": r.status,
        "readings": [{"kind": x.kind, "value1": x.value1, "value2": x.value2, "flag": x.flag, "reason": x.flag_reason} for x in readings],
    }


def adherence(db: Session, patient_id: int, days: int = 7, now: datetime | None = None) -> dict:
    now = now or config.now()
    since = now - timedelta(days=days)
    rows = db.scalars(select(Reminder).where(Reminder.patient_id == patient_id, Reminder.kind == "dose", Reminder.due_at >= since)).all()
    taken = sum(1 for r in rows if r.status == "taken")
    bad = sum(1 for r in rows if r.status in ("missed", "escalated"))
    done = taken + bad
    return {"taken": taken, "not_taken": bad, "pending": len(rows) - done,
            "percent": round(100 * taken / done) if done else None}
