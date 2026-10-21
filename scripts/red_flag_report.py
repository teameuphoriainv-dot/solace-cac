"""Run every red-flag test set through the check-in scoring, before and after the fixes.

Five sets, reported separately and in this order:
  pinned       the 186 phrases in backend/tests/test_red_flags.py
  regression   the red teams' check-ins (backend/tests/data/redteam_en.json and
               redteam_multilingual.json), used to find and fix misses
  heldout      check-ins written after the rules were frozen (backend/tests/data/heldout.json),
               never used for tuning
  diagnostic_blind1
               blind test 1 (backend/tests/data/diagnostic_blind1.json). It was blind when it ran,
               then its misses were used to fix the rules by category, so it is a diagnostic set now
  blind2       blind test 2, written after those fixes froze. It is run by a separate agent, so this
               script only reads its totals (--blind2 FILE). Without a file it keeps the totals
               recorded last time, or says "pending".

The --blind2 file is JSON with any of: cases, urgent, everyday, after_under, after_missed,
after_over, checklist_under, checklist_missed (counts, no AI key), plus generated_at and note.

Writes:
  docs/evidence/red-flag-stress-test.md     a plain-English report for people
  frontend/src/data/red-flag-results.json   the same numbers for the app's evidence page
                                            ("summary" and "cases" are the pinned set; "sets" has
                                            every measured set in the order above; "pending_sets"
                                            names a set that has not been run yet)

"Before" is the scoring as it was before the fixes (2026-10-12): the old rule list, and the old
rule that let a paperwork match override everything. It runs from a saved copy of the old
backend (--baseline). Without that copy the "before" numbers already in the JSON are kept.

"After" is today's scoring with no AI key (services/intake_pipeline.py with AI off), using the
trained model when its files are present.

Usage (from the repo root):
    backend/.venv/bin/python scripts/red_flag_report.py
    backend/.venv/bin/python scripts/red_flag_report.py --baseline /path/to/old/backend --blind2 results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DATA = BACKEND / "tests" / "data"
MD_OUT = ROOT / "docs" / "evidence" / "red-flag-stress-test.md"
JSON_OUT = ROOT / "frontend" / "src" / "data" / "red-flag-results.json"
GENERATED = "2026-10-19"

LANG_NAMES = {
    "en": "English", "es": "Spanish", "zh": "Chinese", "hi": "Hindi", "ar": "Arabic", "fr": "French",
    "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese", "de": "German",
    "it": "Italian", "tr": "Turkish", "pl": "Polish", "fa": "Persian", "ur": "Urdu", "id": "Indonesian",
    "tl": "Filipino", "bn": "Bengali",
}
SET_ORDER = ("pinned", "regression", "heldout", "diagnostic_blind1", "blind2")
SET_NAMES = {"pinned": "Pinned phrases", "regression": "Red-team regression set", "heldout": "Held-out set",
             "diagnostic_blind1": "Blind test 1 (now a diagnostic set)", "blind2": "Blind test 2"}
SET_ABOUT = {
    "pinned": "Our own phrases in backend/tests/test_red_flags.py. We fixed the rules until every one passed.",
    "regression": "Written to break the rules. We fixed the rules using them.",
    "heldout": "Written after the first fixes and never used to tune the rules.",
    "diagnostic_blind1": "Written and run blind, then used to fix the rules by category, so it is no longer blind.",
    "blind2": "Written after the fixes from blind test 1 froze, and run blind. The honest number for new wording.",
}
TUNED = {"pinned": True, "regression": True, "heldout": False, "diagnostic_blind1": True, "blind2": False}
# The blind run of blind test 1, before the fixes it led to (the blind evaluator's own numbers,
# through the full app over HTTP: start-intake, transcribe, intake; no AI key, trained model on).
BLIND1_RUN = {"under": 58, "missed": 53, "over": 8, "checklist_under": 28, "checklist_missed": 21}
_BLIND2_KEYS = ("cases", "urgent", "everyday", "after_under", "after_missed", "after_over",
                "checklist_under", "checklist_missed")

# Runs inside the old backend. Reads cases as JSON on stdin, prints one ESI per case.
_BEFORE_SCRIPT = r"""
import json, sys, warnings, logging
from pathlib import Path
warnings.filterwarnings("ignore"); logging.disable(logging.CRITICAL)
from services import triage_ml
triage_ml.MODELS_DIR = Path(sys.argv[1])
from services import triage, triage_rules
cases = json.load(sys.stdin)
def one(c):
    shortcut = triage_rules.evaluate(c["text"])
    result = triage.predict(c["text"], {}, medical_info=c["medical_info"])
    # The old intake rule: any shortcut match won the visible score, in either direction.
    return shortcut.esi_level if shortcut else result.esi_level
# One case at a time: the old model code is not safe to call from several threads.
print(json.dumps([one(c) for c in cases]))
"""


def _pinned_cases() -> list[dict]:
    import importlib.util  # noqa: PLC0415

    sys.path.insert(0, str(BACKEND))
    spec = importlib.util.spec_from_file_location("test_red_flags", BACKEND / "tests" / "test_red_flags.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = []
    for c in module.CASES:
        c = dict(c)
        c["medical_info"] = {"age": c["age"], "sex": "female"} if c.get("age") is not None else {"sex": "female"}
        c["set"] = "pinned"
        out.append(c)
    return out


def _file_cases(names: tuple[str, ...], set_name: str) -> list[dict]:
    out = []
    for name in names:
        for c in json.loads((DATA / name).read_text(encoding="utf-8"))["cases"]:
            emergency = c["kind"] == "emergency"
            out.append({
                "id": c["id"], "text": c["text"], "language": c["language"], "medical_info": c["medical_info"],
                "expected_max_esi": c["max_esi"] if emergency else (c.get("max_esi") or 5),
                "expected_min_esi": None if emergency else c["min_esi"], "set": set_name,
                "flags": c.get("truthful_flags"),
            })
    return out


def _is_everyday(c: dict) -> bool:
    return bool(c.get("expected_min_esi"))


def _before(cases: list[dict], baseline: Path | None) -> list[int | None]:
    if baseline is not None and (baseline / "services" / "triage_rules.py").exists():
        env = {**os.environ, "PYTHONPATH": str(baseline), "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "",
               "SOLACE_MODE": "local"}
        payload = [{"text": c["text"], "medical_info": c["medical_info"]} for c in cases]
        out = subprocess.run(
            [sys.executable, "-c", _BEFORE_SCRIPT, str(BACKEND / "models")],
            input=json.dumps(payload), capture_output=True, text=True, cwd=str(baseline), env=env, check=True,
        )
        return json.loads(out.stdout.strip().splitlines()[-1])
    # No old backend: keep the numbers recorded last time.
    # Only the pinned phrases are stored one by one; main() keeps the other sets' recorded totals.
    old: dict = {}
    if JSON_OUT.exists():
        old = {(c["text"], c["language"]): c.get("before_esi") for c in json.loads(JSON_OUT.read_text()).get("cases", [])}
    return [old.get((c["text"], c["language"])) if c["set"] == "pinned" else None for c in cases]


def _after(cases: list[dict], checklist: bool = False) -> list[int]:
    """Today's score with no AI key. With checklist=True the patient answers the checklist honestly."""
    os.environ.setdefault("SOLACE_MODE", "local")
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, str(BACKEND))
    from services import intake_pipeline, red_flag_checklist  # noqa: PLC0415

    def one(c: dict) -> int:
        flags = None
        if checklist:
            flags = [f for f in (c.get("flags") or ["none"]) if f in red_flag_checklist.IDS] or ["none"]
        return intake_pipeline.triage_check_in(c["text"], medical_info=c["medical_info"], language=c["language"],
                                               allow_ai=False, red_flags=flags).esi_level

    with ThreadPoolExecutor(4) as pool:
        return list(pool.map(one, cases))


def _expected_text(c: dict) -> str:
    lo, hi = c.get("expected_min_esi"), c["expected_max_esi"]
    if lo:
        return f"ESI {lo} to {hi}"
    return "ESI 1" if hi == 1 else f"ESI {hi} or more urgent"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _summarize(name: str, rows: list[dict]) -> dict:
    urgent = [r for r in rows if not _is_everyday(r)]
    everyday = [r for r in rows if _is_everyday(r)]
    s = {
        "name": name, "title": SET_NAMES[name], "about": SET_ABOUT[name], "status": "measured", "tuned": TUNED[name],
        "cases": len(rows), "urgent": len(urgent), "everyday": len(everyday),
        "before_under": sum(1 for r in urgent if r["before_esi"] is not None and r["before_esi"] > r["expected_max_esi"]),
        "after_under": sum(1 for r in urgent if r["after_esi"] > r["expected_max_esi"]),
        "after_missed": sum(1 for r in urgent if r["after_esi"] >= 3),
        "after_over": sum(1 for r in everyday if r["after_esi"] < r["expected_min_esi"]),
    }
    if rows and all(r.get("checklist_esi") is not None for r in rows):
        s["checklist_under"] = sum(1 for r in urgent if r["checklist_esi"] > r["expected_max_esi"])
        s["checklist_missed"] = sum(1 for r in urgent if r["checklist_esi"] >= 3)
    return s


def _blind2(path: Path | None, saved: dict) -> dict | None:
    """The blind test 2 totals from its results file, or the ones recorded last time, or None."""
    if path is not None and path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        s = {"name": "blind2", "title": SET_NAMES["blind2"], "about": SET_ABOUT["blind2"], "status": "measured",
             "tuned": False, "before_under": None}
        s.update({k: raw[k] for k in _BLIND2_KEYS if isinstance(raw.get(k), int)})
        for k in ("generated_at", "note"):
            if isinstance(raw.get(k), str):
                s[k] = raw[k]
        if all(k in s for k in ("cases", "urgent", "everyday", "after_under", "after_over")):
            return s
    old = saved.get("blind2")
    return old if old and old.get("status") == "measured" else None


def _n(s: dict, key: str, of: str = "urgent") -> str:
    return "not reported" if s.get(key) is None else f"{s[key]} of {s[of]}"


def _misses_table(rows: list[dict]) -> list[str]:
    lines = ["| Phrase | Language | Expected | Before | After |", "|---|---|---|---|---|"]
    for r in rows:
        b = "not run" if r["before_esi"] is None else f"ESI {r['before_esi']}"
        lines.append(f"| {_cell(r['text'])} | {LANG_NAMES.get(r['language'], r['language'])} | "
                     f"{_expected_text(r)} | {b} | ESI {r['after_esi']} |")
    return lines


def _results_table(sets: list[dict], blind2: dict | None) -> list[str]:
    lines = ["| Set | Check-ins | Emergencies | Missed before any fix | Missed now | Everyday shown too urgent now | Used to fix the rules |",
             "|---|---|---|---|---|---|---|"]
    for s in sets:
        before = "not run" if s.get("before_under") is None else f"{s['before_under']} of {s['urgent']}"
        lines.append(f"| {s['title']} | {s['cases']} | {s['urgent']} | {before} | {s['after_under']} of {s['urgent']} | "
                     f"{s['after_over']} of {s['everyday']} | {'yes' if s['tuned'] else 'no'} |")
    if blind2 is None:
        lines.append(f"| {SET_NAMES['blind2']} | pending | pending | not run | pending | pending | no |")
    return lines


def _md(rows, by_set, sets, blind2, model_on, data) -> list[str]:
    pinned, reg, held, diag = (next(s for s in sets if s["name"] == n) for n in SET_ORDER[:4])
    all_langs = ["en"] + sorted({r["language"] for r in rows} - {"en"})
    lines = [
        "# Red-flag stress test",
        "",
        f"Generated {GENERATED} by `scripts/red_flag_report.py`. These runs use no AI key. The trained model was "
        f"{'on' if model_on else 'off (files not downloaded), so the rule-based engine stood in for it'}.",
        "",
        "## What we tested",
        "",
        f"We ran {len(rows)} check-ins through the scoring, in {len(all_langs)} languages, in four sets, and a fifth "
        "set is run separately:",
        "",
        f"* **{SET_NAMES['pinned']}** ({pinned['cases']}). The phrases pinned by `backend/tests/test_red_flags.py`.",
        f"* **{SET_NAMES['regression']}** ({reg['cases']}). Check-ins that two red teams of Claude Code agents wrote to "
        "break the rules: typos, teen slang, someone typing for a person who collapsed, overdoses by drug name, "
        "pregnancy, babies, all 20 languages, other languages typed in Latin letters, and everyday traps like \"my "
        "infection is not responding to antibiotics\". We used these to find and fix misses, and "
        "`backend/tests/test_redteam_regression.py` pins them.",
        f"* **{SET_NAMES['heldout']}** ({held['cases']}). New check-ins written after the first fixes were frozen. "
        "We never tuned the rules to them.",
        f"* **{SET_NAMES['diagnostic_blind1']}** ({diag['cases']}). Written and frozen by another Claude Code agent "
        "before it looked at the rules or the tests, and run once blind. We then fixed the rules by category using "
        "its misses, so it is no longer blind. It is kept as a diagnostic set and pinned in "
        "`backend/tests/test_redteam_regression.py`.",
        f"* **{SET_NAMES['blind2']}**. Written after the fixes from blind test 1 froze, and run blind by a separate "
        f"agent. {'Its totals are below.' if blind2 else 'Pending: it has not been run yet.'} This is the honest "
        "number for wording nobody has seen yet.",
        "",
        "A check-in is **under-triaged** when it is shown as less urgent than it should be. ESI 1 is the most "
        "urgent and ESI 5 the least, so a higher number than expected is a miss. An everyday check-in is "
        "**over-triaged** when it is shown more urgent than it should be (ESI 1 or 2 for a sprained ankle).",
        "",
        "## Results",
        "",
        *_results_table(sets, blind2),
        "",
        "\"Before any fix\" is the scoring before 2026-10-18: a short list of exact English phrases, and a paperwork "
        "word like \"refill\" could override everything else. So \"I can't breathe and need a refill of my "
        "inhaler\" was shown as ESI 5.",
        "",
        "Now, the score shown is always the most urgent of the model and the safety rules. The paperwork rule only "
        "applies when nothing else is urgent. The rules read the app's other languages for the most dangerous "
        "problems, in their own script and typed in Latin letters, and they notice common ways a patient says a red "
        "flag is not happening (\"no chest pain\", \"no tengo dolor de pecho\", \"胸口也不痛\"). A check-in the rules recognize "
        "as another language is held at ESI 3 when no AI translation is available, so a nurse reads it soon.",
        "",
        "## What the held-out set tells us",
        "",
        f"Keyword rules catch the pinned and red-team phrases because we wrote rules for them. On new wording they "
        f"miss more: {held['after_under']} of {held['urgent']} held-out emergencies are still shown as less urgent "
        "than they should be. That is why the check-in also asks the patient to tap any red flag from a short list "
        "(for example \"Hard to breathe\" or \"Chest pain, pressure or tightness\"). Any tap sets ESI 2 or more "
        "urgent, whatever words were typed and in any language. With an AI key, an AI check reads the patient's "
        "words for the same red flags, and it can only raise the score. The AI check's accuracy has not been measured.",
        "",
        "`backend/tests/test_redteam_regression.py` checks a harder case than this table: it forces the model to say "
        "ESI 5, so the rules alone must carry every red-team emergency.",
        "",
        "## Blind test 1, now a diagnostic set",
        "",
        "The blind run went through the full app (start-intake, transcribe, intake) with no AI key and the trained "
        "model on. It found two kinds of problems: emergencies described in words the rules did not know, and false "
        "alarms from words the rules read without noticing they were denied or in the past (\"no thoughts of "
        "hurting myself\" showed the 988 crisis line, \"never blacked out\", chest pain the patient said they did "
        "not have, and a teen who \"watched a stroke video\" shown ESI 1). We then fixed the rules by category, not "
        "phrase by phrase, and wrote fresh phrases for each category, both ways, in the tests. The \"now\" column is "
        "this script's run, in process, with the same scoring the app uses. Because the fixes used this set, the "
        "\"now\" column is no longer a blind number.",
        "",
        "| Measure | Blind run, before these fixes | Now |",
        "|---|---|---|",
        f"| Emergencies shown less urgent than expected, from the words alone | {BLIND1_RUN['under']} of 160 | {_n(diag, 'after_under')} |",
        f"| Emergencies shown ESI 3 or calmer, from the words alone | {BLIND1_RUN['missed']} of 160 | {_n(diag, 'after_missed')} |",
        f"| Emergencies shown ESI 3 or calmer, with honest checklist answers | {BLIND1_RUN['checklist_missed']} of 160 | {_n(diag, 'checklist_missed')} |",
        f"| Everyday check-ins shown ESI 1 or 2 | {BLIND1_RUN['over']} of 80 | {diag['after_over']} of {diag['everyday']} |",
        "",
        "## Blind test 2",
        "",
    ]
    if blind2 is None:
        lines += ["Pending. It is written after the fixes above froze and is run blind by a separate agent; its "
                  "totals will appear here when it has run.", ""]
    else:
        lines += [
            f"Run {blind2.get('generated_at', 'after the fixes froze')}. {blind2.get('note', '')}".strip(),
            "",
            "| Measure | Result |", "|---|---|",
            f"| Emergencies shown less urgent than expected, from the words alone | {_n(blind2, 'after_under')} |",
            f"| Emergencies shown ESI 3 or calmer, from the words alone | {_n(blind2, 'after_missed')} |",
            f"| Emergencies shown ESI 3 or calmer, with honest checklist answers | {_n(blind2, 'checklist_missed')} |",
            f"| Everyday check-ins shown ESI 1 or 2 | {_n(blind2, 'after_over', 'everyday')} |",
            "",
        ]
    picked_sets = (
        ("Red-team emergencies still missed", "regression", False), ("Red-team everyday check-ins shown too urgent", "regression", True),
        ("Held-out emergencies still missed", "heldout", False), ("Held-out everyday check-ins shown too urgent", "heldout", True),
        ("Blind test 1 emergencies still missed", "diagnostic_blind1", False),
        ("Blind test 1 everyday check-ins shown too urgent", "diagnostic_blind1", True),
    )
    pin_over = [r for r in by_set["pinned"] if _is_everyday(r) and r["after_esi"] < r["expected_min_esi"]]
    if pin_over:
        lines += ["Pinned everyday check-ins that came out more urgent than expected:", ""]
        lines += [f"* \"{r['text']}\" ({r['language']}): ESI {r['after_esi']}" for r in pin_over]
        lines.append("")
    for title, name, everyday in picked_sets:
        if everyday:
            picked = [r for r in by_set[name] if _is_everyday(r) and r["after_esi"] < r["expected_min_esi"]]
        else:
            picked = [r for r in by_set[name] if not _is_everyday(r) and r["after_esi"] > r["expected_max_esi"]]
        lines += [f"## {title} ({len(picked)})", ""]
        lines += (_misses_table(picked) if picked else ["None."])
        lines.append("")
    lines += ["## Every pinned phrase", "", "| Phrase | Language | Expected | Before | After |", "|---|---|---|---|---|"]
    for r in by_set["pinned"]:
        b = "not run" if r["before_esi"] is None else f"ESI {r['before_esi']}"
        miss_b = " (miss)" if r["before_esi"] is not None and r["before_esi"] > r["expected_max_esi"] else ""
        miss_a = " (miss)" if r["after_esi"] > r["expected_max_esi"] else ""
        lines.append(f"| {_cell(r['text'])} | {LANG_NAMES.get(r['language'], r['language'])} | "
                     f"{_expected_text(r)} | {b}{miss_b} | ESI {r['after_esi']}{miss_a} |")
    lines += ["", "## The safety rules", "", "| ESI | Rule | Example |", "|---|---|---|"]
    for r in data["rules"]:
        lines.append(f"| {r['esi']} | {_cell(r['name'])} | {_cell(r['examples'][0]) if r['examples'] else ''} |")
    lines += ["", "## The bedside vital-sign floor", "",
              "After a nurse measures vital signs, these checks can raise the score (never lower it).", "",
              "| ESI | Check |", "|---|---|"]
    lines += [f"| {v['esi']} | {v['check']} |" for v in data["vital_floor"]]
    lines += ["", "## Limits", "",
              "Every check-in in these sets was written with Claude Code, an AI coding assistant, at the team's "
              "direction, not by the students themselves: the pinned phrases, the red-team and held-out sets, and "
              "both blind sets (each written by a separate Claude Code agent). None was collected from real patients, "
              "and none of the phrases, in any language, has been checked by native speakers or clinicians. The "
              "expected levels follow the ESI handbook as those agents read it, and a few are judgment calls. Passing "
              "these tests does not mean the app is safe for real triage; it is a student demo. The rules are meant "
              "to catch the most dangerous words, and a nurse always makes the real decision.", ""]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--baseline", type=Path, default=None, help="folder of the old backend (the one with services/)")
    parser.add_argument("--blind2", type=Path, default=None, help="blind test 2 results (JSON totals)")
    args = parser.parse_args()

    cases = (_pinned_cases()
             + _file_cases(("redteam_en.json", "redteam_multilingual.json"), "regression")
             + _file_cases(("heldout.json",), "heldout")
             + _file_cases(("diagnostic_blind1.json",), "diagnostic_blind1"))
    before = _before(cases, args.baseline)
    after = _after(cases)
    diag_idx = [i for i, c in enumerate(cases) if c["set"] == "diagnostic_blind1"]
    with_list = dict(zip(diag_idx, _after([cases[i] for i in diag_idx], checklist=True)))

    sys.path.insert(0, str(BACKEND))
    from services import triage_ml, triage_rules  # noqa: PLC0415

    model_on = triage_ml._load() is not None
    rows = [{**c, "before_esi": b, "after_esi": a, "checklist_esi": with_list.get(i)}
            for i, (c, b, a) in enumerate(zip(cases, before, after))]
    by_set = {name: [r for r in rows if r["set"] == name] for name in SET_ORDER[:4]}
    sets = [_summarize(name, by_set[name]) for name in SET_ORDER[:4]]
    saved = {s["name"]: s for s in json.loads(JSON_OUT.read_text()).get("sets", [])} if JSON_OUT.exists() else {}
    if args.baseline is None:  # no old backend: keep the recorded "before" totals
        for s in sets:
            if s["name"] != "pinned" and s["name"] in saved:
                s["before_under"] = saved[s["name"]].get("before_under")
    blind2 = _blind2(args.blind2, saved)
    if blind2 is not None:
        sets.append(blind2)
    pinned_rows = by_set["pinned"]
    pinned = sets[0]
    langs = ["en"] + sorted({r["language"] for r in pinned_rows} - {"en"})

    data = {
        "generated_at": GENERATED,
        # The pinned set, unchanged in shape, for the evidence page.
        "summary": {"cases": pinned["cases"], "languages": langs,
                    "before_under_triaged": pinned["before_under"], "after_under_triaged": pinned["after_under"]},
        "cases": [{"text": r["text"], "language": r["language"], "expected_max_esi": r["expected_max_esi"],
                   "before_esi": r["before_esi"], "after_esi": r["after_esi"]} for r in pinned_rows],
        "sets": sets,
        "pending_sets": [] if blind2 else [{"name": "blind2", "title": SET_NAMES["blind2"], "about": SET_ABOUT["blind2"],
                                            "status": "pending"}],
        "blind1_run": dict(BLIND1_RUN, urgent=160, everyday=80),
        "rules": [{"esi": r["esi"], "name": r["name"], "examples": r["examples"]} for r in triage_rules.describe_rules()],
        "vital_floor": list(triage_rules.VITAL_CHECKS),
    }
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text("\n".join(_md(rows, by_set, sets, blind2, model_on, data)), encoding="utf-8")

    for s in sets:
        extra = f", with honest checklist answers missed {s['checklist_missed']}" if "checklist_missed" in s else ""
        print(f"{s['title']}: {s['cases']} cases ({s['urgent']} emergencies, {s['everyday']} everyday). "
              f"Under-triaged: before {s.get('before_under')}, after {s['after_under']} (ESI 3 or calmer: "
              f"{s.get('after_missed')}{extra}). Everyday too urgent after: {s['after_over']}.")
    if blind2 is None:
        print("Blind test 2: pending")
    print(f"Wrote {MD_OUT.relative_to(ROOT)} and {JSON_OUT.relative_to(ROOT)}")
    return 1 if pinned["after_under"] else 0


if __name__ == "__main__":
    sys.exit(main())
