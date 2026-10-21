---
name: mep-curriculum-grounding
description: Grounds every question-engine task in official MEP PNE curriculum records (componente, bloque temático, afirmación, evidencia), keeps original Spanish wording, separates official from secondary sources and rejects unsupported or invented curricular links. Use before planning, generating or reviewing any PNE question.
---

# Skill: MEP Curriculum Grounding

> Turns a curricular target into a verified grounding bundle, or abstains.

---

## Purpose

- Resolve a request (subject, application, afirmación or evidencia IDs) to
  official curriculum records.
- Preserve MEP Spanish verbatim; never paraphrase stored curricular text.
- Distinguish `official` from `secondary` sources.
- Detect invented or unsupported links before any generation happens.
- Keep source-level traceability and spec versions (e.g. `PNE2025`).

Shared rules: `.ace/standards/question-engine.md`.
Vocabulary: `.ace/knowledge/mep-pne-curriculum.md`.

---

## Activation

Use when a task:

- selects objectives, afirmaciones or evidencias for practice;
- needs curricular text for a prompt;
- reviews whether an item's curricular claim is supported;
- adds a new spec version or application (diagnóstica, sumativa).

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| `subject` | Yes | Machine code (`matematicas`, …) |
| `spec_version` | Yes | e.g. `PNE2025` |
| `application` | Yes | `diagnostica` or `sumativa` |
| `target_ids` | Yes | Afirmación or evidencia record IDs |
| `records` | Yes | Curriculum records (`.ace/schemas/question-engine/curriculum-record.schema.json`) |

---

## Outputs

A grounding bundle (JSON):

```json
{
  "status": "grounded",
  "spec_version": "PNE2025",
  "application": "diagnostica",
  "evidencias": [
    {
      "record_id": "PNE2025-PRI-MAT-DIAG-B1-A3-E2",
      "text_es": "Aplica los conceptos de divisibilidad, divisor o factor de un número natural, en situaciones de diversos contextos.",
      "afirmacion": { "record_id": "PNE2025-PRI-MAT-DIAG-B1-A3", "text_es": "Resuelve problemas, de diversos contextos, relacionados a los conceptos básicos de la teoría de números." },
      "bloque": { "record_id": "PNE2025-PRI-MAT-DIAG-B1", "text_es": "Números" },
      "cognitive_verb": "Aplica",
      "source": { "file_name": "Marco-de-especificaciones-de-Primaria-2025.pdf", "file_sha256": "804dbb9f…", "page": 37 }
    }
  ],
  "rejected_targets": []
}
```

`status` is `grounded`, `partial` (some targets rejected) or `abstain` (none usable).

---

## Prerequisites

- [ ] Records produced by `curriculum-data-ingestion` and schema-valid
- [ ] Source files listed in `references/MANIFEST.sha256`

---

## Procedures

### 1. Resolve the chain

```markdown
For each target ID:
1. Look up the record; afirmación targets expand to all child evidencias.
2. Walk parent_id: evidencia → afirmación → bloque. Every link must exist.
3. Confirm subject, application and spec_version match the request.
```

### 2. Enforce authority

```markdown
1. Keep only records with provenance = official and review.status != rejected.
2. Confirm source.file_sha256 appears in references/MANIFEST.sha256.
3. Secondary records may be attached as context, never as the grounding basis.
```

### 3. Detect unsupported links

Reject a target when:

- the ID does not exist (often an invented or model-made ID);
- the requested evidencia belongs to another afirmación or application;
- diagnóstica and sumativa tables are mixed;
- a prompt or item asserts a curricular relation absent from the records.

### 4. Extract the cognitive verb

Take the first verb of the evidencia `text_es` (e.g. *Aplica*, *Identifica*).
The verb definitions live in the componente's *infinitivos verbales* table.

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `curriculum-data-ingestion` | Produces the records this skill reads |
| `evidence-coverage-planning` | Consumes the grounding bundle |
| `mep-question-design` | Consumes verbatim `text_es` and the verb |
| `question-quality-review` | Re-checks grounding per item (checks G01–G03) |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| Unknown target ID | Add to `rejected_targets` with reason `unknown_id` |
| Broken parent chain | Reject target, reason `broken_chain` |
| Only secondary sources | Reject target, reason `no_official_source` |
| Checksum not in manifest | Reject target, reason `unverified_source` |
| All targets rejected | Return `status: abstain`; generation must not start |

Never "repair" a missing link from model memory.

---

## Examples

### Correct

Request `target_ids: ["PNE2025-PRI-MAT-DIAG-B1-A3"]` → bundle with every
evidencia of afirmación 3, each with verbatim `text_es` and page.

### Rejected

Request `PNE2025-PRI-MAT-DIAG-B1-A3-E9` → `abstain`, reason `unknown_id`:
afirmación 3 has no evidencia 9 in the records.

Sample records: `.ace/schemas/question-engine/examples/curriculum-records.json`.

---

## Common Pitfalls

1. **Paraphrasing curricular text**: breaks verbatim excerpt checks downstream.
2. **Ignoring the application**: diagnóstica and sumativa tables differ.
3. **Evidencia numbers without afirmación**: numbering restarts per afirmación.
4. **Treating guides as official**: workbooks and item collections are secondary.
5. **Using printed page numbers**: `source.page` is the PDF page index.

---

## Invocation

```markdown
"Apply the mep-curriculum-grounding skill from
.ace/skills/mep-curriculum-grounding/SKILL.md to build the grounding bundle
for PNE2025 diagnóstica, Matemáticas, afirmación B1-A3."
```
