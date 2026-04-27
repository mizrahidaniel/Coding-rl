# SWEGraph v1

SWEGraph is a local Python environment/task factory for software-engineering agents. v1 focuses on **task generation, hidden validation, dense rewards, and trajectory logging**, not full LLM autonomy.

## Why

SWEGraph mirrors graph-backed computer-use environments for SWE:
- controllable synthetic tasks,
- hidden structured state/specs,
- dense progress rewards,
- full action trajectories.

## Architecture Summary

- **Task Factory (`swegraph/task.py`, `swegraph/task_generators/`)**
  - Generates reproducible tasks across 3 families: bug injection, config/API bug, feature addition.
  - Emits task specs with user prompt, hidden spec, public+hidden tests, mutation/oracle metadata.
- **Fixture Repos (`swegraph/fixtures/repos/`)**
  - `stats_utils`, `csv_tool`, `todo_cli` created as toy but realistic Python repos.
- **Sandbox (`swegraph/sandbox.py`)**
  - Copies fixture to temp workspace, runs commands with timeout, never edits original fixture.
- **Action API (`swegraph/actions.py`)**
  - `run_command`, `read_file`, `write_file`, `apply_patch`, `replace_text`, `finish`.
- **Evaluation & Reward (`swegraph/evaluator.py`, `swegraph/reward.py`)**
  - Separates public/hidden tests, computes dense component rewards, checks guards (protected files/tests deletion/suspicious config edits), and emits final report.
- **Trajectory Logger (`swegraph/trajectory.py`)**
  - JSONL step logs with milestone and reward components.
- **Baselines (`swegraph/baselines/`)**
  - `do_nothing`, `oracle`, and `naive` scripted baselines.

## CLI

```bash
python -m swegraph generate --out runs/tasks --num-tasks 30
python -m swegraph run --task runs/tasks/task_001.json --baseline oracle --out runs/oracle_001
python -m swegraph eval --run runs/oracle_001
python -m swegraph batch --tasks runs/tasks --baseline do_nothing --out runs/do_nothing_batch
```

## Example task JSON (abridged)

```json
{
  "task_id": "task_001",
  "repo_id": "stats_utils",
  "task_family": "bug_injection",
  "user_prompt": "The percentile calculation seems off for edge cases...",
  "public_tests": ["tests/test_public_bug.py"],
  "hidden_tests": {"tests/test_hidden_bug.py": "..."},
  "mutation_metadata": {"type": "replace_text", "path": "stats_utils/core.py"}
}
```

## Example trajectory step (abridged)

```json
{
  "step_index": 0,
  "action_type": "baseline:oracle",
  "changed_files": ["stats_utils/core.py"],
  "milestone_state": {"public_failure_reproduced": true, "public_tests_pass": true},
  "reward_components": {"public_tests_pass": 1.0, "step_cost": -0.01}
}
```

## Example final report (abridged)

```json
{
  "public_tests_pass": true,
  "hidden_tests_pass": true,
  "protected_files_changed": [],
  "tests_deleted_or_disabled": false,
  "final_success": true,
  "reward_total": 4.29
}
```

## Future extensions

- GitHub repo ingestion.
- Dockerized sandboxes.
- LLM/coding-agent adapters.
- RL environment API and verifier model training.
- SWE-bench-style export + long-horizon task families.
