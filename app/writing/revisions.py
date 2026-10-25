"""Versioned editorial revisions of stored writing exercises (T024, ADR-023).

A revision spec names an exercise, a reason and targeted replacements: in instructions, in the text (applied
to both the text with errors and the tutor-only reference) and in corrections, plus documented
alternatives. The revised record and reference pass the same checks as generated exercises before they are
appended to writing.exercise_revision. Earlier revisions, generation histories and submissions are kept.
Applying a spec whose reason is already stored does nothing.
"""

from __future__ import annotations

import copy
from typing import Any

import psycopg

from app.writing import contracts, editing, generation
from app.writing.store import InvalidRecord, WritingStore


def _replace(text: str, old: str, new: str, where: str) -> str:
    if text.count(old) != 1:
        raise InvalidRecord([f"{where}: {old!r} occurs {text.count(old)} times"])
    return text.replace(old, new)


def revise(spec: dict[str, Any], record: dict[str, Any], reference: dict[str, Any] | None) -> tuple[dict, dict]:
    record, reference = copy.deepcopy(record), copy.deepcopy(reference)
    if "set_instructions" in spec:  # T025: composed exercises may get a whole new, shorter instruction list
        record["instructions_es"] = list(spec["set_instructions"])
    for old, new in spec.get("situation", []):
        record["communicative_situation_es"] = _replace(record["communicative_situation_es"], old, new, "situation")
    record["deliverable"].update(spec.get("deliverable", {}))
    for idea in spec.get("ideas_remove", []):
        if idea not in record.get("suggested_ideas_es", []):
            raise InvalidRecord([f"idea {idea!r} not found"])
        record["suggested_ideas_es"].remove(idea)
    for old, new in spec.get("instructions", []):
        matches = [i for i, line in enumerate(record["instructions_es"]) if line == old]
        if len(matches) != 1:
            raise InvalidRecord([f"instruction {old!r} not found once"])
        record["instructions_es"][matches[0]] = new
    for old, new in spec.get("text", []):
        record["source_text_es"] = _replace(record["source_text_es"], old, new, "text")
        reference["corrected_text_es"] = _replace(reference["corrected_text_es"], old, new, "reference")
    for change in spec.get("corrections", []):
        found = [c for c in reference["corrections"] if c["error"] == change["error"]]
        if len(found) != 1:
            raise InvalidRecord([f"correction {change['error']!r} not found once"])
        found[0]["error"], found[0]["correction"] = change["new_error"], change["new_correction"]
        # After the text replacements, `reference_old` is the fragment of the reference to correct anew.
        reference["corrected_text_es"] = _replace(reference["corrected_text_es"], change["reference_old"],
                                                  change["new_correction"], "reference fix")
    if "ambiguities_es" in spec:
        reference["ambiguities_es"] = spec["ambiguities_es"]
    return record, reference


def checks_for(catalog: psycopg.Connection, store: WritingStore, record: dict[str, Any],
               reference: dict[str, Any] | None, baseline: str) -> list[dict[str, str]]:
    """Correction exercises: W02-W07, W09-W15. Composed paragraphs (T025): W02-W07, W13, W14, W16-W18."""
    level = contracts.level(record["level"])
    g = generation.build_grounding(catalog, baseline, f"L{level['ordinal']}", record["difficulty"],
                                   record["target_criteria"], exercise_type=record["exercise_type"])
    if record["exercise_type"] != "conventions_editing":
        stored = [r["record"] for r in store.exercises() if r["exercise_id"] != record["exercise_id"]]
        return (generation.deterministic_checks(g, record, [r["topic_es"] for r in stored])
                + generation.compose_checks(g, record, stored))
    others = [r["record"]["source_text_es"] for r in store.exercises("writing_conventions")
              if r["exercise_id"] != record["exercise_id"] and r["record"].get("source_text_es")]
    topics = [r["record"]["topic_es"] for r in store.exercises() if r["exercise_id"] != record["exercise_id"]]
    return (generation.deterministic_checks(g, record, topics) + editing.editing_checks(g, record, reference, others)
            + editing.quality_checks(record, reference))


def apply_revisions(store: WritingStore, catalog: psycopg.Connection, specs: list[dict[str, Any]],
                    baseline: str = "PNE2026-SUM-v1.0") -> list[dict[str, Any]]:
    results = []
    for spec in specs:
        eid = spec["exercise_id"]
        done = [r for r in store.revisions(eid) if r["reason"] == spec["reason"]]
        if done:
            results.append({"exercise_id": eid, "status": "present", "revision": done[0]["revision"]})
            continue
        current = store.record(eid)
        reference = store.reference_correction(eid)
        editing_type = current is not None and current["exercise_type"] == "conventions_editing"
        if current is None or (editing_type and reference is None):
            results.append({"exercise_id": eid, "status": "missing"})
            continue
        base_ref = {k: reference[k] for k in ("corrected_text_es", "corrections", "ambiguities_es")} \
            if editing_type else None
        record, new_ref = revise(spec, current, base_ref)
        checks = checks_for(catalog, store, record, {**new_ref, "exercise_id": eid} if new_ref else None, baseline)
        revision = store.add_revision(eid, record, new_ref, spec["reason"], checks)
        results.append({"exercise_id": eid, "status": "revised", "revision": revision,
                        "checks": [f"{c['id']}:{c['status']}" for c in checks]})
    return results
