"""Process-Reward-Model preference-pair emission.

Self-Play SWE-RL trains the *agent* via outcome reward. Existing PRM work
(SWE-PRM, AgentPRM) trains step-level critics from collected trajectories
but doesn't ship a public dataset of *paired* steps drawn from oracle vs
counterfactual rollouts at the **same task seed**. That paired form is the
right shape for DPO/IPO-style preference training.

This module turns a directory of completed runs into a JSONL of preference
tuples, where each entry has::

    {
      "task_id": "task_001",
      "step_index": 2,
      "state_hash": "<sha256>",
      "milestone_state": {...},
      "public_test_status": {...},
      "preferred": {
          "baseline": "oracle",
          "action_type": "replace_text",
          "edit_metadata": {...},
          "command": null,
          "reward_delta": 1.69
      },
      "rejected": {
          "baseline": "attack_public_test_overfit",
          ...,
          "reward_delta": -0.50
      },
      "labels": {
          "preferred_final_success": true,
          "rejected_final_success": false,
          "preferred_validator_pass": true,
          "rejected_validator_pass": false
      }
    }

State hash: SHA-256 over the canonicalised milestone-state + public-test
``passed/failed`` count at that step. Two trajectories share a state when
the runner has observed the same milestone snapshot and the same test
status. This is a coarse but reproducible matcher; v3 can refine to a
file-content fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _state_hash(step: dict) -> str:
    canon = {
        "milestone": dict(sorted((step.get("milestone_state") or {}).items())),
        "public": {
            "passed": (step.get("public_test_status") or {}).get("passed", 0),
            "failed": (step.get("public_test_status") or {}).get("failed", 0),
        },
    }
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()[:16]


def _action_summary(step: dict) -> dict[str, Any]:
    return {
        "action_type": step.get("action_type"),
        "command": step.get("command"),
        "edit_metadata": step.get("edit_metadata"),
        "reward_delta": (step.get("reward_components") or {}).get("_step_total"),
    }


def _load_trajectory(run_dir: Path) -> list[dict]:
    f = run_dir / "trajectory.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def _load_report(run_dir: Path) -> dict:
    f = run_dir / "final_report.json"
    return json.loads(f.read_text()) if f.exists() else {}


def emit_prm_pairs(
    *,
    tasks: list[Path],
    baselines: list[str],
    run_root: Path,
    out_path: Path,
    refresh: bool = True,
) -> int:
    """Run each baseline on each task (so all rollouts share the same task
    JSON and same fixture seed), then emit oracle-vs-counterfactual pairs at
    every state where actions diverge.

    Returns the number of pairs written.
    """
    if "oracle" not in baselines:
        baselines = ["oracle", *baselines]

    # 1. Run each baseline on every task. We re-use ``swegraph run`` rather
    #    than re-implementing the loop so trajectories match what the rest
    #    of the system produces.
    if refresh and run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)

    for baseline in baselines:
        for t in tasks:
            out_dir = run_root / baseline / t.stem
            if (out_dir / "trajectory.jsonl").exists():
                continue
            cmd = [
                sys.executable, "-m", "swegraph", "run",
                "--task", str(t),
                "--baseline", baseline,
                "--out", str(out_dir),
                "--mode", "training",
            ]
            subprocess.run(cmd, capture_output=True, text=True)

    # 2. Walk each task and produce pairs.
    pair_count = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for t in tasks:
            oracle_dir = run_root / "oracle" / t.stem
            oracle_traj = _load_trajectory(oracle_dir)
            oracle_report = _load_report(oracle_dir)
            if not oracle_traj:
                continue
            oracle_states = {(_state_hash(s), s["step_index"]): s for s in oracle_traj}

            # Map oracle steps by state-hash (any step index) for permissive
            # matching, plus by step index for the strict matcher.
            oracle_by_hash: dict[str, list[dict]] = {}
            oracle_by_index: dict[int, dict] = {}
            for s in oracle_traj:
                oracle_by_hash.setdefault(_state_hash(s), []).append(s)
                oracle_by_index[s["step_index"]] = s

            def _emit(o_step: dict, cf_step: dict, baseline: str, match_type: str) -> bool:
                if (
                    o_step.get("action_type") == cf_step.get("action_type")
                    and o_step.get("command") == cf_step.get("command")
                    and (o_step.get("edit_metadata") or {}).get("path")
                    == (cf_step.get("edit_metadata") or {}).get("path")
                ):
                    return False
                pair = {
                    "task_id": t.stem,
                    "step_index": cf_step["step_index"],
                    "state_hash": _state_hash(cf_step),
                    "match_type": match_type,
                    "milestone_state": cf_step.get("milestone_state"),
                    "public_test_status": {
                        "passed": (cf_step.get("public_test_status") or {}).get("passed", 0),
                        "failed": (cf_step.get("public_test_status") or {}).get("failed", 0),
                    },
                    "preferred": {"baseline": "oracle", **_action_summary(o_step)},
                    "rejected": {"baseline": baseline, **_action_summary(cf_step)},
                    "labels": {
                        "preferred_final_success": bool(oracle_report.get("final_success")),
                        "rejected_final_success": bool(cf_report.get("final_success")),
                        "preferred_validator_pass": bool(oracle_report.get("hidden_tests_pass")),
                        "rejected_validator_pass": bool(cf_report.get("hidden_tests_pass")),
                        "rejected_guard_hits": len(cf_report.get("guard_report") or []),
                    },
                }
                fh.write(json.dumps(pair) + "\n")
                return True

            for baseline in baselines:
                if baseline == "oracle":
                    continue
                cf_dir = run_root / baseline / t.stem
                cf_traj = _load_trajectory(cf_dir)
                cf_report = _load_report(cf_dir)
                if not cf_traj:
                    continue
                seen_state_hashes: set[str] = set()
                emitted_for_pair = 0
                for cf_step in cf_traj:
                    h = _state_hash(cf_step)
                    # 1. strict match: same step index + same state hash
                    o_step = oracle_states.get((h, cf_step["step_index"]))
                    if o_step is not None and _emit(o_step, cf_step, baseline, "strict"):
                        pair_count += 1
                        emitted_for_pair += 1
                        continue
                    # 2. permissive match: any oracle step at the same state hash
                    candidates = oracle_by_hash.get(h, [])
                    if candidates:
                        if _emit(candidates[0], cf_step, baseline, "state_hash"):
                            pair_count += 1
                            emitted_for_pair += 1
                            continue
                    # 3. fallback: same step index in oracle
                    o_idx = oracle_by_index.get(cf_step["step_index"])
                    if o_idx is not None and h not in seen_state_hashes:
                        if _emit(o_idx, cf_step, baseline, "step_index"):
                            pair_count += 1
                            emitted_for_pair += 1
                    seen_state_hashes.add(h)

    return pair_count
