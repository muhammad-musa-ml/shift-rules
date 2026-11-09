"""Measure what a rule change costs, and what a roster that is too small looks like.

    python -m shiftrules.bench --out results/benchmark.txt

Every run is checked: the schedule must have no broken rule, and the cells
that check.py finds short must be exactly the cells the builder reported as
unfilled. The benchmark stops if either differs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import platform
import random
import statistics
import time
from collections import Counter

from . import synth
from .check import check
from .engine import build, rebuild
from .model import load_roster, load_rules

SEEDS = 20


def verify(roster, rules, assignments, unfilled, where):
    found = check(roster, rules, assignments)
    hard = [v for v in found if v.involved]
    short = [v for v in found if not v.involved]
    if hard or len(short) != len(unfilled):
        raise SystemExit("%s: %d broken rules, %d short cells, %d reported unfilled" % (
            where, len(hard), len(short), len(unfilled)))


def changes(roster_doc, rules_doc, seed):
    rnd = random.Random("change-%d" % seed)
    start = dt.date.fromisoformat(roster_doc["start"])
    first = rnd.randrange(roster_doc["days"] - 7)
    week = [(start + dt.timedelta(days=first + k)).isoformat() for k in range(7)]
    people = [p["id"] for p in roster_doc["providers"]]
    time_off = [{"id": "week-off-" + pid, "kind": "unavailable", "provider": pid, "dates": week}
                for pid in rnd.sample(people, 4)]
    return [
        ("four providers off for one week", rules_doc + time_off),
        ("run limit 5 days -> 3 days",
         [dict(r, max=3) if r["id"] == "max-5-days-running" else r for r in rules_doc]),
        ("at most 2 Friday or Saturday nights per 28 days",
         rules_doc + [{"id": "weekend-nights", "kind": "max_per_window", "max": 2,
                       "window_days": 28, "shift": "night", "weekdays": [4, 5]}]),
    ]


def spread(values, digits=1):
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return "%.*f (sd %.*f, %s to %s)" % (
        digits, statistics.mean(values), digits, sd, _num(min(values)), _num(max(values)))


def _num(x):
    return "%d" % x if float(x).is_integer() else "%.0f" % x


def run(seeds=SEEDS):
    lines = []
    emit = lines.append
    emit("shift-rules benchmark: %d seeds, 32 providers, 3 sites, 28 days, python %s on %s" % (
        seeds, platform.python_version(), platform.system()))
    emit("")

    base_ms, built = [], []
    table = {}
    for seed in range(1, seeds + 1):
        roster_doc = synth.roster_doc(seed)
        roster = load_roster(roster_doc)
        rules_doc = synth.rules_doc(seed, roster_doc)
        rules = load_rules(rules_doc, roster)

        t = time.perf_counter()
        base = build(roster, rules, seed)
        base_ms.append((time.perf_counter() - t) * 1000)
        verify(roster, rules, base.assignments, base.unfilled, "base seed %d" % seed)
        if base.unfilled:
            raise SystemExit("base seed %d has unfilled cells" % seed)
        built.append(len(base.assignments))
        old = set(base.assignments)

        for name, doc in changes(roster_doc, rules_doc, seed):
            new_rules = load_rules(doc, roster)
            t = time.perf_counter()
            rb = rebuild(roster, new_rules, base.assignments, seed)
            rb_ms = (time.perf_counter() - t) * 1000
            sc = build(roster, new_rules, seed)
            verify(roster, new_rules, rb.assignments, rb.unfilled, "rebuild seed %d %s" % (seed, name))
            verify(roster, new_rules, sc.assignments, sc.unfilled, "scratch seed %d %s" % (seed, name))
            if len(old - set(rb.assignments)) != len(rb.removed):
                raise SystemExit("rebuild seed %d %s: removed list and schedule differ" % (seed, name))
            row = table.setdefault(name, {"rb_removed": [], "sc_removed": [], "rb_added": [],
                                          "rb_unfilled": [], "sc_unfilled": [], "rb_ms": []})
            row["rb_removed"].append(len(old - set(rb.assignments)))
            row["sc_removed"].append(len(old - set(sc.assignments)))
            row["rb_added"].append(len(set(rb.assignments) - old))
            row["rb_unfilled"].append(len(rb.unfilled))
            row["sc_unfilled"].append(len(sc.unfilled))
            row["rb_ms"].append(rb_ms)

    emit("Base schedule: %s assignments, no unfilled cell and no broken rule in any seed." % spread(built))
    emit("Base build time in ms: %s" % spread(base_ms, 0))
    emit("")
    emit("Rule change: existing assignments that move, mean over %d seeds (sd, min to max)" % seeds)
    emit("")
    emit("| change | rebuild moves | from scratch moves | rebuild unfilled | scratch unfilled |")
    emit("|---|---|---|---|---|")
    for name, row in table.items():
        emit("| %s | %s | %s | %s | %s |" % (
            name, spread(row["rb_removed"]), spread(row["sc_removed"]),
            spread(row["rb_unfilled"]), spread(row["sc_unfilled"])))
    emit("")
    for name, row in table.items():
        emit("rebuild time in ms, %s: %s" % (name, spread(row["rb_ms"], 0)))
    emit("")

    short_cells, blocks, demanded = [], Counter(), 0
    for seed in range(1, seeds + 1):
        roster_doc = synth.roster_doc(seed, providers=20)
        roster = load_roster(roster_doc)
        rules = load_rules(synth.rules_doc(seed, roster_doc), roster)
        demanded = sum(1 for r in rules if r.kind == "coverage" for d in range(roster.days)
                       for sh in roster.shifts for si in roster.sites if r.covers_cell(roster, d, sh, si))
        result = build(roster, rules, seed)
        verify(roster, rules, result.assignments, result.unfilled, "small seed %d" % seed)
        short_cells.append(len(result.unfilled))
        for u in result.unfilled:
            for why, n in u.blocked_by.items():
                blocks["off-*" if why.startswith("off-") else why] += n
    total = sum(blocks.values())
    emit("Roster too small (20 providers): unfilled coverage requirements out of %d, mean over %d seeds: %s" % (
        demanded, seeds, spread(short_cells)))
    emit("What blocked the providers in those cells (share of all provider-by-cell blocks):")
    for why, n in blocks.most_common(5):
        emit("  %-22s %4.1f%%" % (why, 100.0 * n / total))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shiftrules.bench")
    p.add_argument("--out", help="also write the report to this file")
    p.add_argument("--seeds", type=int, default=SEEDS)
    args = p.parse_args(argv)
    text = run(args.seeds)
    print(text, end="")
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
