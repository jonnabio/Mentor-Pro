# T058 Result: Tutor HTTPS Access via Tailscale Serve

- **Role:** Developer (PO authorization PO-T058-TAILSCALE-2026-11-09)
- **Status:** verified (deployed 2026-11-09 as v2026.11.09-2)

## Decision

The first revision (2026-11-07) published the tutor on the house Wi-Fi
address over plain HTTP. The PO replaced it with Tailscale Serve: HTTPS
on port 8443 with a publicly trusted certificate, tailnet only, proxying
to the loopback tutor. URL:
`https://macedonianserver.tailb0ac04.ts.net:8443/tutor`. See ADR-031
amendment T058.

## Findings (server, read-only, 2026-11-09)

- Tailscale 1.104.4, MagicDNS on, certificate domain
  `macedonianserver.tailb0ac04.ts.net`.
- Existing Serve: `:443 / -> http://127.0.0.1:3001` (Uptime Kuma),
  tailnet only; no `:8443`; no Funnel.
- Tutor published on `127.0.0.1:8081` only; nothing on the Wi-Fi address
  port 8081.
- No operator user: changing Serve needs the administrator's `sudo`.

## Change

- `deploy/compose.yml`: the plain-HTTP Wi-Fi tutor binding is removed;
  the tutor stays `127.0.0.1:8081` only (same as `dev`).
- `deploy/mentorpro` smoke: `serve_check` reads
  `tailscale serve status --json` and requires the Serve port to proxy
  only to the loopback tutor, no other Serve entry to reach the tutor,
  and Funnel off; then the tutor page over HTTPS (200), tutor API and
  practice results without the token (403). The Wi-Fi tutor check (000)
  is kept. Production: 13 checks. `MENTORPRO_TAILNET_URL` empty skips
  them. The tool never changes Serve or Funnel.
- ADR-031 amendment T058 rewritten; runbook section J.1 (configure,
  verify and undo Serve without touching port 443).
- No application, generation, budget, bank-only or student data change.

## Tests

`tests/app/test_deploy.py`: Serve check passes for the correct
configuration with the tutor reachable and refusing without the token
(11 checks in the test environment); fails for Funnel on, a wrong target,
the tutor on another Serve port, a missing entry, unreadable output and a
missing `tailscale`; the tool's only Tailscale call is
`serve status --json`; the tutor binding is loopback only. Token
acceptance, refusal and read-only practice results stay covered by
`test_tutor_service.py` and `test_tutor_practice_results.py`.

## Release

- PR #59 merged into `dev` as `804305e` (dev CI 42640072137, green).
  Authorization `PO-T058-TAILSCALE-2026-11-09`.
- Release PR #65 merged into `main` as `6a25ee1` (run 42643333120, green);
  tag `v2026.11.09-2`, image
  `sha256:0cede5a3da3ea6346e5a763044cc77ba78efa631eb52fd5ba9d6404f91f5de9c`.
- Administrator configured `tailscale serve --bg --https=8443
  http://127.0.0.1:8081` and installed the updated deploy tool. Serve
  after: `:443 -> 127.0.0.1:3001` unchanged, `:8443 -> 127.0.0.1:8081`,
  both tailnet only, Funnel off.
- Backup `mentor_pro_2026-11-09_233217.dump` verified; preflight
  compatible; `DEPLOY OK`, smoke 13/13, `STATUS HEALTHY`. Window
  `T058-2026-11-09`.

## Acceptance (production, 2026-11-09)

- Tutor page over HTTPS: 200. Correct code: queue, practice sessions and
  questions 200 (15 sessions). Wrong or missing code: 403. POST: 405.
- Tutor on the Wi-Fi address port 8081: 000 (not reachable).
- Uptime Kuma on its existing URL: 302 (unchanged).
- No production data, setting or student record changed.
