import unittest

from shiftrules.check import check
from shiftrules.model import Assignment, DocError, dump_schedule, load_schedule

from tests.fixtures import A, make


def ids(violations):
    return sorted(v.rule for v in violations)


class StructuralTests(unittest.TestCase):
    def test_clean_schedule(self):
        roster, rules = make([])
        self.assertEqual(check(roster, rules, [A("p1", 0), A("p2", 0, site="B"), A("p3", 1)]), [])

    def test_provider_at_a_site_they_are_not_credentialed_for(self):
        roster, rules = make([])
        found = check(roster, rules, [A("p3", 0, site="B")])
        self.assertEqual(ids(found), ["builtin:credentialed"])
        self.assertEqual(found[0].involved, (A("p3", 0, site="B"),))

    def test_two_places_at_once(self):
        roster, rules = make([])
        found = check(roster, rules, [A("p1", 0, site="A"), A("p1", 0, site="B")])
        self.assertEqual(ids(found), ["builtin:overlap"])

    def test_back_to_back_shifts_do_not_overlap(self):
        roster, rules = make([])
        self.assertEqual(check(roster, rules, [A("p1", 0, "day"), A("p1", 0, "night")]), [])

    def test_duplicate_assignment_is_reported_once_and_nothing_else(self):
        roster, rules = make([])
        found = check(roster, rules, [A("p1", 0), A("p1", 0)])
        self.assertEqual(ids(found), ["builtin:duplicate"])

    def test_names_the_roster_does_not_have_are_reported_not_raised(self):
        roster, rules = make([{"id": "r", "kind": "min_rest_hours", "hours": 8}])
        found = check(roster, rules, [
            Assignment("zz", 0, "day", "A"),
            Assignment("p1", 0, "swing", "A"),
            Assignment("p1", 0, "day", "Q"),
            Assignment("p1", 99, "day", "A"),
        ])
        self.assertEqual(ids(found), ["builtin:unknown"] * 4)

    def test_a_day_before_the_roster_starts_is_unknown(self):
        roster, rules = make([])
        self.assertEqual(ids(check(roster, rules, [Assignment("p1", -1, "day", "A")])),
                         ["builtin:unknown"])


class CoverageTests(unittest.TestCase):
    def test_short_cell_is_reported_with_the_count(self):
        roster, rules = make([{"id": "cov", "kind": "coverage", "count": 2, "shift": "night", "site": "A"}])
        found = check(roster, rules, [A("p1", 0, "night")])
        self.assertTrue(all(v.rule == "cov" for v in found))
        self.assertIn("2026-01-05 night A: 1 of 2", [v.detail for v in found])
        self.assertEqual(len(found), 14)  # every night of the 14 days is short or empty

    def test_filled_cell_is_clean(self):
        roster, rules = make(
            [{"id": "cov", "kind": "coverage", "count": 2, "shift": "night", "site": "A",
              "dates": ["2026-01-05"]}])
        self.assertEqual(check(roster, rules, [A("p1", 0, "night"), A("p2", 0, "night")]), [])

    def test_skill_counts_only_providers_who_have_it(self):
        roster, rules = make(
            [{"id": "peds", "kind": "coverage", "count": 2, "skill": "peds", "shift": "day",
              "site": "A", "dates": ["2026-01-05"]}])
        found = check(roster, rules, [A("p1", 0), A("p2", 0)])
        self.assertEqual(ids(found), ["peds"])
        self.assertIn("1 of 2 with skill peds", found[0].detail)

    def test_weekday_scope(self):
        roster, rules = make(
            [{"id": "mon", "kind": "coverage", "count": 1, "shift": "day", "site": "A",
              "weekdays": [0]}])
        days = [v.day for v in check(roster, rules, [])]
        self.assertEqual(days, [0, 7])


class UnavailableTests(unittest.TestCase):
    def test_assignment_on_a_blocked_date(self):
        roster, rules = make([{"id": "off", "kind": "unavailable", "provider": "p1",
                               "dates": ["2026-01-06"]}])
        self.assertEqual(ids(check(roster, rules, [A("p1", 1)])), ["off"])
        self.assertEqual(check(roster, rules, [A("p1", 2), A("p2", 1)]), [])

    def test_shift_scope(self):
        roster, rules = make([{"id": "nonights", "kind": "unavailable", "provider": "p1",
                               "shift": "night"}])
        self.assertEqual(check(roster, rules, [A("p1", 0, "day")]), [])
        self.assertEqual(ids(check(roster, rules, [A("p1", 0, "night")])), ["nonights"])


class WindowTests(unittest.TestCase):
    rule = {"id": "w", "kind": "max_per_window", "max": 2, "window_days": 3}

    def test_three_in_three_days(self):
        roster, rules = make([self.rule])
        found = check(roster, rules, [A("p1", 0), A("p1", 1), A("p1", 2)])
        self.assertEqual(ids(found), ["w"])
        self.assertEqual(len(found[0].involved), 3)

    def test_one_crowded_stretch_is_one_violation_however_many_windows_hold_it(self):
        roster, rules = make([{"id": "w", "kind": "max_per_window", "max": 2, "window_days": 7}])
        found = check(roster, rules, [A("p1", d) for d in (3, 4, 5)])
        self.assertEqual(len(found), 1)

    def test_window_edge(self):
        roster, rules = make([self.rule])
        self.assertEqual(check(roster, rules, [A("p1", 0), A("p1", 1), A("p1", 3)]), [])

    def test_exactly_the_maximum_is_allowed(self):
        roster, rules = make([{"id": "w", "kind": "max_per_window", "max": 1, "window_days": 3}])
        self.assertEqual(check(roster, rules, [A("p1", 0), A("p1", 3)]), [])
        self.assertEqual(ids(check(roster, rules, [A("p1", 0), A("p1", 2)])), ["w"])

    def test_only_scoped_assignments_count(self):
        roster, rules = make([{"id": "nights", "kind": "max_per_window", "max": 1,
                               "window_days": 3, "shift": "night"}])
        self.assertEqual(check(roster, rules, [A("p1", 0), A("p1", 1), A("p1", 2, "night")]), [])

    def test_provider_scope(self):
        roster, rules = make([{"id": "w", "kind": "max_per_window", "max": 1,
                               "window_days": 3, "provider": "p2"}])
        self.assertEqual(check(roster, rules, [A("p1", 0), A("p1", 1)]), [])
        self.assertEqual(ids(check(roster, rules, [A("p2", 0), A("p2", 1)])), ["w"])


class RestTests(unittest.TestCase):
    def test_day_then_night_has_no_gap(self):
        roster, rules = make([{"id": "rest", "kind": "min_rest_hours", "hours": 11}])
        found = check(roster, rules, [A("p1", 0, "day"), A("p1", 0, "night")])
        self.assertEqual(ids(found), ["rest"])
        self.assertIn("0h between", found[0].detail)

    def test_night_then_next_day_shift(self):
        roster, rules = make([{"id": "rest", "kind": "min_rest_hours", "hours": 11}])
        self.assertEqual(ids(check(roster, rules, [A("p1", 0, "night"), A("p1", 1, "day")])), ["rest"])

    def test_gap_equal_to_the_minimum_is_allowed(self):
        roster, rules = make([{"id": "rest", "kind": "min_rest_hours", "hours": 12}])
        self.assertEqual(check(roster, rules, [A("p1", 0, "day"), A("p1", 1, "day")]), [])
        roster, rules = make([{"id": "rest", "kind": "min_rest_hours", "hours": 13}])
        self.assertEqual(ids(check(roster, rules, [A("p1", 0, "day"), A("p1", 1, "day")])), ["rest"])

    def test_provider_scope(self):
        roster, rules = make([{"id": "rest", "kind": "min_rest_hours", "hours": 11, "provider": "p2"}])
        self.assertEqual(check(roster, rules, [A("p1", 0, "day"), A("p1", 0, "night")]), [])

    def test_overlap_is_not_also_reported_as_short_rest(self):
        roster, rules = make([{"id": "rest", "kind": "min_rest_hours", "hours": 11}])
        found = check(roster, rules, [A("p1", 0, site="A"), A("p1", 0, site="B")])
        self.assertEqual(ids(found), ["builtin:overlap"])


class ConsecutiveTests(unittest.TestCase):
    def test_run_longer_than_the_maximum(self):
        roster, rules = make([{"id": "run", "kind": "max_consecutive_days", "max": 3}])
        found = check(roster, rules, [A("p1", d) for d in range(4)])
        self.assertEqual(ids(found), ["run"])
        self.assertEqual(len(found[0].involved), 4)

    def test_run_equal_to_the_maximum_is_allowed(self):
        roster, rules = make([{"id": "run", "kind": "max_consecutive_days", "max": 3}])
        self.assertEqual(check(roster, rules, [A("p1", d) for d in range(3)]), [])

    def test_a_gap_breaks_the_run(self):
        roster, rules = make([{"id": "run", "kind": "max_consecutive_days", "max": 2}])
        self.assertEqual(check(roster, rules, [A("p1", d) for d in (0, 1, 3, 4)]), [])

    def test_two_shifts_on_one_day_are_one_day(self):
        roster, rules = make([{"id": "run", "kind": "max_consecutive_days", "max": 2}])
        self.assertEqual(check(roster, rules, [A("p1", 0, "day"), A("p1", 0, "night"), A("p1", 1, "night")]), [])

    def test_shift_scope(self):
        roster, rules = make([{"id": "run", "kind": "max_consecutive_days", "max": 2, "shift": "night"}])
        mixed = [A("p1", 0, "day"), A("p1", 1, "day"), A("p1", 2, "night"), A("p1", 3, "night")]
        self.assertEqual(check(roster, rules, mixed), [])
        nights = [A("p1", d, "night") for d in range(3)]
        self.assertEqual(ids(check(roster, rules, nights)), ["run"])


class ScheduleFileTests(unittest.TestCase):
    def test_round_trip(self):
        roster, _ = make([])
        assignments = [A("p2", 1, "night", "B"), A("p1", 0)]
        doc = dump_schedule(roster, assignments)
        self.assertEqual(doc["assignments"][0]["date"], "2026-01-05")
        self.assertEqual(sorted(load_schedule(doc, roster)), sorted(assignments))

    def test_a_name_that_is_not_a_string_is_refused(self):
        roster, _ = make([])
        bad = {"assignments": [{"provider": 5, "date": "2026-01-05", "shift": "day", "site": "A"}]}
        with self.assertRaisesRegex(DocError, r"assignments\[0\].provider: expected a string"):
            load_schedule(bad, roster)

    def test_a_field_the_loader_does_not_know(self):
        roster, _ = make([])
        bad = {"assignments": [{"provider": "p1", "date": "2026-01-05", "shift": "day",
                                "site": "A", "room": 3}]}
        with self.assertRaisesRegex(DocError, "unknown field 'room'"):
            load_schedule(bad, roster)


if __name__ == "__main__":
    unittest.main()
