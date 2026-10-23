"""Deterministic item checker for all four PNE subjects.

Runs structural, grounding and subject-specific checks on QuestionItem JSON
(.ace/schemas/question-engine/question-item.schema.json) and returns a
ValidationResult-shaped dict. No network, no LLM, no randomness.

Only Matemáticas keys can be *proven* (exact arithmetic). For Español,
Ciencias and Estudios Sociales the checker proves structure and grounding;
an independent solve is still required (requires_independent_solve = true).

Usage:
    python item_checker.py ITEMS.json --records RECORDS.json [--bank BANK.json] [--facts FACTS.json]

Exit code: 0 if every item passes, 1 otherwise, 2 on usage/input errors.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cr_math import AmbiguousNumberError, evaluate, parse_quantity  # noqa: E402

CHECKER_VERSION = "1.4.0"  # 1.4.0: C09 material key-length cue fails
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "question-engine" / "question-item.schema.json"

SUBJECT_CODES = {"espanol": "ESP", "matematicas": "MAT", "ciencias": "CIE", "estudios_sociales": "EST"}
BANNED_OPTIONS = (
    "todas las anteriores", "ninguna de las anteriores", "todas las opciones",
    "ninguna de las opciones", "ambas son correctas", "a y b", "b y c", "a y c",
)
STIMULUS_CUES = ("observe", "observá", "la imagen", "la figura", "el gráfico", "la tabla", "el mapa", "el texto", "la lectura", "el fragmento")
MAX_STEM_WORDS = 120
# C09: a key is a material length cue only when it is the strictly longest option, at least
# KEY_CUE_RATIO x the longest distractor AND KEY_CUE_MIN_GAP characters longer. The gap keeps
# short options (numbers, single words) from failing on small absolute differences.
KEY_CUE_RATIO = 1.5
KEY_CUE_MIN_GAP = 12
MAX_OPTION_WORDS = 30
MIN_PASSAGE_WORDS = 40
NEAR_DUPLICATE_THRESHOLD = 0.85
OPTION_SIMILARITY_THRESHOLD = 0.9
# Grounding failures cannot be fixed by regenerating the same slot.
GROUNDING_CHECKS = {"G01", "G02"}
RE_OPERATOR = re.compile(r"[-+*/×÷]")
RE_EXPR_NUMBER = re.compile(r"\d+(?:,\d+)?")
RE_TEXT_NUMBER = re.compile(r"\d{1,3}(?: \d{3})+(?:,\d+)?|\d+(?:,\d+)?")
# Constants an expression may use without them appearing in the item text.
ALLOWED_CONSTANTS = {Fraction(n) for n in (*range(2, 11), 100, 1000)}

Check = dict[str, str]


# --------------------------------------------------------------------------- helpers

def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s/,]", " ", text)
    return " ".join(text.split())


def squash(text: str) -> str:
    """Collapse whitespace only; used for verbatim comparisons."""
    return " ".join(text.split())


def shingles(text: str, size: int = 3) -> set[str]:
    words = normalize(text).split()
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def item_fingerprint(item: dict[str, Any]) -> set[str]:
    stim = item.get("stimulus", {}).get("text", "")
    return shingles(f"{stim} {item.get('stem', '')}")


def _check(check_id: str, status: str, message: str) -> Check:
    return {"id": check_id, "status": status, "message": message}


# --------------------------------------------------------------------------- common checks

def check_schema(item: dict[str, Any], validator: Any) -> list[Check]:
    if validator is None:
        return [_check("C01", "warn", "jsonschema not installed; schema not validated")]
    errors = sorted(validator.iter_errors(item), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        return [_check("C01", "fail", f"schema: {where}: {first.message} ({len(errors)} error(s))")]
    return [_check("C01", "pass", "schema valid")]


def check_options_and_key(item: dict[str, Any], option_count: int | None) -> list[Check]:
    checks: list[Check] = []
    options = item.get("options", [])
    labels = [o.get("label") for o in options]
    expected = [chr(ord("A") + i) for i in range(len(options))]
    if labels != expected:
        checks.append(_check("C02", "fail", f"labels must be {expected}, got {labels}"))
    elif option_count is not None and len(options) != option_count:
        checks.append(_check("C02", "fail", f"expected {option_count} options, got {len(options)}"))
    else:
        checks.append(_check("C02", "pass", f"{len(options)} options labelled in order"))

    key = item.get("answer_key")
    if labels.count(key) == 1:
        checks.append(_check("C03", "pass", f"answer_key {key} references exactly one option"))
    else:
        checks.append(_check("C03", "fail", f"answer_key {key!r} does not reference exactly one option"))

    norm = [normalize(o.get("text", "")) for o in options]
    dupes = {t for t in norm if norm.count(t) > 1}
    similar = [
        (labels[i], labels[j])
        for i in range(len(norm)) for j in range(i + 1, len(norm))
        if norm[i] != norm[j] and jaccard(set(norm[i].split()), set(norm[j].split())) >= OPTION_SIMILARITY_THRESHOLD
    ]
    if dupes:
        checks.append(_check("C04", "fail", "duplicate option texts"))
    elif similar:
        checks.append(_check("C04", "fail", f"near-identical options: {similar}"))
    else:
        checks.append(_check("C04", "pass", "options are distinct"))

    banned = [o["label"] for o in options
              if any(normalize(o.get("text", "")).startswith(b) for b in BANNED_OPTIONS)]
    checks.append(_check("C05", "fail", f"banned option wording in {banned}") if banned
                  else _check("C05", "pass", "no banned option wording"))

    rationales = item.get("distractor_rationales", {})
    missing = [lbl for lbl in labels if lbl != key and lbl not in rationales]
    extra = [lbl for lbl in rationales if lbl == key or lbl not in labels]
    if missing or extra:
        checks.append(_check("C06", "fail", f"distractor rationales missing {missing} / invalid {extra}"))
    else:
        checks.append(_check("C06", "pass", "every distractor has a rationale"))
    return checks


def check_lengths_and_stimulus(item: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    stem_words = len(item.get("stem", "").split())
    long_options = [o["label"] for o in item.get("options", []) if len(o.get("text", "").split()) > MAX_OPTION_WORDS]
    if stem_words > MAX_STEM_WORDS or long_options:
        checks.append(_check("C07", "fail", f"stem {stem_words} words (max {MAX_STEM_WORDS}); long options {long_options}"))
    else:
        checks.append(_check("C07", "pass", "lengths within limits"))

    stimulus = item.get("stimulus", {})
    stype = stimulus.get("type", "none")
    stem = normalize(item.get("stem", ""))
    cued = [c for c in STIMULUS_CUES if normalize(c) in stem]
    if stype == "image" and not stimulus.get("assets"):
        checks.append(_check("C08", "fail", "image stimulus without assets"))
    elif stype in ("text", "table") and not stimulus.get("text", "").strip():
        checks.append(_check("C08", "fail", f"{stype} stimulus without text"))
    elif stype == "none" and cued:
        checks.append(_check("C08", "fail", f"stem refers to a stimulus ({cued}) but none is provided"))
    else:
        checks.append(_check("C08", "pass", "stimulus consistent with stem"))

    key = item.get("answer_key")
    texts = {o["label"]: o.get("text", "") for o in item.get("options", []) if "label" in o}
    if key in texts and len(texts) > 1:
        key_len = len(texts[key].strip())
        longest = max(len(t.strip()) for lbl, t in texts.items() if lbl != key)
        if key_len >= KEY_CUE_RATIO * longest and key_len - longest >= KEY_CUE_MIN_GAP:
            checks.append(_check("C09", "fail", f"key is a length cue: {key_len} chars vs longest distractor "
                                                f"{longest} (limit {KEY_CUE_RATIO}x and +{KEY_CUE_MIN_GAP})"))
        else:
            checks.append(_check("C09", "pass", "no length cue on the key"))
    return checks


def grounding_basis(record: dict[str, Any]) -> str | None:
    """Return "official", "approved_baseline" or None (not groundable). See ADR-006."""
    if record.get("assessment_type", "multiple_choice") != "multiple_choice":
        return None
    if record.get("provenance") == "official":
        return "official"
    if record.get("baseline_status") == "approved":
        return "approved_baseline"
    return None


def check_grounding(item: dict[str, Any], records: dict[str, dict[str, Any]]) -> list[Check]:
    checks: list[Check] = []
    ref = item.get("curriculum_ref", {})
    evid_id = ref.get("evidencia_id", "")
    evid = records.get(evid_id)
    code = SUBJECT_CODES.get(item.get("subject", ""), "?")

    problems = []
    if evid is None:
        problems.append(f"evidencia {evid_id!r} not in records")
    else:
        if evid.get("record_type") != "evidencia":
            problems.append(f"{evid_id} is not an evidencia")
        if evid.get("parent_id") != ref.get("afirmacion_id"):
            problems.append("evidencia does not belong to the cited afirmación")
        afirm = records.get(ref.get("afirmacion_id", ""))
        if afirm is None or afirm.get("parent_id") != ref.get("bloque_id"):
            problems.append("afirmación does not belong to the cited bloque")
        if evid.get("subject") != item.get("subject") or f"-{code}-" not in evid_id:
            problems.append("subject mismatch")
        if evid.get("application") != ref.get("application") or evid.get("spec_version") != ref.get("spec_version"):
            problems.append("application/spec_version mismatch")
        basis = grounding_basis(evid)
        if basis is None:
            problems.append("evidencia is neither official nor in an approved baseline")
        elif item.get("grounding_basis") not in (None, basis):
            problems.append(f"item grounding_basis {item.get('grounding_basis')!r} != record basis {basis!r}")
        if evid.get("review", {}).get("status") == "rejected":
            problems.append("evidencia record was rejected in review")
    if not item.get("item_id", "").startswith(f"Q-{evid_id}-"):
        problems.append("item_id does not embed the evidencia_id")
    checks.append(_check("G01", "fail", "; ".join(problems)) if problems
                  else _check("G01", "pass", f"curriculum chain is consistent (basis: {grounding_basis(evid)})"))

    bad_refs = []
    for src in item.get("source_refs", []):
        rec = records.get(src.get("record_id", ""))
        if rec is None or grounding_basis(rec) is None:
            bad_refs.append(f"{src.get('record_id')}: unknown, or neither official nor approved baseline")
        elif squash(src.get("excerpt", "")) not in squash(rec.get("text_es", "")):
            bad_refs.append(f"{src.get('record_id')}: excerpt not verbatim")
    checks.append(_check("G02", "fail", "; ".join(bad_refs)) if bad_refs
                  else _check("G02", "pass", "every excerpt is verbatim text of a groundable record"))

    verb = item.get("cognitive_verb", "")
    if evid is not None and verb and normalize(verb) not in normalize(evid.get("text_es", "")):
        checks.append(_check("G03", "warn", f"cognitive_verb {verb!r} not found in evidencia text"))
    elif evid is not None:
        checks.append(_check("G03", "pass", "cognitive_verb appears in evidencia"))
    return checks


def check_duplicates(item: dict[str, Any], bank: list[dict[str, Any]]) -> list[Check]:
    if not bank:
        return [_check("D01", "skip", "no bank supplied")]
    fp = item_fingerprint(item)
    stem_norm = normalize(item.get("stem", ""))
    for other in bank:
        if other.get("item_id") == item.get("item_id"):
            continue
        if normalize(other.get("stem", "")) == stem_norm and normalize(other.get("stimulus", {}).get("text", "")) == normalize(item.get("stimulus", {}).get("text", "")):
            return [_check("D01", "fail", f"exact duplicate of {other.get('item_id')}")]
        score = jaccard(fp, item_fingerprint(other))
        if score >= NEAR_DUPLICATE_THRESHOLD:
            return [_check("D01", "fail", f"near-duplicate of {other.get('item_id')} (similarity {score:.2f})")]
    return [_check("D01", "pass", f"no duplicate among {len(bank)} bank items")]


# --------------------------------------------------------------------------- subject checks

def check_math(item: dict[str, Any]) -> tuple[list[Check], bool]:
    spec = item.get("subject_checks", {}).get("math")
    if not spec or not (spec.get("expression") or spec.get("select")):
        return [_check("M01", "fail", "matemáticas item without subject_checks.math expression or select")], False
    if spec.get("expression") and spec.get("select"):
        return [_check("M01", "fail", "use either expression or select, not both")], False
    if spec.get("expression") and not RE_OPERATOR.search(spec["expression"].strip()[1:]):
        # A bare number restates the claimed key instead of computing it.
        return [_check("M01", "fail", "expression must compute the answer, not restate a number")], False
    unit = spec.get("unit", "")

    values: dict[str, Fraction] = {}
    for opt in item.get("options", []):
        try:
            value, opt_unit = parse_quantity(opt.get("text", ""))
        except AmbiguousNumberError as exc:
            return [_check("M02", "fail", f"option {opt.get('label')}: {exc}")], False
        except ValueError:
            return [_check("M02", "fail", f"option {opt.get('label')} is not a number with optional unit")], False
        if opt_unit != unit:
            return [_check("M02", "fail", f"option {opt.get('label')} unit {opt_unit!r} != expected {unit!r}")], False
        values[opt["label"]] = value
    if spec.get("select"):
        if spec["select"] not in ("min", "max") or not values:
            return [_check("M01", "fail", f"select must be 'min' or 'max', got {spec['select']!r}")], False
        # The checker, not the model, decides which option is smallest or largest.
        expected = min(values.values()) if spec["select"] == "min" else max(values.values())
    else:
        try:
            expected = evaluate(spec["expression"])
        except (ValueError, ZeroDivisionError) as exc:
            return [_check("M01", "fail", f"expression not evaluable: {exc}")], False
    distinct = len(set(values.values())) == len(values)
    matches = [lbl for lbl, v in values.items() if v == expected]
    grounded_proof = True
    if spec.get("expression"):
        text = f"{item.get('stimulus', {}).get('text', '')} {item.get('stem', '')}"
        text_values = set()
        for token in RE_TEXT_NUMBER.findall(text):
            try:
                text_values.add(parse_quantity(token)[0])
            except ValueError:
                pass
        operands = [Fraction(t.replace(",", ".")) for t in RE_EXPR_NUMBER.findall(spec["expression"])]
        foreign = [o for o in operands if o not in text_values and o not in ALLOWED_CONSTANTS]
        grounded_proof = bool(operands) and not foreign and any(o in text_values for o in operands)
    checks = [_check("M02", "pass" if distinct else "fail",
                     "option values are distinct" if distinct else "two options have the same value")]
    if matches == [item.get("answer_key")] and distinct:
        checks.append(_check("M03", "pass", f"expected value {expected}; only the key matches"))
        if not grounded_proof:
            # e.g. "148/100" restates the key: consistent, but not a proof; require an independent solve.
            checks.append(_check("M04", "warn", "expression operands not taken from the item text; key not proven"))
            return checks, False
        checks.append(_check("M04", "pass", "expression operands come from the item text"))
        return checks, True
    checks.append(_check("M03", "fail", f"expression = {expected}; matching options {matches}, key {item.get('answer_key')}"))
    return checks, False


def check_reading(item: dict[str, Any]) -> list[Check]:
    stimulus = item.get("stimulus", {})
    passage = squash(stimulus.get("text", ""))
    if stimulus.get("type") != "text" or len(passage.split()) < MIN_PASSAGE_WORDS:
        return [_check("R01", "fail", f"español item needs a text stimulus of at least {MIN_PASSAGE_WORDS} words")]
    checks = [_check("R01", "pass", f"passage has {len(passage.split())} words")]
    reading = item.get("subject_checks", {}).get("reading", {})
    missing = [s for s in reading.get("quoted_spans", []) if squash(s) not in passage]
    checks.append(_check("R02", "fail", f"quoted spans not in passage: {missing}") if missing
                  else _check("R02", "pass", "quoted spans appear verbatim"))
    support = reading.get("key_support_span")
    if not support:
        checks.append(_check("R03", "fail", "key_support_span is required for español items"))
    elif squash(support) not in passage:
        checks.append(_check("R03", "fail", "key_support_span not found verbatim in passage"))
    else:
        checks.append(_check("R03", "pass", "key is supported by a verbatim passage span"))
    return checks


def check_facts(item: dict[str, Any], records: dict[str, dict[str, Any]], facts: list[str]) -> list[Check]:
    terms = item.get("subject_checks", {}).get("facts", {}).get("support_terms", [])
    if not terms:
        return [_check("F01", "fail", "support_terms required for ciencias/estudios sociales items")]
    key_text = next((normalize(o.get("text", "")) for o in item.get("options", []) if o.get("label") == item.get("answer_key")), "")
    corpus = " ".join(
        [normalize(records.get(s.get("record_id", ""), {}).get("text_es", "")) for s in item.get("source_refs", [])]
        + [normalize(item.get("stimulus", {}).get("text", ""))]
        + [normalize(f) for f in facts]
    )
    unsupported = [t for t in terms if normalize(t) not in corpus]
    not_in_key = [t for t in terms if normalize(t) not in key_text and normalize(t) not in normalize(item.get("explanation", ""))]
    checks = [_check("F01", "fail", f"support terms not in sources/stimulus/facts: {unsupported}") if unsupported
              else _check("F01", "pass", "support terms are grounded")]
    checks.append(_check("F02", "fail", f"support terms absent from key and explanation: {not_in_key}") if not_in_key
                  else _check("F02", "pass", "key/explanation use the grounded terms"))
    return checks


# --------------------------------------------------------------------------- orchestration

def check_item(item: dict[str, Any], records: dict[str, dict[str, Any]], bank: list[dict[str, Any]] | None = None,
               facts: list[str] | None = None, option_count: int | None = None, validator: Any = None) -> dict[str, Any]:
    """Run every applicable deterministic check and return a ValidationResult dict."""
    checks: list[Check] = []
    checks += check_schema(item, validator)
    checks += check_options_and_key(item, option_count)
    checks += check_lengths_and_stimulus(item)
    checks += check_grounding(item, records)
    checks += check_duplicates(item, bank or [])

    subject = item.get("subject")
    math_proven = False
    if subject == "matematicas":
        math_checks, math_proven = check_math(item)
        checks += math_checks
    elif subject == "espanol":
        checks += check_reading(item)
    elif subject in ("ciencias", "estudios_sociales"):
        checks += check_facts(item, records, facts or [])
    else:
        checks.append(_check("S01", "fail", f"unknown subject {subject!r}"))

    failed_ids = {c["id"] for c in checks if c["status"] == "fail"}
    failed = bool(failed_ids)
    reasons = [f"{c['id']}: {c['message']}" for c in checks if c["status"] == "fail"]
    if not failed:
        # Final verdict is set by question-quality-review after the independent solve.
        verdict = "pending"
    elif failed_ids & GROUNDING_CHECKS:
        verdict = "reject"
    else:
        verdict = "regenerate"
    return {
        "schema_version": "1.0",
        "item_id": item.get("item_id", ""),
        "checker_version": CHECKER_VERSION,
        "deterministic_status": "fail" if failed else "pass",
        "checks": checks,
        "math_proven": math_proven,
        "requires_independent_solve": not math_proven,
        "verdict": verdict,
        "reasons": reasons,
    }


def load_validator() -> Any:
    try:
        import jsonschema
    except ImportError:
        return None
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def _load_json_list(path: str | None) -> list[Any]:
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("items", help="JSON file with one item or a list of items")
    parser.add_argument("--records", required=True, help="JSON list of curriculum records")
    parser.add_argument("--bank", help="JSON list of existing bank items for duplicate detection")
    parser.add_argument("--facts", help="JSON list of reviewed fact strings (ciencias / estudios sociales)")
    parser.add_argument("--option-count", type=int, choices=[3, 4, 5], help="required number of options")
    args = parser.parse_args(argv)

    try:
        items = _load_json_list(args.items)
        records = {r["record_id"]: r for r in _load_json_list(args.records)}
        bank = _load_json_list(args.bank)
        facts = [str(f) for f in _load_json_list(args.facts)]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2

    validator = load_validator()
    results = []
    for index, item in enumerate(items):
        # Earlier items in the same batch count as bank entries (sibling duplicates).
        results.append(check_item(item, records, bank + items[:index], facts, args.option_count, validator))
    json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if all(r["deterministic_status"] == "pass" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
