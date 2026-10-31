# T046 Result: Tutor Page Navigation Back to Mentor Pro

- **Date:** 2026-10-31
- **Role:** Developer
- **Status:** Development complete (PO, 2026-10-31): merged into `dev`, fixed LAN URL kept; not deployed.

## Change

- `app/static/tutor.html`: a "Volver a Mentor Pro" link in the header,
  to `http://192.168.50.229:8080/`, the student app on the house Wi-Fi
  (ADR-030 section 10). An absolute address is needed: the tutor service
  serves no `/` (it stays 404), so a relative link would fail.
- `app/static/styles.css`: one rule for the link's spacing.
- `tests/app/test_tutor_service.py`: one regression test. The tutor
  page carries the link; the tutor service still answers 404 on `/`; the
  student page still has no link to the tutor (ADR-024).

Authentication, the token, allowed hosts, routes and port bindings are
unchanged.

## Limits

- The link assumes the parent uses the house Wi-Fi. Away from home
  (SSH tunnel only to 8081), it does not load unless 8080 is tunnelled
  too.
- In local development, where the student app serves `/tutor` itself,
  the link still points at the production address.

## Verification

- `tests/app/test_tutor_service.py`: 38 passed.
- ACE gate: pass (see PR #38).
