"""Question bank foundation (T047, ADR-034): fixed cell plan, adoption, gap-only seeding, locking, review gate."""

from __future__ import annotations

import copy

import psycopg
import pytest

from app.generation.pipeline import generate_one
from app.generation.store import GenerationStore
from app.llm.usage import MemoryUsageStore
from app.practice import seeding
from app.practice.bank import QuestionBank
from app.practice.store import PracticeStore
from conftest import SYNTHETIC
from test_generation import MATH_ITEM, FakeLlm, bundle, catalog_conn, client_for  # noqa: F401  (fixture)

# Synthetic Matemáticas: M01 (E1, E2), M02 (E1), M03 (E1). Target 6 gives the plan
# 1 M01-E1 easy, 2 M01-E2 medium, 3 M02-E1 hard, 4 M02-E1 easy, 5 M03-E1 medium, 6 M03-E1 hard.
TARGET = 6
SITUATIONS = [  # (stem, total, groups): distinct situations, so no two items are near duplicates
    "Una escuela reúne {t} cuadernos y los reparte por igual en {g} aulas. ¿Cuántos cuadernos recibe cada aula?",
    "En la feria se venden {t} empanadas en bolsas de {g} unidades. ¿Cuántas bolsas se llenan?",
    "Un grupo reparte {t} calcomanías en {g} sobres iguales. ¿Cuántas calcomanías lleva cada sobre?",
    "La biblioteca ordena {t} libros en {g} estantes con la misma cantidad. ¿Cuántos libros van por estante?",
    "Para el acto cívico se acomodan {t} sillas en {g} filas iguales. ¿Cuántas sillas tiene cada fila?",
    "Una finca empaca {t} naranjas en {g} cajas con igual cantidad. ¿Cuántas naranjas lleva cada caja?",
    "El comedor sirve {t} galletas en {g} bandejas iguales. ¿Cuántas galletas hay en cada bandeja?",
    "Un club reparte {t} camisetas entre {g} equipos por igual. ¿Cuántas camisetas recibe cada equipo?",
    "La cooperativa reparte {t} sacos de café entre {g} camiones por igual. ¿Cuántos sacos lleva cada camión?",
    "Una tienda acomoda {t} botellas en {g} refrigeradoras iguales. ¿Cuántas botellas caben en cada una?",
]
NUMBERS = [(144, 6), (96, 4), (250, 5), (168, 7), (216, 9), (120, 8), (132, 4), (225, 3), (180, 6), (336, 7)]


def item(index: int) -> dict:
    total, groups = NUMBERS[index]
    answer = total // groups
    out = copy.deepcopy(MATH_ITEM)
    out["stem"] = SITUATIONS[index].format(t=total, g=groups)
    out["options"] = [{"label": "A", "text": str(answer - 3)}, {"label": "B", "text": str(answer)},
                      {"label": "C", "text": str(answer + 2)}, {"label": "D", "text": str(total - groups)}]
    out["explanation"] = f"Se divide {total} entre {groups} y se obtiene {answer}."
    out["subject_checks"] = {"math": {"expression": f"{total} / {groups}"}}
    return out


def clean(url):
    with psycopg.connect(url, autocommit=True) as conn:
        batches = "SELECT batch_id FROM generation.bank_batch WHERE baseline_version = %s"
        attempts = "SELECT request_id FROM generation.question_attempt WHERE baseline_version = %s"
        conn.execute(f"DELETE FROM generation.bank_item_review WHERE request_id IN ({attempts})", (SYNTHETIC,))
        conn.execute(f"DELETE FROM generation.bank_review_sample WHERE batch_id IN ({batches})", (SYNTHETIC,))
        conn.execute(f"DELETE FROM generation.bank_batch_item WHERE batch_id IN ({batches})", (SYNTHETIC,))
        conn.execute("DELETE FROM generation.bank_batch WHERE baseline_version = %s", (SYNTHETIC,))
        conn.execute(f"DELETE FROM generation.bank_revalidation WHERE request_id IN ({attempts})", (SYNTHETIC,))
        conn.execute("DELETE FROM generation.question_attempt WHERE baseline_version = %s "
                     "AND (practice_set_id IS NULL OR practice_set_id LIKE 'seed-%%')", (SYNTHETIC,))


@pytest.fixture()
def url(synthetic_client):
    url, _ = synthetic_client.app.state.catalog_target
    PracticeStore(url)  # practice.item, read by QuestionBank (fresh CI database)
    QuestionBank(url)  # ensure tables
    clean(url)
    yield url
    clean(url)


def factory(url, fake):
    return lambda: (client_for(fake), MemoryUsageStore(), GenerationStore(url))


def seed_run(url, conn, fake=None, max_calls=200):
    return seeding.run(url, conn, SYNTHETIC, "matematicas", factory(url, fake or FakeLlm([item(i) for i in range(10)])),
                       target=TARGET, max_calls=max_calls)


def store_accepted(url, conn, code, ordinal, content, difficulty, practice_set_id=None, slot=None):
    outcome = generate_one(client_for(FakeLlm([content])), MemoryUsageStore(), bundle(conn, "matematicas", code, ordinal),
                           difficulty)
    assert outcome.status == "accepted", outcome.reasons
    GenerationStore(url).add(outcome, SYNTHETIC, difficulty, "test", practice_set_id=practice_set_id, slot=slot)
    return outcome.request_id


def eligible(url, conn, cell, include_held=False):
    ordinal = {"E1": 1, "E2": 2}
    plan = seeding.build_plan(conn, SYNTHETIC, "matematicas", TARGET)[cell - 1]
    return QuestionBank(url).eligible(conn, SYNTHETIC, "matematicas", plan["objective_code"],
                                      ordinal[plan["evidence_id"][-2:]], plan["evidence_id"], plan["difficulty"],
                                      include_held=include_held)


# ---------------------------------------------------------------- plan, coverage, gap-only seeding

def test_plan_is_fixed_and_gaps_are_reported_without_substitution(url, catalog_conn):
    out = seed_run(url, catalog_conn, max_calls=0)
    plan = [(c["objective_code"], c["evidence_id"][-2:], c["difficulty"]) for c in out["coverage"]["cells"]]
    assert plan == [("M01", "E1", "easy"), ("M01", "E2", "medium"), ("M02", "E1", "hard"),
                    ("M02", "E1", "easy"), ("M03", "E1", "medium"), ("M03", "E1", "hard")]
    assert out["run"] == {"adopted": 0, "generated": 0, "calls": 0, "stop_reason": "run_call_limit", "status": "open"}
    assert out["inventory"]["validated"] == 0 and out["coverage"]["gap_cells"] == TARGET
    assert {r["key"]: r["planned"] for r in out["coverage"]["by_objective"]} == {"M01": 2, "M02": 2, "M03": 2}
    assert {r["key"]: r["planned"] for r in out["coverage"]["by_difficulty"]} == {"easy": 2, "medium": 2, "hard": 2}
    assert out["coverage"]["unplanned_objectives"] == [] and out["coverage"]["unplanned_evidencias"] == []
    assert out["readiness"]["review_status"] == "pending"
    assert seed_run(url, catalog_conn, max_calls=0)["batch_id"] == out["batch_id"]  # resumed, plan unchanged


def test_generation_fills_every_exact_cell_and_holds_new_questions(url, catalog_conn):
    out = seed_run(url, catalog_conn)
    assert out["run"]["generated"] == TARGET and out["run"]["status"] == "filled" and out["status"] == "filled"
    assert out["inventory"] == {"validated": 6, "target": 6, "adopted": 0, "generated": 6, "held_from_practice": 6,
                                "seen_by_student": 0, "deactivated": 0}
    assert all(r["filled"] == r["planned"] for r in out["coverage"]["by_evidencia"])
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            """SELECT bi.cell, q.objective_code, q.evidence_id, q.difficulty, q.practice_set_id, q.slot
               FROM generation.bank_batch_item bi JOIN generation.question_attempt q USING (request_id)
               WHERE bi.batch_id = %s ORDER BY bi.cell""", (out["batch_id"],)).fetchall()
    for (cell, code, evidence, difficulty, set_id, slot), planned in zip(rows, out["coverage"]["cells"]):
        assert (code, evidence, difficulty) == (planned["objective_code"], planned["evidence_id"],
                                                planned["difficulty"])
        assert set_id.startswith(f"seed-{out['batch_id']}-") and slot == cell
    assert eligible(url, catalog_conn, 1) == []                    # held from practices until review passes
    assert len(eligible(url, catalog_conn, 1, include_held=True)) == 1


def test_budget_stop_then_resume_generates_only_the_gaps(url, catalog_conn):
    fake = FakeLlm([item(i) for i in range(10)])
    first = seed_run(url, catalog_conn, fake, max_calls=4)
    assert first["run"]["stop_reason"] == "run_call_limit" and first["run"]["calls"] <= 4
    filled_before = {c["cell"]: c["request_id"] for c in first["coverage"]["cells"] if c["status"] == "filled"}
    assert 0 < len(filled_before) < TARGET
    second = seed_run(url, catalog_conn, fake)
    assert second["run"]["generated"] == TARGET - len(filled_before) and second["status"] == "filled"
    after = {c["cell"]: c["request_id"] for c in second["coverage"]["cells"]}
    assert all(after[c] == r for c, r in filled_before.items())    # earlier links untouched
    assert len(set(after.values())) == TARGET


def test_adoption_takes_only_eligible_exact_cell_non_duplicate_unquarantined_questions(url, catalog_conn):
    good = store_accepted(url, catalog_conn, "M01", 1, item(0), "easy")       # cell 1
    duplicate = store_accepted(url, catalog_conn, "M02", 1, item(0), "hard")  # cell 3, near duplicate of `good`
    wrong_cell = store_accepted(url, catalog_conn, "M01", 1, item(1), "hard")  # no M01-E1 hard cell
    quarantined = store_accepted(url, catalog_conn, "M03", 1, item(2), "medium")  # cell 5
    seeding.quarantine(url, quarantined, "ambiguous")
    other_seeder = store_accepted(url, catalog_conn, "M02", 1, item(3), "easy", "seed-bb-other-1", 4)  # cell 4
    out = seed_run(url, catalog_conn, max_calls=0)
    linked = {c["cell"]: (c["request_id"], c["origin"]) for c in out["coverage"]["cells"] if c["status"] == "filled"}
    assert linked == {1: (good, "adopted")} and out["run"]["adopted"] == 1
    assert {duplicate, wrong_cell, quarantined, other_seeder}.isdisjoint(r for r, _ in linked.values())
    assert eligible(url, catalog_conn, 1)[0]["request_id"] == good  # adopted bank questions stay servable


# ---------------------------------------------------------------- locking and recovery

def test_a_competing_run_is_refused_immediately(url, catalog_conn):
    with seeding.SeedLock(url, SYNTHETIC, "matematicas"):
        with pytest.raises(seeding.SeedBusy):
            seed_run(url, catalog_conn, max_calls=0)
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT count(*) FROM generation.bank_batch WHERE baseline_version = %s",
                            (SYNTHETIC,)).fetchone()[0] == 0
    with seeding.SeedLock(url, SYNTHETIC, "ciencias"):  # the lock is per subject
        assert seed_run(url, catalog_conn, max_calls=0)["status"] == "open"


def test_a_crashed_run_releases_the_lock_and_its_unlinked_output_is_recovered(url, catalog_conn):
    batch_id = seed_run(url, catalog_conn, max_calls=0)["batch_id"]
    crashed = seeding.SeedLock(url, SYNTHETIC, "matematicas").__enter__()
    orphan = store_accepted(url, catalog_conn, "M01", 1, item(4), "easy", f"seed-{batch_id}-dead01", 1)
    crashed.conn.close()  # process died: the connection ends without unlocking
    out = seed_run(url, catalog_conn, max_calls=0)
    cell1 = out["coverage"]["cells"][0]
    assert (cell1["request_id"], cell1["origin"]) == (orphan, "generated") and out["run"]["adopted"] == 1


def test_lock_loss_stops_the_run_before_any_further_write(url, catalog_conn):
    def kill_lock_then_factory():
        with psycopg.connect(url, autocommit=True) as conn:  # the lock connection is terminated mid-run
            conn.execute("""SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory'
                            AND classid::bigint = %s AND objsubid = 2""", (seeding.LOCK_NAMESPACE,))
        return factory(url, FakeLlm([item(i) for i in range(10)]))()

    with pytest.raises(seeding.LockLost):
        seeding.run(url, catalog_conn, SYNTHETIC, "matematicas", kill_lock_then_factory, target=TARGET)
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT count(*) FROM generation.bank_batch_item bi JOIN generation.bank_batch b "
                            "USING (batch_id) WHERE b.baseline_version = %s", (SYNTHETIC,)).fetchone()[0] == 0


def test_database_constraints_reject_double_links_and_a_second_current_batch(url, catalog_conn):
    out = seed_run(url, catalog_conn)
    extra = store_accepted(url, catalog_conn, "M01", 1, item(9), "easy")
    with psycopg.connect(url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO generation.bank_batch_item (batch_id, cell, request_id, origin) "
                         "VALUES (%s, 1, %s, 'adopted')", (out["batch_id"], extra))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO generation.bank_batch (batch_id, baseline_version, subject, target, plan, "
                         "status, review_seed) VALUES ('bb-x', %s, 'matematicas', 6, '[]', 'open', 's')", (SYNTHETIC,))


# ---------------------------------------------------------------- educational review gate

def test_sampling_is_reproducible_and_spread_over_difficulties():
    cells = list(range(1, 31))
    difficulty = {c: ("easy", "medium", "hard")[(c - 1) % 3] for c in cells}
    first = seeding.draw_sample(cells, difficulty, "bb-x:seed")
    assert first == seeding.draw_sample(cells, difficulty, "bb-x:seed") and len(first) == 10
    assert [difficulty[c] for c in first].count("easy") >= 3 and len(set(first)) == 10
    assert first != seeding.draw_sample(cells, difficulty, "bb-y:seed")


def decide(rows, quarantine=()):
    return [{"request_id": r["request_id"], "verdict": "quarantined" if r["cell"] in quarantine else "approved",
             "reason": "wrong_key" if r["cell"] in quarantine else ""} for r in rows]


def test_review_gate_quarantines_reviews_the_replacement_and_keeps_all_evidence(url, catalog_conn):
    batch_id = seed_run(url, catalog_conn, FakeLlm([item(i) for i in range(6)]))["batch_id"]
    with pytest.raises(seeding.SeedError):
        seeding.review_record(url, batch_id, [{"request_id": "req-none", "verdict": "approved"}])
    round1 = seeding.review_sample(url, batch_id)
    assert len(round1) == TARGET and {r["round"] for r in round1} == {1}
    export = seeding.review_export(url, catalog_conn, batch_id)
    assert len(export["questions"]) == TARGET and export["questions"][0]["answer_key"] == "B"
    rejected = next(r for r in round1 if r["cell"] == 2)["request_id"]
    state = seeding.review_record(url, batch_id, decide(round1, quarantine={2}))
    assert state["review_status"] == "pending" and state["quarantined"] == 1
    assert seeding.get_batch(url, batch_id)["status"] == "open"           # cell 2 reopened as a gap
    assert eligible(url, catalog_conn, 2, include_held=True) == []          # quarantined is never eligible
    with pytest.raises(seeding.SeedError):
        seeding.review_sample(url, batch_id)                                # not filled until replaced

    refill = seed_run(url, catalog_conn, FakeLlm([item(7)]))
    assert refill["run"]["generated"] == 1, refill["run"]
    assert refill["inventory"]["deactivated"] == 1
    round2 = seeding.review_sample(url, batch_id)
    assert [(r["round"], r["cell"]) for r in round2] == [(2, 2)] and round2[0]["request_id"] != rejected
    assert seeding.review_record(url, batch_id, decide(round2))["review_status"] == "passed"
    assert len(eligible(url, catalog_conn, 1)) == 1                         # released to practices

    samples = seeding._samples(url, batch_id)
    assert next(s for s in samples if s["request_id"] == rejected)["verdict"] == "quarantined"
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT count(*) FROM generation.bank_item_review WHERE batch_id = %s",
                            (batch_id,)).fetchone()[0] == TARGET + 1
        assert conn.execute("SELECT active FROM generation.bank_batch_item WHERE request_id = %s",
                            (rejected,)).fetchone()[0] is False


def test_three_quarantined_sample_questions_fail_the_batch(url, catalog_conn):
    batch_id = seed_run(url, catalog_conn)["batch_id"]
    rows = seeding.review_sample(url, batch_id)
    assert seeding.review_record(url, batch_id, decide(rows, quarantine={1, 3, 5}))["review_status"] == "failed"
    with pytest.raises(seeding.SeedError):
        seeding.review_sample(url, batch_id)
    assert eligible(url, catalog_conn, 2) == []  # still held: a failed batch is never released


def test_review_decisions_are_all_or_nothing(url, catalog_conn):
    batch_id = seed_run(url, catalog_conn)["batch_id"]
    rows = seeding.review_sample(url, batch_id)
    bad = decide(rows)
    bad[-1]["verdict"], bad[-1]["reason"] = "quarantined", "not-a-reason"
    with pytest.raises(seeding.SeedError):
        seeding.review_record(url, batch_id, bad)
    assert seeding.review_state(url, batch_id)["unreviewed"] == TARGET


def test_a_quarantine_after_release_holds_the_batch_until_the_replacement_is_reviewed(url, catalog_conn):
    batch_id = seed_run(url, catalog_conn, FakeLlm([item(i) for i in range(6)]))["batch_id"]
    rows = seeding.review_sample(url, batch_id)
    assert seeding.review_record(url, batch_id, decide(rows))["review_status"] == "passed"
    assert len(eligible(url, catalog_conn, 4)) == 1
    found_later = next(r for r in rows if r["cell"] == 4)["request_id"]
    seeding.quarantine(url, found_later, "level")                   # found after release, outside a round
    assert seeding.get_batch(url, batch_id)["review_status"] == "pending"
    assert eligible(url, catalog_conn, 1) == []                     # generated questions held again
    seed_run(url, catalog_conn, FakeLlm([item(8)]))
    replacement = seeding.review_sample(url, batch_id)
    assert [(r["round"], r["cell"]) for r in replacement] == [(2, 4)]
    assert seeding.review_record(url, batch_id, decide(replacement))["review_status"] == "passed"
    assert eligible(url, catalog_conn, 4)[0]["request_id"] == replacement[0]["request_id"]
