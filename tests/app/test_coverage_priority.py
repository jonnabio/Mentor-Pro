"""T067: composer-driven generation priority. mentor_pro_test, fake seeding runs or no LLM at all."""

from __future__ import annotations

import pytest

from app.practice import coverage, replenishment, seeding
from app.practice.replenishment import Policy
from conftest import SYNTHETIC
from test_bank_seeding import TARGET, factory, item, url  # noqa: F401  (fixture)
from test_generation import FakeLlm
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_replenishment import clean_requests

LEVELS = ("easy", "medium", "hard")


def entry(size, composes, objectives=None, levels=None):
    return {"size": size, "composes": composes, "objectives": objectives or {}, "levels": levels or {}}


def cov(held, mixed, single=None):
    single = single or {lv: {"size": 5, "composes": True} for lv in LEVELS}
    return {"held": held, "mixed": mixed, "single_level_size5": single}


CODES = ["M01", "M02", "M03", "M04", "M05"]


# ---------------------------------------------------------------- priority rules (pure)


def test_smallest_missing_size_comes_first_then_missing_then_single_level_then_larger_sizes():
    c = cov(held={"M01": {"easy": 3, "medium": 3, "hard": 2}, "M02": {"easy": 1}, "M04": {"medium": 2}},
            mixed=[entry(5, True), entry(10, True),
                   entry(15, False, {"M04": {"needed": 3, "held": 2}}, {"hard": {"needed": 4, "held": 2}}),
                   entry(20, False, {"M02": {"needed": 4, "held": 1}, "M04": {"needed": 4, "held": 2}})],
            single={"easy": {"size": 5, "composes": True},
                    "medium": {"size": 5, "composes": False, "objectives": {"M02": {"needed": 1, "held": 0}}},
                    "hard": {"size": 5, "composes": True}})
    out = coverage.priorities(c, CODES)
    assert out["M04"]["tier_name"] == "unblock_smallest_size" and out["M04"]["size"] == 15
    assert out["M04"]["levels"][0] == "hard"                      # the level the size is short of first
    assert {out["M03"]["tier"], out["M05"]["tier"]} == {2}       # no eligible question at all
    assert out["M02"]["tier_name"] == "single_level_coverage" and out["M02"]["levels"][0] == "medium"
    assert out["M01"]["tier_name"] == "depth"
    ranks = sorted(out, key=lambda k: out[k]["rank"])
    assert ranks == ["M04", "M03", "M05", "M02", "M01"]


def test_larger_size_tier_when_no_other_need():
    c = cov(held={code: {"easy": 2, "medium": 2, "hard": 2} for code in CODES},
            mixed=[entry(5, True), entry(10, False, {"M05": {"needed": 3, "held": 2}}),
                   entry(15, False, {"M01": {"needed": 4, "held": 2}})])
    out = coverage.priorities(c, CODES)
    assert out["M05"]["tier"] == 1 and out["M01"]["tier_name"] == "next_size" and out["M01"]["size"] == 15


def test_low_yield_objective_goes_last_within_its_tier_and_levels_avoid_low_yield():
    c = cov(held={}, mixed=[entry(5, False, {"M01": {"needed": 1, "held": 0}, "M02": {"needed": 1, "held": 0}})])
    yields = {("M01", lv): {"content_attempts": 3, "accepted": 0} for lv in LEVELS}
    yields[("M02", "hard")] = {"content_attempts": 4, "accepted": 0}
    out = coverage.priorities(c, ["M01", "M02"], yields)
    assert out["M02"]["rank"] < out["M01"]["rank"] and out["M01"]["low_yield"]
    assert out["M02"]["levels"][-1] == "hard"                    # a level with zero yield is tried last
    assert out["M02"]["levels"][0] == "easy"


def test_unblocking_prefers_easy_first_and_depth_builds_the_scarcest_level():
    c = cov(held={"M01": {"easy": 4, "medium": 4}, "M02": {"easy": 3, "medium": 3}},
            mixed=[entry(5, False, {"M03": {"needed": 1, "held": 0}})])
    out = coverage.priorities(c, ["M01", "M02", "M03"])
    assert out["M03"]["levels"] == ["easy", "medium", "hard"]     # tier 1, no level named
    assert out["M01"]["tier_name"] == "depth" and out["M01"]["levels"][0] == "hard"   # the subject has no hard


def test_level_only_shortage_names_every_objective_with_that_level():
    c = cov(held={code: {"easy": 5} for code in CODES},
            mixed=[entry(5, False, {}, {"medium": {"needed": 1, "held": 0}, "hard": {"needed": 1, "held": 0}})])
    out = coverage.priorities(c, CODES)
    assert all(o["tier"] == 1 and o["levels"][:2] == ["medium", "hard"] for o in out.values())


def test_reason_codes_are_stable():
    assert replenishment._reason_code("rubric 1 for ['distractor_quality', 'difficulty_match']") == \
        "rubric:distractor_quality,difficulty_match"
    assert replenishment._reason_code("generation exhausted: all candidate models failed") == "generation exhausted"


# ---------------------------------------------------------------- real composer on the test database


@pytest.fixture()
def db(url):
    clean_requests(url)
    yield url
    clean_requests(url)


def test_priority_uses_the_real_composer(db, catalog_conn):
    out = replenishment.priority(db, catalog_conn, SYNTHETIC, "matematicas")
    report = out["coverage"]
    assert report["available_mixed"] == [] and report["smallest_missing_mixed"] == 5
    first = report["mixed"][0]
    assert first["size"] == 5 and not first["composes"] and first["objectives"]
    tier1 = {c for c, p in out["order"].items() if p["tier"] == 1}
    assert tier1 == set(first["objectives"])                     # exactly what blocks size 5


# ---------------------------------------------------------------- run order, cap and second pass


class FakeSeed:
    """Stands in for seeding.run: per objective, calls spent and candidates generated per invocation."""

    def __init__(self, outcomes):
        self.outcomes, self.seen = outcomes, []

    def __call__(self, url, catalog, baseline, subject, llm_factory, max_calls, objective, prefer=None):
        self.seen.append((objective, max_calls, prefer))
        spend, made = self.outcomes.get(objective, (max_calls, 0))
        spent = min(spend, max_calls)
        return {"run": {"generated": made if spent else 0, "calls": spent,
                        "stop_reason": "run_call_limit" if spent >= max_calls else None}}


def fixed_order(monkeypatch, order):
    def fake(url, catalog, baseline, subject):
        return {"order": {code: {"tier": t, "tier_name": coverage.TIER_NAMES[t], "size": 5,
                                 "levels": ["medium", "easy", "hard"], "low_yield": False}
                          for code, t in order.items()}}
    monkeypatch.setattr(replenishment, "priority", fake)


def test_run_follows_priority_caps_each_objective_and_gives_leftovers_a_second_pass(db, catalog_conn, monkeypatch):
    fixed_order(monkeypatch, {"M03": 1, "M01": 4, "M02": 5})
    seed = FakeSeed({"M03": (50, 0), "M01": (2, 1), "M02": (50, 0)})
    out = replenishment.run(db, catalog_conn, SYNTHETIC, "matematicas", lambda: None, Policy(), 20,
                            seed_run=seed)
    assert [s[0] for s in seed.seen[:3]] == ["M03", "M01", "M02"]   # priority, not alphabetical
    assert [s[1] for s in seed.seen[:3]] == [5, 5, 5]               # no objective takes the whole run
    assert seed.seen[0][2] == ("medium", "easy", "hard")             # preferred level order reaches the seeder
    assert seed.seen[3] == ("M03", 8, ("medium", "easy", "hard"))    # leftover: capped, empty objective again
    assert out["calls"] == 20 and out["runs"][0]["tier_name"] == "unblock_smallest_size"
    assert out["runs"][3]["pass"] == 2


def test_a_run_never_exceeds_its_calls(db, catalog_conn, monkeypatch):
    fixed_order(monkeypatch, {"M01": 1, "M02": 1, "M03": 1})
    seed = FakeSeed({})
    out = replenishment.run(db, catalog_conn, SYNTHETIC, "matematicas", lambda: None, Policy(), 7, seed_run=seed)
    assert out["calls"] == 7 and [s[1] for s in seed.seen] == [5, 2]


def test_objective_calls_setting_is_bounded():
    assert Policy().objective_calls == 5
    assert Policy.from_env({"MENTOR_PRO_REPLENISH_OBJECTIVE_CALLS": "8"}).objective_calls == 8
    for bad in ("0", "51", "x"):
        with pytest.raises(replenishment.PolicyError):
            Policy.from_env({"MENTOR_PRO_REPLENISH_OBJECTIVE_CALLS": bad})


def test_seeder_prefer_generates_the_preferred_level_first(db, catalog_conn):
    plan = seeding.build_plan(catalog_conn, SYNTHETIC, "matematicas", TARGET)
    m01 = [c for c in plan if c["objective_code"] == "M01"]
    want = m01[-1]["difficulty"]                                  # the level plan order would reach last
    assert m01[0]["difficulty"] != want
    out = seeding.run(db, catalog_conn, SYNTHETIC, "matematicas", factory(db, FakeLlm([item(i) for i in range(10)])),
                      target=TARGET, max_calls=200, objective="M01", prefer=(want,))
    linked = seeding.links(db, out["batch_id"])
    first = min(linked, key=lambda r: r["linked_at"])
    assert {c["cell"]: c["difficulty"] for c in plan}[first["cell"]] == want
    assert {r["cell"] for r in linked} <= {c["cell"] for c in m01}  # only the objective's planned cells
