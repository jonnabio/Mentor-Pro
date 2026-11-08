# RCA-006: Bank-Only Practice Dead-Ends on a Bank Shortage

- **Severity:** critical (student blocked)
- **Detected:** 2026-11-08, T059 supervised acceptance, production
  `v2026.11.08-2`
- **Status:** fixed in T059 (generate-on-shortage)

## Symptoms

With `MENTOR_PRO_BANK_ONLY_SUBJECTS=matematicas` active, Matemáticas
choices the bank could not fill answered 409 with "Todavía estamos
preparando preguntas revisadas para estas opciones. Prueba con otra
dificultad u otros objetivos." No practice was created and nothing was
generated. Before activation the same choices were generated.

## 5 Whys

1. Why no practice? The request used `source: bank_only`, and a bank
   shortage returns 409 with nothing created.
2. Why only the bank? ADR-035 designed bank-only practice for sizes 5-30
   as bank-or-nothing (D5: explain the shortage, offer a smaller size).
3. Why did size 5 lose generation? The T057 switch moves the student UI's
   size-5 requests for the subject to `bank_only`; the generated flow is
   reachable only with the switch off.
4. Why was it not caught? T057 acceptance checked only a fully stocked
   whole-subject mixed practice (`compose-check`); single objectives and
   explicit levels, which the 17-question bank cannot fill, were not
   tried.
5. Why was that combination not a requirement? The activation decision
   treated "the bank can compose one practice" as readiness, not "every
   choice the UI offers still produces a practice".

## Fix

- A bank-only size-5 request that the bank cannot fill starts the
  existing generated flow for the whole practice (same subject,
  objectives and difficulty; no bank items mixed in). Larger sizes keep
  the explained 409 (generation makes 5-question practices only).
- Such a practice is complete or failed, never partial; a failure names
  the cause (provider, budget, call limit, quality) and leaves nothing to
  answer.
- Validation, provider fallback, budgets, paid approval (never automatic)
  and bank eligibility rules are unchanged.

## Prevention

- Tests in `tests/app/test_bank_only_practice.py` (T059 section).
- Guard RCA-006 in `docs/rca/regression-guards.yaml`.
- Lesson: an activation gate must cover every option the UI offers, not
  only the composed happy path.
