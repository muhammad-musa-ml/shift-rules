import datetime as dt
import unittest

from shiftrules.model import DocError, load_roster, load_rules

from tests.fixtures import make, roster_doc


class RosterTests(unittest.TestCase):
    def test_fixture_starts_on_a_monday(self):
        self.assertEqual(dt.date(2026, 1, 5).weekday(), 0)

    def test_loads_a_valid_roster(self):
        roster = load_roster(roster_doc())
        self.assertEqual(roster.days, 14)
        self.assertEqual(roster.shift_start(1, "night"), 24 + 19)
        self.assertEqual(roster.shift_end(1, "night"), 24 + 31)
        self.assertEqual(roster.weekday(6), 6)
        self.assertEqual(roster.weekday(7), 0)
        self.assertEqual(roster.providers["p1"].skills, frozenset({"peds"}))

    def test_unknown_roster_field_is_named(self):
        with self.assertRaisesRegex(DocError, "unknown field 'dayz'"):
            load_roster(roster_doc(dayz=3))

    def test_provider_site_must_exist(self):
        doc = roster_doc(providers=[{"id": "p1", "sites": ["Z"]}])
        with self.assertRaisesRegex(DocError, "'Z' is not a known site"):
            load_roster(doc)

    def test_duplicate_provider_id(self):
        doc = roster_doc(providers=[{"id": "p1", "sites": ["A"]}, {"id": "p1", "sites": ["B"]}])
        with self.assertRaisesRegex(DocError, "unique"):
            load_roster(doc)

    def test_shift_hours_are_bounded(self):
        doc = roster_doc(shifts={"day": {"start": 7, "hours": 30}})
        with self.assertRaisesRegex(DocError, "roster.shifts.day.hours"):
            load_roster(doc)

    def test_bad_start_date(self):
        with self.assertRaisesRegex(DocError, "roster.start"):
            load_roster(roster_doc(start="2026-13-01"))


class RuleTests(unittest.TestCase):
    def test_loads_every_kind(self):
        roster, rules = make([
            {"id": "c", "kind": "coverage", "count": 2, "shift": "night", "site": ["A", "B"]},
            {"id": "u", "kind": "unavailable", "provider": "p1", "dates": ["2026-01-06"]},
            {"id": "w", "kind": "max_per_window", "max": 3, "window_days": 7, "weekdays": [5, 6]},
            {"id": "r", "kind": "min_rest_hours", "hours": 11},
            {"id": "k", "kind": "max_consecutive_days", "max": 5, "shift": "night"},
        ])
        self.assertEqual([r.kind for r in rules],
                         ["coverage", "unavailable", "max_per_window", "min_rest_hours",
                          "max_consecutive_days"])
        self.assertEqual(rules[1].days, frozenset({1}))
        self.assertEqual(rules[2].weekdays, frozenset({5, 6}))
        self.assertEqual(rules[2].limit, 3)

    def test_misspelled_field_is_an_error_naming_rule_and_field(self):
        with self.assertRaisesRegex(DocError, "rule 'w'.*unknown field 'window_day'"):
            make([{"id": "w", "kind": "max_per_window", "max": 3, "window_day": 7}])

    def test_missing_field(self):
        with self.assertRaisesRegex(DocError, "rule 'w'.*missing 'window_days'"):
            make([{"id": "w", "kind": "max_per_window", "max": 3}])

    def test_unknown_kind(self):
        with self.assertRaisesRegex(DocError, "rule 'x'.*unknown kind 'maximum'"):
            make([{"id": "x", "kind": "maximum"}])

    def test_field_of_another_kind_is_refused(self):
        with self.assertRaisesRegex(DocError, "unknown field 'site'"):
            make([{"id": "r", "kind": "min_rest_hours", "hours": 8, "site": "A"}])

    def test_duplicate_rule_id(self):
        with self.assertRaisesRegex(DocError, "id used twice"):
            make([
                {"id": "r", "kind": "min_rest_hours", "hours": 8},
                {"id": "r", "kind": "max_consecutive_days", "max": 4},
            ])

    def test_unknown_provider_shift_site_and_skill(self):
        with self.assertRaisesRegex(DocError, "'p9' is not a known provider"):
            make([{"id": "u", "kind": "unavailable", "provider": "p9"}])
        with self.assertRaisesRegex(DocError, "'swing' is not a known shift"):
            make([{"id": "c", "kind": "coverage", "count": 1, "shift": "swing"}])
        with self.assertRaisesRegex(DocError, "'C' is not a known site"):
            make([{"id": "c", "kind": "coverage", "count": 1, "site": "C"}])
        with self.assertRaisesRegex(DocError, "no provider has the skill 'pedz'"):
            make([{"id": "c", "kind": "coverage", "count": 1, "skill": "pedz"}])

    def test_date_outside_the_roster_is_refused(self):
        with self.assertRaisesRegex(DocError, "2026-02-01 is outside the roster"):
            make([{"id": "u", "kind": "unavailable", "provider": "p1", "dates": ["2026-02-01"]}])

    def test_weekday_and_count_bounds(self):
        with self.assertRaisesRegex(DocError, "rule 'u'.weekdays"):
            make([{"id": "u", "kind": "unavailable", "provider": "p1", "weekdays": [7]}])
        with self.assertRaisesRegex(DocError, "rule 'c'.count"):
            make([{"id": "c", "kind": "coverage", "count": 0}])
        with self.assertRaisesRegex(DocError, "rule 'c'.count"):
            make([{"id": "c", "kind": "coverage", "count": True}])

    def test_rules_must_be_a_list(self):
        roster = load_roster(roster_doc())
        with self.assertRaisesRegex(DocError, "rules: expected a list"):
            load_rules({"id": "r"}, roster)

    def test_scope_matching(self):
        roster, rules = make([
            {"id": "c", "kind": "coverage", "count": 1, "shift": "night", "site": "A",
             "weekdays": [0], "dates": ["2026-01-05", "2026-01-06"]},
        ])
        rule = rules[0]
        self.assertTrue(rule.covers_cell(roster, 0, "night", "A"))
        self.assertFalse(rule.covers_cell(roster, 0, "day", "A"))
        self.assertFalse(rule.covers_cell(roster, 0, "night", "B"))
        self.assertFalse(rule.covers_cell(roster, 1, "night", "A"))  # Tuesday
        self.assertFalse(rule.covers_cell(roster, 7, "night", "A"))  # Monday, date not listed


if __name__ == "__main__":
    unittest.main()
