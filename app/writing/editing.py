"""Nivel 1 text-correction exercises (`conventions_editing`) with OpenRouter (T023, ADR-022).

The model writes a short original text with deliberate errors, the list of exact corrections and the
corrected reference text. Code splits the result: the exercise record (what the student may see) and a
tutor-only reference correction stored in writing.reference_correction, never in the exercise record.
Checks W01-W07 (shared with ADR-020) plus W09-W12 below, then the independent review W08.

| Check | Rule |
|-------|------|
| W09 | 40-120 words, 3-8 sentences, 3-8 corrections; each error occurs once, differs from its fix and targets one of the exercise criteria; every target criterion has an error |
| W10 | Applying the corrections to the text gives exactly the reference text (nothing else changes) |
| W11 | Each fix is the kind of change its criterion covers (for example only b/v for EE09, only accents for EE15) |
| W12 | The text is not a near duplicate of a stored Nivel 1 text (word overlap below 0.5) |
| W13 | Instructions use Costa Rican voseo, not tú (for example «No cambiés», not «No cambies») (T024) |
| W14 | No repetitive wording: no content word twice in one sentence of the text, no repeated sentence, no two instructions that say nearly the same (T024) |
| W15 | A correction that adds «¿» or «¡» needs a colon or sentence start before it, or a documented alternative (T024) |
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from app.generation.parsing import OutputError, extract_json
from app.llm.budget import BudgetGate
from app.llm.client import OpenRouterClient
from app.llm.router import Store, route
from app.writing import generation as gen

PROMPT_VERSION = "writing-edit-1.1"  # 1.1 (T024): voseo, repetition, ambiguity, meaning
# Correction exercises make reasoning models count words and errors; 4000 output tokens truncated the first
# live request (T023). Own limit, like SOLVE/RUBRIC_MAX_TOKENS; daily request and USD budgets are unchanged.
EDIT_MAX_TOKENS = 8000
# T029 (RCA-004): the review checks the text, the reference and every correction; at RUBRIC_MAX_TOKENS (3000) the
# only independent reviewer truncated 4 of 6 L1 reviews, so the generator reviewed instead. Same budgets.
EDIT_REVIEW_MAX_TOKENS = 6000
# Inventory plan for Nivel 1 (T023): one exercise per group of convention criteria (ADR-019 mapping).
CATEGORIES = {
    "capitalization_punctuation": {"criteria": ["EE16", "EE17", "EE18"],
                                   "focus_es": "mayúsculas, punto y seguido, punto y aparte, comas en enumeraciones "
                                               "y signos de interrogación y exclamación"},
    "spelling": {"criteria": ["EE09", "EE11", "EE15"],
                 "focus_es": "uso de b y v, uso de la h y tildes"},
    "agreement": {"criteria": ["EE07", "EE08"],
                  "focus_es": "concordancia entre artículo, sustantivo y adjetivo, y entre sujeto y verbo"},
}
EDIT_FIELDS = ("title_es", "topic_es", "communicative_situation_es", "instructions_es",
               "deliverable_description_es", "source_text_es", "reference_text_es", "corrections")
EDIT_REVIEW_KEYS = gen.REVIEW_KEYS + ("errors_genuine", "reference_correct", "unambiguous", "meaning_preserved",
                                      "natural_text")
SYSTEM = ("Usted diseña ejercicios de corrección de textos para estudiantes de sexto grado de primaria en Costa "
          "Rica, según la rúbrica MEP 2026 de producción escrita. Escribe en español de Costa Rica, claro para "
          "niñas y niños de 11 a 12 años. Responde solo con un objeto JSON.")
REVIEW_SYSTEM = ("Usted revisa ejercicios de corrección de textos para sexto grado de primaria en Costa Rica. Verifica "
                 "que cada error sea un error real, que la corrección sea la única correcta y que el ejercicio sea "
                 "claro. Responde solo con un objeto JSON.")


@dataclass
class EditAttempt(gen.Attempt):
    reference: dict[str, Any] | None = None


# ---------------------------------------------------------------- prompts

def generation_messages(g: gen.Grounding, focus_es: str, avoid_topics: list[str]) -> list[dict[str, str]]:
    criteria = "\n".join(f"- {c['code']}: {c['statement_es']}\n  Contenidos: {c['concepts_es']}" for c in g.criteria)
    avoid = "; ".join(list(gen.MODEL_TOPICS) + avoid_topics)
    words = {"easy": "50 a 70", "medium": "70 a 95", "hard": "90 a 115"}[g.difficulty]
    user = f"""Cree UN ejercicio original de corrección de un texto expositivo breve (Nivel 1, Convenciones de
escritura; dificultad {gen.DIFFICULTY_ES[g.difficulty]}). Enfoque: {focus_es}.

Criterios de la rúbrica que se evaluarán en el texto corregido (no los cite en el ejercicio):
{criteria}

Instrucciones para crear el ejercicio:
- Escriba un texto expositivo original de {words} palabras, de 4 a 7 oraciones, sobre un tema cercano a
  estudiantes de sexto grado en Costa Rica, distinto de: {avoid}.
- Inserte de 4 a 7 errores intencionales, reales e inequívocos, propios de sexto grado. Cada error corresponde a
  uno de los criterios indicados y cada criterio debe tener al menos un error. No incluya otros errores.
- Cada error debe aparecer una sola vez en el texto. En "corrections", "error" es el fragmento exacto con el error
  (una o pocas palabras, copiado tal cual del texto) y "correction" es ese mismo fragmento corregido.
- "reference_text_es" es el mismo texto con esas correcciones aplicadas, sin ningún otro cambio.
- Oraciones naturales y expositivas: no repita palabras dentro de una oración ni use frases poéticas o vacías.
- Si un error es una pregunta sin signos, escríbala como pregunta directa precedida de dos puntos (por ejemplo
  «preguntan: cuál es…?»), para que tenga una sola corrección. Si un error admite otra corrección válida,
  explíquela en "ambiguities_es".
- Las correcciones no cambian el sentido del texto.
- Instrucciones (3 a 5), cortas y sin repetir ideas, en voseo costarricense también en negativo («Leé»,
  «Corregí», «Escribí», «No cambiés», «No agregués»; nunca «cambies», «agregues», «Lee», «Corrige»): que lea el
  texto, qué tipo de errores debe corregir (sin decir dónde están ni cuántos son), que corrija el texto completo y
  que no cambie las ideas.
- Situación comunicativa breve: quién escribió el texto y para qué (por ejemplo, el boletín del grado).
- No mencione códigos de criterios, puntos, rúbricas ni calificación.

Responda solo con este JSON:
{{"title_es": "...", "topic_es": "...", "communicative_situation_es": "...", "instructions_es": ["..."],
  "deliverable_description_es": "...", "source_text_es": "...", "reference_text_es": "...",
  "corrections": [{{"error": "...", "correction": "...", "criterion": "EE.."}}], "ambiguities_es": []}}"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def review_messages(g: gen.Grounding, exercise: dict[str, Any], reference: dict[str, Any]) -> list[dict[str, str]]:
    criteria = "\n".join(f"- {c['code']}: {c['statement_es']}" for c in g.criteria)
    payload = {"title_es": exercise["title_es"], "instructions_es": exercise["instructions_es"],
               "texto_con_errores": exercise["source_text_es"], "texto_corregido": reference["corrected_text_es"],
               "correcciones": reference["corrections"], "ambiguedades": reference["ambiguities_es"]}
    user = f"""Ejercicio de corrección para sexto grado (Nivel 1, Convenciones de escritura):
{json.dumps(payload, ensure_ascii=False, indent=1)}

Criterios que el ejercicio debe permitir evaluar:
{criteria}

Califique de 0 a 2 (2 = cumple por completo):
- clarity: instrucciones claras.
- age_appropriate: tema, vocabulario y extensión adecuados para 11-12 años.
- completeness: la persona estudiante tiene todo lo necesario para corregir el texto.
- alignment: los errores corresponden a los criterios indicados.
- language: el texto corregido es español correcto de Costa Rica.
- errors_genuine: cada error es realmente incorrecto según la normativa.
- reference_correct: el texto corregido resuelve todos los errores, no deja otros y conserva el sentido.
- unambiguous: cada error tiene una sola corrección válida, o la alternativa está documentada en ambigüedades.
- meaning_preserved: ninguna corrección cambia el sentido de la oración.
- natural_text: oraciones naturales y expositivas, sin repeticiones ni frases poéticas o vacías; instrucciones en
  voseo costarricense sin repetir ideas.
Responda solo con JSON: {{"clarity": 0, "age_appropriate": 0, "completeness": 0, "alignment": 0, "language": 0,
"errors_genuine": 0, "reference_correct": 0, "unambiguous": 0, "meaning_preserved": 0, "natural_text": 0,
"notes": "..."}}"""
    return [{"role": "system", "content": REVIEW_SYSTEM}, {"role": "user", "content": user}]


# ---------------------------------------------------------------- parsing and assembly

def _clean(text: str) -> str:
    return " ".join(text.split())


def model_fields(text: str) -> dict[str, Any]:
    """W01 for editing: required fields and types."""
    raw = extract_json(text, required=EDIT_FIELDS)
    fields: dict[str, Any] = {}
    for key in ("title_es", "topic_es", "communicative_situation_es", "deliverable_description_es",
                "source_text_es", "reference_text_es"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise OutputError(f"{key} must be a non-empty string")
        fields[key] = _clean(raw[key])
    if not isinstance(raw["instructions_es"], list) or not all(isinstance(x, str) and x.strip()
                                                                for x in raw["instructions_es"]):
        raise OutputError("instructions_es must be a list of non-empty strings")
    fields["instructions_es"] = [_clean(re.sub(r"^\s*(\d+[.)]|[-•])\s*", "", x)) for x in raw["instructions_es"]]
    corrections = raw["corrections"]
    if not isinstance(corrections, list) or not all(
            isinstance(c, dict) and all(isinstance(c.get(k), str) and c[k].strip() for k in
                                        ("error", "correction", "criterion")) for c in corrections):
        raise OutputError("corrections must be a list of {error, correction, criterion}")
    fields["corrections"] = [{"error": _clean(c["error"]), "correction": _clean(c["correction"]),
                              "criterion": c["criterion"].strip().upper()} for c in corrections]
    ambiguities = raw.get("ambiguities_es", [])
    fields["ambiguities_es"] = [_clean(a) for a in ambiguities if isinstance(a, str) and a.strip()] \
        if isinstance(ambiguities, list) else []
    return fields


def sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()])


def assemble(g: gen.Grounding, fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(student-visible exercise record, tutor-only reference correction)."""
    exercise = gen.assemble(g, {**fields, "suggested_ideas_es": []})
    exercise.pop("suggested_ideas_es")
    sentences = sentence_count(fields["source_text_es"])
    exercise["deliverable"].update(min=max(1, sentences), max=max(1, sentences))
    exercise["title_es"] = fields["title_es"]
    exercise["source_text_es"] = fields["source_text_es"]
    reference = {"exercise_id": exercise["exercise_id"], "corrected_text_es": fields["reference_text_es"],
                 "corrections": fields["corrections"], "ambiguities_es": fields["ambiguities_es"]}
    return exercise, reference


# ---------------------------------------------------------------- checks W09-W12

def _fold(text: str) -> str:
    """Lowercase without accents."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _same_except(error: str, fix: str, mapping: dict[str, str]) -> bool:
    def norm(t: str) -> str:
        return "".join(mapping.get(ch, ch) for ch in t.lower())
    return norm(error) == norm(fix)


def change_fits_criterion(criterion: str, error: str, fix: str) -> bool:
    """W11: the correction changes only what the criterion covers."""
    if error == fix:
        return False
    low_e, low_f = error.lower(), fix.lower()
    if criterion == "EE18":
        return low_e == low_f
    if criterion == "EE15":
        return _fold(error) == _fold(fix) and low_e != low_f
    if criterion == "EE09":
        return _same_except(error, fix, {"b": "B", "v": "B"}) and _fold(error) != _fold(fix)
    if criterion == "EE10":
        return _same_except(_fold(error), _fold(fix), {"s": "S", "c": "S", "z": "S"})
    if criterion == "EE11":
        return _fold(error).replace("h", "") == _fold(fix).replace("h", "")
    if criterion == "EE12":
        return _same_except(_fold(error), _fold(fix), {"g": "G", "j": "G"})
    if criterion == "EE13":
        return _fold(error).replace("rr", "r") == _fold(fix).replace("rr", "r")
    if criterion == "EE14":
        return _same_except(_fold(error), _fold(fix), {"m": "M", "n": "M"})
    if criterion == "EE16":
        # A full stop added, removed or replacing a comma (comma splice); words and their order unchanged.
        return re.sub(r"[.;,]", "", low_e).split() == re.sub(r"[.;,]", "", low_f).split() and "." in low_e + low_f
    if criterion == "EE17":
        return re.sub(r"[,¿?¡!]", "", low_e).split() == re.sub(r"[,¿?¡!]", "", low_f).split()
    if criterion in ("EE07", "EE08"):
        e_words, f_words = error.split(), fix.split()
        changed = [(a, b) for a, b in zip(e_words, f_words) if a != b]
        return len(e_words) == len(f_words) and 1 <= len(changed) <= (3 if criterion == "EE07" else 2)
    return False


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-záéíóúñü]+", text.lower()))


def editing_checks(g: gen.Grounding, exercise: dict[str, Any], reference: dict[str, Any],
                   stored_sources: list[str]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def check(check_id: str, ok: bool, message: str) -> None:
        checks.append({"id": check_id, "status": "pass" if ok else "fail", "message": "ok" if ok else message})

    source, corrected = exercise["source_text_es"], reference["corrected_text_es"]
    corrections = reference["corrections"]
    words, sentences = len(source.split()), sentence_count(source)
    problems = []
    if not 40 <= words <= 120:
        problems.append(f"{words} words")
    if not 3 <= sentences <= 8:
        problems.append(f"{sentences} sentences")
    if not 3 <= len(corrections) <= 8:
        problems.append(f"{len(corrections)} corrections")
    for c in corrections:
        if c["criterion"] not in g.codes:
            problems.append(f"{c['error']!r}: criterion {c['criterion']} not targeted")
        if c["error"] == c["correction"]:
            problems.append(f"{c['error']!r}: no change")
        if source.count(c["error"]) != 1:
            problems.append(f"{c['error']!r} occurs {source.count(c['error'])} times in the text")
    uncovered = sorted(set(g.codes) - {c["criterion"] for c in corrections})
    if uncovered:
        problems.append(f"no error for {uncovered}")
    check("W09", not problems, "; ".join(problems))

    applied = source
    for c in corrections:
        applied = applied.replace(c["error"], c["correction"], 1)
    check("W10", _clean(applied) == _clean(corrected) and source != corrected,
          "applying the corrections does not give the reference text")

    misfit = [f"{c['criterion']}: {c['error']!r} -> {c['correction']!r}" for c in corrections
              if not change_fits_criterion(c["criterion"], c["error"], c["correction"])]
    check("W11", not misfit, f"corrections outside their criterion: {misfit}")

    own = _words(source)
    similar = [round(len(own & _words(s)) / len(own | _words(s)), 2) for s in stored_sources if own | _words(s)]
    check("W12", all(x < 0.5 for x in similar), f"near duplicate of a stored text (overlap {max(similar or [0])})")
    return checks


# W13: tú imperatives and negative tú subjunctives that Costa Rican voseo replaces (Leé, Corregí, No cambiés…).
TU_FORMS = re.compile(
    r"^(lee|corrige|escribe|revisa|agrega|usa|piensa|recuerda|cambia|copia|borra|subraya|completa|presta)\b"
    r"|\bno\s+(cambies|agregues|quites|olvides|uses|escribas|copies|borres|dejes|pongas|cambies|repitas|"
    r"inventes|modifiques|elimines|añadas|cuentes|narres|digas|hagas|mezcles|salgas|copies|olvides|repitas|incluyas|menciones|expliques|tengas)\b", re.IGNORECASE)
STOPWORDS = {"para", "como", "este", "esta", "estos", "estas", "pero", "porque", "cada", "todos", "todas", "también",
             "donde", "cuando", "desde", "entre", "sobre", "muy", "más", "sus", "son", "que", "los", "las", "del",
             "una", "uno", "unos", "unas", "con", "por", "sin", "hay", "ser", "está", "están", "tiene", "tienen"}


def _content_words(sentence: str) -> list[str]:
    return [w for w in re.findall(r"[a-záéíóúñü]+", sentence.lower()) if len(w) >= 4 and w not in STOPWORDS]


def quality_checks(exercise: dict[str, Any], reference: dict[str, Any]) -> list[dict[str, str]]:
    """W13-W15 (T024): voseo, repetition and undocumented ambiguity."""
    checks: list[dict[str, str]] = []

    def check(check_id: str, ok: bool, message: str) -> None:
        checks.append({"id": check_id, "status": "pass" if ok else "fail", "message": "ok" if ok else message})

    tu = [i for i in exercise["instructions_es"] if TU_FORMS.search(i.strip())]
    check("W13", not tu, f"tú forms instead of voseo: {tu}")

    sentences = [x for x in re.split(r"(?<=[.!?])\s+", reference["corrected_text_es"]) if x.strip()]
    repeated = []
    for sentence in sentences:
        words = _content_words(sentence)
        repeated += sorted({w for w in words if words.count(w) > 1})
    duplicate_sentences = len({x.lower() for x in sentences}) < len(sentences)
    sets = [set(_content_words(i)) for i in exercise["instructions_es"]]
    similar = [(a, b) for a in range(len(sets)) for b in range(a + 1, len(sets))
               if sets[a] and sets[b] and len(sets[a] & sets[b]) / len(sets[a] | sets[b]) >= 0.6]
    check("W14", not repeated and not duplicate_sentences and not similar,
          f"repetition: words {repeated}, duplicate sentence {duplicate_sentences}, similar instructions {similar}")

    source = exercise["source_text_es"]
    unclear = []
    for c in reference["corrections"]:
        if c["correction"].count("¿") + c["correction"].count("¡") > c["error"].count("¿") + c["error"].count("¡"):
            before = source[:source.find(c["error"])].rstrip()
            mark = c["correction"].find("¿") if "¿" in c["correction"] else c["correction"].find("¡")
            inline = c["correction"][:mark].rstrip()
            context = (before + " " + inline).rstrip()
            if not (context.endswith(":") or context == "" or context[-1] in ".!?") and not reference["ambiguities_es"]:
                unclear.append(c["error"])
    check("W15", not unclear, f"added question/exclamation marks without a colon or documented alternative: "
                              f"{unclear}")
    return checks


def parse_review(text: str) -> dict[str, Any]:
    raw = extract_json(text, required=EDIT_REVIEW_KEYS)
    scores = {}
    for key in EDIT_REVIEW_KEYS:
        value = raw[key]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2:
            raise OutputError(f"review {key} must be 0, 1 or 2")
        scores[key] = value
    return {**scores, "notes": str(raw.get("notes", ""))[:500]}


# ---------------------------------------------------------------- generation loop

def generate_editing_exercise(client: OpenRouterClient, usage_store: Store, catalog: psycopg.Connection,
                              writing_store: Any, category: str, difficulty: str = "medium",
                              baseline: str = "PNE2026-SUM-v1.0", gate: BudgetGate | None = None) -> gen.WritingOutcome:
    """Generate, check, review and store one Nivel 1 correction exercise with its tutor-only reference."""
    plan = CATEGORIES[category]
    g = gen.build_grounding(catalog, baseline, "L1", difficulty, plan["criteria"], exercise_type="conventions_editing")
    gate = gate or BudgetGate(usage_store, client.settings, max_calls=gen.MAX_CALLS)
    avoid = writing_store.topics() if writing_store is not None else []
    sources = writing_store.source_texts("writing_conventions") if writing_store is not None else []
    attempts: list[gen.Attempt] = []
    stop: str | None = None
    for _ in range(gen.MAX_REQUESTS):
        attempt = EditAttempt(request_id=f"wreq-{uuid.uuid4().hex[:16]}")
        attempts.append(attempt)
        generated = route(client, usage_store, generation_messages(g, plan["focus_es"], avoid), purpose="generation",
                          max_tokens=EDIT_MAX_TOKENS, request_id=attempt.request_id, gate=gate)
        attempt.usage += generated.records
        if generated.status == "exhausted":  # truncated or failed output: counts as one of the bounded requests
            attempt.reasons.append(f"generation exhausted: {generated.message}")
            _record(writing_store, g, attempt)
            continue
        if generated.status != "ok":
            attempt.status, stop = "unavailable", gen._stop_reason(generated)
            attempt.reasons.append(f"generation {generated.status}: {generated.message}")
            _record(writing_store, g, attempt)
            break
        try:
            fields = model_fields(generated.content or "")
            attempt.checks.append({"id": "W01", "status": "pass", "message": "ok"})
        except OutputError as exc:
            attempt.checks.append({"id": "W01", "status": "fail", "message": str(exc)})
            attempt.reasons.append(f"W01: {exc}")
            _record(writing_store, g, attempt)
            continue
        exercise, reference = assemble(g, fields)
        attempt.exercise, attempt.reference = exercise, reference
        attempt.checks += (gen.deterministic_checks(g, exercise, avoid) + editing_checks(g, exercise, reference, sources)
                           + quality_checks(exercise, reference))
        failed = [c for c in attempt.checks if c["status"] == "fail"]
        if failed:
            attempt.reasons += [f"{c['id']}: {c['message']}" for c in failed]
            _record(writing_store, g, attempt)
            continue
        generator = generated.final.model_used if generated.final else None
        reviewed = gen.review_route(client, usage_store, review_messages(g, exercise, reference),
                                    EDIT_REVIEW_MAX_TOKENS, attempt.request_id, generator, gate)
        attempt.usage += reviewed.records
        if reviewed.status != "ok":
            attempt.status, stop = "unavailable", gen._stop_reason(reviewed)
            attempt.reasons.append(f"review {reviewed.status}: {reviewed.message}")
            _record(writing_store, g, attempt)
            break
        same = gen.same_model_review(generator, reviewed)  # RCA-004: W08 must come from another model
        if same:
            attempt.checks.append({"id": "W08", "status": "fail", "message": same})
            attempt.reasons.append(f"W08: {same}")
            _record(writing_store, g, attempt)
            continue
        try:
            attempt.review = parse_review(reviewed.content or "") | gen.reviewer_of(reviewed)
        except OutputError as exc:
            attempt.checks.append({"id": "W08", "status": "fail", "message": f"review output: {exc}"})
            attempt.reasons.append(f"W08: review output: {exc}")
            _record(writing_store, g, attempt)
            continue
        low = {k: v for k, v in attempt.review.items() if k in EDIT_REVIEW_KEYS and v < 2}
        attempt.checks.append({"id": "W08", "status": "fail" if low else "pass",
                               "message": f"review below 2: {low}; {attempt.review['notes']}" if low else "ok"})
        if low:
            attempt.reasons.append(f"W08: review below 2: {low}")
            _record(writing_store, g, attempt)
            continue
        attempt.status = "accepted"
        _record(writing_store, g, attempt)
        if writing_store is not None:
            writing_store.add_exercise(exercise, generation_request_id=attempt.request_id, reference=reference)
        return gen.WritingOutcome("accepted", exercise, attempts)
    return gen.WritingOutcome("unavailable" if stop else "rejected", None, attempts, stop or "max_requests")


def _record(writing_store: Any, g: gen.Grounding, attempt: EditAttempt) -> None:
    if writing_store is not None:
        writing_store.add_generation_attempt(attempt, g.level["code"], g.difficulty, g.codes, PROMPT_VERSION)
