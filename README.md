# shift-rules

I wrote a small scheduler for physician shifts in which the rules are data. It builds a four-week schedule from a rule file, checks the result with a second, separately written checker, and after a rule changes it rebuilds by keeping every assignment that is not part of a broken rule. I ran it on Python 3.13.5; it uses only the standard library.

All data here is synthetic. `shiftrules/synth.py` makes up the providers, sites and time off, so every number below describes my generator and says nothing about a real hospital group.

## Why

Three things looked hard to me about a scheduler whose rules change often.

- A new ask should be a rule in a file, not a special case in code. A rule is a JSON object with a kind (`coverage`, `unavailable`, `max_per_window`, `min_rest_hours`, `max_consecutive_days`) and optional scope fields (shift, site, weekdays, dates, provider; each kind accepts the ones that make sense for it). "At most 2 Friday or Saturday nights in 28 days" is one such object, and the benchmark uses it with no code written for it.
- A process should not fail silently. A rule file is refused if it has a misspelled key (the message names the rule, or the fields present when it is the `id` or `kind` that is misspelled), a key repeated in one object, a name or date the roster does not have, or a scope that matches no shift. `build` refuses rules with no coverage rule, since it would build nothing. A cell the builder cannot fill is reported with how many providers each rule, or a missing skill, ruled out (a provider is counted under the first rule that blocks them). `check` exits 1 on any broken rule or short cell.
- A changed rule should not reshuffle a month people have already seen.

## What is in it

- `model.py` loads the roster and the rules strictly. A schedule file may name things the roster lacks, and `check` reports them.
- `check.py` re-derives every rule from the finished list of assignments. Four built-in checks cannot be switched off by a rule file: credentialed sites only, no overlapping shifts, no duplicate assignment, no name the roster does not have.
- `engine.py` builds one assignment at a time. It takes first the cells that the fewest providers could ever work (credentialed at the site, with the skill if one is asked), then the earlier date, and gives each cell to the provider with the fewest shifts so far. Its incremental rule tests are written separately from `check.py`; the two share only the matching of a rule's scope and the shift times in `model.py`. `rebuild` asks the checker what the changed rules forbid, removes assignments one at a time (the one that leaves the fewest broken rules, the latest on a tie), then fills what is open with everything else held fixed. Each removal and addition is printed with the rule that caused it; an addition shows the coverage rule it fills.
- `synth.py` generates a roster and rules from a seed, `bench.py` measures, `cli.py` is the command line.

## Run it

```
python -m unittest
python -m shiftrules generate --seed 1 --out demo
python -m shiftrules build demo/roster.json demo/rules.json --out demo/schedule.json
python -m shiftrules check demo/roster.json demo/rules.json demo/schedule.json
python tools/demo.py --out results/demo.txt
python -m shiftrules.bench --out results/benchmark.txt
python tools/prove_tests_bite.py --out results/tests-bite.txt
```

`--seed` on `generate` seeds the made-up documents. `build` and `rebuild` take their own `--seed` for the tie-break, default 0. `generate` will not overwrite `roster.json` or `rules.json` without `--force`, and `rebuild` will not write over the schedule it reads.

`tools/demo.py` runs the rest of the example in a temporary folder: it appends one time-off rule to `rules.json`, checks the old schedule against it, rebuilds, and checks again. `results/demo.txt` is its output. The rebuild step printed:

```
removed 2026-01-05 day A p04 (p04-away)
removed 2026-01-11 night A p04 (p04-away)
added 2026-01-05 day A p28 (cover-2-everywhere)
added 2026-01-11 night A p01 (cover-2-everywhere)
2 removed, 2 added, 0 unfilled cells
```

Exit codes are 0 for done, 1 for broken rules or unfilled cells, 2 for a document that could not be loaded or a file that could not be written.

## Results

`python -m shiftrules.bench` builds 20 seeded schedules, 32 providers, 3 sites, 28 days, two shifts a day. Each needs 336 assignments. It applies three rule changes to each and compares `rebuild` with building again from scratch, which is the same builder run again with the same seed. A move is an assignment that is in the old schedule and not in the new one. The table is copied from `results/benchmark.txt`: mean over 20 seeds, with the standard deviation and the range.

| Rule change | Rebuild moves | From scratch moves | Rebuild unfilled | Scratch unfilled |
|---|---|---|---|---|
| Four providers off for one week | 10.9 (sd 2.0, 7 to 14) | 93.8 (sd 21.4, 63 to 142) | 0.0 (sd 0.0, 0 to 0) | 0.0 (sd 0.0, 0 to 0) |
| Run limit 5 days to 3 days | 2.9 (sd 1.9, 0 to 8) | 15.2 (sd 19.8, 0 to 91) | 0.0 (sd 0.0, 0 to 0) | 0.0 (sd 0.0, 0 to 0) |
| At most 2 Friday or Saturday nights per 28 days | 7.2 (sd 2.0, 3 to 12) | 27.1 (sd 10.1, 10 to 53) | 0.1 (sd 0.3, 0 to 1) | 0.1 (sd 0.3, 0 to 1) |

The base schedule had no unfilled cell and no broken rule in any seed. Building it took 289 ms on average (244 to 357), and a rebuild took 189 to 468 ms on average depending on the change.

Every schedule the benchmark produces is checked, and it stops if the checker finds a broken rule, or if the cells the checker finds short are not exactly the cells the builder reported as unfilled. With 20 providers instead of 32 the builder left 9.1 of 196 coverage requirements unfilled on average (sd 3.2, 4 to 14), listed each, and the most common blockers were `rest-11h` (37.5% of provider-by-cell blocks), `builtin:credentialed` (20.1%), `max-3-nights-per-week` (17.0%) and `builtin:overlap` (15.9%).

The tests check three things.

- A test draws 60 random rule sets and 150 random attempted assignments for each, and requires the builder's incremental test and the checker to agree on every attempt: if the builder accepts it the checker finds nothing wrong with the result, and if it refuses it the checker finds the rule the builder named.
- Each rule kind has boundary cases (a rest gap equal to the minimum, a window at its maximum, a run at its maximum), and the scope fields appear in both the unit tests and the random rule sets.
- `tools/prove_tests_bite.py` breaks the code on a copy in 40 ways, one line at a time, and every break fails at least one test (`results/tests-bite.txt`).

## What this does not show

- The roster, the rules and the time off are made up by me. A real group has rules I have not seen, and a rule of a kind not on the list above needs code.
- I wrote the checker and the builder from the same reading of each rule. The agreement test shows that the two implementations agree, not that a rule means what a hospital means by it. A mistake in the scope matching or the shift times, which both use, would not be found by that test.
- The builder is greedy with no backtracking, so it can leave a cell unfilled that a better solver would fill. The "from scratch" column is this builder run again, not another product, and a different tie-break could move fewer assignments than 93.8.
- `rebuild` chooses what to remove with the same kind of local rule, so it is not the smallest possible change either.
- There are no preferences, swaps, payroll, storage or interface here, and nothing about a schedule longer than 28 days or a group larger than 32 providers.
- The timings come from one Windows machine, one run of the benchmark, and are a rough guide only.

## Layout

- `shiftrules/`: `model.py`, `check.py`, `engine.py`, `synth.py`, `bench.py`, `cli.py`
- `tests/`, `tools/` (`prove_tests_bite.py`, `demo.py`), `results/`

MIT licence.
