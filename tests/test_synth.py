import unittest

from shiftrules import synth
from shiftrules.check import check
from shiftrules.engine import build
from shiftrules.model import load_roster, load_rules


class SynthTests(unittest.TestCase):
    def test_documents_load(self):
        for seed in (1, 2, 3):
            doc = synth.roster_doc(seed)
            roster = load_roster(doc)
            rules = load_rules(synth.rules_doc(seed, doc), roster)
            self.assertEqual(len(roster.providers), 32)
            self.assertGreater(len(rules), 6)

    def test_eight_providers_have_the_pediatric_skill_and_all_of_them_work_site_a(self):
        doc = synth.roster_doc(1)
        peds = [p for p in doc["providers"] if "peds" in p["skills"]]
        self.assertEqual(len(peds), 8)
        self.assertTrue(all("A" in p["sites"] for p in peds))
        self.assertTrue(all(p["skills"] == [] for p in doc["providers"] if p not in peds))

    def test_time_off_rules_name_real_providers_and_short_runs_of_days(self):
        doc = synth.roster_doc(1)
        off = [r for r in synth.rules_doc(1, doc) if r["id"].startswith("off-")]
        self.assertGreater(len(off), 10)
        self.assertLess(len(off), len(doc["providers"]))
        self.assertTrue(all(2 <= len(r["dates"]) <= 4 for r in off))

    def test_same_seed_same_documents(self):
        self.assertEqual(synth.roster_doc(4), synth.roster_doc(4))
        doc = synth.roster_doc(4)
        self.assertEqual(synth.rules_doc(4, doc), synth.rules_doc(4, doc))
        self.assertNotEqual(synth.roster_doc(4), synth.roster_doc(5))

    def test_base_scenario_can_be_filled_and_passes_the_checker(self):
        for seed in (1, 2, 3):
            doc = synth.roster_doc(seed)
            roster = load_roster(doc)
            rules = load_rules(synth.rules_doc(seed, doc), roster)
            result = build(roster, rules, seed=seed)
            self.assertEqual(result.unfilled, [], "seed %d" % seed)
            self.assertEqual(check(roster, rules, result.assignments), [], "seed %d" % seed)


if __name__ == "__main__":
    unittest.main()
