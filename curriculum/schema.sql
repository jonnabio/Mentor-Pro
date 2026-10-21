-- Mentor Pro curriculum catalog (SQLite), schema version 1.
-- Five tables per ADR-006. Curricular text columns store workbook cells verbatim.
-- No student data is stored here.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subject (
    code     TEXT PRIMARY KEY CHECK (code IN ('espanol', 'matematicas', 'ciencias', 'estudios_sociales')),
    name_es  TEXT NOT NULL UNIQUE,
    id_code  TEXT NOT NULL UNIQUE CHECK (id_code IN ('ESP', 'MAT', 'CIE', 'EST'))
);

-- Documents imported (the workbook) and documents cited by records (MEP 2026 marco / rúbrica).
CREATE TABLE IF NOT EXISTS source_document (
    baseline_version  TEXT NOT NULL,
    id                TEXT NOT NULL,
    title             TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('workbook', 'spec_table', 'rubric')),
    year              INTEGER NOT NULL,
    file_ref          TEXT,              -- generic manifest name; never a student-identifying name
    sha256            TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
    provenance        TEXT NOT NULL CHECK (provenance IN ('official', 'secondary')),
    availability      TEXT NOT NULL CHECK (availability IN ('held', 'cited_not_held')),
    imported_at       TEXT,              -- set for the imported workbook only
    PRIMARY KEY (baseline_version, id)
);

CREATE TABLE IF NOT EXISTS block (
    baseline_version  TEXT NOT NULL,
    id                TEXT NOT NULL,     -- e.g. PNE2026-PRI-MAT-SUM-B2
    subject_code      TEXT NOT NULL REFERENCES subject (code),
    assessment_type   TEXT NOT NULL CHECK (assessment_type IN ('multiple_choice', 'written_rubric')),
    ordinal           INTEGER NOT NULL CHECK (ordinal >= 1),
    name_es           TEXT NOT NULL,     -- verbatim "Bloque MEP" cell, including any "(40 %)"
    weight_pct        INTEGER CHECK (weight_pct IS NULL OR weight_pct BETWEEN 0 AND 100),
    PRIMARY KEY (baseline_version, id),
    UNIQUE (baseline_version, subject_code, assessment_type, ordinal),
    UNIQUE (baseline_version, subject_code, assessment_type, name_es)
);

-- One row per workbook "Código" (objective = afirmación or rubric criterion).
CREATE TABLE IF NOT EXISTS assertion (
    baseline_version     TEXT NOT NULL,
    id                   TEXT NOT NULL,  -- e.g. PNE2026-PRI-MAT-SUM-B1-A7
    workbook_code        TEXT NOT NULL,  -- stable user-facing objective code, e.g. M07
    block_id             TEXT NOT NULL,
    ordinal              INTEGER NOT NULL CHECK (ordinal >= 1),
    numbering_es         TEXT NOT NULL,  -- verbatim "Numeración", e.g. "Afirmación 7"
    text_es              TEXT NOT NULL,  -- verbatim "Afirmación / criterio"
    concepts_es          TEXT NOT NULL,  -- verbatim "Conceptos detallados"
    check_activity_es    TEXT NOT NULL,  -- verbatim "Actividad de comprobación"
    source_citation_es   TEXT NOT NULL,  -- verbatim "Fuente / página"
    source_document_id   TEXT NOT NULL,
    source_table         TEXT,           -- parsed from the citation, e.g. "Tabla 3"
    source_page          INTEGER,        -- parsed PDF page
    planned_items_raw    TEXT NOT NULL,  -- verbatim "Ítems previstos"
    planned_items        INTEGER,        -- parsed; NULL for rubric criteria
    evidence_count       INTEGER NOT NULL,
    provenance           TEXT NOT NULL CHECK (provenance IN ('official', 'secondary')),
    baseline_status      TEXT NOT NULL CHECK (baseline_status IN ('approved', 'withdrawn')),
    verification_status  TEXT NOT NULL CHECK (verification_status IN ('unverified', 'verified', 'discrepancy')),
    PRIMARY KEY (baseline_version, id),
    UNIQUE (baseline_version, workbook_code),
    FOREIGN KEY (baseline_version, block_id) REFERENCES block (baseline_version, id),
    FOREIGN KEY (baseline_version, source_document_id) REFERENCES source_document (baseline_version, id)
);

CREATE TABLE IF NOT EXISTS evidence (
    baseline_version     TEXT NOT NULL,
    id                   TEXT NOT NULL,  -- e.g. PNE2026-PRI-MAT-SUM-B1-A7-E3
    assertion_id         TEXT NOT NULL,
    ordinal              INTEGER NOT NULL CHECK (ordinal >= 1),  -- verbatim "N.º"
    text_es              TEXT NOT NULL,  -- verbatim "Evidencia / criterio verificable"
    provenance           TEXT NOT NULL CHECK (provenance IN ('official', 'secondary')),
    verification_status  TEXT NOT NULL CHECK (verification_status IN ('unverified', 'verified', 'discrepancy')),
    PRIMARY KEY (baseline_version, id),
    UNIQUE (baseline_version, assertion_id, ordinal),
    FOREIGN KEY (baseline_version, assertion_id) REFERENCES assertion (baseline_version, id)
);

CREATE INDEX IF NOT EXISTS idx_assertion_block ON assertion (baseline_version, block_id);
CREATE INDEX IF NOT EXISTS idx_evidence_assertion ON evidence (baseline_version, assertion_id);
