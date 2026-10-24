# Task T019 Result: Dashboard-Driven Objective Practice

> **Date:** 2026-10-24
> **Status:** Done
> **Decision:** [ADR-018](../adr/ADR-018-dashboard-driven-practice.md)

---

## Implementation

| Area | Change |
|------|--------|
| `app/static/app.js` | Each dashboard objective has "Practicar este objetivo" ("Repasar este objetivo" for "Dominio consolidado"); `practiceObjective()` resets the menu, selects the subject, "Un objetivo", only that objective, "Intermedia" and 5 questions, and shows a notice; nothing is sent to the server |
| `app/static/index.html` | `#dashboard-choice` notice above "Generar práctica" |
| `app/static/styles.css` | "Necesita refuerzo" highlighted (red frame, "Prioridad" tag); "En progreso" amber bar; full-width action on mobile |
| `app/practice/mastery.py` | Spanish recommendations for "Necesita refuerzo" and "En progreso" (text only; thresholds and calculation unchanged) |
| `scripts/dev/practice_e2e.py` | `scenario_dashboard_practice` (desktop and mobile); wait for feedback in the T015 partial-exit step |

The practice itself is the existing flow: `POST /api/practice/sessions`
fills from the validated bank, then generates missing slots. Objectives keep
the curriculum order. Question counts other than 5 stay disabled, as before.

---

## Verification

| Requirement | Evidence (browser, desktop and mobile) |
|-------------|----------------------------------------|
| Dashboard → objective → configuration | Form shown with subject, "Un objetivo", only the chosen objective, "Intermedia", 5 questions, button enabled |
| Code and curriculum text preserved | Objective label and notice contain the dashboard code and text |
| All six statuses navigate | Six objectives given one status each (dashboard response intercepted); every action presets the form; "Repasar este objetivo" only for "Dominio consolidado" |
| Highlights and recommendations | "Prioridad" and "Prioridad de repaso…" on "Necesita refuerzo"; "Vas por buen camino…" on "En progreso"; "¡Excelente dominio!…" on "Dominio consolidado" |
| No automatic generation | No `POST /api/practice/sessions` and no runner call during navigation |
| Student can adjust settings | Difficulty changed to "Difícil" before starting |
| Practice after confirmation | "Generar práctica" → exactly one session and one job; 5 questions answered |
| Results update the right objective | Dashboard answer counts changed only for that objective (+5) |
| Layout | No horizontal overflow; mobile screenshots checked |
| Unit | `test_labels_and_recommendation_are_spanish` extended |

- Suite: 386 passed.
- Browser (mocked, `mentor_pro_test`): 259/259, three consecutive runs.
- ACE gate: `VERIFY_RESULT=pass gate=all`.

The first browser run failed once in the existing T015 step
"desktop-exit-partial": the script submitted an answer and opened the exit
dialog without waiting for the feedback, so the cancellation could precede
the answer. The step now waits for the feedback; the T015 behaviour is
unchanged.

No change to authentication, the database schema, the curriculum, budgets,
validation rules, mastery thresholds or the calculation.
