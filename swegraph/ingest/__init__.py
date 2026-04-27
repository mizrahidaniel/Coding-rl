"""Real-repo ingestion pipeline.

The v1/v2 task generators assume hand-authored fixtures with hand-authored
mutations. v3 inverts that: point the harness at a real (or vendored-real)
repository, run a procedural AST-level mutator across its source modules,
identify *surviving* mutants (mutations that the existing test suite does
not catch), and turn each one into a SWEGraph task whose hidden validator
is a held-out subset of the same suite.

This addresses the v2 plan's biggest unmitigated risk: "toy fixtures don't
generalise." The generated tasks now carry an authentic bug shape (a real
mutation operator on real code) and an authentic semantic spec (the
existing test suite, partitioned).

Pipeline stages:
1. ``mutators`` — AST-based mutation operators.
2. ``survival`` — apply a mutation, run the test suite, classify the result
   (killed / survived / broke-syntax).
3. ``test_split`` — partition test functions into public/hidden by
   deterministic hash so two ingest runs over the same repo + seed produce
   identical splits.
4. ``task_factory`` — assemble (mutation, public_tests, hidden_validators)
   into a ``TaskSpec``.
5. ``cli`` integration — ``swegraph ingest --fixture <name>``.
"""

from swegraph.ingest.mutators import (
    Mutation,
    enumerate_mutations,
    MUTATION_OPERATORS,
)
from swegraph.ingest.survival import classify_mutation, SurvivalResult
from swegraph.ingest.task_factory import build_ingested_tasks
from swegraph.ingest.test_split import split_tests

__all__ = [
    "Mutation",
    "MUTATION_OPERATORS",
    "SurvivalResult",
    "build_ingested_tasks",
    "classify_mutation",
    "enumerate_mutations",
    "split_tests",
]
