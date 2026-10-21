---
title: Solace ER Triage Demo
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Student ER waiting room triage demo (fictional data)
---

# Solace: ER waiting room triage (student demo)

Solace sorts ER waiting-room patients by urgency from their own phones, so the sickest
person is less likely to be missed. It is a 2026 Congressional App Challenge entry by Dhruv
Jain and Sriyan Bodla (IL-16).

This is a demo with made-up patients. It is not for real medical use. Every visitor gets a
private practice hospital, so you will not see anyone else's test patients.

- Patient check-in: open the app and choose "Check in as a patient", or go to `/demo`.
- Nurse dashboard: `/demo/clinician`, sign in as Dr. Chen with PIN 224466.
- Both side by side: `/showcase`.

Source code, credits and the AI disclosure: **https://github.com/teameuphoriainv-dot/solace-cac**

---

The main hosted demo runs on AWS App Runner; this Space is an optional second copy.

This file is the Hugging Face Space card. It is copied over `README.md` only in the Space
copy of the code; see `deploy/DEPLOY.md` in the main repository for how to deploy.
