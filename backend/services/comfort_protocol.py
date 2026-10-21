"""Patient comfort cards for the waiting room. Always returns exactly 3 cards.

With an AI key, Claude tailors the cards to the patient's words. Without one, or
if the reply is unusable, the fixed cards in lib/comfort_i18n.py are used, in the
patient's language when that table has it. Either way the cards follow the
visible ESI, so they never contradict the priority badge or the care card:
  * ESI 1 always gets the fixed "get help now" cards,
  * suicidal thoughts (from the rules, the checklist or the AI red-flag check)
    always get the fixed 988 cards,
  * a check-in nobody could read yet gets the fixed "a nurse will read it" cards,
  * a pregnant patient never gets the cards written to a child's parent.

AI cards are checked in every language before a patient sees them: a card that
suggests food, drink, a medicine or a dose is swapped for the fixed card, and the
last card must still tell the patient to tell staff (or name 911 or 988).

Patient-facing output is plain text: no emoji, no dashes.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from lib import claude, json_extract
from lib.config import settings
from lib.content_guard import strip_dashes
from lib.fallbacks import comfort_cards
from lib.medical_format import format_medical_info
from services import triage_rules

log = logging.getLogger(__name__)

_MODEL = settings.model_utility

# Patient-facing copy limits.
_MAX_TITLE_LEN = 40
_MAX_INSTRUCTION_LEN = 160

# Emoji / pictographic ranges to strip from any patient-facing string.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols, pictographs, emoji
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators
    "\U00002B00-\U00002BFF"  # arrows / misc
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero-width joiner
    "]+"
)

# ---- unsafe-advice check, every language ------------------------------------------------
# A specific medicine name or a dose is never OK on a patient card, whatever the wording.
_DOSE_OR_DRUG = re.compile(
    r"\d+(?:[.,]\d+)?\s?(?:mg|mcg|µg|μg|ml|cc|iu|units?|g|мг|мл|毫克|毫升|ミリグラム|밀리그램|ملغ|مجم|میلی ?گرم|मिलीग्राम|মিলিগ্রাম)(?![^\W\d_])"
    r"|\b(?:tylenol|ibuprof\w*|advil|motrin|aleve|naproxen\w*|aspirin\w*|acetaminophen\w*|paracetam\w*|benadryl|"
    r"diphenhydramine|nitroglycerin\w*|epipen|antihistamin\w*|antibiotic\w*|antibiótic\w*|antibiotique\w*|"
    r"парацетамол\w*|ибупрофен\w*|аспирин\w*)\b"
    r"|对乙酰氨基酚|布洛芬|阿司匹林|泰诺|イブプロフェン|アセトアミノフェン|アスピリン|타이레놀|이부프로펜|아세트아미노펜|아스피린|"
    r"باراسيتامول|إيبوبروفين|ايبوبروفين|أسبرين|اسبرين|استامینوفن|ایبوپروفن|آسپرین|پیناڈول|"
    r"पैरासिटामोल|आइबुप्रोफेन|एस्पिरिन|प्यारासिटामोल|প্যারাসিটামল|আইবুপ্রোফেন",
    re.IGNORECASE,
)
# The general words for a medicine, in all 20 languages (language-agnostic on purpose).
_MEDICINE_ANY = re.compile(
    r"\b(?:medicine\w*|medication\w*|medicin\w*|pills?|pillol\w*|pille|pillen|tablet\w*|drugs?|doses?|dosage|medicamento\w*|pastilla\w*|"
    r"dosis|rem[eé]di\w*|médicament\w*|medicament\w*|medikament\w*|comprim\w*|cachets?|arznei\w*|farmac\w*|"
    r"compress[ae]|ilaç\w*|lek|leki|leku|leków|lekarstw\w*|dawk\w*|obat\w*|gamot|tableta|thuốc|liều|"
    r"лекарств\w*|таблетк\w*|препарат\w*|доз[аыуе]\w*)\b"
    r"|药|藥|剂量|用量|薬|錠|服用|약을|약물|알약|복용|진통제|해열제|"
    r"دواء|أدوية|ادوية|الدواء|حبوب|جرعة|دارو|قرص|دوا|گولی|خوراک|दवा|गोली|खुराक|ওষুধ|ঔষধ|বড়ি|ট্যাবলেট|ডোজ",
    re.IGNORECASE,
)
# Food and drink. English is always checked; each other language adds its own words.
_FOOD_EN = r"\b(?:water|drink\w*|sip\w*|eat\w*|food|snack\w*|hydrat\w*|juice|coffee|soda|candy)\b"
_FOOD_BY_LANG: dict[str, str] = {
    "es": r"\b(?:agua|beb\w*|tom\w* agua|coma|comer|comida|jugo|zumo|caf[eé])\b",
    "fr": r"\b(?:eau|boire|bois|buvez|manger|mangez|nourriture|repas|collation|jus|caf[eé]|th[eé])\b",
    "pt": r"\b(?:[aá]gua|beber|beba|comer|coma|comida|lanche|suco|ch[aá]|caf[eé])\b",
    "de": r"\b(?:wasser|trinken|trink\w*|essen|iss|esst|nahrung|saft|tee|kaffee)\b",
    "it": r"\b(?:acqua|bere|beva|bevi|mangiare|mangi|cibo|spuntino|succo|t[eè]|caff[eè])\b",
    "tr": r"\b(?:su|suyu|içecek|içmek|içme\w*|yemek|yiyecek|atıştır\w*|çay|kahve)\b",
    "pl": r"\b(?:woda|wody|wodę|pić|pij\w*|jeść|jedz\w*|jedzeni\w*|przekąsk\w*|sok|herbat\w*|kawa|kawy|kawę)\b",
    "id": r"\b(?:air|minum\w*|makan\w*|camilan|jus|teh|kopi)\b",
    "tl": r"\b(?:tubig|inom\w*|uminom|kain|kumain|kumakain|pagkain|meryenda|tsaa|kape)\b",
    "vi": r"\b(?:nước|uống|ăn|đồ ăn|thức ăn|trà|cà phê)\b",
    "ru": r"\b(?:вод[аыуе]|пить|пейте|выпе\w*|поесть|кушать|еда|еды|еду|едой|пищ\w*|сок|чай|кофе)\b",
    "zh": r"喝|吃|水|食物|饮料|零食|进食|飲料",
    "ja": r"飲|食べ|水|食事|お茶|コーヒー",
    "ko": r"마시|먹|음식|간식|음료|물을|물이",
    "ar": r"ماء|مياه|شرب|تأكل|أكل|الأكل|طعام|عصير|شاي|قهوة",
    "fa": r"آب |بنوش|ننوش|نوشیدن|بخور|نخور|خوردن|غذا|خوراکی|چای|قهوه",
    "ur": r"پانی|پیئیں|پینا|کھائیں|کھانا|کھانے|غذا|چائے",
    "hi": r"पानी|पिएं|पीना|पीएं|खाना|खाएं|खाने|भोजन|चाय|कॉफी|नाश्ता",
    "bn": r"পানি|জল |খাবার|খাবেন|খাওয়া|কফি",
}
# In English and Spanish a card that only says to wait, or to ask first, is fine.
_NO_FOOD_OK = re.compile(
    r"\b(?:(?:do not|don'?t|never) (?:eat|drink|give)|ask (?:a nurse|staff|the nurse) before|no (?:coma|beba)|pregunte a (?:una|la) enfermera antes)\b",
    re.IGNORECASE,
)
# "Tell staff": English is always accepted, plus the card's own language.
_ESCALATION_EN = r"\b(?:staff|nurse|front desk)\b|911|988"
_ESCALATION_BY_LANG: dict[str, str] = {
    "es": r"\b(?:personal|enfermer\w*|recepci[oó]n)\b",
    "fr": r"\b(?:personnel|infirmi\w*|accueil|soignant\w*)\b",
    "pt": r"\b(?:equipe|enfermeir\w*|recep[cç][aã]o|funcion[aá]ri\w*)\b",
    "de": r"\b(?:personal|pflege\w*|krankenschwester|empfang|mitarbeit\w*|anmeldung)\b",
    "it": r"\b(?:personale|infermier\w*|accettazione|reception|operator\w*)\b",
    "tr": r"\b(?:personel\w*|hemşire\w*|görevli\w*|danışma\w*)\b",
    "pl": r"\b(?:personel\w*|pielęgniar\w*|rejestracj\w*|obsług\w*)\b",
    "id": r"\b(?:petugas|perawat|staf|resepsionis)\b",
    "tl": r"\b(?:nars|kawani|tauhan)\b",
    "vi": r"nhân viên|y tá|quầy",
    "ru": r"\b(?:персонал\w*|медсестр\w*|сотрудник\w*|регистратур\w*|врач\w*)\b",
    "zh": r"工作人员|工作人員|护士|護士|医护|醫護|前台|服务台",
    "ja": r"スタッフ|看護師|受付|職員",
    "ko": r"직원|간호사|접수",
    "ar": r"موظف|ممرض|طاقم|الاستقبال|العاملين",
    "fa": r"کارکنان|پرستار|کادر|پذیرش|کارمند",
    "ur": r"عملے|عملہ|نرس|اسٹاف|استقبالیہ",
    "hi": r"कर्मचारी|नर्स|स्टाफ|रिसेप्शन",
    "bn": r"কর্মী|নার্স|স্টাফ|রিসেপশন",
}


def _lang(language: str | None) -> str:
    return (language or "en").strip().lower().split("-")[0][:2] or "en"


def _compile(extra: str | None, base: str) -> re.Pattern[str]:
    return re.compile(f"{base}|{extra}" if extra else base, re.IGNORECASE)


_FOOD = {lang: _compile(_FOOD_BY_LANG.get(lang), _FOOD_EN) for lang in list(_FOOD_BY_LANG) + ["en"]}
_ESCALATION = {lang: _compile(_ESCALATION_BY_LANG.get(lang), _ESCALATION_EN) for lang in list(_ESCALATION_BY_LANG) + ["en"]}


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def unsafe_advice(text: str, language: str = "en") -> bool:
    """True when the text tells the patient to eat, drink or take a medicine.

    A medicine name or a dose always counts. The general words for food, drink
    or medicine count unless (in English or Spanish) the text only says to wait
    or to ask a nurse first."""
    t, lang = _nfc(text), _lang(language)
    if _DOSE_OR_DRUG.search(t):
        return True
    if _MEDICINE_ANY.search(t) or _FOOD.get(lang, _FOOD["en"]).search(t):
        return not (lang in ("en", "es") and _NO_FOOD_OK.search(t))
    return False


def mentions_medicine(text: str) -> bool:
    """A medicine word, a medicine name or a dose, in any language."""
    t = _nfc(text)
    return bool(_DOSE_OR_DRUG.search(t) or _MEDICINE_ANY.search(t))


def names_medicine_or_dose(text: str) -> bool:
    """A specific medicine name or a dose, in any language."""
    return bool(_DOSE_OR_DRUG.search(_nfc(text)))


def mentions_food(text: str, language: str = "en") -> bool:
    return bool(_FOOD.get(_lang(language), _FOOD["en"]).search(_nfc(text)))


def says_tell_staff(text: str, language: str = "en") -> bool:
    """Tells the patient to tell staff (or names 911 or 988), in English or the given language."""
    return bool(_ESCALATION.get(_lang(language), _ESCALATION["en"]).search(_nfc(text)))


def _strip_emoji(text: str) -> str:
    """Remove emoji/pictographs and collapse the whitespace they leave behind."""
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", text or "")).strip()


def _sanitize_cards(cards: list[dict]) -> list[dict]:
    """Strip emoji and dashes, drop any icon field, clamp lengths. Returns title/instruction only."""
    out: list[dict] = []
    for item in cards if isinstance(cards, list) else []:
        if not isinstance(item, dict):
            continue
        title = strip_dashes(_strip_emoji(str(item.get("title", ""))))[:_MAX_TITLE_LEN].strip()
        instruction = strip_dashes(_strip_emoji(str(item.get("instruction", ""))))[:_MAX_INSTRUCTION_LEN].strip()
        if title and instruction:
            out.append({"title": title, "instruction": instruction})
    return out


def _context(transcript: str, medical_info: dict[str, Any] | None) -> tuple[bool, bool]:
    """(crisis, young child) from the same rules that set the ESI.

    A patient marked pregnant on the form is never treated as a young child, so
    "the baby is not moving" gets cards for the patient, not for a parent."""
    info = medical_info if isinstance(medical_info, dict) else {}
    pregnant = bool(info.get("pregnant"))
    a = triage_rules.assess(transcript or "", age=info.get("age"), pregnant=pregnant)
    child = not pregnant and a.child_months is not None and a.child_months < 60
    return a.crisis, child


def _fallback(esi_level: int, language: str, *, crisis: bool = False, child: bool = False,
              needs_reading: bool = False) -> list[dict]:
    """Exactly 3 fixed cards for the ESI level and language."""
    return _sanitize_cards(comfort_cards(esi_level, language, crisis=crisis, child=child, needs_reading=needs_reading))[:3]


def fallback_cards(
    transcript: str, esi_level: int, language: str, medical_info: dict[str, Any] | None = None,
    *, crisis: bool | None = None, needs_reading: bool = False,
) -> list[dict]:
    """Fixed cards with the crisis, child and needs-reading checks applied. Never calls an AI.

    `crisis` is the stored check-in decision (it can come from the checklist or the
    AI red-flag check, which the rules here cannot see); the rules' own crisis
    check is always added to it."""
    rules_crisis, child = _context(transcript, medical_info)
    return _fallback(esi_level, language, crisis=bool(crisis) or rules_crisis, child=child, needs_reading=needs_reading)


_SYSTEM = """You are Solace, a kind helper for a patient who is waiting in an emergency room. Write 3 short comfort cards.

Rules:
- ESI 1-2: the first card tells them to tell the nearest staff member now. Keep them still and calm. Never tell them to walk somewhere alone.
- ESI 3: gentle comfort, such as a comfortable position or slow breathing.
- ESI 4-5: gentle comfort, such as resting a sore arm or leg on a chair, or asking staff for an ice pack.
- Never tell the patient to eat or drink anything. Never suggest any medicine.
- The last card must tell the patient to tell staff right away if they feel worse.
- Never tell the patient to leave, go home, or come back later.
- If the patient is a young child, write to the parent.
- Return EXACTLY 3 cards. Each has a title (1 to 4 words) and an instruction (1 short sentence, under 25 words).
- Plain text only. No emoji, no symbols, no markdown, and never use em dashes or en dashes.
- Respond ONLY in language code: {language}.
- Return a JSON array only. No preamble, no markdown fence.

JSON schema:
[{{"title": "...", "instruction": "..."}}]"""


def generate(
    transcript: str,
    photo_analysis: dict[str, Any] | None,
    esi_level: int,
    language: str,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    *,
    crisis: bool | None = None,
    needs_reading: bool = False,
    allow_ai: bool = True,
) -> list[dict]:
    rules_crisis, child = _context(transcript, medical_info)
    crisis = bool(crisis) or rules_crisis
    if crisis or needs_reading or esi_level <= 1 or not allow_ai or not claude.available():
        return _fallback(esi_level, language, crisis=crisis, child=child, needs_reading=needs_reading)
    try:
        user_parts = [
            f'Patient transcript:\n"""\n{transcript.strip()}\n"""',
            f"Photo analysis: {(photo_analysis or {}).get('description') or 'none'}",
            f"ESI level: {esi_level}",
        ]
        if child:
            user_parts.append("The patient is a young child. Write to the parent.")
        if medical_info:
            user_parts.append(f"Medical history: {format_medical_info(medical_info)}")
        if followup_qa:
            from services.followups import format_qa_for_prompts

            qa = format_qa_for_prompts(followup_qa)
            if qa:
                user_parts.append(f"Follow-up answers:\n{qa}")
        user_parts.append("Return the JSON array of exactly 3 cards now.")

        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=600,
            system=_SYSTEM.format(language=language),
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
            purpose="comfort_protocol",
        )
        raw = "".join(b.text for b in resp.content)
        parsed = _parse(raw)
        if parsed:
            return _enforce(parsed, esi_level, language, child)
        log.warning("Comfort protocol parse failed; using fallback (len=%d, content redacted)", len(raw))
    except Exception as e:
        log.exception("Comfort protocol generation failed: %s", e)
    return _fallback(esi_level, language, child=child)


def _enforce(cards: list[dict], esi_level: int, language: str, child: bool) -> list[dict]:
    """Keep the AI cards consistent with the safety rules, in every language: swap
    out food, drink, medicine or dose advice, and make sure the last card still
    says to tell staff."""
    fixed = _fallback(esi_level, language, child=child)
    out = []
    for i, card in enumerate(cards[:3]):
        text = f"{card['title']} {card['instruction']}"
        out.append(fixed[i] if unsafe_advice(text, language) else card)
    last = out[-1]
    if not says_tell_staff(f"{last['title']} {last['instruction']}", language):
        out[-1] = fixed[-1]  # the last card always says to tell staff if things get worse
    return out


def _parse(raw: str) -> list[dict]:
    """Parse the Claude JSON array into exactly 3 sanitized cards, or [] if fewer than 3."""
    arr = json_extract.extract_array(raw)
    if not arr:
        return []
    cleaned = _sanitize_cards(arr)
    if len(cleaned) < 3:
        return []
    return cleaned[:3]
