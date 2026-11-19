"""Tutor view of quiz-size coverage per subject (T069, PO-T069-2026-11-16). Read-only, counts and codes only.

For each subject: which whole-subject sizes the bank composes now (the real `BankComposer`, the same check the
student availability makes, T063), and for every size that does not, what blocks it, by stage
(`capacity.stages`): the fixed seeding plan, generated questions, approved questions. The gap is reported per
objective and per level, with the questions awaiting tutor review that could close it. Total inventory is never
used as readiness: a size is available only when the composer assembles it.

Pending-review questions are never counted as available; nothing here records a verdict or generates anything.
Served only by the tutor service under /api/tutor/coverage with the shared tutor check.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query

from app.allocation import MIXED_CYCLE, QUESTION_COUNTS
from app.practice import capacity, coverage, seeding
from app.practice.bank import QuestionBank
from app.practice.bank_allocation import BankComposer
from app.writing.tutor import LOOPBACK, tutor_guard
from curriculum.catalog import PracticeScope, SelectionError, select_objectives

LEVELS = MIXED_CYCLE
TARGET_SIZE = max(QUESTION_COUNTS)


def _pending_and_plan(url: str, baseline: str, subject: str, objectives: list[dict[str, Any]],
                      servable: frozenset[str] = frozenset()) -> tuple[dict[str, Counter[str]], dict[str, Counter[str]]]:
    """Questions awaiting review and planned cells, per objective and level, from the subject's current batch.
    T072: a question already eligible (`servable`, automatic eligibility) is counted as approved, not pending."""
    pending: dict[str, Counter[str]] = {o["workbook_code"]: Counter() for o in objectives}
    batch = seeding.current_batch(url, baseline, subject)
    if batch is None:
        return pending, capacity.plan_cells(objectives, seeding.DEFAULT_TARGET)
    plan: dict[str, Counter[str]] = {o["workbook_code"]: Counter() for o in objectives}
    cells = {c["cell"]: c for c in batch["plan"]}
    for c in batch["plan"]:
        plan.setdefault(c["objective_code"], Counter())[c["difficulty"]] += 1
    for link in seeding._awaiting_item_review(url, batch["batch_id"]).values():
        if link["request_id"] in servable:
            continue
        cell = cells[link["cell"]]
        pending.setdefault(cell["objective_code"], Counter())[cell["difficulty"]] += 1
    return pending, plan


def _blockers(entry: dict[str, Any], pending: dict[str, Counter[str]], levels: tuple[str, ...]) -> dict[str, Any]:
    """The approved-question gap of one size, with the pending questions that could close each part of it."""
    gap = entry["approved_gap"]
    objectives = [{"objective_code": code, "needed": g["needed"], "approved": g["fillable"],
                   "missing": g["needed"] - g["fillable"],
                   "pending": sum(pending.get(code, Counter())[lv] for lv in levels)}
                  for code, g in sorted(gap["objectives"].items())]
    levels_out = [{"difficulty": lv, "needed": g["needed"], "approved": g["fillable"],
                   "missing": g["needed"] - g["fillable"],
                   "pending": sum(pending.get(code, Counter())[lv] for code in entry["need"])}
                  for lv, g in gap["levels"].items()]
    return {"missing": gap["missing"], "objectives": objectives, "levels": levels_out}


class CoverageReport:
    def __init__(self, url: Callable[[], str], baseline: str, subjects: tuple[tuple[str, str], ...],
                 open_catalog: Callable[[str], psycopg.Connection]):
        self.url, self.baseline, self.subjects, self.open_catalog = url, baseline, subjects, open_catalog

    def subject(self, subject: str) -> dict[str, Any]:
        url = self.url()
        catalog = self.open_catalog(url)
        try:
            objectives = select_objectives(catalog, self.baseline, PracticeScope.SUBJECT_SIMULATION,
                                           subject).objectives
            bank = QuestionBank(url)
            composer, approved = coverage.held(bank, catalog, self.baseline, subject, objectives)
            with bank.connect() as db:
                composer.db = db
                available = composer.available_sizes(QUESTION_COUNTS)
                single = {lv: BankComposer(bank, catalog, self.baseline, subject, objectives, lv, db)
                          .available_sizes(QUESTION_COUNTS) for lv in LEVELS}
            servable = frozenset(c["request_id"] for o in objectives for c in composer._candidates(o))
            pending, plan = _pending_and_plan(url, self.baseline, subject, objectives, servable)
        finally:
            catalog.close()
        sizes = []
        for size in QUESTION_COUNTS:
            entry = capacity.stages(objectives, size, "mixed", plan, pending, approved, size in available)
            sizes.append({"size": size, "available": size in available, "ok": entry["ok"],
                          "first_failure": entry["first_failure"], "blocker": entry["blocker"],
                          "missing": entry["missing"], "cause": entry["cause"],
                          **({} if size in available else {"gap": _blockers(entry, pending, LEVELS)})})
        nxt = next((s for s in sizes if not s["available"]), None)
        target = sizes[-1]
        return {
            "subject": subject, "name_es": dict(self.subjects).get(subject, subject),
            "objectives": len(objectives),
            "approved": sum(sum(c.values()) for c in approved.values()),
            "pending": sum(sum(c.values()) for c in pending.values()),
            "plan_cells": sum(sum(c.values()) for c in plan.values()),
            "available_sizes": available, "single_level_sizes": single,
            "next_size": nxt["size"] if nxt else None,
            "sizes": sizes,
            "progress": {"size": TARGET_SIZE, "approved_fill": TARGET_SIZE - target["missing"]["approved"],
                         "with_pending_fill": TARGET_SIZE - target["missing"]["generated"],
                         "plan_fill": TARGET_SIZE - target["missing"]["plan"]},
            "cells": [{"objective_code": o["workbook_code"], "evidences": len(o["evidences"]),
                       **{lv: {"approved": approved[o["workbook_code"]][lv],
                               "pending": pending.get(o["workbook_code"], Counter())[lv],
                               "plan": plan.get(o["workbook_code"], Counter())[lv]} for lv in LEVELS}}
                      for o in objectives],
        }


def build_coverage_router(report: CoverageReport, api_error: type[Exception], token: str,
                          allowed_hosts: frozenset[str] = LOOPBACK) -> APIRouter:
    router = APIRouter(prefix="/api/tutor/coverage", tags=["tutor"],
                       dependencies=[Depends(tutor_guard(api_error, token, allowed_hosts))])
    codes = [code for code, _ in report.subjects]

    @router.get("")
    def subject_coverage(subject: str = Query(max_length=40)) -> dict[str, Any]:
        if subject not in codes:
            raise api_error(422, "unknown_subject", "La materia seleccionada no existe.")
        try:
            return {**report.subject(subject), "subjects": [{"subject": c, "name_es": n} for c, n in report.subjects]}
        except SelectionError:
            raise api_error(404, "no_objectives", "Esta materia no tiene objetivos de selección única.") from None

    return router
