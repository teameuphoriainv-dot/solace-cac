# AI disclosure

The 2026 Congressional App Challenge rules allow AI tools "provided that all AI usage is
fully disclosed in the submission materials," and say AI "may only be used to support
specific aspects of the project." This file is our full account. It covers two different
things:

1. **AI that helped us build the app** (coding assistants).
2. **AI inside the running app** (features that call an AI service when a key is set).

## 1. AI coding assistants

### What we wrote ourselves

We, Dhruv Jain and Sriyan Bodla, wrote the app's code ourselves in VS Code. We used Claude
Code (by Anthropic) to review what we wrote, point out bugs and suggest fixes, and we
decided which suggestions to keep. That covers:

- **The safety rules and the safety floor**: `backend/services/triage_rules.py` (the
  red-flag rules, `most_urgent`, `vitals_floor`, `apply_floor`) and the red-flag checklist
  in `backend/services/red_flag_checklist.py`.
- **The trained model**: `scripts/train_triage_model.py` (LightGBM, 5 folds, text
  features, calibration) and `backend/services/triage_ml.py`, which loads it and scores a
  patient at the bedside.
- **The backend API**: the FastAPI routers and the check-in pipeline
  (`backend/routers/intake.py`, `backend/services/intake_pipeline.py`,
  `backend/routers/triage.py` and the rest of `backend/`).
- **The frontend**: the React and TypeScript pages and components for patient check-in,
  the patient result and the nurse dashboard (`frontend/src/`).

`CODE-TOUR.md` lists the files each of us can walk a judge through.

### What Claude Code generated (we directed and checked it)

- **Test data.** The 186 test phrases in `backend/tests/test_red_flags.py`; the red-team
  check-ins in `backend/tests/data/redteam_en.json` and `redteam_multilingual.json`, written
  by Claude Code agents told to break our rules (typos, slang, all 20 languages); the
  held-out set (`heldout.json`), written after the rules were frozen; and the two blind
  tests, written by agents that never saw the rules. Blind test 1 was used to find gaps,
  so it is now a diagnostic set (`diagnostic_blind1.json`). Blind test 2 was never used to
  change anything; it is the number we report as honest (see `README.md`, "Honest limits").
- **Translations and word lists.** The red-flag word lists for the 19 languages other than
  English (`LEXICONS` in `backend/services/triage_rules.py`), the patient screens in those
  languages (`frontend/src/lib/i18n/`) and the translated comfort cards were written with
  Claude Code. No native speaker or clinician has checked them.
- **Documents.** First drafts of `README.md`, `CODE-TOUR.md`, `CREDITS.md`, this file, the
  deploy guides, the "How it works" page text and the stress test report
  (`docs/evidence/red-flag-stress-test.md`). We edited them. Our written answers are in our
  own words.
- **Research.** Claude Code looked up the Medicare (CMS) emergency room numbers for
  hospitals in and near IL-16 that the front page shows, and which district each hospital
  is in. The two CMS links on the front page are the sources.
- **Deployment and final changes (2026-10-24).** Claude Code rebuilt and redeployed the
  hosted demo (AWS CodeBuild and App Runner for the backend, Vercel for the web app,
  `vercel.json`) and wrote the `/patient` and `/clinician` addresses
  (`frontend/src/lib/paths.ts` and the pages that link between them).

### Where Solace came from

Solace grew out of our earlier repository
[Dhruvjain35/solace-ai](https://github.com/Dhruvjain35/solace-ai) (first commit `35f9a8d`,
2026-04-19). Claude Code was used heavily there too; many of its commits end with a
`Co-Authored-By: Claude ...` line, which anyone can check. This repository is the contest
version, adapted in October 2026.

## 2. AI inside the running app

Solace runs fully without any AI key. With no key, the urgency score (ESI), the bedside
model, the safety floor, the live queue and the early-warning scores all run on the
computer hosting the app, with no outside calls. Keys switch on these extra features:

| Feature | AI service | Who sees it |
|---|---|---|
| Comfort tips while waiting, follow-up questions during check-in | Claude (Anthropic) | Patient |
| Translating a check-in written in another language into English, so the rules and the model can read it | Claude (Anthropic) | Nobody directly (it feeds the score) |
| The AI red-flag check: reads the patient's words, in any language, for the checklist danger signs. It can only raise the score, to ESI 2 | Claude (Anthropic) | Nurse (labeled as an AI check); the patient only sees the usual words for their level |
| Reading a driver's license or insurance card photo | Claude (Anthropic) | Patient, nurse |
| A one-line description of a symptom photo | Claude (Anthropic) | Nurse |
| Visit notes (scribe), the clinician pre-brief, the summary published to the patient | Claude (Anthropic) | Nurse, patient |
| Reasoning (possible causes to consider), prescription ideas, disposition and workup drafts | Claude (Anthropic) | Nurse |
| Server-side speech to text for browsers without live dictation | Whisper (OpenAI) | Patient |
| Spoken audio of the waiting-room guidance | ElevenLabs | Patient |

Rules we hold the app to:

- **AI never sets the urgency score on its own.** At check-in the ESI
  comes from the deterministic rules, the checklist the patient taps, and our trained
  LightGBM model. At the bedside it comes from the model plus the safety floor. Three
  nuances, all only when a key is set: if the patient adds a photo, Claude's short
  description of it is added to the text the model and rules read; if the words do not read
  as English, Claude's English translation is read too; and the AI red-flag check can raise
  the score to ESI 2 when it finds a checklist danger sign in the words. The rules still read
  the patient's own words, so a translation can add red flags but never remove one. With no
  key, a check-in whose words do not read as English (another language picked, another
  script, or another language typed in Latin letters) is never shown below ESI 3, so a nurse
  reads it soon. With a key, the translation takes the place of that hold, so the same
  check-in can get a calmer score with a key than without one: a twisted ankle described in
  Spanish is held at ESI 3 with no key, and with a translation it can be scored like the
  English phrase (ESI 4 or 5).
- **The safety floor never depends on AI.** It is plain code in
  `backend/services/triage_rules.py` and can only raise urgency.
- **No key means an honest note, not a fake answer.** Each AI feature says in plain words
  that it is off and offers the non-AI version. A fallback never makes up medical content.
- **AI results are labeled.** AI-backed responses include `ai_available` so the screen can
  say when a result came from AI.
- **Spending is capped.** The hosted demo stops calling Claude for the day once
  `AI_DAILY_BUDGET_USD` ($3) is reached. It also limits how many AI calls one visitor (an
  address and a browser) can make per hour, and how much everyone together can use in one
  hour and in one minute. Visitors on one shared network share the per-visitor limit; the
  daily budget and the Anthropic Console limit are the hard stops.

The bedside model itself is machine learning we trained (LightGBM on the synthetic Kaggle
Triagegeist data, see `CREDITS.md`), not a generative AI service. It runs locally and never
sends data anywhere.

## If a judge asks

We expect questions like "Which parts did the AI write?" and "Explain this function." Our
honest answer is in section 1. `CODE-TOUR.md` lists the files each of us can walk through,
with likely questions and answers.
