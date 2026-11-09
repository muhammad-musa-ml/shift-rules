import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from shiftrules.cli import main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.roster = os.path.join(self.dir, "roster.json")
        self.rules = os.path.join(self.dir, "rules.json")
        self.schedule = os.path.join(self.dir, "schedule.json")
        code, _, _ = run("generate", "--seed", "1", "--out", self.dir)
        self.assertEqual(code, 0)

    def build(self):
        code, out, _ = run("build", self.roster, self.rules, "--out", self.schedule)
        self.assertEqual(code, 0, out)

    def test_generate_build_check(self):
        self.build()
        code, out, _ = run("check", self.roster, self.rules, self.schedule)
        self.assertEqual(code, 0, out)
        self.assertIn("0 violations", out)

    def test_check_exits_1_and_names_the_rule_for_a_planted_violation(self):
        self.build()
        doc = read(self.schedule)
        planted = dict(doc["assignments"][0])
        doc["assignments"].append(planted)
        write(self.schedule, doc)
        code, out, _ = run("check", self.roster, self.rules, self.schedule)
        self.assertEqual(code, 1)
        self.assertIn("builtin:duplicate", out)

    def test_check_reports_a_cell_that_lost_its_provider(self):
        self.build()
        doc = read(self.schedule)
        gone = doc["assignments"].pop(0)
        write(self.schedule, doc)
        code, out, _ = run("check", self.roster, self.rules, self.schedule)
        self.assertEqual(code, 1)
        self.assertIn("cover-2-everywhere: %s %s %s" % (gone["date"], gone["shift"], gone["site"]), out)

    def test_a_misspelled_rule_field_stops_the_run_with_exit_2(self):
        rules = read(self.rules)
        rules.append({"id": "typo", "kind": "max_per_window", "max": 3, "windowdays": 7})
        write(self.rules, rules)
        code, out, err = run("build", self.roster, self.rules, "--out", self.schedule)
        self.assertEqual(code, 2)
        self.assertIn("rule 'typo'", err)
        self.assertIn("windowdays", err)
        self.assertFalse(os.path.exists(self.schedule))

    def test_a_missing_file_is_exit_2(self):
        code, _, err = run("check", self.roster, self.rules, os.path.join(self.dir, "nope.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_build_exits_1_and_lists_unfilled_cells_when_demand_is_too_high(self):
        rules = read(self.rules)
        rules.append({"id": "cover-20", "kind": "coverage", "count": 20, "site": "C", "shift": "night",
                      "dates": ["2026-01-05"]})
        write(self.rules, rules)
        code, out, _ = run("build", self.roster, self.rules, "--out", self.schedule)
        self.assertEqual(code, 1)
        self.assertIn("unfilled 2026-01-05 night C", out)
        self.assertIn("(cover-20)", out)
        self.assertEqual(read(self.schedule)["unfilled"][0]["rule"], "cover-20")

    def test_build_refuses_rules_that_ask_for_nothing(self):
        write(self.rules, [r for r in read(self.rules) if r["kind"] != "coverage"])
        code, _, err = run("build", self.roster, self.rules, "--out", self.schedule)
        self.assertEqual(code, 2)
        self.assertIn("no coverage rule", err)
        self.assertFalse(os.path.exists(self.schedule))

    def test_a_key_repeated_in_the_rules_file_is_exit_2(self):
        with open(self.rules, "w", encoding="utf-8") as f:
            f.write('[{"id": "c", "kind": "coverage", "count": 1, "count": 3}]')
        code, _, err = run("build", self.roster, self.rules, "--out", self.schedule)
        self.assertEqual(code, 2)
        self.assertIn("key 'count' appears twice", err)

    def test_generate_does_not_overwrite_without_force(self):
        before = read(self.rules)
        write(self.rules, [])
        code, _, err = run("generate", "--seed", "2", "--out", self.dir)
        self.assertEqual(code, 2)
        self.assertIn("already exists", err)
        self.assertEqual(read(self.rules), [])
        code, _, _ = run("generate", "--seed", "1", "--out", self.dir, "--force")
        self.assertEqual(code, 0)
        self.assertEqual(read(self.rules), before)

    def test_generate_refuses_sizes_the_loader_would_refuse(self):
        empty = os.path.join(self.dir, "elsewhere")
        for args in (["--days", "4"], ["--days", "367"], ["--providers", "0"]):
            code, _, err = run("generate", "--out", empty, *args)
            self.assertEqual(code, 2, args)
            self.assertIn(args[0], err)
        self.assertFalse(os.path.exists(empty))
        code, _, _ = run("generate", "--out", empty, "--days", "5", "--providers", "3")
        self.assertEqual(code, 0)
        code, out, _ = run("build", os.path.join(empty, "roster.json"), os.path.join(empty, "rules.json"),
                           "--out", os.path.join(empty, "schedule.json"))
        self.assertIn(code, (0, 1))
        self.assertIn("built", out)

    def test_rebuild_will_not_overwrite_the_schedule_it_reads(self):
        self.build()
        with open(self.schedule, "rb") as f:
            before = f.read()
        code, _, err = run("rebuild", self.roster, self.rules, self.schedule, "--out", self.schedule)
        self.assertEqual(code, 2)
        self.assertIn("also an input file", err)
        with open(self.schedule, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_an_output_folder_that_does_not_exist_is_exit_2_not_a_traceback(self):
        code, _, err = run("build", self.roster, self.rules, "--out", os.path.join(self.dir, "no", "such", "s.json"))
        self.assertEqual(code, 2)
        self.assertIn("error:", err)

    def test_rebuild_exits_1_and_says_so_when_a_cell_cannot_be_filled(self):
        self.build()
        rules = read(self.rules)
        rules.append({"id": "cover-20", "kind": "coverage", "count": 20, "site": "C", "shift": "night",
                      "dates": ["2026-01-05"]})
        write(self.rules, rules)
        new_schedule = os.path.join(self.dir, "new.json")
        code, out, _ = run("rebuild", self.roster, self.rules, self.schedule, "--out", new_schedule)
        self.assertEqual(code, 1)
        self.assertIn("0 removed", out)
        self.assertIn("1 unfilled cells", out)
        self.assertIn("unfilled 2026-01-05 night C", out)

    def test_the_module_runs_as_a_program_with_the_documented_exit_codes(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def program(*argv):
            return subprocess.run([sys.executable, "-B", "-m", "shiftrules", *argv], cwd=root,
                                  capture_output=True, text=True)

        self.build()
        ok = program("check", self.roster, self.rules, self.schedule)
        self.assertEqual((ok.returncode, ok.stdout.strip().endswith("0 violations")), (0, True))
        write(self.rules, [{"id": "typo", "kind": "coverage", "count": 1, "cout": 2}])
        bad = program("check", self.roster, self.rules, self.schedule)
        self.assertEqual(bad.returncode, 2)
        self.assertIn("error:", bad.stderr)

    def test_rebuild_lists_what_moved_and_why(self):
        self.build()
        first = read(self.schedule)["assignments"][0]
        rules = read(self.rules)
        rules.append({"id": "new-off", "kind": "unavailable", "provider": first["provider"],
                      "dates": [first["date"]]})
        write(self.rules, rules)
        new_schedule = os.path.join(self.dir, "new.json")
        code, out, _ = run("rebuild", self.roster, self.rules, self.schedule, "--out", new_schedule)
        self.assertEqual(code, 0, out)
        self.assertIn("removed %s %s %s %s (new-off)" % (
            first["date"], first["shift"], first["site"], first["provider"]), out)
        self.assertIn("added %s %s %s" % (first["date"], first["shift"], first["site"]), out)
        code, out, _ = run("check", self.roster, self.rules, new_schedule)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
