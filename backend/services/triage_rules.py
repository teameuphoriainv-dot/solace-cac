"""Deterministic triage rules: red-flag phrases and the bedside vital-sign floor.

The model was trained on synthetic, templated English, so on real free text it
can miss an obvious emergency ("I can't breathe" scored ESI 4). These rules run
on every check-in and can only make a patient MORE urgent, never less:

  * English red-flag rules. Each one is two-sided: tests/test_red_flags.py pins
    phrases that must fire and phrases that must stay low ("faint rash"), and
    tests/test_redteam_regression.py pins the red-team check-ins
    (tests/data/redteam_*.json).
  * Red-flag lists for the app's other languages, typed in their own script or
    in Latin letters ("seene mein dard"), so the most dangerous complaints are
    caught even with no AI key. The word lists live in services/triage_lexicons.py.
  * Denials: "no chest pain", "no tengo dolor de pecho", "胸口也不痛" and "I never
    blacked out" do not count as the complaint (cue words in triage_lexicons.DENIAL).
  * The bedside vital-sign floor from the ESI handbook.

Keyword rules do not generalize to every way a person can describe an emergency
(see docs/evidence/red-flag-stress-test.md, held-out set). The red-flag checklist
the patient taps at check-in is the safety net that does not depend on wording.

The visible score is the most urgent of the model and these rules. The badge,
the patient explanation, the care card and the comfort cards all read from this
one module, so they can never disagree.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from dataclasses import replace as _replace

from services import triage_lexicons as _lex


@dataclass(frozen=True)
class ShortcutResult:
    esi_level: int                  # 1-5
    reason: str                     # short rule id for the audit log
    recommendation: str             # one line for the clinician
    skip_claude_pipeline: bool = True
    name: str = ""                  # plain-English name for clinicians and the evidence page
    crisis: bool = False            # suicidal thoughts or self-harm: show the 988 line


@dataclass(frozen=True)
class Rule:
    result: ShortcutResult
    pattern: re.Pattern[str]
    also: re.Pattern[str] | None = None        # compound rule: both must match
    ignore: re.Pattern[str] | None = None      # phrases blanked out first ("faint rash")
    child_under_months: int | None = None      # only for young children
    crisis_if: re.Pattern[str] | None = None   # first-person overdose counts as a crisis
    examples: tuple[str, ...] = ()


@dataclass
class Assessment:
    matches: list[ShortcutResult] = field(default_factory=list)  # most urgent first
    admin: ShortcutResult | None = None   # paperwork-only request; never a floor
    child_months: int | None = None

    @property
    def floor(self) -> ShortcutResult | None:
        return self.matches[0] if self.matches else None

    @property
    def crisis(self) -> bool:
        return any(m.crisis for m in self.matches)


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------
_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'", "ё": "е"})
# Arabic, Persian and Urdu spell the same letters several ways; fold them to one.
_ARABIC_SCRIPT = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ی": "ي", "ے": "ي", "ئ": "ي",
    "ؤ": "و", "ة": "ه", "ۀ": "ه", "ہ": "ه", "ھ": "ه", "ۃ": "ه", "ک": "ك", "ں": "ن",
    "ـ": None, "‌": None, "‍": None,
})
# Arabic vowel marks, and the Devanagari and Bengali nukta and candrabindu.
_MARKS = re.compile("[ً-़়ٰٟঁ]")
_LATIN_EXTRA = str.maketrans({"ł": "l", "đ": "d", "ı": "i", "ø": "o", "ß": "ss", "æ": "ae", "œ": "oe"})

# Common misspellings and dictation splits (services/triage_lexicons.py), folded to the word the English rules know.
_TYPOS = _lex.TYPOS
_TYPO_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _TYPOS), key=len, reverse=True)) + r")\b")


def normalize(text: str) -> str:
    """Lowercase, straighten quotes, unify script variants. Used on text AND patterns,
    so patterns must not use uppercase escapes like \\S or \\W."""
    t = unicodedata.normalize("NFKC", text or "").lower().translate(_QUOTES)
    t = t.translate(_ARABIC_SCRIPT).replace("ँ", "ं")
    return re.sub(r"\s+", " ", _MARKS.sub("", t)).strip()


def _deaccent(text: str) -> str:
    """Strip accents for Latin-script matching: "corazón" becomes "corazon". Safe on patterns."""
    t = unicodedata.normalize("NFKD", text.translate(_LATIN_EXTRA))
    return "".join(c for c in t if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Strip accents and fix common misspellings ("cant breth" becomes "cant breath").
    Use it on patient text only; patterns go through _deaccent."""
    return _TYPO_RE.sub(lambda m: _TYPOS[m.group(1)], _deaccent(text))


def _words(*alts: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b")


_ign = _words   # ignore lists use the same shape


def _phrases(alts: str, latin: bool) -> re.Pattern[str]:
    src = normalize(alts)
    return re.compile(r"\b(?:" + _deaccent(src) + r")\b" if latin else src)


# Narrow negations only ("no chest pain"). A broad "no ..." scrub could eat "no, I can't breathe".
# "never had chest pain LIKE THIS" and "no chest pain UNTIL tonight" are complaints, so they stay.
_NEGATED = re.compile(
    r"\b(?:no|denies|deny|without|never had|not having(?: any)?|(?:don'?t|do not|doesn'?t|does not|haven'?t|have not) (?:have|had)(?: any)?)"
    r" (?:chest pain|chest pressure|shortness of breath|trouble breathing|difficulty breathing|fevers?|bleeding)\b"
    r"(?! (?:like|until|till|til|before|this bad|this severe|ever|usually|normally)\b| but (?:it'?s|its|it is|it feels|feels)\b)"
    r"|\b(?:no|not|didn'?t|did not|without|denies|never|wasn'?t|was not|haven'?t|hasn'?t|have not|has not) (?:any |ever |even )?"
    r"(?:confus\w*|vomit\w*|throw\w* up|threw up|pass\w* out|loc|loss of consciousness|sleepy|drowsy|seizures?"
    r"|black\w* out|blackouts?|faint\w*|knocked out|los\w* (?:\w+ )?consciousness|unconscious)\b"
    r"(?! (?:yet|until|till|til|before (?:today|tonight|this))\b)"
)

# ---------------------------------------------------------------------------
# What each rule tells the clinician
# ---------------------------------------------------------------------------
_ESI2_NOTE = "Do not let this patient wait. Bed and clinician promptly."
RESUS = ShortcutResult(1, "rule.esi1.life_threatening_keywords",
                       "ESI 1: not breathing, unresponsive, or turning blue. Immediate resuscitation.",
                       name="Not breathing, not waking up, or turning blue")
TRAUMA = ShortcutResult(1, "rule.esi1.catastrophic_trauma",
                        "ESI 1: catastrophic trauma or hemorrhage. Trauma team, hemorrhage control, airway.",
                        name="Severe injury (amputation, gunshot, blood spurting)")
STROKE = ShortcutResult(1, "rule.esi1.stroke_symptoms",
                        "ESI 1: possible stroke. Activate stroke alert; CT head now.",
                        name="Stroke signs (face drooping, slurred speech, one side weak)")
CHEST = ShortcutResult(2, "rule.esi2.chest_pain", f"ESI 2: chest pain or pressure. ECG within 10 minutes. {_ESI2_NOTE}",
                       name="Chest pain or pressure")
BREATH = ShortcutResult(2, "rule.esi2.breathing", f"ESI 2: trouble breathing. {_ESI2_NOTE}",
                        name="Cannot breathe or very hard to breathe")
ALLERGY = ShortcutResult(2, "rule.esi2.airway_swelling", f"ESI 2: possible anaphylaxis or airway swelling. {_ESI2_NOTE}",
                         name="Throat, lips, or tongue swelling (allergic reaction)")
BLEED = ShortcutResult(2, "rule.esi2.heavy_bleeding", f"ESI 2: heavy or uncontrolled bleeding. {_ESI2_NOTE}",
                       name="Heavy bleeding or bleeding that will not stop")
PREGNANCY = ShortcutResult(2, "rule.esi2.pregnancy_bleeding",
                           f"ESI 2: pregnant with bleeding, leaking fluid, severe pain, or another warning sign. {_ESI2_NOTE}",
                           name="Pregnant with bleeding, leaking fluid, bad pain, or another warning sign")
FAINT = ShortcutResult(2, "rule.esi2.syncope", f"ESI 2: fainted, passed out, or collapsed. {_ESI2_NOTE}",
                       name="Fainted, passed out, or collapsed")
HEAD = ShortcutResult(2, "rule.esi2.head_injury", f"ESI 2: head injury with confusion, vomiting, or loss of consciousness. {_ESI2_NOTE}",
                      name="Head injury with confusion, vomiting, or passing out")
NECK = ShortcutResult(2, "rule.esi2.stiff_neck_fever", f"ESI 2: stiff neck with fever or headache; consider meningitis. {_ESI2_NOTE}",
                      name="Stiff neck with fever or headache")
CHILD_FEVER = ShortcutResult(2, "rule.esi2.child_fever_lethargy", f"ESI 2: young child with fever and lethargy. {_ESI2_NOTE}",
                             name="Child under 5 with fever who is very sleepy or hard to wake")
INFANT_FEVER = ShortcutResult(2, "rule.esi2.infant_fever", f"ESI 2: infant under 3 months with fever. {_ESI2_NOTE}",
                              name="Baby under 3 months with a fever")
CRISIS = ShortcutResult(2, "rule.esi2.crisis", "ESI 2: suicidal thoughts or self-harm. Continuous observation; psych consult.",
                        name="Suicidal thoughts or self-harm", crisis=True)
OVERDOSE = ShortcutResult(2, "rule.esi2.overdose", f"ESI 2: overdose or poisoning. Call Poison Control; watch airway. {_ESI2_NOTE}",
                          name="Overdose or poisoning")
OVERDOSE_SELF = ShortcutResult(2, "rule.esi2.overdose_self",
                               "ESI 2: overdose by the patient. Treat as possible self-harm; continuous observation.",
                               name="Overdose or poisoning", crisis=True)
SEIZURE = ShortcutResult(2, "rule.esi2.seizure", f"ESI 2: seizure. {_ESI2_NOTE}", name="Seizure")
ONE_SIDE = ShortcutResult(2, "rule.esi2.one_sided_weakness", f"ESI 2: one-sided weakness or numbness; screen for stroke. {_ESI2_NOTE}",
                          name="One arm or one side weak or numb")
HIGH_RISK = ShortcutResult(2, "rule.esi2.high_risk_presentation", f"ESI 2: high-risk presentation. {_ESI2_NOTE}",
                           name="Other high-risk signs (worst headache, vision loss, serious injury, dangerous readings)")
ALTERED = ShortcutResult(2, "rule.esi2.new_confusion", f"ESI 2: new confusion or altered mental status. {_ESI2_NOTE}",
                         name="New confusion or not acting like themselves")
DANGER_OTHERS = ShortcutResult(2, "rule.esi2.danger_to_others",
                               f"ESI 2: thoughts of hurting someone else. Safe room; security aware. {_ESI2_NOTE}",
                               name="Thoughts of hurting someone else")
ASSAULT = ShortcutResult(2, "rule.esi2.assault",
                         f"ESI 2: sexual assault or strangulation. Private room; trauma-informed exam. {_ESI2_NOTE}",
                         name="Sexual assault or strangulation")
SUGAR = ShortcutResult(2, "rule.esi2.high_sugar", f"ESI 2: very high blood sugar with symptoms; consider DKA or HHS. {_ESI2_NOTE}",
                       name="Very high blood sugar with vomiting, confusion, or fast breathing")
INFANT_UNWELL = ShortcutResult(2, "rule.esi2.infant_unwell", f"ESI 2: baby under 3 months not feeding, very sleepy, or dry. {_ESI2_NOTE}",
                               name="Baby under 3 months who will not feed, is very sleepy, or has no wet diapers")
DEHYDRATED = ShortcutResult(2, "rule.esi2.child_dehydration_lethargy", f"ESI 2: young child not peeing and very sleepy. {_ESI2_NOTE}",
                            name="Young child not peeing and very sleepy")
ADMIN = ShortcutResult(5, "rule.esi5.administrative",
                       "ESI 5: non-clinical / administrative. Direct to front desk; no medical workup.",
                       name="Paperwork or refill only")

# ---------------------------------------------------------------------------
# Shared pieces of the English rules (matched on folded, lowercased text)
# ---------------------------------------------------------------------------
_FILL = r"(?:(?:is|are|feels?|keeps?|started|starting|getting|got|has|have|had|been|really|so|very|all|kind of|kinda|to|began|just|now|suddenly|a little|a bit|looks?|seems|went|gone) ){0,3}"
# Spanish fever and sleepiness words are included so a parent's check-in in Spanish is read too.
_FEVER = r"fevers?|feverish|temperature|temp|burning up|fiebre|calentura|10[2-6](?:\.\d)?(?: ?degrees| ?f)?"
_FEVER_PLUS = (_FEVER + r"|(?:feels?|is|so|very|really) hot|(?:feels?|is|so|very|really|felt) (?:\w+ )?warm|hot to the touch|warm to the touch"
               r"|100\.[4-9]|10[1-6](?:\.\d)?|3[89]\.\d|(?:3[89]|40)(?:\.\d)? ?(?:c|degrees|celsius)")
# Fever words in every offered language plus Celsius readings, for the child fever rules.
_FEVER_ANY = (r"\b(?:fievre|febre|febbre|fieber|lagnat|nilalagnat|demam|ates|goraczk\w*|sot|temperatur\w*|"
              r"(?:3[89]|4[01])(?:[.,]\d)? ?(?:degrees?|deg|c)|100[.,][4-9]|101(?:[.,]\d)?)\b|"
              + _deaccent(normalize(_lex.FEVER_WORDS))
              # Persian "تب" (fever) only as its own word, so Arabic "تبكي" (she is crying) does not count
              + r"|(?:^|(?<= ))" + normalize("تب") + r"(?= |ش|دار|$)")
_NORMAL_TEMP = _ign(r"(?:temp|temperature|fever) (?:is |was |of )?(?:normal|fine|ok|okay|good|9[5-9](?:\.\d)?|3[56](?:\.\d)?)",
                    r"normal (?:temp|temperature)|(?:no|without) (?:a )?(?:temp|temperature)",
                    r"warm (?:from|after) (?:being )?(?:bundled|swaddled|the car|a bath|sleeping)")
_NOT_WELL = r"not breathing (?:well|right|normal\w*|properly|good|great|easily|easy|very well)"
# "breathing right" or "breathing fast" is a breathing problem (ESI 2), not "not breathing" (ESI 1).
_NOT_RIGHT = (r"(?! (?:well|right|normal\w*|properly|good|great|easily|easy|very well|ok|okay|fine|correctly|too fast|fast|hard"
              r"|heavy|heavily|funny|weird|strange|loud|noisy|through)\b)")
# "isn't responding" counts only with a person object or at the end ("not responding to antibiotics" does not).
_RESP_OBJ = r"(?: (?:to )?(?:me|us|anyone|anybody|anything|at all|when|her name|his name|their name|voice|touch|pain|questions)\b|\s*$|\s*[.,!;])"
_DRUGS = (r"tylenol|acetaminophen|paracetamol|ibuprofen|advil|motrin|aspirin|aleve|naproxen|benadryl|diphenhydramine|xanax|alprazolam|"
          r"valium|klonopin|ativan|benzos?|adderall|ritalin|oxy\w*|percocet|vicodin|hydrocodone|codeine|morphine|fentanyl|heroin|opioids?|"
          r"opiates?|methadone|suboxone|tramadol|lithium|seroquel|ambien|trazodone|melatonin|insulin|metoprolol|propranolol|amlodipine|"
          r"digoxin|warfarin|eliquis|xarelto|clonidine|iron|vitamins?|sleeping pills|pills?|tablets?|meds|medications?|medicines?|capsules|"
          r"gummies|edibles?|cough syrup|nyquil|dayquil|robitussin|prescription")
_CHEMICALS = _lex.HOUSEHOLD_CHEMICALS
_HISTORY = (r"(?:(?:\w+ ){0,2}(?:weeks?|months?|years?) ago|last (?:month|year)|in (?:19|20)\d\d"
            r"|in (?:jan\w*|feb\w*|march|april|june|july|aug\w*|sept?\w*|oct\w*|nov\w*|dec\w*))")
_CHILD_SLEEPY = _words(
    r"(?:very |really |so |extremely |super |unusually )?sleepy", r"letharg\w*", r"listless", r"drowsy", r"floppy", r"limp",
    r"(?:muy )?dormid[oa]", r"somnolient[oa]", r"no (?:se )?despierta", r"decaid[oa]", r"letargic[oa]",
    r"(?:won'?t|will not|doesn'?t|does not|hard to|difficult to|can'?t|cannot|barely) (?:wake|stay awake|keep (?:his|her|their) eyes open)",
    r"keeps? (?:falling asleep|nodding off)", r"not acting (?:right|normal|like (?:himself|herself|themselves))",
    r"not (?:himself|herself)", r"barely (?:awake|moving|responding)", r"not (?:responding|reacting)")

RULES: list[Rule] = [
    Rule(RESUS, _words(
        r"not breathing", r"isn'?t breathing", r"stopped breathing", r"no longer breathing", r"unrespons\w*", r"unconscious",
        r"(?:won'?t|will not|doesn'?t|does not|can'?t|cannot) wake (?:him|her|them)",
        r"(?:won'?t|will not) wake up", r"not waking up", r"no pulse", r"pulseless", r"cardiac arrest", r"heart (?:has )?stopped",
        r"cpr", r"code blue", r"apnea", r"apneic", r"blue lips",
        r"(?:lips|face|skin) " + _FILL + r"(?:turning |going )?blue", r"gasping", r"choking", r"drown\w*",
        r"hanged", r"hanging (?:himself|herself|myself|themselves)", r"tried to hang",
        # someone typing for a person who collapsed rarely writes "unresponsive"
        r"(?:isn'?t|is not|not|wasn'?t|was not|stopped|won'?t|will not|doesn'?t|does not|didn'?t|can'?t) (?:really |even )?"
        r"(?:responding|responsive|respond|answering|answer|reacting|react)" + _RESP_OBJ,
        r"(?:isn'?t|is not|wasn'?t|was not) (?:responding|responsive|answering|reacting)(?! to)",
        r"barely breathing", r"breathing (?:is |really |very |so |kind of |kinda ){0,2}(?:slow|slowly|agonal)",
        r"no heart ?beat", r"(?:can'?t|cannot|couldn'?t) (?:find|feel) (?:a |his |her |their )?pulse", r"out cold",
        r"(?:won'?t|will not|doesn'?t) come to",
        r"(?:lips|face|skin|mouth) " + _FILL + r"(?:turning |going )?(?:a little |kind of |kinda |slightly )?(?:blue|purple|gr[ae]y|dusky)",
        r"(?:he|she|they|baby) (?:is |was |'s )?gurgling|breathing (?:\w+ ){0,2}gurgl\w*",
        r"(?:umbilical )?cord (?:is )?(?:hanging|coming|sticking) out|prolapsed cord",
        r"(?:blue|purple|gr[ae]y) (?:around|on) (?:the|his|her|their|my) (?:lips|mouth)",
        r"(?:is|was|looks?|went|turned|turning|going|getting) (?:all |kind of |kinda |a little |really )?(?:blue|purple|gr[ae]y) and (?:not|isn'?t|wasn'?t|won'?t|can'?t|limp|floppy|cold|clammy)",
        r"turn(?:ing|ed)? (?:blue|purple|gr[ae]y)",
        r"(?:baby|infant|newborn) (?:\w+ ){0,4}(?:limp|floppy|lifeless)",
        r"(?:collapsed|fell|on the (?:floor|ground)) (?:\w+ ){0,4}(?:not|isn'?t|is not) moving",
        r"(?:fentanyl|heroin|opioids?|overdos\w*) (?:\w+ ){0,4}(?:blue|purple|gr[ae]y)\b",
        # a bystander who is not sure the person is breathing ("I don't think he's breathing")
        r"(?:(?:don'?t|do not) think|not sure|(?:can'?t|cannot|couldn'?t) (?:tell|see|hear|feel)(?: if| whether)?) (?:if |whether |that )?"
        r"(?:he|she|they|the baby|baby|my \w+|it)(?:'?s| is|'?re| are)? (?:still |even |really )?breathing" + _NOT_RIGHT,
        r"(?:doesn'?t|does not|don'?t|do not) (?:seem|look|appear|sound) (?:like )?(?:to be |(?:he|she|they)(?:'?s| is|'?re| are) )?breathing" + _NOT_RIGHT,
        r"(?:is|isn'?t) (?:he|she|the baby|baby|it) (?:even |still )?breathing" + _NOT_RIGHT,
        r"(?:his|her|their|the baby'?s|my \w+'?s) chest (?:isn'?t|is not|not|stopped|has stopped|stopped) (?:moving|going up and down|rising)",
        r"(?:not|isn'?t|is not) (?:moving|responding) (?:or|and|nor) (?:not )?breathing"),
        ignore=_ign(
            _NOT_WELL,
            r"(?:fingers?|toes?|toenails?|fingernails?|nails?|bruises?|feet|foot|hands?|knuckles?|veins?) (?:\w+ ){0,3}(?:turn\w*|go|goes|going|went|are|is|look|looks) (?:\w+ ){0,2}(?:blue|purple)",
            r"(?:lips|tongue|mouth|teeth) (?:\w+ ){0,3}(?:blue|purple) from (?:a |the |my |eating |drinking )?(?:\w+ )?(?:popsicles?|freezies?|slushies?|candy|blue raspberry|juice|gatorade|drinks?|berries|blueberries|markers?|lollipops?|icee)",
            r"cpr (?:class(?:es)?|certification|certified|card|course|training|instructor|form|recertification|dummy|mannequin)|(?:class|course|training|certification|instructor|took|taking|learning|teaching|teach) (?:in |for |a )?cpr",
            r"drown\w* in (?:homework|bills|work|debt|paperwork|stress|emails?|assignments|responsibilities|tests)|(?:phone|iphone|laptop|plants?|car|tablet) (?:\w+ ){0,2}drowned",
            r"chok\w* on (?:all )?(?:this |the |my )?(?:paperwork|homework|work|bills|laughter|laughing)",
            r"(?:was|were|had been) (?:choking|gasping) (?:\w+ ){0,4}(?:earlier|before|yesterday|last night|after (?:my |a )?(?:run|workout))(?:,? but| and)? (?:i'?m|im|he'?s|hes|she'?s|shes|they'?re|it'?s) (?:fine|ok|okay|better|good) now",
            r"(?:sleep|obstructive|central) apnea|apnea (?:machine|mask)",
            # a rash or an infection "not responding" to treatment is not a person who will not wake
            r"(?:infection|rash|cough|fever|eczema|acne|wound|cold|symptoms?|condition|skin|uti|sinus\w*|asthma|allerg\w*|blood pressure|bp|sugar|"
            r"headache|migraine|tooth|toothache|ear|pain|cut|sore|swelling) (?:is |was |has been |have been |are |were )?(?:still )?"
            r"(?:not|isn'?t|aren'?t|wasn'?t|hasn'?t been|haven'?t been|stopped|won'?t|doesn'?t|didn'?t) (?:\w+ )?(?:responding|reacting|respond|react)\w*",
            r"(?:not|isn'?t|wasn'?t|stopped|hasn'?t been|has not been) (?:responding|reacting) (?:well |at all )?to (?:the |my |his |her |any |this )?"
            r"(?:antibiotics?|meds?|medications?|medicines?|treatment|therapy|cream|ointment|inhaler|tylenol|ibuprofen|advil|motrin|drops|steroids?|prednisone|pills|shots?)"),
        examples=("My husband collapsed, he is not breathing", "My baby's lips are turning blue")),
    Rule(TRAUMA, _words(
        r"amputat\w*", r"dismember\w*", r"severed", r"degloving", r"chainsaw",
        r"(?:finger|thumb|toe|hand|foot|arm|leg|ear|nose)s? (?:got |was |is |were |are |has been )?(?:cut|chopped|sliced|sawed|ripped|torn|blown) off",
        r"(?:cut|chopped|sliced|sawed|ripped|tore|torn) off (?:my|his|her|their) \w+", r"exsanguinat\w*", r"hemorrhagic shock",
        r"spurting", r"blood (?:is )?(?:gushing|pouring|spraying)", r"(?:massive|uncontroll\w*|profuse|arterial|gushing) (?:bleed\w*|hemorrhag\w*|blood)",
        r"gunshot", r"gsw", r"(?:been|got|get|was|were|i'?m|he'?s|she'?s) shot",
        r"shot (?:in|through) (?:the|my|his|her) (?:chest|head|neck|stomach|belly|abdomen|back)", r"impale\w*",
        r"stab(?:bed)? (?:wound )?(?:to|in) (?:the |my |his |her )?(?:chest|abdomen|stomach|belly|neck|back|head)",
        r"(?:spurt|squirt|pump)\w* (?:\w+ ){0,2}blood|blood (?:is )?(?:spurt|squirt|pump|pour|gush|spray|shoot)\w*|pouring blood",
        r"(?:fingers?|thumb|toes?|hand|foot|ear|nose)s? (?:is |are |was |were )?(?:hanging|dangling) (?:off|by)",
        r"(?:knife wound|knifed|stab wound|stabbed(?: me| him| her)?) (?:\w+ ){0,1}(?:in|to) (?:the |my |his |her )?(?:chest|abdomen|stomach|belly|neck|back|head|side)"),
        ignore=_ign(
            r"(?:get|got|getting) shot (?:records?|with (?:a |an |the |my )?(?:nerf|bb|paintball|airsoft|water|flu|tetanus|covid|booster|vaccine|insulin|novocaine)|down)",
            r"shot (?:records?|card)", r"i'?m (?:so |just |totally )?shot\b(?! (?:in|through|by))", r"im (?:so |just |totally )?shot\b(?! (?:in|through|by))",
            r"(?:fishhook|fish hook|splinter|thorn|sliver|toothpick) (?:\w+ ){0,2}impale\w*|impale\w* (?:\w+ ){0,2}(?:fishhook|splinter|thorn)",
            r"(?:use|using|uses|run|running) (?:a )?chainsaw",
            r"amputat\w* (?:\w+ ){0,2}(?:years? ago|surgery|records?|stump)|(?:old|prior|previous|past) amputat\w*"),
        examples=("He was shot in the chest", "My finger got cut off by a saw")),
    Rule(STROKE, _words(
        r"stroke", r"(?:face|mouth|smile)\w* " + _FILL + r"droop\w*", r"droop\w* (?:face|mouth|smile)",
        r"(?:one|left|right) side of (?:my|his|her|their|the) (?:face|mouth|body) " + _FILL + r"(?:droop\w*|numb|weak|sag\w*|dead|paralyz\w*|limp|heavy)",
        r"face (?:is |looks )?(?:lopsided|crooked|uneven)", r"crooked smile", r"slurr\w*",
        r"speech (?:is |was |sounds |became )?(?:garbled|jumbled|strange|weird)",
        r"(?:can'?t|cannot|unable to) (?:get (?:my|the|his|her) words out|find (?:my|the) words)",
        r"words (?:are |come |came )?(?:out )?(?:jumbled|garbled|mixed up)",
        r"sudden(?:ly)? (?:\w+ ){0,3}(?:trouble|difficulty|can'?t) (?:talking|speaking|talk|speak)",
        r"sudden (?:weakness|numbness)", r"suddenly (?:went |felt |became |got |is |feels )?(?:weak|numb) on (?:one|the left|the right) side",
        r"(?:weak|numb)(?:ness)? (?:on|in|down) (?:the |my |his |her )?(?:left|right|one) side of (?:my|his|her|the) body",
        r"(?:can'?t|cannot) (?:move|feel|lift) (?:my|his|her) (?:left|right) (?:arm|leg|side)", r"hemipar\w*", r"aphasia",
        r"(?:face|arm|leg|body) (?:\w+ ){0,2}(?:numb|weak|droop\w*|limp) on (?:one|the left|the right) side",
        r"(?:face|mouth|smile)\w* " + _FILL + r"dropp\w*",
        r"(?:face|smile|mouth) (?:\w+ ){0,3}(?:weird|funny|droop\w*|dropp\w*|crooked|lopsided|uneven|numb|weak|slack) on (?:one|the left|the right) side",
        r"(?:talking|speaking|speech|talks|speaks) (?:is |sounds |was |got |all )?(?:funny|weird|strange|gibberish|nonsense|odd|wrong|slurry)",
        r"(?:can'?t|cannot|couldn'?t|unable to|not able to) (?:talk|speak) (?:right|properly|normally|clearly)",
        r"(?:words|speech) (?:are |is |keep |keeps )?(?:coming out |come out |came out )?(?:wrong|weird|funny|jumbled|garbled|mixed up|all wrong)",
        r"(?:sudden(?:ly)?|all of a sudden|woke up and|out of nowhere) (?:\w+ ){0,3}(?:can'?t|cannot|couldn'?t) (?:lift|move|raise|use|feel) (?:my|his|her|their) (?:\w+ )?(?:arm|leg|hand)",
        r"(?:can'?t|cannot|couldn'?t) (?:lift|move|raise|use|feel) (?:my|his|her|their) (?:\w+ )?(?:arm|leg|hand) (?:all of a sudden|suddenly)",
        r"(?:hand|arm|leg) (?:doesn'?t|does not|won'?t|isn'?t|stopped) work\w*(?! (?:well|right) since)",
        r"(?:can'?t|cannot|unable to) (?:move|feel) the (?:left|right) side of (?:my|his|her|their) (?:body|face)",
        r"(?:arm|leg|hand) (?:went|is|feels|has gone|suddenly went) (?:dead|limp|numb|weak) (?:\w+ ){0,4}face (?:feels|looks|is|went) (?:funny|weird|numb|droopy|strange|off)"),
        # Old strokes are history, but "had a stroke 2 hours ago" is happening now: only weeks, months or years count as old.
        ignore=_ign(
            r"heat ?stroke|sun ?stroke|(?:back|breast|swim\w*|brush|key|pen|heart) ?strokes?|stroke of (?:\w+ )?(?:luck|genius|fate|midnight|insight|brilliance)",
            # a lesson, video or worry about strokes is not a stroke now (unless the person says they have the signs)
            r"(?:strokes? (?:video|videos|movie|film|documentary|presentation|lesson|lecture|class|unit|awareness|month|ads?|commercial|poster|pamphlet|brochure"
            r"|quiz|test|exam|project|assignment|homework|essay|report|simulation|drill|training|education|seminar)"
            r"|(?:video|movie|film|documentary|lesson|lecture|class|presentation|article|show|episode|ad|commercial|poster|book|essay|report|project|unit|quiz"
            r"|homework|assignment|tiktok|youtube) (?:\w+ ){0,3}(?:about|on) (?:a |the )?strokes?"
            r"|(?:learn\w*|read\w*|stud\w*|teach\w*|taught|watch\w*|talk\w*) (?:\w+ ){0,2}about (?:a |the )?strokes?)"
            r"(?!(?:[ ,]+[\w']+){0,10}[ ,]+(?:having (?:one|a stroke)|same (?:signs|symptoms|thing)|those signs|these signs|the signs|has them|have them))",
            r"(?:worried|scared|afraid|nervous|anxious|paranoid|worry|fear) (?:\w+ ){0,3}(?:of|about) (?:getting |having )?(?:a )?strokes? "
            r"(?:someday|one day|in the future|later in life|when i'?m older|eventually|like (?:my|his|her) \w+)",
            r"(?:two|four|2|4).?stroke (?:engine|motor|oil)|(?:golf|tennis|rowing|putting|swimming|paint|piston) strokes?",
            r"strok(?:e|ed|es|ing) (?:the|my|his|her|its|their|our) (?:cat|dog|kitten|puppy|pet|horse|hair|beard|fur|back|arm|hand)",
            r"(?:had|have had|has had|suffered|survived) (?:a |an |two |several |his |her |my )?(?:mild |small |minor |mini |big |massive )?strokes? " + _HISTORY,
            r"(?:history of|previous|prior|old|past) (?:a |an )?(?:mild |small |minor |mini )?strokes?",
            r"stroke (?:survivor|risk|screening|prevention|clinic|rehab\w*|history|follow.?up)|risk (?:of|for) (?:a )?stroke|strokes? runs? in (?:my|the|our) family|family history of strokes?",
            r"(?:can'?t|cannot) (?:talk|speak) (?:\w+ ){0,3}(?:because of|from|due to) (?:my |a )?(?:sore throat|cold|laryngitis|cough|tooth|braces)"),
        examples=("My face is drooping and my speech is slurred", "Sudden weakness on the left side of my body")),
    Rule(CHEST, _words(
        r"chest (?:pain|pains|pressure|tightness|discomfort|heaviness)",
        r"(?:pain|pains|pressure|tightness|squeezing|heaviness|ache|aching|burning|discomfort|weight|band|vise|vice|belt|strap) (?:in|on|across|around) (?:(?:my|his|her|the) )?chest",
        r"chest " + _FILL + r"(?:hurt\w*|tight|heavy|crushing|squeez\w*|aching|aches|burning|on fire|pounding)",
        r"chest " + _FILL + r"(?:(?:mad|hella|super|real|really|so|very|kinda|kind of|a little|a bit|pretty|lowkey|highkey) )?(?:hurt\w*|tight\w*|heavy|crushing|squeez\w*|aching|aches|burn\w*|on fire|pounding|(?:funny|weird|strange|off|wrong)(?! when i cough| from (?:this |my |a )?(?:cold|cough)))",
        r"crushing (?:\w+ ){0,2}(?:pain|pressure|feeling)", r"heart attack", r"angina",
        r"(?:pain|ache|aching|numbness|pressure) (?:that )?(?:is )?(?:goes|going|radiat\w*|spread\w*|shoot\w*|moving|moves) (?:down|into|to|up) (?:my |his |her |the )?(?:left )?(?:arm|jaw|shoulder)",
        r"(?:an? )?(?:elephant|ton of bricks|something heavy|someone|brick|heavy weight|weight) (?:\w+ ){0,3}(?:on|sitting on|standing on|crushing|squeezing) (?:my|his|her|the) (?:chest|heart)",
        r"(?:my|his|her) heart (?:hurts|is hurting|aches|is aching|feels (?:tight|heavy|squeezed))|(?:pain|ache|aching|pressure|hurts?) in (?:my|his|her) heart|heart ?pains?",
        r"(?:grabb|clutch|hold|rubb|press|pound|thump|clench)\w* (?:at )?(?:his|her|my|their) chest",
        r"(?:jaw|neck) and (?:my |his |her )?left arm|left arm and (?:my |his |her )?jaw",
        r"indigestion (?:\w+ ){0,6}(?:sweat\w*|clammy)|(?:sweat\w*|clammy) (?:\w+ ){0,6}indigestion",
        r"chest (?:\w+ ){0,3}like (?:an? )?(?:elephant|ton of bricks|weight|vice|vise|someone)|chest (?:\w+ ){0,4}(?:squeezed|crushed|in a vise|in a vice)",
        r"(?:pain|pressure|tightness|squeezing|heaviness|ache|burning|discomfort|feeling) (?:\w+ ){0,2}(?:in|on|behind|under|across) (?:my |his |her |the )?(?:breastbone|sternum)",
        r"cp (?:and|with|\+) sob|sob (?:and|with|\+) cp",
        # heart pain described without the word "chest": nitro, "the same feeling as my stent", heartburn with clammy grey skin
        r"(?:took|taken|had to (?:take|use)|used|popped|tried|gave (?:him|her|me))(?: \w+){0,2} (?:nitro(?!us\b|gen\b)\w*|ntg)\b"
        r"(?!(?: \w+){0,3} (?:cold brew|coffee|brew|energy|drink|weeks? ago|months? ago|years? ago|last (?:week|month|year)))",
        r"(?:nitro(?!us\b|gen\b)\w*|ntg) (?:\w+ ){0,4}(?:didn'?t|did not|isn'?t|is not|not|hasn'?t|has not|doesn'?t|does not|won'?t|never) (?:\w+ )?(?:help\w*|work\w*|do anything|touch\w*|fix\w*)",
        r"(?:stents?|(?<!gastric )bypass|cabg|heart attacks?|angina|angioplasty|cardiac cath\w*|heart surgery) (?:[\w']+[ ,]+){0,14}(?:same|that|this|the) (?:\w+ ){0,3}"
        r"(?:feeling|pain|pressure|tightness|ache|sensation|band|squeez\w*|heaviness|thing) (?:\w+ ){0,3}(?:is |are |'s |has |have )?(?:back|again|return\w*|coming back|came back|started again)",
        r"(?:feels?|feeling|felt) (?:\w+ ){0,3}(?:like|same as|the same as) (?:\w+ ){0,3}(?:before|last time|when) (?:\w+ ){0,3}(?:my |the |a |his |her )?(?:stents?|(?<!gastric )bypass|heart attack|angina)\b",
        r"(?:stents?|(?<!gastric )bypass|heart attack|angina) (?:[\w']+[ ,]+){0,10}(?:feels?|feeling|felt) (?:\w+ ){0,2}(?:the same|exactly the same|just like (?:that|it|before|last time)|like (?:that|last time|before))",
        r"(?:heartburn|indigestion|acid reflux|reflux|gas pain) (?:[\w']+[ ,]+){0,10}(?:clammy|gr[ae]y|ashen|cold sweat|jaw|left arm|short of breath)"
        r"|(?:clammy|gr[ae]y|ashen|cold sweat) (?:[\w']+[ ,]+){0,10}(?:heartburn|indigestion|acid reflux)"),
        # A heart attack years ago, in the family, or "almost had a heart attack when I saw the bill" is not chest pain now.
        ignore=_ign(
            r"chest (?:cold|congestion|x-?rays?|hair|tube|of drawers|freezer|press|day|workout)",
            # ... unless it is "the same feeling is back"
            r"(?:had|has had|have had|survived) (?:a |an |his |her |my )?(?:mild |small |minor |massive |big )?heart attacks? " + _HISTORY
            + r"(?!(?:[ ,]+[\w']+){0,10}[ ,]+(?:same|again|back|like (?:that|it|this|then|last time|before)))",
            r"(?:nitro\w*|ntg) (?:\w+ )?(?:refill|prescription|script|bottle)",
            r"(?:history of|prior|previous|old|past) (?:a )?heart attacks?|(?:died|passed away|passed) (?:\w+ ){0,2}(?:of|from) (?:a )?heart attacks?",
            r"heart attacks? (?:run|runs) in (?:my|the|our) family|family history of heart attacks?",
            r"almost (?:had|gave me) a heart attack (?:when|from|because|at|seeing|over)|(?:gave|give|giving) me a heart attack",
            r"heart (?:hurts|aches|is aching|is broken) (?:\w+ ){0,3}(?:breakup|broke up|dumped|died|passed|miss\w*)"),
        examples=("Crushing chest pain down my left arm", "My chest hurts a lot")),
    Rule(BREATH, _words(
        r"can'?t breathe?", r"cannot breathe?", r"can not breathe?", r"unable to breathe?", r"couldn'?t breathe?",
        r"can'?t (?:catch|get) (?:my|his|her|a|their) breath", r"can'?t get (?:enough )?air", r"not getting (?:enough )?air",
        r"(?:hard|difficult|struggling|struggle|trouble|difficulty|problems?|hurts?) (?:to |with |)?breath\w*",
        r"(?:hard|difficult|tough) for (?:me|him|her|them|my \w+) to breathe?", r"(?:can )?barely (?:breathe?|catch (?:my|his|her) breath)",
        _NOT_WELL,
        r"breathing (?:is |feels |got |has gotten )?(?:really |very |so |super |kind of |kinda |too |way too )?(?:hard|difficult|labou?red|fast|rapid|shallow|noisy|deep and fast|fast and deep)",
        r"(?:harder|more difficult) (?:and harder )?to (?:breathe?|catch (?:my|his|her|their) breath)|breathing (?:is |keeps )?(?:getting|gotten) (?:harder|worse)",
        r"(?:can only|only able to) (?:say|speak|get out) (?:\w+ ){0,3}(?:a few|a couple|two|three|one|1|2|3) words?",
        r"(?:can'?t|cannot|unable to) (?:finish|complete|get through) (?:a |my |one |full |whole )?sentences? (?:\w+ ){0,4}(?:breath\w*|air)",
        r"short(?:ness)? of breath", r"breathless", r"dyspnea", r"suffocat\w*", r"air hunger",
        r"out of breath (?:at rest|sitting|lying down|just sitting|while resting)", r"wheez\w* (?:badly|a lot|really bad|so bad)",
        r"asthma attack", r"inhaler (?:isn'?t|is not|not|doesn'?t|does not) (?:working|helping)",
        r"(?:inhaler|albuterol|nebulizer|neb|puffer|ventolin|proair)\w* (?:\w+ ){0,2}(?:isn'?t|is not|not|doesn'?t|does not|didn'?t|did not|hasn'?t|has not|won'?t) "
        r"(?:\w+ )?(?:working|helping|work|help|doing (?:anything|much|a thing)|do (?:anything|much))",
        r"(?:inhaler|albuterol|nebulizer|neb|puffer|ventolin|proair)\w* (?:\w+ ){0,3}every (?:5|10|15|20|30|few|couple of|couple) min\w*",
        r"(?:used|using|took|taken|hit|hittin\w*|hitting) (?:my |his |her )?(?:inhaler|albuterol|puffer|neb\w*) (?:\w+ ){0,3}(?:\d+|several|many|a bunch of|so many) times "
        r"(?:\w+ ){0,4}(?:still|not helping|no help|didn'?t help|not working)",
        r"(?:not|haven'?t|hasn'?t|wasn'?t|weren'?t|isn'?t|never) (?:been )?able to (?:breathe?|catch (?:my|his|her) breath)",
        r"(?:couldn'?t|could not) (?:catch|get) (?:my|his|her|their|a) breath", r"(?:can'?t|cannot|couldn'?t) (?:get|take|catch) (?:a )?(?:full|deep|good|whole) breath",
        r"breathing (?:is |feels )?(?:really |very |so )?(?:weird|funny|strange|wrong|off)",
        r"(?:don'?t|do not) think (?:i'?m|im|i am|he'?s|hes|she'?s|shes|he is|she is|they'?re) breathing (?:right|well|normal\w*|properly|ok|okay)",
        # breathing distress in plain words: ribs or skin sucking in, a high noise breathing in, drooling and cannot swallow
        r"(?:intercostal |subcostal |suprasternal )?retractions|(?:chest|ribs?|belly|stomach|tummy|neck|throat) (?:is |are )?retracting",
        r"(?:skin|chest|belly|stomach|tummy|neck|throat|ribs?) (?:\w+ ){0,3}(?:suck\w*|pull\w*|sink\w*|cav\w*|tug\w*) (?:in|under|between|around|below) "
        r"(?:[\w']+ ){0,6}(?:breath\w*|ribs?|collar ?bones?|breastbone)",
        r"(?:see|seeing|showing) (?:all )?(?:his|her|their|the baby'?s|my) ribs (?:\w+ ){0,3}(?:when|every time|each time|with each|as) (?:\w+ )?breath\w*",
        r"(?:nostrils? (?:are |is )?flar\w*|flaring (?:his|her|their) nostrils|head bobb\w*) (?:[\w']+ ){0,4}(?:breath\w*|grunt\w*)"
        r"|(?:using|uses) (?:his|her|their|my) (?:belly|stomach|neck|shoulders?) (?:muscles )?to breathe",
        r"stridor|(?:high.?pitched|squeak\w*|squeal\w*|whistl\w*|crow\w*|honk\w*|harsh|seal.?like|gaspy|weird|strange|funny|scary|loud|noisy) (?:\w+ ){0,2}"
        r"(?:noise|sound|squeak|whistle)s? (?:\w+ ){0,4}(?:breath\w* in\b|inhal\w*|tries to breathe|trying to breathe|every (?:single )?breath|each breath)",
        r"(?:noisy|squeaky|whistling|crowing|high.?pitched) (?:breathing|breaths?) (?:in|when (?:he|she|they|i) breathes? in)",
        r"(?<!not )(?<!no )drool\w*[ ,]+(?:and |& )?(?:[\w']+[ ,]+){0,3}(?:can'?t|cannot|won'?t|unable to|not able to|hard to|trouble|refus\w* to) swallow\w*",
        r"(?:can'?t|cannot|won'?t|unable to|not able to|hard to|trouble) swallow\w*[ ,]+(?:and |& )?(?:[\w']+[ ,]+){0,3}(?<!not )(?<!no )(?<!isnt )(?<!isn't )drool\w*"),
        ignore=_ign(
            r"breath\w* (?:out of|through|with) (?:my|his|her|the|their|one) nose",
            r"nose (?:is )?(?:so |really |very )?(?:stuffy|blocked|congested|stuffed)(?: up)?(?: (?:\w+ ){0,2}(?:can'?t|cannot|hard to) breathe?)?",
            r"hard(?:er)? to breathe? through (?:it|my nose|his nose|her nose)", r"hurts to breathe? (?:in )?(?:cold air|through my teeth)",
            r"(?:nose|nostril|inhaler|cpap|machine|mask|retainer|braces|teeth|tooth) (?:\w+ ){0,4}(?:whistl\w*|noise|sound|squeak\w*)|snor\w*"),
        examples=("I can't breathe", "It's really hard to breathe")),
    Rule(ALLERGY, _words(
        r"anaphyla\w*", r"allergic reaction", r"severe allerg\w*", r"epi-?pen", r"epinephrine",
        r"(?:throat|lips?|tongue|mouth|face) " + _FILL + r"(?:swell\w*|swollen|puff\w* up)", r"throat " + _FILL + r"(?:closing|tight\w*)",
        r"(?:swelling|swollen|swelled) (?:up )?(?:of |in |on |around )?(?:my |his |her |the |their )?(?:throat|lips?|tongue|mouth|face)",
        r"(?:can'?t|cannot|hard to) swallow (?:my (?:own )?)?(?:spit|saliva)",
        r"angioedema", r"(?:tongue|throat) (?:feels |is |getting )?(?:thick|closing up)",
        r"swol+en shut", r"(?:face|lips?|tongue|throat) (?:is |are )?(?:blowing up|ballooning)",
        r"(?:can'?t|cannot|unable to|hard to) swallow (?:\w+ ){0,3}drool\w*|drool\w* (?:\w+ ){0,3}(?:can'?t|cannot|unable to) swallow"),
        # Past reactions, carrying an EpiPen, and swelling after dental work are not an allergic emergency now.
        ignore=_ign(
            r"(?:mild|minor|slight|small|little) allergic reactions?",
            r"(?:had|history of|get|gets|got) (?:an? )?(?:allergic reactions?|anaphyla\w*)(?: \w+){0,4} (?:as a (?:kid|child|baby|teen)|years? ago|in (?:19|20)\d\d|in the past|once)",
            r"(?:gives|give|gave) (?:me|him|her) anaphyla\w*|allergic to \w+(?: \w+){0,3} anaphyla\w*",
            r"allergic reactions? to (?:a |an |my |the )?(?:new )?(?:lotion|soap|detergent|shampoo|makeup|cream|jewelry|nickel|metal|tape|bandaid|band-aid|perfume|deodorant|sunscreen)(?!(?: \w+){0,5} (?:throat|tongue|lips|breath\w*|swell\w*|swollen))",
            r"(?:carry|carries|lost|refill\w*|renew\w*|replace\w*|expired|need)(?! to use)(?: \w+){0,4} epi-?pens?|epi-?pens? (?:refill|prescription|expired|is expired|ran out)",
            r"(?:mouth|face|cheek|jaw|gums?) (?:\w+ ){0,3}swollen (?:\w+ ){0,2}(?:after|from|since) (?:my |the |a |getting |having )?(?:wisdom teeth|dental work|dentist|root canal|extraction|filling|oral surgery|teeth (?:pulled|out))"),
        examples=("My throat is swelling after eating peanuts", "My lips and tongue are swollen")),
    Rule(BLEED, _words(
        r"severe(?:ly)? bleed\w*", r"heavy bleed\w*", r"bleed\w* (?:very |really |so )?(?:heavily|badly|a lot|so much|really bad|profusely|everywhere|nonstop|non-stop|like crazy|through)",
        r"(?:won'?t|will not|doesn'?t|does not|can'?t|cannot|isn'?t going to|wouldn'?t) stop bleed\w*",
        r"bleed\w* (?:that |and it |and )?(?:still )?(?:won'?t|will not|doesn'?t|does not|isn'?t|is not|has not|hasn'?t) (?:stop\w*|slow\w*)",
        r"(?:can'?t|cannot|couldn'?t) (?:get|make) (?:it|the bleeding|the blood) (?:to )?stop", r"blood (?:won'?t|will not|doesn'?t|does not|isn'?t|is not) stop\w*",
        r"keeps? (?:on )?bleeding", r"(?:a lot|lots|so much|tons|a ton) of blood", r"blood everywhere",
        r"soak\w* (?:through )?(?:\w+ ){0,2}(?:towels?|bandages?|pads?|gauze|shirt)", r"hemorrhag\w*", r"hemoptysis", r"hematemesis",
        r"(?:cough\w*|vomit\w*|throw\w* up|threw up) (?:up )?(?:\w+ )?blood", r"blood in (?:my |his |her )?(?:vomit|throw up)",
        r"bleed\w* (?:really |real |so )?bad\b",
        r"(?:won'?t|will not|doesn'?t|does not|can'?t|cannot) (?:stop|quit) bleed\w*", r"(?:puk\w*|spit\w*) (?:up )?(?:\w+ )?blood",
        r"melena|black (?:tarry |tar |sticky |and tarry )?(?:stools?|poops?|poo|bowel movements?)|(?:tarry|bloody) (?:stools?|poops?)",
        r"blood in (?:my |his |her |the )?(?:stool|poop|poo|toilet)", r"so much blood|too much blood|blood is everywhere",
        r"bleed\w* (?:thru|through) (?:\w+ ){0,2}(?:towels?|bandages?|pads?|gauze|shirt|clothes|sheets?|dressing)",
        r"soak\w* (?:thru|through) (?:\w+ ){0,3}(?:towels?|bandages?|pads?|gauze|shirt|clothes|sheets?|tampons?|dressing)"),
        ignore=_ign(r"(?:a lot|lots|tons|a ton|so much) of blood (?:work|tests?|draws?|pressure|sugar|panels?)",
                    r"heavy (?:period )?bleeding as usual", r"(?:keep|keeps) bleeding from (?:a )?(?:tiny |small |little |minor )?(?:paper )?cut",
                    r"(?:tiny|small|little|minor) (?:paper )?cut|paper cut",
                    r"(?:a lot|lots|so much|tons) of blood (?:\w+ ){0,6}(?:but|and) (?:it )?(?:has )?stopped"),
        examples=("I cut my hand on glass and it won't stop bleeding", "I'm bleeding a lot")),
    Rule(PREGNANCY, _words(
        r"pregnan\w*", r"\d+ weeks? along", r"expecting (?:a baby|twins)",
        r"(?:i'?m|im|i am|she'?s|shes|she is|wife is|we'?re) (?:only |about |almost |like |nearly )?(?:\d{1,2}|twenty[- ]?\w*|thirty[- ]?\w*) (?:weeks?|wks?)\b(?! old| out| post| after)",
        r"(?:i'?m|im|i am|she'?s|shes|she is|wife is) expecting\b",
        r"positive (?:pregnancy|preg|home) test|(?:pregnancy|preg) test (?:was|is|came back) positive|missed (?:my|her) period",
        r"postpartum|post-partum|gave birth|just had (?:a|my|the) baby|had (?:a|my|the) baby (?:\w+ ){0,2}(?:days?|weeks?) ago",
        r"(?:baby|head) is coming|can see the head|crowning"),
        # Real bleeding words only: "blood test", "blood pressure" and bleeding gums are not a pregnancy emergency.
        also=re.compile(_words(
            r"bleed\w*", r"bloody", r"spotting", r"blood (?:clots?|everywhere|coming|running|down)", r"leak\w* (?:fluid|water)",
            r"water (?:broke|has broken|just broke|is breaking|break)", r"gush of (?:fluid|water)",
            r"(?:severe|really bad|very bad|terrible|bad|sharp|stabbing|worst) (?:\w+ ){0,3}(?:pain|cramp\w*|headache)",
            r"pain (?:on|in) (?:my |the |one |her )?(?:\w+ )?(?:side|shoulder)", r"shoulder (?:pain|hurts)",
            r"(?:baby|fetus) (?:isn'?t|is not|not|stopped|hasn'?t been|has not been|hasn'?t|has not) (?:moving|kicking|moved)",
            r"(?:baby|babies) (?:\w+ ){0,3}(?:not moving|hasn'?t moved|has not moved|stopped moving|isn'?t moving|moving less|not kicking|stopped kicking)",
            r"(?:can'?t|cannot|don'?t|do not) feel (?:the |my )?baby (?:move|moving|kick\w*)",
            r"(?:less|no|decreased|reduced) (?:fetal )?movements?", r"contractions? (?:\w+ ){0,2}(?:\d+|one|two|three|four|five) min\w*",
            r"(?:seeing|see|saw) (?:spots|stars|flashing lights|flashes)", r"blurr\w* vision", r"(?:blurry|blurred|double|spotty) vision",
            r"vision (?:is )?(?:blurry|blurred|going)", r"(?:head|headache) (?:is )?(?:pounding|killing|splitting)",
            r"fell(?! asleep| behind)|fallen(?! asleep)|a fall|tripped", r"hit|kicked|punched|beat|beaten|shoved|pushed",
            r"(?:car|auto) (?:accident|crash|wreck)|accident|crash",
            r"can see the head|head is coming|baby is coming|crowning|urge to push", r"faint\w*|passed out", r"seiz\w*",
            r"fluid (?:\w+ ){0,2}(?:running|coming|leaking|gushing|pouring|dripping)",
            r"sang|sangr\w*|saign\w*").pattern
            # the same warning signs in the patient's own words (the form's pregnant flag is often the only English)
            + "|" + _deaccent(normalize(_lex.PREGNANCY_WARNING))),
        ignore=_ign(r"(?:not|isn'?t|am not|i'?m not|im not|never been) pregnant",
                    r"(?:gums?|nose|finger|toe|cut|scrape|lip|knee|tooth|teeth|mouth|ear|hemorrhoids?) (?:\w+ ){0,3}(?:bleed\w*|bloody)",
                    r"bleed\w* (?:\w+ ){0,2}(?:gums?|nose|when i brush)|nosebleeds?",
                    r"blood (?:test|tests|work|draw|pressure|sugar|type|count|glucose|panel)",
                    r"(?<!positive )(?<!positive blood )(?<!positive urine )(?:blood |urine )?pregnancy test(?!s? (?:was|is|came back|came out) positive)",
                    r"(?:had )?(?:a little |some )?spotting (?:\w+ )?(?:last (?:week|month)|weeks? ago|months? ago)"),
        examples=("I am 30 weeks pregnant and bleeding", "I'm 34 weeks and my water broke")),
    Rule(FAINT, _words(
        r"faint(?:ed|ing|s)", r"(?:feel|feels|feeling|felt) (?:(?:very|so|really|kind of|kinda|a bit|a little) )?faint",
        r"(?:dizzy|lightheaded|light-headed|light headed|weak|woozy) and faint", r"faint and (?:dizzy|lightheaded|light-headed|weak)",
        r"(?:going|about|gonna|might|want) to faint", r"i'?m (?:(?:so|very|really) )?faint", r"pass(?:ed|es|ing)? out",
        r"black(?:ed|ing|s)? out", r"blackouts?", r"syncop\w*", r"collaps\w*", r"los(?:t|ing|e) (?:\w+ )?conscious\w*",
        r"knocked (?:him |her |me |them )?out",
        r"next thing i (?:remember|knew|know)|woke up on the (?:floor|ground)|(?:found|find) (?:myself|him|her) on the (?:floor|ground)"),
        ignore=_ign(
            r"faint (?:rash|smell|odou?r|lines?|marks?|spots?|scar|bruise|sound|noise|taste|light|glow|colou?r|hint|trace|outline|ringing|itch|stain|memory|pink|red|yellow)",
            r"knocked out (?:\w+ )?(?:tooth|teeth)",
            r"(?:almost|nearly) (?:fainted|passed out) (?:from )?(?:laugh\w*|when i saw (?:the|my) (?:bill|price|grade|score))",
            r"(?:could|gonna|going to|about to|might) (?:pass out|faint|collapse) (?:from|with|of) (?:tired\w*|exhaustion|boredom|hunger)|so tired i could (?:pass out|faint|collapse)",
            r"pass\w* out (?:the |some |a |my |our |free )?(?:flyers?|candy|papers?|cards?|food|samples|invitations?|tests?|snacks|programs|menus|forms?|booklets?|brochures?|handouts?|presents|gifts)",
            r"collapsed (?:on|onto|into) (?:the |my )?(?:couch|bed|sofa|chair|recliner)",
            r"(?:tent|roof|ceiling|shelf|shelves|chair|table|bridge|arch|arches|vein|veins|deck|stage|trampoline|bed|box|boxes|fort|sandcastle|cake) (?:\w+ ){0,2}collaps\w*|collapsed (?:arch|arches|vein|veins)",
            r"(?:power|electricity|lights|screen|tv|phone) (?:\w+ ){0,2}black\w* out|blackout curtains?",
            r"(?:drank|drinking|drunk) (?:\w+ ){0,6}black(?:ed)? out (?:\w+ ){0,3}(?:hungover|hangover|fine now)",
            # a faint long ago is history ("fainted once two years ago"), unless it happened again now
            r"(?:(?:faint(?:ed|ing)?|pass(?:ed)? out|black(?:ed)? out|collapsed|lost consciousness|syncope) (?:once |twice |one time |a few times |a couple (?:of )?times |before )?"
            r"(?:(?:\w+ ){0,2}(?:weeks?|months?|years?) ago|last (?:month|year)|in (?:19|20)\d\d|as a (?:kid|child|teen\w*|baby)"
            r"|when i was (?:a kid|little|younger|a teen\w*|\d+|in (?:middle|high|elementary|grade) school)|back in (?:middle |high )?school|a long (?:while|time) ago)"
            r"|(?:\w+ )?(?:weeks?|months?|years?) ago (?:i|he|she|they) (?:fainted|passed out|blacked out|collapsed)"
            r"|(?:used to|use to) (?:faint|pass out|black out)|(?:history of|prior|previous|old) (?:\w+ )?(?:fainting|syncope|blackouts?|passing out))"
            r"(?!(?:[ ,]+[\w']+){0,6}[ ,]+(?:again|(?:and|then) (?:today|tonight|this morning|this afternoon|this evening|just now|an hour ago)|(?:faint|pass|black|collaps)\w*))"),
        examples=("I fainted at work", "I feel dizzy and faint")),
    Rule(HEAD, _words(
        r"(?:hit|bumped|banged|smacked|struck|whacked|slammed|knocked|hurt|injured|cracked) (?:\w+ ){0,2}head", r"head (?:injury|injuries|trauma|wound|first)",
        r"fell (?:\w+ ){0,6}head", r"concuss\w*", r"(?:blow|hit|kick\w*|knee|elbow) (?:to|in) the head"),
        also=_words(r"confus\w*", r"disorient\w*", r"not making sense", r"(?:isn'?t|doesn'?t|don'?t) make (?:any )?sense", r"acting (?:strange|weird|funny|odd|different|drunk)",
                    r"vomit\w*", r"throw\w* up", r"threw up", r"puk\w*", r"pass\w* out", r"black\w* out", r"knocked out", r"unconscious", r"lost consciousness",
                    r"(?:very |really |so )?sleepy", r"drowsy", r"can'?t (?:remember|stay awake)", r"memory", r"seiz\w*", r"blood thinners?",
                    r"warfarin|eliquis|xarelto|coumadin|plavix|apixaban|rivaroxaban", r"worst headache", r"(?:fluid|blood|bleeding) (?:from|out of) (?:his |her |my |the |their )?(?:nose|ears?)"),
        examples=("He fell off a ladder and hit his head and is confused",)),
    Rule(NECK, _words(r"stiff neck", r"neck (?:(?:is|feels|got|has|gotten|been|really|very|so|super) ){0,2}stiff",
                      r"(?:can'?t|cannot) (?:bend|touch|put|move) (?:my |his |her )?(?:chin|head|neck) (?:to|down|forward)",
                      r"neck (?:hurts|is painful|is sore|really hurts) (?:to|when i) (?:move|bend|turn)|(?:can'?t|cannot|hurts to) (?:move|bend|turn) (?:my |his |her )?neck"),
         also=_words(_FEVER, r"headaches?", r"head (?:hurts|is pounding|is killing)", r"light (?:hurts|bothers)", r"rash", r"chills"),
         examples=("Bad headache and fever for two days with a stiff neck",)),
    Rule(CHILD_FEVER, re.compile(_words(_FEVER_PLUS).pattern + "|" + _FEVER_ANY), child_under_months=60,
         also=_CHILD_SLEEPY, ignore=_NORMAL_TEMP,
         examples=("My 3 year old has a fever of 104 and is very sleepy",)),
    Rule(INFANT_FEVER, re.compile(_words(_FEVER_PLUS).pattern + "|" + _FEVER_ANY), child_under_months=3, ignore=_NORMAL_TEMP,
         examples=("My 6 week old baby has a fever",)),
    Rule(CRISIS, _words(
        r"suicid\w*", r"kill(?:ing)? (?:myself|my ?self)", r"end(?:ing)? (?:my|my own) life", r"end it all", r"tak(?:e|ing) my (?:own )?life",
        r"want(?:s|ed)? to die", r"wanna die", r"ready to die", r"wish (?:i|i'?d) (?:was|were|had been|could be) dead", r"better off dead",
        r"(?:don'?t|do not|no longer|doesn'?t) want to (?:live|be alive|be here anymore|exist|wake up)", r"no reason to live", r"not worth living",
        r"(?:want|wanted|going|trying|tried|urges?|thinking about|thoughts of|thoughts about|thought about) (?:to )?(?:hurt|harm|cut|kill|burn)(?:ing)? (?:myself|my ?self)",
        r"harm(?:ing)? myself", r"self.?harm\w*", r"(?:jump|jumping) (?:off|from) (?:a |the )?(?:bridge|building|roof)",
        # slang, plans and means
        r"kms", r"unaliv\w*",
        r"(?:want|wanna|going|gonna|might|plan|planning|ready|about) (?:to )?(?:just )?end (?:it|things|everything)\b(?! (?:with|between|off)\b)",
        r"(?:thinking (?:about|of)|want(?:s|ed)? to|going to|gonna|plan(?:ning)? to|ready to) end(?:ing)? (?:it|things|my life)\b(?! (?:with|between|off)\b)",
        r"end(?:ing)? it (?:all|tonight|today|now|for good)\b(?! (?:\w+ ){0,2}(?:with|between)\b)",
        r"(?:should|could|might as well|would rather|deserve to) (?:just )?(?:die|be dead)", r"(?:better|happier|easier) (?:off )?without me",
        r"(?:don'?t|do not|doesn'?t|does not|dont) (?:want|wanna) (?:to )?(?:live|be alive|be here anymore|exist|go on)",
        r"(?:no|don'?t see (?:the|any)|dont see (?:the|any)|what'?s the|whats the) point (?:in|of) (?:living|life|going on|being alive|being here)",
        r"(?:jump|step|walk|throw myself|run|lie down) (?:in front of|into|under|off of|off) (?:a |the )?(?:train|car|bus|truck|traffic|bridge|building|roof|cliff|overpass|balcony|tracks)",
        r"(?:use|turn|point|put) (?:it|the gun|a gun|my gun|the knife|a knife|them|the pills) (?:on|at|to) (?:myself|my ?self|my head)",
        r"goodbye (?:letters?|notes?|messages?|texts?)|suicide notes?|(?:bought|got|have) (?:a )?(?:rope|noose)",
        r"(?:saving|saved|stockpil\w*|hoard\w*|collecting) (?:up )?(?:my |all my |all of my )?(?:pills|meds|medications?|medicines?)",
        r"(?:take|swallow) (?:them|all of them|all my pills|them all|all my meds) (?:all )?at once",
        r"(?:plan|planning|plans) (?:to|on) (?:kill\w*|overdos\w*|end\w*|hang\w*|shoot\w*)",
        r"(?:cut|cutting|hurt|hurting|burn|burning|harm|harming) (?:myself|my ?self|my (?:arms?|wrists?|legs?|thighs?)) (?:\w+ ){0,2}(?:on purpose|deliberately|intentionally)",
        r"(?:cutting|burning) myself(?: again)?\b(?! (?:a|some)\b)", r"relapsed (?:\w+ ){0,2}(?:cut|cutting|self.?harm)\w*",
        r"(?:sleep|go to sleep|fall asleep) and (?:never|not) wake up", r"(?:want|wanted|wanna) to dye\b(?! (?:my|her|his|their|it|the|this|some|them)\b)",
        r"(?:keep )?thinking (?:i|that i) should (?:just )?die",
        r"(?:end|ending|take|taking) (?:his|her|their) (?:own )?life|kill(?:ing)? (?:himself|herself|themselves)|(?:hurt|harm|cut)(?:ing)? (?:himself|herself|themselves)",
        r"(?:scratch\w*|cut\w*|slic\w*) (?:my |his |her )?(?:arms?|wrists?|legs?|thighs?|skin) (?:\w+ ){0,2}(?:with )?(?:a )?(?:razor|blade|knife|glass|scissors)",
        # a plan with a place or a means, a written goodbye, being tired of living
        r"(?:jump|jumping|throw myself|throwing myself|leap|leaping) (?:off|from|out of|in front of) (?:of )?(?:a |the |my |our |that |this )?(?:top (?:floor )?of (?:a |the )?)?(?:\w+ ){0,2}"
        r"(?:bridge|building|roof|rooftop|garage|parking (?:structure|deck|ramp|lot)|overpass|cliff|balcony|tower|window|ledge|top floor|skyscraper|dam|stairwell|train|tracks|highway|freeway|traffic|subway)"
        r"(?! (?:\w+ ){0,3}into (?:the |a )?(?:pool|snow|foam|airbag|pile))",
        r"(?:plan\w*|going|gonna|want\w*|wanna|thinking (?:about|of)|thought (?:about|of)|ready|decided|tempted|urges?) (?:to |on )?(?:just )?jump\w* (?:off|from|in front of)"
        r"(?! (?:the |a |my )?(?:high )?(?:dive|diving board|board|swing|trampoline|bed|couch|stage|ramp|bleachers|dock|boat|pier|rope swing|wall|steps?|stairs|monkey bars))",
        r"(?:want\w*|wanna|going|gonna|plan\w*|thinking (?:about|of)|thought (?:about|of)|ready|tried|trying|try|urges? to|decided) (?:to |of |about |on )?"
        r"(?:shoot\w*|hang\w*|drown\w*|stab\w*|poison\w*|gas\w*|electrocut\w*|suffocat\w*) (?:myself|my ?self)\b(?! up\b| in the (?:foot|leg)\b)",
        r"nooses?",
        r"(?:wrote|written|writing|write|left|leaving|leave|typed|typing|recorded|recording) (?:a |my |some |the )?(?:goodbye|farewell|good.?bye|suicide) "
        r"(?:letters?|notes?|messages?|texts?|posts?|videos?)(?! (?:\w+ ){0,3}(?:coworker|co-worker|colleague|retire\w*|leaving|moving|party|team|boss|teacher|class))"
        r"|(?:my )?(?:final|last) (?:letters?|notes?|words) (?:to|for) (?:my family|everyone|everybody|the world|my kids|my parents)",
        r"(?:want|wanna|need|wish) (?:for )?(?:it all|everything|all of (?:it|this)|my life|life|this life|the world) (?:\w+ )?(?:to )?(?:stop|end|be over|go away)\b"
        r"(?! (?:hurting|aching|spinning|itching|burning|swelling|bleeding|moving|throbbing|ringing|for a (?:second|minute|bit|while)))",
        r"(?:tired|sick|exhausted) of (?:living|being alive|existing|life)\b(?! (?:in|at|with|here|there|paycheck)\b)|done with (?:living|life)\b"),
        # "never wanted to die BEFORE tonight" is a crisis, so it is not scrubbed.
        ignore=re.compile(
            r"\b(?:(?:not|never|no longer|isn'?t|wasn'?t|aren'?t|am not|i'?m not|denies|deny) (?:being |feeling )?(?:suicidal|homicidal)"
            r"|no (?:suicidal|homicidal|self.?harm) (?:thoughts|ideation|feelings|plans?)"
            r"|(?:don'?t|do not|doesn'?t|does not|didn'?t|did not|never) want(?:ed)? to die(?! (?:before|until|till|til)\b)"
            r"|want(?:s|ed)? to die (?:of|from) (?:embarrassment|shame|laughing|laughter)|(?:died|die|dying) (?:of|from) (?:embarrassment|laughing|laughter)"
            r"|(?:committed|attempted|died by) suicide (?:\w+ ){0,2}(?:last (?:year|month)|years? ago|months? ago|in (?:19|20)\d\d)"
            # "no thoughts of hurting myself", "I would never hurt myself", "not thinking about ending my life"
            r"|(?:no|not|never|without|denies|deny|don'?t have|do not have|haven'?t had|have not had|never had|not having|no current|no recent) (?:any )?(?:\w+ ){0,2}"
            r"(?:thoughts?|ideas?|urges?|plans?|intentions?|intent|desire|wish|wishes|feelings?) (?:of|about|to|for) (?:suicide|self.?harm|(?:hurting|harming|killing|cutting|ending|hurt|harm|kill|cut|end) (?:myself|my ?self|my life))"
            r"(?! (?:until|till|til|before|lately|recently|but)\b)"
            r"|(?:not|never|no longer|isn'?t|am not|i'?m not|im not) (?:been )?(?:thinking|thought) (?:about|of) (?:suicide|self.?harm|(?:hurting|harming|killing|ending) (?:myself|my life))(?! (?:until|till|before|but)\b)"
            r"|(?:would|will|could) never (?:hurt|harm|kill) myself(?!(?:[ ,]+[\w']+){0,6}[ ,]+(?:until|till|but now|now i|anymore)\b)"
            r"|(?<!promise )(?<!sure )(?:i'?m|im|i am) not (?:going to|gonna|trying to|planning to|planning on) (?:hurt|harm|kill)(?:ing)? myself"
            r"|no (?:self.?harm|suicid\w*)(?: \w+)?|not (?:self.?harming|cutting myself)|(?:no|denies|deny) (?:si|hi|si or hi|si/hi)"
            r"|never (?:tried|attempted) (?:to )?(?:kill myself|suicide)(?! (?:before|until|till)\b))\b"),
        examples=("I feel like I want to end my life", "I don't want to live anymore")),
    # Goodbye letters to family, with words of giving up, are a written plan.
    Rule(CRISIS, _words(
        r"(?:wrote|written|writing|left|leaving|typed) (?:\w+ ){0,2}(?:letters?|notes?) (?:to|for) (?:my |each of my |all my |everyone in my )?"
        r"(?:family|kids|children|parents|mom|dad|mum|wife|husband|partner|friends|everyone|everybody|loved ones|sister|brother|son|daughter|boyfriend|girlfriend)"),
        also=_words(r"(?:want|wanna|wish) (?:\w+ ){0,3}(?:stop|end|over|gone|die|dead|disappear)", r"in case (?:i|something)", r"(?:when|after|once) i'?m gone",
                    r"(?:can'?t|cannot) (?:do this|go on|take it)", r"say(?:ing)? goodbye|goodbye|sorry for everything|forgive me", r"(?:no|nothing) (?:point|reason)",
                    r"(?:tired|done|exhausted) (?:of|with) (?:it|this|everything|life|living)"),
        examples=("I wrote letters to my family last night and I just want everything to stop",)),
    Rule(OVERDOSE, _words(
        r"overdos\w*", r"(?:took|taken|swallowed|ate|drank|downed) (?:\w+ ){0,2}(?:whole|entire|full) (?:bottle|pack|packet|box|strip|container|sleeve)",
        r"(?:took|taken|swallowed|ate|downed) (?:too many|a lot of|lots of|a bunch of|a handful of|a whole bunch of|a ton of|all (?:of )?(?:my|his|her|their|the)) (?:\w+ ){0,2}(?:pills|tablets|meds|medications?|medicines?|capsules|gummies)",
        r"(?:took|taken|swallowed|downed) (?:like |about |around )?(?:\d{2,}|twenty|thirty|forty|fifty|a hundred) (?:\w+ ){0,3}(?:pills|tablets|capsules)",
        r"(?:swallowed|ate|drank|took) (?:some |a |a lot of |a bunch of )?(?:bleach|poison|antifreeze|drain cleaner|rat poison|(?:detergent|laundry|tide) pods?|button batter(?:y|ies)|lighter fluid|gasoline|lamp oil)",
        r"poison(?:ed|ing)",
        # a drug name is enough; "pills" is not needed
        r"(?:took|taken|swallowed|ate|drank|downed|popped|got into|chugged|chewed) (?:like |about |around |maybe |almost |over |at least |way |far )?"
        r"(?:\d{2,}|\d+ or \d+|ten|fifteen|twenty|thirty|forty|fifty|a hundred|a handful of|a bunch of|a lot of|lots of|too many|too much|"
        r"all (?:of )?(?:my|his|her|their|the)|(?:my|his|her|the|a) whole (?:\w+ )?(?:bottle|pack|box|prescription|supply|script)(?: of)?) (?:\w+ ){0,3}?(?:" + _DRUGS + r")",
        r"(?:toddler|baby|kid|child|son|daughter|grandson|granddaughter|\d+ (?:year|yr|month) old|little one) (?:\w+ ){0,3}"
        r"(?:ate|swallowed|drank|got into|chewed|took) (?:\w+ ){0,5}(?:" + _DRUGS + r"|patch|gummy|weed|thc|marijuana|vape juice|e-?liquid|"
        r"nicotine|washer fluid|windshield (?:washer )?fluid|cleaner|soap|detergent|bleach|essential oils?|hand sanitizer|mouthwash|magnets?|batter(?:y|ies)|coin cells?)",
        r"(?:swallowed|swallow|ate|drank) (?:\w+ ){0,5}(?:magnets?|batter(?:y|ies)|coin cells?|vape juice|e-?liquid|nicotine|(?:windshield )?washer fluid|cough syrup)",
        r"(?:snort\w*|inject\w*|shot up|smok\w*) (?:\w+ ){0,3}(?:fentanyl|heroin|carfentanil|opioids?)",
        r"(?:ate|swallowed|chewed) (?:\w+ ){0,3}fentanyl patch",
        # household chemicals, by any person: "drank something from under the sink"
        r"(?:drank|drink|drinking|swallowed|swallow|ate|eaten|eating|got into|chugged|sipped|had (?:a )?(?:sip|mouthful) of|ingested|gulped|downed|bit|bit into|chewed)"
        r" (?:(?!and |then |with |while |after |before |when |but |to )[\w']+ ){0,4}?(?:" + _CHEMICALS + r")"),
        ignore=_ign(r"food poison\w*|poison (?:ivy|oak|sumac)", r"lead poisoning test|(?:test|tested|screen\w*) for lead",
                    r"poisoned by (?:poison )?(?:ivy|oak|sumac)",
                    r"(?:chicken|sushi|food|meat|fish|eggs?|burger|salad|restaurant|takeout) (?:\w+ ){0,2}poisoned (?:me|us)",
                    r"(?:got )?poisoned by (?:bad |old )?(?:sushi|food|chicken|meat|fish|eggs?|takeout)",
                    r"overdos\w* on (?:cheesecake|candy|sugar|cake|chocolate|pizza|netflix|sleep|sun)"),
        crisis_if=re.compile(r"\bi (?:just )?(?:took|swallowed|ate|drank|downed|overdosed)\b|\bi'?ve (?:just )?(?:taken|swallowed|overdosed)\b"
                             r"|\b(?:on purpose|intentionally|deliberately)\b|\bafter (?:a |an )?(?:big |bad |huge )?(?:fight|argument|breakup|break ?up)\b"
                             r"|\bto (?:kill|hurt|harm|end) (?:herself|himself|themselves|myself|it all|her life|his life|my life)\b"),
        examples=("I took a whole bottle of tylenol", "My toddler swallowed a laundry pod")),
    Rule(SEIZURE, _words(
        r"seiz(?:ure|ures|ing|uring)", r"(?:he|she|they|i|baby|son|daughter|kid|child|husband|wife|dad|mom) seized\b(?! up)",
        r"convuls\w*", r"(?:having|had|has) (?:a )?(?:seizure )?fit", r"(?:is|was|keeps|started|been) fitting\b(?! (?:room|in|into|for|well|me|the|a)\b)",
        r"status epilepticus", r"grand mal|tonic.?clonic|petit mal|epileptic (?:fit|attack|episode)", r"foaming at the mouth",
        r"(?:jerking|twitching|shaking|convulsing) (?:\w+ ){0,3}(?:all over|uncontrollabl\w*)|eyes (?:are |were )?(?:rolled|rolling) (?:back|up)"),
        ignore=re.compile(
            r"\b(?:(?:anti-?)?seizure|epilepsy) (?:medications?|meds|medicines?|pills|prescriptions?|refills?)\b|\bhistory of seizures\b"
            r"|\b(?:had|have had) (?:a |an |two |several )?seizures? (?:(?:\w+ ){0,2}(?:weeks?|months?|years?) ago|last (?:month|year)|in (?:19|20)\d\d"
            r"|as a (?:kid|child|teen\w*|baby|toddler))\b"
            r"|\blast seizure (?:was )?(?:(?:\w+ ){0,2}(?:weeks?|months?|years?) ago|in (?:19|20)\d\d|last (?:month|year))"
            r"|\bhad a fit (?:when|at|over|about|because|in (?:the|a|my) (?:store|car|shop|restaurant|mall|parking lot))\b"
            r"|\b(?:\w+ )?seized up\b"),
        examples=("My son had a seizure",)),
    Rule(ONE_SIDE, _words(
        r"(?:left|right) (?:arm|side|leg) (?:(?:is|feels|went|has|gone|got|suddenly|keeps|kind of|kinda|pretty|a little|really|so|all) ){0,3}(?:going |getting )?(?:weak|numb|limp|dead|tingl\w*|paralyz\w*|heavy)",
        r"(?:weak|numb|tingl\w*)(?:ness|ing)? (?:in|on|down) (?:my |his |her |the )?(?:left|right) (?:arm|side)"),
        ignore=_ign(r"(?:left|right) (?:arm|hand|leg|side)s? (?:\w+ ){0,3}(?:tingl\w*|numb|dead|asleep) (?:\w+ ){0,2}(?:after|from) (?:sleeping|laying|lying) on (?:it|my \w+)|slept on (?:it|my \w+)(?: wrong)?"),
        examples=("My left arm is numb",)),
    Rule(HIGH_RISK, _words(
        r"sepsis", r"septic", r"open fracture", r"compound fracture", r"bone (?:is )?(?:sticking|poking|coming) (?:out|through)",
        r"worst headache", r"thunderclap", r"worst pain (?:of|in) (?:my|his|her) life",
        r"sudden(?:ly)? (?:\w+ ){0,2}(?:can'?t see|lost (?:my |his |her )?(?:vision|sight)|went blind|blind)",
        r"(?:lost|losing) (?:my |his |her )?(?:vision|sight) (?:suddenly|all of a sudden)", r"testic\w* (?:torsion|twist\w*)",
        r"ectopic", r"miscarr\w*", r"(?:chemical|acid|bleach) (?:in|splash\w* (?:in|into)) (?:my |his |her |the )?eyes?", r"electrocut\w*",
        r"severe(?:ly)? burn\w*", r"burn\w* (?:on|to) (?:my |his |her |the )?face",
        # eyes and vision
        r"(?:chemical|acid|bleach|lye|ammonia|drain cleaner|oven cleaner|cleaner|pepper spray|bear spray|lime|cement|concrete|degreaser|solvent|battery acid) (?:\w+ ){0,3}(?:in|into) (?:my |his |her |the |both )?(?:face and )?eyes?",
        r"(?:sudden(?:ly)?|all of a sudden) (?:\w+ ){0,3}(?:loss of (?:vision|sight))|sudden loss of (?:vision|sight)",
        r"(?:can'?t|cannot) see (?:out of|in|from) (?:my |his |her )?(?:left|right|one) eye",
        r"(?:curtain|shade|veil|blackness|darkness) (?:\w+ ){0,3}(?:over|in|across) (?:my |his |her )?(?:left |right |one )?(?:eye|vision)",
        r"(?:vision|everything|sight) went (?:\w+ ){0,2}(?:dark|black) in (?:my |his |her )?(?:left|right|one) eye",
        # testicle and other surgical emergencies
        r"(?:testic\w*|testes|scrot\w*|(?:my|his) balls?|(?:my|his) nuts|(?:my|his) ball) (?:\w+ ){0,3}(?:pain|hurts?|hurting|swollen|swelling|twist\w*|torsion)",
        r"(?:pain|hurts?|swelling|swollen) (?:\w+ ){0,3}(?:testic\w*|testes|scrot\w*|(?:my|his) balls?|(?:my|his) nuts)",
        r"(?:hit|kicked|kneed) in the (?:nuts|balls|groin) (?:\w+ ){0,6}(?:swollen|purple|threw up|vomit\w*)",
        r"priapism|erection (?:\w+ ){0,3}(?:hours|won'?t go away)|ovarian torsion|torsion",
        r"(?:belly|abdomen|stomach) (?:is )?(?:rigid|hard as a (?:board|rock)|board.?like)",
        r"worst (?:\w+ ){0,2}pain (?:of|in) (?:my|his|her) life",
        r"sudden\w* (?:\w+ ){0,3}(?:severe|really bad|terrible|worst|excruciating|horrible) (?:\w+ ){0,2}(?:belly|stomach|abdominal|abdomen|back) pain",
        r"tearing (?:\w+ ){0,3}pain|ripping (?:\w+ ){0,3}pain|pain (?:\w+ ){0,3}(?:like something (?:ripped|tore)|tearing|ripping)|aortic dissection|dissecting aneurysm",
        r"(?:leg|arm|foot|hand) (?:is |feels |went |turned )?(?:\w+ ){0,2}(?:cold and (?:pale|blue|white|numb)|pale and cold)",
        # headache wording
        r"headache\w*[,.]? (?:\w+[,.]? ){0,6}worst (?:one )?(?:i'?ve|i have|ive|ever)|worst (?:\w+ ){0,2}headache",
        r"(?:feel|feels|feeling) like (?:i'?m|im|i am) (?:going to|gonna|about to) die\b(?! (?:of|from)\b)|sense of (?:impending )?doom",
        # burns
        r"(?:boiling|scalding) (?:water|oil|grease|coffee|soup) (?:\w+ ){0,6}(?:on|onto|over|all over) (?:my|his|her|their|him|her|them|herself|himself|myself)",
        r"(?:burn\w*|scald\w*) (?:\w+ ){0,3}(?:whole|entire|both) (?:arm|arms|leg|legs|back|chest|body|face|hand|hands)",
        r"skin (?:is )?(?:peeling|coming|falling) off", r"burn\w* (?:my|his|her|their) (?:face|eyes?|neck|mouth|throat)",
        r"(?:voice|throat) (?:\w+ ){0,2}(?:hoarse|raspy) (?:\w+ ){0,5}(?:fire|smoke)|(?:fire|smoke) (?:\w+ ){0,6}(?:hoarse|raspy|singed|soot)",
        # poisoning by gas, heat
        r"carbon monoxide|co (?:alarm|detector|monitor|poisoning)|gas leak|smoke inhalation|chlorine gas|toxic (?:fumes|gas)|bleach and ammonia|mix\w* (?:\w+ ){0,2}bleach (?:and|with) (?:ammonia|vinegar)",
        r"(?:whole family|we all|all of us|everyone (?:in|at) (?:the|my|our) (?:house|home|family)|my whole house) (?:\w+ ){0,4}(?:headaches?|dizzy|sick|throwing up|vomiting|nauseous|confused)",
        r"(?:have|has|got|getting|having|with|from|think (?:i|he|she) (?:have|has|got)) (?:a )?(?:heat ?stroke|sun ?stroke)", r"(?:stopped|not|isn'?t|quit|no longer) sweating",
        # sugar, vital signs and lab values typed in
        r"ketoacidosis|dka|ketones? (?:are |is )?(?:high|large|moderate)",
        r"(?:blood )?(?:sugar|glucose|bg) (?:\w+ ){0,2}(?:is |was |of |at |dropped to |reading |reads |says )?(?:[1-5]\d)\b(?! (?:years?|units?|percent|minutes?|hours?|days?|grams?))|hypoglycemi\w*",
        r"(?:heart rate|hr|pulse|heartrate|heart) (?:\w+ ){0,2}(?:is |of |at |was |over |above )?(?:1[4-9]\d|2\d\d)\b(?! (?:during|after|when|while) (?:my |a |the )?(?:workout|run|running|exercise|practice|game))", r"tachycardi\w*|svt|rvr",
        r"(?:oxygen|o2|spo2|sats?|saturation|pulse ox|pulse oximeter) (?:\w+ ){0,3}(?:is |of |at |was |says |reads |shows |dropped to )?(?:[5-8]\d|9[01])\b(?! years?)",
        r"(?:bp|blood pressure|pressure) (?:\w+ ){0,2}(?:is |of |at |was )?(?:[4-8]\d) ?(?:over|/) ?\d{2}\b(?!(?: \w+){0,4} (?:normal|always|usually|baseline))",
        r"(?:bp|blood pressure) (?:\w+ ){0,2}(?:is |of |at |was )?(?:1[89]\d|2\d\d) ?(?:over|/) ?\d{2,3} (?:\w+ ){0,4}(?:headache|vision|confus\w*|chest|short of breath|numb|weak)",
        r"potassium (?:\w+ ){0,2}(?:is |of |at )?(?:[6-9](?:\.\d)?)\b|hemoglobin (?!a1c)(?:\w+ ){0,2}(?:is |of |at )?(?:[1-6](?:\.\d)?)\b",
        r"sickle cell (?:\w+ ){0,3}(?:crisis|pain|fever|chest|breath)|(?:pain )?crisis (?:\w+ ){0,3}sickle|vaso.?occlusive",
        # infection
        r"meningitis|encephalitis|necrotizing|flesh.?eating|neutropeni\w*",
        r"(?:fever|temp\w*|10[0-5](?:\.\d)?) (?:\w+ ){0,5}(?:chemo\w*|transplant)|(?:chemo\w*|transplant) (?:\w+ ){0,6}(?:fever|temp\w*|10[0-5](?:\.\d)?)",
        r"(?:rash|spots) (?:\w+ ){0,3}(?:looks? like bruises|(?:doesn'?t|does not|won'?t) (?:fade|go away|blanch|turn white) when (?:i |you )?(?:press|push))|purpur\w*|petechia\w*|non.?blanching",
        # spine and nerves
        r"(?:can'?t|cannot|couldn'?t) (?:feel|move) (?:my|his|her|their|both) legs|numb (?:between|in) (?:my )?(?:legs|groin|saddle|crotch)|saddle (?:numbness|anesthesia)",
        r"(?:can'?t|cannot|lost) control (?:of )?(?:my )?(?:bladder|bowels?)",
        # injury mechanisms
        r"(?:hit|struck|run over|ran over) by (?:a |an |the )?(?:car|truck|bus|van|suv|vehicle|train|motorcycle)|(?:got |was |were )?run over",
        r"(?:motorcycle|motorbike|dirt bike|atv|car|truck|bike|bicycle) (?:crash|accident|wreck)(?!(?: \w+){0,3} (?:ago|last (?:week|month|year)|in (?:19|20)\d\d))|(?:hit|went through|smashed into) the windshield|(?:ejected|thrown) from (?:the |a )?(?:car|vehicle)",
        r"fell (?:\w+ ){0,3}(?:roof|balcony|(?:second|2nd|third|3rd) (?:floor|story)|scaffold\w*|cliff)|fell (?:about |like |over )?(?:\d{2,}|ten|fifteen|twenty|thirty) (?:feet|ft|foot)",
        r"(?:(?:got |been |was |were |i'?m |im |he'?s |she'?s )?(?:stabbed|knifed)|stab(?:bed)? wound|knife wound|stabbed (?:me|him|her|them))(?! (?:\w+ ){0,2}(?:by|with) (?:a |an |the |my )?(?:cactus|pencil|pen|fork|thorn|splinter|toothpick|needle|stick|branch|plant|rose))",
        r"(?:hand|arm|finger|fingers|leg|foot) (?:\w+ )?(?:got )?(?:caught|crushed|stuck) (?:in|under) (?:a |the )?(?:machine|meat slicer|slicer|press|conveyor|auger|wood chipper|chipper|lawn ?mower|snowblower|snow blower|forklift)|crush\w* (?:in|by|under) (?:a |the )?(?:machine|press|car|forklift)",
        r"(?:snake|rattlesnake|rattler|copperhead|cottonmouth|water moccasin|coral snake|viper) (?:\w+ ){0,2}(?:bit|bite|bitten)|bit(?:ten)? by a (?:\w+ )?(?:snake|rattlesnake|rattler|copperhead|cottonmouth|scorpion|black widow|brown recluse)|snake ?bite",
        r"(?:shock\w*|zapped) (?:\w+ ){0,3}(?:power line|live wire|high voltage|electric\w*|outlet|transformer|third rail)|electric(?:al)? shock|struck by lightning|lightning strike",
        r"fell through (?:the )?ice|(?:under ?water|submerged|in the water) for (?:\w+ ){0,2}(?:minutes?|a while)|near.?drown\w*|almost drowned",
        # withdrawal, clots, missed dialysis
        r"delirium tremens|dts|alcohol withdrawal|(?:stopped|quit|cut back on|ran out of) (?:drinking(?! (?:soda|coffee|caffeine|energy drinks?|pop|tea|milk|juice))|alcohol|my xanax|benzos|xanax|klonopin) (?:\w+ ){0,6}(?:shak\w*|tremor\w*|seeing things|hallucinat\w*|sweat\w*|seiz\w*)",
        r"withdrawal (?:\w+ ){0,3}(?:shak\w*|seiz\w*|seeing things|hallucinat\w*)",
        r"pulmonary embol\w*|blood clot (?:in|to) (?:my |the )?lungs?",
        r"dialysis (?:\w+ ){0,6}missed|missed (?:\w+ ){0,3}dialysis"),
        ignore=_ign(r"septic (?:tank|system|field|line|pump)"),
        examples=("Worst headache of my life, it came on suddenly",)),
    # New confusion is ESI 2 (ESI handbook decision point B), not only after a head injury.
    Rule(ALTERED, _words(
        r"(?:is|seems|got|getting|became|acting|really|very|so|suddenly|now|and|im|i'?m|hes|he'?s|shes|she'?s) (?:\w+ ){0,2}confus(?:ed|ion)\b(?! (?:about|by|with|on|over)\b)",
        r"(?:not|isn'?t|doesn'?t|don'?t) mak(?:e|ing) (?:any )?sense",
        r"(?:can'?t|doesn'?t|does not|didn'?t) (?:tell me|know) (?:what (?:year|day)|where (?:he|she|they|i) (?:is|am|are)|who i am)",
        r"disoriented|delirious|(?:really|very|so|completely|totally|super) out of it", r"talking (?:gibberish|nonsense|crazy)",
        r"(?:not|isn'?t) acting (?:right|normal|like (?:himself|herself|themselves))",
        r"acting (?:strange|weird|funny|odd|different|drunk)\b(?! (?:about|lately|sometimes|recently|at school|toward|towards|with)\b)",
        r"barely awake|hard to wake|(?:won'?t|can'?t) stay awake", r"seeing things|hallucinat\w*",
        r"(?:can'?t|cannot) remember anything",
        r"(?:suddenly|all of a sudden|since (?:this morning|today|yesterday|last night)) (?:\w+ ){0,3}(?:confus\w*|disorient\w*|not making sense)",
        r"(?:confus\w*|disorient\w*) (?:\w+ ){0,3}(?:suddenly|all of a sudden|since (?:this morning|today|yesterday|last night))",
        r"(?:doesn'?t|does not|didn'?t|can'?t) (?:know where (?:she|he|they) (?:is|are)|recogni[sz]e (?:me|us|anyone|anybody))",
        r"not (?:acting like )?(?:himself|herself)"),
        ignore=_ign(r"(?:a little |sometimes |always |usually |often )?confused (?:sometimes|at times|a lot lately)"
                    r"|(?:its|it'?s|that'?s|which is) (?:normal|usual|baseline) for (?:her|him|them)|(?:has|with|from) (?:dementia|alzheimer\w*)"),
        examples=("My grandma is suddenly confused and does not know where she is",)),
    # Danger to others is ESI 2 but not the 988 suicide card.
    Rule(DANGER_OTHERS, _words(
        r"homicidal",
        r"(?:want|wanna|going|gonna|planning|plan|urges?|thoughts? (?:of|about)|thinking (?:of|about)|telling me|told me) (?:to )?(?:hurt|harm|kill|stab|shoot|strangle|attack|murder)(?:ing)? "
        r"(?:my \w+|him|her|them|someone|somebody|people|everyone|other people|others|everybody)\b",
        r"voices? (?:are |keep )?(?:telling|tell|told) me to"),
        ignore=re.compile(
            _ign(r"(?:kill|murder) (?:my \w+|him|her|them) (?:\w+ ){0,6}(?:lol|lmao|jk|haha)").pattern
            + r"|\b(?:(?:not|never|no longer|isn'?t|wasn'?t|aren'?t|am not|i'?m not|denies|deny) (?:being |feeling )?homicidal"
            r"|no homicidal (?:thoughts|ideation|feelings|plans?)"
            r"|(?:no|not|never|without|don'?t have|do not have) (?:any )?(?:\w+ ){0,2}(?:thoughts?|ideas?|urges?|plans?|intentions?) (?:of|about|to) (?:hurting|harming|killing|hurt|harm|kill) "
            r"(?:anyone|anybody|someone|somebody|others|other people|people|him|her|them|my \w+)"
            r"|(?:would|will) never (?:hurt|harm|kill) (?:anyone|anybody|someone|others|him|her|them))\b"),
        examples=("I keep having thoughts about hurting someone",)),
    Rule(ASSAULT, _words(
        r"raped|rape|sexually assaulted|sexual(?:ly)? assault\w*|molest\w*|roofied|drugged (?:me|my drink)|(?:put|slipped) something in my drink",
        r"(?:step ?dad|stepfather|step ?mom|uncle|cousin|teacher|coach|grandpa|grandfather|neighbor|(?:mom|moms|mother'?s) boyfriend|babysitter|pastor) (?:\w+ )?touched me",
        r"touched me (?:inappropriately|down there|without (?:my )?(?:consent|permission))",
        r"strangl\w*|chok(?:ed|ing) me(?: out)?|choked (?:\w+ )?out|(?:hands?|arms?) (?:around|on) my (?:neck|throat)|tried to choke me",
        r"threaten\w* (?:me|us|him|her) with a (?:gun|knife|weapon)"),
        examples=("I was sexually assaulted last night", "My boyfriend choked me")),
    Rule(SUGAR, _words(r"(?:blood )?(?:sugar|glucose|bg) (?:\w+ ){0,3}(?:over |above |at |is |was |of |reading |says |reads |shows )?(?:[4-9]\d\d|hi)\b",
                       r"(?:glucometer|meter|dexcom|libre|cgm) (?:\w+ ){0,2}(?:says|reads|shows) (?:hi|high|[4-9]\d\d)"),
         also=_words(r"confus\w*", r"vomit\w*", r"throw\w* up", r"threw up", r"puk\w*", r"breath\w* (?:fast|hard|heavy|deep)", r"sleepy", r"drowsy",
                     r"weak", r"thirsty", r"dizzy", r"out of it", r"stomach (?:pain|hurts)", r"shak\w*"),
         examples=("My blood sugar is over 600 and I keep throwing up",)),
    Rule(INFANT_UNWELL, _words(
        r"(?:won'?t|will not|isn'?t|is not|not|can'?t|refus\w*|stopped) (?:eat\w*|feed\w*|nurs\w*|drink\w*|tak\w* (?:the |a |her |his )?bottle)",
        r"no wet diapers?", r"(?:hasn'?t|has not|haven'?t|have not) (?:had )?(?:a |any )?(?:wet|peed|pooped)",
        r"letharg\w*|listless|very sleepy|really sleepy|so sleepy|super sleepy|hard to wake|won'?t wake|grunting|weak cry|not crying|mottled"),
        child_under_months=3,
        examples=("My 5 week old will not feed and is very sleepy",)),
    Rule(ALLERGY, _words(r"(?:bee|wasp|hornet|yellow jacket) stings?|stung", r"ate (?:a |some )?(?:peanuts?|nuts?|shrimp|shellfish)", r"hives"),
         also=_words(r"(?:tongue|throat|lips?|mouth) (?:feels |is |are |getting |got )?(?:thick|tight|weird|funny|scratchy|itchy|tingly|closing|swell\w*)",
                     r"wheez\w*", r"(?:hard|trouble) (?:to )?(?:breathe|swallow)", r"faint\w*", r"dizzy"),
         examples=("I got stung by a bee and my throat feels tight",)),
    # A swallowed small object, or food stuck, with signs the airway or food pipe is blocked.
    Rule(BREATH, _words(
        r"(?:swallow\w*|ate|eaten|chok\w* on|inhal\w*|breathed in|put|stuck|lodged|sucked in) (?:\w+ ){0,4}(?:coins?|penny|pennies|nickel|dime|quarter|marbles?|beads?|buttons?|legos?"
        r"|toy|small (?:toy|part|object|piece)|piece of (?:a |the |his |her )?(?:toy|plastic|metal|balloon|crayon|glass)|balloon|pin|tack|earring|fish ?bone|chicken bone|bottle cap|screw)",
        r"(?:food|meat|steak|chicken|hot dog|bone) (?:is |got |was )?(?:stuck|lodged) (?:in|down) (?:my|his|her|their|the) (?:throat|chest|esophagus|windpipe)"),
        also=_words(r"drool\w*", r"(?:can'?t|cannot|won'?t|unable to|not able to|hard to|trouble|refus\w* to) swallow", r"chok\w*", r"gag\w*", r"wheez\w*",
                    r"(?:hard|trouble|struggling|difficult) (?:to )?breath\w*", r"(?:noise|squeak\w*|whistl\w*) (?:\w+ ){0,3}breath\w*",
                    r"(?:keeps?|won'?t stop|can'?t stop|nonstop|non-stop|constant\w*) cough\w*|cough\w* (?:\w+ ){0,2}(?:nonstop|non-stop|and can'?t stop|won'?t stop|constantly)"),
        examples=("My toddler swallowed a coin and now he is drooling and cannot swallow",)),
    Rule(DEHYDRATED, re.compile(_words(
        r"(?:hasn'?t|has not|haven'?t|not|hardly|barely|didn'?t|did not) (?:\w+ ){0,2}(?:peed|pee|peeing|urinated|wet (?:a )?diapers?)",
        r"no wet diapers?", r"dry diapers?", r"no ha (?:hecho pipi|orinado)", r"panal seco").pattern + "|" + _deaccent(normalize(_lex.CHILD_NO_PEE))),
        child_under_months=60,
        also=re.compile(_CHILD_SLEEPY.pattern + "|" + _deaccent(normalize(_lex.CHILD_SLEEPY))),
        examples=("My 18 month old has not peed all day and is really sleepy",)),
]

# Paperwork-only requests. This rule can only apply when nothing else says ESI 3
# or more urgent, so it can never hide a real complaint ("refill" + "can't breathe").
_ADMIN = re.compile(
    r"^(?=.{0,200}$)(?:.*\b(refill|prescription pickup|prior auth|prior authorization|paperwork|fax|records request|fmla|"
    r"disability form|work note|school note|doctor'?s note|medical clearance|vaccine record|immunization record)\b)"
)

# ---------------------------------------------------------------------------
# Red flags in the app's other languages. The word lists are in services/triage_lexicons.py;
# each key maps to one of the results above.
# ---------------------------------------------------------------------------
_LEX_KEYS = {"resus": RESUS, "stroke": STROKE, "chest": CHEST, "breath": BREATH, "bleed": BLEED,
             "crisis": CRISIS, "faint": FAINT, "seizure": SEIZURE, "allergy": ALLERGY, "pregnancy": PREGNANCY, "overdose": OVERDOSE,
             "head": HEAD, "altered": ALTERED}
_LATIN = _lex.LATIN_CODES
LEXICONS: dict[str, dict[str, str]] = _lex.LEXICONS
_LEXICON_MORE = _lex.LEXICON_MORE
_CRISIS_IGNORE = next(r.ignore for r in RULES if r.result is CRISIS)
_COMPILED_LEX: list[tuple[str, ShortcutResult, re.Pattern[str], bool]] = [
    (code, _LEX_KEYS[key], _phrases(alts, code in _LATIN), code in _LATIN)
    for code, flags in LEXICONS.items() for key, alts in flags.items()
]


# ---------------------------------------------------------------------------
# Denials ("no tengo dolor de pecho", "胸口也不痛", "I never blacked out").
# The cue words are in triage_lexicons.DENIAL; see the note there.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Denial:
    before: re.Pattern[str] | None
    after: re.Pattern[str] | None
    inner: re.Pattern[str] | None
    keep: re.Pattern[str] | None
    cjk: bool


def _denial(code: str, d: dict[str, str]) -> _Denial:
    latin = code == "en" or code in _LATIN
    n = (lambda s: _deaccent(normalize(s))) if latin else normalize
    cjk = code in ("zh", "ja")
    sp, start = ("", "") if cjk else (" ", r"(?:^|(?<= ))")

    def alt(key: str) -> str:
        return f"(?:{n(d[key])})" if d.get(key) else ""

    before = None
    if d.get("before"):
        fill = f"(?:{alt('fill')}{sp})*" if d.get("fill") else ""
        item = r".{1,4}" if cjk else r"(?:[\w'-]+,? ){1,3}"   # one denied item in a list: "no fever or ..."
        join = f"(?:{item}{alt('join')}{sp}{fill})*" if d.get("join") else ""
        glue = f"{alt('glue')}?" if d.get("glue") else ""
        before = re.compile(f"{start}{alt('before')}{sp}{fill}{join}{glue}$")
    after = re.compile(n(d["after"])) if d.get("after") else None
    inner = re.compile(n(d["inner"])) if d.get("inner") else None
    keep = re.compile(" " + n(d["keep"])) if d.get("keep") else None
    return _Denial(before, after, inner, keep, cjk)


_DENIALS = {code: _denial(code, d) for code, d in _lex.DENIAL.items()}
# Languages that share letters, so one language's list can match another's words ("胸の痛" is in
# Chinese text too): a denial in any of them counts.
_DENIAL_GROUPS = {"zh": ("zh", "ja"), "ja": ("ja", "zh"), "ar": ("ar", "fa", "ur"), "fa": ("fa", "ar", "ur"),
                  "ur": ("ur", "fa", "ar"), "es": ("es", "pt"), "pt": ("pt", "es")}
# English rules that read a denial the same way ("no chest pain", "never blacked out", "not short of breath").
_EN_DENIABLE = {CHEST.reason, BREATH.reason, FAINT.reason}


def _lex_denials(code: str) -> tuple[_Denial, ...]:
    return tuple(_DENIALS[c] for c in _DENIAL_GROUPS.get(code, (code,)) if c in _DENIALS)


def _denied(d: _Denial, pat: re.Pattern[str], text: str, m: re.Match[str]) -> bool:
    """True when the patient is saying this red flag is NOT happening."""
    if d.keep is not None and d.keep.match(text, m.end()):
        return False
    if d.before is not None and d.before.search(text, 0, m.start()):
        return True
    if d.after is not None and d.after.match(text, m.end()):
        return True
    if d.inner is not None and d.inner.search(m.group(0)):
        bare = re.sub(r" +", " ", d.inner.sub("" if d.cjk else " ", m.group(0))).strip()
        return bool(pat.search(bare))
    return False


def _hit(pat: re.Pattern[str], text: str, denials: tuple[_Denial, ...] = ()) -> bool:
    """True when any match of the red flag is not denied."""
    if not denials:
        return bool(pat.search(text))
    return any(not any(_denied(d, pat, text, m) for d in denials) for m in pat.finditer(text))


# ---------------------------------------------------------------------------
# Child age ("my 3 year old", "my son is 2", "6 week old baby", "she is 6 weeks")
# ---------------------------------------------------------------------------
_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "a": 1, "an": 1,
        "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
_N = r"(\d{1,2}|" + "|".join(_NUM) + r")"
_NS = r"(\d{1,2}|" + "|".join(k for k in _NUM if k not in ("a", "an", "un", "una")) + r")"  # no articles: "is a little"
_NOT_DURATION = r"(?<!hace )(?<!por )(?<!durante )(?<!desde )"   # "hace 2 anos" is how long, not an age
# "she is 2 weeks into her antibiotics" or "3 days post-op" is a duration, not a baby's age.
_NOT_AFTER = (r"(?! (?:ago|pregnant|along|of (?:pregnancy|gestation)|out|post|after|since|into|in|of|on|off|with|without|from"
              r"|now|straight|late|early|overdue|clean|sober|postpartum|sick|left)\b)")
_KID_IS = (r"(?:(?:baby|son|daughter|newborn|infant|kid|child|little one|boy|girl)(?:'s| is| was| who is)"
           r"|(?:she|he) (?:is|was)|she'?s|he'?s|shes|hes) (?:only |just |about |almost |barely )?")
# Read the same with or without a pregnancy: "my 3 year old", "my son is 2".
_AGE_PATTERNS_ANY = [
    (re.compile(r"\b" + _N + r"[ -]?(?:(?:years?|yrs?)[ -]old|yo|y/o)\b"), 12),
    (re.compile(r"\b" + _N + r"[ -]?(?:months?|mos?)[ -]old"), 1),
    (re.compile(r"\b" + _N + r"[ -]?(?:weeks?|wks?)[ -]old"), 0.25),
    (re.compile(r"\b" + _N + r"[ -]?days?[ -]old"), 0),
    (re.compile(r"\b(?:son|daughter|baby|kid|child|boy|girl|toddler|grandson|granddaughter|nephew|niece|little one)(?: who is| is|'s) " + _NS + r"\b(?! (?:hours?|days?|weeks?|months?|minutes?|times|degrees))"), 12),
]
# Skipped for a pregnant patient: "tengo 30 semanas" and "she is 34 weeks" are how far along she is.
_AGE_PATTERNS_CHILD_ONLY = [
    # Spanish, matched on accent-free text: "mi hijo de 2 anos", "tiene 3 meses".
    (re.compile(_NOT_DURATION + r"\b" + _NS + r" anos?\b"), 12),
    (re.compile(_NOT_DURATION + r"\b" + _NS + r" mes(?:es)?\b(?! de embarazo)"), 1),
    (re.compile(_NOT_DURATION + r"\b" + _NS + r" semanas?\b(?! de embarazo)"), 0.25),
    # A baby's age written without "old": "my baby is 6 weeks", "a 3 week baby", "born 10 days ago".
    (re.compile(r"\b" + _KID_IS + _NS + r"[ -]?(?:weeks?|wks?)\b" + _NOT_AFTER), 0.25),
    (re.compile(r"\b" + _KID_IS + _NS + r"[ -]?(?:months?|mos?)\b" + _NOT_AFTER), 1),
    (re.compile(r"\b" + _KID_IS + _NS + r"[ -]?days?\b" + _NOT_AFTER), 0),
    (re.compile(r"\b" + _NS + r"[ -]?(?:weeks?|wks?)[ -](?:baby|son|daughter|newborn|infant|boy|girl)\b"), 0.25),
    (re.compile(r"\b" + _NS + r"[ -]?(?:months?|mos?)[ -](?:baby|son|daughter|newborn|infant|boy|girl)\b"), 1),
    (re.compile(r"\bborn (?:\w+ ){0,2}?" + _NS + r" days?(?: ago)?\b(?! (?:early|late|premature\w*|before|after|past|overdue))"), 0),
    (re.compile(r"\bborn (?:\w+ ){0,2}?" + _NS + r" weeks?(?: ago)?\b(?! (?:early|late|premature\w*|before|after|past|overdue))"), 0.25),
]
_AGE_PATTERNS = _AGE_PATTERNS_ANY + _AGE_PATTERNS_CHILD_ONLY
_CHILD_WORDS = {re.compile(r"\b(?:newborn|recien nacid[oa])\b"): 0, re.compile(r"\b(?:infant|baby|toddler)\b"): 24}
_PREGNANT = re.compile(r"\b(?:pregnan\w*|embarazada|embarazo|gravida|enceinte)\b")


def child_age_months(transcript: str, age: int | float | None = None, pregnant: bool = False) -> int | None:
    """Youngest age (in months) found in the medical form or the text, or None.

    For a pregnant patient, "baby" and "34 weeks" describe the pregnancy, not a child.
    """
    found: list[float] = []
    try:
        if age not in (None, ""):
            found.append(float(age) * 12)
    except (TypeError, ValueError):
        pass
    text = fold(normalize(transcript))
    pregnant = bool(pregnant) or bool(_PREGNANT.search(text))
    for pat, months_per in (_AGE_PATTERNS_ANY if pregnant else _AGE_PATTERNS):
        for m in pat.finditer(text):
            raw = m.group(1)
            n = int(raw) if raw.isdigit() else _NUM[raw]
            if months_per == 12 and n > 17:
                continue
            found.append(n * months_per)
    if not pregnant:
        for pat, months in _CHILD_WORDS.items():
            if pat.search(text):
                found.append(months)
    return int(min(found)) if found else None


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------
def _scrub(text: str, pattern: re.Pattern[str] | None) -> str:
    return pattern.sub(" ", text) if pattern else text


def assess(transcript: str, *, age: int | float | None = None, pregnant: bool = False,
           english: str | None = None, on_blood_thinner: bool = False) -> Assessment:
    """Every red flag in the check-in, most urgent first. `english` is an optional
    English translation; rules run on it as well as on the original words.
    `pregnant` and `on_blood_thinner` come from the medical form."""
    out = Assessment(child_months=child_age_months(transcript, age, pregnant))
    hits: dict[str, ShortcutResult] = {}
    order: list[ShortcutResult] = []

    def add(r: ShortcutResult) -> None:
        if r.reason not in hits:
            hits[r.reason] = r
            order.append(r)

    texts = [t for t in (transcript, english) if t and t.strip()]
    for raw in texts:
        norm = normalize(raw)
        plain = fold(norm)
        folded = _NEGATED.sub(" ", plain)
        for rule in RULES:
            # The chest, breathing and fainting rules read denials themselves, so they see the words before _NEGATED.
            deny = (_DENIALS["en"],) if rule.result.reason in _EN_DENIABLE else ()
            text = _scrub(plain if deny else folded, rule.ignore)
            if rule.child_under_months is not None and (out.child_months is None or out.child_months >= rule.child_under_months):
                continue
            hit = _hit(rule.pattern, text, deny) or (rule.result is PREGNANCY and pregnant)
            if hit and (rule.also is None or rule.also.search(text) or (rule.result is HEAD and on_blood_thinner)):
                add(OVERDOSE_SELF if rule.crisis_if is not None and rule.crisis_if.search(text) else rule.result)
        latin_text = _scrub(folded, _CRISIS_IGNORE)  # "not suicidal" must not trip the Spanish "suicid..."
        for code, result, pat, latin in _COMPILED_LEX:
            if _hit(pat, latin_text if latin else norm, _lex_denials(code)):
                add(result)
        if out.admin is None and _ADMIN.search(plain):
            out.admin = ADMIN
    out.matches = sorted(order, key=lambda r: r.esi_level)
    return out


def evaluate(transcript: str) -> ShortcutResult | None:
    """The most urgent rule for this text, or the paperwork rule, or None."""
    if not transcript:
        return None
    a = assess(transcript)
    return a.floor or a.admin


def is_crisis(transcript: str) -> bool:
    return bool(transcript) and assess(transcript).crisis


# ---------------------------------------------------------------------------
# One decision for the check-in score
# ---------------------------------------------------------------------------
NEEDS_READING = ShortcutResult(
    3, "rule.esi3.needs_reading",
    "ESI 3: written in a language the offline rules cannot fully read. A nurse should read it, with an interpreter if needed.",
    name="Written in a language the offline rules cannot fully read",
)


@dataclass(frozen=True)
class Decision:
    esi_level: int                      # what the patient and the queue see
    model_esi_level: int                # the model's own guess
    rule: ShortcutResult | None         # the rule that set the visible level, if one did
    fired: tuple[ShortcutResult, ...]   # every red flag at the visible level
    crisis: bool                        # show the 988 card (ESI 1 gets "tell staff now" instead)

    @property
    def raised(self) -> bool:
        return self.esi_level < self.model_esi_level


def most_urgent(model_esi: int, a: Assessment) -> Decision:
    """The visible check-in score: the most urgent of the model and the red-flag rules.

    The paperwork rule (ESI 5) applies only when no red flag fired and the model
    already says 4 or 5, so it can never hide a real complaint.
    """
    level, rule = int(model_esi), None
    floor = a.floor
    if floor is not None and floor.esi_level < level:
        level, rule = floor.esi_level, floor
    elif floor is None and a.admin is not None and level >= 4:
        level, rule = a.admin.esi_level, a.admin
    fired = tuple(m for m in a.matches if m.esi_level <= level)
    return Decision(level, int(model_esi), rule, fired, a.crisis and level >= 2)


_EN_WORDS = re.compile(
    r"\b(?:the|my|and|i|i'm|im|is|it|it's|have|has|had|of|with|was|am|been|this|that|since|hurts?|pain|can't|cant|feel|feels|need|he|she|his|her)\b"
)
# High-frequency words of the app's other languages typed in Latin letters (triage_lexicons.FOREIGN_WORDS).
_FOREIGN_WORDS = re.compile(_lex.FOREIGN_WORDS)


def looks_english(text: str) -> bool:
    """True when the text reads as English, so these rules and the model can read all of it."""
    t = normalize(text)
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False
    if sum(1 for c in letters if ord(c) > 127) / len(letters) > 0.05:
        return False
    en = len(set(_EN_WORDS.findall(t)))
    # German "was" and "am" are English words too, so count the other language's words against them.
    return en >= 2 and en > len(set(_FOREIGN_WORDS.findall(fold(t))))


def foreign_latin(text: str) -> bool:
    """Latin-script text with a word from another offered language, or Arabizi digits
    ("me duele el pecho", "3andi alam fi sadri"), even when English was picked."""
    return not looks_english(text) and bool(_FOREIGN_WORDS.search(fold(normalize(text))))


def mostly_non_latin(text: str) -> bool:
    """True for text written mostly in another script (Chinese, Arabic, Hindi ...)."""
    letters = [c for c in normalize(text) if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if ord(c) > 0x24F) / len(letters) > 0.3


_LEGACY_NAMES = {
    "rule.esi1.not_breathing_or_unresponsive": RESUS.name,
    "rule.esi2.high_risk_presentation": "High-risk complaint, such as chest pain or trouble breathing",
    "floor.esi1.unresponsive": "Unresponsive, or GCS 8 or below",
    "floor.esi2.danger_zone_vitals": "Danger-zone vital signs",
}


def rule_name(reason: str | None) -> str:
    """Plain-English name for a stored rule id (current or older), or "" if unknown."""
    if not reason:
        return ""
    for r in [rule.result for rule in RULES] + [OVERDOSE_SELF, ADMIN, NEEDS_READING]:
        if r.reason == reason:
            return r.name
    return _LEGACY_NAMES.get(reason, "")


# ---------------------------------------------------------------------------
# Bedside safety floor (vital signs)
# ---------------------------------------------------------------------------
# These checks come from the ESI Implementation Handbook's decision points and
# can only RAISE acuity, never lower it.
#   Decision point A (ESI 1): unresponsive, or GCS 8 or below.
#   Decision point B (ESI 2): new confusion or lethargy, or severe pain (7+ of 10).
#   Decision point D (ESI 2): "danger zone" vitals for adults and older children.
# Systolic pressure under 90 is added as a sign of possible shock.
VITAL_CHECKS: list[dict] = [
    {"esi": 1, "check": "Unresponsive, or GCS 8 or below"},
    {"esi": 2, "check": "New confusion, drowsiness, or agitation (GCS under 15)"},
    {"esi": 2, "check": "Severe pain, 7 or more out of 10"},
    {"esi": 2, "check": "Oxygen saturation under 92%"},
    {"esi": 2, "check": "Systolic blood pressure under 90"},
    {"esi": 2, "check": "Heart rate over 100 (age 8 and up)"},
    {"esi": 2, "check": "Breathing rate over 20 per minute (age 8 and up)"},
]


def vitals_floor(vitals: dict, age: int | None = None) -> ShortcutResult | None:
    """Return the most urgent vital-sign rule that fires, or None."""
    v = {k: x for k, x in (vitals or {}).items() if x is not None}
    mental = str(v.get("mental_status") or "").lower()
    gcs = v.get("gcs_total")

    if mental == "unresponsive" or (gcs is not None and gcs <= 8):
        return ShortcutResult(
            esi_level=1,
            reason="floor.esi1.unresponsive",
            recommendation="ESI 1: unresponsive or GCS 8 or below. Immediate airway and resuscitation.",
            name="Unresponsive, or GCS 8 or below",
        )

    reasons: list[str] = []
    if mental in {"confused", "drowsy", "agitated"} or (gcs is not None and gcs < 15):
        reasons.append("altered mental status")
    if (v.get("pain_score") or 0) >= 7:
        reasons.append("severe pain")
    if (v.get("spo2") or 100) < 92:
        reasons.append("oxygen saturation under 92%")
    if (v.get("systolic_bp") or 999) < 90:
        reasons.append("systolic pressure under 90")
    # Adult heart-rate and breathing thresholds do not apply to young children.
    if age is None or age >= 8:
        if (v.get("heart_rate") or 0) > 100:
            reasons.append("heart rate over 100")
        if (v.get("respiratory_rate") or 0) > 20:
            reasons.append("respiratory rate over 20")

    if not reasons:
        return None
    return ShortcutResult(
        esi_level=2,
        reason="floor.esi2.danger_zone_vitals",
        recommendation="ESI 2: " + ", ".join(reasons) + ". Do not let this patient wait.",
        name="Danger-zone vital signs",
    )


def apply_floor(model_esi: int, transcript: str, vitals: dict, age: int | None = None) -> tuple[int, list[str]]:
    """Raise the model's ESI to the strictest matching rule. Never lowers it.

    Returns the final ESI and the reason of every rule that fires at the final
    level or more urgent, so a vital-sign reason is kept even when the complaint
    already reached the same level.
    """
    fired = list(assess(transcript or "", age=age).matches)
    vit = vitals_floor(vitals, age)
    if vit is not None:
        fired.append(vit)
    esi = min([model_esi] + [r.esi_level for r in fired])
    why: list[str] = []
    for r in sorted(fired, key=lambda r: r.esi_level):
        if r.esi_level <= esi and r.recommendation not in why:
            why.append(r.recommendation)
    return esi, why


def describe_rules() -> list[dict]:
    """Plain-English rule list for the evidence page, most urgent first. One row per rule."""
    rows: list[dict] = []
    seen: dict[str, dict] = {}
    for r in RULES:
        row = seen.get(r.result.reason)
        if row is None:
            row = {"esi": r.result.esi_level, "name": r.result.name, "examples": list(r.examples)}
            seen[r.result.reason] = row
            rows.append(row)
        else:
            row["examples"] += [e for e in r.examples if e not in row["examples"]]
    langs = sorted(c for c in LEXICONS if "_" not in c)
    rows.append({"esi": 1, "name": f"Red-flag words in {len(langs)} more languages: not breathing, unconscious, stroke",
                 "examples": ["Mi esposo no respira (es)", "他昏迷了 (zh)", "वह बेहोश है (hi)"]})
    rows.append({"esi": 2, "name": f"Red-flag words in {len(langs)} more languages: chest pain, cannot breathe, heavy bleeding, suicidal thoughts",
                 "examples": ["Me duele mucho el pecho y no puedo respirar (es)", "胸口很痛，喘不过气 (zh)",
                              "عندي ألم شديد في صدري ولا أستطيع التنفس (ar)"]})
    rows.append({"esi": 2, "name": "The same red flags typed in Latin letters (Hindi, Arabic, Chinese, Russian, Japanese, Korean, Persian, Bengali)",
                 "examples": ["seene mein dard ho raha hai (Hindi in Latin letters)"]})
    rows.append({"esi": 3, "name": "Written in another language and no AI translation is available: a nurse reads it",
                 "examples": ["Me torcí el tobillo y está hinchado (es)"]})
    rows.append({"esi": 5, "name": "Paperwork or refill only, used only when nothing else is urgent",
                 "examples": ["I need a refill of my blood pressure pills", "I need a school note"]})
    rows.sort(key=lambda row: row["esi"])
    return rows
