# ADR-038: Automatic Question Eligibility and Student Reports

> **Status:** Accepted (T072, PO decision 2026-11-19). Automatic eligibility
> ships behind a flag that is off by default. Activating it in production
> needs a separate PO authorization. Amends
> [ADR-034](ADR-034-question-bank-foundation.md) (human approval holds new
> seeder questions) and the operational queue threshold from T066.
> **Date:** 2026-11-19

---

## Context

ADR-034 holds every seeder-generated question out of practices until a human
releases it, either through a passed batch gate or an individual tutor
approval (T051). Automated validation (the deterministic checker, the blind
solve where required, and the rubric) was already mandatory. With one tutor,
review throughput became the inventory bottleneck: 51 validated questions
waited for review on 2026-11-18.

The PO changed the policy:

- human approval is optional;
- automated validation stays mandatory;
- the student can report a question;
- a reported question goes to the tutor.

## Decision

### D1. Four separate concepts

| Concept | Where it lives | Meaning |
|---|---|---|
| Automated validation | `question_attempt.verdict` / `checker_version`, `bank_revalidation` | The question passed the current checker (unchanged) |
| Student eligibility | `QuestionBank.candidates()` | Computed; never stored |
| Tutor review | `bank_item_review` (append-only) | Optional `approved` or `quarantined`; unchanged |
| Student report | `generation.question_report` (new) | `open`, `retained` or `quarantined` |

The meaning of `approved` doesn't change. No verdict is created
automatically, and historical rows are never modified.

### D2. Eligibility rule

A question is eligible when all of these hold:

1. `status = 'accepted'`, and it passed the current checker version or a
   recorded revalidation (unchanged);
2. its latest verdict isn't `quarantined` (unchanged);
3. it has no `open` student report (new; applies in both modes);
4. it isn't held:
   - **Flag off** (`MENTOR_PRO_AUTO_ELIGIBILITY` unset or `off`): the ADR-034
     and T051 rule applies unchanged.
   - **Flag on**: a seeder question needs an active batch link, and its
     batch review must not have `failed`. A tutor verdict isn't required.

Curriculum, difficulty and composition constraints don't change; they live in
the composer. Pending questions whose evidence is missing or outdated still
go through revalidation, so a pending question never skips a gate.

### D3. Student reports

- `POST /api/practice/sessions/{session_id}/reports` with `{slot, reason,
  comment?}`. The reason is one of `wrong_answer`, `confusing`,
  `missing_info`, `display` or `other`. The comment is optional, at most 300
  characters.
- **Access:** Mentor Pro has one anonymous student and no login (PO decision
  2026-11-19; authentication comes later). The report must name a slot that
  exists in a real practice session. The session ID is an unguessable
  32-character hex value.
- **Records:** the question (`request_id`, `item_id`), a SHA-256 of the exact
  item content the student saw, the session and slot, the reason, the
  comment and the time.
- **Duplicates:** at most one report per session and slot; a repeat returns
  `already_reported`.
- **Abuse limit:** a global cap of 30 reports in 24 hours. Requests beyond it
  get 429.
- **Exposure:** the response never includes the answer key or any tutor
  data.

### D4. The report hold

- An `open` report excludes the question from new practices at once.
  Practices already created keep their items, answers and scores.
- The tutor resolves the report in the tutor service:
  - **Retain:** reports go to `retained`, the hold clears, and no verdict
    is recorded.
  - **Quarantine:** a `quarantined` verdict is recorded through the existing
    mechanism, the cell reopens, and reports go to `quarantined`.
- Resolution runs in one transaction under the review lock and re-checks
  that the reports are still open, so a repeated or simultaneous resolution
  is refused with 409.
- Completed practices that used the question are counted for the tutor so
  they can be investigated. Scores aren't rewritten.

### D5. Workload bound

The operational "pause above 40 pending" rule is retired once human review
is optional. Instead, a scheduled tick skips with `reports_open` while open
reports are at or above `MENTOR_PRO_REPORT_PAUSE` (default 10). It resumes on
its own once reports are resolved. The administrator's manual pause still
takes precedence.

Replenishment no longer counts an eligible question as "pending review".
Coverage and capacity follow the same rule, so the review backlog doesn't
block generation in either mode.

### D6. Rollback safeguard (PO, 2026-11-19)

An image older than T072 ignores `generation.question_report` and would
serve reported questions again. Every image built by CI now carries the
OCI label `io.mentorpro.capability.report-holds=1`
(`scripts/release/release.py labels()`, proven by `check-labels`). The
deploy helper reads it only from an image whose registry digest, version
tag, commit and labels it has verified; labels are part of the digest, so
the capability is bound to the immutable release identity. A manifest
field cannot supply it.

Inside the deploy lock, before any container changes, `preflight`, `deploy`
and `rollback` (manifest or adopted legacy targets, and `migrate`, which
runs the deploy path):

| Target image | Open reports | Result |
| --- | --- | --- |
| label `1` | any (not read) | existing gates decide |
| no label | 0, or no report table | permitted, existing gates decide |
| no label | 1 or more | BLOCKED |
| no label | unreadable | BLOCKED (fail closed) |
| other label value | any | BLOCKED (fail closed) |

The count is a read-only query. There is no override flag. Recovery is
documented in the production runbook: stay on a capable release, or have
the tutor resolve the reports first. The script never clears reports,
changes verdicts or re-exposes questions.

## Consequences

- With the flag on, the trust boundary for student-facing content becomes
  the automated validation plus student reports, not prior human review.
- Turning the flag off restores the ADR-034 behavior immediately; nothing is
  stored by mode.
- **Migration:** one additive table, created with `CREATE TABLE IF NOT
  EXISTS` like the other Question Bank tables. Rolling back to the previous
  image ignores the table. A rollback also drops the report hold, so the
  deploy helper refuses one while reports are open (D6).
- Reporting is active as soon as T072 is deployed, independent of the flag.
  It can only remove questions from practices.
