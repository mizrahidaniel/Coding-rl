from swegraph.baselines.do_nothing import run_do_nothing
from swegraph.baselines.naive_search_replace import run_naive_search_replace
from swegraph.baselines.oracle_patch import run_oracle_patch

BASELINES = {
    "do_nothing": run_do_nothing,
    "oracle": run_oracle_patch,
    "naive": run_naive_search_replace,
}
