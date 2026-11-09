import datetime as dt
import random
import unittest

from shiftrules.check import check
from shiftrules.engine import State, build
from shiftrules.model import Assignment, load_roster, load_rules

from tests.fixtures import A, make

PIDS = ["p1", "p2", "p3", "p4", "p5", "p6"]
DATES = [(dt.date(2026, 1, 5) + dt.timedelta(days=i)).isoformat() for i in range(14)]


def random_roster():
    return load_roster({
        "start": "2026-01-05",
        "days": 14,
        "shifts": {"day": {"start": 7, "hours": 12}, "night": {"start": 19, "hours": 12}},
        "sites": ["A", "B"],
        "providers": [
            {"id": "p1", "sites": ["A", "B"]}, {"id": "p2", "sites": ["A", "B"]},
            {"id": "p3", "sites": ["A"]}, {"id": "p4", "sites": ["B"]},
            {"id": "p5", "sites": ["A", "B"]}, {"id": "p6", "sites": ["A"]},
        ],
    })


def random_rule_docs(rnd):
    docs = []
    for i in range(rnd.randint(4, 7)):
        kind = rnd.choice(["unavailable", "max_per_window", "min_rest_hours", "max_consecutive_days"])
        doc = {"id": "r%d" % i, "kind": kind}
        if kind == "unavailable":
            doc["provider"] = rnd.choice(PIDS)
            doc["dates"] = rnd.sample(DATES, 4)
            if rnd.random() < 0.5:
                doc["shift"] = rnd.choice(["day", "night"])
        elif kind == "max_per_window":
            doc["max"] = rnd.randint(0, 3)
            doc["window_days"] = rnd.randint(2, 7)
            if rnd.random() < 0.5:
                doc["shift"] = rnd.choice(["day", "night"])
            if rnd.random() < 0.3:
                doc["site"] = rnd.choice(["A", "B"])
            if rnd.random() < 0.3:
                doc["weekdays"] = rnd.sample(range(7), 3)
        elif kind == "min_rest_hours":
            doc["hours"] = rnd.randint(0, 14)
        else:
            doc["max"] = rnd.randint(1, 4)
            if rnd.random() < 0.5:
                doc["shift"] = rnd.choice(["day", "night"])
        if kind != "unavailable" and rnd.random() < 0.3:
            doc["provider"] = rnd.sample(PIDS, 2)
        docs.append(doc)
    return docs


class BlockedByTests(unittest.TestCase):
    def test_each_kind_names_its_rule(self):
        roster, rules = make([
            {"id": "off", "kind": "unavailable", "provider": "p2", "dates": ["2026-01-09"]},
            {"id": "cap", "kind": "max_per_window", "max": 1, "window_days": 3, "provider": "p1"},
            {"id": "rest", "kind": "min_rest_hours", "hours": 11, "provider": "p3"},
            {"id": "run", "kind": "max_consecutive_days", "max": 1, "provider": ["p2"]},
        ])
        s = State(roster, rules)
        self.assertEqual(s.blocked_by("p2", 4, "day", "A"), "off")
        s.add(A("p1", 0))
        self.assertEqual(s.blocked_by("p1", 2, "day", "A"), "cap")
        self.assertIsNone(s.blocked_by("p1", 3, "day", "A"))
        s.add(A("p3", 0, "day"))
        self.assertEqual(s.blocked_by("p3", 0, "night", "A"), "rest")
        s.add(A("p2", 5))
        self.assertEqual(s.blocked_by("p2", 6, "day", "A"), "run")

    def test_builtins_come_before_rules(self):
        roster, rules = make([{"id": "off", "kind": "unavailable", "provider": "p3"}])
        s = State(roster, rules)
        self.assertEqual(s.blocked_by("p3", 0, "day", "B"), "builtin:credentialed")
        s.add(A("p1", 0))
        self.assertEqual(s.blocked_by("p1", 0, "day", "A"), "builtin:duplicate")
        self.assertEqual(s.blocked_by("p1", 0, "day", "B"), "builtin:overlap")


class AgreementTests(unittest.TestCase):
    """The builder's incremental test and the checker are written separately.
    For any attempted assignment they have to agree: if the builder accepts it
    the checker finds nothing wrong with the schedule that results, and if the
    builder refuses it the checker finds the rule the builder named."""

    def test_builder_and_checker_agree_on_random_rules(self):
        accepted = refused = 0
        for seed in range(60):
            rnd = random.Random(seed)
            roster = random_roster()
            rules = load_rules(random_rule_docs(rnd), roster)
            state = State(roster, rules)
            current = []
            for attempt in range(150):
                a = Assignment(rnd.choice(PIDS), rnd.randrange(14),
                               rnd.choice(["day", "night"]), rnd.choice(["A", "B"]))
                why = state.blocked_by(a.provider, a.day, a.shift, a.site)
                broken = [v for v in check(roster, rules, current + [a]) if v.involved]
                where = "seed %d attempt %d %r" % (seed, attempt, a)
                if why is None:
                    self.assertEqual(broken, [], where)
                    state.add(a)
                    current.append(a)
                    accepted += 1
                else:
                    self.assertIn(why, {v.rule for v in broken}, where)
                    refused += 1
        self.assertGreater(accepted, 500)
        self.assertGreater(refused, 500)


class BuildTests(unittest.TestCase):
    def test_fills_every_cell_and_the_checker_agrees(self):
        roster, rules = make([
            {"id": "cov", "kind": "coverage", "count": 1, "site": "A"},
            {"id": "rest", "kind": "min_rest_hours", "hours": 11},
            {"id": "run", "kind": "max_consecutive_days", "max": 5},
        ])
        result = build(roster, rules, seed=1)
        self.assertEqual(result.unfilled, [])
        self.assertEqual(check(roster, rules, result.assignments), [])
        self.assertEqual(len(result.assignments), 14 * 2)

    def test_same_seed_gives_the_same_schedule(self):
        roster, rules = make([{"id": "cov", "kind": "coverage", "count": 1}])
        self.assertEqual(build(roster, rules, seed=7).assignments, build(roster, rules, seed=7).assignments)

    def test_work_is_spread_across_providers(self):
        roster, rules = make([{"id": "cov", "kind": "coverage", "count": 1, "site": "A"}])
        loads = {}
        for a in build(roster, rules, seed=3).assignments:
            loads[a.provider] = loads.get(a.provider, 0) + 1
        self.assertLessEqual(max(loads.values()) - min(loads.values()), 1)

    def test_a_cell_nobody_can_cover_is_reported_with_the_reasons(self):
        roster, rules = make([
            {"id": "cov", "kind": "coverage", "count": 1, "dates": ["2026-01-06"]},
            {"id": "off", "kind": "unavailable", "provider": ["p1", "p2", "p3"], "dates": ["2026-01-06"]},
        ])
        result = build(roster, rules)
        self.assertEqual(len(result.unfilled), 4)  # 2 shifts x 2 sites
        by_cell = {(u.shift, u.site): u for u in result.unfilled}
        self.assertEqual(by_cell[("day", "A")].blocked_by, {"off": 3})
        self.assertEqual(by_cell[("day", "B")].blocked_by, {"off": 2, "builtin:credentialed": 1})
        self.assertEqual(result.assignments, [])

    def test_unfilled_matches_what_the_checker_sees(self):
        roster, rules = make([
            {"id": "cov", "kind": "coverage", "count": 2, "site": "A"},
            {"id": "off", "kind": "unavailable", "provider": "p1", "dates": DATES[:5]},
            {"id": "cap", "kind": "max_per_window", "max": 2, "window_days": 7},
        ])
        result = build(roster, rules, seed=2)
        self.assertGreater(len(result.unfilled), 0)
        short = {(v.day, v.detail.split(": ")[0]) for v in check(roster, rules, result.assignments)
                 if not v.involved}
        reported = {(u.day, "%s %s %s" % (roster.date_of(u.day).isoformat(), u.shift, u.site))
                    for u in result.unfilled}
        self.assertEqual(short, reported)
        self.assertEqual([v for v in check(roster, rules, result.assignments) if v.involved], [])

    def test_skill_coverage_uses_only_providers_with_the_skill(self):
        roster, rules = make([
            {"id": "peds", "kind": "coverage", "count": 1, "skill": "peds", "shift": "day", "site": "A"},
        ])
        result = build(roster, rules)
        self.assertEqual({a.provider for a in result.assignments}, {"p1"})
        roster, rules = make([
            {"id": "peds", "kind": "coverage", "count": 1, "skill": "peds", "dates": ["2026-01-05"],
             "shift": "day", "site": "A"},
            {"id": "off", "kind": "unavailable", "provider": "p1", "dates": ["2026-01-05"]},
        ])
        result = build(roster, rules)
        self.assertEqual(result.unfilled[0].blocked_by, {"off": 1, "skill:peds": 2})

    def test_existing_assignments_are_kept_and_counted(self):
        roster, rules = make([{"id": "cov", "kind": "coverage", "count": 1, "site": "A", "dates": ["2026-01-05"]}])
        kept = [A("p3", 0, "day"), A("p2", 0, "night")]
        result = build(roster, rules, initial=kept)
        self.assertEqual(sorted(result.assignments), sorted(kept))
        self.assertEqual(result.filled_for, {})

    def test_two_rules_on_one_cell_share_the_assignment(self):
        roster, rules = make([
            {"id": "any", "kind": "coverage", "count": 1, "shift": "day", "site": "A", "dates": ["2026-01-05"]},
            {"id": "peds", "kind": "coverage", "count": 1, "skill": "peds", "shift": "day", "site": "A",
             "dates": ["2026-01-05"]},
        ])
        result = build(roster, rules)
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(result.assignments[0].provider, "p1")


if __name__ == "__main__":
    unittest.main()
