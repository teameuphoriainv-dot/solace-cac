# Solace

**Solace sorts ER waiting-room patients by urgency from their own phones, so the sickest
person is less likely to be missed.**

A patient scans a QR code in the waiting room, picks one of 20 languages, and describes
their symptoms by typing or talking. If the words do not already look like an emergency, a
short checklist asks "Is any of this happening right now?" and the patient taps any danger
sign that applies. Solace gives them an urgency level on the standard Emergency Severity
Index (ESI 1 is the most urgent, 5 the least) with plain guidance while they wait. The triage
nurse sees a live queue sorted by urgency. When the nurse takes vital signs at the bedside, a
trained machine learning model re-checks the patient, and a set of plain safety rules can
only raise the urgency, so the model cannot lower the score of an emergency the rules
recognize.

A 2026 Congressional App Challenge entry by **Dhruv Jain** and **Sriyan Bodla**, Illinois's
16th District.

**Try it live: <https://solace-cac.vercel.app>** (no sign-up; every visitor
gets a private practice hospital)

Straight to one side of the app (one shared demo hospital):
- Patient check-in: <https://solace-cac.vercel.app/patient>
- Clinician dashboard: <https://solace-cac.vercel.app/clinician> (sign in as Dr. Chen, PIN 224466)

> This is a student project with made-up patients. It is not for real medical use and has
> not been tested in a real hospital. The model was trained on synthetic (made-up) data.

## The 90-second tour

1. **Open the front page** (the live link, or <http://localhost:5173> when running locally).
   It shows three ways in. Each one opens your own private demo hospital, with an id like
   `demo-k3x9q2` in the address, so you never see anyone else's test patients. "Start fresh"
   gives you a new one.
2. **Check in as a patient.** Pick a language, agree to the consent screen, and tap one of
   the "Try an example" phrases, for example *"Crushing chest pain down my left arm and I'm
   sweating"* or the Spanish *"Me duele mucho el pecho y no puedo respirar"*. Answer any
   follow-up questions (urgent phrases like these skip them) and skip the optional steps.
   The result screen shows the ESI level, what it means, and what to do while waiting. Try
   the twisted-ankle example too: it is not urgent, so you also see the red-flag checklist.
3. **Open the clinician dashboard** and sign in as **Dr. Chen, PIN 224466**. Your patient is
   in the live queue next to five built-in example patients (ESI 1 to 5, one who speaks
   Spanish, one who pressed "I feel worse").
4. **Open a low-urgency patient, like James with the sprained ankle, and enter shock vital
   signs**: blood pressure 88/54, heart rate 124, oxygen 91 percent, breathing rate 24. Press
   "Re-check the score". The screen shows the model's own guess (ESI 3 for James in our test
   run), then the safety floor raising it to ESI 2, with every reason listed.
5. **Watch both sides at once** at `/showcase`: the patient's phone on the left, the nurse's
   queue on the right, updating live.
6. **See how it works** at `/how-it-works`: the pipeline, the safety rules, our test results
   (including what they still miss) and an honest model card.

Demo sign-ins (all fictional, printed on purpose): **Dr. Chen 224466** (care team lead),
**Dr. Patel 113355**, **Dr. Kim 667788**. Any of them can reset the demo.

## Run it on your own computer

You need **Python 3.12** and **Node.js 20 or newer**. No API keys and no cloud account.

```bash
# 1. Backend (from the repo root)
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..

# 2. The trained model (about 250 MB, optional). Every file is checked against a pinned
#    sha256 before it is installed. Without it, triage runs on the safety rules alone.
scripts/fetch_models.sh

# 3. Start the backend on port 8000
cd backend && .venv/bin/uvicorn main:app --port 8000
```

If step 2 says `fetch_models: download failed`, the model release has not been published
yet. Skip it: the app still runs, scoring with the safety rules alone.

In a second terminal:

```bash
cd frontend
npm ci
npm run dev          # open http://localhost:5173
```

The dev server sends `/api` and `/media` to the backend on port 8000. A phone on the same
Wi-Fi can open the address Vite prints as "Network" to try the patient side.

**One port instead of two:** run `npm run build` in `frontend/` once, then start only the
backend and open <http://localhost:8000>. The backend serves the built app itself.

**With Docker:**

```bash
docker build -t solace-cac .
docker run --rm -p 7860:7860 solace-cac      # open http://localhost:7860
```

The image downloads and checks the model during the build, so this fails until the model
release is published. If the model files are already in `backend/models`,
`docker build --build-arg FETCH_MODELS=0 -t solace-cac .` uses them instead. Hosting it
online is covered in [deploy/DEPLOY.md](deploy/DEPLOY.md).

**Extra check-ins from the command line:** with the backend running,
`python3 scripts/seed_demo.py` checks in the five example phrases through the real pipeline
and prints each ESI next to the range the tests expect.

## No-key mode and AI mode

Solace is built to be judged with **no keys at all**. Everything on the triage path runs on
the computer hosting the app:

- the urgency score at check-in (plain safety rules, the red-flag checklist and the trained
  model),
- the bedside re-check with the trained 5-fold LightGBM model and the safety floor,
- the live queue, the "I feel worse" alarm, and the early-warning scores (NEWS2, qSOFA),
- sample ID and insurance cards (fictional) instead of reading a real card,
- a preview of the text message a patient would get, instead of sending one.

Voice typing and read-aloud also need no key: they use the speech features built into the
visitor's web browser. (Some browsers send dictated audio to their own maker's servers to
turn it into text.)

Features that need an AI key (visit notes, reasoning about possible causes, prescription
ideas, reading a real card photo, comfort text written for the patient, the AI red-flag
check) still appear. With no key, each one says in plain words that it is off and shows the
non-AI version. None of them ever makes up medical content.

**AI mode:** copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. Optional:
`OPENAI_API_KEY` (server speech to text) and `ELEVENLABS_API_KEY` (spoken audio).
`AI_DAILY_BUDGET_USD` caps the day's Claude spending (default 3 dollars). There are also
limits per visitor (address and browser) per hour, and ceilings per hour and per minute for
everyone together, so one burst cannot use up the whole day.

To see what is switched on, open `/api/demo/capabilities`. For example:
`{"llm": false, "ocr": false, "transcription": false, "tts": false, "sms": false,
"triage_model": {"loaded": true, "mode": "lgbm_5fold", "folds": 5}}`.

## How the triage works

1. **At check-in** (`backend/routers/intake.py`, `create_intake`, which calls
   `backend/services/intake_pipeline.py`, `triage_check_in`), the patient's words go through
   plain rules (`backend/services/triage_rules.py`) and the triage model. The most urgent
   answer wins, and rules for things like "can't breathe" can only raise urgency. A
   paperwork-only request ("I need a work note") counts only when nothing else is urgent.
2. **The red-flag checklist** (`backend/services/red_flag_checklist.py`). Unless the rules
   already say ESI 1 or 2, the patient sees ten danger signs, such as "Hard to breathe",
   "Chest pain, pressure or tightness" or "Swallowed something dangerous, like pills, poison
   or a battery", plus "None of these". It does not depend on how the patient words things
   or which language they use. Every tapped sign puts the score at ESI 2 or more urgent
   (never less urgent). "Thinking about hurting yourself" also shows the 988 crisis line; the
   swallowing sign does not by itself. The nurse sees "Patient checked: ..." next to the
   score.
3. **The AI red-flag check** (`backend/services/ai_red_flags.py`, only with an AI key). One
   short Claude call reads the patient's words in any language and names the checklist's
   danger signs if they are clearly there. It waits at most 5 seconds, counts toward the daily AI
   budget, and can only raise the score to ESI 2. The nurse sees it labeled as an AI check;
   the patient is never shown it as an AI diagnosis. If it fails or is slow, it is skipped.
4. **At the bedside** (`backend/routers/triage.py`, `refine_triage`), the nurse's vital signs
   go into the trained model (`backend/services/triage_ml.py`), and then `apply_floor` checks
   the danger-zone vital signs from the ESI handbook, plus systolic pressure under 90 as a
   sign of shock. If the rules say the patient is more urgent, the rules win, and the screen
   shows both the model's guess and the reasons.

The red-flag stress test is `backend/tests/test_red_flags.py`: 186 emergency and everyday
phrases in 20 languages. `backend/tests/test_redteam_regression.py` pins about 1,000 more
that red teams wrote to break the rules, plus blind test 1 (now a diagnostic set), with the
model forced to its calmest answer so the rules alone must catch them. `scripts/red_flag_report.py`
runs these sets and the held-out set through the scoring from before and after our fix,
adds the totals of blind test 2, and writes the results the "How it works" page shows
([docs/evidence/red-flag-stress-test.md](docs/evidence/red-flag-stress-test.md)).

`CODE-TOUR.md` walks through the twelve files that matter most.

## Project layout

```
backend/                FastAPI app (Python)
  main.py               starts the app, serves the built frontend, makes judge sandboxes
  routers/              the API: intake, triage, patients, notes, clinical AI, scans, SMS
  services/             triage rules, red-flag checklist, the model, early warning, scribe, seed data
  lib/                  settings, sign-in, sandboxes, AI spend cap, in-memory tables
  db/                   storage functions (in memory in this build; restarting clears them)
  models/               trained model files (downloaded, not in git)
  tests/                pytest tests, plus the red-team and held-out check-ins in tests/data
frontend/               React + TypeScript + Vite + Tailwind
  src/pages/            front door, how it works, patient check-in and result, dashboard, showcase
  src/components/       patient and clinician screens
  src/lib/              API calls, sandboxes, capabilities, and the screen text: English
                        ships with the app, and each other language is its own file in
                        src/lib/i18n/, loaded only when a patient picks it
scripts/                fetch_models.sh, train_triage_model.py, calibrate_conformal.py,
                        seed_demo.py, red_flag_report.py
deploy/                 hosting guides: AWS App Runner (the hosted demo), Hugging Face
                        Spaces, Render, any Docker host
docs/evidence/          the red-flag stress test report
Dockerfile              one container: builds the frontend, checks the model, runs the API
```

## Testing

```bash
# from the repo root
(cd backend && .venv/bin/python -m pytest -q)    # backend tests
(cd frontend && npm run typecheck)               # TypeScript check
scripts/fetch_models.sh --verify                 # model files match their pinned hashes
```

Check-ins the rules alone still cannot reach are marked as expected failures (`xfailed`),
each with its reason, so they stay visible instead of being deleted: 4 from the red-team set
and 39 from blind test 1. Some tests need the trained model. Without it, those are skipped
with a message; run `scripts/fetch_models.sh` first to run them all. The triage tests pin the
five "Try an example" phrases to the ESI range they must land in, and
`python3 scripts/seed_demo.py` checks the same five phrases against a running server.

## Honest limits

- **Made-up data.** Every patient is fictional. The model learned from about 80,000
  synthetic ER visits from a Kaggle competition. It scores about 0.999 on the parts of that
  synthetic data each fold did not train on, which is far higher than any model would reach
  on real patients. That is why the safety rules get the last word.
- **Keyword rules miss new wording.** Our own 186 test phrases all pass. Then red teams,
  run with Claude Code agents told to break the rules, wrote over 1,000 new ways to describe
  emergencies in 20 languages, and the keyword rules missed most of them. We patched the
  rules: 4 of the 829 red-team emergencies, and 49 of 190 in a held-out set written after
  the first fixes, are still shown less urgent than they should be. Blind test 1, by an agent
  that never saw the rules, found 53 of 160 emergencies missed. We used its misses to fix
  general gaps (denials, "not breathing", swallowed poisons and batteries, suicide plans), so
  it is now only a diagnostic set.
- **Our honest number is blind test 2.** It was written after those fixes froze and never
  used to change anything: 240 check-ins (160 emergencies, 80 everyday) in English, Spanish,
  Chinese, Hindi, Arabic and Vietnamese, run through the full app with no AI key and the
  trained model on. From the words alone, 43 of the 160 emergencies were shown ESI 3 or
  calmer, and 61 were shown less urgent than they should be (this counts an ESI 1 emergency
  shown at ESI 2). With honest checklist answers, 17 were ESI 3 or calmer and 42 were less
  urgent than they should be. All 17 are emergencies no checklist item describes, like sudden
  vision loss or a fever after chemotherapy. Only 16 of the 41 emergencies that should be
  ESI 1 were shown ESI 1, and the checklist cannot help there, because it only lifts a score
  to ESI 2. By language, from the words
  alone: English 26 of 100, Spanish 2 of 12, Chinese 4 of 12, Hindi 5 of 12, Arabic 3 of 12
  and Vietnamese 3 of 12 missed. We have not measured how much the AI red-flag check helps.
- **False alarms.** Blind test 2 found 4 of 80 everyday check-ins shown as too urgent. Three
  were denials the rules did not notice ("I didn't hit my head or pass out", "No swelling of
  my lips or tongue", and "I'm not having a stroke or anything", which was shown ESI 1). One
  was a Vietnamese figure of speech for a bad toothache, which showed the crisis line. The
  checklist cannot fix these, because it can only raise a score.
- **Not checked by clinicians or native speakers.** The thresholds come from published
  sources (see `CREDITS.md`), but no nurse or doctor has reviewed Solace, and it has not been
  used with real patients. Every test phrase (both blind tests included), the red-flag word
  lists in 19 other languages, and the translations of the patient screens were written with
  Claude Code; no native speaker has checked them.
- **Languages.** The rules read English best. When the words do not read as English (the
  patient picked another language, wrote in another script, or typed another language in
  Latin letters even with English picked) and there is no AI key to translate them, the
  check-in is never shown below ESI 3, so a nurse reads it soon. The check for "reads as
  English" is a simple word list, so unusual text can slip past it. With an AI key, the
  words are translated instead, so the same check-in can get a different score with and
  without a key. The model's text features were learned from mostly English complaints. The
  checklist and the bedside vital-sign rules work the same in every language.
- **Data lives in memory.** Restarting the server clears every test patient. There are no
  real accounts; the demo PINs are public on purpose.
- **AI can be wrong.** AI results are labeled and are off unless a key is set. AI never sets
  the urgency score on its own. With a key, its English translation of a non-English
  check-in and its description of a symptom photo are read by the rules and the model (which
  still read the patient's own words too), and the AI red-flag check can raise the score to
  ESI 2. Because the translation takes the place of the ESI 3 hold described above, a
  non-English check-in can get a calmer score with a key than without one.

## Credits, AI use and where this came from

- [CREDITS.md](CREDITS.md): every library and its license, fonts, the training data, and the
  medical scoring systems we used (ESI, NEWS2, qSOFA, SIRS).
- [AI-DISCLOSURE.md](AI-DISCLOSURE.md): how we used AI coding assistants (Claude Code) to
  build and test this, and which features call AI at runtime.
- [CODE-TOUR.md](CODE-TOUR.md): the files we can walk a judge through.

Solace grew out of our earlier work in 2026, all after the contest's October 30, 2025
cutoff: [Dhruvjain35/triagegeist-clinical-ai](https://github.com/Dhruvjain35/triagegeist-clinical-ai)
(2026-03-23), [Dhruvjain35/TriageAI-DEMO](https://github.com/Dhruvjain35/TriageAI-DEMO)
(2026-04-13) and [Dhruvjain35/solace-ai](https://github.com/Dhruvjain35/solace-ai) (first
commit [`35f9a8d`](https://github.com/Dhruvjain35/solace-ai/commit/35f9a8df0289abb2c633b89499157b3ed603338c),
2026-04-19). This repository is the contest version.

Solace is not connected to Solace Health (solace.health) or to any hospital.

## License

[MIT](LICENSE), copyright 2026 Dhruv Jain and Sriyan Bodla.
