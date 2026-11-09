"""Synthetic rosters and rule documents. No real providers, sites or rules."""

from __future__ import annotations

import datetime as dt
import random

START = dt.date(2026, 1, 5)  # a Monday
SITES = ["A", "B", "C"]


def roster_doc(seed: int, providers: int = 32, days: int = 28) -> dict:
    rnd = random.Random("roster-%d" % seed)
    people = []
    for i in range(providers):
        if i < 8:  # the pediatric-trained providers all work site A
            sites, skills = ["A", rnd.choice(["B", "C"])], ["peds"]
        else:
            sites, skills = rnd.sample(SITES, 2), []
        people.append({"id": "p%02d" % (i + 1), "sites": sorted(sites), "skills": skills})
    return {
        "start": START.isoformat(),
        "days": days,
        "shifts": {"day": {"start": 7, "hours": 12}, "night": {"start": 19, "hours": 12}},
        "sites": list(SITES),
        "providers": people,
    }


def rules_doc(seed: int, roster: dict) -> list:
    rnd = random.Random("rules-%d" % seed)
    rules = [
        {"id": "cover-2-everywhere", "kind": "coverage", "count": 2},
        {"id": "cover-peds-A-days", "kind": "coverage", "count": 1, "skill": "peds",
         "shift": "day", "site": "A"},
        {"id": "rest-11h", "kind": "min_rest_hours", "hours": 11},
        {"id": "max-6-per-week", "kind": "max_per_window", "max": 6, "window_days": 7},
        {"id": "max-3-nights-per-week", "kind": "max_per_window", "max": 3, "window_days": 7,
         "shift": "night"},
        {"id": "max-5-days-running", "kind": "max_consecutive_days", "max": 5},
    ]
    start = dt.date.fromisoformat(roster["start"])
    for person in roster["providers"]:
        if rnd.random() < 0.6:
            first = rnd.randrange(roster["days"] - 4)
            length = rnd.randint(2, 4)
            dates = [(start + dt.timedelta(days=first + k)).isoformat() for k in range(length)]
            rules.append({"id": "off-" + person["id"], "kind": "unavailable",
                          "provider": person["id"], "dates": dates})
    return rules
