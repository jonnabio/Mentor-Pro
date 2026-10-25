# T030 Result: Reliable Writing Draft Persistence

- **Status:** verified
- **Role:** Developer
- **ADR:** [ADR-028](../adr/ADR-028-reliable-draft-saving.md)

## Supported recovery scenarios

| Scenario | Behavior | Verified by |
| --- | --- | --- |
| Rapid typing, then leaving the exercise | Saved before leaving; a failed save keeps the student on the page | browser |
| Pause in typing (L1–L4) | Autosave after 2 s; "Guardado" only after the server answered | browser |
| L4 stage change | Saved before the stage changes; all paragraphs and notes kept | browser (T028 scenario) |
| Network or PostgreSQL failure | "No se pudo guardar" + "Reintentar"; text kept; earlier draft unchanged (503, nothing written) | browser, API, live |
| Tab hidden | Pending edits sent at once (keepalive) | browser |
| Tab closed or page reloaded | `beforeunload` asks; `pagehide` sends the newest text (keepalive) | browser |
| Reload during an outstanding save; delayed older request | The newest text wins (`client_seq`); reload restores it | browser, API |
| Server restart | Reload restores the last confirmed draft | live (uvicorn), API |
| Submitted work | Immutable: draft 409 after submission, one submission | API |

Draft rows now record `client_seq` and `exercise_revision`. No writing
content, rubric, curriculum, multiple-choice practice or OpenRouter use
changed.

## Unavoidable browser limitations

- Keepalive bodies are limited to 64 KiB; a larger draft is sent without
  keepalive on close and may not arrive.
- A browser crash, forced kill or power loss keeps only what the server had
  confirmed (at most the last 2 s of typing are lost).
- Mobile browsers may freeze a hidden tab before a request completes; the
  hidden-tab flush is sent immediately to reduce that window.
- A reload shows the draft stored at that moment; a keepalive save still in
  transit appears on the next load.

## Validation

| Check | Result |
| --- | --- |
| `tests/app/test_writing_drafts.py` | 5 passed |
| Full suite (ACE gate `test`) | 523 passed |
| Browser, mocked, `mentor_pro_test` | 447/447 (10 new draft checks) |
| Live app (uvicorn, `mentor_pro_test`), `scripts/dev/draft_restart_check.py` | 4/4 |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all` |

No real student drafts or submissions were read or changed.
Screenshots: `docs/progress/screenshots/T030/`.
