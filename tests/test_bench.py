import unittest

from shiftrules import bench
from shiftrules.engine import build

from tests.fixtures import A, make


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.roster, self.rules = make([
            {"id": "cov", "kind": "coverage", "count": 1, "site": "A", "dates": ["2026-01-05"]},
            {"id": "rest", "kind": "min_rest_hours", "hours": 11},
        ])
        self.result = build(self.roster, self.rules)

    def test_a_consistent_result_passes(self):
        bench.verify(self.roster, self.rules, self.result.assignments, self.result.unfilled, "ok")

    def test_a_broken_rule_stops_the_benchmark(self):
        bad = self.result.assignments + [A("p1", 0, "day", "B"), A("p1", 0, "night", "B")]
        with self.assertRaises(SystemExit):
            bench.verify(self.roster, self.rules, bad, self.result.unfilled, "bad")

    def test_an_empty_cell_that_was_not_reported_stops_the_benchmark(self):
        with self.assertRaises(SystemExit):
            bench.verify(self.roster, self.rules, self.result.assignments[1:], [], "silent")

    def test_the_same_number_of_cells_but_different_ones_stops_the_benchmark(self):
        # One cell is short and one is reported, but they are not the same cell.
        roster, rules = make([
            {"id": "cov", "kind": "coverage", "count": 1, "dates": ["2026-01-05", "2026-01-06"],
             "shift": "day", "site": "A"},
        ])
        full = build(roster, rules)
        dropped = full.assignments[1:]  # the first day's cell is now short
        other_cell = build(*make([
            {"id": "cov", "kind": "coverage", "count": 1, "dates": ["2026-01-06"], "shift": "day", "site": "A"},
            {"id": "off", "kind": "unavailable", "provider": ["p1", "p2", "p3"], "dates": ["2026-01-06"]},
        ])).unfilled  # reports the second day's cell
        self.assertEqual([(u.rule, u.day) for u in other_cell], [("cov", 1)])
        with self.assertRaises(SystemExit):
            bench.verify(roster, rules, dropped, other_cell, "wrong cell")

    def test_a_reported_cell_that_is_not_empty_stops_the_benchmark(self):
        cells = build(*make([
            {"id": "cov", "kind": "coverage", "count": 1, "dates": ["2026-01-05"]},
            {"id": "off", "kind": "unavailable", "provider": ["p1", "p2", "p3"], "dates": ["2026-01-05"]},
        ])).unfilled
        with self.assertRaises(SystemExit):
            bench.verify(self.roster, self.rules, self.result.assignments, cells, "phantom")


class RunTests(unittest.TestCase):
    def test_one_seed_prints_the_table(self):
        text = bench.run(seeds=1)
        self.assertIn("| four providers off for one week |", text)
        self.assertIn("Roster too small", text)


if __name__ == "__main__":
    unittest.main()
