"""Synthetic workbook with the real layout, plus manifest helpers."""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from curriculum import importer  # noqa: E402

CAT_HEADERS = list(importer.CATALOG_HEADERS)
EV_HEADERS = list(importer.EVIDENCE_HEADERS)
SRC_MAT = "Tabla 3, marco sumativo MEP 2026; pág. PDF 18."
SRC_LEC = "Tabla 3, marco sumativo MEP 2026; pág. PDF 17."
SRC_RUB = "rúbrica MEP 2026; pág. PDF 4."


def catalog_rows() -> list[list]:
    return [
        ["M01", "Matemáticas", "Números", "Afirmación 1", "Resuelve problemas con números naturales.",
         "Valor posicional.\n• Lectura y escritura.", "Escribí 12 500 en letras.", SRC_MAT, 2.0, "3 ítem(s) previsto(s)"],
        ["M02", "Matemáticas", "Números", "Afirmación 2", "Compara números naturales.",
         "Comparación con <, > o =.", "Ordená cinco números.", SRC_MAT, 1.0, "2 ítem(s) previsto(s)"],
        ["M03", "Matemáticas", "Geometría", "Afirmación 1", "Compara números naturales.",
         "Mismo texto que M02 en otro bloque.", "Medí ángulos.", SRC_MAT, 1.0, "1 ítem(s) previsto(s)"],
        ["EL01", "Español", "Comprensión lectora", "Afirmación 1", "Distingue las ideas fundamentales en textos no literarios.",
         "Tema e idea principal.", "Leé un artículo breve.", SRC_LEC, 1.0, "2 ítem(s) previsto(s)"],
        ["EE01", "Español", "Convenciones lingüísticas (15 %)", "Afirmación 1", "Emplea correctamente la tilde.",
         "Tilde diacrítica.", "Revisá tu texto.", SRC_RUB, 1.0, "criterio de rúbrica"],
    ]


def evidence_rows() -> list[list]:
    return [
        ["M01", 1.0, "Lee números  mayores que 100 000.", "Matemáticas", False,
         "Resuelve problemas con números naturales.", "Números", SRC_MAT],
        ["M01", 2.0, "Escribe números en notación desarrollada.", "Matemáticas", True,
         "Resuelve problemas con números naturales.", "Números", SRC_MAT],
        ["M02", 1.0, "Usa los símbolos <, > o =.", "Matemáticas", False,
         "Compara números naturales.", "Números", SRC_MAT],
        ["M03", 1.0, "Compara medidas de ángulos.", "Matemáticas", False,
         "Compara números naturales.", "Geometría", SRC_MAT],
        ["EL01", 1.0, "Explica qué es una idea fundamental.", "Español", False,
         "Distingue las ideas fundamentales en textos no literarios.", "Comprensión lectora", SRC_LEC],
        ["EE01", 1.0, "Coloca la tilde en palabras agudas.", "Español", False,
         "Emplea correctamente la tilde.", "Convenciones lingüísticas (15 %)", SRC_RUB],
    ]


def write_workbook(path: Path, cat: list[list], ev: list[list],
                   cat_headers: list[str] | None = None) -> Path:
    wb = openpyxl.Workbook()
    wb.active.title = "01 Panel"
    for name, headers, rows in (("06 Evidencias", EV_HEADERS, ev), ("07 Catálogo", cat_headers or CAT_HEADERS, cat)):
        ws = wb.create_sheet(name)
        ws.append([f"TÍTULO {name}"])
        ws.append(["Nota"])
        ws.append([])
        ws.append(headers)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


def register(manifest: Path, workbook: Path, name: str = "synthetic-workbook.xlsx") -> None:
    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write(f"{digest} *{name}\n")


# PostgreSQL test database. Each test gets its own schema, dropped afterwards.
# The database name must end in "_test" so tests can never touch the real catalog.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://mentor_pro_admin@127.0.0.1:5432/mentor_pro_test")


@dataclass(frozen=True)
class PgTarget:
    url: str
    schema: str


def new_target() -> PgTarget:
    database = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        raise RuntimeError(f"refusing to run tests against non-test database {database!r}")
    return PgTarget(TEST_DATABASE_URL, f"t_{uuid.uuid4().hex[:12]}")


def drop_target(target: PgTarget) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(target.url, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(target.schema)))


def query(target: PgTarget, statement: str, *args) -> list[tuple]:
    """Run a query in the target schema and return tuples (creates tables if missing)."""
    from psycopg.rows import tuple_row

    from curriculum import db

    with db.connect(target.url, target.schema) as conn:
        return conn.cursor(row_factory=tuple_row).execute(statement, args or None).fetchall()


BASELINE_WORKBOOK_SHA = "cce57db40afacdb2f6d2492c39ba9df6c1bc398941c1c7fb9cff8ec28bcc19d3"


def baseline_workbook() -> Path | None:
    """The real baseline workbook, located by checksum (not in Git), or None."""
    for path in (REPO_ROOT / "references" / "original").glob("*.xlsx"):
        if hashlib.sha256(path.read_bytes()).hexdigest() == BASELINE_WORKBOOK_SHA:
            return path
    return None
