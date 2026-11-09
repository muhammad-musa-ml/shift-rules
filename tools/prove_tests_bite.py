"""Break the code on a copy, one line at a time, and check that a test fails.

    python tools/prove_tests_bite.py --out results/tests-bite.txt

The repository is never edited. Each break goes into a fresh copy in a
temporary folder, and the whole test suite runs against that copy. A row is
UNRUN, not a verdict, if the line to change does not occur exactly once or the
file did not change. Four copies run at a time.
"""

import argparse
import concurrent.futures
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ["tests.test_model", "tests.test_check", "tests.test_engine", "tests.test_rebuild",
           "tests.test_cli", "tests.test_synth", "tests.test_bench"]

BREAKS = [
    ("check.py", "if 0 <= gap < rule.hours:", "if 0 <= gap <= rule.hours:", "check: a rest gap equal to the minimum is flagged"),
    ("check.py", "if len(chosen) > rule.limit and chosen not in seen:", "if len(chosen) >= rule.limit and chosen not in seen:", "check: a window at its maximum is flagged"),
    ("check.py", "if len(chosen) > rule.limit and chosen not in seen:", "if len(chosen) > rule.limit:", "check: one crowded stretch is reported once per window that holds it"),
    ("check.py", "if len(run) > rule.limit:", "if len(run) >= rule.limit:", "check: a run at its maximum is flagged"),
    ("check.py", "if len(have) < rule.count:", "if len(have) <= rule.count:", "check: a cell at its count is flagged"),
    ("check.py", "if a.site not in roster.providers[a.provider].sites:", "if False:", "check: credentialing is ignored"),
    ("check.py", "if roster.shift_start(b.day, b.shift) < roster.shift_end(a.day, a.shift):", "if roster.shift_start(b.day, b.shift) <= roster.shift_end(a.day, a.shift):", "check: back-to-back shifts count as overlap"),
    ("check.py", "if a in seen:", "if False:", "check: duplicates are ignored"),
    ("check.py", "and a.site in roster.sites and 0 <= a.day < roster.days)", "and a.site in roster.sites and a.day < roster.days)", "check: a day before the roster starts is accepted"),
    ("engine.py", "if gap < rule.hours:", "if gap <= rule.hours:", "engine: a rest gap equal to the minimum is blocked"),
    ("engine.py", "if sum(1 for d in days if first <= d < first + rule.window_days) + 1 > rule.limit:", "if sum(1 for d in days if first <= d < first + rule.window_days) + 1 >= rule.limit:", "engine: a window at its maximum is blocked"),
    ("engine.py", "return length > rule.limit", "return length >= rule.limit", "engine: a run at its maximum is blocked"),
    ("engine.py", "return rule.covers_cell(state.roster, day, shift, site)", "return False", "engine: unavailable never blocks"),
    ("engine.py", "if site not in r.providers[pid].sites:", "if False:", "engine: credentialing is not tested"),
    ("engine.py", "for rule in self.rules:", "for rule in reversed(self.rules):", "engine: the last blocking rule is named, not the first"),
    ("engine.py", "key = (len(state.by_provider[pid]), rank[pid])", "key = (0, rank[pid])", "engine: fewest-shifts-first is removed"),
    ("engine.py", "random.Random(seed).shuffle(order)", "order.sort()", "engine: the seed no longer changes the tie-break"),
    ("engine.py", "if have >= rule.count:", "if have > rule.count:", "engine: fills one past the count"),
    ("engine.py", "unfilled.append(Unfilled(rule.id, day, shift, site, rule.count, have, dict(reasons)))", "pass", "engine: a cell that cannot be filled is not reported"),
    ("engine.py", "if best is None or left < best[0]:", "if best is None or left <= best[0]:", "engine: a rebuild tie goes to the earliest, not the latest"),
    ("engine.py", "broken = [v for v in check(roster, rules, current) if v.involved]", "broken = []", "engine: rebuild never removes anything"),
    ("engine.py", "if a in seen:", "if False:", "engine: rebuild keeps a duplicate in the old schedule"),
    ("engine.py", '                return "builtin:duplicate"', "                pass", "engine: a duplicate is not blocked as a duplicate"),
    ("model.py", "if key not in known:", "if False:", "model: an unknown field is accepted"),
    ("model.py", "if not 0 <= day < roster.days:", "if False:", "model: a date outside the roster is accepted"),
    ("model.py", "if not 0 <= day < roster.days:", "if not day < roster.days:", "model: a date before the roster starts is accepted"),
    ("model.py", "if not isinstance(skill, str) or not any(skill in p.skills for p in roster.providers.values()):", "if False:", "model: a skill nobody has is accepted"),
    ("model.py", "if not isinstance(skill, str) or not any(", "if not any(", "model: a skill that is not a string crashes the loader"),
    ("model.py", "if not isinstance(kind, str) or kind not in KINDS:", "if kind not in KINDS:", "model: a kind that is not a string crashes the loader"),
    ("model.py", 'present = ", ".join(sorted(str(k) for k in obj))', 'present = ""', "model: a misspelled id or kind does not name the fields present"),
    ("model.py", "if key in out:", "if False:", "model: a key repeated in a JSON file is accepted"),
    ("model.py", '        raise DocError("%s: its scope matches no shift of the roster" % where)', "        pass", "model: a rule whose scope matches nothing is accepted"),
    ("cli.py", "return 1 if result.unfilled else 0", "return 0", "cli: build exits 0 with unfilled cells"),
    ("cli.py", "return 1 if out.unfilled else 0", "return 0", "cli: rebuild exits 0 with unfilled cells"),
    ("cli.py", 'if not any(r.kind == "coverage" for r in rules):', "if False:", "cli: build accepts rules that ask for nothing"),
    ("cli.py", "if taken and not args.force:", "if False:", "cli: generate overwrites existing files"),
    ("cli.py", "if any(os.path.abspath(out) == os.path.abspath(p) for p in inputs):", "if False:", "cli: --out may be the schedule being read"),
    ("cli.py", "except (DocError, OSError) as e:", "except DocError as e:", "cli: an unwritable output path is a traceback"),
    ("bench.py", "if hard or short != reported:", "if hard or len(short) != len(reported):", "bench: the same number of different cells passes"),
    ("synth.py", "if i < 8:", "if i < 7:", "synth: only seven providers get the pediatric skill"),
]


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def one(work, i, name, old, new, label):
    copy = os.path.join(work, "b%02d" % i)
    for part in ("shiftrules", "tests"):
        shutil.copytree(os.path.join(ROOT, part), os.path.join(copy, part),
                        ignore=shutil.ignore_patterns("__pycache__"))
    target = os.path.join(copy, "shiftrules", name)
    before = sha(target)
    with open(target, encoding="utf-8", newline="") as f:
        text = f.read()
    if text.count(old) != 1:
        return "%02d UNRUN    %s (the line occurs %d times)" % (i, label, text.count(old)), False
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old, new))
    if sha(target) == before:
        return "%02d UNRUN    %s (the file did not change)" % (i, label), False
    res = subprocess.run([sys.executable, "-B", "-m", "unittest", "-f"] + MODULES,
                         cwd=copy, capture_output=True, text=True)
    first = [ln for ln in res.stderr.splitlines() if ln.startswith(("FAIL:", "ERROR:"))]
    if res.returncode != 0:
        return "%02d FAILED   %s -> %s" % (i, label, first[0].split(" (")[0] if first else "exit code"), True
    return "%02d PASSED   %s (no test noticed)" % (i, label), False


def run_all():
    work = tempfile.mkdtemp(prefix="bite-")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [pool.submit(one, work, i, *b) for i, b in enumerate(BREAKS, 1)]
            results = [j.result() for j in jobs]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    lines = [line for line, _ in results]
    killed = sum(1 for _, ok in results if ok)
    lines.append("%d of %d breaks made a test fail; %d did not" % (killed, len(BREAKS), len(BREAKS) - killed))
    return "\n".join(lines) + "\n", len(BREAKS) - killed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", help="also write the report to this file")
    args = p.parse_args()
    text, bad = run_all()
    print(text, end="")
    if args.out:
        with open(os.path.join(ROOT, args.out), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
