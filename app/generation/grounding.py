"""Grounding bundle for one objective and one evidencia (mep-curriculum-grounding skill).

All curricular text comes verbatim from the catalog. The bundle also yields
checker-ready curriculum records (curriculum-record schema 1.1 shape) so the
deterministic checker validates against exactly the text the model was given.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from curriculum.catalog import AssessmentType, get_objective

SPEC_VERSION = "PNE2026"
APPLICATION = "sumativa"


class GroundingError(ValueError):
    """Objective or evidencia cannot ground a multiple-choice item (abstain)."""


@dataclass(frozen=True)
class GroundingBundle:
    baseline_version: str
    subject: str
    objective: dict[str, Any]
    evidence: dict[str, Any]

    @property
    def objective_code(self) -> str:
        return self.objective["workbook_code"]

    @property
    def concept_lines(self) -> list[str]:
        """Curricular concepts split into lines (bullets stripped), used as reviewed facts."""
        lines = []
        for raw in self.objective["concepts_es"].splitlines():
            line = raw.strip().lstrip("•").strip()
            if line:
                lines.append(line)
        return lines

    def records(self) -> list[dict[str, Any]]:
        """Checker records: bloque, afirmación and the selected evidencia."""
        common = {
            "spec_version": SPEC_VERSION,
            "application": APPLICATION,
            "subject": self.subject,
            "provenance": self.objective["provenance"],
            "baseline_status": self.objective["baseline_status"],
            "verification_status": self.objective["verification_status"],
            "assessment_type": self.objective["assessment_type"],
            "review": {"status": "pending"},
        }
        return [
            {**common, "record_id": self.objective["block_id"], "record_type": "bloque", "parent_id": None,
             "text_es": self.objective["block_name_es"]},
            {**common, "record_id": self.objective["id"], "record_type": "afirmacion",
             "parent_id": self.objective["block_id"], "text_es": self.objective["text_es"]},
            {**common, "record_id": self.evidence["id"], "record_type": "evidencia",
             "parent_id": self.objective["id"], "text_es": self.evidence["text_es"],
             "provenance": self.evidence["provenance"], "verification_status": self.evidence["verification_status"]},
        ]


def select_evidence(objective: dict[str, Any], evidence_ordinal: int | None) -> dict[str, Any]:
    """Explicit ordinal if given, otherwise the first evidencia (deterministic)."""
    evidences = sorted(objective["evidences"], key=lambda e: e["ordinal"])
    if not evidences:
        raise GroundingError(f"{objective['workbook_code']} has no evidencias")
    if evidence_ordinal is None:
        return evidences[0]
    for evidence in evidences:
        if evidence["ordinal"] == evidence_ordinal:
            return evidence
    raise GroundingError(f"{objective['workbook_code']} has no evidencia {evidence_ordinal}")


def build_grounding(conn: psycopg.Connection, baseline: str, subject: str, objective_code: str,
                    evidence_ordinal: int | None = None) -> GroundingBundle:
    objective = get_objective(conn, baseline, objective_code)
    if objective is None:
        raise GroundingError(f"objective {objective_code} not in baseline {baseline}")
    if objective["subject_code"] != subject:
        raise GroundingError(f"objective {objective_code} belongs to {objective['subject_code']}, not {subject}")
    if objective["assessment_type"] != AssessmentType.MULTIPLE_CHOICE.value:
        raise GroundingError(f"objective {objective_code} is a written-production criterion")
    if objective["baseline_status"] != "approved" and objective["provenance"] != "official":
        raise GroundingError(f"objective {objective_code} is not groundable")
    return GroundingBundle(baseline, subject, objective, select_evidence(objective, evidence_ordinal))
