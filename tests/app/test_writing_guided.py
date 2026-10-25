"""Nivel 4 guided composition (T028, ADR-026): generation, five-stage drafts, submission, tutor, progress."""

from __future__ import annotations

import copy
import uuid

import pytest

from app.writing import contracts, generation
from app.writing.store import assemble_sections
from test_writing_generation import REVIEW_OK, FakeLlm, catalog, run, store  # noqa: F401  (fixtures)
from test_writing_tutor import HEADERS, L23, env  # noqa: F401  (env is a fixture)

L4_CODES = [f"EE{n:02d}" for n in range(1, 19)]
REQUIRED = L4_CODES[:6]
PLAN = ["¿Qué son los recreos activos y por qué importan en tu escuela?",
        "¿Por qué algunos estudiantes no se mueven durante el recreo? Pensá en las causas.",
        "¿Qué consecuencias tiene para la salud y el ánimo pasar el recreo sentado?",
        "¿Qué acciones o soluciones puede proponer la escuela? Cerrá con una idea final."]
GUIDED = {
    "topic_es": "Los recreos activos en la escuela",
    "communicative_situation_es": ("La escuela organiza una semana de recreos activos. El comité de salud pide "
                                   "textos para el periódico mural. Escribí para tus compañeros de sexto grado."),
    "suggested_ideas_es": ["Juegos que se pueden hacer en el recreo.", "Beneficios de moverse en la escuela.",
                           "Espacios seguros para jugar."],
    "instructions_es": ["Escribí un texto expositivo de cuatro párrafos con al menos 200 palabras.",
                        "En la introducción presentá el tema y su importancia.",
                        "Usá dos párrafos de desarrollo: uno para las causas y otro para las consecuencias.",
                        "En la conclusión proponé acciones o soluciones.",
                        "Uní tus ideas con conectores como «además» o «por esta razón»."],
    "deliverable_description_es": "Un texto expositivo de cuatro párrafos: introducción, dos de desarrollo y "
                                  "conclusión.",
    "paragraph_plan_es": PLAN,
}
SECTIONS = {"plan": "Ideas: juegos, salud, ánimo, espacios.",
            "introduction": "Los recreos activos son importantes para todos.",
            "development_1": "Muchos estudiantes no se mueven porque no tienen juegos.",
            "development_2": "Por eso se cansan y se sienten tristes en clase.",
            "conclusion": "La escuela puede organizar juegos cada semana."}


def guided_exercise(exercise_id: str = "PE-L4-recreos-activos-0001") -> dict:
    """A valid L4 record as the generator assembles it: EE01-EE06 required, EE07-EE18 optional."""
    record = copy.deepcopy(L23["introduction_paragraph"])
    rubric = contracts.criteria()
    record.update(exercise_id=exercise_id, level="guided_composition", exercise_type="guided_composition",
                  target_criteria=L4_CODES, topic_es=GUIDED["topic_es"], scaffolding_es=PLAN,
                  instructions_es=GUIDED["instructions_es"])
    record["deliverable"].update(unit="paragraphs", min=4, max=4, words_target=200, evidence_mode="typed")
    record["evaluation"]["parameters"] = [
        {"criterion": c, "rubric_ref": f"MEP-RUBRICA-PE-2026#{c}", "applicability": "scored",
         **({"optional": True} if c not in REQUIRED else {})} for c in L4_CODES]
    record["provenance"]["curriculum_records"] = [
        {"workbook_code": c,
         "assertion_id": f"PNE2026-PRI-ESP-PE-B{rubric[c]['dimension']}-A{rubric[c]['rubric_number']}"}
        for c in L4_CODES]
    assert contracts.validate_exercise(record) == []
    return record


# ---------------------------------------------------------------- contracts

def test_optional_criteria_only_for_conventions_in_guided_composition():
    record = guided_exercise()
    core = copy.deepcopy(record)
    core["evaluation"]["parameters"][0]["optional"] = True  # EE01 is core
    assert any("may be optional" in e for e in contracts.validate_exercise(core))
    l2 = copy.deepcopy(L23["introduction_paragraph"])
    l2["evaluation"]["parameters"][0]["optional"] = True
    assert any("may be optional" in e for e in contracts.validate_exercise(l2))
    assert contracts.optional_criteria(record) == set(L4_CODES[6:])


def test_evaluation_requires_mandatory_criteria_and_allows_unscored_optional():
    record = guided_exercise()
    base = {"schema_version": "1.0", "evaluation_id": "EV-l4-0001", "exercise_id": record["exercise_id"],
            "submission": {"submission_id": "SUB-l4-0001", "evidence_mode": "typed", "word_count": 210,
                           "paragraph_count": 4, "submitted_at": "2026-10-25T10:00:00-06:00"},
            "evaluator": {"kind": "human", "role": "tutor"}, "status": "completed",
            "evaluated_at": "2026-10-25T11:00:00-06:00", "rubric_id": record["evaluation"]["rubric_id"],
            "rubric_sha256": record["evaluation"]["rubric_sha256"],
            "feedback_es": {"strengths": [], "improvements": []}}
    required = [{"criterion": c, "status": "scored", "points": 3} for c in REQUIRED]
    assert contracts.validate_evaluation({**base, "criterion_scores": required}, record) == []
    with_optional = required + [{"criterion": "EE09", "status": "scored", "points": 4}]
    assert contracts.validate_evaluation({**base, "criterion_scores": with_optional}, record) == []
    pending_optional = required + [{"criterion": "EE09", "status": "pending"}]
    assert any("only when scored" in e for e in contracts.validate_evaluation(
        {**base, "criterion_scores": pending_optional}, record))
    assert any("required target" in e for e in contracts.validate_evaluation(
        {**base, "criterion_scores": required[1:]}, record))


# ---------------------------------------------------------------- generation (scripted models)

def test_guided_generation_stores_plan_and_optional_conventions(catalog, store):
    fake = FakeLlm([GUIDED])
    outcome, _ = run(catalog, store, fake, level="L4", criteria=L4_CODES)
    assert outcome.status == "accepted", [a.reasons for a in outcome.attempts]
    exercise = outcome.exercise
    assert exercise["scaffolding_es"] == PLAN and exercise["target_criteria"] == L4_CODES
    assert contracts.optional_criteria(exercise) == set(L4_CODES[6:])
    assert exercise["deliverable"] == {**exercise["deliverable"], "unit": "paragraphs", "min": 4, "max": 4,
                                       "words_target": 200, "evidence_mode": "typed"}
    prompt, review = fake.prompts
    assert "paragraph_plan_es" in prompt and "EE06" in prompt and "EE07" not in prompt  # optional not prompted
    assert "EE07" not in review and PLAN[1] in review
    [row] = store.generation_attempts()
    assert row["prompt_version"] == "writing-1.3" and {c["id"] for c in row["checks"]} >= {"W04", "W19"}


@pytest.mark.parametrize("plan,problem", [
    (PLAN[:3], "exactly 4"),
    ([PLAN[0], "Pensá en el recreo.", PLAN[2], PLAN[3]], "item 2 does not name"),
    ([PLAN[0], PLAN[1], PLAN[2], "Explicá las causas otra vez."], "item 4"),
])
def test_w19_rejects_bad_paragraph_plans(catalog, store, plan, problem):
    outcome, _ = run(catalog, store, FakeLlm([{**GUIDED, "paragraph_plan_es": plan}]), level="L4",
                     criteria=L4_CODES)
    assert outcome.status == "rejected"
    assert any(r.startswith("W19") and problem in r for a in outcome.attempts for r in a.reasons)


def test_l2_prompt_has_no_paragraph_plan(catalog):
    g = generation.build_grounding(catalog, "PNE2026-SUM-v1.0", "L2", "medium", ["EE03", "EE04"])
    assert "paragraph_plan_es" not in generation.generation_messages(g, [])[1]["content"]


# ---------------------------------------------------------------- student workflow

@pytest.fixture()
def guided(env):
    student, store, url = env
    record = guided_exercise()
    store.add_exercise(record)
    return student, store, url, record


def test_exercise_view_offers_five_stages_without_rubric_content(guided):
    student, _, _, record = guided
    data = student.get(f"/api/writing/exercises/{record['exercise_id']}").json()
    stages = data["guided"]["stages"]
    assert [s["key"] for s in stages] == ["plan", "introduction", "development", "conclusion", "review"]
    assert [s["plan_es"] for s in stages] == [[], [PLAN[0]], [PLAN[1], PLAN[2]], [PLAN[3]], []]
    assert stages[2]["sections"] == ["development_1", "development_2"] and data["draft"] is None
    body = str(data)
    assert "EE0" not in body and "rúbrica" not in body and "puntos" not in body


def test_sections_are_saved_resumed_and_assembled_on_submission(guided):
    student, store, _, record = guided
    url = f"/api/writing/exercises/{record['exercise_id']}"
    partial = {"plan": "Mis ideas.", "introduction": "Primera parte."}
    saved = student.put(f"{url}/draft", json={"sections": partial}).json()
    assert saved["word_count"] == 2  # only paragraphs count; the plan does not
    draft = student.get(url).json()["draft"]
    assert draft["sections"] == {**dict.fromkeys(SECTIONS, ""), **partial} and draft["text"] == "Primera parte."
    assert student.put(f"{url}/draft", json={"text": "sin partes"}).json()["error"] == "sections_required"

    missing = student.post(f"{url}/submit", json={"sections": partial, "client_request_id": str(uuid.uuid4())})
    assert missing.status_code == 422 and "Desarrollo 1" in missing.json()["message_es"]
    split = student.post(f"{url}/submit", json={"sections": {**SECTIONS, "conclusion": "Uno.\n\nDos."},
                                                 "client_request_id": str(uuid.uuid4())})
    assert split.status_code == 422 and split.json()["error"] == "blank_line_in_paragraph"

    request_id = str(uuid.uuid4())
    first = student.post(f"{url}/submit", json={"sections": SECTIONS, "client_request_id": request_id}).json()
    again = student.post(f"{url}/submit", json={"sections": {**SECTIONS, "conclusion": "Otra."},
                                                 "client_request_id": str(uuid.uuid4())}).json()
    assert first["created"] and not again["created"] and first["status_es"] == "Pendiente de revisión del tutor"
    sub = store.submission(record["exercise_id"])
    assert sub["text_es"] == "\n\n".join(SECTIONS[k] for k in ("introduction", "development_1", "development_2",
                                                                "conclusion"))
    assert sub["sections"] == SECTIONS and "Ideas:" not in sub["text_es"]  # plan kept apart
    assert (sub["paragraph_count"], sub["exercise_revision"]) == (4, 1)
    assert sub["text_es"] == assemble_sections(SECTIONS)
    assert student.put(f"{url}/draft", json={"sections": SECTIONS}).json()["error"] == "already_submitted"


# ---------------------------------------------------------------- tutor and progress

def test_tutor_sees_sections_and_completes_with_mandatory_criteria_only(guided):
    student, _, _, record = guided
    student.post(f"/api/writing/exercises/{record['exercise_id']}/submit",
                 json={"sections": SECTIONS, "client_request_id": str(uuid.uuid4())})
    pending = student.get("/api/writing/progress").json()
    rows = {r["code"]: r for r in pending["criteria"]}
    assert {c for c, r in rows.items() if r["status"] == "pending"} == set(REQUIRED)  # optional never pending

    sid = student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"][0]["submission_id"]
    detail = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()
    assert [s["key"] for s in detail["sections"]] == ["plan", "introduction", "development_1", "development_2",
                                                      "conclusion"]
    assert detail["sections"][0]["text_es"] == SECTIONS["plan"] and detail["exercise"]["scaffolding_es"] == PLAN
    assert detail["student_text"].count("\n\n") == 3
    optional = {c["code"] for c in detail["criteria"] if c["optional"]}
    assert optional == set(L4_CODES[6:])
    for c in detail["criteria"]:
        assert c["descriptors_es"] == contracts.criteria()[c["code"]]["descriptors_es"]

    url = f"/api/tutor/submissions/{sid}/evaluation"
    incomplete = student.put(url, json={"scores": {c: 3 for c in REQUIRED[:5]}, "complete": True}, headers=HEADERS)
    assert incomplete.json()["error"] == "incomplete"
    scores = {**{c: 3 for c in REQUIRED}, "EE01": 2, "EE09": 4, "EE10": None}
    done = student.put(url, json={"scores": scores, "complete": True, "strengths": ["Buen plan."]}, headers=HEADERS)
    assert done.json()["status"] == "completed"

    feedback = student.get(f"/api/writing/exercises/{record['exercise_id']}").json()["feedback"]
    assert len(feedback["scores"]) == 7 and feedback["strengths_es"] == ["Buen plan."]
    data = student.get("/api/writing/progress").json()
    rows = {r["code"]: r for r in data["criteria"]}
    assert (rows["EE01"]["latest_points"], rows["EE09"]["latest_points"], rows["EE10"]["status"]) == (2, 4,
                                                                                                    "unassessed")
    assert data["activity"]["levels"][3] == {**data["activity"]["levels"][3], "submitted": 1, "evaluated": 1}
    assert data["coverage"]["evaluated"] == 7 and data["coverage"]["pending"] == 0
    assert student.get("/api/dashboard").status_code == 200
