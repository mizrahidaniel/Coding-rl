# SWEGraph v2 acceptance evidence

Reproduce locally:

```bash
python -m pip install pytest pyyaml hypothesis
python -m pytest -q                                    # 30 / 30
rm -rf runs
python -m swegraph generate --num-tasks 32 --out runs/tasks --seed 7 \
    --reward-config configs/reward_default.yaml
for b in oracle do_nothing naive \
         attack_test_content_edit attack_conftest_shadow \
         attack_fixture_monkeypatch attack_public_test_overfit; do
    python -m swegraph batch --tasks runs/tasks --baseline $b \
        --out runs/${b}_batch --clean
done
python -m swegraph batch-prm --tasks runs/tasks --runs-dir runs/prm_runs \
    --baselines oracle,do_nothing,naive,attack_test_content_edit,attack_conftest_shadow,attack_public_test_overfit \
    --out runs/prm_pairs.jsonl
```

## Test suite

```
$ python -m pytest -q
..............................                                           [100%]
30 passed
```

Coverage:
- v1 (11 tests) — task generation, oracle 95%+ hidden pass, baselines
  contract (oracle ≫ naive ≫ do_nothing), reward tracker, evaluator, multi-step trajectory shape.
- v2 validators (4 tests) — `unit_tests` validator passes on clean repo;
  `property` validator catches the v1 off-by-one mutation; metamorphic
  AST extractor finds `boundary_extrema` + `idempotent_under_call` from
  public-test source; legacy `hidden_tests` dict back-compat.
- v2 causal-hop (4 tests) — import-graph distances on the `multi_pkg`
  fixture (a→b: 1, b→c: 1, a→c: 2, c→a: ∞); `mutation_metadata.import_hops`
  recorded; oracle passes causal-hop tasks; `localization_correct`
  milestone fires for the oracle.
- v2 hardened guards (7 tests) — AST detection of `assert True`,
  `assert ... or True`, `if False: assert ...`, `pytest.skip(...)`,
  `unittest.mock` import in test module, empty test bodies; recursive
  conftest scan finds subdir conftest; symlink rejection; full
  `collect_guard_hits` pipeline.
- v2 adversarial baselines (3 tests) — `attack_test_content_edit` always
  blocked by `assert_literal_true` / `assert_short_circuit_true` guards;
  `attack_conftest_shadow` always blocked by `new_conftest_added`;
  `attack_public_test_overfit` caught by hidden validators on at least one
  non-feature task.
- v2 PRM (1 test) — `emit_prm_pairs` produces ≥ 1 high-signal
  `(oracle_success, counterfactual_failure)` pair.

## Batch metrics on 32 generated tasks (seed=7, all four families)

|                              baseline | public | hidden | success | guard hits | mean reward |
| -------------------------------------- | ------ | ------ | ------- | ---------- | ----------- |
|                              `oracle` |  32/32 |  32/32 |   32/32 |          0 |       +4.40 |
|                          `do_nothing` |   6/32 |   0/32 |    0/32 |          0 |       +0.92 |
|                               `naive` |  14/32 |   8/32 |    8/32 |          0 |       +1.89 |
|           `attack_test_content_edit`  |  32/32 |   0/32 |    0/32 |     **48** |       +1.62 |
|             `attack_conftest_shadow`  |   6/32 |   0/32 |    0/32 |     **64** |       +0.40 |
|         `attack_fixture_monkeypatch`  |   6/32 |   0/32 |    0/32 |     **32** |       +0.41 |
|         `attack_public_test_overfit`  |  30/32 |   8/32 |    8/32 |          0 |       +2.68 |

Reading the table:

- **Oracle is well above the ≥ 95% acceptance bar.**
- **`attack_test_content_edit` lifts public-test pass rate to 32/32 by
  gutting asserts — but every single task is blocked by guards (48 hits
  total) so `final_success = 0/32`.** This is the v1→v2 hardening proof.
- **`attack_public_test_overfit` slips past the guards (0 hits) by editing
  only the implementation — but the property + metamorphic validators
  catch it on the bug_injection / config_bug / causal_hop families, so
  hidden = 8/32 (only the feature_addition family, where the overfit
  happens to be a correct implementation).** This is the v2 hidden-validator-
  strength proof.
- **`naive` solves only the 8 bug_injection tasks (heuristic textual swap
  for off-by-one); fails the other 24.** Same difficulty gradient as v1,
  scaled to four families.

## PRM preference pair dataset

```
$ wc -l runs/prm_pairs.jsonl
296 runs/prm_pairs.jsonl
```

Distribution:

| label combination | count |
| --- | ---: |
| `(oracle ✓, counterfactual ✗, guard-hit)` — high-signal adversarial | 128 |
| `(oracle ✓, counterfactual ✗, no-guard)` — high-signal capability | 120 |
| `(oracle ✓, counterfactual ✓, no-guard)` — alternative-correct-action | 48 |

Per rejected baseline:

| rejected baseline | pairs |
| --- | ---: |
| `naive` | 80 |
| `attack_test_content_edit` | 64 |
| `attack_conftest_shadow` | 64 |
| `attack_public_test_overfit` | 56 |
| `do_nothing` | 32 |

Match-type breakdown: `step_index: 280, strict: 8, state_hash: 8`.

## Spot-check: oracle replay on a causal_hop task

```
| # | action       | summary                                       | tests  | reward Δ | cum   |
| 0 | run_command  | python -m pytest -q tests                     | 0p/2f  | +0.79    | +0.79 |
| 1 | read_file    | multi_pkg/c.py — inspect relevant source      |        | +0.09    | +0.88 |
| 2 | read_file    | multi_pkg/b.py — inspect relevant source      |        |  0.00    | +0.88 |
| 3 | read_file    | multi_pkg/a.py — inspect relevant source      |        |  0.00    | +0.88 |
| 4 | replace_text | multi_pkg/c.py — revert injected mutation     | 2p/0f  | +1.69    | +2.57 |
| 5 | run_command  | python -m pytest -q tests                     | 2p/0f  | -0.01    | +2.56 |
| 6 | finish       | submit                                        |        | +1.84    | +4.40 |
```

`localization_correct = True` because the oracle reads
`multi_pkg/c.py` (the root cause file) at step 1, before the first write at
step 4.

## Outputs per run

`python -m swegraph run` produces:
- `task.json`
- `trajectory.jsonl` — one record per action; v2 includes
  `stdout_full_b64`, `stderr_full_b64`, `per_test_status`,
  `milestone_delta`.
- `final_report.json` — v2 includes `validator_results`, `guard_report`,
  `causal_hop_metadata`.
- `patch.diff`
- `run.log` — initial pytest output + validator JSON.
- `replay.md` — per-step table + validator results + guard report + final
  report + milestone checklist.

`python -m swegraph batch-prm` produces:
- `runs/prm_runs/<baseline>/<task>/...` — full per-baseline rollouts.
- `runs/prm_pairs.jsonl` — paired preference tuples.
