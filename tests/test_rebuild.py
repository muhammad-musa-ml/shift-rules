import unittest

from shiftrules import synth
from shiftrules.check import check
from shiftrules.engine import build, rebuild
from shiftrules.model import Assignment, load_roster, load_rules

from tests.fixtures import A, make


def base_scenario(seed=1):
    doc = synth.roster_doc(seed)
    roster = load_roster(doc)
    rules_doc = synth.rules_doc(seed, doc)
    return roster, rules_doc, load_rules(rules_doc, roster)


class RebuildTests(unittest.TestCase):
    def test_unchanged_rules_change_nothing(self):
        roster, _, rules = base_scenario()
        old = build(roster, rules, seed=1).assignments
        out = rebuild(roster, rules, old, seed=1)
        self.assertEqual(out.removed, [])
        self.assertEqual(out.added, [])
        self.assertEqual(out.assignments, old)

    def test_new_time_off_moves_only_that_providers_shifts_that_day(self):
        roster, rules_doc, rules = base_scenario()
        old = build(roster, rules, seed=1).assignments
        victim = next(a for a in old if a.day == 10)
        theirs = [a for a in old if a.provider == victim.provider and a.day == 10]
        date = roster.date_of(10).isoformat()
        new_rules = load_rules(rules_doc + [
            {"id": "new-off", "kind": "unavailable", "provider": victim.provider, "dates": [date]},
        ], roster)

        out = rebuild(roster, new_rules, old, seed=1)

        self.assertEqual(sorted(a for a, _ in out.removed), sorted(theirs))
        self.assertTrue(all(why == "new-off" for _, why in out.removed))
        self.assertEqual(len(out.added), len(theirs))
        self.assertTrue(all(a.provider != victim.provider for a, _ in out.added))
        self.assertTrue(all(why in {"cover-2-everywhere", "cover-peds-A-days"} for _, why in out.added))
        kept = set(old) - set(theirs)
        self.assertTrue(kept <= set(out.assignments))
        self.assertEqual(out.unfilled, [])
        self.assertEqual(check(roster, new_rules, out.assignments), [])

    def test_a_long_run_loses_one_assignment_not_the_whole_run(self):
        roster, rules = make([{"id": "run", "kind": "max_consecutive_days", "max": 5}])
        old = [A("p1", d) for d in range(7)]
        out = rebuild(roster, rules, old)
        self.assertEqual(len(out.removed), 1)
        self.assertEqual(out.removed[0][1], "run")
        self.assertEqual(check(roster, rules, out.assignments), [])
        self.assertEqual(len(out.assignments), 6)

    def test_a_short_rest_loses_the_later_shift(self):
        roster, rules = make([{"id": "rest", "kind": "min_rest_hours", "hours": 11}])
        out = rebuild(roster, rules, [A("p1", 0, "day"), A("p1", 0, "night")])
        self.assertEqual(out.removed, [(A("p1", 0, "night"), "rest")])

    def test_duplicates_and_unknown_names_are_reported_not_dropped_quietly(self):
        roster, rules = make([])
        old = [A("p1", 0), A("p1", 0), Assignment("zz", 0, "day", "A")]
        out = rebuild(roster, rules, old)
        self.assertEqual(
            sorted(why for _, why in out.removed), ["builtin:duplicate", "builtin:unknown"])
        self.assertEqual(out.assignments, [A("p1", 0)])

    def test_when_nobody_can_take_the_shift_it_is_reported(self):
        roster, rules = make([
            {"id": "cov", "kind": "coverage", "count": 1, "dates": ["2026-01-05"], "shift": "day",
             "site": "A"},
            {"id": "off", "kind": "unavailable", "provider": ["p1", "p2", "p3"], "dates": ["2026-01-05"]},
        ])
        out = rebuild(roster, rules, [A("p1", 0)])
        self.assertEqual(out.removed, [(A("p1", 0), "off")])
        self.assertEqual(out.assignments, [])
        self.assertEqual(len(out.unfilled), 1)
        self.assertEqual(out.unfilled[0].blocked_by, {"off": 3})


if __name__ == "__main__":
    unittest.main()
