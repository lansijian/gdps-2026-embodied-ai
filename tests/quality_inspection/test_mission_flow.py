from unittest.mock import patch
from gdps_qi.mission.mission_flow import FlowNode, MissionFlowState, default_specs


def test_full_six_samples_and_tail_terminates():
    st, specs = MissionFlowState(), default_specs()
    visited = []
    for _ in range(100):
        visited.append((st.current_step.step_id, st.sample_index))
        _, phase = st.transition(True, specs)
        if phase == "mission_complete": break
    else: raise AssertionError("mission looped")
    assert st.done
    assert len(visited) == 35
    assert [s for n,s in visited if n == "p1_pick_weigh"] == list(range(1,7))
    assert [s for n,s in visited if n == "p2_prepare_tube"] == list(range(1,7))
    assert [s for n,s in visited if n == "repeat_six"] == list(range(1,7))
    assert [n for n,s in visited][-4:] == ["p3_centrifuge","p4_unload","p5_inspect","p6_report"]
    assert "stabilize_after_nav" in st.completed
    assert "stabilize_pre_manip" in st.completed
    assert "manipulation_ready" in st.completed
    before = list(st.completed)
    assert st.transition(True, specs)[1] == "mission_complete"
    assert st.completed == before


def test_failure_recovery_and_pause():
    st, specs = MissionFlowState(), default_specs()
    assert st.transition(False, specs)[1] == "retry"
    assert st.retries["navigate_to_station"] == 1
    assert st.transition(False, specs)[1] == "safe_hold"
    assert st.transition(True, specs)[1] == "safe_hold_active"
    st.recover("operator-reviewed-failure-001")
    assert st.transition(True, specs)[0] == FlowNode.STABILIZE_BODY
    st.pause()
    assert st.transition(True, specs)[1] == "safe_hold_active"
    st.recover("operator-resume-002")
    assert st.transition(True, specs)[0] == FlowNode.REGISTER_WORKSTATION


def test_timeout_cannot_advance_and_recovery_needs_evidence():
    import pytest
    st, specs = MissionFlowState(), default_specs()
    with patch("gdps_qi.mission.mission_flow.time.monotonic", return_value=st.entered_at+121):
        assert st.transition(True, specs)[1] == "timeout"
    assert st.safe_hold
    with pytest.raises(ValueError): st.recover("")
    assert st.current == FlowNode.NAVIGATE_TO_STATION
