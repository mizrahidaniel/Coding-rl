# SWEGraph v1 acceptance evidence

Reproduce locally:

```bash
python -m pip install pytest pyyaml
python -m pytest -q
rm -rf runs
python -m swegraph generate --num-tasks 30 --out runs/tasks --reward-config configs/reward_default.yaml
python -m swegraph batch --tasks runs/tasks --baseline oracle     --out runs/oracle_batch     --clean
python -m swegraph batch --tasks runs/tasks --baseline do_nothing --out runs/do_nothing_batch --clean
python -m swegraph batch --tasks runs/tasks --baseline naive      --out runs/naive_batch      --clean
```

## Test suite

`pytest -q` -> **11 passed**.

Coverage:
- task generation across all three families
- final report contains required fields
- oracle baseline ≥ 95 % hidden pass on a 12-task sample
- reward tracker awards each milestone once and charges negative milestones once
- reward config loads from JSON and YAML
- `do_nothing` fails hidden tests on every generated task and still emits a
  trajectory
- `naive` solves only the bug_injection family (no peek at
  `mutation_metadata`)
- oracle trajectory is multi-step (reproduce / read / patch / verify / finish)

## Batch metrics on 30 generated tasks (seed=7)

| baseline | public pass | hidden pass | final success | mean reward |
| --- | --- | --- | --- | --- |
| `oracle` | 30 / 30 | **30 / 30** | 30 / 30 | +4.54 |
| `naive` | 10 / 30 | **10 / 30** | 10 / 30 | +2.07 |
| `do_nothing` | 0 / 30 | **0 / 30** | 0 / 30 | +0.77 |

Oracle is well above the 95 % requirement; do_nothing fails every task as
required; naive cleanly partitions: it solves the 10 bug_injection tasks (its
heuristic catches the off-by-one in `percentile`) and fails the 10 config
renames + 10 feature additions.

## Spot-check: oracle replay

```
| # | action       | summary                                | tests | reward Δ | cum   |
| 0 | run_command  | python -m pytest -q tests              | 0p/1f | +0.79    | +0.79 |
| 1 | read_file    | stats_utils/core.py                    |       | +0.09    | +0.88 |
| 2 | replace_text | stats_utils/core.py revert injected... | 1p/0f | +1.69    | +2.57 |
| 3 | run_command  | python -m pytest -q tests              | 1p/0f | -0.01    | +2.56 |
| 4 | finish       | submit                                 |       | +3.98    | +4.54 |
```

`reward Δ = +3.98` on the `finish` step is the post-trajectory hidden-tests
award (+2.0) plus protected-files / no-test-deletion guard rewards merged
into the last logged step.

## Outputs per run

Every `python -m swegraph run` writes:
- `task.json`
- `trajectory.jsonl` — one record per action
- `final_report.json`
- `patch.diff` — `git diff` against the post-mutation initial commit
- `run.log`
- `replay.md` — human-readable trajectory + final report
