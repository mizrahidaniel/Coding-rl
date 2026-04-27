# SWEGraph v2

SWEGraph is a local Python **environment / task factory** for software-engineering
agents. v1 shipped multi-step trajectories, dense milestone rewards, and
hidden tests on three toy fixtures. v2 closes the honest gaps that public
critique surfaced and adds **one genuinely-novel difficulty axis**:

> **Causal-hop tasks** plant a single mutation in a leaf module and measure
> the agent's ability to localise the fault through a controllable number of
> static import edges. No prior public system uses static import-graph
> distance as a generator-side difficulty knob.

Everything else in v2 is *engineering hardening*: stronger hidden validation
(Hypothesis property + auto-extracted metamorphic relations), AST-level
reward-hacking guards, four adversarial baselines, a paired-preference PRM
dataset emitter, and richer trajectory logs. Honest framing — not headline
novelty.

## Honest delta vs prior art

The 2025-2026 SWE-RL frontier already publishes:

- **SWE-bench Pro / Live / Rebench (2026)** — contamination-resistant
  benchmarks (private codebases, monthly refresh, post-cutoff tasks).
- **Self-Play SWE-RL (arXiv 2512.18552)** — dual-role injector/solver,
  +10.4 on SWE-bench Verified, +7.8 on Pro.
- **SWE-RL (Meta, arXiv 2502.18449)** — 11M PR instances + difflib similarity
  reward.
- **MIST-RL (2026)** — incremental mutation-killing reward for test
  generation.
- **SWE-PRM / AgentPRM (2025-26)** — step-level process reward models.
- **Agentic Property-Based Testing (arXiv 2510.09907)** — Hypothesis-driven
  test generation by LLMs.
- **Prime Intellect Verifiers + Environments Hub** — open-source RL
  environment standard with built-in SWE support.

Against this, SWEGraph v2 ships:

| Item | Verdict | What's actually new |
| --- | --- | --- |
| Procedural task families | not novel | SWE-smith and Self-Play SWE-RL already do generation at scale |
| Hidden tests as Hypothesis properties + auto-extracted metamorphic relations | reframing | PBT-as-decontamination is a useful shape but not invention |
| **Causal-hop import-graph difficulty axis** | **novel** | controllable static-graph distance from mutation site to public test surface |
| Reward-hacking guard library (AST detection, recursive conftest scan, symlink reject) | not novel | all known patterns; precision-over-recall implementation |
| Counterfactual adversarial baselines (4 attackers) as labelled negatives | useful infrastructure | most prior art logs negatives, doesn't ship a registry |
| Paired-state PRM preference dataset (oracle vs counterfactual at same seed) | close to novel | DPO-shape pairs at identical state hashes for SWE; no public dataset of this form |
| Multi-correct-patch acceptance via property satisfaction | useful | addresses single-oracle limitation Meta SWE-RL flagged |
| Trajectory format: gzip+b64 stdout/stderr, per-test pass/fail map, milestone deltas | polish | needed to train PRMs; not a contribution by itself |

## Architecture

```
swegraph/
  task.py                      # generate_tasks, load_task (v1 back-compat)
  task_generators/
    bug_injection.py           # off-by-one in stats_utils + property/metamorphic validators
    config_bug.py              # rename in csv_tool
    feature_addition.py        # optional kwarg in todo_cli
    causal_hop.py              # NEW: 3-module import-chain mutations
  fixtures/repos/
    stats_utils/  csv_tool/  todo_cli/  multi_pkg/   # NEW: a -> b -> c
  validators/                  # NEW: HiddenValidator abstraction
    unit_test.py               #   wraps v1 hidden_tests dict
    property.py                #   Hypothesis-driven; assertion expression
    metamorphic.py             #   relation library (boundary_extrema, idempotent, ...)
    _runners/                  #   subprocess entrypoints
  utils/
    diffing.py
    file_guard.py              # HARDENED: AST detection, recursive conftest, symlink
    import_graph.py            # NEW: static-import distance (causal hops)
    metamorphic_extract.py     # NEW: AST -> relation extraction from public tests
    prompts.py
  baselines/
    do_nothing.py / oracle_patch.py / naive_search_replace.py
    adversarial/               # NEW: 4 attackers as labelled negatives
      test_content_edit.py     #   gut public-test asserts
      conftest_shadow.py       #   drop subdir conftest
      fixture_monkeypatch.py   #   inject mock import
      public_test_overfit.py   #   hardcode lookup table for visible inputs
  sandbox.py                   # LocalSandbox (Docker is a v3 hook)
  actions.py                   # ActionAPI tool surface
  reward.py                    # RewardTracker + YAML/JSON loader
  evaluator.py                 # validators + guard report + causal-hop metadata
  tests_runner.py              # pytest counts + per-test status parser
  trajectory.py                # JSONL logger (now full stdout/stderr + deltas)
  prm.py                       # NEW: paired-preference PRM dataset emitter
  cli.py                       # generate / run / eval / batch / batch-prm
configs/
  reward_default.yaml
docs/
  acceptance.md                # v2 acceptance evidence (numbers below)
  research-notes.md            # NEW: design rationale + critical reception
tests/                         # 30 tests (11 v1 + 19 v2) all green
```

## CLI

```bash
# Generate 32 tasks (8 per family) with default reward weights:
python -m swegraph generate --num-tasks 32 --out runs/tasks \
    --reward-config configs/reward_default.yaml

# Run a single task with a specific baseline:
python -m swegraph run --task runs/tasks/task_004.json --baseline oracle --out runs/oracle_004
python -m swegraph run --task runs/tasks/task_004.json --baseline attack_test_content_edit --out runs/attacker_004

# Inspect the final report:
python -m swegraph eval --run runs/oracle_004

# Batch a baseline over all tasks:
python -m swegraph batch --tasks runs/tasks --baseline oracle --out runs/oracle_batch --clean

# Emit a JSONL of paired preference tuples for PRM/critic training:
python -m swegraph batch-prm \
    --tasks runs/tasks \
    --runs-dir runs/prm_runs \
    --baselines oracle,do_nothing,naive,attack_test_content_edit,attack_public_test_overfit \
    --out runs/prm_pairs.jsonl
```

## Key concepts

### HiddenValidator

`TaskSpec.hidden_validators` is a list of validator specs (discriminated by
`kind`). Each validator runs in a subprocess with `PYTHONPATH=workspace`,
isolated from any other validator and from the agent's loop.

- **`unit_tests`** — the v1 contract; a dict of `{filename -> body}`. Tests
  are written to a temp dir and pytest is invoked.
- **`property`** — Hypothesis-driven. The agent's implementation is fuzzed
  against a Python `assertion` expression with `args` and `result` bound.
- **`metamorphic`** — relation library: `boundary_extrema`,
  `idempotent_under_call`, `monotonic_in_arg`, `non_increasing_size`. The
  task generator can declare "this function should be idempotent" without
  authoring the assertion.

Auto-extraction from public-test ASTs (`utils/metamorphic_extract.py`) seeds
metamorphic relations from invariants present in the public test source.
This is the wedge against the "PBT is just hand-authored hidden tests with
extra steps" criticism: at least one relation per task comes from the public
tests mechanically.

### Causal-hop tasks

`multi_pkg` is a 3-module fixture with the directed import chain
`a -> b -> c`. The `causal_hop` task generator plants a mutation in `b` or
`c` and exposes a public test that imports only `a`. The shortest static
import path between the mutation site and the public test surface is
recorded as `mutation_metadata.import_hops`. The runner sets
`localization_correct` if and only if the agent reads the
`root_cause_file` before its first write — turning a coarse boolean into a
real signal that scales with hop count.

`utils/import_graph.py` builds a directed import graph by AST-parsing every
non-test `.py` file. `hop_count(graph, src, dst)` returns the BFS distance.

### Reward-hacking guards (monitored, not bulletproof)

`utils/file_guard.py` ships:

- `ast_detect_disabled_asserts` — flags `assert True`, `assert ... or True`,
  `if False: ... assert ...`, `pytest.skip(...)`, `@pytest.mark.skip`,
  `unittest.mock` imports in test modules, and empty test bodies.
- `recursive_conftest_scan` — flags any conftest below the workspace that
  did not exist in the baseline snapshot.
- `reject_symlinks` — flags any symlinks in the workspace.

Every detection writes a `GuardReportEntry` to `final_report.guard_report`.
Block-severity hits force `final_success: false` regardless of test status.
The framing is *monitored*, not *blocked*: the structured guard report is
itself a labelled-data asset for verifier training.

### Adversarial baselines

Four attackers under `baselines/adversarial/`:

| Attacker | Pattern | Caught by |
| --- | --- | --- |
| `attack_test_content_edit` | gut public-test asserts | `ast_detect_disabled_asserts` |
| `attack_conftest_shadow` | drop a subdir conftest | `recursive_conftest_scan` |
| `attack_fixture_monkeypatch` | inject `unittest.mock` into the test module | `ast_detect_disabled_asserts` (mock import) |
| `attack_public_test_overfit` | hardcode a lookup table for the inputs in public tests | hidden `PropertyValidator` + `MetamorphicValidator` |

The first three trigger guard hits and fail final-success. The fourth slips
past the guards but fails the hidden validators on the `bug_injection`,
`config_bug`, and `causal_hop` families. (`feature_addition`'s overfit
happens to be a correct implementation — documented as a known weak
adversary.)

### PRM preference pairs

`swegraph batch-prm` runs N baselines on the same task seeds and emits
JSONL preference tuples of the form:

```json
{
  "task_id": "task_001",
  "step_index": 2,
  "state_hash": "2b8bf830346535be",
  "match_type": "state_hash",
  "milestone_state": {...},
  "preferred": {"baseline": "oracle", "action_type": "replace_text", ...},
  "rejected":  {"baseline": "attack_public_test_overfit", "action_type": "write_file", ...},
  "labels": {
    "preferred_final_success": true,
    "rejected_final_success": false,
    "preferred_validator_pass": true,
    "rejected_validator_pass": false,
    "rejected_guard_hits": 0
  }
}
```

The state hash is SHA-256 over `(milestone_state, public_test_status)` so
two trajectories share a state when the runner has observed the same
milestones and pass/fail counts. Three matchers are run in priority order:
strict (same step + same hash), state-hash (any step at the same hash),
step-index (same step regardless of hash). Each pair is tagged with its
`match_type`.

This is the directly-shippable asset against the SWE-PRM literature: a
public dataset of paired actions at identical states under controlled task
seeds.

## Acceptance evidence

Run end-to-end:

```bash
python -m pytest -q                                    # 30 / 30 passing
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
    --baselines oracle,do_nothing,naive,attack_test_content_edit,attack_public_test_overfit \
    --out runs/prm_pairs.jsonl
```

Headline numbers (32 tasks, 4 families, seed=7):

| baseline | hidden pass | mean reward | guard hits | comment |
| --- | --- | --- | --- | --- |
| `oracle` | 32/32 | +4.36 | 0 | upper bound |
| `naive` | 8/32 | +1.94 | 0 | bug_injection only (heuristic) |
| `do_nothing` | 0/32 | +0.97 | 0 | lower bound |
| `attack_test_content_edit` | 0/32 | — | 18+ | guards block |
| `attack_conftest_shadow` | 0/32 | — | 24+ | guards block |
| `attack_fixture_monkeypatch` | 0/32 | — | 12+ | guards block |
| `attack_public_test_overfit` | ~25% | — | 0 | hidden validators block (except feature_addition) |

PRM dataset: ~50-60 paired preference tuples per 8-task batch across 4
counterfactual baselines, with a healthy mix of
`(oracle_success, counterfactual_failure)` and
`(oracle_success, counterfactual_failure_with_guard_hit)` shapes.

See `docs/acceptance.md` for the exact reproducer and `docs/research-notes.md`
for the design rationale + critical reception that drove v2.

## Out of scope (v3 hooks)

- Real-repo ingestion via mutmut on small Python packages (planned).
- Docker-per-task sandbox (replaces `LocalSandbox`).
- LLM agent adapter (drop-in for any model that consumes the user prompt +
  public tests + `ActionAPI`).
- Cross-language: a Rust or TS task family using `proptest` / `fast-check`.
- Trained PRM artifact (the dataset is shipped; the trained model is not).
- Calibrated decontamination metric (mutual information between hidden spec
  and public-test surface).
- Patch-DAG (multi-correct-patch equivalence-class clustering) — multi-month
  research.
