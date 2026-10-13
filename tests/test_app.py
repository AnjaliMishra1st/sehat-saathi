import os

os.environ["DATABASE_URL"] = "sqlite:///./test_sehat.db"
os.environ["ENABLE_SCHEDULER"] = "false"

import pytest
from fastapi.testclient import TestClient

from app import nlp
from app.db import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


def make_patient(c, **kw):
    body = {"name": "Test Dadi", "phone": "+910000000001", "language": "hi", "family_name": "Raj", "family_phone": "+910000000002"}
    body.update(kw)
    return c.post("/api/patients", json=body).json()["id"]


def test_yes_no_parsing():
    assert nlp.parse_yes_no("haan li") is True
    assert nlp.parse_yes_no("nahi li") is False  # negative wins over 'li'
    assert nlp.parse_yes_no("नहीं") is False
    assert nlp.parse_yes_no("ਹਾਂ ਜੀ ਲਈ") is True
    assert nlp.parse_yes_no("pata nahi kya") is False
    assert nlp.parse_yes_no("hmm") is None


def test_reading_parsing_and_flags():
    r = nlp.parse_readings("aaj sugar 280 aur bp 150/95 tha")
    assert {"kind": "sugar", "value1": 280, "value2": None} in r
    assert {"kind": "bp", "value1": 150, "value2": 95} in r
    assert nlp.check_reading("sugar", 280, None)[0] is True
    assert nlp.check_reading("sugar", 120, None)[0] is False
    assert nlp.check_reading("bp", 170, 100)[0] is True


def test_unconfirmed_medicine_gets_no_reminder(client):
    pid = make_patient(client)
    mid = client.post(f"/api/patients/{pid}/medicines", json={"name": "Amlodipine", "times": ["08:00"]}).json()["id"]
    assert client.post("/api/reminders/trigger", json={"medicine_id": mid}).status_code == 409
    client.post(f"/api/medicines/{mid}/confirm", json={"by": "Dr X"})
    assert client.post("/api/reminders/trigger", json={"medicine_id": mid}).status_code == 201


def test_full_loop_taken_and_flag(client):
    pid = make_patient(client)
    mid = client.post(f"/api/patients/{pid}/medicines", json={"name": "Metformin", "times": ["08:00"], "food": "after"}).json()["id"]
    client.post(f"/api/medicines/{mid}/confirm", json={"by": "Dr X"})
    rid = client.post("/api/reminders/trigger", json={"medicine_id": mid}).json()["id"]
    res = client.post(f"/api/reminders/{rid}/response", json={"text": "haan li, sugar 300"}).json()
    assert res["status"] == "taken"
    assert res["readings"][0]["flag"] is True
    assert client.get("/api/dashboard").json()["flagged_readings"] == 1


def test_no_reply_retries_then_escalates_to_family(client):
    pid = make_patient(client)
    mid = client.post(f"/api/patients/{pid}/medicines", json={"name": "Telmisartan", "times": ["08:00"]}).json()["id"]
    client.post(f"/api/medicines/{mid}/confirm", json={"by": "Dr X"})
    client.post("/api/reminders/trigger", json={"medicine_id": mid})
    assert client.post("/api/scheduler/tick", json={"advance_minutes": 11}).json()["retried"] == 1
    assert client.post("/api/scheduler/tick", json={"advance_minutes": 25}).json()["escalated"] == 1
    calls = client.get("/api/calls").json()
    assert any(c["kind"] == "family_alert" and c["channel"] == "sms" for c in calls)
    assert client.get("/api/reminders").json()[0]["status"] == "escalated"


def test_summary_page_and_qr(client):
    pid = make_patient(client)
    s = client.post(f"/api/patients/{pid}/summary", json={"text": "3 din se sar dard hai, neend nahi aati, sugar ki dawai khatam"}).json()
    assert any("sar dard" in d for d in s["detected"])
    assert any("refill" in d for d in s["detected"])
    assert "Test Dadi" in client.get(s["url"]).text
    assert client.get(s["qr"]).headers["content-type"].startswith("image/svg")


def test_queue_and_stock(client):
    client.post("/api/queue", json={"name": "A"})
    client.post("/api/queue", json={"name": "B"})
    assert client.post("/api/queue/next", json={"department": "General OPD"}).json()["called"]["token_no"] == 1
    assert client.post("/api/queue/next", json={"department": "General OPD"}).json()["called"]["token_no"] == 2
    client.post("/api/stock", json={"name": "X", "expiry": "2020-01-01", "qty": 5})
    assert client.get("/api/stock").json()[0]["state"] == "expired"


def test_seed_and_validation(client):
    assert client.post("/api/demo/seed").json()["seeded"] is True
    assert client.post("/api/patients/1/medicines", json={"name": "X", "times": ["8am"]}).status_code == 422
    assert client.get("/health").json()["status"] == "ok"


def test_consult_draft_then_confirm_starts_reminders(client):
    pid = make_patient(client)
    text = "Amlodipine 5 mg subah ek goli khane ke baad. Metformin 500 mg subah shaam do baar. Paracetamol bukhar mein zaroorat par."
    drafts = client.post(f"/api/patients/{pid}/consult", json={"text": text}).json()["drafts"]
    assert [d["name"] for d in drafts] == ["Amlodipine", "Metformin", "Paracetamol"]
    assert drafts[0]["food"] == "after" and drafts[1]["times"] == ["08:00", "18:00"] and drafts[2]["as_needed"]
    # a draft saves nothing
    assert client.get("/api/patients").json()[0]["medicines"] == []
    r = client.post(f"/api/patients/{pid}/consult/confirm", json={"by": "Dr X", "items": drafts}).json()
    assert len(r["created"]) == 2  # as-needed medicine gets no fixed reminders
    mid = r["created"][0]["id"]
    assert client.post("/api/reminders/trigger", json={"medicine_id": mid}).status_code == 201
    assert client.post(f"/api/patients/{pid}/consult", json={"text": "kuch nahi"}).status_code == 422


# ---------- multi-hospital queue ----------
def test_daily_limit_blocks_extra_tokens_and_shows_left(client):
    client.post("/api/departments", json={"hospital": "H1", "name": "Medicine OPD", "daily_limit": 2})
    for n in ("A", "B"):
        assert client.post("/api/queue", json={"name": n, "hospital": "H1", "department": "Medicine OPD"}).status_code == 201
    r = client.post("/api/queue", json={"name": "C", "hospital": "H1", "department": "Medicine OPD"})
    assert r.status_code == 409
    av = client.get("/api/availability", params={"hospital": "H1", "lang": "hi"}).json()[0]
    assert av["left"] == 0 and av["full"] is True and "सीमा" in av["say"]
    client.post("/api/departments", json={"hospital": "H1", "name": "Medicine OPD", "daily_limit": 5})  # staff raises limit
    assert client.get("/api/availability").json()[0]["left"] == 3


def test_hospitals_are_independent(client):
    a = client.post("/api/queue", json={"name": "A", "hospital": "H1", "department": "ENT"}).json()
    b = client.post("/api/queue", json={"name": "B", "hospital": "H2", "department": "ENT"}).json()
    assert a["token_no"] == 1 and b["token_no"] == 1  # numbering is per hospital + department
    q = client.get("/api/queue", params={"hospital": "H2"}).json()
    assert [t["name"] for t in q] == ["B"]


def test_how_many_ahead_and_near_turn_call_only_once(client):
    for i in range(12):
        client.post("/api/queue", json={"name": f"P{i}", "hospital": "H1", "department": "Medicine OPD"})
    me = client.post("/api/queue", json={"name": "Dadi Ji", "hospital": "H1", "department": "Medicine OPD",
                                          "phone": "+910000000009", "language": "pa"}).json()
    assert me["token_no"] == 13 and me["ahead"] == 12
    params = {"token_no": 13, "department": "Medicine OPD", "hospital": "H1"}
    assert client.get("/api/queue/status", params=params).json()["ahead"] == 12
    assert client.post("/api/scheduler/tick", json={}).json()["queue_notified"] == 0  # still too far
    for _ in range(3):
        client.post("/api/queue/next", json={"department": "Medicine OPD", "hospital": "H1"})
    assert client.get("/api/queue/status", params=params).json()["ahead"] == 9
    assert client.post("/api/scheduler/tick", json={}).json()["queue_notified"] == 1
    assert client.post("/api/scheduler/tick", json={}).json()["queue_notified"] == 0  # no repeat calls
    calls = [c for c in client.get("/api/calls").json() if c["kind"] == "queue_near"]
    assert len(calls) == 1 and calls[0]["language"] == "pa" and "9" in calls[0]["text"]


# ---------- sugar / BP check reminders ----------
def test_sugar_check_reminder_with_bare_number_reply(client):
    pid = make_patient(client)
    cid = client.post(f"/api/patients/{pid}/checks", json={"kind": "sugar", "times": ["07:30"]}).json()["id"]
    r = client.post("/api/checks/trigger", json={"check_id": cid}).json()
    assert r["kind"] == "check" and r["medicine"] == "SUGAR check"
    res = client.post(f"/api/reminders/{r['id']}/response", json={"text": "280"}).json()  # just the number
    assert res["status"] == "taken" and res["readings"][0]["flag"] is True
    assert client.get("/api/patients").json()[0]["adherence"]["percent"] is None  # checks don't count as doses


def test_bp_check_no_reply_alerts_family_and_unclear_reply_asks_again(client):
    pid = make_patient(client)
    cid = client.post(f"/api/patients/{pid}/checks", json={"kind": "bp", "times": ["07:30"]}).json()["id"]
    rid = client.post("/api/checks/trigger", json={"check_id": cid}).json()["id"]
    assert client.post(f"/api/reminders/{rid}/response", json={"text": "hmm"}).json()["understood"] is False
    client.post("/api/scheduler/tick", json={"advance_minutes": 11})
    client.post("/api/scheduler/tick", json={"advance_minutes": 25})
    alerts = [c for c in client.get("/api/calls").json() if c["kind"] == "family_alert"]
    assert alerts and "BP" in alerts[0]["text"]
    assert client.post(f"/api/patients/{pid}/checks", json={"kind": "weight", "times": ["07:30"]}).status_code == 422


def test_seed_has_two_hospitals_one_full(client):
    client.post("/api/demo/seed")
    av = {(a["hospital"], a["department"]): a for a in client.get("/api/availability").json()}
    assert av[("Civil Hospital Demo", "Medicine OPD")]["left"] == 6
    assert av[("District Hospital Demo", "Medicine OPD")]["full"] is True


# ---------- Gnani voice (network is faked: no key needed to run tests) ----------
class FakeResp:
    def __init__(self, status=200, content=b"RIFFfakewav", payload=None):
        self.status_code, self.content, self._p = status, content, payload or {}
        self.text = str(self._p)

    def json(self):
        return self._p


def test_gnani_request_shapes(monkeypatch):
    from app import config, gnani

    monkeypatch.setattr(config, "GNANI_API_KEY", "test-key")
    seen = {}

    def fake_post(url, **kw):
        seen[url.split("vachana.ai")[1]] = kw
        return FakeResp(payload={"success": True, "transcript": "हाँ ली"})

    monkeypatch.setattr(gnani.httpx, "post", fake_post)
    assert gnani.synthesize("नमस्ते", "pa") == b"RIFFfakewav"
    tts = seen["/api/v1/tts/inference"]
    assert tts["headers"] == {"X-API-Key-ID": "test-key"}
    assert tts["json"]["model"] == "timbre-v2.5" and tts["json"]["language"] == "pa-IN" and tts["json"]["voice"] == "Mehuli"
    assert gnani.transcribe(b"wav", "hi") == "हाँ ली"
    stt = seen["/stt/v3"]
    assert stt["data"] == {"language_code": "hi-IN", "format": "transcribe"} and "audio_file" in stt["files"]


def test_gnani_errors_are_readable(monkeypatch):
    from app import config, gnani

    monkeypatch.setattr(config, "GNANI_API_KEY", "bad")
    monkeypatch.setattr(gnani.httpx, "post", lambda *a, **k: FakeResp(403, payload={"error": {"message": "no credits"}}))
    with pytest.raises(gnani.GnaniError) as e:
        gnani.synthesize("x")
    assert "credits" in str(e.value)


def test_voice_endpoints_without_key_say_503(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "GNANI_API_KEY", "")
    assert client.get("/api/voice/status").json() == {"gnani": False}
    assert client.post("/api/voice/tts", json={"text": "hi"}).status_code == 503
    assert client.post("/api/voice/stt", content=b"x").status_code == 503


def test_voice_reply_runs_the_normal_reminder_logic(client, monkeypatch):
    from app import config, gnani

    monkeypatch.setattr(config, "GNANI_API_KEY", "k")
    monkeypatch.setattr(gnani, "transcribe", lambda audio, lang, **kw: "haan li, sugar 280")
    monkeypatch.setattr(gnani, "synthesize", lambda text, lang="hi": b"WAVDATA")
    assert client.post("/api/voice/tts", json={"text": "hi", "lang": "hi"}).content == b"WAVDATA"
    pid = make_patient(client)
    mid = client.post(f"/api/patients/{pid}/medicines", json={"name": "Metformin", "times": ["08:00"]}).json()["id"]
    client.post(f"/api/medicines/{mid}/confirm", json={"by": "Dr X"})
    rid = client.post("/api/reminders/trigger", json={"medicine_id": mid}).json()["id"]
    out = client.post(f"/api/reminders/{rid}/voice-reply", content=b"fake-audio", headers={"Content-Type": "audio/wav"}).json()
    assert out["transcript"] == "haan li, sugar 280"
    assert out["result"]["status"] == "taken" and out["result"]["readings"][0]["flag"] is True
    assert client.post(f"/api/reminders/{rid}/voice-reply", content=b"").status_code == 422
