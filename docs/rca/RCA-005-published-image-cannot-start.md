# RCA-005: Published Docker Image Cannot Start

> **Severity:** High (release blocker; no data affected, nothing deployed)
> **Date:** 2026-10-26
> **Task:** CI/CD Stage 6.2 (preview on macedonianserver)
> **Status:** Fixed; replacement image published and verified on the server

---

## Issue Summary

The first image published to GHCR
(`ghcr.io/jonnabio/mentor-pro@sha256:4ab51ff3c10b4009219f9b126958bd278b2c7caf3e80a23a6679feafdbd8a787`,
run 40253896144, commit `517a502`) passed CI but exits on startup. The
Stage 6.2 preview container on macedonianserver stopped with exit code 1
before serving any request.

---

## Evidence

On macedonianserver, after
`docker run -d --name mentor-pro-preview -p 127.0.0.1:8081:8000 <digest>`:

```text
$ docker ps -a --filter name=mentor-pro-preview --format "{{.Status}}"
Exited (1)
$ curl http://127.0.0.1:8081/
curl: (7) Failed to connect to 127.0.0.1 port 8081
$ docker logs mentor-pro-preview
  File "/app/app/writing/contracts.py", line 15, in <module>
    import jsonschema
ModuleNotFoundError: No module named 'jsonschema'
```

`jsonschema==4.23.0` was listed only in `requirements-dev.txt`; the
`Dockerfile` installs only `requirements.txt`.

---

## 5 Whys

1. Why did the container exit? `uvicorn` could not import `app.main`:
   `app/writing/contracts.py` imports `jsonschema`, which is not installed.
2. Why was it not installed? It was declared in `requirements-dev.txt`,
   where it was first added for the ACE checker scripts (T001), before the
   writing contracts (T020) made it a runtime import of the app.
3. Why did the tests pass? The `tests` job installs `requirements-dev.txt`,
   so every test ran with `jsonschema` present.
4. Why did the Docker job pass? It only built and pushed the image; nothing
   ever started the container that was about to be published.
5. Why was there no check that runtime imports match production
   dependencies? Development and production dependencies were split
   without a rule or test tying the app's imports to `requirements.txt`.

**Root cause:** the pipeline published an image without starting it, and
nothing verified that the app's runtime imports are installed by
`requirements.txt`.

A second effect: in an image without `jsonschema`, the shared checker
(`item_checker.load_validator`) does not fail; it reports C01 "jsonschema
not installed; schema not validated" as a warning, so generated items
would have skipped schema validation silently had the app started.

---

## Fix

- `jsonschema==4.23.0` moved from `requirements-dev.txt` to
  `requirements.txt` (still installed for development through
  `-r requirements.txt`).
- `.github/workflows/ci.yml`, `docker-build` job, on every push to `dev`
  and `main` and every PR:
  1. build the image once into the runner's Docker engine (`load: true`);
  2. start it and require `GET /` to answer HTTP 200 within 60 s; the step
     fails if the container exits, never answers, or answers another code,
     and prints the container logs;
  3. on push to `main` only, tag and push **that same local image**
     (`docker tag` / `docker push`), so the published artifact is the one
     that passed the smoke test, never a rebuild.

`GET /` proves the server starts and serves the UI; it does not prove
database connectivity or curriculum readiness (Stage 6.3 integration
checks).

---

## Prevention

- Test: `tests/app/test_runtime_dependencies.py` parses every import in
  `app/`, `curriculum/` and the checker scripts loaded at runtime, and
  fails when a third-party module is not installed by `requirements.txt`
  (directly or as a dependency of a declared package). Verified failing
  with `jsonschema` removed from `requirements.txt`.
- CI smoke test as a mandatory publication gate (above).
- Guard RCA-005 in `docs/rca/regression-guards.yaml`.

### Corrected build evidence

- `dev` run 40349885223 (commit `8626543`): smoke step
  `GET / -> HTTP 200`; login and publish steps skipped.
- `main` (PR #4, merge `7e45376`): smoke step `GET / -> HTTP 200`, then
  `testing` and `sha-7e45376a43ac62693f109116dfb2217ea3766b3a` pushed with
  digest
  `sha256:486dcc0aaf6ba02addf3a9890f24613d4645dd8c4da25d62b7f64d17f2235e20`.
- macedonianserver (2026-10-26): pulled by that digest (`linux/amd64`,
  245 MB), `mentor-pro-preview` on `127.0.0.1:8081` is up,
  `GET / -> HTTP 200`, title "Mentor Pro · Práctica PNE",
  "Application startup complete".

---

## Lessons Learned

A green build is not a working artifact. Run the artifact you will publish,
and keep test environments from hiding missing production dependencies.
