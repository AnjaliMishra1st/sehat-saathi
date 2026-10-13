import io
import json
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import qrcode
import qrcode.image.svg
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, gnani, nlp, queue, services, voice
from .db import SessionLocal, get_db, init_db
from .models import (CallLog, CheckSchedule, Department, Medicine, Patient, QueueToken, Reading, Reminder,
                     Stock, Summary)

STATIC = Path(__file__).parent / "static"
scheduler = BackgroundScheduler(timezone=str(config.TZ))


def _scheduled_tick():
    db = SessionLocal()
    try:
        services.tick(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if config.ENABLE_SCHEDULER:
        scheduler.add_job(_scheduled_tick, "interval", seconds=60, id="tick", replace_existing=True)
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Sehat Saathi", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- schemas ----------
class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=5, max_length=20)
    language: str = "hi"
    age: int | None = None
    family_name: str | None = None
    family_phone: str | None = None

    @field_validator("language")
    @classmethod
    def _lang(cls, v):
        if v not in ("hi", "pa", "en"):
            raise ValueError("language must be hi, pa or en")
        return v


class MedicineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dose: str | None = None
    times: list[str] = Field(min_length=1)  # ["08:00", "21:00"]
    food: str | None = None  # before | after

    @field_validator("times")
    @classmethod
    def _times(cls, v):
        for t in v:
            try:
                datetime.strptime(t, "%H:%M")
            except ValueError:
                raise ValueError(f"time '{t}' must look like HH:MM (24h)")
        return v

    @field_validator("food")
    @classmethod
    def _food(cls, v):
        if v not in (None, "", "before", "after"):
            raise ValueError("food must be before, after or empty")
        return v or None


class ConfirmIn(BaseModel):
    by: str = Field(min_length=1, description="Doctor / pharmacist name")


class TextIn(BaseModel):
    text: str = Field(min_length=1)


class TriggerIn(BaseModel):
    medicine_id: int


class TickIn(BaseModel):
    now: datetime | None = None
    advance_minutes: int | None = None  # demo: pretend N minutes passed


class QueueIn(BaseModel):
    name: str = Field(min_length=1)
    hospital: str = config.DEFAULT_HOSPITAL
    department: str = "General OPD"
    phone: str | None = None  # optional: lets the system call when the turn is near
    language: str = "hi"

    @field_validator("language")
    @classmethod
    def _lang(cls, v):
        if v not in ("hi", "pa", "en"):
            raise ValueError("language must be hi, pa or en")
        return v


class DeptIn(BaseModel):
    hospital: str = Field(min_length=1)
    name: str = Field(min_length=1)
    daily_limit: int = Field(ge=1, le=5000)


class CheckIn(BaseModel):
    kind: str  # sugar | bp
    times: list[str] = Field(min_length=1)
    set_by: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in ("sugar", "bp"):
            raise ValueError("kind must be sugar or bp")
        return v

    @field_validator("times")
    @classmethod
    def _times(cls, v):
        for t in v:
            try:
                datetime.strptime(t, "%H:%M")
            except ValueError:
                raise ValueError(f"time '{t}' must look like HH:MM (24h)")
        return v


class CheckTriggerIn(BaseModel):
    check_id: int


class StockIn(BaseModel):
    name: str = Field(min_length=1)
    batch: str | None = None
    expiry: date
    qty: int = 0


# ---------- helpers ----------
def _patient_or_404(db: Session, pid: int) -> Patient:
    p = db.get(Patient, pid)
    if not p:
        raise HTTPException(404, "Patient not found")
    return p


def _med_dict(m: Medicine) -> dict:
    return {"id": m.id, "patient_id": m.patient_id, "name": m.name, "dose": m.dose, "times": m.time_list(),
            "food": m.food, "active": m.active, "confirmed_by": m.confirmed_by}


def _reminder_dict(r: Reminder) -> dict:
    return {"id": r.id, "patient_id": r.patient_id, "patient": r.patient.name, "language": r.patient.language,
            "kind": r.kind, "medicine": r.label or (r.medicine.name if r.medicine else ""),
            "dose": None if r.kind == "check" or not r.medicine else r.medicine.dose, "due_at": r.due_at.isoformat(timespec="minutes"),
            "status": r.status, "attempts": r.attempts, "script": r.script, "response_text": r.response_text}


# ---------- system ----------
@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "gnani_voice": gnani.enabled(), "time": config.now().isoformat(timespec="seconds")}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


# ---------- patients & medicines ----------
@app.post("/api/patients", status_code=201)
def create_patient(body: PatientIn, db: Session = Depends(get_db)):
    p = Patient(**body.model_dump())
    db.add(p)
    db.commit()
    return {"id": p.id, "name": p.name}


@app.get("/api/patients")
def list_patients(db: Session = Depends(get_db)):
    out = []
    for p in db.scalars(select(Patient).order_by(Patient.id)).all():
        last_flag = db.scalar(select(Reading).where(Reading.patient_id == p.id, Reading.flag.is_(True))
                              .order_by(Reading.taken_at.desc()))
        out.append({"id": p.id, "name": p.name, "phone": p.phone, "language": p.language, "age": p.age,
                    "family_name": p.family_name, "family_phone": p.family_phone,
                    "adherence": services.adherence(db, p.id),
                    "medicines": [_med_dict(m) for m in p.medicines],
                    "checks": [{"id": c.id, "kind": c.kind, "times": c.time_list()} for c in
                               db.scalars(select(CheckSchedule).where(CheckSchedule.patient_id == p.id, CheckSchedule.active.is_(True))).all()],
                    "latest_flag": last_flag.flag_reason if last_flag else None})
    return out


@app.post("/api/patients/{pid}/medicines", status_code=201)
def add_medicine(pid: int, body: MedicineIn, db: Session = Depends(get_db)):
    _patient_or_404(db, pid)
    m = Medicine(patient_id=pid, name=body.name, dose=body.dose, times=",".join(body.times), food=body.food)
    db.add(m)
    db.commit()
    return _med_dict(m)  # confirmed_by is None -> no reminders yet


@app.post("/api/medicines/{mid}/confirm")
def confirm_medicine(mid: int, body: ConfirmIn, db: Session = Depends(get_db)):
    m = db.get(Medicine, mid)
    if not m:
        raise HTTPException(404, "Medicine not found")
    m.confirmed_by = body.by
    db.commit()
    return _med_dict(m)


# ---------- Gnani voice (real speech) ----------
class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    lang: str = "hi"


@app.get("/api/voice/status")
def voice_status():
    return {"gnani": gnani.enabled()}


@app.post("/api/voice/tts")
async def voice_tts(body: TTSIn):
    """Text -> real speech (Gnani Timbre). The dashboard plays this as the 'phone call' audio."""
    if not gnani.enabled():
        raise HTTPException(503, "GNANI_API_KEY is not set")
    try:
        audio = await run_in_threadpool(gnani.synthesize, body.text, body.lang)
    except gnani.GnaniError as e:
        raise HTTPException(502, str(e))
    return Response(audio, media_type="audio/wav")


@app.post("/api/voice/stt")
async def voice_stt(request: Request, lang: str = "hi"):
    """Audio bytes in the request body (WAV, up to 60 s) -> transcript (Gnani Prisma)."""
    if not gnani.enabled():
        raise HTTPException(503, "GNANI_API_KEY is not set")
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "Empty audio")
    try:
        text = await run_in_threadpool(gnani.transcribe, audio, lang)
    except gnani.GnaniError as e:
        raise HTTPException(502, str(e))
    return {"transcript": text}


@app.post("/api/reminders/{rid}/voice-reply")
async def reminder_voice_reply(rid: int, request: Request, db: Session = Depends(get_db)):
    """The patient's spoken reply (WAV in the body): speech-to-text, then the normal reminder logic."""
    r = db.get(Reminder, rid)
    if not r:
        raise HTTPException(404, "Reminder not found")
    if not gnani.enabled():
        raise HTTPException(503, "GNANI_API_KEY is not set")
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "Empty audio")
    try:
        text = await run_in_threadpool(gnani.transcribe, audio, r.patient.language)
    except gnani.GnaniError as e:
        raise HTTPException(502, str(e))
    if not text:
        return {"transcript": "", "result": {"understood": False, "status": r.status, "readings": []}}
    return {"transcript": text, "result": services.handle_response(db, r, text)}


# ---------- sugar / BP check reminders ----------
@app.post("/api/patients/{pid}/checks", status_code=201)
def add_check(pid: int, body: CheckIn, db: Session = Depends(get_db)):
    _patient_or_404(db, pid)
    c = CheckSchedule(patient_id=pid, kind=body.kind, times=",".join(body.times), set_by=body.set_by)
    db.add(c)
    db.commit()
    return {"id": c.id, "kind": c.kind, "times": c.time_list()}


@app.post("/api/checks/trigger", status_code=201)
def trigger_check(body: CheckTriggerIn, db: Session = Depends(get_db)):
    """Demo helper: ask for a sugar/BP reading right now."""
    c = db.get(CheckSchedule, body.check_id)
    if not c:
        raise HTTPException(404, "Check not found")
    now = config.now()
    r = services.start_check(db, c, now.replace(second=0, microsecond=0), now)
    db.commit()
    return _reminder_dict(r)


# ---------- reminders ----------
@app.get("/api/reminders")
def list_reminders(status: str | None = None, db: Session = Depends(get_db)):
    q = select(Reminder).order_by(Reminder.due_at.desc(), Reminder.id.desc()).limit(100)
    if status:
        q = q.where(Reminder.status == status)
    return [_reminder_dict(r) for r in db.scalars(q).all()]


@app.post("/api/reminders/trigger", status_code=201)
def trigger_reminder(body: TriggerIn, db: Session = Depends(get_db)):
    """Demo helper: fire a reminder call right now for a confirmed medicine."""
    m = db.get(Medicine, body.medicine_id)
    if not m:
        raise HTTPException(404, "Medicine not found")
    if not m.confirmed_by:
        raise HTTPException(409, "Schedule not confirmed by a doctor/pharmacist yet")
    now = config.now()
    r = services.start_reminder(db, m, now.replace(second=0, microsecond=0), now)
    db.commit()
    return _reminder_dict(r)


@app.post("/api/reminders/{rid}/response")
def reminder_response(rid: int, body: TextIn, db: Session = Depends(get_db)):
    r = db.get(Reminder, rid)
    if not r:
        raise HTTPException(404, "Reminder not found")
    return services.handle_response(db, r, body.text)


@app.post("/api/scheduler/tick")
def manual_tick(body: TickIn | None = None, db: Session = Depends(get_db)):
    """Run the scheduler once. `advance_minutes` lets you demo retry/escalation without waiting."""
    body = body or TickIn()
    now = body.now or config.now() + timedelta(minutes=body.advance_minutes or 0)
    return services.tick(db, now)


# ---------- readings ----------
@app.post("/api/patients/{pid}/readings", status_code=201)
def add_readings(pid: int, body: TextIn, db: Session = Depends(get_db)):
    _patient_or_404(db, pid)
    items = nlp.parse_readings(body.text)
    if not items:
        raise HTTPException(422, "Could not find a sugar or BP reading. Try: 'sugar 180' or 'bp 140/90'")
    saved = services.save_readings(db, pid, items)
    db.commit()
    return [{"kind": r.kind, "value1": r.value1, "value2": r.value2, "flag": r.flag, "reason": r.flag_reason} for r in saved]


@app.get("/api/patients/{pid}/readings")
def get_readings(pid: int, db: Session = Depends(get_db)):
    rows = db.scalars(select(Reading).where(Reading.patient_id == pid).order_by(Reading.taken_at.desc()).limit(30)).all()
    return [{"kind": r.kind, "value1": r.value1, "value2": r.value2, "taken_at": r.taken_at.isoformat(timespec="minutes"),
             "flag": r.flag, "reason": r.flag_reason} for r in rows]


# ---------- pre-visit summary ("Meri Baat Doctor Tak") ----------
@app.post("/api/patients/{pid}/summary", status_code=201)
def create_summary(pid: int, body: TextIn, db: Session = Depends(get_db)):
    _patient_or_404(db, pid)
    detected = nlp.extract_symptoms(body.text)
    if nlp.looks_urgent(body.text):
        detected.insert(0, "URGENT WORDS MENTIONED (chest / breathing): please see this patient first")
    s = Summary(patient_id=pid, code=secrets.token_hex(3).upper(), raw_text=body.text, detected=json.dumps(detected))
    db.add(s)
    db.commit()
    return {"code": s.code, "url": f"/s/{s.code}", "qr": f"/s/{s.code}/qr.svg", "detected": detected}


@app.get("/s/{code}/qr.svg")
def summary_qr(code: str, request: Request):
    url = str(request.base_url).rstrip("/") + f"/s/{code}"
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.get("/s/{code}", response_class=HTMLResponse)
def summary_page(code: str, db: Session = Depends(get_db)):
    """One-page doctor view: scan QR, read in 10 seconds."""
    s = db.scalar(select(Summary).where(Summary.code == code.upper()))
    if not s:
        raise HTTPException(404, "Summary not found")
    p = db.get(Patient, s.patient_id)
    meds = [m for m in p.medicines if m.active]
    readings = db.scalars(select(Reading).where(Reading.patient_id == p.id).order_by(Reading.taken_at.desc()).limit(8)).all()
    adh = services.adherence(db, p.id)
    esc = lambda t: (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    det = "".join(f"<li{' class=urgent' if x.startswith('URGENT') else ''}>{esc(x)}</li>" for x in s.detected_list()) or "<li>Nothing specific detected, read the patient's words above</li>"
    med_rows = "".join(
        f"<tr><td>{esc(m.name)} {esc(m.dose)}</td><td>{', '.join(m.time_list())}</td><td>{esc(m.food) or ''}</td>"
        f"<td>{'confirmed by ' + esc(m.confirmed_by) if m.confirmed_by else 'not confirmed'}</td></tr>" for m in meds
    ) or "<tr><td colspan=4>No medicines on file</td></tr>"
    rd_rows = "".join(
        f"<tr class={'flag' if r.flag else ''}><td>{r.taken_at:%d %b %H:%M}</td><td>{r.kind}</td>"
        f"<td>{r.value1}{('/' + str(r.value2)) if r.value2 else ''}</td><td>{esc(r.flag_reason) or ''}</td></tr>" for r in readings
    ) or "<tr><td colspan=4>No readings yet</td></tr>"
    pct = f"{adh['percent']}%" if adh["percent"] is not None else "n/a"
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Patient summary {s.code}</title><style>
body{{font:16px/1.5 "Noto Sans","Segoe UI",system-ui,sans-serif;max-width:720px;margin:0 auto;padding:20px;color:#14262b}}
h1{{font-size:1.4rem;margin:0}} h2{{font-size:1rem;margin:1.4rem 0 .4rem;color:#0f5c5c}}
.said{{background:#eef4f3;border-left:4px solid #0f5c5c;padding:12px 14px;border-radius:4px;font-size:1.05rem}}
table{{border-collapse:collapse;width:100%}} td,th{{padding:6px 8px;border-bottom:1px solid #d9e3e1;text-align:left}}
tr.flag td{{background:#fdecea;color:#8c1d18;font-weight:600}} li.urgent{{color:#b3261e;font-weight:700}}
.note{{font-size:.85rem;color:#5b6d70;margin-top:1.6rem}}</style></head><body>
<h1>{esc(p.name)}{f', {p.age} yrs' if p.age else ''}</h1><div>Summary code {s.code}, {s.created_at:%d %b %Y %H:%M}</div>
<h2>Patient said (own words)</h2><div class=said>{esc(s.raw_text)}</div>
<h2>Picked out from it</h2><ul>{det}</ul>
<h2>Current medicines</h2><table><tr><th>Medicine</th><th>Times</th><th>Food</th><th>Schedule</th></tr>{med_rows}</table>
<h2>Recent sugar / BP</h2><table><tr><th>When</th><th>Type</th><th>Value</th><th>Flag</th></tr>{rd_rows}</table>
<h2>Last 7 days: medicines taken</h2><div>{pct} ({adh['taken']} taken, {adh['not_taken']} missed or unanswered)</div>
<p class=note>Auto-generated from the patient's own words and logged readings. It is not a diagnosis.
Flag limits are hospital-configurable placeholders. The doctor decides all treatment.</p></body></html>"""


# ---------- "Doctor ki baat": consult text -> schedule draft -> doctor confirms ----------
class ConsultItem(BaseModel):
    name: str = Field(min_length=1)
    dose: str | None = None
    times: list[str] = []
    food: str | None = None
    as_needed: bool = False

    @field_validator("times")
    @classmethod
    def _t(cls, v):
        for t in v:
            datetime.strptime(t, "%H:%M")
        return v


class ConsultConfirmIn(BaseModel):
    by: str = Field(min_length=1, description="Doctor / pharmacist name")
    items: list[ConsultItem]


@app.post("/api/patients/{pid}/consult")
def consult_draft(pid: int, body: TextIn, db: Session = Depends(get_db)):
    """Turn what the doctor said into a DRAFT schedule. Nothing is saved until confirmed."""
    _patient_or_404(db, pid)
    drafts = nlp.parse_consult(body.text)
    if not drafts:
        raise HTTPException(422, "No medicine found. Try: 'Amlodipine subah ek goli khane ke baad'")
    return {"drafts": drafts, "note": "Draft only. Doctor must review and confirm."}


@app.post("/api/patients/{pid}/consult/confirm", status_code=201)
def consult_confirm(pid: int, body: ConsultConfirmIn, db: Session = Depends(get_db)):
    _patient_or_404(db, pid)
    made = []
    for it in body.items:
        if it.as_needed or not it.times:
            continue  # nothing to remind for 'only when needed' medicines
        m = Medicine(patient_id=pid, name=it.name, dose=it.dose, times=",".join(it.times),
                     food=it.food or None, confirmed_by=body.by)
        db.add(m)
        made.append(m)
    db.commit()
    return {"created": [_med_dict(m) for m in made]}


# ---------- hospital queue: limits, availability, 'how many ahead' (any hospital) ----------
@app.post("/api/departments", status_code=201)
def set_department(body: DeptIn, db: Session = Depends(get_db)):
    """Create a department or change its daily token limit."""
    d = db.scalar(select(Department).where(Department.hospital == body.hospital, Department.name == body.name))
    if d:
        d.daily_limit = body.daily_limit
    else:
        d = Department(hospital=body.hospital, name=body.name, daily_limit=body.daily_limit)
        db.add(d)
    db.commit()
    return {"hospital": d.hospital, "department": d.name, "daily_limit": d.daily_limit}


@app.get("/api/availability")
def get_availability(hospital: str | None = None, lang: str = "hi", db: Session = Depends(get_db)):
    """'How many tokens are left today?' Patients ask this BEFORE travelling."""
    return queue.availability(db, config.now(), hospital, lang)


@app.post("/api/queue", status_code=201)
def add_to_queue(body: QueueIn, db: Session = Depends(get_db)):
    now = config.now()
    limit = queue.limit_for(db, body.hospital, body.department)
    issued = queue.issued_today(db, body.hospital, body.department, now)
    if limit is not None and issued >= limit:
        raise HTTPException(409, f"Today's limit ({limit}) for {body.department} at {body.hospital} is full. Please come tomorrow.")
    last = db.scalar(select(func.max(QueueToken.token_no)).where(
        QueueToken.hospital == body.hospital, QueueToken.department == body.department,
        QueueToken.created_at >= queue.day_start(now))) or 0
    t = QueueToken(token_no=last + 1, name=body.name, hospital=body.hospital, department=body.department,
                   phone=body.phone, language=body.language, created_at=now)
    db.add(t)
    db.commit()
    ahead = queue.ahead_count(db, t, now)
    return {"id": t.id, "token_no": t.token_no, "hospital": t.hospital, "department": t.department, "ahead": ahead,
            "say": voice.ahead_script(t.token_no, ahead, t.language)}


@app.get("/api/queue")
def get_queue(hospital: str | None = None, db: Session = Depends(get_db)):
    today = queue.day_start(config.now())
    q = select(QueueToken).where(QueueToken.created_at >= today).order_by(QueueToken.hospital, QueueToken.department, QueueToken.token_no)
    if hospital:
        q = q.where(QueueToken.hospital == hospital)
    return [{"id": t.id, "token_no": t.token_no, "name": t.name, "hospital": t.hospital, "department": t.department,
             "status": t.status, "notified": t.notified} for t in db.scalars(q).all()]


@app.get("/api/queue/status")
def queue_status(token_no: int, department: str = "General OPD", hospital: str = config.DEFAULT_HOSPITAL,
                 lang: str = "hi", db: Session = Depends(get_db)):
    """'How many people are ahead of me?' (works from a phone call too)."""
    now = config.now()
    t = db.scalar(select(QueueToken).where(
        QueueToken.hospital == hospital, QueueToken.department == department, QueueToken.token_no == token_no,
        QueueToken.created_at >= queue.day_start(now)))
    if not t:
        raise HTTPException(404, "Token not found for today")
    ahead = queue.ahead_count(db, t, now) if t.status == "waiting" else 0
    return {"token_no": t.token_no, "status": t.status, "ahead": ahead, "say": voice.ahead_script(t.token_no, ahead, lang)}


@app.post("/api/queue/next")
def call_next(body: dict, db: Session = Depends(get_db)):
    dept = body.get("department", "General OPD")
    hosp = body.get("hospital", config.DEFAULT_HOSPITAL)
    for t in db.scalars(select(QueueToken).where(QueueToken.hospital == hosp, QueueToken.department == dept,
                                                  QueueToken.status == "called")).all():
        t.status = "done"
    nxt = db.scalar(select(QueueToken).where(QueueToken.hospital == hosp, QueueToken.department == dept,
                                             QueueToken.status == "waiting").order_by(QueueToken.token_no))
    if not nxt:
        db.commit()
        return {"called": None}
    nxt.status = "called"
    db.commit()
    return {"called": {"token_no": nxt.token_no, "name": nxt.name}}


# ---------- medical shop stock / expiry ----------
@app.post("/api/stock", status_code=201)
def add_stock(body: StockIn, db: Session = Depends(get_db)):
    s = Stock(**body.model_dump())
    db.add(s)
    db.commit()
    return {"id": s.id}


@app.get("/api/stock")
def list_stock(days: int = 60, db: Session = Depends(get_db)):
    today = config.now().date()
    out = []
    for s in db.scalars(select(Stock).order_by(Stock.expiry)).all():
        left = (s.expiry - today).days
        state = "expired" if left < 0 else "expiring" if left <= days else "ok"
        out.append({"id": s.id, "name": s.name, "batch": s.batch, "expiry": s.expiry.isoformat(), "qty": s.qty,
                    "days_left": left, "state": state})
    return out


# ---------- phone log, dashboard, demo ----------
@app.get("/api/calls")
def list_calls(db: Session = Depends(get_db)):
    rows = db.scalars(select(CallLog).order_by(CallLog.id.desc()).limit(40)).all()
    names = {p.id: p.name for p in db.scalars(select(Patient)).all()}
    return [{"id": c.id, "patient": names.get(c.patient_id), "kind": c.kind, "channel": c.channel, "to": c.to_phone,
             "language": c.language, "text": c.text, "provider": c.provider, "ok": c.ok,
             "at": c.created_at.isoformat(timespec="seconds")} for c in rows]


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    today = config.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rem = db.scalars(select(Reminder).where(Reminder.due_at >= today)).all()
    count = lambda s: sum(1 for r in rem if r.status == s)
    flags = db.scalars(select(Reading).where(Reading.flag.is_(True), Reading.taken_at >= today - timedelta(days=1))).all()
    expiring = [s for s in db.scalars(select(Stock)).all() if (s.expiry - config.now().date()).days <= 60]
    waiting = db.scalar(select(func.count()).select_from(QueueToken).where(QueueToken.status == "waiting", QueueToken.created_at >= today))
    return {"patients": db.scalar(select(func.count()).select_from(Patient)),
            "today": {"called": count("called"), "taken": count("taken"), "missed": count("missed"), "escalated": count("escalated")},
            "flagged_readings": len(flags), "expiring_stock": len(expiring), "queue_waiting": waiting}


@app.post("/api/demo/seed")
def seed(db: Session = Depends(get_db)):
    """Loads DUMMY patients/medicines/stock/queue. Never put real patient data in a demo."""
    from .seed import load_demo

    return load_demo(db)
