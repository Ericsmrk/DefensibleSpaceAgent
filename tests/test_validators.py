from src.validators import (
    ALLOWED_TOOLS,
    VALID_REQUEST_TYPES,
    validate_coordinates,
    validate_plan,
    validate_tool_args,
)


def _valid_plan(**overrides):
    base = {
        "request_type": "full_property_assessment",
        "assessment_mode": "property_level_environmental_assessment",
        "domain": "wildfire_defensible_space",
        "user_goal": "Assess home",
        "execution_ready": True,
        "steps": [
            {"step_id": 1, "objective": "Geocode", "tool": "geocode_google", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "NDVI", "tool": "compute_mean_ndvi", "depends_on": [1], "required": True},
            {"step_id": 3, "objective": "Fuel", "tool": "classify_fuel", "depends_on": [2], "required": True},
        ],
    }
    base.update(overrides)
    return base


def test_validate_plan_passes():
    ok, reasons = validate_plan(_valid_plan())
    assert ok
    assert reasons == []


def test_validate_plan_blocks_disallowed_tool():
    ok, reasons = validate_plan(
        _valid_plan(
            steps=[{"step_id": 1, "objective": "Hack", "tool": "os.system", "depends_on": [], "required": True}]
        )
    )
    assert not ok
    assert any("disallowed" in reason for reason in reasons)


def test_validate_plan_requires_request_type():
    ok, reasons = validate_plan({
        "assessment_mode": "x",
        "domain": "wildfire_defensible_space",
        "user_goal": "x",
        "execution_ready": True,
        "steps": [{"step_id": 1, "objective": "x", "tool": "geocode_google", "depends_on": [], "required": True}],
    })
    assert not ok
    assert any("missing" in reason and "request_type" in reason for reason in reasons)


def test_validate_plan_invalid_request_type():
    ok, reasons = validate_plan(_valid_plan(request_type="invalid_type"))
    assert not ok
    assert any("request_type" in reason for reason in reasons)


def test_validate_plan_execution_ready_false_when_incomplete():
    ok, reasons = validate_plan(_valid_plan(request_type="incomplete", execution_ready=True))
    assert not ok
    assert any("execution_ready" in reason for reason in reasons)


def test_validate_plan_execution_ready_false_when_unsupported():
    ok, reasons = validate_plan(_valid_plan(request_type="unsupported", execution_ready=True))
    assert not ok
    assert any("execution_ready" in reason for reason in reasons)


def test_validate_plan_dependency_order():
    # step 2 depends on 3 but 3 comes after 2 in list
    ok, reasons = validate_plan(
        _valid_plan(
            steps=[
                {"step_id": 1, "objective": "A", "tool": "geocode_google", "depends_on": [], "required": True},
                {"step_id": 2, "objective": "B", "tool": "compute_mean_ndvi", "depends_on": [3], "required": True},
                {"step_id": 3, "objective": "C", "tool": "classify_fuel", "depends_on": [1], "required": True},
            ]
        )
    )
    assert not ok
    assert any("depends_on" in reason and "before" in reason for reason in reasons)


def test_validate_plan_constraints_buffer_range():
    ok, reasons = validate_plan(_valid_plan(constraints={"buffer_m": 999, "cloud_pct": 10}))
    assert not ok
    assert any("buffer_m" in reason for reason in reasons)


def test_validate_plan_constraints_cloud_pct_range():
    ok, reasons = validate_plan(_valid_plan(constraints={"buffer_m": 100, "cloud_pct": 150}))
    assert not ok
    assert any("cloud_pct" in reason for reason in reasons)


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


def test_allowed_tools_and_request_types():
    assert "geocode_google" in ALLOWED_TOOLS
    assert "compute_mean_ndvi" in ALLOWED_TOOLS
    assert "classify_fuel" in ALLOWED_TOOLS
    assert "address_baseline" in VALID_REQUEST_TYPES
    assert "full_property_assessment" in VALID_REQUEST_TYPES
    assert "incomplete" in VALID_REQUEST_TYPES
    assert "unsupported" in VALID_REQUEST_TYPES
