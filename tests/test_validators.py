from src.validators import (
    ALLOWED_TOOLS,
    VALID_ASSESSMENT_MODES,
    VALID_REQUEST_TYPES,
    validate_coordinates,
    validate_plan,
    validate_tool_args,
)


def _valid_plan(**overrides):
    base = {
        "request_type": "baseline_free_tier",
        "assessment_mode": "address_level_baseline",
        "domain": "wildfire_defensible_space",
        "user_goal": "Assess home",
        "execution_ready": True,
        "missing_requirements": [],
        "location_strategy": {"use_provided_coordinates": False, "needs_geocoding": True},
        "analysis_modules": [
            "location_resolution",
            "california_scope_validation",
            "hazard_context_analysis",
            "terrain_context_analysis",
            "regional_vegetation_analysis",
            "baseline_report_synthesis",
        ],
        "steps": [
            {"step_id": 1, "objective": "Resolve location", "tool": "resolve_location", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Validate CA scope", "tool": "validate_california_scope", "depends_on": [1], "required": True},
            {"step_id": 3, "objective": "Hazard context", "tool": "gather_hazard_context", "depends_on": [2], "required": True},
            {"step_id": 4, "objective": "Terrain context", "tool": "gather_terrain_context", "depends_on": [3], "required": True},
            {"step_id": 5, "objective": "Regional vegetation", "tool": "gather_regional_vegetation_context", "depends_on": [4], "required": True},
            {"step_id": 6, "objective": "Baseline report", "tool": "generate_baseline_report", "depends_on": [5], "required": True},
        ],
        "constraints": {"buffer_m": 120, "cloud_pct": 20},
        "recommended_next_action": "Resolve the property location and gather California baseline context.",
        "planner_summary": "Baseline plan for a California address-level wildfire overview.",
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
            steps=[{"step_id": 1, "objective": "Hack", "tool": "os.system", "depends_on": [], "required": True}],
            analysis_modules=[],
        )
    )
    assert not ok
    assert any("disallowed" in reason for reason in reasons)


def test_validate_plan_requires_request_type():
    ok, reasons = validate_plan(
        {
            "assessment_mode": "address_level_baseline",
            "domain": "wildfire_defensible_space",
            "user_goal": "x",
            "execution_ready": True,
            "missing_requirements": [],
            "location_strategy": {"use_provided_coordinates": False, "needs_geocoding": True},
            "analysis_modules": [],
            "steps": [{"step_id": 1, "objective": "x", "tool": "resolve_location", "depends_on": [], "required": True}],
            "constraints": {"buffer_m": 120, "cloud_pct": 20},
            "recommended_next_action": "x",
            "planner_summary": "x",
        }
    )
    assert not ok
    assert any("missing" in reason and "request_type" in reason for reason in reasons)


def test_validate_plan_invalid_request_type():
    ok, reasons = validate_plan(_valid_plan(request_type="invalid_type"))
    assert not ok
    assert any("request_type" in reason for reason in reasons)


def test_validate_plan_execution_ready_false_when_incomplete():
    ok, reasons = validate_plan(
        _valid_plan(
            request_type="incomplete",
            assessment_mode="incomplete_request",
            execution_ready=True,
            missing_requirements=["California property address or coordinates required"],
            steps=[],
            location_strategy={"use_provided_coordinates": False, "needs_geocoding": False},
        )
    )
    assert not ok
    assert any("execution_ready" in reason for reason in reasons)


def test_validate_plan_execution_ready_false_when_unsupported():
    ok, reasons = validate_plan(
        _valid_plan(
            request_type="unsupported",
            assessment_mode="unsupported_request",
            execution_ready=True,
            missing_requirements=["Unsupported"],
            steps=[],
            location_strategy={"use_provided_coordinates": False, "needs_geocoding": False},
        )
    )
    assert not ok
    assert any("execution_ready" in reason for reason in reasons)


def test_validate_plan_dependency_order():
    # step 2 depends on 3 but 3 comes after 2 in list
    ok, reasons = validate_plan(
        _valid_plan(
            steps=[
                {"step_id": 1, "objective": "A", "tool": "resolve_location", "depends_on": [], "required": True},
                {"step_id": 2, "objective": "B", "tool": "validate_california_scope", "depends_on": [3], "required": True},
                {"step_id": 3, "objective": "C", "tool": "gather_hazard_context", "depends_on": [1], "required": True},
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
    ok, reasons = validate_tool_args(
        {"address": "x", "buffer_m": 999, "start": "a", "end": "b", "cloud_pct": 120},
        plan=_valid_plan(request_type="full_paid_tier", assessment_mode="property_level_environmental_assessment", steps=[
            {"step_id": 1, "objective": "Resolve location", "tool": "resolve_location", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Validate CA scope", "tool": "validate_california_scope", "depends_on": [1], "required": True},
            {"step_id": 3, "objective": "NDVI", "tool": "compute_property_ndvi", "depends_on": [2], "required": True},
        ], analysis_modules=[
            "location_resolution","california_scope_validation","hazard_context_analysis","terrain_context_analysis","regional_vegetation_analysis",
            "property_vegetation_analysis","fuel_classification","property_slope_analysis","vegetation_proximity_analysis","calfire_recommendation_generation","full_report_synthesis"
        ], recommended_next_action="x", planner_summary="x", constraints={"buffer_m": 120, "cloud_pct": 20})
    )
    assert not ok
    assert len(reasons) >= 2


def test_validate_coordinates():
    ok, _ = validate_coordinates(38.0, -120.0)
    assert ok
    bad, reasons = validate_coordinates(200, -500)
    assert not bad
    assert len(reasons) == 2


def test_allowed_tools_and_request_types():
    assert "resolve_location" in ALLOWED_TOOLS
    assert "compute_property_ndvi" in ALLOWED_TOOLS
    assert "classify_property_fuel" in ALLOWED_TOOLS
    assert "baseline_free_tier" in VALID_REQUEST_TYPES
    assert "full_paid_tier" in VALID_REQUEST_TYPES
    assert "incomplete" in VALID_REQUEST_TYPES
    assert "unsupported" in VALID_REQUEST_TYPES
    assert "address_level_baseline" in VALID_ASSESSMENT_MODES
    assert "property_level_environmental_assessment" in VALID_ASSESSMENT_MODES


def test_validate_plan_use_provided_coordinates_requires_context():
    plan = _valid_plan(
        location_strategy={"use_provided_coordinates": True, "needs_geocoding": False},
        steps=[
            {"step_id": 1, "objective": "Validate CA scope", "tool": "validate_california_scope", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Hazard", "tool": "gather_hazard_context", "depends_on": [1], "required": True},
            {"step_id": 3, "objective": "Terrain", "tool": "gather_terrain_context", "depends_on": [2], "required": True},
            {"step_id": 4, "objective": "Vegetation", "tool": "gather_regional_vegetation_context", "depends_on": [3], "required": True},
            {"step_id": 5, "objective": "Report", "tool": "generate_baseline_report", "depends_on": [4], "required": True},
        ],
    )
    ok, reasons = validate_plan(plan, provided_lat=None, provided_lng=None)
    assert not ok
    assert any("no coordinates were supplied" in reason for reason in reasons)


def test_validate_plan_use_provided_coordinates_with_context_passes():
    plan = _valid_plan(
        location_strategy={"use_provided_coordinates": True, "needs_geocoding": False},
        steps=[
            {"step_id": 1, "objective": "Validate CA scope", "tool": "validate_california_scope", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Hazard", "tool": "gather_hazard_context", "depends_on": [1], "required": True},
            {"step_id": 3, "objective": "Terrain", "tool": "gather_terrain_context", "depends_on": [2], "required": True},
            {"step_id": 4, "objective": "Vegetation", "tool": "gather_regional_vegetation_context", "depends_on": [3], "required": True},
            {"step_id": 5, "objective": "Report", "tool": "generate_baseline_report", "depends_on": [4], "required": True},
        ],
    )
    ok, reasons = validate_plan(plan, provided_lat=38.4, provided_lng=-120.5)
    assert ok
    assert reasons == []


def test_validate_plan_use_provided_with_geocode_step_invalid():
    plan = _valid_plan(
        location_strategy={"use_provided_coordinates": True, "needs_geocoding": False},
        steps=[
            {"step_id": 1, "objective": "Resolve", "tool": "resolve_location", "depends_on": [], "required": True},
            {"step_id": 2, "objective": "Validate CA", "tool": "validate_california_scope", "depends_on": [1], "required": True},
        ],
    )
    ok, reasons = validate_plan(plan, provided_lat=38.4, provided_lng=-120.5)
    assert not ok
    assert any("resolve_location" in reason and "redundant" in reason for reason in reasons)
