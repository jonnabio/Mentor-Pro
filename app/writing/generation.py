"""Generate one Producción escrita exercise with OpenRouter (T021, ADR-020).

The model writes only student-facing text (topic, situation, ideas, instructions, deliverable description).
Code assembles the record from the level map and the official rubric (ADR-019), so criteria and
descriptors cannot be invented or altered. Each attempt passes deterministic checks W01-W07 and an
independent review W08; up to MAX_REQUESTS generation requests share one budget gate.
T028 (ADR-026): Nivel 4 adds a four-item paragraph plan (W19); its optional EE07-EE18 are left out of the
prompts, which name only the criteria every evaluation scores.
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg

from app.generation.parsing import OutputError, extract_json
from app.generation.pipeline import RUBRIC_MAX_TOKENS
from app.llm.budget import BudgetGate
from app.llm.client import OpenRouterClient
from app.llm.router import RouteResult, Store, route
from app.writing import contracts
from curriculum.catalog import list_rubric_criteria

PROMPT_VERSION = "writing-1.3"  # 1.1 (T025): paragraph scope, no model text, voseo; 1.2: short sentences;
# 1.3 (T028): L4 paragraph plan. Prompts of the other levels are unchanged.
MAX_REQUESTS = 3
MAX_CALLS = 12  # generation and review calls per exercise, including route() retries
LEVEL_ALIASES = {f"L{lv['ordinal']}": lv["code"] for lv in contracts.levels()["levels"]}
DIFFICULTY_ES = {"easy": "Fácil", "medium": "Intermedia", "hard": "Difícil"}
REVIEW_KEYS = ("clarity", "age_appropriate", "completeness", "alignment", "language")
COMPOSE_REVIEW_KEYS = REVIEW_KEYS + ("paragraph_scope", "no_model_text")  # T025, composed paragraphs (L2-L5)
# W16 (T025): ideas that belong to another paragraph type. Introductions present the topic; development
# explains causes and consequences; conclusions propose actions or solutions.
OUT_OF_SCOPE = {
    "introduction_paragraph": ("consecuencia", "solucion", "accion", "acciones", "causa", "provoca"),
    "development_paragraphs": ("solucion", "acciones", "accion", "que podes hacer", "recomend"),
    "conclusion_paragraph": ("causa", "provoca", "consecuencia"),
}
GUIDE_SHA = "2b42d432a0eca2bc3f363823db5941381abea806f511af8573a3da46f092b265"
TEST_SHA = "7e657f24295b8fdc63bcdc25217e31bb69ef5d2cdf7d1d148979fe641cc00928"
# Topics of the MEP model test and the preparation guide: style models, never reused (W06).
MODEL_TOPICS = ("La importancia de la higiene en la vida diaria", "La importancia del agua para la salud",
                "El cuidado del medio ambiente", "La tecnología y su impacto en la vida cotidiana",
                "La actividad física y sus beneficios", "La lectura como hábito fundamental")
MODEL_TASK_ES = """Modelo de consigna (Prueba Nacional de Producción de texto escrito, primaria 2026):
1. Escriba un texto expositivo. Recuerde que el propósito de este tipo de texto es informar y explicar un tema, no narrar una historia.
2. El tema es: La importancia de la higiene en la vida diaria
Situación comunicativa: En la escuela, el hogar y otros espacios, las personas realizan distintas actividades que requieren mantener buenos hábitos de higiene. Sin embargo, en algunos casos no se practican estos hábitos de forma adecuada, lo que puede provocar enfermedades o afectar la convivencia. Ante esta situación, usted debe escribir un texto expositivo en el que presente información clara y organizada sobre este tema.
Para desarrollar su texto, puede considerar las siguientes ideas: (cuatro ideas: importancia, causas, consecuencias, acciones o soluciones)
3. Redacte el texto expositivo en cuatro párrafos: uno de introducción, dos de desarrollo y uno de conclusión.
4. Dispone de 90 minutos para escribir el texto expositivo."""

SYSTEM = ("Usted diseña ejercicios de producción escrita para estudiantes de sexto grado de primaria en Costa Rica, "
          "según la Prueba Nacional Estandarizada de producción de texto escrito del MEP. Escribe en español de "
          "Costa Rica, con lenguaje claro para niñas y niños de 11 a 12 años. Responde solo con un objeto JSON.")
REVIEW_SYSTEM = ("Usted revisa ejercicios de producción escrita para sexto grado de primaria en Costa Rica. Evalúa "
                 "si la persona estudiante puede entender y completar el ejercicio, y si el ejercicio permite "
                 "evaluar los criterios indicados. Responde solo con un objeto JSON.")
MODEL_FIELDS = ("topic_es", "communicative_situation_es", "suggested_ideas_es", "instructions_es",
                "deliverable_description_es")
PLAN_FIELD = "paragraph_plan_es"  # T028: guided_composition only, stored as scaffolding_es
# W19: what each of the four plan items must (first) and must not (second) talk about, in order.
PLAN_SCOPE = (
    ((), ("causa", "consecuencia", "solucion")),
    (("causa", "por que", "origen", "motivo", "razon"), ("solucion",)),
    (("consecuencia", "efecto", "afecta", "provoca", "result"), ("solucion",)),
    (("accion", "solucion", "medida", "propuesta", "recomend", "podemos", "pueden", "cierre", "conclu"), ("causa",)),
)


class WritingRequestError(ValueError):
    """The requested level, difficulty and criteria do not form a valid exercise request."""


@dataclass
class Grounding:
    baseline: str
    level: dict[str, Any]
    exercise_type: str
    difficulty: str
    deliverable: dict[str, Any]
    criteria: list[dict[str, Any]]  # code, assertion_id, statement_es, descriptors_es, concepts_es, activity_es

    @property
    def codes(self) -> list[str]:
        return [c["code"] for c in self.criteria]

    @property
    def guided(self) -> bool:
        return self.exercise_type == "guided_composition"

    def optional(self, code: str) -> bool:
        """T028: conventions criteria the tutor may score in a guided composition, never required."""
        return (self.level["code"] in contracts.OPTIONAL_LEVELS and code in contracts.CONVENTION_CRITERIA
                and code not in self.level["core_criteria"])

    @property
    def required(self) -> list[dict[str, Any]]:
        return [c for c in self.criteria if not self.optional(c["code"])]


@dataclass
class Attempt:
    request_id: str
    status: str = "rejected"           # accepted | rejected | unavailable
    checks: list[dict[str, str]] = field(default_factory=list)
    review: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    exercise: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        sent = [u for u in self.usage if u["status"] != "budget_blocked"]
        ok = [u for u in sent if u["status"] == "ok"]
        return {"calls": len(sent), "tokens_in": sum(u["tokens_in"] or 0 for u in sent),
                "tokens_out": sum(u["tokens_out"] or 0 for u in sent),
                "cost_usd": round(sum(u["cost_usd"] or 0 for u in sent), 8),
                "cost_complete": all(u["cost_usd"] is not None for u in ok),
                "models_used": sorted({u["model_used"] for u in sent if u["model_used"]})}


@dataclass
class WritingOutcome:
    status: str                        # accepted | rejected | unavailable
    exercise: dict[str, Any] | None
    attempts: list[Attempt]
    stop_reason: str | None = None


# ---------------------------------------------------------------- request and grounding

def resolve_level(level: str) -> dict[str, Any]:
    code = LEVEL_ALIASES.get(level.upper(), level) if level else level
    try:
        return contracts.level(code)
    except StopIteration:
        raise WritingRequestError(f"unknown writing level {level!r}") from None


def exercise_type_for(level: dict[str, Any], criteria: list[str]) -> str:
    if level["code"] == "writing_conventions":
        return "conventions_production"
    if level["code"] == "paragraph_writing":
        if "EE05" in criteria and "EE06" in criteria:
            raise WritingRequestError("paragraph_writing targets EE05 or EE06, not both")
        return "development_paragraphs" if "EE05" in criteria else "conclusion_paragraph"
    return level["exercise_types"][0]


def deliverable_for(level: dict[str, Any], exercise_type: str, difficulty: str) -> dict[str, Any]:
    spec = level["deliverable"]
    if exercise_type in ("conventions_production", "conventions_editing"):
        low, high = {"easy": (3, 4), "medium": (4, 6), "hard": (6, 8)}[difficulty]
    elif exercise_type == "development_paragraphs":
        low = high = 2
    elif exercise_type in ("conclusion_paragraph", "introduction_paragraph"):
        low = high = 1  # EE04 and EE06 assess a single paragraph (T025 fix: conclusions got the L3 range 1-2)
    else:
        low, high = spec["min"], spec["max"]
    deliverable = {"unit": spec["unit"], "min": low, "max": high,
                   "evidence_mode": "handwritten" if level["code"] == "full_composition" else "typed"}
    for key in ("words_target", "time_limit_min"):
        if key in spec:
            deliverable[key] = spec[key]
    return deliverable


def build_grounding(catalog: psycopg.Connection, baseline: str, level: str, difficulty: str,
                    criteria: list[str], exercise_type: str | None = None) -> Grounding:
    """Check the request against the level map and join catalog records with the official rubric."""
    lv = resolve_level(level)
    if difficulty not in DIFFICULTY_ES:
        raise WritingRequestError(f"difficulty must be one of {sorted(DIFFICULTY_ES)}")
    codes = list(dict.fromkeys(c.upper() for c in criteria))
    if exercise_type is not None and exercise_type not in lv["exercise_types"]:
        raise WritingRequestError(f"exercise type {exercise_type} is not part of level {lv['code']}")
    exercise_type = exercise_type or exercise_type_for(lv, codes)
    core = set(lv["core_criteria"]) | set(lv.get("type_core_criteria", {}).get(exercise_type, []))
    if not codes or set(codes) - set(lv["allowed_criteria"]) or core - set(codes) \
            or len(codes) < lv["min_target_criteria"]:
        raise WritingRequestError(f"criteria {codes} do not fit level {lv['code']}: core {sorted(core)}, "
                                  f"allowed {lv['allowed_criteria']}")
    catalog_rows = {r["workbook_code"]: r for r in list_rubric_criteria(catalog, baseline)}
    rubric = contracts.criteria()
    joined = []
    for code in codes:
        row, official = catalog_rows.get(code), rubric[code]
        expected_id = f"PNE2026-PRI-ESP-PE-B{official['dimension']}-A{official['rubric_number']}"
        if row is None or row["id"] != expected_id:
            raise WritingRequestError(f"{code} is not a written-rubric record of baseline {baseline}")
        joined.append({"code": code, "assertion_id": row["id"], "statement_es": official["statement_es"],
                       "descriptors_es": official["descriptors_es"], "concepts_es": row["concepts_es"],
                       "activity_es": row["check_activity_es"]})
    joined.sort(key=lambda c: c["code"])
    return Grounding(baseline, lv, exercise_type, difficulty, deliverable_for(lv, exercise_type, difficulty), joined)


# ---------------------------------------------------------------- prompts

def _deliverable_es(g: Grounding) -> str:
    d = g.deliverable
    unit = {"sentences": "oraciones", "paragraphs": "párrafos"}[d["unit"]]
    amount = f"{d['min']}" if d["min"] == d["max"] else f"de {d['min']} a {d['max']}"
    text = f"{amount} {unit}" if not (d["min"] == d["max"] == 1) else "un solo párrafo"
    kind = {"introduction_paragraph": " de introducción", "development_paragraphs": " de desarrollo (causas y "
            "consecuencias)", "conclusion_paragraph": " de conclusión (acciones o soluciones)",
            "guided_composition": ": introducción, dos de desarrollo y conclusión",
            "full_composition": ": introducción, dos de desarrollo y conclusión"}.get(g.exercise_type, "")
    extra = f"; al menos {d['words_target']} palabras" if "words_target" in d else ""
    extra += f"; {d['time_limit_min']} minutos" if "time_limit_min" in d else ""
    return f"{text}{kind}{extra}"


CONTENT_ES = {
    "conventions_production": "oraciones completas sobre el tema, escritas con cuidado de la ortografía y la puntuación",
    "introduction_paragraph": ("un párrafo de introducción con una idea principal que presente el tema y al menos "
                               "dos ideas complementarias relacionadas con la situación comunicativa"),
    "development_paragraphs": ("dos párrafos de desarrollo: el primero explica causas y el segundo consecuencias; "
                               "cada uno con una idea principal y al menos dos ideas complementarias"),
    "conclusion_paragraph": ("un párrafo de conclusión con una idea principal y al menos dos ideas complementarias "
                             "sobre acciones o soluciones"),
    "guided_composition": "cuatro párrafos (introducción, dos de desarrollo y conclusión) de al menos 200 palabras",
    "full_composition": ("cuatro párrafos (introducción, dos de desarrollo y conclusión) de al menos 200 palabras, "
                         "escritos a mano en 90 minutos"),
}


SCOPE_ES = {
    "conventions_production": "oraciones sobre el tema.",
    "conventions_editing": "corrección del texto.",
    "introduction_paragraph": "presentar el tema y por qué importa; no causas, consecuencias ni soluciones.",
    "development_paragraphs": "causas (primer párrafo) y consecuencias (segundo párrafo); no soluciones.",
    "conclusion_paragraph": "acciones o soluciones y un cierre; no causas ni consecuencias nuevas.",
    "guided_composition": "introducción, causas, consecuencias y soluciones.",
    "full_composition": "introducción, causas, consecuencias y soluciones.",
}


def generation_messages(g: Grounding, avoid_topics: list[str]) -> list[dict[str, str]]:
    criteria = "\n".join(
        f"- {c['code']}: {c['statement_es']}\n  Desempeño esperado (4 puntos): {c['descriptors_es'][4]}\n"
        f"  Contenidos: {c['concepts_es']}" for c in g.required)
    avoid = "; ".join(list(MODEL_TOPICS) + avoid_topics)
    user = f"""Cree UN ejercicio original de producción escrita.

Nivel: {g.level['ordinal']} — {g.level['name_es']} ({g.level['purpose']})
Tipo de ejercicio: {g.exercise_type}
Dificultad: {DIFFICULTY_ES[g.difficulty]}
Producto esperado de la persona estudiante: {_deliverable_es(g)}
Tipo de texto: expositivo (informa y explica; no narra una historia).

Criterios que se evaluarán (no los cite en el ejercicio; úselos para que el ejercicio permita lograrlos):
{criteria}

{MODEL_TASK_ES}

Reglas:
- Tema original, cercano a la vida de estudiantes de sexto grado en Costa Rica, distinto de: {avoid}.
- La situación comunicativa dice quién escribe, para qué y para quién (por ejemplo, una campaña o feria escolar),
  en 2 o 3 oraciones cortas de máximo 25 palabras cada una. Ninguna oración del ejercicio supera 25 palabras.
- De 3 a 7 instrucciones numeradas implícitamente (una por elemento), cortas y claras, en segunda persona con voseo
  costarricense (por ejemplo «Escribí», «Agregá»), sin palabras difíciles.
- Las instrucciones deben decir exactamente qué entregar ({_deliverable_es(g)}) y qué debe contener:
  {CONTENT_ES[g.exercise_type]}. Use esas mismas palabras clave.
- 2 a 4 ideas sugeridas, relacionadas con la situación comunicativa.
- No mencione códigos de criterios, puntos, rúbricas ni calificación.
- Las ideas sugeridas son temas breves (máximo 15 palabras), no oraciones listas para copiar; no escriba un
  párrafo modelo ni un ejemplo completo.
- Las ideas sugeridas corresponden solo a este tipo de párrafo: {SCOPE_ES[g.exercise_type]}
- Instrucciones sin repetir la misma idea, en voseo también en negativo («No copiés»; nunca «No copies»).
{PLAN_RULES_ES if g.guided else ""}
Responda solo con este JSON:
{{"topic_es": "...", "communicative_situation_es": "...", "suggested_ideas_es": ["..."],
  "instructions_es": ["..."], "deliverable_description_es": "..."{PLAN_JSON if g.guided else ""}}}"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


PLAN_RULES_ES = """- Las instrucciones nombran los cuatro párrafos: introducción, dos de desarrollo y conclusión.
- Agregue un plan de párrafos con exactamente 4 orientaciones cortas (máximo 20 palabras cada una), en este orden:
  1) introducción: qué presentar del tema; 2) primer párrafo de desarrollo: causas;
  3) segundo párrafo de desarrollo: consecuencias; 4) conclusión: acciones o soluciones y un cierre.
  Cada orientación es una pregunta o una pista para pensar (por ejemplo «¿Por qué ocurre…?»), nunca una oración
  lista para copiar en el texto.
"""
PLAN_JSON = ', "paragraph_plan_es": ["...", "...", "...", "..."]'


def review_messages(g: Grounding, exercise: dict[str, Any]) -> list[dict[str, str]]:
    student = {k: exercise[k] for k in ("topic_es", "communicative_situation_es", "suggested_ideas_es",
                                         "instructions_es")}
    student["deliverable_es"] = exercise["deliverable"]["description_es"]
    if exercise.get("scaffolding_es"):
        student["paragraph_plan_es"] = exercise["scaffolding_es"]
    criteria = "\n".join(f"- {c['code']}: {c['statement_es']}" for c in g.required)
    user = f"""Ejercicio para sexto grado (nivel {g.level['ordinal']}, {g.level['name_es']}; producto esperado:
{_deliverable_es(g)}):
{json.dumps(student, ensure_ascii=False, indent=1)}

Criterios que el ejercicio debe permitir evaluar:
{criteria}

Califique de 0 a 2 (2 = cumple por completo, 1 = cumple con fallas, 0 = no cumple):
- clarity: instrucciones claras e inequívocas.
- age_appropriate: vocabulario, tema y extensión adecuados para 11-12 años.
- completeness: contiene toda la información necesaria para escribir sin ayuda.
- alignment: el producto pedido permite evaluar cada criterio indicado.
- language: español correcto de Costa Rica, instrucciones en voseo y sin repetir ideas.
- paragraph_scope: las ideas sugeridas corresponden solo al tipo de párrafo pedido ({SCOPE_ES[g.exercise_type]})
- no_model_text: el ejercicio no da un párrafo modelo ni oraciones listas para copiar.
Responda solo con JSON: {{"clarity": 0, "age_appropriate": 0, "completeness": 0, "alignment": 0,
"language": 0, "paragraph_scope": 0, "no_model_text": 0, "notes": "..."}}"""
    return [{"role": "system", "content": REVIEW_SYSTEM}, {"role": "user", "content": user}]


# ---------------------------------------------------------------- assembly and checks

def model_fields(text: str, guided: bool = False) -> dict[str, Any]:
    """W01: the required fields with the right types (only these are taken from the model)."""
    names = MODEL_FIELDS + ((PLAN_FIELD,) if guided else ())
    raw = extract_json(text, required=names)
    fields = {k: raw[k] for k in names}
    for key in ("topic_es", "communicative_situation_es", "deliverable_description_es"):
        if not isinstance(fields[key], str) or not fields[key].strip():
            raise OutputError(f"{key} must be a non-empty string")
        fields[key] = " ".join(fields[key].split())
    for key in ("suggested_ideas_es", "instructions_es") + ((PLAN_FIELD,) if guided else ()):
        if not isinstance(fields[key], list) or not all(isinstance(x, str) and x.strip() for x in fields[key]):
            raise OutputError(f"{key} must be a list of non-empty strings")
        fields[key] = [" ".join(re.sub(r"^\s*(\d+[.)]|[-•])\s*", "", x).split()) for x in fields[key]]
    return fields


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = [w for w in re.findall(r"[a-z0-9]+", plain) if w not in {"la", "el", "los", "las", "de", "del", "y",
                                                                    "en", "un", "una", "para", "por"}]
    return "-".join(words[:3]) or "ejercicio"


def assemble(g: Grounding, fields: dict[str, Any]) -> dict[str, Any]:
    """The full exercise record: model text plus code-owned level, criteria, rubric and provenance."""
    typed = g.deliverable["evidence_mode"] == "typed"
    rubric = contracts.rubric()
    parameters = []
    for c in g.criteria:
        p = {"criterion": c["code"], "rubric_ref": f"{rubric['rubric_id']}#{c['code']}", "applicability": "scored"}
        if c["code"] in contracts.handwritten_criteria() and typed:
            p.update(applicability="not_evaluable", not_evaluable_reason="handwritten_evidence_required")
        if g.optional(c["code"]):
            p["optional"] = True
        parameters.append(p)
    scaffolding = {"scaffolding_es": fields[PLAN_FIELD]} if g.guided and PLAN_FIELD in fields else {}
    return {
        "schema_version": "1.0",
        "exercise_id": f"PE-L{g.level['ordinal']}-{_slug(fields['topic_es'])}-{secrets.token_hex(3)}",
        "level": g.level["code"], "exercise_type": g.exercise_type, "difficulty": g.difficulty,
        "language": "es-CR", "text_type": "expositivo",
        "topic_es": fields["topic_es"], "communicative_situation_es": fields["communicative_situation_es"],
        "suggested_ideas_es": fields["suggested_ideas_es"], **scaffolding,
        "instructions_es": fields["instructions_es"],
        "deliverable": {"description_es": fields["deliverable_description_es"], **g.deliverable},
        "target_criteria": g.codes,
        "evaluation": {"evaluator": "human", "rubric_id": rubric["rubric_id"],
                       "rubric_sha256": rubric["source"]["file_sha256"], "scale": {"min": 0, "max": 4},
                       "counting_rule": "identical_repetition_counts_once", "parameters": parameters},
        "provenance": {"baseline_version": g.baseline,
                       "curriculum_records": [{"workbook_code": c["code"], "assertion_id": c["assertion_id"]}
                                              for c in g.criteria],
                       "sources": [{"document_id": rubric["rubric_id"], "role": "rubric",
                                    "file_sha256": rubric["source"]["file_sha256"]},
                                   {"document_id": "MEP-PRUEBA-PE-2026-MODELO", "role": "task_model",
                                    "file_sha256": TEST_SHA},
                                   {"document_id": "GUIA-PE-2026", "role": "topic_model", "file_sha256": GUIDE_SHA}],
                       "authored_by": "llm_draft_human_reviewed"},
    }


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _student_text(exercise: dict[str, Any]) -> str:
    """Everything the student sees (T023: also the title and the text to correct)."""
    return " ".join([exercise.get("title_es", ""), exercise["topic_es"], exercise["communicative_situation_es"],
                     *exercise.get("suggested_ideas_es", []), *exercise.get("scaffolding_es", []),
                     *exercise["instructions_es"],
                     exercise["deliverable"]["description_es"], exercise.get("source_text_es", "")]).strip()


def deterministic_checks(g: Grounding, exercise: dict[str, Any], avoid_topics: list[str]) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def check(check_id: str, ok: bool, message: str) -> None:
        checks.append({"id": check_id, "status": "pass" if ok else "fail", "message": "ok" if ok else message})

    problems = contracts.validate_exercise(exercise)
    check("W02", not problems, "; ".join(problems))

    text = _student_text(exercise)
    plain = _plain(text)
    leaks = re.findall(r"\bEE ?\d{2}\b", text) + re.findall(r"\b\d\s*puntos?\b", plain) \
        + [w for w in ("rubrica", "calificacion", "descriptor") if w in plain]
    copied = [c["code"] for c in g.criteria for d in c["descriptors_es"] if _plain(d)[:60] in plain]
    check("W03", not leaks and not copied, f"rubric content in student text: {leaks + copied}")

    instructions = _plain(" ".join(exercise["instructions_es"] + [exercise["deliverable"]["description_es"]]))
    need = {
        "conventions_production": [("oracion",)],
        "conventions_editing": [("corregi", "corrige", "correg"), ("texto",)],
        "introduction_paragraph": [("parrafo",), ("introduccion",), ("idea principal",),
                                   ("dos ideas", "ideas complementarias", "ideas que la apoyen")],
        "development_paragraphs": [("dos parrafos",), ("causa",), ("consecuencia",)],
        "conclusion_paragraph": [("parrafo",), ("conclusion",), ("accion", "solucion")],
        "guided_composition": [("cuatro parrafos", "4 parrafos"), ("200 palabras",), ("desarrollo",),
                               ("conclusion",)],
        "full_composition": [("cuatro parrafos", "4 parrafos"), ("200 palabras",), ("90 minutos",)],
    }[g.exercise_type]
    if "EE04" in g.codes and g.exercise_type != "introduction_paragraph":
        need.append(("introduccion",))
    missing = [" / ".join(alts) for alts in need if not any(a in instructions for a in alts)]
    check("W04", not missing, f"instructions do not state: {missing}")

    long_items = [i for i in exercise["instructions_es"] if len(i) > 220]
    ideas = exercise.get("suggested_ideas_es", [])
    parts = [exercise["topic_es"], exercise["communicative_situation_es"], *ideas,
             *exercise["instructions_es"], exercise["deliverable"]["description_es"],
             exercise.get("source_text_es", "")]
    sentences = [s for part in parts for s in re.split(r"(?<=[.!?;:])\s+", part) if s.strip()]
    long_sentences = [s for s in sentences if len(s.split()) > 30]
    sizes_ok = (3 <= len(exercise["instructions_es"]) <= 7 and not long_items and not long_sentences
                and 60 <= len(exercise["communicative_situation_es"]) <= 700 and len(exercise["topic_es"]) <= 90
                and (0 if g.exercise_type == "conventions_editing" else 2) <= len(ideas) <= 4)
    check("W05", sizes_ok, f"length limits: {len(exercise['instructions_es'])} instructions, "
                           f"{len(long_items)} long items, {len(long_sentences)} sentences over 30 words, "
                           f"situation {len(exercise['communicative_situation_es'])} chars, "
                           f"{len(ideas)} ideas")

    topic = _plain(exercise["topic_es"]).strip(" .")
    reused = [t for t in list(MODEL_TOPICS) + avoid_topics if _plain(t).strip(" .") == topic]
    check("W06", not reused, f"topic reuses a model or stored topic: {reused}")

    english = [w for w in ("write ", " the ", "paragraph", "sentence", "student") if w in f" {plain} "]
    spanish = bool(re.search(r"[áéíóúñ]", text.lower()))
    check("W07", spanish and not english, f"language: accents {spanish}, English words {english}")
    return checks


def compose_checks(g: Grounding, exercise: dict[str, Any], stored: list[dict[str, Any]]) -> list[dict[str, str]]:
    """W13, W14, W16-W18 for composed paragraphs (T025); `stored` are the other stored exercise records."""
    from app.writing.editing import TU_FORMS, _content_words  # editing imports this module

    checks: list[dict[str, str]] = []

    def check(check_id: str, ok: bool, message: str) -> None:
        checks.append({"id": check_id, "status": "pass" if ok else "fail", "message": "ok" if ok else message})

    tu = [i for i in exercise["instructions_es"] if TU_FORMS.search(i.strip())]
    check("W13", not tu, f"tú forms instead of voseo: {tu}")
    sets = [set(_content_words(i)) for i in exercise["instructions_es"]]
    similar = [(a + 1, b + 1) for a in range(len(sets)) for b in range(a + 1, len(sets))
               if sets[a] and sets[b] and len(sets[a] & sets[b]) / min(len(sets[a]), len(sets[b])) >= 0.75]
    check("W14", not similar, f"instructions repeat each other: {similar}")
    words = OUT_OF_SCOPE.get(g.exercise_type, ())
    off = [i for i in exercise["suggested_ideas_es"] if any(w in _plain(i) for w in words)]
    check("W16", not off, f"ideas outside the {g.exercise_type} scope: {off}")
    long_ideas = [i for i in exercise["suggested_ideas_es"] if len(i.split()) > 15]
    situation_sentences = len([x for x in re.split(r"(?<=[.!?])\s+", exercise["communicative_situation_es"]) if x])
    check("W17", not long_ideas and situation_sentences <= 3,
          f"model text: {len(long_ideas)} ideas over 15 words, situation of {situation_sentences} sentences")

    def bag(record: dict[str, Any]) -> set[str]:
        return set(_content_words(" ".join([record["topic_es"], record["communicative_situation_es"]])))

    own_topic, own = set(_content_words(exercise["topic_es"])), bag(exercise)
    near = [r["topic_es"] for r in stored
            if (own_topic and len(own_topic & set(_content_words(r["topic_es"]))) / len(own_topic) >= 0.6)
            or (own and len(own & bag(r)) / len(own | bag(r)) >= 0.4)]
    check("W18", not near, f"near-duplicate topic or situation: {near}")
    if g.guided:
        check("W19", *plan_problems(exercise.get("scaffolding_es", [])))
    return checks


def plan_problems(plan: list[str]) -> tuple[bool, str]:
    """W19 (T028): four short plan items in order (introduction, causes, consequences, conclusion), each in its
    paragraph's scope; questions or hints, not sentences to copy."""
    if len(plan) != 4:
        return False, f"paragraph plan needs exactly 4 items, got {len(plan)}"
    problems = [f"item {n + 1} over 25 words" for n, item in enumerate(plan) if len(item.split()) > 25]
    for n, (item, (need, avoid)) in enumerate(zip(plan, PLAN_SCOPE)):
        text = _plain(item)
        if need and not any(w in text for w in need):
            problems.append(f"item {n + 1} does not name its paragraph scope {need[:2]}")
        off = [w for w in avoid if w in text]
        if off:
            problems.append(f"item {n + 1} talks about another paragraph {off}")
    return not problems, "; ".join(problems)


def parse_review(text: str, keys: tuple[str, ...] = REVIEW_KEYS) -> dict[str, Any]:
    raw = extract_json(text, required=keys)
    scores = {}
    for key in keys:
        value = raw[key]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2:
            raise OutputError(f"review {key} must be 0, 1 or 2")
        scores[key] = value
    return {**scores, "notes": str(raw.get("notes", ""))[:500]}


# ---------------------------------------------------------------- generation loop

def generate_exercise(client: OpenRouterClient, usage_store: Store, catalog: psycopg.Connection, writing_store: Any,
                      level: str, difficulty: str, criteria: list[str], baseline: str = "PNE2026-SUM-v1.0",
                      gate: BudgetGate | None = None) -> WritingOutcome:
    """Generate, check, review and store one exercise; every attempt is recorded in writing.generation_attempt."""
    g = build_grounding(catalog, baseline, level, difficulty, criteria)
    gate = gate or BudgetGate(usage_store, client.settings, max_calls=MAX_CALLS)
    avoid = writing_store.topics() if writing_store is not None else []
    stored = [r["record"] for r in writing_store.exercises()] if writing_store is not None else []
    attempts: list[Attempt] = []
    stop: str | None = None
    for _ in range(MAX_REQUESTS):
        attempt = Attempt(request_id=f"wreq-{uuid.uuid4().hex[:16]}")
        attempts.append(attempt)
        generated = route(client, usage_store, generation_messages(g, avoid), purpose="generation",
                          max_tokens=client.settings.generation_max_tokens, request_id=attempt.request_id, gate=gate)
        attempt.usage += generated.records
        if generated.status != "ok":
            attempt.status, stop = "unavailable", _stop_reason(generated)
            attempt.reasons.append(f"generation {generated.status}: {generated.message}")
            _record(writing_store, g, attempt)
            break
        try:
            fields = model_fields(generated.content or "", g.guided)
            attempt.checks.append({"id": "W01", "status": "pass", "message": "ok"})
        except OutputError as exc:
            attempt.checks.append({"id": "W01", "status": "fail", "message": str(exc)})
            attempt.reasons.append(f"W01: {exc}")
            _record(writing_store, g, attempt)
            continue
        exercise = assemble(g, fields)
        attempt.exercise = exercise
        attempt.checks += deterministic_checks(g, exercise, avoid) + compose_checks(g, exercise, stored)
        failed = [c for c in attempt.checks if c["status"] == "fail"]
        if failed:
            attempt.reasons += [f"{c['id']}: {c['message']}" for c in failed]
            _record(writing_store, g, attempt)
            continue
        generator = generated.final.model_used if generated.final else None
        reviewed = route(client, usage_store, review_messages(g, exercise), purpose="review",
                         max_tokens=RUBRIC_MAX_TOKENS, request_id=attempt.request_id,
                         avoid=frozenset({generator} if generator else ()), gate=gate)
        attempt.usage += reviewed.records
        if reviewed.status != "ok":
            attempt.status, stop = "unavailable", _stop_reason(reviewed)
            attempt.reasons.append(f"review {reviewed.status}: {reviewed.message}")
            _record(writing_store, g, attempt)
            break
        same = same_model_review(generator, reviewed)  # RCA-004: W08 must come from another model
        if same:
            attempt.checks.append({"id": "W08", "status": "fail", "message": same})
            attempt.reasons.append(f"W08: {same}")
            _record(writing_store, g, attempt)
            continue
        try:
            attempt.review = parse_review(reviewed.content or "", COMPOSE_REVIEW_KEYS)
        except OutputError as exc:
            attempt.checks.append({"id": "W08", "status": "fail", "message": f"review output: {exc}"})
            attempt.reasons.append(f"W08: review output: {exc}")
            _record(writing_store, g, attempt)
            continue
        low = {k: v for k, v in attempt.review.items() if k in COMPOSE_REVIEW_KEYS and v < 2}
        attempt.checks.append({"id": "W08", "status": "fail" if low else "pass",
                               "message": f"review below 2: {low}; {attempt.review['notes']}" if low else "ok"})
        if low:
            attempt.reasons.append(f"W08: review below 2: {low}")
            _record(writing_store, g, attempt)
            continue
        attempt.status = "accepted"
        _record(writing_store, g, attempt)
        if writing_store is not None:
            writing_store.add_exercise(exercise, generation_request_id=attempt.request_id)
        return WritingOutcome("accepted", exercise, attempts)
    status = "unavailable" if stop else "rejected"
    return WritingOutcome(status, None, attempts, stop or "max_requests")


def same_model_review(generator: str | None, reviewed: RouteResult) -> str | None:
    """RCA-004: route() only tries the generator last, so when every other model fails the generator can review
    its own exercise. W08 is an independent review (ADR-020): that review is refused, never accepted."""
    reviewer = reviewed.final.model_used if reviewed.final else None
    if generator and reviewer == generator:
        return f"review not independent: {reviewer} also generated the exercise"
    return None


def _stop_reason(result: RouteResult) -> str:
    return "daily_budget" if result.status == "budget_blocked" else "llm_unavailable"


def _record(writing_store: Any, g: Grounding, attempt: Attempt) -> None:
    if writing_store is not None:
        writing_store.add_generation_attempt(attempt, g.level["code"], g.difficulty, g.codes, PROMPT_VERSION)
