"""Synthetic workbook with the real layout, plus manifest helpers."""

from __future__ import annotations

import hashlib
import sys
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
