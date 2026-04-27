# SWEGraph v2: design rationale and critical reception

## Why v2

v1 (Apr 2026) was a polished implementation of standard SWE-RL infrastructure:
multi-step trajectories, milestone-shaped rewards, hidden tests, three
scripted baselines on three toy fixtures. Two independent code reviewers and
a planning agent stress-tested it and surfaced a tight, honest critique:

- **Milestones were rule-fired booleans.** Editing any file collected
  `implementation_edited`. Reading any file collected `relevant_file_read`.
  These are signal proxies, not signal.
- **Hidden tests were near-duplicates of public tests** with one or two
  hand-authored extensions. Trivially gameable; trivially overfittable.
- **Naive baseline was contrived.** It solved exactly the family it was
  hand-coded for (10/30 ≡ all bug_injection tasks). A textbook ceiling
  effect, not a difficulty gradient.
- **Reward-hacking guards leaked.** Test content editing, subdir conftest
  shadowing, fixture monkeypatching, symlink writes — all slipped past v1.
- **Single-oracle assumption.** Every task had one canonical patch. Multiple
  correct patches were penalised.
- **Trajectory format lost critical information** for downstream PRM/critic
  training: stdout truncated to 300 chars, no per-test results, milestone
  snapshots instead of deltas.

## What 2025-2026 prior art already does

Web research dated April 2026:

| System | Year | Contribution |
| --- | --- | --- |
| SWE-bench Pro | Scale AI, 2026 | 1,865 tasks across 41 repos including private codebases legally inaccessible to model trainers; contamination-resistant by construction |
| SWE-bench Live | 2026 | Monthly-refresh GitHub issue collection from post-cutoff dates |
| SWE-Rebench | 2026 | Decontaminated alternative: tasks post-date model training cutoffs |
| Self-Play SWE-RL (`arXiv 2512.18552`) | Dec 2025 | Dual-role injector/solver self-play; +10.4 SWE-bench Verified, +7.8 Pro; tasks specified by test patches; no human-curated issues |
| SWE-RL Meta (`arXiv 2502.18449`) | Feb 2025 | 11M PR instances; difflib-similarity reward; explicit limitation: cannot assess semantic correctness |
| MIST-RL | 2026 | Mutation-killing incremental reward for *test* generation; submodular optimisation avoids test bloat |
| SWE-PRM / AgentPRM | 2025-26 | Step-level process reward models that intervene at inference |
| Agentic Property-Based Testing (`arXiv 2510.09907`) | Oct 2025 | Hypothesis-driven LLM test generation; isolated venvs per agent |
| Prime Intellect Verifiers + Environments Hub | 2025-26 | Open-source RL-environment standard; SWE-native support; Prime-RL trainer |
| SWE-smith | 2025 | 50k tasks from 128 repos; SWE-agent-LM-32B → 40.2% Pass@1 on SWE-bench Verified |

## Where the v2 wedge actually lives

Holding the prior art up to the v1 critique, three honest options exist:

1. **Causal-hop import-graph difficulty axis.** Self-Play SWE-RL measures
   "frontier difficulty" empirically (solver pass rate). SWE-bench Pro
   stratifies by file count. Nobody publicly uses *static import-graph
   distance* as a generator-side knob. This is small but new, and it lets
   downstream work stratify any agent's success rate by a clean
   theoretical quantity.

2. **PBT-as-decontamination *with auto-extracted metamorphic relations*.**
   Hand-authored Hypothesis strategies are still hand-authored — a fair
   reviewer reduces this to "hidden tests with extra steps." The honest
   move is to mine at least one relation per task from the public-test AST
   so the hidden validator is *not* re-authored against the bug. v2 ships
   `utils/metamorphic_extract.py` with a precision-over-recall heuristic
   library (`boundary_extrema`, `idempotent_under_call`,
   `non_increasing_size`).

3. **Paired-state PRM preference dataset.** SWE-PRM and AgentPRM train
   step-level critics from collected trajectories. Nobody publicly ships a
   *paired* dataset of `(state, oracle_action, counterfactual_action)`
   tuples drawn from controlled task seeds. That paired form is the right
   shape for DPO/IPO-style preference training of a step-level critic.
   v2's `swegraph batch-prm` produces it.

Items 1 and 3 are the modest novelties. Item 2 is a useful reframing that
defends against the v1 hidden-test critique. Everything else in v2 — the
hardened guards, the four adversarial baselines, the trajectory format
upgrades, the legacy back-compat shim — is engineering hardening, framed
as such.

## What v2 explicitly does NOT claim

- That this matches Self-Play SWE-RL on absolute capability — it does not.
  v2 is an environment, not a trained agent.
- That property-based hidden validators are an invention — they are a
  reframing of Hypothesis under a decontamination lens, with mechanical
  relation extraction as the actual technical contribution.
- That the toy fixtures generalise. They don't. v3 must ingest real
  packages via mutmut for the authenticity story to hold.
- That the hardened guards are bulletproof. They are *monitored* — an AST
  detector for `assert True or actual_check` is defeated by
  `assert (lambda: True)()`. Guards exist to label trajectories for the
  PRM, not to be a sound type system.

## Risks called out by the planning agent that v2 has NOT solved

- **Causal-hop difficulty might just measure how good `grep` is.** We do
  not yet have an empirical curve showing model success rate decreasing in
  hop count. The infrastructure is there; the experiment isn't run.
- **Mutmut on real repos is the only way the toy-fixtures critique goes
  away.** v2 deliberately deferred this; v3 must ship it.  ← **closed in v3**
- **Single-oracle problem is only partially solved.** PBT validates
  behaviour, but `oracle_metadata` still records one canonical patch.
  Localization-correct uses that one canonical reading-order. Both should
  generalise to *patch sets*.
- **Calibrated decontamination metric not shipped.** Mutual information
  between hidden spec and public test surface would directly quantify what
  v2 claims about decontamination. Future work.

---

## v3 — real-repo ingestion via AST mutators

The biggest planning-agent risk on v2 was: "toy fixtures don't generalise
until real-repo ingestion ships." v3 closes that gap with a procedural
mutation pipeline (`swegraph/ingest/`) that operates on any Python repo
with a green test suite.

### Why an AST mutator instead of mutmut

Two motivations:

1. **Honesty.** Mutmut's mutation registry, equivalence filtering, and
   hash cache are sophisticated, but they are also a black box. By writing
   the operators ourselves (~250 LOC, five families: `off_by_one`,
   `compare_swap`, `boolean_flip`, `return_value`, `binary_op`) we own the
   end-to-end story and can reason about what mutations are emitted on
   any given source file.
2. **Precision.** Mutmut applies mutations as text patches and relies on
   global string replacement, which fails on short tokens like ``and`` /
   ``or`` / ``+``. Our mutator records ``(line, col, before, after)`` for
   every mutation and applies it precisely. That precision flows through
   the runtime (``cli._apply_mutation`` and ``oracle_patch.py``) so the
   reverse-mutation oracle never accidentally rewrites the wrong token.

The five operator families are deliberately the same families mutmut
implements; the contribution is the precise application + the
public/hidden split coupling, not the mutation taxonomy.

### Why the public/hidden split is the real wedge

A surviving mutation alone is not a SWEGraph task — to be useful it must
be *decidable* (the hidden validator catches it) and *non-trivial* (the
public surface doesn't already make the bug obvious). The ingest pipeline
sweeps a small fan of split seeds and accepts only mutations where
**public passes + hidden fails** (preferred) or, failing that,
**public also fails + hidden fails** (fallback). The agent then sees a
plausible-looking workspace where public tests don't tell it the answer,
and must infer the property the hidden split encodes — exactly the
shape SWE-bench Verified has but constructed automatically.

### Honest numbers

On the vendored `reqparse_lite` fixture (3 modules, 250 LOC source, 42
public tests):
- 14 killed mutations, 12 yield decidable tasks, 2 reject (no split
  produces a public-misses + hidden-catches partition under the seed fan
  we try).
- Oracle solves 12/12 (precise reverse-mutation).
- do_nothing 0/12 (lower bound holds).
- **naive 0/12** — the v2 heuristic regex doesn't match these AST
  mutations on real code. This is the difficulty gradient v1's planning
  agent demanded and v2 didn't deliver.

### What v3 explicitly does NOT claim

- That it's been validated on real PyPI packages. It hasn't — the
  pipeline is repo-agnostic but the only target shipped is
  `reqparse_lite`. v4 should add `--pypi <package>` and demonstrate
  on ≥ 3 real packages.
- That AST mutators cover all real-world bug shapes. They don't — they
  cover boundary, comparison, boolean, return-value, and arithmetic
  bugs. Logic-level errors that span multiple lines are out of scope.
- That the split-seed fan is sound. With more seeds the search yields
  more decidable splits, but we don't yet quantify how seed count
  affects task quality. v4 should publish that curve.

## Path to becoming research- or product-worthy

In rough priority:

1. **Real-repo ingestion via mutmut on small public Python packages** —
   produces authentic surviving mutants as task seeds; combine with PBT
   validators to keep "real bug + real semantic spec" as the success
   contract.
2. **Empirical hop-count vs success curve** for at least one open-weights
   model on the existing causal_hop fixture, expanded to 4-hop and 5-hop
   chains.
3. **Train a small PRM on the v2 preference-pair dataset** and report
   calibration (ECE) on a held-out task family. That's a paper.
4. **Inverse-difficulty curriculum** — regenerate hidden properties to
   target the agent's current failure modes (closes the Self-Play SWE-RL
   loop one notch tighter on the *generator* side, not the agent side).
5. **Cross-language**: a single causal_hop fixture in Rust or TypeScript
   with `proptest` / `fast-check`. Forces the harness to be language-agnostic.
6. **Spec-leak metric**: probe-classifier mutual information between hidden
   formal spec and (public tests + user prompt). Directly quantifies what
   v2 claims.

## Reception sources

The critique that drove v2 is documented in:
- The two Explore-agent reports run on April 2026 against v1.
- The Plan-agent stress-test of the proposed v2 design.
- Web research compiled into the table above.

Honest framing rule: where v2 is a polish or reframing, the README and this
document call it that. Where v2 is novel (causal-hop axis, paired PRM
dataset shape), the claim is narrow and falsifiable.
