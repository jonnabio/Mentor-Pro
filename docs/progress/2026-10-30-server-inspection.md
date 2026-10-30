# Read-Only Server Inspection (Step A)

- **Date:** 2026-10-30
- **Role:** Architect
- **Authorization:** PO instruction of 2026-10-30 (step A, read-only)
- **Plan:** [release preparation, Part 3](../planning/2026-10-30-release-acceptance-and-inspection-plan.md)
- **Result:** no blocker for step B (first GHCR publication). Two items
  need the administrator before step C (I6).

Nothing was created, copied, started, stopped or changed on the server.
SSH as `jonnabio` without `sudo`. The account is in the `docker` group,
so the Docker checks ran without `sudo`. No environment values were read
or printed. The tooling was syntax-checked by sending the source on
standard input to the server's `python3` (parse only, not executed, no
file written).

## Observed

| Item | Expected | Observed | Status |
| --- | --- | --- | --- |
| OS | — | Ubuntu 26.04.1 LTS, kernel 7.0.0-38 | info |
| `python3` | present | 3.14.4 (CI and image use 3.12); `mentorpro_deploy.py`, `mentorpro_migrate.py` parse on 3.14; `deploy/mentorpro` passes `bash -n` | OK, see N1 |
| Docker / Compose | `config --format json`, `up --wait` | Docker 29.9.1; Compose v5.6.0; `up --wait` present | OK |
| `compose config --format json` | succeeds | fails as `jonnabio`: `/etc/mentor-pro/app.env` permission denied (root `0700`) | expected: tooling runs with `sudo` (`deploy/mentorpro` header) |
| Running images | app and tutor on `sha256:5d69fe6c…1137` | app and tutor on `ghcr.io/jonnabio/mentor-pro@sha256:5d69fe6c…1137`; postgres `17.6` healthy | OK |
| Ports | app `127.0.0.1:8080` and `192.168.50.229:8080`; tutor `127.0.0.1:8081` only | exactly these (`docker ps` and `ss -ltn`); postgres not published | OK |
| Compose project | `mentor-pro`, file `/opt/mentor-pro/compose.deploy.yml` | all three containers; no host networking; gateway `172.19.0.1` (unchanged) | OK |
| Volume and network | `mentor-pro_postgres_data`, `mentor-pro_default` | present | OK |
| `deploy/compose.yml` vs server file | same services | identical except the image (`${MENTOR_PRO_IMAGE}` vs literal digest) and the app and tutor health checks added in I1 | OK, see N2 |
| `RELEASES` | current release last | 2 entries; last `2026-10-28T01:10:25Z sha256:5d69fe6c…1137 2f6a4b3 ok` | OK |
| `/opt/mentor-pro/release.env` | absent before I6 | absent | expected |
| `/var/lib/mentor-pro/rehearsal` | absent or root `0700` | absent (I6 creates it) | expected |
| `/var/backups/mentor-pro` | root `0700` | root `0700`; contents not listed (needs `sudo`) | A1 |
| `/etc/mentor-pro` | root `0700`, no tutor key in `app.env` | root `0700`; key names not checked (needs `sudo`) | A2 |
| Disk | room for dump, rehearsal database, one image | `/` 98 G, 73 G free (22 %); images 3.6 GB, volumes 265 MB | OK |
| Other services | not affected | `uptime-kuma` (separate project `network-monitor`, `127.0.0.1:3001`) | info |

## Blockers

None for step B. Step B is GitHub-side only (release PR, GHCR, tag,
manifest) and touches no server.

## Before step C (I6), administrator with `sudo`, read-only

- **A1:** `sudo ls -l /var/backups/mentor-pro` (latest dump present,
  size near 127,791 bytes).
- **A2:** `sudo sed -E 's/=.*/=<set>/' /etc/mentor-pro/app.env /etc/mentor-pro/tutor.env /etc/mentor-pro/postgres.env`
  (key names only; `app.env` has no `MENTOR_PRO_TUTOR_*` key).

## Notes (not blocking)

- **N1:** the server runs Python 3.14; the tooling is tested on 3.12. It
  parses on 3.14 and uses the standard library only; I6 `status` and
  `smoke` will be its first real run there. Adding 3.14 to the CI
  matrix for the deploy tests is a possible later change (scope frozen).
- **N2:** adopting `deploy/compose.yml` adds health checks to app and
  tutor; they take effect only when the containers are recreated (the
  I7 deployment). I6 itself replaces no container.
- **N3:** `jonnabio` is in the `docker` group, which is equivalent to
  root on the host. The runbook uses `sudo docker`; both work. Recorded,
  no change proposed.
- **N4:** old compose copies (`.bak`, `.pre-adr030`, `.pre-t033`,
  `.pre-tutor`, `.pre-wifi`) remain in `/opt/mentor-pro`; cleanup stays in
  the backlog.
