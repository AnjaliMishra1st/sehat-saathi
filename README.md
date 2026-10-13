<div align="center">

# 🩺 Sehat Saathi

**A voice-first health helper for patients who travel far to reach a hospital.**
Before the hospital. Inside the hospital. After the hospital.

[![CI](https://github.com/AnjaliMishra1st/sehat-saathi/actions/workflows/ci.yml/badge.svg)](https://github.com/AnjaliMishra1st/sehat-saathi/actions)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![Voice](https://img.shields.io/badge/Voice-Gnani%20Vachana-orange)
![Tests](https://img.shields.io/badge/tests-19%20passing-brightgreen)

</div>

---

## The Problem

Many patients travel a long way to big government hospitals like AIIMS. They stand in line, sometimes all night. In the morning they learn that the daily token limit is over, and they are sent home without a checkup.

After the visit there is a second problem. At home, patients forget medicines, and nobody tracks their BP or sugar.

Both problems hurt the same person, so Sehat Saathi solves them together.

## The Solution

Sehat Saathi works through **voice**, in the patient's own language. It does not need a smartphone app.

| Stage | What the patient or family gets |
|---|---|
| **Before the hospital** | Ask by voice: *"How many tokens are left in Medicine OPD today?"* and know before travelling. |
| **In the hospital** | Ask: *"How many people are ahead of me?"* The system calls when the turn is near, so the patient can rest instead of standing in line. |
| **For the doctor** | A one-page summary of the patient's words, medicines and readings, opened by QR code. |
| **After the hospital** | Medicine reminder calls, a simple "taken / not taken" reply, and an SMS to the family if there is no reply. |

## Features

- **OPD queue**: daily token limit per department, tokens left, people ahead, and a "your number is near" call (10 or fewer ahead).
- **Visit summary**: the patient's own words become a one-page doctor view with a QR code.
- **Medicine reminders**: voice call, then reply, then retry, then SMS to family.
- **Understands many ways of replying**: Hindi, Hinglish, Punjabi and English ("haan", "nahi", "li").
- **BP and sugar readings**: understood from speech or text (for example "sugar 280" or "bp 150/95"). Readings outside the range are flagged for the doctor.
- **Scheduled health checks**: calls that ask the patient to check now and say the number.
- **Chemist stock**: batch and expiry tracking, with expired and expiring-in-60-days status.
- **DevOps ready**: Docker, Postgres, health check, `/metrics`, GitHub Actions CI and automated tests.

## Voice Technology (Gnani)

Sehat Saathi uses Gnani's **Vachana** speech APIs ([docs](https://docs.gnani.ai)):

- **Text-to-speech (Timbre v2.5):** reminders, queue answers and token availability are spoken in Hindi, Punjabi or English.
- **Speech-to-text (Prisma):** the patient's spoken reply or reading is turned into text, and then the normal reminder logic runs.

If no API key is set, the dashboard uses the browser's built-in voice, so the demo still works.

## Quick Start

### Option A: Docker (recommended, includes Postgres)

```bash
docker compose up --build
```

Open <http://localhost:8000>

### Option B: Local Python (uses SQLite)

```bash
python -m venv venv
source venv/Scripts/activate        # Windows Git Bash
# source venv/bin/activate          # Mac / Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://localhost:8000>

### Turn on real Gnani voice

1. Get an API key at <https://app.gnani.ai/voice>.
2. Copy the example settings file:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` and set:
   ```
   VOICE_PROVIDER=gnani
   GNANI_API_KEY=your-key-here
   ```
4. Test the key without starting the server:
   ```bash
   python scripts/gnani_check.py
   ```
   It speaks a sentence, saves `hello.wav`, then listens to it again.
5. Start the app. The header should show **Voice: Gnani ON**.

> ⚠️ Never commit your `.env` file. It is already listed in `.gitignore`.

### Run the tests

```bash
python -m pytest -q
```

## 2-Minute Demo

1. **Queue story:** open the **OPD queue** tab. Civil Hospital Medicine OPD has 6 tokens left. District Hospital Medicine OPD is **FULL**. Press **Hear answer**.
2. Take a token with a phone number. Press **Call next** a few times, then **Skip 11 min**. The "your number is near" call appears in the Patient phone panel.
3. Press **Load demo data** (dummy patients only).
4. Open **Patients**, press **Call now** on Amlodipine, then **Hear latest call**.
5. Reply **Li + sugar 280**. The status becomes *taken* and the reading gets a red flag.
6. Call again and send no reply. Press **Skip 11 min** twice. The first press retries the call, the second sends an SMS to the family.
7. Open **Visit summary**, type or speak symptoms, and scan the QR code to see the doctor page.

## Project Structure

```
sehat-saathi/
├── app/
│   ├── main.py        # API routes
│   ├── queue.py       # OPD queue and token logic
│   ├── nlp.py         # understands replies, readings and symptoms
│   ├── voice.py       # voice provider switch
│   ├── gnani.py       # Gnani speech-to-text and text-to-speech
│   ├── services.py    # reminder and alert logic
│   ├── models.py      # database tables
│   ├── seed.py        # dummy demo data
│   └── static/        # dashboard (index.html)
├── scripts/           # gnani_check.py
├── tests/             # automated tests
├── monitoring/        # Prometheus config
├── Dockerfile
└── docker-compose.yml
```

## Safety Rules

- It **never diagnoses** and **never suggests or changes a dose**. It only reminds, records and flags.
- A doctor or pharmacist must **confirm each medicine schedule** before reminders start.
- The BP and sugar limits in `app/nlp.py` are placeholders. Each hospital must set its own.
- Symptom detection is keyword based. The doctor always sees the patient's exact words.
- The demo uses **dummy data only**. Real patient data needs consent, encryption and DPDP Act compliance.

## Current Limits (Honest Notes)

- **The phone call is simulated.** The call text is saved and played as audio on the dashboard "phone". A real call needs a telephony provider such as Gnani Agent Builder or Twilio.
- **Queue data is demo data.** It is based on how a large hospital works, but it is not connected to a real hospital system.

## Roadmap

- [ ] Family status page ("did the elder take the medicine today?")
- [ ] Real phone calls through a telephony provider
- [ ] Connect to a real hospital token system
- [ ] Prescription photo to schedule (OCR, verified by a doctor)
- [ ] Login and roles for doctor, nurse and chemist
- [ ] WhatsApp channel and more languages
- [ ] ABHA integration

## Troubleshooting

| Problem | Fix |
|---|---|
| Error about a missing column after updating the code | The demo database has an old layout. Stop the server, delete `sehat.db` (it holds only dummy data), and start again. |
| `venv` will not activate in Git Bash | Use `source venv/Scripts/activate` |
| Header does not say "Voice: Gnani ON" | Check that `.env` has `VOICE_PROVIDER=gnani` and a valid `GNANI_API_KEY`, then restart the server. |

## Author

Built by **Anjali Mishra** for the Gnani.ai voice AI challenge.
