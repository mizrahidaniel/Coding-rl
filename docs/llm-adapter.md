# SWEGraph v4 — LLM agent adapter

The `llm` baseline turns SWEGraph from a harness with three scripted baselines into a harness any LLM agent can be measured against. It uses the official Anthropic SDK, defaults to `claude-opus-4-7` with adaptive thinking and `effort: "high"`, and yields one `Action` record per tool call into the existing trajectory logger.

This is the v3-plan "table-stakes shim" item. The wedge isn't the adapter itself — every SWE-bench-style harness ships one. The reason it matters here is that v2 introduced the **causal-hop import-graph difficulty axis** but didn't have an agent to actually run against it; until now, the axis was theoretical.

## Architecture

```
swegraph/baselines/
  llm_adapter.py          # real Anthropic SDK loop (the `llm` baseline)
  llm_mock.py             # scripted responder (the `llm_mock` baseline)
```

Two key seams:
- **`run_llm_loop(api, task, config, *, responder=...)`** — the actual tool-use loop. It accepts a `responder` callable that takes a list of messages and returns an Anthropic-shaped response. The default responder calls `claude-opus-4-7`; tests inject a scripted `responder` to drive the same loop offline.
- **`execute_tool_call(name, args, api)`** — translates a single Claude tool call into an `Action` record + the textual `tool_result` that goes back to the model. Unit-tested directly so the most failure-prone seam doesn't depend on running the whole loop.

Tools exposed to the model (mirroring `ActionAPI`):

| Tool | Purpose |
| --- | --- |
| `run_command(command)` | Shell command in the workspace. Returns `exit_code`, stdout/stderr (truncated). |
| `read_file(path)` | Read a workspace file. Truncates to head + tail when > 4 KB so the loop stays in budget. |
| `write_file(path, content)` | Replace a file's full contents. |
| `replace_text(path, old, new)` | Surgical first-occurrence replace. Preferred over `write_file` for small edits. |
| `finish()` | Submit. Only call once public tests pass. |

System prompt is marked `cache_control: ephemeral` so repeated batch rollouts on the same task family share the cached prefix. Adaptive thinking is on by default (`thinking={"type": "adaptive"}`); set `--llm-effort low` for ablations, or `xhigh` / `max` for harder tasks. `max` is Opus-tier only.

## Usage

```bash
# Real Claude rollout
export ANTHROPIC_API_KEY=...
python -m swegraph run --task runs/tasks/task_001.json --baseline llm \
    --out runs/llm_001 \
    --llm-model claude-opus-4-7 \
    --llm-effort high \
    --llm-max-steps 30

# Offline (mock; no API key)
python -m swegraph run --task runs/tasks/task_001.json --baseline llm_mock \
    --out runs/mock_001
```

Equivalent env-var form (for batch runs that don't go through `swegraph run`):

```bash
export SWEGRAPH_LLM_MODEL=claude-opus-4-7
export SWEGRAPH_LLM_MAX_STEPS=30
export SWEGRAPH_LLM_EFFORT=high
```

## Empirical hop-count vs success curve (v2 wedge validation)

The point v2's planning agent flagged: the causal-hop axis is theoretically clean but might just measure how good `grep` is. The recipe to validate it now exists:

```bash
# 1. Generate a deliberately-skewed task set across hop counts.
python -m swegraph generate --num-tasks 64 --out runs/hop_eval --seed 7

# 2. Run an LLM at fixed effort against the whole set.
python -m swegraph batch \
    --tasks runs/hop_eval \
    --baseline llm \
    --out runs/hop_curve_high \
    --llm-effort high \
    --llm-max-steps 30 \
    --clean

# 3. Stratify success by import_hops.
python - <<'PY'
import json
from collections import defaultdict
rows = json.loads(open("runs/hop_curve_high/batch_summary.json").read())
buckets = defaultdict(lambda: {"n": 0, "hidden": 0})
for r in rows:
    h = r.get("import_hops")
    if h is None:
        continue
    buckets[h]["n"] += 1
    buckets[h]["hidden"] += int(r["hidden"])
for h, b in sorted(buckets.items()):
    print(f"hops={h}: {b['hidden']}/{b['n']} ({b['hidden']/b['n']:.0%})")
PY
```

A real difficulty axis shows monotonically decreasing success as hops increase; if the curve is flat, the axis is measuring something else and the wedge collapses.

## Cost guidance

Each rollout is a multi-turn loop with adaptive thinking. Order-of-magnitude expectations on Opus 4.7:

| Budget | Tokens per task | Notes |
| --- | --- | --- |
| `--llm-effort low` + `--llm-max-steps 10` | ~10–25 K | Fastest; good for sanity checks |
| `--llm-effort high` + `--llm-max-steps 30` (default) | ~30–80 K | Recommended for empirical curves |
| `--llm-effort max` + `--llm-max-steps 50` | ~80–200 K | Hardest tasks; diminishing returns |

Practical workflow:
1. Iterate against `llm_mock` (zero cost).
2. Smoke-test `llm` on a *single* task before any batch run.
3. Run the smallest batch (8 tasks) at default settings to calibrate.
4. Only then run a full sweep.

## What v4 does NOT include

- **Trained PRM artifact** — the v2 `swegraph batch-prm` produces 296+ paired preference tuples, but no PRM has been trained on them. v5.
- **Empirical hop curve numbers** — the recipe is shipped; the actual run is up to whoever has API credits + time.
- **Automatic agent comparison harness** — multi-agent leaderboard ("Claude vs `gpt-5` vs OpenHands") is out of scope. The `llm` baseline can be reused as a template for adapters to other model APIs, but the cross-vendor harness isn't shipped.
- **Cross-language** — the agent and the harness are still Python-only. v6.
