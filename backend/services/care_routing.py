"""What the patient should do next, shown as the main card on the result screen.

Everyone who checks in is already in the ER waiting room, and this advice comes
from a self-report before any nurse has seen them. So the card never tells a
patient to leave, go home, book a virtual visit, or come back later:

  ESI 1       tell staff right now (works for a bystander too)
  ESI 2       tell the front desk now and stay close
  ESI 3       stay, you will be seen today
  ESI 4 or 5  please stay; the wait may be longer because sicker people go first
  crisis      suicidal thoughts at ESI 2 or more: tell staff now, stay with someone, 988 line

The destination codes match the patient screen's translated cards:
ed_now = "now" (or "crisis" when the text has 988), ed = "close", urgent = "stay".

The level comes from the visible ESI, which already includes the red-flag rules
in services/triage_rules.py, so the card can never disagree with the badge.
Pure deterministic, no AI call.

For a child under 12 (young_child below) the card speaks to the parent: "stay
with your child", "tell staff if your child seems worse", and no food, drink or
medicine for the child until a nurse says it is OK. `audience` says which one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services import triage_rules

CHILD_UNDER_YEARS = 12


@dataclass(frozen=True)
class CareRecommendation:
    destination: str          # ed_now | ed | urgent
    label: str                # card title
    rationale: str            # one or two plain sentences
    action_cta: str           # text on the (non-navigating) button
    severity: str             # "critical" | "high" | "moderate" | "low"
    next_steps: tuple[str, ...] = field(default=())
    capacity_note: str = ""
    kind: str = ""            # now | crisis | high | today | wait (frontend i18n key: care_<kind>_*)
    language: str = "en"      # language the text above is written in
    audience: str = "patient"  # "patient", or "parent" for a child under 12


_KIND_META = {
    "now": ("ed_now", "critical"),
    "crisis": ("ed_now", "critical"),
    "high": ("ed", "high"),
    "today": ("urgent", "moderate"),
    "wait": ("urgent", "low"),
}

_COPY: dict[str, dict[str, dict]] = {
    "en": {
        "now": {"label": "Tell staff right now",
                "rationale": "What you described needs care right away. Tell the nearest staff member now. If you are helping someone, stay with them.",
                "cta": "I'm telling staff now",
                "steps": ("Tell the nearest staff member or the front desk right now.",
                          "If you are helping someone, stay with them and do not leave them alone.",
                          "Do not eat or drink until a nurse says it is OK.")},
        "crisis": {"label": "Please tell a staff member now",
                   "rationale": "You deserve help right now. Please tell a staff member now and stay with someone. You can also call or text 988 (Suicide and Crisis Lifeline) any time, day or night.",
                   "cta": "I'm telling staff",
                   "steps": ("Tell the nearest staff member now.",
                             "Stay with a staff member or someone you trust.",
                             "You can call or text 988 any time, day or night.")},
        "high": {"label": "Tell the front desk now",
                 "rationale": "You are a high priority. Please let the front desk know you are here, then stay close by so a nurse can find you.",
                 "cta": "OK, I'm telling the front desk",
                 "steps": ("Tell the front desk you checked in and were marked high priority.",
                           "Stay close to the front desk. Please do not leave.",
                           "Tell staff right away if you feel worse.",
                           "Do not eat or drink until a nurse says it is OK.")},
        "today": {"label": "Stay here to be seen today",
                  "rationale": "Please stay. A nurse will check on you soon. If you feel worse, tell the front desk right away.",
                  "cta": "OK, I'll stay",
                  "steps": ("Stay in the waiting area so we can call you.",
                            "Tell the front desk right away if you feel worse.",
                            "Please ask a nurse before you eat or drink.")},
        "wait": {"label": "Please stay to be seen",
                 "rationale": "Your wait may be longer because sicker people go first. Please do not leave before a nurse sees you. If you feel worse, tell the front desk right away.",
                 "cta": "OK, I'll wait",
                 "steps": ("Stay in the waiting area so we can call you.",
                           "Please do not leave before a nurse sees you.",
                           "Tell the front desk right away if you feel worse.")},
        "busy": "The emergency room is busy right now, so your wait may be longer. Please stay, and tell the front desk if you feel worse.",
    },
    "es": {
        "now": {"label": "Avise al personal ahora",
                "rationale": "Lo que describió necesita atención inmediata. Avise ahora mismo al empleado más cercano. Si está ayudando a alguien, quédese con esa persona.",
                "cta": "Estoy avisando al personal",
                "steps": ("Avise ahora mismo al empleado más cercano o a la recepción.",
                          "Si está ayudando a alguien, quédese con esa persona y no la deje sola.",
                          "No coma ni beba nada hasta que una enfermera le diga que puede.")},
        "crisis": {"label": "Avise ahora a un miembro del personal",
                   "rationale": "Usted merece ayuda ahora mismo. Por favor, avise ahora a un miembro del personal y quédese con alguien. También puede llamar o enviar un mensaje de texto al 988 (Línea de Prevención del Suicidio y Crisis) a cualquier hora, de día o de noche.",
                   "cta": "Estoy avisando al personal",
                   "steps": ("Avise ahora al empleado más cercano.",
                             "Quédese con un miembro del personal o con alguien de confianza.",
                             "Puede llamar o enviar un mensaje de texto al 988 a cualquier hora, de día o de noche.")},
        "high": {"label": "Avise en la recepción ahora",
                 "rationale": "Usted tiene prioridad alta. Avise en la recepción que ya está aquí y quédese cerca para que una enfermera le encuentre.",
                 "cta": "De acuerdo, voy a la recepción",
                 "steps": ("Diga en la recepción que se registró y que le marcaron con prioridad alta.",
                           "Quédese cerca de la recepción. Por favor, no se vaya.",
                           "Avise al personal de inmediato si se siente peor.",
                           "No coma ni beba nada hasta que una enfermera le diga que puede.")},
        "today": {"label": "Quédese para recibir atención hoy",
                  "rationale": "Por favor, quédese. Una enfermera le revisará pronto. Si se siente peor, avise de inmediato en la recepción.",
                  "cta": "De acuerdo, me quedo",
                  "steps": ("Quédese en la sala de espera para que podamos llamarle.",
                            "Avise de inmediato en la recepción si se siente peor.",
                            "Pregunte a una enfermera antes de comer o beber.")},
        "wait": {"label": "Por favor, quédese para recibir atención",
                 "rationale": "Su espera puede ser más larga porque primero se atiende a los más enfermos. Por favor, no se vaya antes de ver a una enfermera. Si se siente peor, avise de inmediato en la recepción.",
                 "cta": "De acuerdo, voy a esperar",
                 "steps": ("Quédese en la sala de espera para que podamos llamarle.",
                           "Por favor, no se vaya antes de ver a una enfermera.",
                           "Avise de inmediato en la recepción si se siente peor.")},
        "busy": "La sala de emergencias está muy ocupada, así que su espera puede ser más larga. Por favor, quédese y avise en la recepción si se siente peor.",
    },
}

# The same cards written to the parent of a child under 12.
_CHILD_COPY: dict[str, dict[str, dict]] = {
    "en": {
        "now": {"label": "Tell staff right now",
                "rationale": "What you described for your child needs care right away. Tell the nearest staff member now and stay with your child.",
                "cta": "I'm telling staff now",
                "steps": ("Tell the nearest staff member or the front desk right now.",
                          "Stay with your child and do not leave them alone.",
                          "Do not give your child food, drink, or medicine until a nurse says it is OK.")},
        "crisis": {"label": "Please tell a staff member now",
                   "rationale": "Your child deserves help right now. Please tell a staff member now and stay with your child. You can also call or text 988 (Suicide and Crisis Lifeline) any time, day or night.",
                   "cta": "I'm telling staff",
                   "steps": ("Tell the nearest staff member now.",
                             "Stay with your child. Do not leave them alone.",
                             "You can call or text 988 any time, day or night.")},
        "high": {"label": "Tell the front desk now",
                 "rationale": "Your child is a high priority. Please let the front desk know you are here, then stay close by with your child so a nurse can find you.",
                 "cta": "OK, I'm telling the front desk",
                 "steps": ("Tell the front desk you checked in your child and they were marked high priority.",
                           "Stay close to the front desk with your child. Please do not leave.",
                           "Tell staff right away if your child seems worse.",
                           "Do not give your child food, drink, or medicine until a nurse says it is OK.")},
        "today": {"label": "Stay here so your child is seen today",
                  "rationale": "Please stay. A nurse will check on your child soon. If your child seems worse, tell the front desk right away.",
                  "cta": "OK, we'll stay",
                  "steps": ("Stay in the waiting area with your child so we can call you.",
                            "Tell the front desk right away if your child seems worse.",
                            "Please ask a nurse before you give your child food, drink, or medicine.")},
        "wait": {"label": "Please stay so your child can be seen",
                 "rationale": "Your wait may be longer because sicker people go first. Please do not leave before a nurse sees your child. If your child seems worse, tell the front desk right away.",
                 "cta": "OK, we'll wait",
                 "steps": ("Stay in the waiting area with your child so we can call you.",
                           "Please do not leave before a nurse sees your child.",
                           "Tell the front desk right away if your child seems worse.")},
        "busy": "The emergency room is busy right now, so your wait may be longer. Please stay, and tell the front desk if your child seems worse.",
    },
    "es": {
        "now": {"label": "Avise al personal ahora",
                "rationale": "Lo que describió de su niño necesita atención inmediata. Avise ahora mismo al empleado más cercano y quédese con su niño.",
                "cta": "Estoy avisando al personal",
                "steps": ("Avise ahora mismo al empleado más cercano o a la recepción.",
                          "Quédese con su niño y no lo deje solo.",
                          "No le dé a su niño comida, bebida ni medicina hasta que una enfermera le diga que puede.")},
        "crisis": {"label": "Avise ahora a un miembro del personal",
                   "rationale": "Su niño merece ayuda ahora mismo. Por favor, avise ahora a un miembro del personal y quédese con su niño. También puede llamar o enviar un mensaje de texto al 988 (Línea de Prevención del Suicidio y Crisis) a cualquier hora, de día o de noche.",
                   "cta": "Estoy avisando al personal",
                   "steps": ("Avise ahora al empleado más cercano.",
                             "Quédese con su niño. No lo deje solo.",
                             "Puede llamar o enviar un mensaje de texto al 988 a cualquier hora, de día o de noche.")},
        "high": {"label": "Avise en la recepción ahora",
                 "rationale": "Su niño tiene prioridad alta. Avise en la recepción que ya están aquí y quédese cerca con su niño para que una enfermera los encuentre.",
                 "cta": "De acuerdo, voy a la recepción",
                 "steps": ("Diga en la recepción que registró a su niño y que le marcaron con prioridad alta.",
                           "Quédese cerca de la recepción con su niño. Por favor, no se vaya.",
                           "Avise al personal de inmediato si su niño parece estar peor.",
                           "No le dé a su niño comida, bebida ni medicina hasta que una enfermera le diga que puede.")},
        "today": {"label": "Quédese para que atiendan hoy a su niño",
                  "rationale": "Por favor, quédese. Una enfermera revisará pronto a su niño. Si su niño parece estar peor, avise de inmediato en la recepción.",
                  "cta": "De acuerdo, nos quedamos",
                  "steps": ("Quédese en la sala de espera con su niño para que podamos llamarles.",
                            "Avise de inmediato en la recepción si su niño parece estar peor.",
                            "Pregunte a una enfermera antes de darle a su niño comida, bebida o medicina.")},
        "wait": {"label": "Por favor, quédese para que atiendan a su niño",
                 "rationale": "Su espera puede ser más larga porque primero se atiende a los más enfermos. Por favor, no se vaya antes de que una enfermera vea a su niño. Si su niño parece estar peor, avise de inmediato en la recepción.",
                 "cta": "De acuerdo, vamos a esperar",
                 "steps": ("Quédese en la sala de espera con su niño para que podamos llamarles.",
                           "Por favor, no se vaya antes de que una enfermera vea a su niño.",
                           "Avise de inmediato en la recepción si su niño parece estar peor.")},
        "busy": "La sala de emergencias está muy ocupada, así que su espera puede ser más larga. Por favor, quédese y avise en la recepción si su niño parece estar peor.",
    },
}


def young_child(transcript: str = "", patient_age: Any = None, *, pregnant: bool = False) -> bool:
    """True for a patient under 12, so their screens speak to the parent.

    The age on the form ("Age of the person who is sick") decides when it is there.
    Without it, an age or child word in the patient's own words decides ("my 3 year
    old", "my baby"), except for a pregnant patient, whose "baby" is the pregnancy."""
    try:
        age = float(patient_age) if patient_age not in (None, "") else None
    except (TypeError, ValueError):
        age = None
    if age is not None:
        return 0 <= age < CHILD_UNDER_YEARS
    if pregnant:
        return False
    months = triage_rules.child_age_months(transcript or "", None, False)
    return months is not None and months < CHILD_UNDER_YEARS * 12


def recommend(
    esi_level: int,
    transcript: str = "",
    patient_age: int | None = None,
    *,
    department_load: float | None = None,
    waiting_count: int | None = None,
    language: str = "en",
    crisis: bool | None = None,
    child: bool | None = None,
) -> CareRecommendation:
    """Single-shot recommendation. Always returns; never None.

    `department_load` (0.0 to 1.0) and `waiting_count` only add a "longer wait"
    note for lower-acuity patients. They never move anyone off-site.
    `child` (a patient under 12) is worked out from the age and the words when it
    is not given; the card is then written to the parent.
    """
    assessment = triage_rules.assess(transcript or "", age=patient_age)
    if child is None:
        child = young_child(transcript, patient_age)
    if crisis is None:
        crisis = assessment.crisis
    # The rules already set the visible ESI at intake; re-checking here means a
    # caller that passes a stale level still gets the urgent card.
    level = min([esi_level] + [r.esi_level for r in assessment.matches])

    if crisis and level >= 2:
        kind = "crisis"
    elif level <= 1:
        kind = "now"
    elif level == 2:
        kind = "high"
    elif level == 3:
        kind = "today"
    else:
        kind = "wait"

    lang = (language or "en").strip().lower()[:2]
    table = _CHILD_COPY if child else _COPY
    copy = table.get(lang, table["en"])
    text = copy[kind]
    destination, severity = _KIND_META[kind]

    capacity_note = ""
    if kind in ("today", "wait"):
        busy = (department_load is not None and department_load >= 0.75) or (waiting_count is not None and waiting_count >= 15)
        if busy:
            capacity_note = copy["busy"]

    return CareRecommendation(
        destination=destination,
        label=text["label"],
        rationale=text["rationale"],
        action_cta=text["cta"],
        severity=severity,
        next_steps=tuple(text["steps"]),
        capacity_note=capacity_note,
        kind=kind,
        language=lang if lang in table else "en",
        audience="parent" if child else "patient",
    )


def serialize(rec: CareRecommendation) -> dict:
    return {
        "destination": rec.destination,
        "label": rec.label,
        "rationale": rec.rationale,
        "action_cta": rec.action_cta,
        "severity": rec.severity,
        "next_steps": list(rec.next_steps),
        "capacity_note": rec.capacity_note,
        "kind": rec.kind,
        "language": rec.language,
        "audience": rec.audience,
    }
