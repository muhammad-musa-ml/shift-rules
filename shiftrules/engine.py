"""Build a schedule one assignment at a time and say what could not be filled.

The builder tests each candidate against the rules incrementally (State).
The finished list is then judged again by check.py. The two are written
separately and share only the matching of a rule's scope in model.py.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import NamedTuple

from .model import Assignment, Roster


class Unfilled(NamedTuple):
    rule: str
    day: int
    shift: str
    site: str
    needed: int
    got: int
    blocked_by: dict  # what stopped each provider: a rule id, builtin:<name> or skill:<name>

    def as_dict(self, roster: Roster) -> dict:
        return {
            "rule": self.rule,
            "date": roster.date_of(self.day).isoformat(),
            "shift": self.shift,
            "site": self.site,
            "needed": self.needed,
            "got": self.got,
            "blocked_by": dict(sorted(self.blocked_by.items())),
        }


class Result(NamedTuple):
    assignments: list
    unfilled: list
    filled_for: dict  # Assignment -> id of the coverage rule it was added for


class State:
    def __init__(self, roster: Roster, rules: list):
        self.roster = roster
        self.rules = [r for r in rules if r.kind != "coverage"]
        self.by_provider = {pid: [] for pid in roster.providers}
        self.cells = defaultdict(list)

    def add(self, a: Assignment) -> None:
        self.by_provider[a.provider].append(a)
        self.cells[(a.day, a.shift, a.site)].append(a.provider)

    def blocked_by(self, pid: str, day: int, shift: str, site: str):
        """The id of the first rule this assignment would break, or None."""
        r = self.roster
        if site not in r.providers[pid].sites:
            return "builtin:credentialed"
        start, end = r.shift_start(day, shift), r.shift_end(day, shift)
        mine = self.by_provider[pid]
        for b in mine:
            if (b.day, b.shift, b.site) == (day, shift, site):
                return "builtin:duplicate"
            if start < r.shift_end(b.day, b.shift) and r.shift_start(b.day, b.shift) < end:
                return "builtin:overlap"
        for rule in self.rules:
            if rule.applies_to(pid) and _BLOCKS[rule.kind](self, rule, day, shift, site, mine, start, end):
                return rule.id
        return None


def _unavailable(state, rule, day, shift, site, mine, start, end):
    return rule.covers_cell(state.roster, day, shift, site)


def _window(state, rule, day, shift, site, mine, start, end):
    r = state.roster
    if not rule.covers_cell(r, day, shift, site):
        return False
    days = [b.day for b in mine if rule.covers_cell(r, b.day, b.shift, b.site)]
    for first in range(max(0, day - rule.window_days + 1), day + 1):
        if sum(1 for d in days if first <= d < first + rule.window_days) + 1 > rule.limit:
            return True
    return False


def _rest(state, rule, day, shift, site, mine, start, end):
    r = state.roster
    for b in mine:
        b_start, b_end = r.shift_start(b.day, b.shift), r.shift_end(b.day, b.shift)
        gap = start - b_end if b_end <= start else b_start - end
        if gap < rule.hours:
            return True
    return False


def _run(state, rule, day, shift, site, mine, start, end):
    if rule.shifts is not None and shift not in rule.shifts:
        return False
    days = {b.day for b in mine if rule.shifts is None or b.shift in rule.shifts}
    length = 1
    d = day - 1
    while d in days:
        length += 1
        d -= 1
    d = day + 1
    while d in days:
        length += 1
        d += 1
    return length > rule.limit


_BLOCKS = {
    "unavailable": _unavailable,
    "max_per_window": _window,
    "min_rest_hours": _rest,
    "max_consecutive_days": _run,
}


def build(roster: Roster, rules: list, seed: int = 0, initial=()) -> Result:
    """Fill every coverage rule that the other rules allow. Anything that
    cannot be filled is returned in `unfilled` with what blocked each provider."""
    state = State(roster, rules)
    for a in initial:
        state.add(a)
    order = list(roster.providers)
    random.Random(seed).shuffle(order)
    rank = {pid: i for i, pid in enumerate(order)}

    units = []
    coverage = [r for r in rules if r.kind == "coverage"]
    for ri, rule in enumerate(coverage):
        eligible = {
            site: sum(1 for p in roster.providers.values()
                      if site in p.sites and (not rule.skill or rule.skill in p.skills))
            for site in roster.sites
        }
        for day in range(roster.days):
            for shift in roster.shifts:
                for site in roster.sites:
                    if rule.covers_cell(roster, day, shift, site):
                        units.append((eligible[site], day, roster.shifts[shift][0], site, ri, shift))
    units.sort(key=lambda u: u[:5])

    unfilled = []
    filled_for = {}
    for _, day, _, site, ri, shift in units:
        rule = coverage[ri]
        while True:
            names = state.cells.get((day, shift, site), [])
            have = sum(1 for p in names if not rule.skill or rule.skill in roster.providers[p].skills)
            if have >= rule.count:
                break
            best = None
            reasons: Counter = Counter()
            for pid, p in roster.providers.items():
                if rule.skill and rule.skill not in p.skills:
                    reasons["skill:" + rule.skill] += 1
                    continue
                why = state.blocked_by(pid, day, shift, site)
                if why:
                    reasons[why] += 1
                    continue
                key = (len(state.by_provider[pid]), rank[pid])
                if best is None or key < best[0]:
                    best = (key, pid)
            if best is None:
                unfilled.append(Unfilled(rule.id, day, shift, site, rule.count, have, dict(reasons)))
                break
            a = Assignment(best[1], day, shift, site)
            state.add(a)
            filled_for[a] = rule.id

    everything = [a for mine in state.by_provider.values() for a in mine]
    everything.sort(key=lambda a: (a.day, roster.shifts[a.shift][0], a.site, a.provider))
    return Result(everything, unfilled, filled_for)
