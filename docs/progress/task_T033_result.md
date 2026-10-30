# T033 Result: Tutor Service for Production (ADR-031)

- **Date:** 2026-10-27
- **Role:** Developer
- **Status:** verified locally; published (`main` `2f6a4b3`,
  `sha256:5d69fe6c…1137`); deployed to production 2026-10-28 (runbook
  J; technical checks passed); functional real-user
  acceptance passed 2026-10-30 (PO observations; optional security and
  restart checks not verified; [evidence](../planning/2026-10-30-release-acceptance-and-inspection-plan.md))

## Thought

ADR-031 approved with amendments: dedicated tutor container, SSH-only
access, strong token, exact allowed hosts, security tests that do not rely
on the port binding, fail closed on bad configuration.

## Action

- `app/tutor_main.py`: tutor-only app (`/tutor`, `/static`,
  `/api/tutor/*`), token of at least 32 characters, exact-IP
  `MENTOR_PRO_TUTOR_ALLOWED_HOSTS`, page also address-checked, uvicorn
  with forwarded headers off. Student app unchanged (fixed loopback set).
- `tests/app/test_tutor_service.py` (34 tests).
- ADR-031 accepted with amendments; runbook section J; `.env.example`.

## Observation

- LAN, other-container, in-container loopback and Tailscale addresses get
  403 on every tutor route even with the token; missing or wrong tokens
  403 from the gateway; spoofed forwarding headers 403; wrong gateway 403;
  invalid configuration refuses to start; no student routes on the tutor
  app; the student app ignores the setting and serves no tutor routes
  without a token; a completed evaluation is visible to the student.
- Real uvicorn process ignores `X-Forwarded-For`; negative control (proxy
  headers on) makes that test fail.
- Server check (read-only): no container uses host networking; gateway of
  `mentor-pro_default` is `172.19.0.1`.
- Gate `VERIFY_RESULT=pass gate=all`, 579 tests. Student screens and
  static files unchanged, so the browser suite was not rerun.
