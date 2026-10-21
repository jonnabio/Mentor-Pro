# MEP PNE Curriculum Knowledge

> Domain vocabulary for the sixth-grade *Prueba Nacional Estandarizada*.
> Terms are kept in the original Spanish. Source: *Marco de especificaciones
> Prueba Nacional Estandarizada Primaria 2025* (MEP).

---

## Hierarchy

```text
Componente (asignatura)
└── Bloque temático
    └── Afirmación        "La persona estudiante ..."
        └── Evidencia     numbered per afirmación
```

Each componente also defines **infinitivos verbales** (e.g. *Identificar*,
*Inferir*, *Utilizar*) with a component-specific *definición y descripción*.

---

## Terms

| Term | Meaning in this project |
|------|-------------------------|
| **Componente** | One of the four tested subjects |
| **Bloque temático** | Thematic block within a componente (e.g. *1. Comprensión lectora*, *Bloque 1: Números*) |
| **Afirmación** | Claim about what the student can do; written "La persona estudiante …" |
| **Evidencia** | Observable behaviour supporting an afirmación; the unit every item targets |
| **Infinitivo verbal** | Cognitive verb used in afirmaciones and evidencias; defines cognitive action |
| **Aplicación diagnóstica** | Diagnostic application with its own afirmaciones/evidencias tables |
| **Aplicación sumativa** | Summative application; tables add *Cantidad de ítems* per afirmación |
| **Ítem de selección de respuesta** | Multiple-choice item |
| **Forma actual** | Item style the Marco promotes: problem in a context close to the student, with stimulus |
| **Forma tradicional** | Recall-only style the Marco contrasts against; avoid |
| **Programa de Estudio** | Official subject syllabus (e.g. `MATEMATICAS-PRIMARIA-DIURNA.pdf`) |
| **Marco de referencia** | Framework document the Marco de especificaciones depends on |

---

## Source Documents

Authority is decided per file by `mep-curriculum-grounding`. Default
classification of files in `references/original/`:

| File pattern | Default provenance |
|--------------|--------------------|
| `Marco-de-especificaciones-*.pdf` | `official` |
| `*-PRIMARIA-DIURNA.pdf` (Programas de Estudio) | `official` |
| Guías, cuadernos, workbooks, `Examen_Diagnostico_*`, item collections | `secondary` |
| `PNE-Tracker-2026-workbook.xlsx` (generic name) | `secondary`, approved baseline `PNE2026-SUM-v1.0` (ADR-006) |

Checksums: `references/MANIFEST.sha256`.

---

## Known Facts From the Marco (2025)

- The Marco states it is not a *temario*.
- Diagnostic and summative applications have separate tables; never merge them.
- Example items in the Marco are images; text extraction does not capture them.

---

<!-- markdownlint-disable-next-line MD036 -- metadata footer, not a heading -->
*Last Updated: 2026-10-21*
