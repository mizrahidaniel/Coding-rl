# SWEGraph v1

SWEGraph is a local Python **environment / task factory** for software-engineering
agents. v1 is intentionally not a full LLM agent. It focuses on the asset that
actually matters for SFT, RL, and verifier training: **decontaminated synthetic
tasks with hidden validators, dense milestone rewards, and full multi-step
trajectory logs.**

It is the SWE-side mirror of the graph-backed computer-use environments the
project started with.

| | GUI / computer-use side | SWEGraph side |
| --- | --- | --- |
| state | UI screen + app graph | repo + tests + git + runtime |
| action | click / type / hotkey | `run_command` / `read_file` / `write_file` / `apply_patch` / `replace_text` / `finish` |
| goal | hidden target screen | hidden validator tests pass |
| reward | BFS progress, invalid action, no loops, no collateral | milestone progress, public test progress, no collateral, no test deletion |
| evaluator's edge | hidden state graph | hidden mutation site, hidden tests, file/test guards |

## Why this exists (and what is *not* novel)

Closely-related prior art:
- **SWE-bench / SWE-bench Verified / SWE-bench Pro** — real GitHub-issue benchmarks
  with fail-to-pass / pass-to-pass evaluation. Defines today's SWE eval pattern but
  is increasingly contaminated and only emits final pass/fail.
- **SWE-Gym** — 2,438 real Python tasks with envs + tests; trains agents and
  verifiers from trajectories. Demonstrates trajectory-data value but uses real
  repos (limited supply, contamination risk).
- **SWE-smith** — generates 50k+ task instances from 128 repos and trains a
  32B agent to ~40% on SWE-bench Verified. Closest to "unlimited synthetic SWE
  data" but rewards remain final-test pass/fail.
- **Self-play SWE-RL / automated bug injection** — same family as our
  `bug_injection` task generator.
- **OpenHands / SWE-agent** — open-source agent scaffolds; potential runners.
- **OpenAI Codex** — publicly described as RL-trained on real SWE tasks in
  isolated cloud sandboxes.
- **OpenAI Reinforcement Fine-Tuning / Programmable Graders** — the
  reward-model side of this same shape.
- **Prime Intellect Verifiers / Environment Hub** — packaging spec for
  RL/eval environments (dataset + harness + reward).
- **Mechanize** — commercial SWE RL environments / evals.

The wedge SWEGraph aims to occupy is narrower than "we built coding-agent RL
environments." It is:

1. **Procedural task families** with controllable difficulty, not real-world
   issues (avoids contamination, infinite supply, no scraping cost).
2. **Realistic-user-style prompts**, not formal GitHub issue text.
3. **Hidden formal spec + hidden validator tests** kept off-disk during agent
   rollouts (written to a temp dir, run with `PYTHONPATH=workspace`).
4. **Dense workflow milestones**, not just final pass/fail:
   reproduce → inspect → patch → re-run → submit, each with its own reward.
5. **Reward-hacking guards**: detect deleted tests, edited `pytest.ini` /
   `pyproject.toml`, protected-file changes, unrelated churn.
6. **Action-API-level trajectories** suitable for SFT data and verifier/critic
   training, not just final patch diffs.
7. **Modular**: real-repo ingestion, Docker sandbox, OpenHands runner, and
   Prime-Verifiers export are deliberately left as v2 hooks.

If a competing system already does (1)+(3)+(4)+(5)+(6) on the same surface,
SWEGraph collapses to a polished implementation rather than a novel asset.
That is an honest framing: the differentiation is **density of evaluation
signal + hidden state + procedural generation**, not the existence of an SWE
RL env.

## What v1 includes

- **Task factory** (`swegraph/task.py`, `swegraph/task_generators/`) — three
  families today: `bug_injection`, `config_bug`, `feature_addition`. Each
  emits a `TaskSpec` with user prompt, hidden formal spec, public + hidden
  tests, mutation/oracle metadata, allowed/protected file lists, and an
  embedded reward config.
- **Toy fixture repos** (`swegraph/fixtures/repos/`):
  `stats_utils`, `csv_tool`, `todo_cli`. Real-repo ingestion is a v2 hook.
- **Sandbox** (`swegraph/sandbox.py`) — copies a fixture into a temp
  workspace, runs commands with timeout, never edits the original fixture.
  Initialised as a git repo so true diffs are computable.
- **Action API** (`swegraph/actions.py`) — `run_command`, `read_file`,
  `write_file`, `apply_patch`, `replace_text`, `finish`.
- **Multi-step runner** (`swegraph/cli.py`) — drives a baseline as an
  iterator of `Action` records. Each action is logged as one
  `TrajectoryStep` with the public-test status snapshot, milestone state,
  per-component reward, cumulative reward, and changed-file list.
- **Reward engine** (`swegraph/reward.py`) — milestone-once awards,
  one-shot negative-milestone penalties, per-step cost, YAML/JSON config
  loadable via `--reward-config`.
- **Evaluator** (`swegraph/evaluator.py`) — runs public + hidden tests at
  end-of-trajectory, tracks protected-file edits, deleted/disabled tests,
  unrelated file churn, relevant-file inspection, patch size, and final
  success.
- **Trajectory logger** (`swegraph/trajectory.py`) — JSONL one record per
  action. Milestone snapshot and reward delta per step.
- **Baselines** (`swegraph/baselines/`):
  - `oracle` — uses hidden oracle metadata; upper bound. ≥95% hidden pass.
  - `do_nothing` — runs tests, finishes; lower bound, must fail.
  - `naive` — heuristic textual swaps based on failing-test tracebacks
    (no access to mutation_metadata). Solves easy boundary bugs only.
- **Replay** — every run produces `task.json`, `trajectory.jsonl`,
  `final_report.json`, `patch.diff`, `run.log`, and a human-readable
  `replay.md` with a step-by-step table.

## CLI

```bash
python -m swegraph generate --num-tasks 30 --out runs/tasks
python -m swegraph generate --num-tasks 30 --out runs/tasks \
    --reward-config configs/reward_default.yaml

python -m swegraph run --task runs/tasks/task_001.json --baseline oracle --out runs/oracle_001
python -m swegraph run --task runs/tasks/task_001.json --baseline naive  --out runs/naive_001  --mode benchmark

python -m swegraph eval --run runs/oracle_001

python -m swegraph batch --tasks runs/tasks --baseline do_nothing --out runs/do_nothing_batch --clean
```

`--mode benchmark` withholds the hidden-tests-pass reward award until
final eval. `--mode training` (default) lets the policy see the dense
hidden-test signal.

## Example outputs (abridged)

### Generated task (`runs/tasks/task_001.json`)

```json
{
  "task_id": "task_001",
  "repo_id": "stats_utils",
  "task_family": "bug_injection",
  "user_prompt": "Something's not right with percentile. Boundary indexes look broken. Please patch it.",
  "hidden_formal_spec": "Edge cases including empty input and interior indexes must match (len-1)*p/100.",
  "public_tests": ["tests/test_public_bug.py"],
  "hidden_tests": {"tests/test_hidden_bug.py": "..."},
  "mutation_metadata": {"type": "replace_text", "path": "stats_utils/core.py", "relevant_files": ["stats_utils/core.py"]},
  "oracle_metadata": {"patch_type": "reverse_mutation"},
  "allowed_files": ["stats_utils/core.py", "tests/test_public_bug.py"],
  "protected_files": ["pyproject.toml", "pytest.ini"]
}
```

### Trajectory step (one of N)

```json
{
  "step_index": 2,
  "action_type": "replace_text",
  "edit_metadata": {"path": "stats_utils/core.py", "matched": true, "note": "revert injected mutation"},
  "changed_files": ["stats_utils/core.py"],
  "public_test_status": {"passed": 1, "failed": 0, "all_passed": true},
  "milestone_state": {"public_tests_pass": true, ...},
  "reward_components": {"public_tests_improved": 0.5, "public_tests_pass": 1.0, "step_cost": -0.01, "_step_total": 1.69, "_cumulative": 2.57}
}
```

### Final report

```json
{
  "public_tests_pass": true,
  "hidden_tests_pass": true,
  "final_success": true,
  "protected_files_changed": [],
  "tests_deleted_or_disabled": false,
  "unrelated_files_changed": [],
  "relevant_files_inspected": true,
  "bug_reproduced": true,
  "reward_total": 4.54,
  "trajectory_length": 5
}
```

### Baseline behaviour on 6 generated tasks

| baseline | hidden pass | mean reward | notes |
| --- | --- | --- | --- |
| `oracle` | 6/6 | +4.54 | upper bound |
| `naive` | 2/6 | mixed | solves bug_injection only |
| `do_nothing` | 0/6 | +0.77 | guard rewards only |

## How v1 maps to SFT / RL / verifier training

- **SFT data**: oracle trajectories already provide multi-step
  reproduce → inspect → patch → verify → finish traces. Convert each
  `TrajectoryStep` to a tool-use turn.
- **RL data**: every step has a per-component reward and cumulative reward.
  An RL trainer can either use `_step_total` per step or `final_success` +
  shaped intermediate rewards.
- **Verifier / critic data**: the trajectory + final report is exactly the
  shape needed to train an outcome predictor (success / collateral /
  reward-hacking). Negative trajectories from `naive` and `do_nothing`
  (and future adversarial public-test-overfit baselines) seed the
  contrastive pairs.
- **Benchmark mode**: drop hidden-tests reward from the trajectory and only
  count final success — equivalent to SWE-bench-style eval but with
  procedural decontamination.

## Acceptance criteria status

- `pytest` passes (11 / 11 tests).
- `python -m swegraph generate --num-tasks 30 --out runs/tasks` works.
- `python -m swegraph run --task <task> --baseline oracle --out <dir>` works.
- `python -m swegraph eval --run <dir>` works.
- Oracle baseline passes hidden tests on **30 / 30 = 100 %** of generated
  tasks (sample command + numbers in
  `docs/acceptance.md`).
- `do_nothing` baseline fails 30 / 30 hidden-test runs but always emits a
  valid trajectory.
- Reward components and milestones are visible in `final_report.json` and
  `replay.md`.
- Public / hidden test separation: hidden tests are written to a temp dir
  per run and never live in the workspace.

## Next steps to make this research- and product-worthy

1. **Real-repo ingestion** — pluggable repo loader (Git URL, commit pin,
   pre-built virtualenv) so the same harness operates on SWE-Gym /
   SWE-smith style instances.
2. **Docker sandbox** — replace `LocalSandbox` with a per-task container
   that pins Python version and dependencies; needed for cross-language
   support.
3. **More task families** — dependency migration, perf regression, security
   patch, multi-file refactor, multi-service Docker Compose.
4. **Adversarial baselines** — public-test-overfit, test-deletion,
   pyproject-hijack — to validate the reward-hacking guards under stress.
5. **LLM agent runner** — a tool-use loop that consumes only `user_prompt`
   + `public_tests` and executes via the same Action API. Drop-in for any
   model.
6. **Prime Verifiers export** — package each task as an Environment Hub
   entry (dataset + harness + reward function).
7. **Counterfactual data for verifier training** — per task, run each
   baseline + perturbations and label trajectories with outcome / reward
   buckets.
8. **GUI / computer-use bridge** — same task, but executed inside an IDE
   running in the existing computer-use stack. The two reward systems share
   structure; this is the long-term integration story.

## Project layout

```
swegraph/
  task.py                # generate_tasks, load_task, save_task
  task_generators/       # bug_injection, config_bug, feature_addition
  fixtures/repos/        # stats_utils, csv_tool, todo_cli
  sandbox.py             # LocalSandbox: temp copy + run with timeout
  actions.py             # ActionAPI used by baselines
  baselines/             # do_nothing, oracle, naive (Action iterators)
  reward.py              # RewardTracker + YAML/JSON loader
  evaluator.py           # public + hidden tests + guards
  tests_runner.py        # pytest counts + hidden test executor
  trajectory.py          # JSONL logger
  utils/                 # diffing, file_guard, prompts
  cli.py                 # generate / run / eval / batch
configs/
  reward_default.yaml    # default reward weights (overridable per task)
tests/                   # 11 tests covering generation, baselines, reward, eval
```
