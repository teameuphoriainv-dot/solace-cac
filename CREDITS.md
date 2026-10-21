# Credits

Solace is a student project for the 2026 Congressional App Challenge. This file lists
everything we did not write ourselves: where the code came from, the data the model learned
from, the medical scoring systems we built on, and every library and outside service. How
we used AI tools is in [AI-DISCLOSURE.md](AI-DISCLOSURE.md).

## Team

- Dhruv Jain
- Sriyan Bodla

The public repository is published from Sriyan's personal GitHub account,
`teameuphoriainv-dot` (its display name "euphoria" is a personal handle, not a company). The
`LICENSE` names only the two of us.

In the upstream repository, commits from the GitHub account `zapatoshake-eng` are Sriyan's.
**[TEAM TO CONFIRM before publishing]** Five commits there come from the account
`sathreya6` (authored as "Dhruv Jain"). Confirm this is Dhruv's own account and then
replace this paragraph with one sentence saying so. If it belongs to anyone else, that
person must be credited (or their code rewritten) before submitting, because the rules say
all coding must be done by the student team.

## Where this code came from

This repository is the Congressional App Challenge version of an app we started earlier in
2026. All of it was created after the contest's October 30, 2025 cutoff.

| Date | Repository | What it is |
|---|---|---|
| 2026-03-23 | [Dhruvjain35/triagegeist-clinical-ai](https://github.com/Dhruvjain35/triagegeist-clinical-ai) | Dhruv's first triage model work on the Kaggle Triagegeist data (a training notebook). |
| 2026-04-13 | [Dhruvjain35/TriageAI-DEMO](https://github.com/Dhruvjain35/TriageAI-DEMO) | A live demo of the first triage model. The rule-based fallback engine (`backend/services/triage_engine.py`) was ported from its `model.py`. |
| 2026-04-19 | [Dhruvjain35/solace-ai](https://github.com/Dhruvjain35/solace-ai), first commit [`35f9a8d`](https://github.com/Dhruvjain35/solace-ai/commit/35f9a8df0289abb2c633b89499157b3ed603338c) | The full Solace app, first built for the Hook'em Hacks 2026 hackathon and developed through August 2026. |
| 2026-10 | this repository | The contest version: runs on one computer with no cloud account and no API keys. New here: the bedside vital-sign safety floor, the most-urgent rule at check-in, red-flag phrases in 19 more languages, the red-flag checklist the patient taps, the AI red-flag check that can only raise the score, the red-flag, red-team, held-out and blind tests, the patient screens in 20 languages, judge sandboxes and example patients, sample ID and insurance cards, the judge front door and the "How it works" page. |

The first red-flag keyword floor (keywords can only raise the score) was added upstream on
2026-05-30 in commit
[`326dff4`](https://github.com/Dhruvjain35/solace-ai/commit/326dff44fed188054c856aa44c6dad53c4ddc3a1), from the `sathreya6`
account (see the note under Team). `backend/services/triage_rules.py` grew out of it.

`scripts/train_triage_model.py` is the training script from upstream commit `35f9a8d`; its
header explains why that version matches the shipped model. `scripts/calibrate_conformal.py`
writes `backend/models/conformal.pkl` from the shipped model.

## Training data

The bedside model was trained on the **Kaggle Triagegeist** competition data
(<https://www.kaggle.com/competitions/triagegeist>): about 80,000 synthetic (made up)
emergency department visits. No real patient's data was used. The upstream triagegeist
README names the Laitinen-Fredriksson Foundation as the competition host; we have not
checked that independently.

Citation: Olaf Yunus Laitinen Imanov (2026). Triagegeist. Kaggle.
<https://kaggle.com/competitions/triagegeist>

**License: not fully verified.** Our earlier triagegeist README lists it as a
"Non-Commercial Research License". The competition's rules page did not load without a
Kaggle login, so we have not read the exact terms. **[TEAM TO CONFIRM before publishing]**
Sign in to Kaggle, open the competition's Rules tab, and paste the "Competition Data" clause
here.
The data itself is not in this repository. The trained model files are published separately
(see `scripts/fetch_models.sh`); only publish that release if the terms allow sharing a model
trained on the data in a public, non-commercial student project.

## Medical scoring systems

Solace uses published, openly described triage and early-warning scores. We wrote the code;
the thresholds come from these sources.

- **Emergency Severity Index (ESI), the 1 to 5 urgency scale.** Gilboy N, Tanabe P, Travers
  D, Rosenau AM. *Emergency Severity Index (ESI): A Triage Tool for Emergency Department Care,
  Version 4. Implementation Handbook, 2012 Edition.* AHRQ Publication No. 12-0014. Rockville,
  MD: Agency for Healthcare Research and Quality; 2011. The safety floor in
  `backend/services/triage_rules.py` follows the handbook's decision points (A: needs a
  lifesaving intervention, B: high-risk situation, confused, or severe pain, D: danger-zone
  vital signs). ESI is now maintained by the Emergency Nurses Association.
- **NEWS2.** Royal College of Physicians. *National Early Warning Score (NEWS) 2:
  Standardising the assessment of acute-illness severity in the NHS.* Updated report of a
  working party. London: RCP; 2017.
- **qSOFA and the Sepsis-3 definitions.** Singer M, Deutschman CS, Seymour CW, et al. The
  Third International Consensus Definitions for Sepsis and Septic Shock (Sepsis-3). *JAMA.*
  2016;315(8):801-810. Seymour CW, Liu VX, Iwashyna TJ, et al. Assessment of Clinical Criteria
  for Sepsis. *JAMA.* 2016;315(8):762-774.
- **SIRS.** Bone RC, Balk RA, Cerra FB, et al. Definitions for sepsis and organ failure and
  guidelines for the use of innovative therapies in sepsis. *Chest.* 1992;101(6):1644-1655.
- **MEWS.** Subbe CP, Kruger M, Rutherford P, Gemmel L. Validation of a modified Early Warning
  Score in medical admissions. *QJM.* 2001;94(10):521-526.
- **Why we show our work instead of a black box score.** Wong A, Otles E, Donnelly JP, et al.
  External Validation of a Widely Implemented Proprietary Sepsis Prediction Model in
  Hospitalized Patients. *JAMA Intern Med.* 2021;181(8):1065-1070.
- **Glasgow Coma Scale.** Teasdale G, Jennett B. Assessment of coma and impaired
  consciousness: a practical scale. *Lancet.* 1974;2(7872):81-84.

Machine learning methods:

- **LightGBM.** Ke G, Meng Q, Finley T, et al. LightGBM: A Highly Efficient Gradient Boosting
  Decision Tree. *Advances in Neural Information Processing Systems 30* (NIPS 2017).
- **SHAP explanations** (the "what pushed the model" list, from LightGBM's built-in
  `pred_contrib`). Lundberg SM, Lee S-I. A Unified Approach to Interpreting Model Predictions.
  *NIPS 2017.* Lundberg SM, Erion G, Chen H, et al. From local explanations to global
  understanding with explainable AI for trees. *Nature Machine Intelligence.* 2020;2:56-67.
- **Conformal prediction sets** (the range of ESI levels the model cannot rule out).
  Angelopoulos AN, Bates S. Conformal Prediction: A Gentle Introduction. *Foundations and
  Trends in Machine Learning.* 2023;16(4):494-591.

**[TEAM TO CONFIRM]** `backend/services/drug_interactions.py` is a curated table of common
drug pairs (about 1,000 lines) with no source cited. Add the reference you used, or say in
the README that it is an illustration only.

## Backend libraries (Python)

Versions are pinned in `backend/requirements.txt`. Licenses were read from each installed
package's metadata.

| Package | Version | License | What we use it for |
|---|---|---|---|
| FastAPI | 0.115.0 | MIT | The web API: every `/api/...` route |
| Starlette | 0.38.6 | BSD-3-Clause | The toolkit under FastAPI; serves the built frontend and `/media` files |
| Uvicorn | 0.30.6 | BSD-3-Clause | The web server that runs the app |
| Pydantic | 2.9.2 | MIT | Checks request bodies, such as the vital signs a nurse enters |
| pydantic-settings | 2.5.2 | MIT | Reads settings from environment variables and `.env` |
| python-multipart | 0.0.10 | Apache-2.0 | Reads the check-in form, photos and audio uploads |
| python-dotenv | 1.0.1 | BSD-3-Clause | Loads `.env` for pydantic-settings |
| anthropic | 0.39.0 | MIT | Calls Claude, only when `ANTHROPIC_API_KEY` is set |
| openai | 1.52.0 | Apache-2.0 | Calls Whisper speech to text, only when `OPENAI_API_KEY` is set |
| HTTPX | 0.27.2 | BSD-3-Clause | Calls ElevenLabs and Twilio, only when their keys are set |
| PyJWT | 2.10.1 | MIT | Sign-in tokens for nurses and one-use check-in tokens |
| bcrypt | 4.2.0 | Apache-2.0 | Stores clinician PINs as hashes, never as plain text |
| Pillow | 11.0.0 | MIT-CMU | Re-saves uploaded photos and removes their hidden location data (EXIF) |
| imageio-ffmpeg | 0.6.0 | BSD-2-Clause | Measures the length of uploaded audio (see the FFmpeg note below) |
| boto3 | 1.35.36 | Apache-2.0 | Amazon Web Services SDK. Only used by the older cloud mode, which this build turns off |
| NumPy | 1.26.4 | BSD-3-Clause | Number arrays for the model |
| pandas | 2.2.3 | BSD-3-Clause | Builds the model's input row from a patient and their vitals |
| SciPy | 1.13.1 | BSD-3-Clause | Sparse matrices for the text features |
| scikit-learn | 1.5.2 | BSD-3-Clause | TF-IDF text features and label encoders stored in `artifacts.pkl` |
| LightGBM | 4.5.0 | MIT | The bedside triage model (5 trained folds) |
| pytest | 8.3.3 | MIT | Runs the backend tests |

Packages these pull in that are worth naming: `certifi` (MPL-2.0, the list of trusted web
certificates) and `tqdm` (MPL-2.0 and MIT, progress bars inside the `openai` package). Both
are installed by pip and are not copied into this repository.

**FFmpeg note.** `imageio-ffmpeg` itself is BSD-2-Clause, but when pip installs it, it
downloads a prebuilt FFmpeg program that is licensed under the GNU GPL (version 2 or later).
We only run that program to measure uploaded audio. It is not part of this repository and
we do not change or redistribute it, so the MIT license of our own code is not affected.

## Frontend libraries (JavaScript and TypeScript)

Versions are in `frontend/package.json` and locked in `frontend/package-lock.json`. Licenses
were read from each package's `package.json` in `node_modules`.

| Package | Version | License | What we use it for |
|---|---|---|---|
| React and React DOM | 18.3.1 | MIT | The user interface |
| React Router | 6.30.3 | MIT | Pages and links (`/demo`, `/demo/clinician`, `/showcase`) |
| axios | 1.15.0 | MIT | Talks to the backend API |
| Framer Motion | 11.18.2 | MIT | Animations and screen transitions |
| Lucide React | 0.453.0 | ISC | Icons |
| qrcode.react | 4.2.0 | ISC | The QR code a patient scans to check in |
| TypeScript | 5.9.3 | Apache-2.0 | Type checking (build time only) |
| Vite and @vitejs/plugin-react | 5.4.21, 4.7.0 | MIT | Dev server and production build (build time only) |
| Tailwind CSS | 3.4.19 | MIT | Styling (build time only) |
| PostCSS and Autoprefixer | 8.5.10, 10.5.0 | MIT | CSS processing for Tailwind (build time only) |
| @types/node, @types/react, @types/react-dom | 25.6.0, 18.3.28, 18.3.7 | MIT | Type definitions (build time only) |

Every other package in `node_modules` is MIT, ISC, Apache-2.0, BSD-3-Clause or 0BSD, except
`caniuse-lite` (browser support data, used by Autoprefixer at build time), which is
CC-BY-4.0: data by the Can I Use project, <https://caniuse.com>.

## Fonts and images

- **DM Sans, Fraunces and JetBrains Mono**, loaded from Google Fonts. All three are licensed
  under the SIL Open Font License 1.1.
- **Icons** are from Lucide (ISC license), listed above.
- **[TEAM TO CONFIRM]** The Solace logo and favicons in `frontend/public/` were made by: ____.

## Outside services (only when a key is set)

With no keys, Solace makes no calls to any outside service: triage, the bedside model, the
queue and the early-warning scores all run on the computer hosting the app. When a deployer
adds a key, these services are used:

| Service | Used for | Setting |
|---|---|---|
| Anthropic Claude API | Comfort text, follow-up questions, translating non-English check-ins, the AI red-flag check, notes, reasoning, prescription ideas, reading ID and insurance card photos | `ANTHROPIC_API_KEY` |
| OpenAI Whisper | Server-side speech to text for browsers without live dictation | `OPENAI_API_KEY` |
| ElevenLabs | Spoken audio of the waiting-room guidance | `ELEVENLABS_API_KEY` |
| Twilio | Sending a patient their care instructions by text message | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM_NUMBER` |

Live voice typing and the free read-aloud button use the speech features built into the
visitor's web browser (the Web Speech API), so they need no key.

## Unrelated projects with similar names

Solace is not connected to Solace Health (solace.health), the patient advocacy company, or
to any hospital. The demo hospital, the clinicians and every patient in the app are made up.
