# AI disclosure

The 2026 Congressional App Challenge rules allow AI tools "provided that all AI usage is
fully disclosed in the submission materials," and say AI "may only be used to support
specific aspects of the project." This file is our full account. It covers two different
things:

1. **AI that helped us write the code** (coding assistants).
2. **AI inside the running app** (features that call an AI service when a key is set).

The same account appears in our written answers and in the tools part of our demo video.

## 1. AI coding assistants

### In the original app (April to August 2026)

Solace started in [Dhruvjain35/solace-ai](https://github.com/Dhruvjain35/solace-ai) (first
commit `35f9a8d`, 2026-04-19). Much of the code there was written with AI coding assistants,
mainly Claude Code by Anthropic. Anyone can check this: of the 198 commits on that
repository's `main` branch, 123 end with a `Co-Authored-By: Claude ...` line, which Claude
Code adds when it helps make a commit. The model names in those lines include Claude Opus 5,
Opus 4.8, Opus 4.7, Opus 4.6, Sonnet 4.6 and Fable 5. The repository also has a branch named
`claude/session-work`. A commit without that line is not proof that no AI helped. For
example, the first commit, which holds most of the original app, has no such line.
**[TEAM TO FILL]** say how that first version was written.

### In this contest version (October 2026)

We adapted the app for the contest with Claude Code acting as a coding assistant that we
directed, in sessions on **2026-10-12**, **2026-10-18** and **2026-10-19**.

- **2026-10-12:** Claude Code helped us cut the app down to a version that runs on one
  computer with no cloud account and no API keys (in-memory storage instead of a cloud
  database, local files instead of cloud storage).
- **2026-10-18:** we had several Claude Code agents review the whole app at once (a judge's
  view, a no-key test, a code audit, a check against the contest rules), then had Claude Code
  agents fix what they found in parallel: under-triage of some typed phrases (the check-in
  score now takes the most urgent of the model and the rules), honest messages when a
  feature has no key, the bedside safety-floor display, judge sandboxes and example
  patients, the sample ID and insurance cards, the "How it works" page and its red-flag
  stress test, and the one-container deploy. Claude Code also looked up the Medicare (CMS)
  emergency room numbers for hospitals in and near IL-16 that the front page shows, and
  checked which district each hospital address is in. **[TEAM TO CHECK]** open the two CMS
  links on the front page and confirm a few of the numbers yourselves before you quote them.
- **Test phrases, word lists and translations (2026-10-18 and 2026-10-19).** Claude Code
  wrote the red-flag word lists for the 19 languages other than English
  (`LEXICONS` in `backend/services/triage_rules.py`), the 186 test phrases in
  `backend/tests/test_red_flags.py`, the translations of every patient screen into the 19
  other languages (one file per language in `frontend/src/lib/i18n/`), and the translated
  comfort cards. None of these have been checked by native speakers or clinicians.
  **[TEAM TO FILL]** say which phrases you chose or checked yourselves.
- **Red team and held-out tests (2026-10-18 and 2026-10-19).** Our own 186 phrases all
  passed, so we had separate Claude Code agents act as a red team: they wrote check-ins meant
  to break the rules (typos, slang, someone typing for a person who collapsed, all 20
  languages), 994 of which became `backend/tests/data/redteam_en.json` and
  `redteam_multilingual.json`. The keyword rules missed most of their emergencies. Claude
  Code agents then patched the rules, and the red teams wrote 287 more check-ins after the
  rules were frozen (`backend/tests/data/heldout.json`) that were never used to tune them.
  Those tests showed that patching keywords helps on the phrases it was written for but
  misses much new wording, which is why Claude Code, at our direction, also built the
  red-flag checklist and the AI red-flag check.
- **Two blind tests (2026-10-19).** One more agent wrote blind test 1 (240 check-ins) without
  opening the rules or the test files, and ran it through the real app. Claude Code agents
  then used its misses to fix general gaps in the rules (denials like "no chest pain", "not
  breathing", swallowed poisons and batteries, suicide plans) and, at our direction, added a
  tenth checklist item, "Swallowed something dangerous, like pills, poison or a battery".
  Because it was used for fixing, blind test 1 is now a diagnostic set
  (`backend/tests/data/diagnostic_blind1.json`). After those fixes froze, a separate agent
  wrote and ran blind test 2: 240 new check-ins in six languages, never used to change
  anything. With no AI key, 43 of its 160 emergencies were shown ESI 3 or calmer from the
  words alone, and 17 with honest checklist answers; 4 of its 80 everyday check-ins were
  shown too urgent. That is the number we report as honest. The measured results are in
  `docs/evidence/red-flag-stress-test.md` and on the "How it works" page. We have not
  measured how well the AI red-flag check finds danger signs.
- **Documents:** the first drafts of this file, `README.md`, `CREDITS.md`, `CODE-TOUR.md`,
  the `Dockerfile`, the deploy guides, the "How it works" page text, the stress test report,
  our demo video script and our written-answer drafts were generated by Claude Code.
  **[TEAM TO FILL]** say here what you changed, and confirm that the written answers you
  submit are in your own words.

### What we did ourselves

**[TEAM TO FILL]** Judges are told to look for "significant individual contributions and
technical understanding." Replace each prompt below with a few true sentences in your own
words. Do not claim anything you did not do: judges can ask you to explain any file, and
`CODE-TOUR.md` lists the ones you should know best.

- **Choosing the problem.** Why ER waiting rooms? Who did you talk to, or what did you see
  or read, that made you pick it? [DHRUV] [SRIYAN]
- **The safety floor idea.** Whose idea was it that a model must never be allowed to lower
  the urgency of an obvious emergency? How did you choose the thresholds in
  `backend/services/triage_rules.py` (heart rate over 100, breathing over 20, oxygen under
  92 percent, systolic pressure under 90, GCS 8 or below), and why do the adult heart-rate and
  breathing limits not apply to children under 8? [DHRUV] [SRIYAN]
- **Which red flags to test.** Claude Code wrote the test phrases (see above). Who chose
  which kinds of emergencies to test (for example "no puedo respirar" and the 3 year old
  with a fever), who checked the expected levels, and who decided to run a red team and a
  held-out test and two blind tests? Who chose the checklist items, including the tenth
  (swallowing something dangerous) added after blind test 1? [DHRUV] [SRIYAN]
- **Model training choices.** Who chose LightGBM, 5 folds, the text features and the
  calibration set in `scripts/train_triage_model.py`? Did you look at why the score on the
  synthetic data is so high (about 0.999), and what does that tell you? [DHRUV]
- **Product decisions.** For example: keeping every feature but making each one explain
  itself when its key is off; never letting a fallback invent medical content; giving every
  judge a private sandbox; what the patient screen should and should not say. [DHRUV] [SRIYAN]
- **Testing and checking the AI's work.** How did you check what the coding assistant
  wrote? What did you run, what did you read line by line, and what did you reject or
  rewrite? Name one thing the assistant got wrong that you caught. [DHRUV] [SRIYAN]
- **Code you wrote by hand.** List any files or functions you typed yourselves. [DHRUV]
  [SRIYAN]

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
