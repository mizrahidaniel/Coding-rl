from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from swegraph.schema import TaskSpec


@dataclass
class Action:
    """A single agent action.

    action_type: one of run_command, read_file, write_file, apply_patch,
                 replace_text, finish.
    args: action-specific arguments.
    note: optional human-readable rationale (logged for replay).
    """

    action_type: str
    args: dict[str, Any] = field(default_factory=dict)
    note: str = ""


BaselineFn = Callable[["ActionAPI", TaskSpec], Iterable[Action]]  # noqa: F821

# Registered after class definition to avoid circular imports.
from swegraph.baselines.adversarial import ADVERSARIAL_BASELINES  # noqa: E402
from swegraph.baselines.do_nothing import run_do_nothing  # noqa: E402
from swegraph.baselines.naive_search_replace import run_naive_search_replace  # noqa: E402
from swegraph.baselines.oracle_patch import run_oracle_patch  # noqa: E402

BASELINES: dict[str, BaselineFn] = {
    "do_nothing": run_do_nothing,
    "oracle": run_oracle_patch,
    "naive": run_naive_search_replace,
    **ADVERSARIAL_BASELINES,
}
