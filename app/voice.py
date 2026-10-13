"""Call scripts (Hindi / Punjabi / English) and the simulated phone layer.

Real speech comes from app/gnani.py (Gnani Timbre TTS and Prisma STT).
"""
FOOD = {
    "hi": {"before": " खाने से पहले", "after": " खाने के बाद"},
    "pa": {"before": " ਖਾਣੇ ਤੋਂ ਪਹਿਲਾਂ", "after": " ਖਾਣੇ ਤੋਂ ਬਾਅਦ"},
    "en": {"before": " before food", "after": " after food"},
}

SCRIPTS = {
    "hi": "नमस्ते {name} जी। {medicine} की दवाई लेने का समय हो गया है{food}। क्या आपने दवाई ली? हाँ या नहीं बोलिए।",
    "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ {name} ਜੀ। {medicine} ਦੀ ਦਵਾਈ ਲੈਣ ਦਾ ਸਮਾਂ ਹੋ ਗਿਆ ਹੈ{food}। ਕੀ ਤੁਸੀਂ ਦਵਾਈ ਲਈ? ਹਾਂ ਜਾਂ ਨਹੀਂ ਦੱਸੋ।",
    "en": "Hello {name}. It is time for your {medicine}{food}. Did you take it? Please say yes or no.",
}
FOLLOWUP = {
    "hi": "कोई बात नहीं {name} जी। कृपया अभी दवाई ले लीजिए। आपके सुगर या बीपी की रीडिंग हो तो बता दीजिए।",
    "pa": "ਕੋਈ ਗੱਲ ਨਹੀਂ {name} ਜੀ। ਕਿਰਪਾ ਕਰਕੇ ਹੁਣ ਦਵਾਈ ਲੈ ਲਓ।",
    "en": "No problem {name}. Please take the medicine now. Tell me your sugar or BP reading if you have it.",
}
FAMILY = (
    "{family} ji, {patient} ne {time} ki {medicine} abhi tak confirm nahi ki hai. "
    "Kripya unse sampark karein. (Sehat Saathi)"
)


def build_reminder_script(patient, medicine) -> str:
    lang = patient.language if patient.language in SCRIPTS else "hi"
    food = FOOD[lang].get(medicine.food or "", "")
    label = medicine.name + (f" {medicine.dose}" if medicine.dose else "")
    return SCRIPTS[lang].format(name=patient.name.split()[0], medicine=label, food=food)


def build_followup_script(patient) -> str:
    lang = patient.language if patient.language in FOLLOWUP else "hi"
    return FOLLOWUP[lang].format(name=patient.name.split()[0])


def build_family_alert(patient, medicine, due_at) -> str:
    return FAMILY.format(
        family=(patient.family_name or "Parivar").split()[0],
        patient=patient.name,
        time=due_at.strftime("%I:%M %p"),
        medicine=medicine.name,
    )


class MockVoice:
    """Phone calls and SMS are SIMULATED (saved in call_logs and shown on the dashboard 'phone').

    Gnani's speech APIs (see app/gnani.py) turn the call text into real speech and real replies into text.
    Real telephony needs a phone provider (e.g. Gnani Agent Builder / Twilio), which is a later step.
    """

    name = "simulated"

    def call(self, phone: str, text: str, lang: str) -> bool:
        return True

    def sms(self, phone: str, text: str) -> bool:
        return True


def get_provider():
    return MockVoice()


# ---- health-check calls (sugar / BP) ----
_CHECK_WORD = {
    "hi": {"sugar": "शुगर", "bp": "बीपी"},
    "pa": {"sugar": "ਸ਼ੂਗਰ", "bp": "ਬੀਪੀ"},
    "en": {"sugar": "sugar", "bp": "blood pressure"},
}
_CHECK_SCRIPT = {
    "hi": "नमस्ते {name} जी। अभी अपना {what} जाँच लीजिए और रीडिंग बोलकर बताइए।",
    "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ {name} ਜੀ। ਹੁਣ ਆਪਣਾ {what} ਚੈੱਕ ਕਰੋ ਅਤੇ ਰੀਡਿੰਗ ਬੋਲ ਕੇ ਦੱਸੋ।",
    "en": "Hello {name}. Please check your {what} now and tell me the reading.",
}


def build_check_script(patient, kind: str) -> str:
    lang = patient.language if patient.language in _CHECK_SCRIPT else "hi"
    return _CHECK_SCRIPT[lang].format(name=patient.name.split()[0], what=_CHECK_WORD[lang][kind])


def build_family_check_alert(patient, kind: str, due_at) -> str:
    return (f"{(patient.family_name or 'Parivar').split()[0]} ji, {patient.name} ne {due_at.strftime('%I:%M %p')} par "
            f"{kind.upper()} ki reading abhi tak nahi di. Kripya unse sampark karein. (Sehat Saathi)")


# ---- hospital queue / availability calls ----
def availability_script(hospital: str, dept: str, left: int, lang: str) -> str:
    lang = lang if lang in ("hi", "pa", "en") else "hi"
    if left > 0:
        return {
            "hi": f"{hospital} के {dept} में आज {left} टोकन बचे हैं।",
            "pa": f"{hospital} ਦੇ {dept} ਵਿੱਚ ਅੱਜ {left} ਟੋਕਨ ਬਾਕੀ ਹਨ।",
            "en": f"{left} tokens are left today in {dept} at {hospital}.",
        }[lang]
    return {
        "hi": f"आज {dept} की सीमा पूरी हो गई है। कृपया कल का टोकन लें।",
        "pa": f"ਅੱਜ {dept} ਦੀ ਸੀਮਾ ਪੂਰੀ ਹੋ ਗਈ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਕੱਲ੍ਹ ਦਾ ਟੋਕਨ ਲਓ।",
        "en": f"Today's limit for {dept} is full. Please take a token for tomorrow.",
    }[lang]


def ahead_script(token_no: int, ahead: int, lang: str) -> str:
    lang = lang if lang in ("hi", "pa", "en") else "hi"
    return {
        "hi": f"आपका टोकन नंबर {token_no} है। आपसे पहले {ahead} लोग हैं।",
        "pa": f"ਤੁਹਾਡਾ ਟੋਕਨ ਨੰਬਰ {token_no} ਹੈ। ਤੁਹਾਡੇ ਤੋਂ ਪਹਿਲਾਂ {ahead} ਲੋਕ ਹਨ।",
        "en": f"Your token number is {token_no}. There are {ahead} people ahead of you.",
    }[lang]


def near_script(name: str, dept: str, ahead: int, lang: str) -> str:
    lang = lang if lang in ("hi", "pa", "en") else "hi"
    first = name.split()[0]
    return {
        "hi": f"{first} जी, आपका नंबर पास आ गया है। आपसे पहले सिर्फ {ahead} लोग हैं। कृपया {dept} की तरफ आइए।",
        "pa": f"{first} ਜੀ, ਤੁਹਾਡਾ ਨੰਬਰ ਨੇੜੇ ਆ ਗਿਆ ਹੈ। ਤੁਹਾਡੇ ਤੋਂ ਪਹਿਲਾਂ ਸਿਰਫ਼ {ahead} ਲੋਕ ਹਨ। ਕਿਰਪਾ ਕਰਕੇ {dept} ਵੱਲ ਆਓ।",
        "en": f"{first}, your turn is near. Only {ahead} people are ahead of you. Please come to {dept}.",
    }[lang]
