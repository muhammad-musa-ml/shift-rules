"""Command line: generate, build, check and rebuild.

Exit codes: 0 done, 1 the schedule has violations or unfilled cells, 2 a
document could not be loaded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import synth
from .check import check, label
from .engine import build, rebuild
from .model import DocError, dump_schedule, load_roster, load_rules, load_schedule, read_json


def _write_json(path: str, doc) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")


def _load(args):
    roster = load_roster(read_json(args.roster))
    rules = load_rules(read_json(args.rules), roster)
    return roster, rules


def _blockers(blocked_by: dict) -> str:
    return ", ".join("%s x%d" % (k, v) for k, v in sorted(blocked_by.items())) or "none"


def _print_unfilled(roster, unfilled) -> None:
    for u in unfilled:
        print("unfilled %s %s %s: needs %d, has %d (%s); blocked by %s" % (
            roster.date_of(u.day).isoformat(), u.shift, u.site, u.needed, u.got, u.rule,
            _blockers(u.blocked_by)))


def cmd_generate(args) -> int:
    doc = synth.roster_doc(args.seed, args.providers, args.days)
    os.makedirs(args.out, exist_ok=True)
    _write_json(os.path.join(args.out, "roster.json"), doc)
    _write_json(os.path.join(args.out, "rules.json"), synth.rules_doc(args.seed, doc))
    print("wrote roster.json and rules.json to %s" % args.out)
    return 0


def cmd_build(args) -> int:
    roster, rules = _load(args)
    result = build(roster, rules, args.seed)
    _write_json(args.out, dump_schedule(roster, result.assignments,
                                        [u.as_dict(roster) for u in result.unfilled]))
    print("built %d assignments, %d unfilled cells" % (len(result.assignments), len(result.unfilled)))
    _print_unfilled(roster, result.unfilled)
    return 1 if result.unfilled else 0


def cmd_check(args) -> int:
    roster, rules = _load(args)
    assignments = load_schedule(read_json(args.schedule), roster)
    found = check(roster, rules, assignments)
    for v in found:
        print("%s: %s" % (v.rule, v.detail))
    print("%d assignments, %d violations" % (len(assignments), len(found)))
    return 1 if found else 0


def cmd_rebuild(args) -> int:
    roster, rules = _load(args)
    old = load_schedule(read_json(args.schedule), roster)
    out = rebuild(roster, rules, old, args.seed)
    for a, why in out.removed:
        print("removed %s %s (%s)" % (label(roster, a), a.provider, why))
    for a, why in out.added:
        print("added %s %s (%s)" % (label(roster, a), a.provider, why))
    _write_json(args.out, dump_schedule(roster, out.assignments,
                                        [u.as_dict(roster) for u in out.unfilled]))
    print("%d removed, %d added, %d unfilled cells" % (
        len(out.removed), len(out.added), len(out.unfilled)))
    _print_unfilled(roster, out.unfilled)
    return 1 if out.unfilled else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shiftrules")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="write a synthetic roster.json and rules.json")
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--providers", type=int, default=32)
    g.add_argument("--days", type=int, default=28)
    g.add_argument("--out", required=True, help="folder to write into")
    g.set_defaults(run=cmd_generate)

    b = sub.add_parser("build", help="build a schedule; exit 1 if any cell is unfilled")
    b.add_argument("roster")
    b.add_argument("rules")
    b.add_argument("--out", required=True)
    b.add_argument("--seed", type=int, default=0)
    b.set_defaults(run=cmd_build)

    c = sub.add_parser("check", help="check a schedule; exit 1 on any violation")
    c.add_argument("roster")
    c.add_argument("rules")
    c.add_argument("schedule")
    c.set_defaults(run=cmd_check)

    r = sub.add_parser("rebuild", help="apply changed rules, moving as few assignments as possible")
    r.add_argument("roster")
    r.add_argument("rules")
    r.add_argument("schedule")
    r.add_argument("--out", required=True)
    r.add_argument("--seed", type=int, default=0)
    r.set_defaults(run=cmd_rebuild)
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.run(args)
    except DocError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
