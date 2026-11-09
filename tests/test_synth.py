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
