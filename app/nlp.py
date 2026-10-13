"""Tiny rule-based language helpers (Hindi / Hinglish / Punjabi / English).

Deliberately simple and transparent: no diagnosis, no dose advice.
In production the transcript comes from the speech-to-text API (see voice.py);
these helpers only interpret that text.
"""
import re

NEG = {
    "nahi", "nahin", "nhi", "nai", "na", "no", "not", "nope", "bhool", "bhul", "baaki",
    "नहीं", "नही", "ना", "भूल", "ਨਹੀਂ", "ਨਹੀ", "ਨਈ", "ਭੁੱਲ",
}
POS = {
    "haan", "han", "ha", "haanji", "haa", "yes", "yeah", "li", "le", "kha", "khali",
    "liya", "taken", "done", "ok", "okay", "theek", "ho", "gaya", "khadi", "lai",
    "हाँ", "हां", "ली", "लिया", "खा", "ਹਾਂ", "ਲਈ", "ਲੈ", "ਖਾ",
}


def parse_yes_no(text: str) -> bool | None:
    """True = took the medicine, False = did not, None = could not tell."""
    tokens = re.findall(r"[\w\u0900-\u097F\u0A00-\u0A7F]+", (text or "").lower())
    if not tokens:
        return None
    if any(t in NEG for t in tokens):  # check negatives first: "nahi li" contains "li"
        return False
    if any(t in POS for t in tokens):
        return True
    return None


_SUGAR = re.compile(r"(?:sugar|shugar|glucose|शुगर|ਸ਼ੂਗਰ)\D{0,12}(\d{2,3})", re.I)
_BP = re.compile(r"(?:bp|b\.p\.|blood pressure|बीपी|ਬੀਪੀ)\D{0,12}(\d{2,3})\s*(?:/|by|bai|-|\s)\s*(\d{2,3})", re.I)


def parse_readings(text: str) -> list[dict]:
    out = []
    m = _SUGAR.search(text or "")
    if m:
        out.append({"kind": "sugar", "value1": int(m.group(1)), "value2": None})
    m = _BP.search(text or "")
    if m:
        out.append({"kind": "bp", "value1": int(m.group(1)), "value2": int(m.group(2))})
    return out


# Thresholds are PLACEHOLDERS for the demo. A hospital must set its own;
# the system only *flags for a doctor to look*, it never advises treatment.
def check_reading(kind: str, v1: int, v2: int | None) -> tuple[bool, str | None]:
    if kind == "sugar":
        if v1 >= 250:
            return True, f"Sugar {v1} mg/dL is high"
        if v1 < 70:
            return True, f"Sugar {v1} mg/dL is low"
    if kind == "bp" and v2 is not None:
        if v1 >= 160 or v2 >= 100:
            return True, f"BP {v1}/{v2} is high"
        if v1 <= 90:
            return True, f"BP {v1}/{v2} is low"
    return False, None


SYMPTOMS = {
    "sar dard": ["sar dard", "sir dard", "headache", "सिर दर्द", "सरदर्द", "ਸਿਰ ਦਰਦ"],
    "bukhar (fever)": ["bukhar", "bukhaar", "fever", "बुखार", "ਬੁਖਾਰ"],
    "khansi (cough)": ["khansi", "khasi", "cough", "खांसी", "खाँसी", "ਖੰਘ"],
    "chakkar (dizziness)": ["chakkar", "chakar", "dizzy", "चक्कर", "ਚੱਕਰ"],
    "ulti / matli (nausea)": ["ulti", "matli", "vomit", "उल्टी", "मतली", "ਉਲਟੀ"],
    "neend ki dikkat (sleep)": ["neend", "sleep", "नींद", "ਨੀਂਦ"],
    "saans phoolna (breathlessness)": ["saans", "breath", "सांस", "साँस", "ਸਾਹ"],
    "seene mein dard (chest pain)": ["seene", "chest", "सीने", "ਛਾਤੀ"],
    "pet dard (stomach)": ["pet dard", "pet mein", "stomach", "पेट", "ਪੇਟ"],
    "kamzori (weakness)": ["kamzori", "weakness", "कमज़ोरी", "कमजोरी", "ਕਮਜ਼ੋਰੀ"],
    "pyaas / peshab zyada (thirst/urination)": ["pyaas", "peshab", "thirst", "प्यास", "पेशाब"],
}
_DUR = re.compile(r"(\d+)\s*(din|dino|hafte|hafta|mahine|mahina|saal|days?|weeks?|months?|दिन|हफ्ते|महीने|साल)", re.I)
URGENT = ["seene", "chest", "सीने", "ਛਾਤੀ", "saans", "सांस", "साँस", "ਸਾਹ", "behosh", "बेहोश"]


def extract_symptoms(text: str) -> list[str]:
    low = (text or "").lower()
    found = []
    for label, words in SYMPTOMS.items():
        if any(w in low for w in words):
            found.append(label)
    d = _DUR.search(low)
    out = list(found)
    if d and found:
        out.append(f"duration mentioned: {d.group(1)} {d.group(2)}")
    if any(w in low for w in ["khatam", "khatm", "ख़त्म", "खत्म", "finish", "ਖਤਮ"]):
        out.append("says some medicine has run out (needs refill)")
    return out


def looks_urgent(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in URGENT)


# ---------- "Doctor ki baat": consult speech -> medicine schedule DRAFT ----------
# Output is only a draft. A doctor/pharmacist must review and confirm before reminders start.
_TIME_WORDS = {
    "subah": "08:00", "savere": "08:00", "sawere": "08:00", "morning": "08:00", "सुबह": "08:00", "ਸਵੇਰ": "08:00",
    "dopahar": "13:00", "afternoon": "13:00", "दोपहर": "13:00", "ਦੁਪਹਿਰ": "13:00",
    "shaam": "18:00", "sham": "18:00", "evening": "18:00", "शाम": "18:00", "ਸ਼ਾਮ": "18:00",
    "raat": "21:00", "night": "21:00", "रात": "21:00", "ਰਾਤ": "21:00",
}
_COUNT_WORDS = {"ek": 1, "1": 1, "one": 1, "एक": 1, "do": 2, "2": 2, "two": 2, "दो": 2, "teen": 3, "3": 3, "three": 3, "तीन": 3}
_DEFAULT_BY_COUNT = {1: ["08:00"], 2: ["08:00", "20:00"], 3: ["08:00", "14:00", "21:00"]}
_SKIP = {"doctor", "dr", "dawai", "dawa", "dawaai", "ye", "yeh", "ya", "aur", "phir", "ko", "le", "lena", "lo", "len",
         "tablet", "tab", "cap", "capsule", "syrup", "syp", "goli", "dose", "din", "mein", "me", "roz", "daily", "har",
         "ek", "do", "teen", "one", "two", "three", "bas", "bhi", "rozana", "ab", "abhi", "aapko", "apko", "aap"}
_BEFORE = ["khane se pehle", "khane se pahle", "khali pet", "before food", "empty stomach", "खाने से पहले", "खाली पेट", "ਖਾਣੇ ਤੋਂ ਪਹਿਲਾਂ"]
_AFTER = ["khane ke baad", "khane k baad", "khane ke bad", "after food", "after meal", "खाने के बाद", "ਖਾਣੇ ਤੋਂ ਬਾਅਦ"]
_AS_NEEDED = ["zaroorat", "zarurat", "jarurat", "sos", "if needed", "when needed", "jab bukhar", "jab dard", "ज़रूरत", "जरूरत"]
_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|ml|mcg|g)\b", re.I)
_PER_DAY = re.compile(r"([\w\u0900-\u097F]+)\s*(?:baar|bar|times|बार)", re.I)


def parse_consult(text: str) -> list[dict]:
    text = re.sub(r"\b(tab|cap|syp|inj)\.\s*", "", text or "", flags=re.I)
    parts = [p.strip() for p in re.split(r"(?<!\d)\.(?=\s|$)|[;\n।]", text) if p.strip()]
    drafts = []
    for part in parts:
        low = part.lower()
        tokens = re.findall(r"[\w\u0900-\u097F\u0A00-\u0A7F]+", low)
        name = next((t for t in tokens if len(t) >= 3 and t not in _SKIP and t not in _TIME_WORDS
                     and t not in _COUNT_WORDS and not t.isdigit() and t not in ("baar", "bar", "times", "khane", "khali")), None)
        if not name:
            continue
        notes = []
        dose = _DOSE.search(part)
        times = sorted({v for k, v in _TIME_WORDS.items() if k in tokens})
        as_needed = any(w in low for w in _AS_NEEDED)
        has_food = any(w in low for w in _BEFORE + _AFTER)
        # Without any dosing hint (dose, time, count, food, "when needed") it is just chatter, not a medicine.
        if not (dose or times or as_needed or has_food or _PER_DAY.search(low)):
            continue
        if not times and not as_needed:
            m = _PER_DAY.search(low)
            n = _COUNT_WORDS.get(m.group(1)) if m else None
            if n:
                times = _DEFAULT_BY_COUNT[n]
                notes.append(f"times guessed from '{n} baar': check them")
            else:
                times = ["08:00"]
                notes.append("time not mentioned: defaulted to 08:00, please set")
        food = "before" if any(w in low for w in _BEFORE) else "after" if any(w in low for w in _AFTER) else None
        if as_needed:
            times = []
            notes.append("only when needed: no fixed reminders")
        notes.append("check the medicine spelling")
        drafts.append({"name": name.title() if name.isascii() else name, "dose": f"{dose.group(1)} {dose.group(2).lower()}" if dose else None,
                       "times": times, "food": food, "as_needed": as_needed, "notes": notes, "heard": part})
    return drafts


def parse_bare_reading(kind: str, text: str) -> list[dict]:
    """Reply to a 'tell me your sugar/BP' call may be just numbers: '140' or '150 95'."""
    nums = re.findall(r"\d{2,3}", text or "")
    if kind == "sugar" and nums and 30 <= int(nums[0]) <= 700:
        return [{"kind": "sugar", "value1": int(nums[0]), "value2": None}]
    if kind == "bp" and len(nums) >= 2:
        s, d = int(nums[0]), int(nums[1])
        if 60 <= s <= 260 and 30 <= d <= 160:
            return [{"kind": "bp", "value1": s, "value2": d}]
    return []
