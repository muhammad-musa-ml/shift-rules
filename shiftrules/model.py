"""Roster, rule and schedule documents.

Loading is strict. A field the loader does not know, or a value that names
nothing in the roster, is an error that names the rule, so a typo in a
customer's rule file cannot turn into a rule that quietly does nothing.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import NamedTuple, Optional


class DocError(ValueError):
    """A document is wrong. The message names the rule or the field."""


class Assignment(NamedTuple):
    provider: str
    day: int
    shift: str
    site: str


@dataclass(frozen=True, eq=False)
class Provider:
    id: str
    sites: frozenset
    skills: frozenset


@dataclass(frozen=True, eq=False)
class Roster:
    start: dt.date
    days: int
    shifts: dict  # name -> (start hour, length in hours)
    sites: tuple
    providers: dict  # id -> Provider

    def weekday(self, day: int) -> int:
        return (self.start.weekday() + day) % 7

    def date_of(self, day: int) -> dt.date:
        return self.start + dt.timedelta(days=day)

    def shift_start(self, day: int, shift: str) -> int:
        return day * 24 + self.shifts[shift][0]

    def shift_end(self, day: int, shift: str) -> int:
        return self.shift_start(day, shift) + self.shifts[shift][1]


@dataclass(frozen=True, eq=False)
class Rule:
    id: str
    kind: str
    count: int = 0
    skill: str = ""
    limit: int = 0
    window_days: int = 0
    hours: int = 0
    shifts: Optional[frozenset] = None
    sites: Optional[frozenset] = None
    weekdays: Optional[frozenset] = None
    days: Optional[frozenset] = None
    providers: Optional[frozenset] = None

    def covers_cell(self, roster: Roster, day: int, shift: str, site: str) -> bool:
        if self.shifts is not None and shift not in self.shifts:
            return False
        if self.sites is not None and site not in self.sites:
            return False
        if self.weekdays is not None and roster.weekday(day) not in self.weekdays:
            return False
        if self.days is not None and day not in self.days:
            return False
        return True

    def applies_to(self, provider: str) -> bool:
        return self.providers is None or provider in self.providers


# kind -> (required fields besides id and kind, optional fields)
KINDS = {
    "coverage": ({"count"}, {"skill", "shift", "site", "weekdays", "dates"}),
    "unavailable": ({"provider"}, {"shift", "site", "weekdays", "dates"}),
    "max_per_window": ({"max", "window_days"}, {"provider", "shift", "site", "weekdays"}),
    "min_rest_hours": ({"hours"}, {"provider"}),
    "max_consecutive_days": ({"max"}, {"provider", "shift"}),
}


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise DocError("%s: cannot read (%s)" % (path, e.strerror or e))
    except json.JSONDecodeError as e:
        raise DocError("%s: not valid JSON (%s)" % (path, e))


def _keys(obj, where, required, optional=()):
    if not isinstance(obj, dict):
        raise DocError("%s: expected an object, got %s" % (where, type(obj).__name__))
    known = set(required) | set(optional)
    problems = []
    missing = sorted(set(required) - set(obj))
    if missing:
        problems.append("missing %s" % ", ".join(repr(k) for k in missing))
    for key in obj:
        if key not in known:
            problems.append("unknown field %r (known: %s)" % (key, ", ".join(sorted(known))))
    if problems:
        raise DocError("%s: %s" % (where, "; ".join(problems)))


def _int(value, where, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise DocError("%s: expected an integer from %d to %d, got %r" % (where, lo, hi, value))
    return value


def _names(value, where, allowed, what):
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not items:
        raise DocError("%s: expected a %s name or a non-empty list of them" % (where, what))
    for item in items:
        if not isinstance(item, str) or item not in allowed:
            raise DocError("%s: %r is not a known %s" % (where, item, what))
    return frozenset(items)


def load_roster(doc) -> Roster:
    _keys(doc, "roster", {"start", "days", "shifts", "sites", "providers"})
    try:
        start = dt.date.fromisoformat(doc["start"])
    except (TypeError, ValueError):
        raise DocError("roster.start: expected an ISO date, got %r" % (doc["start"],))
    days = _int(doc["days"], "roster.days", 1, 366)

    if not isinstance(doc["shifts"], dict) or not doc["shifts"]:
        raise DocError("roster.shifts: expected a non-empty object")
    shifts = {}
    for name, spec in doc["shifts"].items():
        where = "roster.shifts.%s" % name
        _keys(spec, where, {"start", "hours"})
        shifts[name] = (
            _int(spec["start"], where + ".start", 0, 23),
            _int(spec["hours"], where + ".hours", 1, 24),
        )

    sites = doc["sites"]
    if (not isinstance(sites, list) or not sites
            or not all(isinstance(s, str) for s in sites) or len(set(sites)) != len(sites)):
        raise DocError("roster.sites: expected a non-empty list of distinct names")

    if not isinstance(doc["providers"], list) or not doc["providers"]:
        raise DocError("roster.providers: expected a non-empty list")
    providers = {}
    for i, p in enumerate(doc["providers"]):
        where = "roster.providers[%d]" % i
        _keys(p, where, {"id", "sites"}, {"skills"})
        pid = p["id"]
        if not isinstance(pid, str) or not pid or pid in providers:
            raise DocError("%s: id must be a unique non-empty string, got %r" % (where, pid))
        where = "provider %r" % pid
        psites = _names(p["sites"], where + ".sites", sites, "site")
        skills = p.get("skills", [])
        if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
            raise DocError("%s.skills: expected a list of names" % where)
        providers[pid] = Provider(pid, psites, frozenset(skills))

    return Roster(start, days, shifts, tuple(sites), providers)


def _dates(value, where, roster):
    if not isinstance(value, list) or not value:
        raise DocError("%s: expected a non-empty list of ISO dates" % where)
    days = set()
    for item in value:
        try:
            d = dt.date.fromisoformat(item)
        except (TypeError, ValueError):
            raise DocError("%s: %r is not an ISO date" % (where, item))
        day = (d - roster.start).days
        if not 0 <= day < roster.days:
            raise DocError("%s: %s is outside the roster (%s for %d days)" % (
                where, item, roster.start.isoformat(), roster.days))
        days.add(day)
    return frozenset(days)


def _weekdays(value, where):
    items = [value] if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(items, list) or not items:
        raise DocError("%s: expected weekday numbers 0 (Monday) to 6 (Sunday)" % where)
    return frozenset(_int(v, where, 0, 6) for v in items)


def _rule(obj, index, roster, seen):
    if not isinstance(obj, dict):
        raise DocError("rules[%d]: expected an object" % index)
    rid = obj.get("id")
    if not isinstance(rid, str) or not rid:
        raise DocError("rules[%d]: id must be a non-empty string, got %r" % (index, rid))
    if rid in seen:
        raise DocError("rule %r: id used twice" % rid)
    seen.add(rid)
    where = "rule %r" % rid
    kind = obj.get("kind")
    if kind not in KINDS:
        raise DocError("%s: unknown kind %r (known: %s)" % (where, kind, ", ".join(sorted(KINDS))))
    required, optional = KINDS[kind]
    _keys(obj, where, {"id", "kind"} | required, optional)

    fields = {"id": rid, "kind": kind}
    if "count" in obj:
        fields["count"] = _int(obj["count"], where + ".count", 1, 50)
    if "max" in obj:
        fields["limit"] = _int(obj["max"], where + ".max", 0, 1000)
    if "window_days" in obj:
        fields["window_days"] = _int(obj["window_days"], where + ".window_days", 1, 366)
    if "hours" in obj:
        fields["hours"] = _int(obj["hours"], where + ".hours", 0, 168)
    if "skill" in obj:
        skill = obj["skill"]
        if not any(skill in p.skills for p in roster.providers.values()):
            raise DocError("%s.skill: no provider has the skill %r" % (where, skill))
        fields["skill"] = skill
    if "shift" in obj:
        fields["shifts"] = _names(obj["shift"], where + ".shift", roster.shifts, "shift")
    if "site" in obj:
        fields["sites"] = _names(obj["site"], where + ".site", roster.sites, "site")
    if "provider" in obj:
        fields["providers"] = _names(obj["provider"], where + ".provider", roster.providers, "provider")
    if "weekdays" in obj:
        fields["weekdays"] = _weekdays(obj["weekdays"], where + ".weekdays")
    if "dates" in obj:
        fields["days"] = _dates(obj["dates"], where + ".dates", roster)
    return Rule(**fields)


def load_rules(doc, roster: Roster) -> list:
    if not isinstance(doc, list):
        raise DocError("rules: expected a list")
    seen: set = set()
    return [_rule(obj, i, roster, seen) for i, obj in enumerate(doc)]
