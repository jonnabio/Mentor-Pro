# Task T014 Result: Learning Dashboard with Repeat-Aware Mastery

> **Date:** 2026-10-23
> **Status:** Done (status classification and repeat-aware amendments)
> **Decision:** [ADR-015](../adr/ADR-015-repeat-aware-learning-status.md)

---

## Scope

No base T014 document existed in the repository; this task implements the two
amendments received (learning-status thresholds; repeat-aware mastery) as the
dashboard scope: per-objective and per-subject learning status for the single
anonymous student, computed from recorded answers. No accounts, decay or
scheduled reviews.

---

## Implementation

| Area | Change |
|------|--------|
| `app/practice/mastery.py` | Metrics per objective from `practice.answer` × `practice.item` keyed by canonical `item_id`; first attempt = earliest answer per question; `classify` with exact fractions; `Thresholds` from environment |
| `app/main.py` | `GET /api/dashboard`: 4 subjects, 78 objectives, six status counts per subject |
| `app/practice/bank.py` | Unseen preference from global PostgreSQL exposure (all sessions), not the per-tab token |
| `app/static/*` | "Ver mi progreso" on the main menu and results; dashboard view with subject selector, practice vs mastery accuracy, six status counts, objective list, recommendation, notice |
| `scripts/dev/practice_e2e.py` | Dashboard scenario (desktop and mobile) |

### Statuses (configurable; compared unrounded)

| Label | Rule (distinct questions, first-attempt accuracy) |
|-------|---------------------------------------------------|
| Sin practicar | 0 |
| Evidencia insuficiente | 1–4 |
| Necesita refuerzo | ≥ 5, < 60 % |
| En progreso | ≥ 5, 60 % to < 80 % |
| Buen dominio | ≥ 5, 80 % to 90 % inclusive |
| Dominio consolidado | ≥ 5, > 90 % — "¡Excelente dominio! Practicá de vez en cuando para mantener lo aprendido." |

Metrics per objective: total answers, practice accuracy, distinct questions,
first-attempt (mastery) accuracy, repeated answers and their accuracy, repeat
exposure rate, distinct evidencias. The page notes that these are Mentor Pro
indicators, not official MEP performance levels.

---

## Validation

| Requirement | Test | Result |
|-------------|------|--------|
| Boundaries 60 / 80 / 90 / > 90 %, unrounded (59.9 %, 79.9 %, 90.1 %) | `test_status_boundaries` (13 cases) | Pass |
| Configurable thresholds, invalid ordering rejected | `test_thresholds_are_configurable` | Pass |
| Same question five times → no mastery | Insufficient evidence; 1 distinct, 4 repeats, exposure 80 % | Pass |
| Five distinct questions qualify | 4/5 → Buen dominio | Pass |
| Repeated correct answers do not raise mastery | Mastery stays 60 %; practice accuracy 82 % | Pass |
| Repeated wrong answers do not overwrite the first attempt | Mastery stays 100 %; all 3 attempts stored | Pass |
| Repetition across tabs and sessions | Five sessions, five browser hashes, one question → detected | Pass |
| Existing historical answers included | Dashboard computed from all stored answers | Pass |
| Unanswered questions are not first attempts | Two of five answered → 2 distinct; a later first answer counts | Pass |
| Four subjects, 78 objectives | Real-baseline API test and browser (8 / 22 / 19 / 29, counts sum per subject) | Pass |
| Bank prefers unseen from server history | Second tab (new token, then none) receives the unseen item | Pass |

| Check | Result |
|-------|--------|
| Full suite | 359 passed |
| Browser (Chrome, mocked generator) | 143/143, including the dashboard on desktop and mobile |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Curriculum, generation, validation and budget policies are unchanged. No
OpenRouter calls were made in this task.

---

## Data Note

With a single global student, every recorded answer counts. The local
database currently holds 343 answers, of which 275 come from mocked browser
test runs (items `Q-mock-…`); they appear in the dashboard as practice
history. They are kept (history is never deleted automatically); removing them
or pointing the mocked browser tests at a separate database requires a
decision.
