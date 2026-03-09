import json

from src.agent import run_planner_only


def _tools(plan):
    return [s.get("tool") for s in (plan.get("steps") or []) if isinstance(s, dict) and s.get("tool")]


def test_scenario_a_ca_address_baseline_free_tier():
    context = {
        "user_request": "Assess wildfire risk for 48978 River Park Rd, Oakhurst, CA",
        "provided_address": "48978 River Park Rd, Oakhurst, CA",
        "provided_coordinates": None,
        "source": "address_only",
        "assessment_preference": "baseline_free_tier",
    }
    plan = run_planner_only(json.dumps(context))
    assert plan["request_type"] == "baseline_free_tier"
    assert plan["execution_ready"] is True
    tools = _tools(plan)
    assert tools[0] == "resolve_location"
    assert "generate_baseline_report" in tools
    for disallowed in (
        "compute_property_ndvi",
        "classify_property_fuel",
        "analyze_property_slope",
        "analyze_vegetation_proximity",
        "analyze_uploaded_structure_photos",
        "generate_calfire_aligned_recommendations",
        "generate_full_report",
    ):
        assert disallowed not in tools


def test_scenario_b_coords_baseline_free_tier_no_resolve_location():
    context = {
        "user_request": "Assess wildfire risk near these coordinates in CA",
        "provided_address": None,
        "provided_coordinates": {"lat": 38.4655752, "lng": -120.5584229},
        "source": "provided_coordinates",
        "assessment_preference": "baseline_free_tier",
    }
    plan = run_planner_only(json.dumps(context))
    assert plan["request_type"] == "baseline_free_tier"
    assert plan["execution_ready"] is True
    tools = _tools(plan)
    assert "resolve_location" not in tools
    assert "generate_baseline_report" in tools


def test_scenario_c_ca_address_full_paid_tier_no_photos():
    context = {
        "user_request": "Full defensible-space assessment for 48978 River Park Rd, Oakhurst, CA",
        "provided_address": "48978 River Park Rd, Oakhurst, CA",
        "provided_coordinates": None,
        "source": "address_only",
        "assessment_preference": "full_paid_tier",
        "uploaded_photos_present": False,
    }
    plan = run_planner_only(json.dumps(context))
    assert plan["request_type"] == "full_paid_tier"
    assert plan["execution_ready"] is True
    tools = _tools(plan)
    assert tools[0] == "resolve_location"
    assert "generate_full_report" == tools[-1]
    assert "analyze_uploaded_structure_photos" not in tools
    # Full tier must include baseline context + property steps
    for required in (
        "validate_california_scope",
        "gather_hazard_context",
        "gather_terrain_context",
        "gather_regional_vegetation_context",
        "compute_property_ndvi",
        "classify_property_fuel",
        "analyze_property_slope",
        "analyze_vegetation_proximity",
        "generate_calfire_aligned_recommendations",
        "generate_full_report",
    ):
        assert required in tools


def test_scenario_d_full_paid_tier_with_photos_includes_photo_step():
    context = {
        "user_request": "Full defensible-space assessment for 48978 River Park Rd, Oakhurst, CA",
        "provided_address": "48978 River Park Rd, Oakhurst, CA",
        "provided_coordinates": None,
        "source": "address_only",
        "assessment_preference": "full_paid_tier",
        "uploaded_photos_present": True,
        "uploaded_photos_count": 2,
    }
    plan = run_planner_only(json.dumps(context))
    tools = _tools(plan)
    assert plan["request_type"] == "full_paid_tier"
    assert plan["execution_ready"] is True
    assert "analyze_uploaded_structure_photos" in tools
    assert tools.index("generate_calfire_aligned_recommendations") > tools.index("analyze_uploaded_structure_photos")


def test_scenario_e_missing_location_incomplete():
    context = {
        "user_request": "I want a full defensible-space assessment for my property",
        "provided_address": None,
        "provided_coordinates": None,
        "source": "request_only",
        "assessment_preference": "full_paid_tier",
    }
    plan = run_planner_only(json.dumps(context))
    assert plan["request_type"] == "incomplete"
    assert plan["execution_ready"] is False
    assert plan.get("steps") == []


def test_scenario_f_out_of_california_unsupported():
    context = {
        "user_request": "Assess wildfire risk for 123 Main St, Austin, TX",
        "provided_address": "123 Main St, Austin, TX",
        "provided_coordinates": None,
        "source": "address_only",
        "assessment_preference": "baseline_free_tier",
    }
    plan = run_planner_only(json.dumps(context))
    assert plan["request_type"] == "unsupported"
    assert plan["execution_ready"] is False


def test_scenario_g_general_wildfire_question_unsupported():
    context = {
        "user_request": "What causes wildfires?",
        "provided_address": None,
        "provided_coordinates": None,
        "source": "request_only",
    }
    plan = run_planner_only(json.dumps(context))
    assert plan["request_type"] == "unsupported"
    assert plan["execution_ready"] is False

