import json

from src.agent import run_agent, run_planner_only


def test_run_agent_returns_structured_output():
    out = run_agent("Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca")
    assert "plan" in out
    assert "tool_args" in out
    assert "validation" in out
    assert "execution" in out
    assert "final_response" in out


def test_run_agent_executes_with_fallbacks():
    out = run_agent("Assess my property")
    assert "validation" in out
    assert "execution" in out
    # "Assess my property" has no address/digits → fallback marks incomplete → no execution
    if out["execution"]:
        assert out["execution"].get("fuel_class") in {
            "No Data",
            "High Vegetation (High Fuel Load)",
            "Moderate Vegetation",
            "Sparse Vegetation",
            "Minimal Vegetation",
        }
    else:
        assert "plan" in out
        assert out["plan"].get("execution_ready") is False or not out["validation"]["passed"]


def test_run_agent_happy_path_with_address():
    # Pass address so planner gets address-only context (needs_geocoding path)
    out = run_agent(
        "Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca",
        address="17825 Woodcrest Dr, Pioneer, Ca",
    )
    assert out["validation"]["passed"] is True
    assert out["execution"]
    assert "address" in out["execution"]
    assert "fuel_class" in out["execution"]
    assert "mean_ndvi" in out["execution"]


def test_run_agent_with_provided_coordinates_skips_geocoding():
    out = run_agent(
        "Assess wildfire risk for 17825 Woodcrest Dr, Pioneer, Ca",
        address="17825 Woodcrest Dr, Pioneer, Ca",
        lat=38.4655752,
        lng=-120.5584229,
    )
    assert out["validation"]["passed"] is True
    assert out["execution"]
    assert out["execution"]["latitude"] == 38.4655752
    assert out["execution"]["longitude"] == -120.5584229
    assert out["execution"].get("evidence", {}).get("geocode", {}).get("source") == "provided"


def test_run_planner_only_with_provided_coordinates_skips_geocode_step():
    context = {
        "user_request": "Assess fire risk for 17825 Woodcrest Dr, Pioneer, Ca",
        "provided_address": "17825 Woodcrest Dr, Pioneer, Ca",
        "provided_coordinates": {"lat": 38.4655752, "lng": -120.5584229},
        "source": "google_places_selection",
    }
    plan = run_planner_only(json.dumps(context))
    loc = plan.get("location_strategy") or {}
    assert loc.get("use_provided_coordinates") is True
    assert loc.get("needs_geocoding") is False
    tools_in_steps = [s.get("tool") for s in (plan.get("steps") or []) if s.get("tool")]
    assert "geocode_google" not in tools_in_steps


def test_run_planner_only_address_only_requires_geocoding():
    context = {
        "user_request": "Assess fire risk for 17825 Woodcrest Dr, Pioneer, Ca",
        "provided_address": "17825 Woodcrest Dr, Pioneer, Ca",
        "provided_coordinates": None,
        "source": "address_only",
    }
    plan = run_planner_only(json.dumps(context))
    loc = plan.get("location_strategy") or {}
    assert loc.get("needs_geocoding") is True
    tools_in_steps = [s.get("tool") for s in (plan.get("steps") or []) if s.get("tool")]
    assert "geocode_google" in tools_in_steps


def test_run_planner_only_returns_structured_spec():
    plan = run_planner_only("Assess wildfire risk for 123 Main St, City, CA")
    assert "request_type" in plan
    assert plan["request_type"] in {"address_baseline", "full_property_assessment", "incomplete", "unsupported"}
    assert "assessment_mode" in plan
    assert "execution_ready" in plan
    assert "steps" in plan
    assert "planner_summary" in plan


def test_run_planner_only_incomplete_request():
    plan = run_planner_only("Tell me about wildfires")
    assert "request_type" in plan
    assert plan["request_type"] in {"incomplete", "unsupported", "address_baseline", "full_property_assessment"}
    assert "planner_summary" in plan


def test_plan_has_allowed_tools_only():
    plan = run_planner_only("Assess fire risk for 456 Oak Ave, Town, CA")
    allowed = {"geocode_google", "compute_mean_ndvi", "classify_fuel"}
    for step in plan.get("steps") or []:
        tool = step.get("tool")
        if tool:
            assert tool in allowed, f"step uses disallowed tool: {tool}"
