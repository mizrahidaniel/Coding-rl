"""Build SWEGraph tasks from a real (or vendored-real) repository.

Pipeline:
1. Enumerate candidate mutations across every non-test ``.py`` file under
   the target source dir.
2. For each mutation: classify survival against the existing test suite.
3. Keep only ``survived`` mutations (the test suite did NOT catch them —
   these are the authentic hidden bugs).
4. Build a deterministic public/hidden split of the test functions.
5. Verify the hidden split DOES catch the mutation (otherwise the task is
   undecidable). Skip mutations that pass both halves.
6. Emit a ``TaskSpec`` per surviving + decidable mutation.

Output ordering is deterministic in (seed, repo content). Capping is via
``max_tasks``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from swegraph.ingest.mutators import (
    MUTATION_OPERATORS,
    Mutation,
    apply_mutation,
    enumerate_mutations,
)
from swegraph.ingest.survival import classify_mutation
from swegraph.ingest.test_split import split_tests
from swegraph.reward import DEFAULT_REWARD
from swegraph.schema import TaskSpec


_USER_PROMPT_TEMPLATES = [
    "We're seeing flaky behaviour in {module}. Could you fix it without changing the public API?",
    "Something regressed in {module}. Mind taking a look?",
    "Reports came in that {module} returns wrong values for some inputs. Please patch.",
    "{module} is misbehaving — please fix without altering the published interface.",
]


def _list_source_files(src_dir: Path) -> list[Path]:
    files: list[Path] = []
    for p in src_dir.rglob("*.py"):
        rel = p.relative_to(src_dir)
        if any(part in {"tests", "__pycache__", ".pytest_cache"} for part in rel.parts):
            continue
        if p.name == "__init__.py":
            continue
        files.append(p)
    return sorted(files)


def _list_test_files(src_dir: Path) -> list[str]:
    out: list[str] = []
    for p in (src_dir / "tests").rglob("test_*.py"):
        out.append(str(p.relative_to(src_dir)))
    return sorted(out)


def _hidden_split_kills_mutation(
    workspace: Path,
    mutation: Mutation,
    public: dict[str, str],
    hidden: dict[str, str],
    test_paths: list[str],
    timeout: int,
) -> tuple[bool, bool]:
    """Return (public_misses, hidden_catches).

    The mutation is decidable iff the hidden split catches it. We also report
    whether the public split misses (preferred shape: public misses, hidden
    catches — the agent has to *infer* the property the public tests don't
    encode).
    """
    public_passed = _run_split_against_mutation(workspace, mutation, public, timeout)
    hidden_passed = _run_split_against_mutation(workspace, mutation, hidden, timeout)
    return public_passed, (not hidden_passed)


def _run_split_against_mutation(
    workspace: Path,
    mutation: Mutation,
    files: dict[str, str],
    timeout: int,
) -> bool:
    """Apply ``mutation`` in a scratch copy with ``files`` substituted for
    the original tests; return True if the suite passes (i.e. mutation is
    not caught).
    """
    if not files:
        return True
    with tempfile.TemporaryDirectory(prefix="swegraph_split_") as tmp:
        scratch = Path(tmp) / "ws"
        shutil.copytree(workspace, scratch)
        # Wipe original tests from disk; rewrite only the split ones.
        tests_dir = scratch / "tests"
        if tests_dir.exists():
            for p in tests_dir.rglob("test_*.py"):
                p.unlink()
        for rel, body in files.items():
            target = scratch / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        target = scratch / mutation.path
        if not apply_mutation(scratch, mutation, target=target):
            return True  # apply failed -> conservatively treat as "no kill"
        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", "-q", "tests"],
                cwd=scratch, text=True, capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return True
        return proc.returncode == 0


def build_ingested_tasks(
    *,
    fixture_dir: Path,
    out_dir: Path,
    seed: int = 7,
    hidden_frac: float = 0.3,
    max_tasks: int = 20,
    operators: list[str] | None = None,
    timeout: int = 30,
    reward_config: dict | None = None,
) -> list[Path]:
    """End-to-end ingestion. Returns the list of ``TaskSpec`` JSON paths
    written.

    Skips mutations that:
    - fail to apply (``broke_syntax``),
    - the original suite catches (``killed``),
    - the hidden split misses (undecidable — both halves still pass).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    src_files = _list_source_files(fixture_dir)
    test_paths = _list_test_files(fixture_dir)

    reward_cfg = {**DEFAULT_REWARD, **(reward_config or {})}

    # Try a small fan of split seeds per mutation so we can find an "interesting"
    # public/hidden partition (public misses, hidden catches) even when one
    # split has the wrong tests in the wrong half.
    candidate_split_seeds = [seed, seed + 1, seed + 2, seed + 3]

    written: list[Path] = []
    survived = killed = broke = baseline_red = no_split_found = 0
    task_index = 0

    for src in src_files:
        rel_src = str(src.relative_to(fixture_dir))
        muts = enumerate_mutations(src)
        # Annotate the path so downstream code resolves it under the workspace.
        muts = [
            Mutation(
                operator=m.operator,
                path=rel_src,
                line=m.line,
                col=m.col,
                before=m.before,
                after=m.after,
                description=m.description,
            )
            for m in muts
        ]
        for m in muts:
            if task_index >= max_tasks:
                break
            r = classify_mutation(fixture_dir, m, timeout=timeout)
            if r.classification == "broke_syntax":
                broke += 1
                continue
            if r.classification == "baseline_red":
                baseline_red += 1
                continue
            if r.classification == "timeout":
                continue
            if r.classification == "survived":
                # Equivalent mutant or untested code path. Skip — the existing
                # suite has nothing to say about the mutation, so we cannot
                # build an honest hidden validator.
                survived += 1
                continue
            killed += 1

            # Find a split where public misses (so the agent doesn't see the
            # bug from public tests) AND hidden catches (so the task is
            # decidable). The "preferred" shape: public passes after mutation,
            # hidden fails -> agent must reason about the spec, not just stare
            # at failing public tests.
            chosen_public: dict[str, str] | None = None
            chosen_hidden: dict[str, str] | None = None
            chosen_split_seed: int | None = None
            chosen_pub_misses: bool = False
            for s in candidate_split_seeds:
                public, hidden = split_tests(fixture_dir, test_paths, seed=s, hidden_frac=hidden_frac)
                if not public or not hidden:
                    continue
                pub_passes, hid_catches = _hidden_split_kills_mutation(
                    fixture_dir, m, public, hidden, test_paths, timeout
                )
                if hid_catches:
                    chosen_public, chosen_hidden, chosen_split_seed = public, hidden, s
                    chosen_pub_misses = bool(pub_passes)
                    if pub_passes:
                        # the preferred shape - stop early
                        break
            if chosen_public is None or chosen_hidden is None:
                no_split_found += 1
                continue

            module_label = rel_src.replace("/", ".").removesuffix(".py")
            user_prompt = _USER_PROMPT_TEMPLATES[task_index % len(_USER_PROMPT_TEMPLATES)].format(module=module_label)

            spec = TaskSpec(
                task_id=f"ingest_task_{task_index+1:03d}",
                repo_id=fixture_dir.name,
                task_family="real_repo_ingested",
                seed=seed,
                user_prompt=user_prompt,
                formal_prompt=(
                    f"A procedural {m.operator} mutation in {rel_src} regresses behaviour. "
                    "Restore the function under test without changing the public API."
                ),
                hidden_formal_spec=(
                    "The held-out hidden test split must pass; the public test split must "
                    "continue to pass."
                ),
                public_tests=list(chosen_public.keys()),
                hidden_validators=[
                    {"kind": "unit_tests", "files": dict(chosen_hidden), "timeout": timeout},
                ],
                mutation_metadata={
                    "type": "replace_text",
                    "path": rel_src,
                    "old": m.before,
                    "new": m.after,
                    "operator": m.operator,
                    "line": m.line,
                    "col": m.col,
                    "relevant_files": [rel_src],
                    "root_cause_file": rel_src,
                    "public_misses": chosen_pub_misses,
                    "split_seed": chosen_split_seed,
                },
                oracle_metadata={"patch_type": "reverse_mutation"},
                allowed_files=[rel_src, *list(chosen_public.keys())],
                protected_files=["pyproject.toml", "pytest.ini", "setup.cfg"],
                expected_behavior=f"Reverse the {m.operator} mutation in {rel_src}",
                difficulty={
                    "level": "preferred" if chosen_pub_misses else "easy",
                    "family": "real_repo_ingested",
                    "operator": m.operator,
                },
                reward_config=reward_cfg,
            )

            # Public tests must also live on disk in the workspace at run-time
            # (the agent reads them). The runner copies the fixture from
            # ``swegraph/fixtures/repos/<repo_id>``, so we rewrite the
            # public test files in the fixture pre-run only when ingested
            # tasks are run. To keep the fixture pristine, we instead emit a
            # ``public_test_overrides`` map that the runner installs into the
            # workspace after copy.
            spec_dict = spec.to_dict()
            spec_dict["public_test_overrides"] = chosen_public
            p = out_dir / f"{spec.task_id}.json"
            p.write_text(__import__("json").dumps(spec_dict, indent=2))
            written.append(p)
            task_index += 1
        if task_index >= max_tasks:
            break

    manifest = {
        "fixture": str(fixture_dir),
        "seed": seed,
        "hidden_frac": hidden_frac,
        "operators": operators or list(MUTATION_OPERATORS.keys()),
        "stats": {
            "tasks_emitted": len(written),
            "survived_skipped": survived,
            "killed": killed,
            "broke_syntax": broke,
            "baseline_red": baseline_red,
            "no_decidable_split_found": no_split_found,
        },
    }
    (out_dir / "ingest_manifest.json").write_text(__import__("json").dumps(manifest, indent=2))
    return written
