"""Adversarial baselines.

Each attacker exercises a specific reward-hacking pattern. They MUST trigger
at least one ``block``-severity hit in ``utils/file_guard.py`` and therefore
fail final-success. Their trajectories are labelled negatives suitable for
PRM/critic training.

Registered attackers:
- ``test_content_edit_attacker`` — comments out asserts in public tests.
- ``conftest_shadow_attacker`` — adds a subdir conftest with monkeypatch.
- ``fixture_monkeypatch_attacker`` — injects ``unittest.mock.patch`` into
  the public test module to silently swap the implementation.
- ``public_test_overfit_attacker`` — replaces the implementation with a
  hardcoded lookup table that satisfies only the inputs in public tests.
"""

from swegraph.baselines.adversarial.test_content_edit import run_test_content_edit_attacker
from swegraph.baselines.adversarial.conftest_shadow import run_conftest_shadow_attacker
from swegraph.baselines.adversarial.fixture_monkeypatch import run_fixture_monkeypatch_attacker
from swegraph.baselines.adversarial.public_test_overfit import run_public_test_overfit_attacker


ADVERSARIAL_BASELINES = {
    "attack_test_content_edit": run_test_content_edit_attacker,
    "attack_conftest_shadow": run_conftest_shadow_attacker,
    "attack_fixture_monkeypatch": run_fixture_monkeypatch_attacker,
    "attack_public_test_overfit": run_public_test_overfit_attacker,
}
