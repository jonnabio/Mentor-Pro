"""Benchmark candidate writing reviewers on stored exercises with seeded defects (T031, ADR-029).

Discovers free text models on OpenRouter (no hardcoded candidates), picks up to three by the rule in
`select_candidates`, and sends each the production review prompt (W08) of 12 fixed cases: 4 stored exercises
as they are (L1-L4) and 8 in-memory copies with one seeded defect each. Stored exercises, revisions,
references and validations are only read. Usage goes to llm.usage_record (purpose `evaluation`) through one
budget gate, so the daily request and USD budgets apply. Never prints the key.

Usage:
    .venv/Scripts/python.exe scripts/dev/benchmark_writing_reviewers.py --discover
    .venv/Scripts/python.exe scripts/dev/benchmark_writing_reviewers.py --out report.json [--models a,b] [--primary]
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.generation.parsing import OutputError  # noqa: E402
from app.llm.budget import BudgetGate  # noqa: E402
from app.llm.client import OpenRouterClient  # noqa: E402
from app.llm.router import route, same_model  # noqa: E402
from app.llm.settings import LlmSettings  # noqa: E402
from app.llm.usage import UsageStore  # noqa: E402
from app.writing import contracts, generation, revalidation  # noqa: E402
from app.writing.store import WritingStore  # noqa: E402
from curriculum import db  # noqa: E402
from curriculum.catalog import open_catalog  # noqa: E402

VERSION = "writing-reviewer-benchmark-1.0"
MAX_CANDIDATES = 3
MIN_CONTEXT = 32000              # longest review prompt is about 3k tokens plus up to 6000 output tokens
MAX_CALLS = 160                  # whole benchmark, retries included (4 models x 12 cases x 3 attempts = 144)
SPECIALIST = ("code", "coder", "safety", "guard", "embed", "rerank")
L1_AGREE, L1_SPELL, L1_PUNCT = ("PE-L1-futbol-comunidad-f136a4", "PE-L1-manglares-terraba-cafb78",
                                "PE-L1-huerta-escolar-8c310b")
L2, L3, L4 = "PE-L2-puntualidad-escuela-su-6aa679", "PE-L3-uso-adecuado-banos-f1da0d", "PE-L4-uso-responsable-redes-f9acfc"
# Qualification criteria (ADR-029), fixed before the run.
CRITERIA = {"structured_rate_min": 11 / 12, "truncation_rate_max": 0.10, "http_error_rate_max": 0.25,
            "defects_flagged_min": 7, "valid_passed_min": 3, "every_defect_category": True}


# ---------------------------------------------------------------- discovery

def select_candidates(client: OpenRouterClient, settings: LlmSettings) -> dict[str, Any]:
    """Free text models other than the generators and the primary reviewer, with structured output and enough
    context, no routers or specialist models; at most one per vendor, other vendors than the generator's first,
    then the longest context (the listing gives no model size; this keeps out small models such as 2-3B ones),
    then models listing `structured_outputs`."""
    generators = [m for m in settings.free_models if m not in settings.generation_excluded_models]
    primary = settings.writing_review_models[0] if settings.writing_review_models else None
    rows, ranked = [], []
    for m in client.list_models():
        if not (m.is_free and m.is_text_chat):
            continue
        params = set(m.supported_parameters)
        reason = None
        if any(same_model(m.id, g) for g in generators):
            reason = "generator"
        elif same_model(m.id, primary):
            reason = "primary reviewer"
        elif m.id.startswith("openrouter/"):
            reason = "router, not a model"
        elif any(word in m.id.lower() for word in SPECIALIST):
            reason = "specialist model"
        elif not params & {"response_format", "structured_outputs"}:
            reason = "no structured output"
        elif (m.context_length or 0) < MIN_CONTEXT:
            reason = "context too short"
        rows.append({"id": m.id, "context_length": m.context_length, "structured_outputs": "structured_outputs" in params,
                     "excluded": reason})
        if reason is None:
            ranked.append(m)
    gen_vendors = {g.split("/")[0] for g in generators}
    ranked.sort(key=lambda m: (m.id.split("/")[0] in gen_vendors, -(m.context_length or 0),
                               "structured_outputs" not in m.supported_parameters, m.id))
    chosen, vendors = [], set()
    for m in ranked:
        if m.id.split("/")[0] not in vendors and len(chosen) < MAX_CANDIDATES:
            chosen.append(m.id)
            vendors.add(m.id.split("/")[0])
    return {"generators": generators, "primary": primary, "listed": rows, "candidates": chosen}


# ---------------------------------------------------------------- cases

def build_cases(store: WritingStore) -> list[dict[str, Any]]:
    """12 fixed cases. Each defect case changes an in-memory copy only and names the review keys that should
    fall below 2 (`expect`); a case is detected when any score is below 2."""
    current = {r["exercise_id"]: r for r in store.exercises(eligible_only=False)}

    def base(eid: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        row = current[eid]
        record = copy.deepcopy(row["record"])
        ref = store.reference_correction(eid, row["revision"]) if record["exercise_type"] == "conventions_editing" else None
        reference = {k: copy.deepcopy(ref[k]) for k in ("corrected_text_es", "corrections", "ambiguities_es")} if ref else None
        return record, reference

    cases = []

    def add(case_id: str, category: str, eid: str, mutate=None, expect=(), note: str = "") -> None:
        record, reference = base(eid)
        if mutate:
            mutate(record, reference)
        cases.append({"case_id": case_id, "category": category, "exercise_id": eid, "record": record,
                      "reference": reference, "expect": list(expect), "note": note})

    for eid in (L1_AGREE, L2, L3, L4):
        add(f"valid-{eid[3:5]}", "valid", eid, note="stored exercise, current revision, eligible")

    def tu_l2(r, _):
        r["instructions_es"] = ["Escribe un solo parrafo de introducion.", "Escribe un parrafo de introducion sobre el tema.",
                                "Incluye una idea principal que presente el tema.", "Agrega al menos dos ideas."]
    add("wording-L2", "wording", L2, tu_l2, ("language", "clarity"),
        "instructions in tú, missing accents and misspelling, one instruction repeated")

    def tu_l1(r, _):
        r["instructions_es"] = ["Lee el texto.", "Lee el texto con mucha atencion.", "Corrige los errores que encuentres.",
                                "Escribe el texto corregido."]
    add("wording-L1", "wording", L1_PUNCT, tu_l1, ("natural_text", "language", "clarity"),
        "instructions in tú, repeated, and no longer name the kind of error")

    def comma(r, ref):
        r["source_text_es"] = r["source_text_es"].replace("Al final del ciclo, la escuela", "Al final del ciclo la escuela")
        ref["corrections"].append({"error": "Al final del ciclo la escuela", "correction": "Al final del ciclo, la escuela",
                                   "criterion": "EE17"})
        ref["ambiguities_es"] = []
    add("ambiguous-L1-comma", "ambiguous", L1_PUNCT, comma, ("unambiguous", "errors_genuine", "alignment"),
        "optional comma after a short introductory phrase taught as the only fix, under EE17 (enumeration commas)")

    def solo(r, ref):
        text = r["source_text_es"]
        sentence = "Los manglares solo crecen en lugares con agua salada."
        r["source_text_es"] = text + " " + sentence
        ref["corrected_text_es"] = ref["corrected_text_es"] + " " + sentence.replace("solo", "sólo")
        ref["corrections"].append({"error": "solo crecen", "correction": "sólo crecen", "criterion": "EE15"})
        ref["ambiguities_es"] = []
    add("ambiguous-L1-solo", "ambiguous", L1_SPELL, solo, ("errors_genuine", "unambiguous", "reference_correct"),
        "«solo» without accent is correct (RAE 2010); the exercise marks it as an error with one fix")

    def outro_ideas(r, _):
        r["suggested_ideas_es"] = ["Acciones que la escuela puede tomar para mejorar la puntualidad",
                                   "Soluciones para que las familias lleguen a tiempo", "Consecuencias de llegar tarde a clases"]
    add("mismatch-L2", "mismatch", L2, outro_ideas, ("paragraph_scope", "alignment"),
        "introduction exercise suggests conclusion and development ideas")

    def plan_order(r, _):
        r["scaffolding_es"] = list(reversed(r["scaffolding_es"]))
    add("mismatch-L4", "mismatch", L4, plan_order, ("paragraph_scope", "alignment", "clarity"),
        "four-paragraph plan in reverse order: solutions first, introduction last")

    def bare_l3(r, _):
        r["instructions_es"] = ["Escribí sobre el tema."]
        r["deliverable"]["description_es"] = "Un texto."
        r["suggested_ideas_es"] = []
    add("incomplete-L3", "incomplete", L3, bare_l3, ("completeness", "clarity", "alignment"),
        "no paragraph type, no ideas, deliverable says only «Un texto.»")

    def bare_l4(r, _):
        r["instructions_es"] = ["Escribí un texto expositivo."]
        r["deliverable"]["description_es"] = "Un texto expositivo."
    add("incomplete-L4", "incomplete", L4, bare_l4, ("completeness", "clarity", "alignment"),
        "number of paragraphs, length and structure removed from instructions and deliverable")
    return cases


# ---------------------------------------------------------------- run

def review_case(client, usage, catalog, gate, model: str, case: dict[str, Any], baseline: str) -> dict[str, Any]:
    record = case["record"]
    level = contracts.level(record["level"])
    g = generation.build_grounding(catalog, baseline, f"L{level['ordinal']}", record["difficulty"],
                                   record["target_criteria"], exercise_type=record["exercise_type"])
    messages, parse, _, max_tokens = revalidation._review(g, record, case["reference"])
    result = route(client, usage, messages, purpose="evaluation", max_tokens=max_tokens,
                   request_id=f"wbench-{uuid.uuid4().hex[:12]}", gate=gate, models=(model,))
    sent = [r for r in result.records if r["status"] != "budget_blocked"]
    out = {"case_id": case["case_id"], "category": case["category"], "status": result.status,
           "attempts": len(sent), "http_errors": sum(1 for r in sent if (r["error_kind"] or "").startswith("http_")),
           "other_errors": [r["error_kind"] for r in sent if r["status"] != "ok"],
           "truncated": any(r["error_kind"] == "truncated" for r in sent),
           "latency_ms": result.final.latency_ms if result.final and result.status == "ok" else None,
           "tokens_in": sum(r["tokens_in"] or 0 for r in sent), "tokens_out": sum(r["tokens_out"] or 0 for r in sent),
           "cost_usd": round(sum(r["cost_usd"] or 0 for r in sent), 8),
           "cost_complete": all(r["cost_usd"] is not None for r in sent if r["status"] == "ok"),
           "model_used": result.final.model_used if result.final else None,
           "structured": False, "scores": None, "low": None, "notes": None}
    if result.status == "ok":
        try:
            review = parse(result.content or "")
        except OutputError as exc:
            out["parse_error"] = str(exc)[:200]
        else:
            low = {k: v for k, v in review.items() if k != "notes" and v < 2}
            out.update(structured=True, scores={k: v for k, v in review.items() if k != "notes"}, low=low,
                       notes=review["notes"][:300])
    out["flagged"] = bool(out["low"])
    out["expected_key_hit"] = bool(out["low"] and set(out["low"]) & set(case["expect"]))
    return out


def summarize(model: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    attempts = sum(r["attempts"] for r in rows)
    answered = [r for r in rows if r["structured"]]
    valid = [r for r in rows if r["category"] == "valid"]
    defects = [r for r in rows if r["category"] != "valid"]
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    categories = sorted({r["category"] for r in defects})
    m = {
        "model": model, "cases": n,
        "structured_rate": round(len(answered) / n, 3),
        "truncation_rate": round(sum(r["truncated"] for r in rows) / n, 3),
        "http_error_rate": round(sum(r["http_errors"] for r in rows) / attempts, 3) if attempts else None,
        "valid_passed": sum(1 for r in valid if r["structured"] and not r["flagged"]), "valid_total": len(valid),
        "defects_flagged": sum(1 for r in defects if r["flagged"]), "defects_total": len(defects),
        "defects_expected_key": sum(1 for r in defects if r["expected_key_hit"]),
        "categories_detected": {c: sum(1 for r in defects if r["category"] == c and r["flagged"]) for c in categories},
        "latency_ms_median": int(statistics.median(latencies)) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
        "attempts": attempts, "tokens_in": sum(r["tokens_in"] for r in rows),
        "tokens_out": sum(r["tokens_out"] for r in rows),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 8),
        "cost_complete": all(r["cost_complete"] for r in rows),
        "models_used": sorted({r["model_used"] for r in rows if r["model_used"]}),
    }
    failures = []
    if m["structured_rate"] < CRITERIA["structured_rate_min"]:
        failures.append(f"structured rate {m['structured_rate']} < {CRITERIA['structured_rate_min']:.3f}")
    if m["truncation_rate"] > CRITERIA["truncation_rate_max"]:
        failures.append(f"truncation rate {m['truncation_rate']} > {CRITERIA['truncation_rate_max']}")
    if m["http_error_rate"] is None or m["http_error_rate"] > CRITERIA["http_error_rate_max"]:
        failures.append(f"HTTP error rate {m['http_error_rate']} > {CRITERIA['http_error_rate_max']}")
    if m["defects_flagged"] < CRITERIA["defects_flagged_min"]:
        failures.append(f"defects flagged {m['defects_flagged']}/{m['defects_total']} < {CRITERIA['defects_flagged_min']}")
    if any(v == 0 for v in m["categories_detected"].values()):
        failures.append("a defect category was never detected: "
                        + ", ".join(c for c, v in m["categories_detected"].items() if v == 0))
    if m["valid_passed"] < CRITERIA["valid_passed_min"]:
        failures.append(f"valid exercises passed {m['valid_passed']}/{m['valid_total']} < {CRITERIA['valid_passed_min']}")
    m["qualified"], m["failures"] = not failures, failures
    return m


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true", help="list the selection only; no chat calls")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--models", help="comma-separated override of the discovered candidates")
    parser.add_argument("--primary", action="store_true", help="also benchmark the primary reviewer as reference")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    settings = LlmSettings.load()
    url = db.database_url()
    with OpenRouterClient(settings) as client:
        selection = select_candidates(client, settings)
        if args.discover:
            print(json.dumps(selection, ensure_ascii=False, indent=2))
            return 0
        if args.out is None:
            parser.error("--out is required unless --discover is given")
        models = [m.strip() for m in args.models.split(",")] if args.models else selection["candidates"]
        if args.primary and selection["primary"]:
            models = [selection["primary"]] + [m for m in models if m != selection["primary"]]
        refused = [m for m in models if any(same_model(m, g) for g in selection["generators"])]
        if refused:
            parser.error(f"a generator cannot be benchmarked as an independent reviewer: {refused}")
        store = WritingStore(url)
        cases = build_cases(store)
        usage = UsageStore(url)
        gate = BudgetGate(usage, settings, max_calls=MAX_CALLS)
        before = usage.today()
        with open_catalog(url) as catalog:
            def run_model(model: str) -> list[dict[str, Any]]:
                rows = []
                for case in cases:
                    rows.append(review_case(client, usage, catalog, gate, model, case, "PNE2026-SUM-v1.0"))
                    r = rows[-1]
                    print(f"  {model} {case['case_id']}: {r['status']} structured={r['structured']} "
                          f"low={r['low']} attempts={r['attempts']} {r['latency_ms']}ms", flush=True)
                return rows
            with ThreadPoolExecutor(max_workers=len(models)) as pool:
                results = dict(zip(models, pool.map(run_model, models)))
    report = {"version": VERSION, "criteria": CRITERIA, "selection": selection, "models": models,
              "cases": [{k: c[k] for k in ("case_id", "category", "exercise_id", "expect", "note")} for c in cases],
              "summary": [summarize(m, results[m]) for m in models], "results": results,
              "requests_today_before": before["requests"], "gate_calls": gate.sent, "gate_refusal": gate.refusal}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    for s in report["summary"]:
        print(json.dumps({k: s[k] for k in ("model", "qualified", "structured_rate", "truncation_rate",
                                             "http_error_rate", "valid_passed", "defects_flagged",
                                             "categories_detected", "latency_ms_median", "attempts", "tokens_in",
                                             "tokens_out", "cost_usd", "failures")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
