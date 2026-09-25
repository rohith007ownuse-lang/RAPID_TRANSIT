"""
tests/test_predictive_health.py
Unit tests for the maintenance decision heuristic and RUL day column:
≤1 d -> SEND_TO_MAINTENANCE, ≤3 d -> PLAN_MAINTENANCE, else CAN_CONTINUE.
"""

from predictive_health import (
    ComponentHealth,
    DataSource,
    HealthState,
    TICKS_PER_DAY,
    _build_maintenance_decision,
)


def _comp(name="tyre_fl", component_type="tyre", value=85.0, rul_ticks=None):
    return ComponentHealth(
        name=name,
        component_type=component_type,
        value=value,
        rul_ticks=rul_ticks,
        data_source=DataSource.SIMULATION,
    )


def _health(**components):
    return dict(components)


def test_no_degraded_components_means_can_continue():
    comp = _comp(value=20.0, rul_ticks=100)  # HEALTHY
    decision = _build_maintenance_decision(_health(tyre_fl=comp))
    assert decision["status"] == "CAN_CONTINUE"
    assert decision["days_to_failure"] is None


def test_under_one_day_sends_to_maintenance():
    comp = _comp(value=90.0, rul_ticks=TICKS_PER_DAY - 100)  # CRITICAL, < 1 day
    decision = _build_maintenance_decision(_health(tyre_fl=comp))
    assert decision["status"] == "SEND_TO_MAINTENANCE"
    assert decision["days_to_failure"] < 1.0
    assert decision["component"] == "tyre_fl"


def test_under_three_days_plans_maintenance():
    comp = _comp(value=95.0, rul_ticks=TICKS_PER_DAY * 2)  # 2 days
    decision = _build_maintenance_decision(_health(vibration=comp))
    assert decision["status"] == "PLAN_MAINTENANCE"
    assert decision["days_to_failure"] == 2.0


def test_over_three_days_can_continue():
    comp = _comp(value=85.0, rul_ticks=TICKS_PER_DAY * 7)  # 7 days
    decision = _build_maintenance_decision(_health(harsh_braking=comp))
    assert decision["status"] == "CAN_CONTINUE"
    assert decision["days_to_failure"] == 7.0


def test_warning_component_with_rul_is_considered():
    comp = _comp(value=75.0, rul_ticks=TICKS_PER_DAY)  # WARNING (<=80), exactly 1 day
    decision = _build_maintenance_decision(_health(energy_degradation=comp))
    assert decision["status"] == "SEND_TO_MAINTENANCE"


def test_shortest_rul_wins_across_components():
    tyre = _comp(name="tyre_fl", value=90.0, rul_ticks=TICKS_PER_DAY * 2)   # 2 days
    vib = _comp(name="vibration", component_type="vibration", value=0.9, rul_ticks=TICKS_PER_DAY // 2)  # 0.5 d
    decision = _build_maintenance_decision(_health(tyre_fl=tyre, vibration=vib))
    assert decision["component"] == "vibration"
    assert decision["days_to_failure"] == 0.5


def test_rul_days_uses_ticks_per_day():
    comp = _comp(value=90.0, rul_ticks=TICKS_PER_DAY)
    assert comp.to_dict()["rul_days"] == 1.0
    comp2 = _comp(value=90.0, rul_ticks=TICKS_PER_DAY * 3 + TICKS_PER_DAY // 2)
    assert comp2.to_dict()["rul_days"] == 3.5


def test_ticks_per_day_is_720():
    assert TICKS_PER_DAY == 720
    assert HealthState.WARNING.value == "WARNING"
    assert HealthState.CRITICAL.value == "CRITICAL"