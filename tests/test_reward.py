from swegraph.reward import RewardTracker
from swegraph.schema import MilestoneState


def test_reward_components_logged():
    tracker = RewardTracker()
    m = MilestoneState(task_started=True, public_failure_reproduced=True)
    comp = tracker.step(m)
    assert "public_failure_reproduced" in comp
    assert "_cumulative" in comp
