from src.validators import validate_coordinates, validate_plan, validate_tool_args


def test_validate_plan_passes():
    ok, reasons = validate_plan(
        {
            "domain": "wildfire_defensible_space",
            "user_goal": "Assess home",
            "steps": [{"step_id": "S1", "objective": "Geocode", "tool": "geocode_google", "constraints": []}],
        }
    )
    assert ok
    assert reasons == []


def test_validate_plan_blocks_disallowed_tool():
    ok, reasons = validate_plan(
        {
            "domain": "wildfire_defensible_space",
            "user_goal": "Assess home",
            "steps": [{"step_id": "S1", "objective": "Hack", "tool": "os.system", "constraints": []}],
        }
    )
    assert not ok
    assert any("disallowed" in reason for reason in reasons)


def test_validate_tool_args_range_checks():
    ok, reasons = validate_tool_args({"address": "x", "buffer_m": 999, "start": "a", "end": "b", "cloud_pct": 120})
    assert not ok
    assert len(reasons) >= 2


def test_validate_coordinates():
    ok, _ = validate_coordinates(38.0, -120.0)
    assert ok
    bad, reasons = validate_coordinates(200, -500)
    assert not bad
    assert len(reasons) == 2
