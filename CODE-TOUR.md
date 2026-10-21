# Code tour

The twelve files that matter most, in the order a patient's check-in flows through them. Both
of us should be able to open any of these in front of a judge, find the function named
here, and explain it in our own words. Functions are named instead of line numbers because
line numbers change.

Each section ends with questions a judge is likely to ask and the short, true answer.

---

## 1. `backend/services/triage_rules.py`: the safety rules

**What it does.** Plain rules (no machine learning, no AI). The red-flag rules can only make
a patient *more* urgent; the one paperwork rule can move a 4 to a 5, and only when no red
flag fired. It has two halves.

- **Red-flag phrases.** `RULES` is a list of `Rule` objects, each with a regular expression
  (`pattern`), an optional second pattern that must also match (`also`, used for things like
  "head injury" *and* "confused"), an `ignore` pattern blanked out first so "faint rash" does
  not count as fainting, and a few `examples`. `LEXICONS` holds short red-flag lists for the
  app's other 19 languages. `assess(transcript, age=...)` runs everything and returns every
  rule that fired, most urgent first, plus the paperwork rule (`ADMIN`) if the patient only
  asked for a note or a refill. `child_age_months` reads ages like "my 3 year old" so
  child-only rules (a sleepy child with a fever) only fire for children.
- **The check-in decision.** `most_urgent(model_esi, assessment)` picks the score the
  patient sees: the most urgent of the model's guess and every rule that fired. The
  paperwork rule (ESI 5) counts only when no red flag fired and the model already says 4 or
  5. It returns a `Decision` that keeps the model's own guess next to the final level.
- **The bedside vital-sign floor.** `vitals_floor(vitals, age)` follows the ESI handbook's
  decision points: unresponsive or GCS 8 or below is ESI 1; confusion, pain 7 or more out of 10,
  oxygen under 92 percent, and (age 8 and up) heart rate over 100 or breathing over 20 per
  minute are ESI 2. Systolic pressure under 90 is also ESI 2; that one is our addition as a
  sign of possible shock, not one of the handbook's danger-zone vital signs.
- **`apply_floor(model_esi, transcript, vitals, age)`** combines them: the final ESI is the
  *minimum* (most urgent) of the model's number and every rule that fired, and it returns the
  reason for every rule at that level.

**Likely questions**

- *Why can the rules only raise the level, never lower it?* Calling a sick patient less
  urgent than they are (under-triage) is the dangerous mistake. Calling someone more urgent
  costs a little time. Our model was trained on clean, made-up data, so we do not let it talk
  us out of an emergency the rules recognize. In code that is the `min(...)` in `apply_floor`.
- *Why do the heart-rate and breathing limits skip children under 8?* Young children
  normally have faster heart and breathing rates, so adult limits would flag healthy kids.
  The ESI handbook has separate, higher limits for younger ages; we have not added those
  bands yet, so for young children we rely on the other checks.
- *How do you stop false alarms?* Rules can have `ignore` phrases that are blanked out
  first ("faint rash" is not fainting), and `backend/tests/test_red_flags.py` checks both
  sides: phrases that must be urgent and everyday ones that must stay at ESI 4 or 5, like "I
  twisted my ankle" or "I need a refill." `backend/tests/test_redteam_regression.py` adds
  about 1,000 red-team check-ins with the model forced to ESI 5, so the rules alone must
  catch them.
- *Do the rules catch everything?* No. On blind test 2, written after our last fixes and
  never used to change them, 43 of 160 emergencies were shown ESI 3 or calmer from the words
  alone (no AI key, model on). With honest checklist answers it was 17, all emergencies no
  checklist item describes. That is why the checklist (section 3) exists, and why it is not
  enough on its own.

## 2. `backend/routers/intake.py`: check-in (`create_intake`)

**What it does.** The endpoint the patient's phone posts to at the end of check-in. In
order: it checks consent and the one-use check-in token from `/start-intake`, applies the
per-visitor rate limit, gets the symptom text (typed, or recorded audio turned into text),
runs it through a content scanner, reads the medical form and the `red_flags` field (the
checklist taps, a JSON list of ids), and looks at an optional photo. Then it calls
`triage_check_in` in `backend/services/intake_pipeline.py`, which scores the patient:
`services/triage.py` runs the model on the words (with normal vitals filled in, because
nobody has measured the patient yet), `triage_rules.most_urgent` lets the red-flag rules
raise it, `red_flag_checklist.merge` lets the checklist taps and the AI red-flag check raise
it to ESI 2, and the guidance card and explanation are chosen to match the final level.
When the words do not read as English (another language picked, another script, or another
language typed in Latin letters) and there is no AI translation, the score is never shown
below ESI 3, so a nurse reads it soon. Finally it saves the patient and starts the slow
extras (comfort tips, spoken audio, the nurse's pre-brief) in the background, so the patient
gets their result right away.

Before this, `backend/routers/transcribe.py` returns the words, any follow-up questions and
`red_flag_checklist`. That is `false` only when the rules already put the check-in at ESI 1
or 2, so a patient in an obvious emergency is not slowed down by extra questions.

**Likely questions**

- *What if the rules and the model disagree?* The more urgent one wins (`most_urgent`). A
  paperwork-only request ("I need a work note") can only lower the score when no red flag
  fired and the model already thought it was not urgent.
- *Why are the comfort tips added later?* They can call an AI service, which takes seconds.
  The ESI and the guidance are computed without AI, so they come back immediately, and the
  result page fills in the rest when it is ready.
- *How do you stop someone from spamming fake patients?* Each check-in needs a one-use token
  from `/start-intake`, there is a per-visitor limit, and the text goes through a content
  scanner first.

## 3. `backend/services/red_flag_checklist.py`: the checklist the patient taps

**What it does.** `IDS` is the fixed list of ten danger signs plus `none` ("None of these"),
in the order the phone shows them, and `LABELS` holds the English text (the phone shows its
own translation). The newest sign, `ingestion` ("Swallowed something dangerous, like pills,
poison or a battery"), was added after blind test 1 missed swallowed batteries and cleaners.
`parse` reads the form field and ignores anything that is not a known id.
`checklist_results` turns each tapped sign into an ESI 2 result named "Patient checked:
<label>"; `self_harm` also sets the crisis flag, so the result shows the 988 line
(`ingestion` does not, on its own).
`ai_results` does the same for what the AI check found, named "AI red-flag check: <label>".
`merge` adds them to the rules' decision: it can only lower the number (raise urgency) to 2,
never raise it, and the nurse sees every sign that was checked.

**Likely questions**

- *Why a checklist if you already have rules?* Rules read words, and people describe the same
  emergency in endless ways and languages. Our red team showed the rules missed most new
  wording. Tapping "Hard to breathe" means the same thing in every language.
- *What if a patient taps everything?* Each tap only sets ESI 2, so the worst case is that a
  nurse sees them sooner. The checklist can never make anyone less urgent, which also means
  it cannot fix a score that is too urgent.

## 4. `backend/services/ai_red_flags.py`: the AI red-flag check (only with a key)

**What it does.** `start` sends one short Claude call (through `lib/claude.py`, so it counts
toward the daily budget) with the patient's words and a fixed system prompt listing all ten of
the checklist signs. The reply must be JSON like
`{"red_flags": ["chest"]}`; `parse` keeps only known ids. `result` waits at most 5 seconds
(`TIMEOUT_S`). On no key, a timeout or a bad reply it returns `None` and the check-in is
scored without it. `intake_pipeline` skips it when the rules or the checklist already set
ESI 2, and its findings go through `red_flag_checklist.ai_results`, so they can only raise
the score.

**Likely questions**

- *Can the AI make a patient less urgent?* No. Its only output is a list of danger signs, and
  each one can only set ESI 2.
- *Does the patient see what the AI said?* No. The nurse sees it labeled "AI red-flag check";
  the patient only sees the usual words for their level.
- *Does it work?* We have not measured how often it finds the right signs. Our tests check
  that it is skipped safely when it fails and that it can only raise the score.

## 5. `backend/services/triage_ml.py`: the trained model (`build_row`, `predict`)

**What it does.** Loads the 5 LightGBM models and `artifacts.pkl` (the text vocabularies,
label encoders and typical values saved at training time).

- `build_row(patient, vitals)` turns one patient and their vitals into one row with the same
  columns the model was trained on. It works out derived numbers like the shock index
  (heart rate divided by systolic pressure) and fills things we do not know (like which nurse
  or which shift) with neutral defaults.
- `predict(patient, vitals)` builds the 561 features (numbers, flags, and TF-IDF text
  features from the complaint), averages the five folds' probabilities for ESI 1 to 5, and
  returns the ESI, its probability, the range of levels it cannot rule out, and the factors
  that pushed it most (SHAP values from LightGBM).
- `status()` reports whether the model is installed (`lgbm_5fold`) or not (`rules_only`).

**Likely questions**

- *What does "5-fold" mean?* We split the training data into five parts and trained five
  models, each on four parts, checking each on the part it did not see. At runtime we average
  all five.
- *Your score is 0.999. Is it really that accurate?* No. That is measured on the parts of
  the synthetic data each fold did not train on (out-of-fold), and that data is very clean.
  Real triage models usually score far lower. That is exactly why the safety rules get the
  last word.
- *What about features like nurse id or arrival time?* They were in the training data, so
  the model still expects them, but they say nothing about the patient. We fill them with
  defaults and never show them as a reason for a score.

## 6. `backend/routers/triage.py`: the bedside re-check (`refine_triage`, `refine`)

**What it does.** `refine_triage` is the endpoint the nurse's vitals form calls. It checks
the nurse is signed in and that at least one vital sign was entered, then calls `refine`.
`refine` asks the model for its guess, then runs the safety floor. If the floor raised the
level it keeps both numbers (`model_esi_level` and the final `esi_level`) and the plain
reasons, and hides the model's percentage. If the model files are not installed, it starts
from the check-in score and uses the rules alone, and says so.

**Likely questions**

- *Why hide the percentage when the rules raise the level?* "ESI 2, 67% confident" would be
  false: the 67% was for the model's own pick. So the screen says "The model guessed ESI 3
  (67%). Safety rules raised it to ESI 2 because..."
- *What happens without the model files?* The re-check still works on the rules, starting
  from the check-in score, and the screen says the model is not installed.

## 7. `backend/services/demo_seed.py`: the five example patients (`seed_canonical_patients`)

**What it does.** Adds five fictional patients covering ESI 1 to 5 (`CANONICAL`): Marcus
(stroke signs), Elena (chest pain, in Spanish), Priya (a bad headache, and she pressed "I
feel worse"), James (a sprained ankle) and Sofia (a prescription refill), with their notes
and scores already filled in so the dashboard looks like a real shift. It skips any that already exist, and it
never calls an AI service or the internet, even when keys are set. The example patients go
through the same scoring as a real check-in, with AI turned off.

**Likely questions**

- *Why not just run them through the AI?* Seeding has to be fast, free and the same every
  time, and it has to work for a judge with no keys and no internet.

## 8. `backend/lib/sandbox.py`: a private hospital for every visitor

**What it does.** Every visitor's browser picks a random id like `demo-k3x9q2`. The first
request for a new id creates that hospital (`touch_or_provision`): the hospital, the three
demo clinicians and the five example patients. `admit` decides whether a request may run,
`sweep` deletes sandboxes idle for 2 hours, and there can be at most 300 at once. One client
address may create 5 new sandboxes an hour and keep 10 alive; past those limits, or when all
300 are in use, the visitor's id is served from the shared `demo` hospital instead of
showing an error.

**Likely questions**

- *How do judges not see each other's test patients?* Each one gets their own hospital id,
  and every API route is scoped to a hospital.
- *Can someone guess another id?* There are about 2 billion possible ids. That is fine for
  made-up demo data; it would not be enough protection for real patient data.

## 9. `frontend/src/pages/PatientIntake.tsx`: the check-in screens

**What it does.** A step-by-step flow: language, optional ID scan (or a sample card),
name and consent, age and sex, optional insurance card, symptoms (typed, dictated, or a
"Try an example" phrase), the red-flag checklist
(`components/patient/RedFlagChecklist.tsx`, shown unless `/transcribe` says the rules
already marked it urgent; the patient must tap at least one row, "None of these" included),
follow-up questions, then submit. The `Step` type lists the steps
and each one has a "can continue" check. It asks `/start-intake` for the one-use token,
and `useCapabilities` tells it which optional features are off so it can say so instead of
showing a broken button. The screen text comes from `lib/i18n.ts`: English ships with the
app, and each other language is its own file in `lib/i18n/`, fetched only when the patient
picks it (until it arrives, the screen shows English).

**Likely questions**

- *How does voice work with no key?* `hooks/useAudioRecorder.ts` uses the browser's own
  speech recognition (the Web Speech API) to type what the patient says. The server-side
  Whisper path is only used for browsers without it, and only when a key is set.

## 10. `frontend/src/pages/PatientResult.tsx`: the result screen

**What it does.** Shows the ESI level, what it means in the patient's language, an
estimated wait, what to do while waiting, comfort tips (filled in when ready), and the
"I feel worse" button (`PainEscalateButton`) that raises an alarm on the nurse's dashboard.
`careKind` and `careCopy` choose the guidance card.

**Likely questions**

- *Could it ever tell a patient in the ER to go home?* No. `careCopy` checks the server's
  suggestion, and anything that would send the patient somewhere else (a virtual visit,
  care at home, scheduling) is replaced with the app's own translated card for that level,
  which says not to leave before a nurse sees them and to tell the front desk if they feel
  worse. The crisis card shows the 988 line for suicidal thoughts.

## 11. `frontend/src/components/clinician/VitalsPanel.tsx`: the nurse's vitals form

**What it does.** The form where a nurse enters blood pressure, heart rate, oxygen and so
on. It calls `refineTriage`, then `Verdict` writes the one sentence that explains the
result ("The model guessed ESI 3. Safety rules raised it to ESI 2 because..."),
`ProbabilityTiles` shows the model's probability for each level, `Factors` lists what pushed
the model, and `ModelCardDetails` explains the model honestly, including the synthetic data.

**Likely questions**

- *Why show the model's guess at all if the rules override it?* So a nurse can see both and
  judge for themselves. Hiding the disagreement would make the app look more certain than
  it is.

## 12. `frontend/src/pages/ShowcaseDemo.tsx`: both sides at once

**What it does.** Puts the real patient screen and the real nurse dashboard side by side in
two frames, both pointed at the same private sandbox, with a divider you can drag. Nothing
here is a recording: a check-in on the left shows up in the queue on the right.

**Likely questions**

- *Is this a mock-up?* No. Each side is the real app page, talking to the real API.

---

## Before a judge asks

- Open each file and find each function named above. Say out loud what it does.
- Run the tests (`cd backend && .venv/bin/python -m pytest -q`) and know what the red-flag
  tests, the red-team regression tests (with blind test 1) and the expected failures check.
  Run `python3 scripts/seed_demo.py` against a running server and explain each line it
  prints.
- Be ready to say which parts the AI coding assistant wrote and what you checked yourselves
  (see `AI-DISCLOSURE.md`). "We checked it" is not enough: name a test you ran or a bug you
  caught.
