# ADR-004: Web Application Stack

> **Status:** Proposed
> **Date:** 2026-10-21

---

## Context

Mentor Pro is a web application for Costa Rican sixth-grade students. It must be
simple to operate now and scale later. Question generation through free
OpenRouter models is slow (minutes per batch). Curriculum ingestion needs PDF
and DOCX processing. Mathematics verification needs exact rational arithmetic.
A local PostgreSQL 17 server is available for development.

---

## Decision

We will use a modular monolith:

- **Backend:** Python with FastAPI. Ingestion, generation, validation, routing
  and cost observability are internal modules with explicit interfaces.
- **Database:** PostgreSQL (local 17 for development; managed Postgres such as
  Supabase in hosted environments).
- **Long-running generation:** jobs table in Postgres processed by a worker
  process. No separate broker until load requires it.
- **Frontend:** React with Vite, Costa Rican Spanish UI strings.

Not included: detailed schema, API or UI design. Those follow in later stages.

---

## Alternatives Considered

### Alternative 1: Full-stack TypeScript (Next.js)

- **Pros:** One language; simple hosting.
- **Cons:** Weaker PDF extraction and exact-math tooling.
- **Why rejected:** Ingestion and verification are core.

### Alternative 2: Microservices

- **Pros:** Independent scaling.
- **Cons:** Operational cost far above current needs.
- **Why rejected:** Premature; module boundaries allow later extraction.

---

## Consequences

### Positive

- Skills scripts in Python can be reused directly by the backend.
- One deployable unit plus one worker.

### Negative

- Two languages (Python, TypeScript) across backend and frontend.

### Neutral

- Scaling path: more workers, then extract the worker as its own service.

---

## Related

- [ADR-005](ADR-005-question-engine-skill-suite.md)
