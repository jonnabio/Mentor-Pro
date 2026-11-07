# T055 Result: Free-First Generation, Paid Approval and Cost Tracking

- **Date:** 2026-11-05
- **Role:** Developer (fast track)
- **Status:** Done. PR #53 (head `500c74b`, CI 42114069387) merged into
  `dev` as `07d7238` (`dev` CI 42117635772 green). Release, L001 and
  deployment authorized under `PO-T055-2026-11-05`. No live OpenRouter
  request, free or paid; every test uses a mocked transport.
- **Decision record:** [ADR-009](../adr/ADR-009-openrouter-integration.md)
  (amendment T055). Evidence: [T054 result](task_T054_result.md).

## Behavior

1. **Free first, never an automatic switch.** `route()` adds the paid
   model only when it is given a claimed `PaidGrant`. With
   `OPENROUTER_ALLOW_PAID=true` and no grant, an exhausted route returns
   `paid_available: true` with "paid generation available with adult
   approval". `seed_bank run` then reports `run.paid_option`: the model,
   the free failure reasons and the next command. Student practice never
   passes a grant.
2. **Estimate** (`python -m app.llm.paid estimate --subject S --objective
   O`): the paid model's current `/models` prices, observed token history
   and the whole workflow. Two figures are given: an expected cost (one
   pass) and a maximum (requests per slot × 2 generation attempts × 3
   calls × HTTP attempts). The output also has the price timestamp, the
   balance status and an uncertainty note. With no prices or no history it
   returns `estimate_unavailable`, and no authorization is created.
3. **Decision** (`approve --max-usd X --approver parent|administrator` or
   `decline`): one decision per pending authorization. At most 3 can be
   pending; they expire after 24 h, and an approval expires 24 h after it
   is given. A decline leaves the free failure state and makes no paid
   call.
4. **Execution** (`seed_bank run --subject S --objective O
   --paid-authorization ID`):
   - The approval is claimed atomically, once, for that subject and
     objective only, and only one paid operation can run at a time.
   - Before the first paid call, prices and the balance are checked
     again.
   - Each paid HTTP attempt reserves its worst-case cost against the
     ceiling and the daily USD budget in one conditional `UPDATE`.
   - Validation, the independent solve and the review are unchanged.
   - The approval ends `consumed` or `stopped`.

## Balances and failures

- `GET /key` uses the application key and reports the key's limit and
  remaining allowance. That is not the account balance.
- `GET /credits` is read only with a separate `OPENROUTER_MANAGEMENT_KEY`.
  The key is never logged or printed, is excluded from `repr` and must
  differ from the application key. Without it, or on any error, the result
  is `balance_unknown` with the reason.
- Both the verified balance and the key allowance cap the ceiling, at
  approval and again at execution.
- `failure_category` comes from the status code and the error code in the
  body, never from message text:

  | Response | Category |
  |---|---|
  | 402 with error code 402 | `insufficient_credits` |
  | Other 402 | `payment_required` |
  | 429 | `rate_limited` |
  | 401 | `auth_invalid` |
  | 403 | `forbidden` |
  | Timeout, connection error or 5xx | `provider_failure` |

- A 402 on the paid model stops paid execution
  (`status: payment_required`, "nothing purchased"). A 429 does not.

## Example estimate (illustrative, not verified pricing)

This uses made-up prices of 3 USD per million input tokens and 15 USD per
million output tokens, and a token history of 1,800 input and 1,500
output tokens on average (2,400 input at most). It assumes 3 requests per
slot and `OPENROUTER_MAX_RETRIES=2`, for one question. These are not
OpenRouter's current prices for any model.

| Figure | USD |
|---|---|
| Expected (3 calls) | 0.0837 |
| Maximum (54 HTTP attempts) | 2.916 |
| Worst case per generation call | 0.069 |
| Worst case per independent solve | 0.039 |
| Worst case per review | 0.054 |

With a 0.50 USD ceiling, paid attempts stop once the next attempt's worst
case would pass 0.50 USD. The output marks `covers_maximum: false`.

## Cost tracking

- New nullable columns on `llm.usage_record` (schema and JSON schema):
  `subject`, `objective_code`, `reasoning_tokens`, `failure_category`,
  `authorization_id`, `liability_usd`. 401 and 402 responses are now
  recorded as sent `error` rows, together with the retries before them.
- Unknown cost stays `NULL` and is never counted as zero. In an approval
  it is counted at its full reservation.
- The daily budget uses the paid exposure: the actual cost, or the
  liability until reconciled. It holds across authorizations and
  counts nothing twice.
- `python -m app.llm.costs report [--credits]` shows today and this month,
  by model, subject, purpose, batch (`seed-<batch>-<run>`) and failure. It
  gives actual USD, paid exposure, unreconciled liability, unknown-cost
  calls, never-sent calls, budget used and remaining, and credits.
- `reconcile` fills missing costs from `GET /generation` and lists
  mismatches for comparison with OpenRouter Activity. Recorded costs are
  never overwritten.

## PO review of PR #53 (changes requested, 2026-11-05)

1. **Controlled schema evolution.** No T055 DDL runs at start-up.
   - Explicit migration `L001_paid_cost_tracking`: `python -m
     app.llm.migrate status|apply [--dry-run]|rollback`.
   - It uses a ledger and an advisory lock, is idempotent and refuses a
     drifted schema. Existing usage rows are checked unchanged by count
     and digest.
   - An unmigrated database keeps the image free-only, and an older
     image runs on a migrated one.
   - The writing range stays `0001..0001`, so `deploy/` is unchanged and
     the administrator does not need to reinstall the root-owned tool.
   - `rollback` refuses while L001 data exists.
2. **Unknown paid costs.**
   - Every paid attempt's record keeps its worst-case reservation as
     `liability_usd`.
   - `today()` reports `paid_exposure_usd`, which is the cost or else the
     liability. The budget gate and each later authorization's daily
     headroom use it.
   - Reconciliation replaces the liability with the actual cost.
3. **Operator access.**
   - No HTTP route reaches the paid, cost or migration commands, and a
     test checks this.
   - Access is SSH (server key) plus docker-group membership into the
     app container, which is the only place holding the database and
     OpenRouter credentials.
   - `--approver` is attribution, not authentication.

Regression tests are in `tests/app/test_paid_migration_and_exposure.py`
(15). Each migration test uses a throwaway database. They cover:

- no start-up DDL, and dry-run, apply, idempotence and drift refusal;
- older-image inserts on a migrated database, and guarded rollback;
- successive authorizations with an unknown cost, and reconciliation
  without double counting;
- concurrent PostgreSQL reservations against the daily exposure;
- a 402 with its earlier retry recorded;
- no web route reaching the commands.

Test 10 in `test_paid_approval.py` now checks that the ceiling blocks
the paid retry and the later paid call.

## Verification

- `tests/app/test_paid_approval.py`: 46 tests, covering scenarios 1–14 of
  the brief, plus bounds, expiry and an operation-scope check. The
  PostgreSQL race moved to the migration file.
- `tests/app/test_paid_migration_and_exposure.py`: 15 tests (PO review).
- `tests/app/test_openrouter.py`: three tests that expected an automatic
  paid fallback became one test asserting that it never happens. The 402
  test now expects a sent `error` row.
- RCA-002 (guarded `app/generation/pipeline.py`): only the `paid`,
  `subject` and `objective_code` parameters were added. Verdict, proof and
  blind-solve logic are untouched; `tests/ace/test_item_checker.py` and
  `tests/app/test_generation.py` pass.
- Full gate tests (ace, curriculum, app): 1004 passed, 9 skipped (attempt 2).
- ACE gate: `VERIFY_RESULT=pass gate=all` (test 335 s, lint 1.9 s; log 20261105-152943-714).

## Not done (not authorized)

No production configuration, deployment, live request, credit purchase,
budget change, bank-only activation, seeding, or M09 verdict.
