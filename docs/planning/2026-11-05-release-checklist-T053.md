# Release Checklist: T053 (Question Generation Fallback)

- **Date:** 2026-11-05
- **Role:** Architect
- **Status:** Prepared. Nothing below is authorized yet: release,
  deployment and the configuration change each need a PO reference.
- **Source:** `dev` `647af18` (PR #50) plus this handoff record.
- **Change since `v2026.11.04-1`:** `app/llm/settings.py`,
  `app/llm/router.py`, `app/generation/pipeline.py`, tests,
  `.env.example`. No `deploy/`, schema, Dockerfile or requirements change:
  no tool reinstall, no migration.

## Fallback model check (2026-11-05, public metadata, no provider request)

| Check | `google/gemma-4-26b-a4b-it:free` |
| --- | --- |
| Listed and free | yes, prompt and completion price 0 |
| Endpoint | Google AI Studio, status 0, uptime (30 min) 100 |
| Router filter `is_text_chat` | passes: input text (also image, video), output text only |
| Output limit | 32,768 tokens (generation uses 4,000) |
| Context | 262,144 |
| Parameters | `max_tokens`, `temperature`, `response_format`, `reasoning` |
| Live quality and latency | not measured |

Repeat the check right before activation (the listing changes; see
T052).

## 1. Release (needs PO authorization)

1. Push `handoff/T053-merged` and open the release PR into `main`.
2. Merge with `--match-head-commit` after green CI.
3. Require the `main` run green, including Tag and Release, the
   protected tag on the merge commit, the GitHub Release, and a manifest
   naming the digest and schema `0001..0001`.

## 2. Administrator configuration (needs PO authorization)

`/etc/mentor-pro/app.env` is root-only; the agent cannot edit or read
it. The administrator adds one line **before** the deployment, so the
deployment's container recreation applies it. The current image ignores
the variable, so adding it early changes nothing.

```sh
sudo cp -p /etc/mentor-pro/app.env /etc/mentor-pro/app.env.bak-T053
sudo grep -c '^OPENROUTER_QUESTION_GENERATION_MODELS=' /etc/mentor-pro/app.env   # expect 0
echo 'OPENROUTER_QUESTION_GENERATION_MODELS=nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-26b-a4b-it:free' \
  | sudo tee -a /etc/mentor-pro/app.env > /dev/null
sudo grep -c '^OPENROUTER_QUESTION_GENERATION_MODELS=' /etc/mentor-pro/app.env   # expect 1
sudo grep -c '^MENTOR_PRO_BANK_ONLY_ENABLED=' /etc/mentor-pro/app.env            # expect 0
```

No other line changes: `OPENROUTER_FREE_MODELS`, timeout, retries and
the daily limit (200) stay as they are. Undo: restore
`app.env.bak-T053`, then recreate the containers with the deployment
tool.

## 3. Deployment (needs PO authorization)

`T="sudo -n /usr/local/lib/mentor-pro/mentorpro"`; `M` is the manifest
path on the server.

1. Download the manifest, `scp` it to
   `/opt/mentor-pro/manifests/<tag>.json`, compare sha256 on both sides.
2. `$T status`, `$T smoke` (`STATUS HEALTHY`, 9/9).
3. `$T preflight "$M"` (schema `0001`).
4. `$T backup`, then `$T verify-backup <full dump path>`.
5. `$T deploy "$M" --backup <path> --window <ref> --authorization <ref>`.
6. `$T status`, `$T smoke`.
7. Checks:
   - app and tutor on the new digest;
   - in the app container, `OPENROUTER_QUESTION_GENERATION_MODELS` is
     set with the two model names (a model list, not a secret), and
     there is no `MENTOR_PRO_BANK_ONLY_ENABLED` key;
   - `/api/subjects` reports `bank_only: false`, sizes `[5]`.

Stop on any other result; never restore or roll back automatically.
Rollback target: `v2026.11.04-1` (`6a661861…c5d1`), same schema.

## 4. After deployment (separate authorization)

The T052 M09 pilot resumes with at least `--max-calls 3` per probe
(generation plus review), then `item-review-sample --objective M09`.
