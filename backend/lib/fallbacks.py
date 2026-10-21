"""Fixed patient copy: the sentence under the priority badge and the comfort cards
used when no AI is available.

Rules for every card and sentence here:
  * no diagnosis words ("your condition is minor"),
  * nothing by mouth until a nurse says it is OK,
  * every level says what to do if things get worse,
  * no dashes, short sentences a 12 year old can read.
The comfort cards for every language live in lib/comfort_i18n.py (English when a
language is not translated yet). The sentences here are written out in English
and Spanish; the patient's screen shows its own translation from `explanation_key`.
"""
from __future__ import annotations

from typing import Any

from lib import comfort_i18n


def _lang(language: str | None) -> str:
    return (language or "en").strip().lower().split("-")[0][:2] or "en"


def comfort_set_name(esi_level: int, *, crisis: bool = False, child: bool = False, needs_reading: bool = False) -> str:
    """Which fixed card set goes with the visible score (see lib/comfort_i18n.py)."""
    level = esi_level if esi_level in (1, 2, 3, 4, 5) else 3
    if crisis and level >= 2:  # ESI 1 keeps "get help now", which also works for a bystander
        return "crisis"
    if needs_reading and level >= 3:  # no breathing exercise when nobody has read the words yet
        return "needs_reading"
    if child and level >= 2:
        return "child2" if level == 2 else "child"
    return f"esi{level}"


def comfort_cards(
    esi_level: int, language: str = "en", *, crisis: bool = False, child: bool = False, needs_reading: bool = False,
) -> list[dict]:
    """Three fixed comfort cards that match the visible ESI, in the patient's
    language when lib/comfort_i18n.py has it (English otherwise). Never empty."""
    name = comfort_set_name(esi_level, crisis=crisis, child=child, needs_reading=needs_reading)
    cards, _ = comfort_i18n.cards_for(_lang(language), name)
    return cards


def _legacy_table(lang: str) -> dict[Any, list[dict]]:
    sets = comfort_i18n.COMFORT_CARDS[lang]
    return {(int(k[3:]) if k.startswith("esi") else k): v for k, v in sets.items()}


# Kept for older imports: the English and Spanish cards, keyed 1 to 5 plus the
# named sets. Every language lives in lib/comfort_i18n.py.
COMFORT_CARDS: dict[str, dict[Any, list[dict]]] = {lang: _legacy_table(lang) for lang in ("en", "es")}
FALLBACK_PROTOCOLS: dict[int, list[dict]] = {k: v for k, v in COMFORT_CARDS["en"].items() if isinstance(k, int)}


ESI_LABELS: dict[int, str] = {
    1: "Critical",
    2: "Emergent",
    3: "Urgent",
    4: "Less Urgent",
    5: "Non-Urgent",
}

# The sentence under the priority badge. Keys match frontend i18n keys
# (result_explain_esi1 ... result_explain_crisis, result_explain_needs_reading).
_EXPLANATIONS: dict[str, dict[str, str]] = {
    "en": {
        "esi1": "You need help right now. Tell the nearest staff member immediately. If you are not at a hospital, call 911.",
        "esi2": "You are a high priority. Please stay close to the front desk and tell staff right away if you feel worse.",
        "esi3": "You will be seen today. People who are sicker may go first. Please tell staff right away if you feel worse.",
        "esi4": "Your wait may be longer because sicker people go first. Please do not leave before a nurse sees you. Tell staff right away if you feel worse.",
        "crisis": "Please tell a staff member now and stay with someone. You can call or text 988 (Suicide and Crisis Lifeline) any time, day or night.",
        "needs_reading": ("A nurse will read what you wrote and check on you soon. If you feel worse, tell the front desk right away. "
                          "If you are thinking about hurting yourself, tell staff now, or call or text 988."),
    },
    "es": {
        "esi1": "Necesita ayuda ahora mismo. Avise de inmediato al empleado más cercano. Si no está en un hospital, llame al 911.",
        "esi2": "Usted tiene prioridad alta. Quédese cerca de la recepción y avise al personal de inmediato si se siente peor.",
        "esi3": "Hoy recibirá atención. Las personas más enfermas pueden pasar primero. Avise al personal de inmediato si se siente peor.",
        "esi4": "Su espera puede ser más larga porque primero se atiende a los más enfermos. Por favor, no se vaya antes de ver a una enfermera. Avise al personal de inmediato si se siente peor.",
        "crisis": "Por favor, avise ahora a un miembro del personal y quédese con alguien. Puede llamar o enviar un mensaje de texto al 988 (Línea de Prevención del Suicidio y Crisis) a cualquier hora, de día o de noche.",
        "needs_reading": ("Una enfermera leerá lo que escribió y pronto le atenderá. Si se siente peor, avise de inmediato en la recepción. "
                          "Si está pensando en hacerse daño, avise al personal ahora, o llame o envíe un mensaje de texto al 988."),
    },
}


def explanation_key(esi_level: int, *, crisis: bool = False, needs_reading: bool = False) -> str:
    if crisis and esi_level >= 2:
        return "crisis"
    if needs_reading and esi_level >= 3:
        return "needs_reading"
    return {1: "esi1", 2: "esi2", 3: "esi3"}.get(esi_level, "esi4")


def patient_explanation(esi_level: int, language: str = "en", *, crisis: bool = False, needs_reading: bool = False) -> str:
    table = _EXPLANATIONS.get(_lang(language), _EXPLANATIONS["en"])
    return table[explanation_key(esi_level, crisis=crisis, needs_reading=needs_reading)]


# Kept for older imports: the English sentence by ESI level.
GENERIC_PATIENT_EXPLANATION: dict[int, str] = {lvl: patient_explanation(lvl) for lvl in (1, 2, 3, 4, 5)}
