# Sehat Saathi (MVP)

**Hospital se pehle, hospital mein, hospital ke baad.** Voice-first, apni bhasha mein, bina smartphone ke.

**Problem:** door se aane wale mareez ko safar se pehle pata nahi hota ki aaj token milega ya nahi. Wo raat bhar line mein lagta hai aur subah wapas bhej diya jaata hai. Ghar par dawai, BP aur sugar ka hisaab bhi gadbad rehta hai.

Ghar se doctor tak, dawai ka poora loop: **patient ki baat → doctor ka one-page summary → dawai reminder call → "li / nahi li" → family alert**, plus hospital name list aur medical shop expiry.

## Quick start

**Option A: Docker (recommended, Postgres included)**
```bash
docker compose up --build
# open http://localhost:8000
```

**Option B: local Python (SQLite)**
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```
Tests: `python -m pytest -q`

Optional monitoring: `docker compose --profile monitoring up` (Prometheus :9090, Grafana :3000, scrape `/metrics`).

## What is in the MVP

| Module | What works |
|---|---|
| Visit summary | Patient's words → symptoms picked out (rule-based) → QR + one-page doctor view with medicines, readings, adherence |
| Medicines | Schedule per patient; **reminders start only after a doctor/pharmacist confirms** |
| Reminder loop | Due time → voice call → "haan/nahi" (Hindi, Hinglish, Punjabi, English) → retry → SMS to family |
| Sugar / BP | Parsed from speech/text ("sugar 280", "bp 150/95"), flagged for the doctor |
| Queue (any hospital) | Daily token limit per department, **"aaj kitne token bache?"** (voice answer, before travelling), "mere aage kitne log?", and a **call when the turn is near** (10 or fewer ahead) |
| BP / sugar checks | Scheduled "check now and tell me the number" calls; bare numbers ("140") understood; out-of-range readings flagged for the doctor; family alerted if no reply |
| Chemist stock | Batch + expiry, expired / expiring-in-60-days status |
| DevOps | Docker, Postgres, health check, `/metrics`, GitHub Actions CI, tests |

## 2-minute demo script

0. **Queue story first:** *Queue* tab shows two demo hospitals. Civil Hospital Medicine OPD has 6 tokens left, District Hospital Medicine OPD is **FULL**. Press **Hear answer**. Then take a token with a phone number, press **Call next** a few times and **Skip 11 min** to get the "your number is near" call.
1. Press **Load demo data** (dummy patients only).
2. *Patients* tab → **Call now** on Amlodipine. The "Patient phone" panel shows the call; press **Hear latest call** (browser voice).
3. Reply **Li + sugar 280**. Status turns *taken* and the reading gets a red flag.
4. Call again, send no reply, press **Skip 11 min** twice (each press moves the demo clock 11 min ahead). 1st press = call retried, 2nd press = SMS to family appears.
5. *Visit summary* tab → type or speak symptoms → scan QR → doctor page.
6. Show `docker compose up`, CI badge, `/metrics`.

## Gnani voice (real speech)

The app uses Gnani's **Vachana** speech APIs (docs: https://docs.gnani.ai):

- **Text-to-speech (Timbre v2.5):** the reminder / queue / availability text is spoken in Hindi, Punjabi or English.
- **Speech-to-text (Prisma):** the patient's spoken reply (or a BP/sugar reading) becomes text, then the normal reminder logic runs.

Without a key the dashboard falls back to the browser's built-in voice, so the demo still works.

1. Get an API key at https://app.gnani.ai/voice (new accounts get free credits, per Gnani's SDK page).
2. Copy `.env.example` to `.env` and paste the key: `GNANI_API_KEY=your-key`. **Never commit `.env`.**
3. Test the key (no server needed): `python scripts/gnani_check.py` (speaks a sentence, saves `hello.wav`, then transcribes it).
4. Start the app. The header badge should say **Voice: Gnani ON**. Use **Hear latest call** and **Reply with voice**.

**What is still simulated:** the phone call itself. A real phone call needs a telephony provider (Gnani Agent Builder or Twilio). In this MVP the call text is saved and played as audio on the dashboard "phone".

## Safety rules (say these in the demo)

- Never diagnoses and never suggests or changes a dose. It reminds, records and flags.
- A doctor/pharmacist must confirm each schedule before reminders start.
- Flag limits in `app/nlp.py` (`check_reading`) are placeholders. A hospital sets its own.
- Demo uses **dummy data only**. Real patient data needs consent, encryption and DPDP Act compliance.
- Symptom detection is keyword-based; the doctor always sees the patient's exact words.

## Roadmap after the MVP

Prescription photo → schedule (OCR, doctor verifies), login and roles (doctor/nurse/chemist), multi-hospital tenants, WhatsApp channel, more languages, stock refill alerts to the nearest chemist, ABHA integration.


## Troubleshooting

- **Error mentioning a missing column after updating the code:** the demo database has an older layout. Stop the server, delete `sehat.db` (it only holds dummy data), start again.
- Git Bash on Windows: activate the venv with `source venv/Scripts/activate`.
