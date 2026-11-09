"""Check a schedule against the rules, from the finished list.

Only the matching of a rule's scope (Rule.covers_cell and Rule.applies_to in
model.py) is shared with the builder in engine.py. The builder decides one
assignment at a time with its own incremental tests; this module re-derives
every rule from the whole schedule. A rule the builder gets wrong shows up
here as a violation instead of passing both.
"""

from __future__ import annotations

from collections import defaultdict
from typing import NamedTuple, Optional

from .model import Assignment, Roster, Rule


class Violation(NamedTuple):
    rule: str  # a rule id, or builtin:<name>
    provider: Optional[str]
    day: Optional[int]
    detail: str
    involved: tuple  # the assignments that break the rule; empty for coverage


def sort_key(roster: Roster, a: Assignment):
    return (a.day, roster.shift_start(a.day, a.shift), a.site, a.provider)


def label(roster: Roster, a: Assignment) -> str:
    return "%s %s %s" % (roster.date_of(a.day).isoformat(), a.shift, a.site)


def check(roster: Roster, rules: list, assignments) -> list:
    out: list = []
    valid = []
    for a in assignments:
        if (a.provider in roster.providers and a.shift in roster.shifts
                and a.site in roster.sites and 0 <= a.day < roster.days):
            valid.append(a)
        else:
            out.append(Violation("builtin:unknown", a.provider, a.day,
                                 "%r names a provider, shift, site or day the roster does not have" % (a,), (a,)))

    unique = []
    seen = set()
    for a in valid:
        if a in seen:
            out.append(Violation("builtin:duplicate", a.provider, a.day,
                                 "%s listed twice for %s" % (label(roster, a), a.provider), (a,)))
        else:
            seen.add(a)
            unique.append(a)
    unique.sort(key=lambda a: sort_key(roster, a))

    by_provider = defaultdict(list)
    cells = defaultdict(set)
    for a in unique:
        by_provider[a.provider].append(a)
        cells[(a.day, a.shift, a.site)].add(a.provider)

    for a in unique:
        if a.site not in roster.providers[a.provider].sites:
            out.append(Violation("builtin:credentialed", a.provider, a.day,
                                 "%s is not credentialed at site %s" % (a.provider, a.site), (a,)))
    for pid in sorted(by_provider):
        items = by_provider[pid]
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if roster.shift_start(b.day, b.shift) < roster.shift_end(a.day, a.shift):
                    out.append(Violation("builtin:overlap", pid, a.day,
                                         "%s works %s and %s at the same time" % (
                                             pid, label(roster, a), label(roster, b)), (a, b)))

    for rule in rules:
        out.extend(_HANDLERS[rule.kind](roster, rule, by_provider, cells))
    return out


def _coverage(roster, rule, by_provider, cells):
    out = []
    for day in range(roster.days):
        for shift in roster.shifts:
            for site in roster.sites:
                if not rule.covers_cell(roster, day, shift, site):
                    continue
                have = [p for p in cells.get((day, shift, site), ())
                        if not rule.skill or rule.skill in roster.providers[p].skills]
                if len(have) < rule.count:
                    out.append(Violation(
                        rule.id, None, day,
                        "%s %s %s: %d of %d%s" % (
                            roster.date_of(day).isoformat(), shift, site, len(have), rule.count,
                            " with skill %s" % rule.skill if rule.skill else ""),
                        ()))
    return out


def _unavailable(roster, rule, by_provider, cells):
    out = []
    for pid in sorted(by_provider):
        if not rule.applies_to(pid):
            continue
        for a in by_provider[pid]:
            if rule.covers_cell(roster, a.day, a.shift, a.site):
                out.append(Violation(rule.id, pid, a.day,
                                     "%s is on %s but is unavailable" % (pid, label(roster, a)), (a,)))
    return out


def _max_per_window(roster, rule, by_provider, cells):
    out = []
    for pid in sorted(by_provider):
        if not rule.applies_to(pid):
            continue
        scoped = [a for a in by_provider[pid] if rule.covers_cell(roster, a.day, a.shift, a.site)]
        seen = set()
        for start in range(roster.days):
            chosen = tuple(a for a in scoped if start <= a.day < start + rule.window_days)
            if len(chosen) > rule.limit and chosen not in seen:
                seen.add(chosen)
                out.append(Violation(
                    rule.id, pid, start,
                    "%s has %d assignments in the %d days from %s (max %d)" % (
                        pid, len(chosen), rule.window_days,
                        roster.date_of(start).isoformat(), rule.limit),
                    chosen))
    return out


def _min_rest(roster, rule, by_provider, cells):
    out = []
    for pid in sorted(by_provider):
        if not rule.applies_to(pid):
            continue
        items = by_provider[pid]
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                gap = roster.shift_start(b.day, b.shift) - roster.shift_end(a.day, a.shift)
                if 0 <= gap < rule.hours:
                    out.append(Violation(
                        rule.id, pid, a.day,
                        "%s has %dh between %s and %s (min %dh)" % (
                            pid, gap, label(roster, a), label(roster, b), rule.hours),
                        (a, b)))
    return out


def _max_consecutive(roster, rule, by_provider, cells):
    out = []
    for pid in sorted(by_provider):
        if not rule.applies_to(pid):
            continue
        scoped = [a for a in by_provider[pid] if rule.shifts is None or a.shift in rule.shifts]
        days = sorted({a.day for a in scoped})
        run = []
        for day in days + [None]:
            if run and (day is None or day != run[-1] + 1):
                if len(run) > rule.limit:
                    out.append(Violation(
                        rule.id, pid, run[0],
                        "%s works %d days in a row from %s (max %d)" % (
                            pid, len(run), roster.date_of(run[0]).isoformat(), rule.limit),
                        tuple(a for a in scoped if a.day in run)))
                run = []
            if day is not None:
                run.append(day)
    return out


_HANDLERS = {
    "coverage": _coverage,
    "unavailable": _unavailable,
    "max_per_window": _max_per_window,
    "min_rest_hours": _min_rest,
    "max_consecutive_days": _max_consecutive,
}
