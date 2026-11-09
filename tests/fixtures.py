"""Small rosters shared by the tests. 2026-01-05 is a Monday."""

from shiftrules.model import Assignment, load_roster, load_rules


def roster_doc(**over):
    doc = {
        "start": "2026-01-05",
        "days": 14,
        "shifts": {"day": {"start": 7, "hours": 12}, "night": {"start": 19, "hours": 12}},
        "sites": ["A", "B"],
        "providers": [
            {"id": "p1", "sites": ["A", "B"], "skills": ["peds"]},
            {"id": "p2", "sites": ["A", "B"]},
            {"id": "p3", "sites": ["A"]},
        ],
    }
    doc.update(over)
    return doc


def make(rule_docs, **roster_over):
    roster = load_roster(roster_doc(**roster_over))
    return roster, load_rules(rule_docs, roster)


def A(provider, day, shift="day", site="A"):
    return Assignment(provider, day, shift, site)
